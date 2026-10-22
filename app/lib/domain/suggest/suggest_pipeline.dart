import 'dart:async';
import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import '../../data/db/database.dart';
import '../model/enums.dart';
import '../ocr/ocr_engine.dart';
import '../ocr/ocr_text_extractor.dart';
import '../search/code_matcher.dart';
import 'group_suggester.dart';
import 'suggest_service.dart';
import 'suggest_thresholds.dart';
/// 建议管道（§5.3.2 + §5.3.3）：识别 → token 落库 → 组级建议落库。
///
/// ═══════════════════════════════════════════════════════════════
/// 职责边界（架构承诺，与 [AssignService] 对偶）：
///
///   **本类写 `suggested_item_id / suggestion_conf / suggestion_json /
///   suggest_state / photos.ocr_state / ocr_tokens`，
///   永远不写 `photos.item_id / photo_groups.item_id / state`。**
///
/// 归属仍然只能由 AssignService 写入。
/// ═══════════════════════════════════════════════════════════════
///
/// 可中断续跑（§5.3.3）：进度全部落在 `photos.ocr_state` 上 ——
/// 中断后重跑 [runForProject]，只处理仍为 pending 的照片，
/// 已完成的识别与建议不会重算。
class SuggestPipeline {
  SuggestPipeline({
    required AppDatabase db,
    required OcrTextExtractor extractor,
    SharedPreferences? prefs,
  })  : _db = db,
        _extractor = extractor,
        _prefsOverride = prefs;

  final AppDatabase _db;

  /// OCR 提取器。**可换** —— P4 诉求 4 起，用户可以在设置里
  /// 在「标准识别 / 增强识别」之间切换，切换后由 provider 重建管道。
  ///
  /// ⚠️ 用可变的字段而不是 final：换引擎时不该重建整个管道对象 ——
  /// 管道的其余状态（进度、幂等标记）都落在数据库上，重建是浪费。
  OcrTextExtractor get extractor => _extractor;
  OcrTextExtractor _extractor;

  /// 换引擎（P4 诉求 4）。仅在**没有正在跑的识别**时调用。
  void swapExtractor(OcrTextExtractor next) => _extractor = next;

  /// 用户设置存储。测试注入 mock；运行时首次访问时懒加载默认实例。
  final SharedPreferences? _prefsOverride;
  SharedPreferences? _prefsCache;

  Future<SharedPreferences> get _prefs async =>
      _prefsCache ??= _prefsOverride ?? await SharedPreferences.getInstance();

  // ── 广播进度（P4 · 真机反馈：重试入口需要它）──────────────
  //
  // 页面订阅 [progressStream] 而不是某一次 runForProject 的返回流 ——
  // 这样「重试失败的照片」从设置面板发起时，进度照样推给页面显示。
  // broadcast：多个订阅者（页面 + 未来可能的调试面板）互不影响。
  final StreamController<SuggestProgress> _progressCtrl =
      StreamController<SuggestProgress>.broadcast();

  /// 识别进度的广播流。页面长驻订阅；重跑/重试都会往里推。
  Stream<SuggestProgress> get progressStream => _progressCtrl.stream;

  /// 正在跑的轮次。**防并发**：手动重跑、设置面板的重试与页面进页
  /// 自动跑可能同时到达，两轮并发会互相抢 pending 照片、重复识别。
  bool _running = false;

  /// 排队的下一个项目。一轮在跑时又有人想跑（手动重跑最典型），
  /// **不丢请求** —— 记下项目，当前轮跑完自动接着跑一轮。
  ///
  /// 为什么要排队而不是直接跳过：自动跑（进页补一轮）跳过看似无害，
  /// 但重试入口是**先把 failed 标回 pending 再触发**的 —— 在跑的那轮
  /// 可能已经扫过这些照片，跳过 = 这批照片永远没人处理。
  /// 排队是唯一不丢动作的语义。管道是跨项目单例，所以排队记的是
  /// **项目 id** 而不是一个布尔 —— A 项目跑到一半排进来 B 项目，
  /// 重启的必须是 B 而不是把 A 再跑一遍。
  String? _queuedProjectId;

  void _push(SuggestProgress p) => _progressCtrl.add(p);

  // ═══════════════════════════════════════════════════════════
  // 入口
  // ═══════════════════════════════════════════════════════════

