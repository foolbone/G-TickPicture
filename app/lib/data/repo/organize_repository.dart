import 'dart:convert';
import 'dart:io';

import 'package:async/async.dart';
import 'package:drift/drift.dart';
import 'package:path/path.dart' as p;
import 'package:uuid/uuid.dart';

import '../../domain/model/assigned_group.dart';
import '../../domain/model/enums.dart';
import '../../domain/model/open_group.dart';
import '../db/database.dart';
import '../fs/project_paths.dart';

/// 整理页的数据引擎（M3 / §5.4）。
///
/// 职责边界（很重要）：
///  · **分组是建议**：本类负责把照片聚成组、改组结构（合并/拆分/移出）。
///    2026-09-29 老板拍板后分组规则是**按批次**：一批（captureSession，
///    相册一次导入或相机一段连拍）整批一组，不再按时序间隔拆分。
///    组表上的 `suggestedItemId` / `suggestionConf` / `suggestState`
///    系列字段它永远不碰 —— 那是 M4 的 SuggestService 专属。
///  · **归属是决定**：`itemId` / `confirmedAt` 只能由 AssignService 写 ——
///    本类从代码上就没有任何写这两个字段的路径（架构规则 3）。
///  · 幂等与保护：[regroupPending] 处理「还没有组」的照片 + 未指派的
///    单张组（边拍边触发时先把先到的照片拉回来，才能与同批次的后续
///    照片合成一组）；多张组与已确认的组永不回收 —— 「现场随手清一段 +
///    收工统一过」双路径共用同一套数据的前提（§5.4 S6）。
class OrganizeRepository {
  OrganizeRepository(this._db);

  final AppDatabase _db;
  static const _uuid = Uuid();

  /// 正在跑重组的项目（P4 诉求 3 的重入锁）。键 = projectId。
  ///
  /// **为什么必须有**：[regroupPending] 是幂等的（只处理 `group_id IS NULL`
  /// 的照片），但**幂等 ≠ 并发安全**。两次并发调用会同时读到同一批未入组
  /// 照片、各自按批次建组，后写的一方覆盖 `group_id` —— 结果是一批
  /// 永远没有照片的**孤儿空组**，它们会一直挂在整理页的待办流里，
  /// 而人要逐个手动清掉。
  ///
  /// 触发场景很现实：整理页可见性改造后，切换 Tab、下拉刷新、
  /// 采集后自动补组三条路径可能同时到达。
  ///
  /// 锁的语义：同一个 projectId 的第二次调用**等第一次跑完**再跑一次
  /// （不是直接返回）—— 因为第一次可能只处理了它拿到的那批，
  /// 等待期间新落的照片需要被这一轮补上。
  final _regroupLocks = <String, Future<int>>{};

  // ── 补拍保护（2026-10-08 真机报错修复）─────────────────────
  //
  // 「补充照片」进行中的目标组。regroup 回收**未指派单张组**的规则与
  // 它天然相撞：老板最常补拍的恰恰是只有一张照片的组（先拍一张建组、
  // 再回来补齐）。补拍期间每落一张照片，openGroupsProvider 都会触发
  // 一轮 regroup —— 目标组一旦被回收（组删了、老照片被挪进新批次组），
  // 拍完回来 attachPhotosToGroup 就炸「目标组不存在」，新照片被孤在
  // 一个自动建的小组里 —— 老板看到的就是「一次连拍分成好几个小组」
  // 加上「拍照保存返回后报错」。
  //
  // 语义：保护期内 regroup **跳过**这些组（不回收、不删）；保护由 UI
  // 在进入/离开补拍流程时显式加解（[protectGroupFromRegroup] /
  // [unprotectGroup]）。进程被杀后保护自然失效 —— 那时补拍流程也不
  // 存在了，attach 不会被调用，无副作用。
  /// 保护计数而不是布尔集合（2026-10-21）：系统相机改成「返回即回 App，
  /// 首批/晚到后台入库」后，补拍目标组要一直保护到 sweep 收尾；页面自己
  /// 那层保护会先释放。计数让两层各自 acquire/release，谁先走都不会误删
  /// 另一层的保护。
  final _protectCounts = <String, int>{};

  /// 把 [groupId] 排除在 regroup 的单张组回收之外，直到调用
  /// [unprotectGroup]。可重入：每次 acquire 都要对应一次 release。
  void protectGroupFromRegroup(String groupId) {
    _protectCounts[groupId] = (_protectCounts[groupId] ?? 0) + 1;
  }

  /// 解除一次保护。未保护过时调用无害。
  void unprotectGroup(String groupId) {
    final n = _protectCounts[groupId];
    if (n == null) return;
    if (n <= 1) {
      _protectCounts.remove(groupId);
    } else {
      _protectCounts[groupId] = n - 1;
    }
  }

  Iterable<String> get _protectedGroups => _protectCounts.keys;

  // ─────────────────────────────────────────────────────────
  // 按批次分组落库
  // ─────────────────────────────────────────────────────────

  /// 把「还没有组」的照片按批次聚成组（一批一组）并落库。返回新建组数。
  ///
  /// 串行化的重入外壳 —— 见 [_regroupLocks] 的说明。
  ///
  /// 前一次还没跑完时，本次调用排队等它结束再执行自己的那一轮。
  Future<int> regroupPending(String projectId) {
    final prev = _regroupLocks[projectId] ?? Future<int>.value(0);
    // 用 late 声明：whenComplete 的闭包要拿 next 自己去做"我还是队尾吗"的判断，
    // 而 `final next = ...` 的自引用在 Dart 里是编译错误
    //（referenced_before_declaration）。
    late final Future<int> next;
    next = prev
        .then((_) => _regroupPendingOnce(projectId),
            onError: (_) => _regroupPendingOnce(projectId))
        .whenComplete(() {
      // 只有自己还是"队尾"时才清锁，避免把后来者的排队链误删
      if (identical(_regroupLocks[projectId], next)) {
        _regroupLocks.remove(projectId);
      }
    });
    _regroupLocks[projectId] = next;
    return next;
  }

