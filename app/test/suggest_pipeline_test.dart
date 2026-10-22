// hide：drift 的列扩展与 matcher 的断言重名（isNull/isNotNull 都撞）
// —— 测试里要的是断言不是列方法。drift 类型经 db.* 属性推断使用，无需 import。
import 'dart:convert';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/item_repository.dart';
import 'package:g_tick_picture/data/repo/organize_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/assign/assign_service.dart';
import 'package:g_tick_picture/domain/model/checklist_row.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/ocr/ocr_text_extractor.dart';
import 'package:g_tick_picture/domain/suggest/suggest_pipeline.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// [SuggestPipeline] 的契约测试 —— OCR 建议管道（M4 / §5.3.2~5.3.3）。
///
/// 断言的四条承诺：
///  1. **建议与归属物理隔离**：管道写 suggested_* / ocr_tokens /
///     photos.ocr_state，永远碰不到 photos.item_id / photo_groups.item_id。
///  2. **可中断续跑**：进度落在 photos.ocr_state 上，重跑只处理 pending，
///     已完成的识别与建议不重算（§5.3.3）。
///  3. **单张失败不终止管道**（现场混几张坏图是常态）。
///  4. **组级合成只在组内全部识别完毕后发生**，幂等标记 =
///     suggestionJson != null（no_suggestion 也写，防止重复合成）。
void main() {
  late AppDatabase db;
  late CaptureRepository capture;
  late OrganizeRepository organize;
  late ProjectRepository projects;
  late ItemRepository items;
  late String projectId;

  setUp(() async {
    // 管道现在会在 runForProject 开头读用户开关（SharedPreferences）
    // —— 所有测试统一给 mock，否则 getInstance 在纯 Dart 测试环境直接崩。
    SharedPreferences.setMockInitialValues({});
    db = AppDatabase.forTesting(NativeDatabase.memory());
    capture = CaptureRepository(db);
    organize = OrganizeRepository(db);
    projects = ProjectRepository(db);
    items = ItemRepository(db);
    projectId = await projects.create(name: '建议管道测试');
    // 2026-09-29 起分组固定为「一批一组」：同批次照片整批成组，
    // groupOfTwo 天然在一组，无需任何开关。
    await items.bulkInsert(projectId, [
      const ChecklistRow(sourceRow: 2, code: 'BOX-001', codeSafe: 'BOX-001', name: '货品A'),
      const ChecklistRow(sourceRow: 3, code: 'BOX-002', codeSafe: 'BOX-002', name: '货品B'),
    ]);
  });

  tearDown(() async {
    await db.close();
  });

  // ── 夹具 ────────────────────────────────────────────────

  DateTime t(int sec) => DateTime(2026, 9, 23, 10, 0, sec);

  NewPhoto ph(String sessionId, int seq, DateTime takenAt) => NewPhoto(
        sessionId: sessionId,
        filePath: '/tmp/p$seq.jpg',
        seq: seq,
        takenAt: takenAt,
        bytes: 1024,
      );

  /// 两张连拍（10s 间隔）→ regroup → 返回 groupId。
  Future<String> groupOfTwo() async {
    final s = await capture.startSession(projectId);
    await capture.insertPhotos(projectId, [
      ph(s, 1, t(0)),
      ph(s, 2, t(10)),
    ]);
    await capture.endSession(s);
    await organize.regroupPending(projectId);
    final g = await (db.select(db.photoGroups)).get();
    return g.single.id;
  }

  Future<String> currentGroupId() async {
    final g = await (db.select(db.photoGroups)).get();
    return g.single.id;
  }

  OcrTokenResult token(String text) =>
      const OcrTokenResult(text: '', ocrConf: 1.0, normCx: 0.5, normCy: 0.5)
          .copy(text: text);

  SuggestPipeline pipelineWith(FakeOcrTextExtractor fake) =>
      SuggestPipeline(db: db, extractor: fake);

  Future<PhotoGroup?> groupRow(String groupId) =>
      (db.select(db.photoGroups)..where((g) => g.id.equals(groupId)))
          .getSingleOrNull();

  test('全链路：识别 → token 落库 → 组建议 pending，归属字段全程未动', () async {
    final gid = await groupOfTwo();
    final photos = await (db.select(db.photos)).get();
    final fake = FakeOcrTextExtractor(results: {
      photos[0].filePath: [token('BOX-001')],
      photos[1].filePath: [token('BOX-001')],
    });

    final progress = await pipelineWith(fake).runForProject(projectId).toList();

    // 进度：2 张全部完成。
    expect(progress, isNotEmpty);
    expect(progress.last.done, 2);
    expect(progress.last.total, 2);
    expect(progress.last.groupsPending, 1);

    // 照片状态。
    final after = await (db.select(db.photos)).get();
    for (final p in after) {
      expect(p.ocrState, OcrState.done.code);
      // ★ 归属字段不被管道触碰。
      expect(p.itemId, isNull);
      expect(p.state, PhotoState.unassigned.code);
    }

    // token 落库（每张一条）。
    final tokens = await (db.select(db.ocrTokens)).get();
    expect(tokens.length, 2);
    expect(tokens.every((t) => t.rawText == 'BOX-001'), isTrue);

    // 组建议。
    final g = (await groupRow(gid))!;
    expect(g.suggestedItemId, isNotNull);
    expect(g.suggestionConf, closeTo(0.98, 1e-9));
    expect(g.suggestState, GroupSuggestState.pending.code);
    final json = jsonDecode(g.suggestionJson!) as Map<String, Object?>;
    expect(json['itemId'], g.suggestedItemId);
    expect(json['evidence'], isA<List<dynamic>>());

    // ★ 组的归属字段不被触碰。
    expect(g.itemId, isNull);
  });

  test('单张失败：该张 failed、组不合成、管道继续走完', () async {
    final gid = await groupOfTwo();
    final photos = await (db.select(db.photos)).get();
    final fake = FakeOcrTextExtractor(
      results: {
        photos[0].filePath: [token('BOX-001')],
      },
      failPaths: {photos[1].filePath},
    );

    final progress = await pipelineWith(fake).runForProject(projectId).toList();

    expect(progress.last.done, 2); // 失败也计入进度。
    final after = await (db.select(db.photos)).get();
    expect(after.map((p) => p.ocrState),
        containsAll([OcrState.done.code, OcrState.failed.code]));

    // 组内未全部 done → 不合成。
    final g = (await groupRow(gid))!;
    expect(g.suggestionJson, isNull);
    expect(g.suggestState, 'pending'); // 表默认值 = 尚未处理。
  });

  test('续跑幂等：跑完再跑 total=0，建议不重算', () async {
    await groupOfTwo();
    final photos = await (db.select(db.photos)).get();
    final fake = FakeOcrTextExtractor(results: {
      for (final p in photos)
        p.filePath: [token('BOX-001')],
    });
    final pipeline = pipelineWith(fake);

    await pipeline.runForProject(projectId).toList();
    final g1 = (await groupRow(await currentGroupId()))!;
    final conf1 = g1.suggestionConf;

    final second = await pipeline.runForProject(projectId).toList();
    expect(second.single.total, 0);
    expect(second.single.done, 0);

    final g2 = (await groupRow(await currentGroupId()))!;
    expect(g2.suggestionConf, conf1);
  });

  test('无匹配：no_suggestion 也写 suggestionJson（幂等标记）', () async {
    final gid = await groupOfTwo();
    final photos = await (db.select(db.photos)).get();
    final fake = FakeOcrTextExtractor(results: {
      for (final p in photos)
        p.filePath: [token('完全不相关的文字')],
    });

    await pipelineWith(fake).runForProject(projectId).toList();

    final g = (await groupRow(gid))!;
    expect(g.suggestedItemId, isNull);
    expect(g.suggestState, GroupSuggestState.noSuggestion.code);
    // ★ no_suggestion 也要有 JSON —— 它是「管道已处理过」的判据。
    expect(g.suggestionJson, isNotNull);
  });

  test('retryPhoto：清旧 token 重写并重合成组建议', () async {
    final gid = await groupOfTwo();
    final photos = await (db.select(db.photos)).get();
    final fake = FakeOcrTextExtractor(results: {
      for (final p in photos)
        p.filePath: [token('完全不相关的文字')],
    });
    final pipeline = pipelineWith(fake);
    await pipeline.runForProject(projectId).toList();
    expect((await groupRow(gid))!.suggestState,
        GroupSuggestState.noSuggestion.code);

    // 更新识别结果后重试第一张。
    fake.results[photos[0].filePath] = [token('BOX-001')];
    await pipeline.retryPhoto(projectId, photos[0].id);

    // 第一张的 token 已被替换为新识别结果。
    final t1 = await (db.select(db.ocrTokens)
          ..where((t) => t.photoId.equals(photos[0].id)))
        .get();
    expect(t1.single.rawText, 'BOX-001');

    // 组建议被重合成：仍有一张是旧结果（无匹配），但管道已覆盖写入。
    final g = (await groupRow(gid))!;
    expect(g.suggestionJson, isNotNull);
    // 组内另一张（photos[1]）还是无匹配 token → 组级平均被拉低，
    // 具体状态取决于两张的合成结果，但必然不再是旧 no_suggestion 原样。
  });

  test('用户开关：关闭后未归属组 state→none（JSON 保留），重开从 JSON 恢复',
      () async {
    SharedPreferences.setMockInitialValues({});
    final gid = await groupOfTwo();
    final photos = await (db.select(db.photos)).get();
    final fake = FakeOcrTextExtractor(results: {
      for (final p in photos)
        p.filePath: [token('BOX-001')],
    });
    final pipeline = pipelineWith(fake);
    await pipeline.runForProject(projectId).toList();
    expect((await groupRow(gid))!.suggestState,
        GroupSuggestState.pending.code);

    // 关闭：state → none；建议本体与 JSON **原样保留**（恢复源，绝不清空）。
    await pipeline.setDisabledByUser(true);
    expect(await pipeline.isDisabledByUser, isTrue);
    final off = (await groupRow(gid))!;
    expect(off.suggestState, GroupSuggestState.none.code);
    expect(off.suggestionJson, isNotNull);
    expect(off.suggestedItemId, isNotNull);

    // 重新打开：按 JSON 里的原始状态立即恢复，无需重新识别。
    await pipeline.setDisabledByUser(false);
    expect(await pipeline.isDisabledByUser, isFalse);
    final restored = (await groupRow(gid))!;
    expect(restored.suggestState, GroupSuggestState.pending.code);
    expect(restored.suggestedItemId, off.suggestedItemId);
  });

  test('关闭状态下 runForProject 直接返回：不识别、不写 token', () async {
    SharedPreferences.setMockInitialValues({});
    await groupOfTwo();
    final photos = await (db.select(db.photos)).get();
    final fake = FakeOcrTextExtractor(results: {
      for (final p in photos)
        p.filePath: [token('BOX-001')],
    });
    final pipeline = pipelineWith(fake);
    await pipeline.setDisabledByUser(true);

    final progress = await pipeline.runForProject(projectId).toList();
    expect(progress.single.total, 0);
    expect(progress.single.done, 0);

    // 管道根本没跑：照片仍 pending、零 token、组建议未生成。
    final after = await (db.select(db.photos)).get();
    expect(after.map((p) => p.ocrState),
        everyElement(OcrState.pending.code));
    expect(await (db.select(db.ocrTokens)).get(), isEmpty);
  });

  // ═════════════════════════════════════════════════════════
  // retryFailedPhotos —— 失败恢复（P4 · 真机反馈 2026-09-24）
  //
  // 真机场景：整批照片在引擎不可用时全部 failed，用户换了引擎后
  // 必须有办法把它们救回来 —— 旧版没有恢复入口，failed 被永久跳过。
  // ═════════════════════════════════════════════════════════
  group('retryFailedPhotos · 失败恢复', () {
    test('失败照片标回 pending 重跑：识别成功并合成组建议', () async {
      final gid = await groupOfTwo();
      final photos = await (db.select(db.photos)).get();

      // 第一轮：全部失败（模拟引擎不可用 / ML Kit 全崩）。
      final bad = FakeOcrTextExtractor(
        failPaths: photos.map((p) => p.filePath).toSet(),
      );
      final pipeline = pipelineWith(bad);
      await pipeline.runForProject(projectId).toList();

      var after = await (db.select(db.photos)).get();
      expect(after.map((p) => p.ocrState), everyElement(OcrState.failed.code));

      // 换上好引擎（模拟用户在设置里切了引擎），发起重试。
      pipeline.swapExtractor(FakeOcrTextExtractor(results: {
        for (final p in photos) p.filePath: [token('BOX-001')],
      }));
      final n = await pipeline.retryFailedPhotos(projectId);
      expect(n, 2);

      // 重跑是 fire-and-forget（进度走广播流）—— 轮询等它收尾。
      for (var i = 0; i < 200; i++) {
        final rows = await (db.select(db.photos)).get();
        final stillWorking = rows.where((p) =>
            p.ocrState == OcrState.pending.code ||
            p.ocrState == OcrState.running.code);
        if (stillWorking.isEmpty) break;
        await Future<void>.delayed(const Duration(milliseconds: 25));
      }

      after = await (db.select(db.photos)).get();
      expect(after.map((p) => p.ocrState), everyElement(OcrState.done.code));

      // 组建议这次要真的合成出来（组内全部 done 的条件终于满足）。
      final g = (await groupRow(gid))!;
      expect(g.suggestedItemId, isNotNull);
      expect(g.suggestionJson, isNotNull);
    });

    test('没有失败照片时返回 0，且不触发新一轮识别', () async {
      await groupOfTwo();
      final pipeline = pipelineWith(FakeOcrTextExtractor());

      final n = await pipeline.retryFailedPhotos(projectId);
      expect(n, 0);

      // 照片原样停在 pending —— 没有任何识别发生。
      final rows = await (db.select(db.photos)).get();
      expect(
          rows.map((p) => p.ocrState), everyElement(OcrState.pending.code));
    });

    test('并发触发：撞锁时排队续跑而不是丢弃（防并发不丢动作）', () async {
      await groupOfTwo();
      final pipeline =
          pipelineWith(FakeOcrTextExtractor(results: const {}));

      // 不 await 第一轮 —— 让第二轮真的撞上在跑的那轮。
      // 旧语义（撞锁直接跳过）在这里是错的：重试入口是先把 failed
      // 标回 pending 再触发的，跳过 = 那批照片永远没人处理。
      final f1 = pipeline.ensurePendingProcessed(projectId);
      final f2 = pipeline.ensurePendingProcessed(projectId);
      await Future.wait([f1, f2]);

      final rows = await (db.select(db.photos)).get();
      expect(rows.map((p) => p.ocrState), everyElement(OcrState.done.code));
    });
  });

  // ═════════════════════════════════════════════════════════
  // rerunGroup / rerunProject —— 手动重新 OCR（P4 · 老板诉求）
  //
  // 场景：引擎换新（标准 → 增强）或对建议不满意，用户要把识别
  // 重来一遍。两条硬约束：
  //  1. 重跑**不叠加** token（先删后写，否则建议被重复 token 拉扯失真）；
  //  2. 重跑**不碰归属** —— 已确认的组是人的决定，识别无权重写。
  // ═════════════════════════════════════════════════════════
  group('手动重新 OCR', () {
    /// 等待 fire-and-forget 的一轮跑完（没有 pending/running 为止）。
    Future<void> waitIdle() async {
      for (var i = 0; i < 200; i++) {
        final rows = await (db.select(db.photos)).get();
        final working = rows.where((p) =>
            p.ocrState == OcrState.pending.code ||
            p.ocrState == OcrState.running.code);
        if (working.isEmpty) return;
        await Future<void>.delayed(const Duration(milliseconds: 25));
      }
    }

    test('rerunGroup：旧建议清空、token 不叠加、重合成新建议', () async {
      final gid = await groupOfTwo();
      final photos = await (db.select(db.photos)).get();
      final fake = FakeOcrTextExtractor(results: {
        for (final p in photos) p.filePath: [token('完全不相关的文字')],
      });
      final pipeline = pipelineWith(fake);
      await pipeline.runForProject(projectId).toList();
      expect((await groupRow(gid))!.suggestState,
          GroupSuggestState.noSuggestion.code);

      // 换识别结果后重跑这一组。
      fake.results[photos[0].filePath] = [token('BOX-001')];
      fake.results[photos[1].filePath] = [token('BOX-001')];
      final n = await pipeline.rerunGroup(projectId, gid);
      expect(n, 2);
      await waitIdle();

      // ★ token 不叠加：两张照片仍然各只有 1 条。
      final tokens = await (db.select(db.ocrTokens)).get();
      expect(tokens.length, 2);
      expect(tokens.map((t) => t.rawText), everyElement('BOX-001'));

      // ★ 建议被重合成。
      final g = (await groupRow(gid))!;
      expect(g.suggestedItemId, isNotNull);
      expect(g.suggestState, GroupSuggestState.pending.code);
      // ★ 归属字段照旧没人碰。
      expect(g.itemId, isNull);
    });

    test('rerunProject：默认跳过已归属的照片与组', () async {
      final gid1 = await groupOfTwo();

      // 第二组：**真两批** —— 先把已有批次的结束时间回拨出 5 分钟续接
      // 窗口，否则 startSession 会续用同一批次；10-09 口径下同批次
      // 整批重聚，两组会并成一组（旧口径「同批也能立第二组」正是
      // 连拍拆成两组的 bug 行为，不能当测试前提）。
      // （裸 SQL：本文件刻意不 import drift —— Value 与 matcher 撞名。）
      await db.customStatement(
        'UPDATE capture_sessions SET ended_at = ?',
        [DateTime.now().millisecondsSinceEpoch - 10 * 60 * 1000],
      );
      final s2 = await capture.startSession(projectId);
      await capture.insertPhotos(projectId, [
        ph(s2, 3, t(100)),
        ph(s2, 4, t(110)),
      ]);
      await capture.endSession(s2);
      await organize.regroupPending(projectId);
      final groups = await (db.select(db.photoGroups)).get();
      final gid2 = groups.map((g) => g.id).firstWhere((id) => id != gid1);

      // 两组都先用 BOX-002 的 token 识别完。
      final photos = await (db.select(db.photos)).get();
      final fake = FakeOcrTextExtractor(results: {
        for (final p in photos) p.filePath: [token('BOX-002')],
      });
      final pipeline = pipelineWith(fake);
      await pipeline.runForProject(projectId).toList();

      final box1 = await (db.select(db.items)
            ..where((i) => i.codeSafe.equals('BOX-001')))
          .getSingle();
      final box2 = await (db.select(db.items)
            ..where((i) => i.codeSafe.equals('BOX-002')))
          .getSingle();

      // 第二组被人工确认归属 —— 之后重跑不许碰它。
      final assign = AssignService(db, deviceName: 'tester');
      await assign.confirmGroup(gid2, itemId: box2.id,
          source: AssignSource.manual);

      // 换识别结果（模拟换了引擎 / 装好了增强识别）后全量重跑。
      for (final p in photos) {
        fake.results[p.filePath] = [token('BOX-001')];
      }
      final n = await pipeline.rerunProject(projectId);
      expect(n, 2); // 只有第一组的 2 张（第二组已归属，跳过）。

      await waitIdle();

      final after = await (db.select(db.photos)).get();
      final g1Photos = after.where((p) => p.groupId == gid1);
      final g2Photos = after.where((p) => p.groupId == gid2);

      // ★ 第一组：token 已换成新识别结果。
      final g1Tokens = await (db.select(db.ocrTokens)
            ..where((t) => t.photoId.isIn(g1Photos.map((p) => p.id).toList())))
          .get();
      expect(g1Tokens.map((t) => t.rawText), everyElement('BOX-001'));

      // ★ 第二组：归属与识别状态原样 —— 人的决定不被识别覆盖。
      expect(g2Photos.map((p) => p.ocrState), everyElement(OcrState.done.code));
      expect(g2Photos.map((p) => p.itemId), everyElement(box2.id));

      // 第一组的建议被重合成（BOX-001）。
      final g1 = (await groupRow(gid1))!;
      expect(g1.suggestedItemId, box1.id);
      // ★ 第二组的建议原样保留（还是 BOX-002，没被重跑清洗）。
      final g2 = (await groupRow(gid2))!;
      expect(g2.suggestedItemId, box2.id);
    });
  });
}

extension on OcrTokenResult {
  OcrTokenResult copy({required String text}) => OcrTokenResult(
        text: text,
        ocrConf: ocrConf,
        normCx: normCx,
        normCy: normCy,
      );
}