  /// 幂等入口：把项目内 pending 的照片处理掉。
  ///
  /// 页面进页 / 下拉刷新用这个。已在跑时排队 —— 在跑的那轮结束后
  /// 会为本项目再跑一轮（fresh 状态，不会漏掉刚标回 pending 的照片）。
  Future<void> ensurePendingProcessed(String projectId) => _pump(projectId);

  /// 唯一的轮次驱动：空了就跑，不空就排队；排队的轮在其后执行。
  Future<void> _pump(String projectId) async {
    if (_running) {
      _queuedProjectId = projectId;
      return;
    }
    _running = true;
    try {
      var current = projectId;
      while (true) {
        await for (final p in _runForProjectInner(current)) {
          _push(p);
        }
        final next = _queuedProjectId;
        _queuedProjectId = null;
        // ⚠️ next == current 也要再跑一轮：重试入口是「先标回 pending
        //    再触发」的，在跑的那轮可能早已扫过这批照片 ——
        //    只有多跑一轮才能把它们捡回来。
        if (next == null) break;
        current = next;
      }
    } finally {
      _running = false;
      _queuedProjectId = null;
    }
  }

  /// 对项目内所有 `ocr_state = pending` 的照片跑一轮识别 + 组级合成，
  /// 进度以流返回（本方法不广播 —— 广播由 [_pump] 负责）。
  ///
  /// 每张照片完成后发一次进度；一组合成完成后发一次带组统计的进度。
  /// **单张失败不终止管道**（该张标 failed，继续下一张）——
  /// 现场几百张里混几张坏图是常态，管道必须像流水线一样走完。
  ///
  /// ⚠️ 页面代码请用 [ensurePendingProcessed]（广播进度 + 防并发）；
  ///    本方法保留为底层原语（测试 / 需要精确消费单轮进度时用）。
  Stream<SuggestProgress> runForProject(String projectId) =>
      _runForProjectInner(projectId);

  Stream<SuggestProgress> _runForProjectInner(String projectId) async* {
    // OCR 被用户关闭 → 立即返回空进度，一张都不识别（§5.3.3）。
    if (await isDisabledByUser) {
      yield const SuggestProgress(
        total: 0,
        done: 0,
        groupsPending: 0,
        groupsConflict: 0,
        groupsNoSuggestion: 0,
      );
      return;
    }

    // 清单编码字典（每个项目一份；清单在作业期不会变）。
    final itemRows = await (_db.select(_db.items)
          ..where((t) => t.projectId.equals(projectId)))
        .get();
    final matcher = CodeMatcher(
      itemRows.map((r) => CodeEntry(itemId: r.id, code: r.code)).toList(),
    );

    final pending = await (_db.select(_db.photos)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.ocrState.equals(OcrState.pending.code)))
        .get();

    var done = 0;
    final total = pending.length;
    if (total == 0) {
      yield const SuggestProgress(
        total: 0,
        done: 0,
        groupsPending: 0,
        groupsConflict: 0,
        groupsNoSuggestion: 0,
      );
      return;
    }

    // 组 id → 该组是否已在本次跑里合成过（一张完成即可触发检查，
    // 但合成条件是组内全部 done，天然只会在最后一张时通过）。
    final synthesized = <String>{};