  /// 把「还没有组」的照片**按批次**聚成组并落库。返回新建组数。
  ///
  /// 【2026-09-29 老板拍板：分组 = 一批一组】
  /// 「选择导入的一批，或者连续拍摄的照片为一组」—— 相册一次导入、
  /// 相机一段连拍（同一个 captureSession）整批成一组，不再按时序间隔
  /// 拆分。回收口径（2026-10-09 收紧为「整批重聚」）：
  ///  · **活跃批次**（本轮有游离照片落下的批次）内**未指派、未指定
  ///    箱号、未保护**的全部组 —— 不限张数，连同游离照片整批重聚。
  ///    旧口径「只回收单张组」在逐张触发的真实节奏下追不上：连拍
  ///    4 张会「两两一组」（10-09 真机反馈）。相机是边拍边触发补组
  ///    的：第 1 张先到已立成组，不让后续照片与它重聚就永远合成
  ///    不了「连续拍摄的一组」。
  ///  · 游离照片 —— 收进来按批次成组。
  ///  · 已确认归属的组（itemId）、老板指定过箱号的组（carton）、
  ///    补拍目标组（保护集）—— 一律不动。
  ///  · 非活跃批次（没有新照片落下）不碰 —— 整理阶段没有游离照片，
  ///    本方法 no-op，手动成果天然安全。
  ///  · 监装照片不参与（category 过滤）—— 它们不与清单对应，
  ///    家是监装照片墙（2026-09-27 部类卫生修复）。
  ///
  /// ⚠️ 外部调用请走 [regroupPending]（带重入锁），不要直接调本方法。
  Future<int> _regroupPendingOnce(String projectId) async {
    // ① 候选一：游离照片（group_id IS NULL —— 还没跑过任何一轮成组）。
    //    同样只收预检：游离监装照片的家是照片墙，不是组。
    //    **先取它** —— 游离照片所在的批次决定本轮重组哪些批次：
    //    只有「本轮有新照片落下的批次」才允许整批重聚。整理阶段没有
    //    游离照片 → 本方法 no-op → 老板手动合并/设置的成果天然不被碰
    //    （这是本条口径的安全边界，不能丢）。
    final orphanPhotos = await (_db.select(_db.photos)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.groupId.isNull() &
              t.category.equals(PhotoCategory.precheck.code)))
        .get();
    final activeSessions = orphanPhotos.map((p) => p.sessionId).toSet();