    for (final photo in pending) {
      // ── 识别单张 ──
      List<OcrTokenResult> tokens;
      var ok = true;
      try {
        tokens = await _extractor.extract(photo.filePath);
      } catch (_) {
        tokens = const [];
        ok = false;
      }

      if (ok) {
        // ⚠️ 先删旧 token 再写新的（与 retryPhoto 同一套规则）——
        // 手动重跑时照片上可能已有旧 token，不删就会新旧叠加，
        // 组级建议会被重复 token 拉扯失真。首跑时删除是空操作。
        await (_db.delete(_db.ocrTokens)
              ..where((t) => t.photoId.equals(photo.id)))
            .go();
        await _storeTokens(photo.id, tokens);
        await _markOcrState(photo.id, OcrState.done);
      } else {
        await _markOcrState(photo.id, OcrState.failed);
      }
      done++;

      // ── 组级合成：仅当照片已入组且组内全部识别完毕 ──
      var groupsPending = 0, groupsConflict = 0, groupsNoSuggestion = 0;
      final gid = photo.groupId;
      if (ok && gid != null && !synthesized.contains(gid)) {
        final ready = await _isGroupFullyDone(gid);
        if (ready) {
          synthesized.add(gid);
          final state = await _synthesizeGroup(gid, matcher);
          switch (state) {
            case GroupSuggestState.pending:
              groupsPending++;
            case GroupSuggestState.conflict:
              groupsConflict++;
            case GroupSuggestState.noSuggestion:
              groupsNoSuggestion++;
            default:
              break;
          }
        }
      }

      yield SuggestProgress(
        total: total,
        done: done,
        groupsPending: groupsPending,
        groupsConflict: groupsConflict,
        groupsNoSuggestion: groupsNoSuggestion,
      );
    }
  }

  /// 单张重试（整理页「重新识别」）。把该张标回 pending 再跑一遍它，
  /// 组内若全部 done 则重合成组建议（覆盖旧建议）。
  Future<void> retryPhoto(String projectId, String photoId) async {
    final rows = await (_db.select(_db.photos)
          ..where((t) => t.id.equals(photoId)))
        .getSingleOrNull();
    if (rows == null) return;

    await _markOcrState(photoId, OcrState.running);
    List<OcrTokenResult> tokens;
    var ok = true;
    try {
      tokens = await _extractor.extract(rows.filePath);
    } catch (_) {
      tokens = const [];
      ok = false;
    }
    if (ok) {
      // 重试 = 旧 token 作废重写，防止残留导致建议失真。
      await (_db.delete(_db.ocrTokens)
            ..where((t) => t.photoId.equals(photoId)))
          .go();
      await _storeTokens(photoId, tokens);
      await _markOcrState(photoId, OcrState.done);
    } else {
      await _markOcrState(photoId, OcrState.failed);
      return;
    }

    final gid = rows.groupId;
    if (gid == null) return;
    if (!await _isGroupFullyDone(gid)) return;
    final itemRows = await (_db.select(_db.items)
          ..where((t) => t.projectId.equals(projectId)))
        .get();
    final matcher = CodeMatcher(
      itemRows.map((r) => CodeEntry(itemId: r.id, code: r.code)).toList(),
    );
    await _synthesizeGroup(gid, matcher);
  }

  /// 把项目内**识别失败**的照片标回 pending 并重跑（P4 · 真机反馈）。
  ///
  /// ═════════════════════════════════════════════════════════════
  /// 为什么要它：[runForProject] 只处理 pending，失败的照片会被
  /// 永久跳过 —— 而 ML Kit / 引擎装配失败时**一整批都会失败**。
  /// 旧版没有任何恢复入口：用户在设置里换了引擎（比如从标准换到
  /// 增强识别），那些 failed 的照片也不会被重试，只能干瞪眼。
  ///
  /// 返回重试的照片数（0 = 没有失败照片，UI 据此隐藏重试按钮）。
  /// 重跑经 [_pump]，进度照常广播到页面；撞上正在跑的一轮会排队。
  /// ═════════════════════════════════════════════════════════════
  Future<int> retryFailedPhotos(String projectId) async {
    final failed = await (_db.select(_db.photos)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.ocrState.equals(OcrState.failed.code)))
        .get();
    if (failed.isEmpty) return 0;

    await (_db.update(_db.photos)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.ocrState.equals(OcrState.failed.code)))
        .write(PhotosCompanion(ocrState: Value(OcrState.pending.code)));

    // 重跑一轮（不 await —— 进度经广播流推给页面，面板不等它）。
    // _pump 保证与页面进页自动跑互斥；撞锁则排队续跑，不丢请求。
    unawaited(_pump(projectId));
    return failed.length;
  }

  /// 重新识别**一组**（P4 · 老板诉求「支持手动重新 OCR」）。
  ///
  /// 场景：识别给的建议不对 / 没给出建议，用户想用现在装配的引擎
  /// 再试一遍这一组。动作：
  ///   ① 组内照片全部标回 pending（不管之前是 done 还是 failed）；
  ///   ② 清掉本组的旧建议（suggested_item_id / conf / json）——
  ///      不清的话，重跑完成前 UI 会继续展示一条已经作废的建议；
  ///   ③ 排一轮识别，跑完自动重合成组建议。
  ///
  /// 返回重跑的照片数（0 = 组里没照片 / 组不存在）。
  ///
  /// ⚠️ 只动建议字段，**不碰 itemId / state** —— 就算这组已经指派过，
  ///    重跑识别也不会动归属（撤销归属是 AssignService.revokeGroup 的事）。
  Future<int> rerunGroup(String projectId, String groupId) async {
    final n = await (_db.update(_db.photos)
          ..where((t) => t.groupId.equals(groupId)))
        .write(PhotosCompanion(ocrState: Value(OcrState.pending.code)));
    if (n == 0) return 0;

    await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
        .write(const PhotoGroupsCompanion(
      suggestedItemId: Value(null),
      suggestionConf: Value(null),
      suggestionJson: Value(null),
      suggestState: Value('pending'), // 表默认值 = 尚未处理
    ));

    unawaited(_pump(projectId));
    return n;
  }

  /// 重新识别**整个项目**（P4 · 老板诉求「支持手动重新 OCR」）。
  ///
  /// 场景：引擎从标准切到增强（或刚装好模型）后，想把所有照片
  /// 用新引擎重跑一遍 —— 旧结果全部作废。
  ///
  /// [includeAssigned]：
  ///  · `false`（默认）只重跑**未归属**的照片 —— 已指派的组是"人确认过的"，
  ///    重跑它们的建议没有业务意义，还可能在重跑完成前让已确认的页面
  ///    显示出与归属不一致的建议。
  ///  · `true` 连已指派的一起重跑（识别数据全量刷新；归属仍然不动）。
  ///
  /// 返回重跑的照片数（0 = 没有可重跑的照片）。
  Future<int> rerunProject(
    String projectId, {
    bool includeAssigned = false,
  }) async {
    final affected = await (_db.update(_db.photos)
          ..where((t) => includeAssigned
              ? t.projectId.equals(projectId)
              : t.projectId.equals(projectId) & t.itemId.isNull()))
        .write(PhotosCompanion(ocrState: Value(OcrState.pending.code)));
    if (affected == 0) return 0;

    // 未归属组的旧建议一并作废（重跑后重合成）。
    await (_db.update(_db.photoGroups)
          ..where((t) => t.projectId.equals(projectId) & t.itemId.isNull()))
        .write(const PhotoGroupsCompanion(
      suggestedItemId: Value(null),
      suggestionConf: Value(null),
      suggestionJson: Value(null),
      suggestState: Value('pending'),
    ));

    unawaited(_pump(projectId));
    return affected;
  }

  // ───────────────────────────────────────────────────────────
  // 内部
  // ───────────────────────────────────────────────────────────

  Future<void> _storeTokens(String photoId, List<OcrTokenResult> tokens) async {
    if (tokens.isEmpty) return;
    await _db.batch((b) {
      b.insertAll(
        _db.ocrTokens,
        tokens
            .map((t) => OcrTokensCompanion.insert(
                  id: _newId(),
                  photoId: photoId,
                  rawText: t.text,
                  confidence: t.ocrConf,
                  boxJson: jsonEncode({'cx': t.normCx, 'cy': t.normCy}),
                ))
            .toList(),
      );
    });
  }

  Future<void> _markOcrState(String photoId, OcrState state) async {
    await (_db.update(_db.photos)..where((t) => t.id.equals(photoId)))
        .write(PhotosCompanion(ocrState: Value(state.code)));
  }

  /// 组内是否所有照片都已识别完成（done 或 skipped 视为完成）。
  Future<bool> _isGroupFullyDone(String groupId) async {
    final notDone = await (_db.select(_db.photos)
          ..where((t) =>
              t.groupId.equals(groupId) &
              t.ocrState.isNotIn([
                OcrState.done.code,
                OcrState.skipped.code,
              ])))
        .get();
    return notDone.isEmpty;
  }

  /// 合成组建议并写库。返回写入的状态（供进度统计）。
  Future<GroupSuggestState> _synthesizeGroup(
    String groupId,
    CodeMatcher matcher,
  ) async {
    final photos = await (_db.select(_db.photos)
          ..where((t) => t.groupId.equals(groupId))
          ..orderBy([(t) => OrderingTerm.asc(t.seq)]))
        .get();

    final inputs = <PhotoTokens>[];
    for (final p in photos) {
      final tokenRows = await (_db.select(_db.ocrTokens)
            ..where((t) => t.photoId.equals(p.id)))
          .get();
      inputs.add(PhotoTokens(
        photoId: p.id,
        tokens: tokenRows.map((t) {
          var w = 1.0;
          try {
            final box = jsonDecode(t.boxJson) as Map<String, Object?>;
            w = SuggestWeights.positionWeight(
              cx: (box['cx'] as num?)?.toDouble() ?? 0.5,
              cy: (box['cy'] as num?)?.toDouble() ?? 0.5,
            );
          } catch (_) {
            // box 解析失败 → 1.0（未知不打折）。
          }
          return SuggestToken(
            text: t.rawText,
            ocrConf: t.confidence,
            positionWeight: w,
          );
        }).toList(),
      ));
    }

    final suggestion = GroupSuggester.suggest(photos: inputs, matcher: matcher);

    // ⚠️ 幂等标记：suggestionJson **必写**（包括 no_suggestion）——
    // 「M4 管道处理过这个组」的判据就是 suggestionJson != null，
    // 中断后续跑不会重复合成，UI 也不用跟 suggestState 的默认值打架。
    await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
        .write(PhotoGroupsCompanion(
      suggestedItemId: Value(suggestion.itemId),
      suggestionConf: Value(suggestion.confidence),
      suggestionJson: Value(jsonEncode(suggestion.toJson())),
      suggestState: Value(suggestion.state),
    ));

    return GroupSuggestState.fromCode(suggestion.state);
  }

  // ───────────────────────────────────────────────────────────
  // 用户开关（§5.3.3：OCR 可整体关闭，其余流程零变化）
  // ───────────────────────────────────────────────────────────

  static const _kOcrDisabled = 'suggest.ocr_disabled';

  /// 用户选择的 OCR 引擎（P4 诉求 4）。存 [OcrEngine.code]。
  static const _kOcrEngine = 'suggest.ocr_engine';

  /// 用户是否在设置里关掉了 OCR 建议。
  Future<bool> get isDisabledByUser async =>
      (await _prefs).getBool(_kOcrDisabled) ?? false;

  /// 用户选的 OCR 引擎。默认 ML Kit —— 它随 APK 分发、零额外体积、
  /// 没有"第一次用才发现不可用"的风险，是稳妥的默认值。
  Future<OcrEngine> get preferredEngine async =>
      OcrEngine.fromCode((await _prefs).getString(_kOcrEngine));

  /// 记录用户选的引擎。
  ///
  /// ⚠️ 这个方法**只写偏好，不装配引擎** —— 装配由 provider 层做。
  ///    分开是因为装配是 async 且可能失败（要探测原生侧），
  ///    而写偏好必须成功。把两件事混在一起会让"设置没保存"变成一个
  ///    可能结果，而它不该是。
  Future<void> setPreferredEngine(OcrEngine engine) async {
    await (await _prefs).setString(_kOcrEngine, engine.code);
  }

  /// 关闭/开启建议功能。
  ///
  /// 关闭：把**未归属组**的 suggest_state 置为 none —— UI 立即收起建议条。
  /// **suggestionJson 一律保留**，它是恢复源，绝不清空 ——
  /// 避免用户来回切一次就丢掉十几分钟的识别结果（§5.3.3 原文语义）。
  ///
  /// 开启：从 suggestionJson 把原状态（pending / no_suggestion / conflict）
  /// 恢复回 suggest_state —— 立即恢复显示，无需重新识别。
  ///
  /// 只动 suggest_state 一个字段：suggested_item_id / suggestion_conf /
  /// ocr_tokens / photos.ocr_state 全部原样，识别数据永远无损。
  Future<void> setDisabledByUser(bool disabled) async {
    final prefs = await _prefs;
    await prefs.setBool(_kOcrDisabled, disabled);

    if (disabled) {
      await (_db.update(_db.photoGroups)
            ..where((t) => t.itemId.isNull()))
          .write(PhotoGroupsCompanion(
        suggestState: Value(GroupSuggestState.none.code),
      ));
      return;
    }

    // 恢复：管道处理过（suggestionJson 非空）的未归属组，按 JSON 原始状态还原。
    final rows = await (_db.select(_db.photoGroups)
          ..where((t) =>
              t.itemId.isNull() & t.suggestionJson.isNotNull()))
        .get();
    for (final r in rows) {
      final Object? state;
      try {
        final decoded = jsonDecode(r.suggestionJson!);
        state = decoded is Map<String, Object?> ? decoded['state'] : null;
      } catch (_) {
        continue; // 坏 JSON 不阻塞其余组的恢复。
      }
      if (state is! String) continue;
      await (_db.update(_db.photoGroups)..where((t) => t.id.equals(r.id)))
          .write(PhotoGroupsCompanion(suggestState: Value(state)));
    }
  }

  static const _uuid = Uuid();

  String _newId() => _uuid.v4();
}