    // ② 候选二：**活跃批次**内的未指派、未保护、未指定箱号的**全部**
    //    预检组 —— **不限张数**。
    //    2026-10-09 真机反馈：不点补充照片直接连拍 4 张，拆成了两组。
    //    相机是每拍一张触发一轮 regroup，旧口径「只回收单张组」追不上：
    //    第 1、2 张聚成 2 张组后，第 3 张的 regroup 不敢动它 → 新建组，
    //    第 4 张又与第 3 张聚成第二组 → 「两两一组」。而「一批一组」
    //    （2026-09-29 拍板）的正确口径是：**同批次未指派组本就该是
    //    一组**，有新照片落下就整批重聚。旧的单张组回收是本条的子集。
    //    三道边界，一道都不能少：
    //    · carton IS NULL —— 老板指定过箱号的组是人工成果，不碰；
    //    · itemId IS NULL —— 归属是 AssignService 的地盘；
    //    · _protectedGroups —— 补拍目标组（2026-10-08 真机事故修复），
    //      否则补拍拍完回来组没了，attach 直接炸「目标组不存在」。
    if (activeSessions.isNotEmpty) {
      var groupQuery = _db.select(_db.photoGroups)
        ..where((t) =>
            t.projectId.equals(projectId) &
            t.itemId.isNull() &
            t.carton.isNull() &
            t.category.equals(PhotoCategory.precheck.code) &
            t.sessionId.isIn(activeSessions.toList()));
      if (_protectedGroups.isNotEmpty) {
        groupQuery = groupQuery
          ..where((t) => t.id.isNotIn(_protectedGroups.toList()));
      }
      final loneGroups = await groupQuery.get();
      final groupIds = loneGroups.map((g) => g.id).toList();

      // ③ 被回收组里的照片（组级 itemId IS NULL 时组内照片必然未指派
      //    —— confirmGroup 同时写组与组内照片；万一数据损坏出现例外，
      //    group_id 置 NULL 不触碰照片上的 itemId，归属仍可追溯，且
      //    交付自检（orphan 审计）会如实暴露，不会静默丢归属）。
      final recycled = groupIds.isEmpty
          ? const <Photo>[]
          : await (_db.select(_db.photos)
                ..where((t) => t.groupId.isIn(groupIds)))
              .get();

      final candidates = [...recycled, ...orphanPhotos];
      if (groupIds.isEmpty && candidates.isEmpty) return 0;

      // ④ 按批次（session）分桶 —— 一批一组的最小单元。
      //    批次来源决定 origin（"照片从哪来"）。
      final sessions = await (_db.select(_db.captureSessions)
            ..where((t) => t.projectId.equals(projectId)))
          .get();
      final isAlbumBySession = <String, bool>{
        for (final s in sessions)
          s.id: s.source == CaptureSource.album.code,
      };

      final bySession = <String, ({bool isAlbum, List<String> photoIds})>{};
      for (final p in candidates) {
        bySession
            .putIfAbsent(
              p.sessionId,
              // 防御：找不到批次记录时按相机批次处理（宁多勿错）
              () => (isAlbum: isAlbumBySession[p.sessionId] ?? false, photoIds: <String>[]),
            )
            .photoIds
            .add(p.id);
      }

      // ⑤ 整批成组：一个批次一个组，**不按时序拆分**（2026-09-29 拍板）。
      final clusters =
          <({String sessionId, List<String> photoIds, GroupOrigin origin})>[];
      bySession.forEach((sessionId, bucket) {
        clusters.add((
          sessionId: sessionId,
          photoIds: bucket.photoIds,
          origin: bucket.isAlbum ? GroupOrigin.album : GroupOrigin.camera,
        ));
      });

      // ⑥ 事务落库：拆旧组 → 挂新组。⚠️ 全程不触碰 itemId。
      return _db.transaction(() async {
        if (groupIds.isNotEmpty) {
          await (_db.update(_db.photos)..where((t) => t.groupId.isIn(groupIds)))
              .write(const PhotosCompanion(groupId: Value(null)));
          await (_db.delete(_db.photoGroups)..where((t) => t.id.isIn(groupIds)))
              .go();
        }
        return _persistClusters(projectId, clusters);
      });
    }
    return 0;
  }

  // ─────────────────────────────────────────────────────────
  // 分组方式（2026-09-29 老板拍板：**按批次一组**，去掉时序聚类）
  //
  // 旧版的三件套 —— 「自动按时序聚类」开关（09-26/09-27 两度改拍板）、
  // 归组间隔（organize.group_gap_seconds）、单组上限
  // （organize.group_max_photos）—— 已整体移除：分组规则不再可配，
  // 一批（captureSession）就是一组。AppSettings 表里的旧键值不再被
  // 任何代码读取，留在库里无害。
  // ─────────────────────────────────────────────────────────

  /// 把分组结果落库：建组 + 照片挂组。调用方负责开事务。
  ///
  /// 从 [_regroupPendingOnce] 抽出的落库段（seq 连续、photoCount 实算）。
  Future<int> _persistClusters(
    String projectId,
    List<({String sessionId, List<String> photoIds, GroupOrigin origin})> clusters,
  ) async {
    if (clusters.isEmpty) return 0;
    var seq = await _maxGroupSeq(projectId);
    final now = DateTime.now().millisecondsSinceEpoch;
    var created = 0;

    for (final c in clusters) {
      seq++;
      final groupId = _uuid.v4();

      await _db.into(_db.photoGroups).insert(
            PhotoGroupsCompanion.insert(
              id: groupId,
              projectId: projectId,
              sessionId: c.sessionId,
              seq: seq,
              coverPhotoId: Value(c.photoIds.first),
              photoCount: Value(c.photoIds.length),
              origin: Value(c.origin.code),
              // 本仓储聚出来的只会是预检组（两条入口都过滤了部类）；
              // 显式写死而不是依赖列默认值 —— 默认值一改这里就悄悄漏。
              category: Value(PhotoCategory.precheck.code),
              createdAt: now,
            ),
          );

      await (_db.update(_db.photos)..where((t) => t.id.isIn(c.photoIds)))
          .write(PhotosCompanion(groupId: Value(groupId)));

      created++;
    }
    return created;
  }

  Future<int> _maxGroupSeq(String projectId) async {
    final row = await _db.customSelect(
      'SELECT COALESCE(MAX(seq), 0) AS m FROM photo_groups WHERE project_id = ?',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photoGroups},
    ).getSingle();
    return row.read<int>('m');
  }

  // ─────────────────────────────────────────────────────────
  // 组结构调整（§5.4 的三个手工修正）
  //
  // 都只动"分组"这个建议层；照片与组的归属字段（itemId）
  // 由 AssignService 在确认时统一回填，这里改结构不需要通知它。
  // ─────────────────────────────────────────────────────────

  /// 新建一个空组（给「移出」的照片安家）。
  Future<String> createGroup(String projectId, String sessionId) async {
    final id = _uuid.v4();
    await _db.into(_db.photoGroups).insert(
          PhotoGroupsCompanion.insert(
            id: id,
            projectId: projectId,
            sessionId: sessionId,
            seq: await _maxGroupSeq(projectId) + 1,
            origin: Value(GroupOrigin.manual.code),
            createdAt: DateTime.now().millisecondsSinceEpoch,
          ),
        );
    return id;
  }

  /// 合并若干组为一组（photoId 全部并入 [targetGroupId]）。
  ///
  /// 空组会被清掉（不留壳）。已确认归属的组不允许被合并
  /// —— 那会绕过 AssignService 的决策记录。
  Future<void> mergeGroups(
    String projectId, {
    required String targetGroupId,
    required List<String> otherGroupIds,
  }) async {
    if (otherGroupIds.isEmpty) return;
    await _db.transaction(() async {
      // 已确认的组不能参与合并（会丢决策记录）—— 目标组与被并走的源组都算
      final locked = await (_db.select(_db.photoGroups)
            ..where((t) =>
                (t.id.isIn(otherGroupIds) | t.id.equals(targetGroupId)) &
                t.itemId.isNotNull()))
          .get();
      if (locked.isNotEmpty) {
        throw StateError('已确认归属的组不允许合并（id=${locked.map((e) => e.id)}）');
      }

      await (_db.update(_db.photos)
            ..where((t) => t.groupId.isIn(otherGroupIds)))
          .write(PhotosCompanion(groupId: Value(targetGroupId)));

      // 目标组的张数同步
      final n = await _countPhotos(targetGroupId);
      await (_db.update(_db.photoGroups)
            ..where((t) => t.id.equals(targetGroupId)))
          .write(PhotoGroupsCompanion(photoCount: Value(n)));

      // 清掉被并走的空组
      await (_db.delete(_db.photoGroups)
            ..where((t) => t.id.isIn(otherGroupIds)))
          .go();
    });
  }

  /// 把一批照片**挂进指定组**（2026-09-30「组内添加照片」）。
  ///
  /// 挂的是**分组**（groupId），不是归属（itemId）—— 后者仍然只有
  /// AssignService 能写。典型来源：组内补拍 / 从相册补导（UI 在
  /// 导入或拍摄完成后立刻调本方法）。
  ///
  /// 移动语义，竞态免疫：
  ///  · 照片当前可能还游离（groupId NULL）—— 直接挂；
  ///  · 也可能已被 regroup 抢先按批次聚进了临时组 —— 从那儿**搬**过来，
  ///    搬空的临时组顺手删掉（与 [mergeGroups] 同一套收尾）。
  ///  两种起点最终状态一致：照片在目标组、临时组不留空壳、
  ///  photoCount 列实算（regroup 回收单张组靠这列，虚高/虚低都会出错）。
  ///
  /// 只允许挂进**未指派的预检组**：
  ///  · 已指派组（itemId 非空）不再收人 —— confirmGroup 时会按组回填
  ///    照片 itemId，事后加进来的照片 itemId 是 NULL，交付计划按 itemId
  ///    挑照片时它会凭空消失。要补拍就先撤销归属。
  ///  · 监装组没有"组内补"的语义（照片墙自身有入口）。
  ///
  /// 返回实际挂进目标的张数（不存在的照片 id 会被静默跳过）。
  Future<int> attachPhotosToGroup(
    String projectId,
    String groupId,
    List<String> photoIds,
  ) async {
    if (photoIds.isEmpty) return 0;

    return _db.transaction(() async {
      final group = await (_db.select(_db.photoGroups)
            ..where((t) => t.id.equals(groupId)))
          .getSingleOrNull();
      if (group == null || group.projectId != projectId) {
        throw StateError('目标组不存在（groupId=$groupId）');
      }
      if (group.itemId != null) {
        throw StateError('该组已指派货品，不能再往里加照片 —— 请先撤销归属');
      }
      if (group.category != PhotoCategory.precheck.code) {
        throw StateError('监装组不支持组内添加照片');
      }

      // 只认本项目的照片；顺带记下它们现在的组（可能为空）
      final photos = await (_db.select(_db.photos)
            ..where((t) => t.id.isIn(photoIds) & t.projectId.equals(projectId)))
          .get();
      if (photos.isEmpty) return 0;

      final oldGroupIds = <String>{
        for (final p in photos)
          if (p.groupId != null && p.groupId != groupId) p.groupId!,
      };

      await (_db.update(_db.photos)
            ..where((t) => t.id.isIn(photos.map((e) => e.id).toList())))
          .write(PhotosCompanion(groupId: Value(groupId)));

      // 搬空的旧组删掉；没搬空的实算张数（列被 regroup 回收逻辑依赖）
      for (final oldId in oldGroupIds) {
        final n = await _countPhotos(oldId);
        if (n == 0) {
          await (_db.delete(_db.photoGroups)..where((t) => t.id.equals(oldId)))
              .go();
        } else {
          await (_db.update(_db.photoGroups)
                ..where((t) => t.id.equals(oldId)))
              .write(PhotoGroupsCompanion(photoCount: Value(n)));
        }
      }

      // 目标组张数同步
      final n = await _countPhotos(groupId);
      await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
          .write(PhotoGroupsCompanion(photoCount: Value(n)));

      return photos.length;
    });
  }

  /// 把一张照片移出组（落入新的空组，等待重新安置或独立归属）。
  Future<void> movePhotoOut(String projectId, String photoId) async {
    await _db.transaction(() async {
      final photo = await (_db.select(_db.photos)
            ..where((t) => t.id.equals(photoId)))
          .getSingleOrNull();
      if (photo == null || photo.groupId == null) return;

      final oldGroupId = photo.groupId!;

      // 已确认的照片不允许移出 —— 归属是 AssignService 的地盘
      if (photo.itemId != null || photo.state == PhotoState.confirmed.code) {
        throw StateError('已确认归属的照片不允许移出（photoId=$photoId）');
      }

      await (_db.update(_db.photos)..where((t) => t.id.equals(photoId)))
          .write(const PhotosCompanion(groupId: Value(null)));

      final n = await _countPhotos(oldGroupId);
      if (n == 0) {
        await (_db.delete(_db.photoGroups)
              ..where((t) => t.id.equals(oldGroupId)))
            .go();
      } else {
        await (_db.update(_db.photoGroups)
              ..where((t) => t.id.equals(oldGroupId)))
            .write(PhotoGroupsCompanion(photoCount: Value(n)));
      }

      // 给它一个新家（manual 组），这样它仍在待办流里
      final newGroupId = await createGroup(projectId, photo.sessionId);
      await (_db.update(_db.photos)..where((t) => t.id.equals(photoId)))
          .write(PhotosCompanion(groupId: Value(newGroupId)));
    });
  }

  Future<int> _countPhotos(String groupId) async {
    final row = await _db.customSelect(
      'SELECT COUNT(*) AS c FROM photos WHERE group_id = ?',
      variables: [Variable.withString(groupId)],
      readsFrom: {_db.photos},
    ).getSingle();
    return row.read<int>('c');
  }

  // ─────────────────────────────────────────────────────────
  // 待办流（整理页主列表）
  // ─────────────────────────────────────────────────────────

  /// 「还没入组的照片数」信号流（P4 诉求 3）。
  ///
  /// 为什么要它：整理页的待办流（[watchOpenGroups]）查的是 `photo_groups`
  /// 表，而**刚拍的照片 `group_id` 是 NULL，根本不在那张表里** ——
  /// 所以它不是"刷新慢"，是"查不到"。要让它出现，必须先跑一次
  /// [regroupPending] 把照片聚成组。
  ///
  /// 这条流就是这个"该跑重组了"的信号：数值 > 0 就意味着有待入组的照片。
  /// 调用方（provider）拿它当触发器，一旦有新的未入组照片就补一轮分组。
  ///
  /// ⚠️ 它只**读** photos 表，不写任何东西 —— 分组仍然只由
  /// [regroupPending] 落库（那才是唯一的写入口）。
  Stream<int> watchPendingPhotoCount(String projectId) => _db.customSelect(
        // 监装照片不算"待处理"：它们不需要入组、不需要对应编码，
        // 在整理页只是躺在一个照片墙里等着打包。把它们算进待办数，
        // 会让"还剩多少活"这个数字永远清不掉。
        'SELECT COUNT(*) AS c FROM photos '
        'WHERE project_id = ? AND group_id IS NULL '
        "AND category = 'precheck'",
        variables: [Variable.withString(projectId)],
        readsFrom: {_db.photos},
      ).watchSingle().map((r) => r.read<int>('c'));

  /// 待处理组流：还没有归属的组 + 组内照片（缩略图投影）+ **M4 建议字段**。
  ///
  /// 排序：按首张拍摄时间升序 —— 与现场走动顺序一致，
  /// 人的记忆是按时间组织的，翻起来最省力。
  /// 组一旦确认归属，就从这条流里消失（§5.4：只看剩下的）。
  ///
  /// M4：建议（suggestedItemId + 清单编码/品名 + 置信度 + 状态 + 依据）
  /// 一并投影 —— 建议进 UI 是设计方案 §5.3.2 的明文承诺；
  /// 本方法仍然是**只读投影**，不写任何字段。
  Stream<List<OpenGroup>> watchOpenGroups(String projectId) {
    final groupsQuery = (_db.select(_db.photoGroups)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.itemId.isNull() &
              // 监装组不进待办流：它本来就不需要对应编码，
              // 放在这里只会让人以为"还有活没干"。
              t.category.equals(PhotoCategory.precheck.code)))
        .watch();

    // 照片行的缩略图是**入库之后**才异步落库的（不阻塞快门，见
    // CameraCaptureService 的派生三连），而组查询只监听 photo_groups
    // —— 照片列变化不会推新值，列表就永远停在占位图（2026-10-14 真机
    // 「最新照片缩略图显示不出来」）。触发流见 [_thumbsKick]。
    return StreamGroup.merge([groupsQuery, _thumbsKick(projectId)])
        .asyncMap((_) => _assembleOpenGroups(projectId));
  }

  /// 组 → 缩略图投影 → 建议货品信息 → 排序，一次组装。
  ///
  /// 抽成独立方法是因为它现在有两个触发源（组变化 / 缩略图缺口变化）。
  Future<List<OpenGroup>> _assembleOpenGroups(String projectId) async {
    final groups = await (_db.select(_db.photoGroups)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.itemId.isNull() &
              t.category.equals(PhotoCategory.precheck.code)))
        .get();
    if (groups.isEmpty) return const <OpenGroup>[];

    // 一把查出照片，避免 N+1（几百组 × 2 张的量级毫无压力）
    final ids = groups.map((g) => g.id).toList();
    final photos = await (_db.select(_db.photos)
          ..where((t) => t.groupId.isIn(ids))
          ..orderBy([(t) => OrderingTerm.asc(t.takenAt)]))
        .get();

    final photosByGroup = <String, List<GroupPhotoThumb>>{};
    // 原始行另存一份：OCR 状态计数要用（缩略图投影不带状态字段）。
    final rawByGroup = <String, List<Photo>>{};
    for (final p in photos) {
      final gid = p.groupId;
      if (gid == null) continue;
      photosByGroup
          .putIfAbsent(gid, () => [])
          .add(GroupPhotoThumb(
            id: p.id,
            takenAtMs: p.takenAt,
            thumbPath: p.thumbPath,
            // P4 诉求 2：全屏查看用。列表**不得**拿它去解码（见模型注释）。
            originalPath: p.filePath,
          ));
      rawByGroup.putIfAbsent(gid, () => []).add(p);
    }

    // ── 建议货品的清单信息（编码/品名）一把查，同样避免 N+1 ──
    final suggestedIds = groups
        .map((g) => g.suggestedItemId)
        .whereType<String>()
        .toSet();
    final itemInfo = <String, ({String code, String? name})>{};
    if (suggestedIds.isNotEmpty) {
      final items = await (_db.select(_db.items)
            ..where((t) => t.id.isIn(suggestedIds)))
          .get();
      for (final it in items) {
        itemInfo[it.id] = (code: it.code, name: it.name);
      }
    }

    final result = groups.map((g) {
      final suggested = g.suggestedItemId;
      final info = suggested == null ? null : itemInfo[suggested];
      final groupPhotos = photosByGroup[g.id] ?? const <GroupPhotoThumb>[];
      // 组内 OCR 状态计数（P4 · 真机反馈）：失败必须可见，
      // 否则"识别崩了"会被「未识别到清晰编码」这句话说成"没有编码"。
      var pendingCount = 0;
      var failedCount = 0;
      for (final p in rawByGroup[g.id] ?? const <Photo>[]) {
        switch (p.ocrState) {
          case 'pending':
          case 'running':
            pendingCount++;
          case 'failed':
            failedCount++;
        }
      }
      return OpenGroup(
        groupId: g.id,
        seq: g.seq,
        takenAtMs: photosByGroup[g.id]?.first.takenAtMs ?? 0,
        photos: groupPhotos,
        suggestedItemId: suggested,
        suggestedCode: info?.code,
        suggestedName: info?.name,
        suggestionConf: g.suggestionConf,
        suggestState: GroupSuggestState.fromCode(g.suggestState),
        evidence: _evidenceOf(g.suggestionJson),
        ocrPendingCount: pendingCount,
        ocrFailedCount: failedCount,
        category: PhotoCategory.fromCode(g.category),
        carton: g.carton,
      );
    }).toList()
      ..sort((a, b) => a.takenAtMs.compareTo(b.takenAtMs));
    return result;
  }

  /// 从 `suggestionJson` 里只取 UI 要的 evidence。
  ///
  /// 候选列表（candidates）第一版不上 UI —— "改派候选"面板等到真有人
  /// 抱怨排序不对再做（§3 原则 7：建议可解释的最低实现是命中依据）。
  /// 坏 JSON 不该发生（管道只写自产 JSON）；解析失败按无证据处理。
  static List<String> _evidenceOf(String? json) {
    if (json == null) return const [];
    try {
      final decoded = jsonDecode(json);
      if (decoded is Map && decoded['evidence'] is List) {
        return (decoded['evidence'] as List).whereType<String>().toList();
      }
    } catch (_) {
      // 按"无证据"处理 —— 不让一个坏字段挡住整条待办流。
    }
    return const [];
  }

  /// 已指派组流（P4 · 真机反馈修复）：已有归属的组 + 归属信息 + 组内缩略图。
  ///
  /// ═════════════════════════════════════════════════════════════
  /// 为什么要有这条流：v3.1「只显示缺口」让 [watchOpenGroups] 只查
  /// `item_id IS NULL` —— 已确认的组从待办流里消失，这在「专注待办」
  /// 上是对的，但它有个没被审视过的副作用：**指派错了的人找不到
  /// 那组照片在哪**（真机实测 2026-09-24：「在整理时，无法看到已经
  /// 指派的照片，导致无法修改」）。
  ///
  /// 修法不是把已确认的组塞回待办流（那会毁掉"列表只会越来越短"的
  /// 收工体验），而是**并行的第二条流**：待办流回答"还剩什么没干"，
  /// 本流回答"已经干了什么、干得对不对"。
  ///
  /// 本方法是**只读投影** —— 撤销/改派仍然只能走 AssignService
  /// （revokeGroup / confirmGroup），这里没有任何写路径。
  /// ═════════════════════════════════════════════════════════════
  Stream<List<AssignedGroup>> watchAssignedGroups(String projectId) {
    final groupsQuery = (_db.select(_db.photoGroups)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.itemId.isNotNull() &
              // 「已指派」是预检这一段的事 —— 监装照片不与清单对应，
              // 也就不存在"指派给哪件货"。
              t.category.equals(PhotoCategory.precheck.code)))
        .watch();

    return StreamGroup.merge([groupsQuery, _thumbsKick(projectId)])
        .asyncMap((_) => _assembleAssignedGroups(projectId));
  }

  /// 「本项目缺缩略图的照片数」触发流（distinct 后只在数字变化时发）。
  ///
  /// 缩略图是入库之后异步落库的（不阻塞快门），而组查询只监听
  /// photo_groups —— 照片列变化不推新值，列表就停在占位图
  /// （2026-10-14 真机「最新照片缩略图显示不出来」）。
  ///
  /// 为什么用「缺缩略图的张数」而不是「照片行的任何变化」：
  /// OCR / 指纹回填也在写照片行，用行变化当触发源，一次导入几百张
  /// 会把整份列表重组装几百次（每组还要查建议信息）。缺缩略图张数
  /// 只在缩略图真正落库（或又失败）时变化 —— 精准、无风暴。
  Stream<int> _thumbsKick(String projectId) =>
      (_db.selectOnly(_db.photos)
            ..addColumns([_db.photos.thumbPath])
            ..where(_db.photos.projectId.equals(projectId)))
          .watch()
          .map((rows) =>
              rows.where((r) => r.read(_db.photos.thumbPath) == null).length)
          .distinct();

  Future<List<AssignedGroup>> _assembleAssignedGroups(String projectId) async {
    final groups = await (_db.select(_db.photoGroups)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.itemId.isNotNull() &
              // 「已指派」是预检这一段的事 —— 监装照片不与清单对应，
              // 也就不存在"指派给哪件货"。
              t.category.equals(PhotoCategory.precheck.code)))
        .get();
    if (groups.isEmpty) return const <AssignedGroup>[];

    final ids = groups.map((g) => g.id).toList();
    final photos = await (_db.select(_db.photos)
          ..where((t) => t.groupId.isIn(ids))
          ..orderBy([(t) => OrderingTerm.asc(t.takenAt)]))
        .get();

    final photosByGroup = <String, List<GroupPhotoThumb>>{};
    for (final p in photos) {
      final gid = p.groupId;
      if (gid == null) continue;
      photosByGroup
          .putIfAbsent(gid, () => [])
          .add(GroupPhotoThumb(
            id: p.id,
            takenAtMs: p.takenAt,
            thumbPath: p.thumbPath,
            // 全屏查看用；列表同样只准读缩略图。
            originalPath: p.filePath,
            ));
      }

      // 归属货品的清单信息（编码/品名/箱号）一把查，避免 N+1。
      // 箱号是 M5.1「整理按箱号分组」的数据源（老板 09-26 拍板）。
      final itemIds = groups.map((g) => g.itemId).whereType<String>().toSet();
      final itemInfo =
          <String, ({String code, String? name, String? containerSummary})>{};
      if (itemIds.isNotEmpty) {
        final items = await (_db.select(_db.items)
              ..where((t) => t.id.isIn(itemIds)))
            .get();
        for (final it in items) {
          itemInfo[it.id] = (
            code: it.code,
            name: it.name,
            containerSummary: it.containerSummary,
          );
        }
      }

      final result = groups.map((g) {
        final itemId = g.itemId ?? '';
        final info = itemInfo[itemId];
        return AssignedGroup(
          groupId: g.id,
          seq: g.seq,
          takenAtMs: photosByGroup[g.id]?.first.takenAtMs ?? 0,
          itemId: itemId,
          itemCode: info?.code ?? '（清单已变，货品不存在）',
          itemName: info?.name,
          containerSummary: info?.containerSummary,
          confirmedAtMs: g.confirmedAt ?? g.createdAt,
          category: PhotoCategory.fromCode(g.category),
          carton: g.carton,
          photos: photosByGroup[g.id] ?? const [],
        );
      }).toList()
        // 已指派的按**确认时间倒序** —— 刚指派的在最上面，
        // 因为"刚指派完发现错了要改"是本流存在的第一理由。
        ..sort((a, b) => b.confirmedAtMs.compareTo(a.confirmedAtMs));
      return result;
  }

  // ─────────────────────────────────────────────────────────
  // 部类（预检 / 监装）与箱号（老板 2026-09-27 拍板）
  //
  // ⚠️ 与归属的分界线（很重要）：
  //   归属 = "这组照片属于哪件货" → 只能 AssignService 写，留决策凭据。
  //   部类 = "这些照片进交付包的哪个文件夹" → 人说了算，不留凭据
  //          （它不是一个事实判断，只是交付时的整理方式）。
  //   箱号同理：它是**人输入**的一个标签，不是清单数据。
  //
  //   所以下面这几个方法**不碰 itemId / confirmedAt / assignments**，
  //   与架构规则 3 不冲突。
  // ─────────────────────────────────────────────────────────

  /// 把一组照片整组归到某个部类（预检 / 监装）。
  ///
  /// 组表与照片表**在同一个事务里**一起更新：整理页按组展示与切换，
  /// 打包与统计却按照片走（监装照片可能根本不进组）。只写一边就会
  /// 出现"组是监装、照片还是预检"的裂缝，包里就会放错文件夹。
  Future<void> setGroupCategory(
    String groupId,
    PhotoCategory category,
  ) async {
    await _db.transaction(() async {
      await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
          .write(PhotoGroupsCompanion(category: Value(category.code)));
      await (_db.update(_db.photos)..where((t) => t.groupId.equals(groupId)))
          .write(PhotosCompanion(category: Value(category.code)));
    });
  }

  /// 把一批照片改部类（v0.22.3 修复：**改回预检时同步摘组**）。
  ///
  /// 为什么必须摘组 —— 两条墙的查询口径不同：
  ///  · 预检墙（[watchOpenGroups]）查的是**组**（只看 precheck 组）；
  ///  · 监装墙（[watchSupervisionPhotos]）查的是**照片行**（category）。
  /// 只改照片行不改挂组 → 改回预检的照片还挂在监装组里：
  /// 监装墙不显示（行改了）、预检墙也看不到（组不对）、
  /// 待入组信号只数 `group_id IS NULL` 又不数它 —— regroup 永远
  /// 不会把它捡回来，照片在两个墙里同时消失（2026-10-14 真机 bug）。
  /// 摘组后 group_id = NULL → 待入组信号 > 0 → regroup 自动重新
  /// 聚成预检组，回到「重新参与编码对应与箱号分组」的承诺语义。
  ///
  /// 对本来的游离照片（group_id 本来就是 NULL）置 NULL 无影响 ——
  /// 「拍完没聚成组的零星照片」这个兜底场景不受影响。
  Future<int> setPhotosCategory(
    List<String> photoIds,
    PhotoCategory category,
  ) async {
    if (photoIds.isEmpty) return 0;
    return _db.transaction(() async {
      await (_db.update(_db.photos)..where((t) => t.id.isIn(photoIds))).write(
        PhotosCompanion(
          category: Value(category.code),
          // Value(null) = 清空列（铁律：不是跳过）—— 摘出所在组。
          groupId: const Value(null),
        ),
      );
      // 摘空的监装组一并清掉（监装组不进任何流，空组只是脏数据）。
      // 只清「无归属的监装组」—— 归属组按架构不该是监装，万一有，
      // 绝不能因为清理把它删了（防回归的保守条件）。
      await _db.customStatement(
        "DELETE FROM photo_groups WHERE category = 'supervision' "
        'AND item_id IS NULL AND id NOT IN '
        '(SELECT group_id FROM photos WHERE group_id IS NOT NULL)',
      );
      return photoIds.length;
    });
  }

  /// 设置一组照片的箱号（**用户指定**，不查清单）。
  ///
  /// null / 空串 / 纯空格 = 清除箱号 → 交付时进 `_未分箱/`。
  Future<void> setGroupCarton(String groupId, String? carton) async {
    final c = (carton ?? '').trim();
    await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
        .write(PhotoGroupsCompanion(carton: Value(c.isEmpty ? null : c)));
  }

  /// 本项目已经用过的箱号（去重，按组序号升序）。
  ///
  /// 给「指定箱号」面板做快捷选择：现场箱号就是有限的一批，
  /// 让人每一箱都手打一遍是没必要的负担（§4.2 少输入原则）。
  Future<List<String>> listCartons(String projectId) async {
    final rows = await (_db.select(_db.photoGroups)
          ..where((t) => t.projectId.equals(projectId) & t.carton.isNotNull())
          ..orderBy([(t) => OrderingTerm.asc(t.seq)]))
        .get();
    final out = <String>[];
    for (final r in rows) {
      final c = (r.carton ?? '').trim();
      if (c.isNotEmpty && !out.contains(c)) out.add(c);
    }
    return out;
  }

  /// 监装照片墙：所有被标为监装的照片（按拍摄时间升序）。
  ///
  /// 用 [GroupPhotoThumb] 这个投影只是因为它正好是"一张照片的最小
  /// 投影"（id + 时间 + 缩略图 + 全屏查看用原图），与是不是"组内"
  /// 无关 —— 列表只读缩略图这条纪律照样适用（R1b）。
  Stream<List<GroupPhotoThumb>> watchSupervisionPhotos(String projectId) =>
      (_db.select(_db.photos)
            ..where((t) =>
                t.projectId.equals(projectId) &
                t.category.equals(PhotoCategory.supervision.code))
            ..orderBy([(t) => OrderingTerm.asc(t.takenAt)]))
          .watch()
          .map((rows) => rows
              .map((p) => GroupPhotoThumb(
                    id: p.id,
                    takenAtMs: p.takenAt,
                    thumbPath: p.thumbPath,
                    originalPath: p.filePath,
                  ))
              .toList());

  /// 已被占用的货品 id 流（已有确认归属的组占用的 item）。
  ///
  /// 整理页指派面板用它把"已有一组归属"的货品置灰 ——
  /// 一件货只允许一个主组，这个规则要在 UI 上就挡住，
  /// 而不是等报告员在交付包里发现重复。
  Stream<Set<String>> watchAssignedItemIds(String projectId) {
    return (_db.select(_db.photoGroups)
          ..where((t) =>
              t.projectId.equals(projectId) & t.itemId.isNotNull()))
        .watch()
        .map((rows) => rows.map((r) => r.itemId!).toSet());
  }

  // ─────────────────────────────────────────────────────────
  // 跨项目搬移（2026-10-08 真机诉求 ③④）
  // ─────────────────────────────────────────────────────────

  /// 把一个组搬到另一个项目（诉求④「一个项目里的某一组移到另一个项目」）。
  ///
  /// 语义与边界：
  ///  · 只允许**未指派**的预检组 —— 已确认归属的组挂在源项目的货品上，
  ///    搬走会让交付证据链断裂（要搬先撤销归属）；
  ///  · 在目标项目里**新建一个批次**承接（source 跟随组来源），
  ///    组 seq / 照片 seq 都接目标项目当前最大值往后排 ——
  ///    「seq 是项目内序号」（交付命名靠它）；
  ///  · 物理文件**搬家不改名**（§6.4「原始文件永不改名」指的是文件名，
  ///    目录从源项目 raw/ 换到目标项目 raw/）；缩略图与 OCR 缓存随行；
  ///  · 文件先搬、库后改：库事务失败时把文件搬回去，不留"库说在 A
  ///    文件在 B"的中间态。
  Future<void> moveGroupToProject({
    required String fromProjectId,
    required String groupId,
    required String toProjectId,
  }) async {
    if (fromProjectId == toProjectId) {
      throw ArgumentError('目标项目与当前项目相同');
    }

    final target = await (_db.select(_db.projects)
          ..where((t) => t.id.equals(toProjectId)))
        .getSingleOrNull();
    if (target == null) throw StateError('目标项目不存在');

    final group = await (_db.select(_db.photoGroups)
          ..where((t) => t.id.equals(groupId)))
        .getSingleOrNull();
    if (group == null) throw StateError('组不存在');
    if (group.projectId != fromProjectId) {
      throw StateError('组不属于当前项目');
    }
    if (group.itemId != null) {
      throw StateError('该组已确认归属货品，请先撤销归属再移动');
    }
    if (group.category != PhotoCategory.precheck.code) {
      throw StateError('监装组不支持跨项目移动');
    }

    final photos = await (_db.select(_db.photos)
          ..where((t) => t.groupId.equals(groupId)))
        .get();
    if (photos.isEmpty) {
      // 空组没有文件要搬，直接换项目归属就行
      final seq = await _maxGroupSeq(toProjectId) + 1;
      await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
          .write(PhotoGroupsCompanion(
        projectId: Value(toProjectId),
        seq: Value(seq),
      ));
      return;
    }

    // 目标批次：source 跟随组来源（相机 / 相册），立即结束 ——
    // 搬过去的是"已完成的整批"，不能再被相机续拍续进去。
    final sessionId = _uuid.v4();
    final now = DateTime.now().millisecondsSinceEpoch;
    await _db.into(_db.captureSessions).insert(
          CaptureSessionsCompanion.insert(
            id: sessionId,
            projectId: toProjectId,
            source: Value(group.origin == GroupOrigin.album.code
                ? CaptureSource.album.code
                : CaptureSource.camera.code),
            startedAt: now,
            endedAt: Value(now),
            photoCount: Value(photos.length),
            note: const Value('跨项目移入'),
          ),
        );

    // ── 物理文件搬家（先于库事务；失败可整体搬回）──
    final moves = <({String from, String to})>[];
    for (final ph in photos) {
      moves.add((
        from: ph.filePath,
        to: p.join(
          (await ProjectPaths.rawDir(toProjectId, sessionId)).path,
          p.basename(ph.filePath),
        ),
      ));
      if (ph.thumbPath != null) {
        moves.add((
          from: ph.thumbPath!,
          to: await ProjectPaths.thumbPath(toProjectId, ph.id),
        ));
      }
      // OCR 缓存名 = {photoId}.json；缺了本来就允许（识别失败的照片没有）
      final ocrFile = File(p.join(
          (await ProjectPaths.ocrDir(fromProjectId)).path, '${ph.id}.json'));
      if (await ocrFile.exists()) {
        moves.add((
          from: ocrFile.path,
          to: p.join((await ProjectPaths.ocrDir(toProjectId)).path,
              '${ph.id}.json'),
        ));
      }
    }
    for (final m in moves) {
      await _moveFile(m.from, m.to);
    }

    try {
      await _db.transaction(() async {
        var photoSeq = await _maxPhotoSeq(toProjectId);
        for (final ph in photos) {
          photoSeq++;
          final newRaw = p.join(
            (await ProjectPaths.rawDir(toProjectId, sessionId)).path,
            p.basename(ph.filePath),
          );
          await (_db.update(_db.photos)..where((t) => t.id.equals(ph.id)))
              .write(PhotosCompanion(
            projectId: Value(toProjectId),
            sessionId: Value(sessionId),
            seq: Value(photoSeq),
            filePath: Value(newRaw),
            thumbPath: ph.thumbPath == null
                ? const Value.absent()
                : Value(await ProjectPaths.thumbPath(toProjectId, ph.id)),
          ));
        }
        await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
            .write(PhotoGroupsCompanion(
          projectId: Value(toProjectId),
          sessionId: Value(sessionId),
          seq: Value(await _maxGroupSeq(toProjectId) + 1),
        ));
      });
    } catch (_) {
      // 库没改成 —— 把文件搬回去，别留"库说在源项目、文件在目标项目"的悬空态
      for (final m in moves) {
        try {
          await _moveFile(m.to, m.from);
        } catch (_) {}
      }
      rethrow;
    }
  }

  /// 把 [fromProjectId] 的**全部**照片 / 组 / 批次 / 交付记录并进
  /// [toProjectId]（诉求③「项目合并」）。源项目归档（deletedAt 置位，
  /// 从项目列表消失，但清单与归属审计记录保留 —— 可追溯）。
  ///
  /// 边界（合并前必须全部满足，否则拒绝并说明为什么）：
  ///  · 源项目里不能有**仍处于已归属状态**的组 —— 归属挂在源项目货品上，
  ///    搬走会让交付证据链断裂；请先撤销归属。
  ///  · 目标项目不能就是自己。
  ///
  /// 批次 id / 组 id / 照片 id 全部原样保留（会话目录整目录搬家，
  /// 文件不改名）；组 seq / 照片 seq 按时间序接目标项目当前最大值
  /// 重排 —— 「seq 是项目内序号」。
  Future<void> mergeProjectInto({
    required String fromProjectId,
    required String toProjectId,
  }) async {
    if (fromProjectId == toProjectId) {
      throw ArgumentError('目标项目与源项目相同');
    }
    final target = await (_db.select(_db.projects)
          ..where((t) => t.id.equals(toProjectId)))
        .getSingleOrNull();
    if (target == null) throw StateError('目标项目不存在');

    final assigned = await (_db.select(_db.photoGroups)
          ..where((t) =>
              t.projectId.equals(fromProjectId) & t.itemId.isNotNull()))
        .get();
    if (assigned.isNotEmpty) {
      throw StateError(
          '源项目还有 ${assigned.length} 组已确认归属货品，请先撤销归属再合并');
    }

    final sessions = await (_db.select(_db.captureSessions)
          ..where((t) => t.projectId.equals(fromProjectId)))
        .get();
    final photos = await (_db.select(_db.photos)
          ..where((t) => t.projectId.equals(fromProjectId)))
        .get();
    final groups = await (_db.select(_db.photoGroups)
          ..where((t) => t.projectId.equals(fromProjectId)))
        .get();

    // ── 物理文件搬家：批次 raw/ 目录整目录 rename（快、原子）；──
    //    缩略图 / OCR 缓存按照片逐个搬。
    for (final s in sessions) {
      final srcDir = Directory(
          p.join((await ProjectPaths.projectDir(fromProjectId)).path,
              'raw', s.id));
      final dstDir = Directory(
          p.join((await ProjectPaths.projectDir(toProjectId)).path,
              'raw', s.id));
      if (await srcDir.exists()) {
        try {
          await srcDir.rename(dstDir.path);
        } on FileSystemException {
          // 跨分区等异常：退回逐文件复制
          await dstDir.create(recursive: true);
          await for (final e in srcDir.list()) {
            if (e is File) {
              final nf = File(p.join(dstDir.path, p.basename(e.path)));
              await e.copy(nf.path);
              await e.delete();
            }
          }
          await srcDir.delete();
        }
      }
    }
    final fileMoves = <({String from, String to})>[];
    for (final ph in photos) {
      if (ph.thumbPath != null) {
        fileMoves.add((
          from: ph.thumbPath!,
          to: await ProjectPaths.thumbPath(toProjectId, ph.id),
        ));
      }
      final ocrFile = File(p.join(
          (await ProjectPaths.ocrDir(fromProjectId)).path, '${ph.id}.json'));
      if (await ocrFile.exists()) {
        fileMoves.add((
          from: ocrFile.path,
          to: p.join((await ProjectPaths.ocrDir(toProjectId)).path,
              '${ph.id}.json'),
        ));
      }
    }
    for (final m in fileMoves) {
      await _moveFile(m.from, m.to);
    }

    try {
      await _db.transaction(() async {
        final now = DateTime.now().millisecondsSinceEpoch;

        // 新文件路径表（原始文件在目标项目的 raw/{sessionId}/ 下）
        final rawDirs = <String, String>{
          for (final s in sessions)
            s.id:
                p.join((await ProjectPaths.projectDir(toProjectId)).path,
                    'raw', s.id),
        };

        // 照片：换项目 + seq 按原序接目标最大值重排 + 路径改写
        var photoSeq = await _maxPhotoSeq(toProjectId);
        for (final ph in photos) {
          photoSeq++;
          await (_db.update(_db.photos)..where((t) => t.id.equals(ph.id)))
              .write(PhotosCompanion(
            projectId: Value(toProjectId),
            seq: Value(photoSeq),
            filePath: Value(
                p.join(rawDirs[ph.sessionId]!, p.basename(ph.filePath))),
            thumbPath: ph.thumbPath == null
                ? const Value.absent()
                : Value(await ProjectPaths.thumbPath(toProjectId, ph.id)),
          ));
        }

        // 组：换项目 + seq 按原相对次序接目标最大值重排
        var groupSeq = await _maxGroupSeq(toProjectId);
        final orderedGroups = [...groups]
          ..sort((a, b) => a.seq.compareTo(b.seq));
        for (final g in orderedGroups) {
          groupSeq++;
          await (_db.update(_db.photoGroups)..where((t) => t.id.equals(g.id)))
              .write(PhotoGroupsCompanion(
            projectId: Value(toProjectId),
            seq: Value(groupSeq),
          ));
        }

        // 批次：换项目即可（id 与 photoCount 原样）
        await (_db.update(_db.captureSessions)
              ..where((t) => t.projectId.equals(fromProjectId)))
            .write(CaptureSessionsCompanion(projectId: Value(toProjectId)));

        // 交付记录：历史凭证跟着照片走
        await (_db.update(_db.deliveries)
              ..where((t) => t.projectId.equals(fromProjectId)))
            .write(DeliveriesCompanion(projectId: Value(toProjectId)));

        // 源项目归档（不物理删 —— 清单 / 归属审计记录还要可追溯）
        await (_db.update(_db.projects)
              ..where((t) => t.id.equals(fromProjectId)))
            .write(ProjectsCompanion(deletedAt: Value(now)));
      });
    } catch (_) {
      // 库没改成 —— 把文件搬回去
      for (final m in fileMoves.reversed) {
        try {
          await _moveFile(m.to, m.from);
        } catch (_) {}
      }
      rethrow;
    }
  }

  Future<int> _maxPhotoSeq(String projectId) async {
    final row = await _db.customSelect(
      'SELECT COALESCE(MAX(seq), 0) AS m FROM photos WHERE project_id = ?',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photos},
    ).getSingle();
    return row.read<int>('m');
  }

  /// 搬一个文件：优先 rename（同分区零拷贝），跨分区退回 copy+delete。
  /// 源不存在 = 无事可做（缩略图/OCR 缓存本来就可能缺）。
  Future<void> _moveFile(String src, String dst) async {
    if (src == dst) return;
    final f = File(src);
    if (!await f.exists()) return;
    await Directory(p.dirname(dst)).create(recursive: true);
    try {
      await f.rename(dst);
    } on FileSystemException {
      await f.copy(dst);
      await f.delete();
    }
  }
}
