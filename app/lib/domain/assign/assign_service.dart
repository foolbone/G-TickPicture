import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import '../../core/constants.dart';
import '../../core/logger.dart';
import '../../data/db/database.dart';
import '../model/bulk_confirm_candidate.dart';
import '../model/enums.dart';

/// 归属决策服务 —— **全应用唯一允许写 `itemId` 的地方**。
///
/// 设计方案 §7.4。三条不可动摇的约定：
///
///   1. 每个写入口都必须带 [deviceName]（免登录下的最小身份标识）。
///      没有"系统自动写归属"的调用路径。
///
///   2. 事务内**先写 assignments 记录，再改 itemId**。
///      这个顺序保证了一个不变式：任何时刻都不存在
///      "有归属但没有决策记录"的状态。若反过来（先改 itemId 后写记录），
///      中途崩溃就会留下一条无据可查的归属，而它可能流入交付包。
///      整个 v3.0 的正确性保证就落在这条顺序上。
///
///   3. 撤销是**打 revokedAt 标记，不是删除**。留痕才能复盘。
class AssignService {
  AssignService(this._db, {required this.deviceName});

  final AppDatabase _db;

  /// 设备昵称。免登录场景下这是能做到的最小身份追踪。
  final String deviceName;

  static const _uuid = Uuid();

  // ═══════════════════════════════════════════════════════════
  // 核心写入
  // ═══════════════════════════════════════════════════════════

  /// 确认一个组的归属（用户点 ✓ 或采纳建议）。
  Future<void> confirmGroup(
    String groupId, {
    required String itemId,
    required AssignSource source,
    String? suggestedItemId,
    double? suggestionConf,
    String? note,
  }) async {
    await _db.transaction(() async {
      final now = DateTime.now().millisecondsSinceEpoch;
      final projectId = await _projectOfGroup(groupId);

      // ① 吊销该组此前未吊销的决策记录（改派场景）
      await (_db.update(_db.assignments)
            ..where((t) =>
                t.targetType.equals(AssignTargetType.group.code) &
                t.targetId.equals(groupId) &
                t.revokedAt.isNull()))
          .write(AssignmentsCompanion(revokedAt: Value(now)));

      // ② 先写决策记录 —— 顺序不可颠倒
      await _db.into(_db.assignments).insert(
            AssignmentsCompanion.insert(
              id: _uuid.v4(),
              projectId: projectId,
              targetType: AssignTargetType.group.code,
              targetId: groupId,
              itemId: itemId,
              source: source.code,
              suggestedItemId: Value(suggestedItemId),
              suggestionConf: Value(suggestionConf),
              confirmedAt: now,
              confirmedBy: deviceName,
              note: Value(note),
            ),
          );

      // ③ 再更新组
      await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
          .write(PhotoGroupsCompanion(
        itemId: Value(itemId),
        confirmedAt: Value(now),
      ));

      // ④ 以及组内所有照片
      await (_db.update(_db.photos)..where((t) => t.groupId.equals(groupId)))
          .write(PhotosCompanion(
        itemId: Value(itemId),
        state: Value(PhotoState.confirmed.code),
      ));
    });
  }

  /// 单张照片指派（拆分组后逐张处理、或"一照多货"的主归属）。
  Future<void> confirmPhoto(
    String photoId, {
    required String itemId,
    required AssignSource source,
    String? suggestedItemId,
    double? suggestionConf,
  }) async {
    await _db.transaction(() async {
      final now = DateTime.now().millisecondsSinceEpoch;
      final projectId = await _projectOfPhoto(photoId);

      await (_db.update(_db.assignments)
            ..where((t) =>
                t.targetType.equals(AssignTargetType.photo.code) &
                t.targetId.equals(photoId) &
                t.revokedAt.isNull()))
          .write(AssignmentsCompanion(revokedAt: Value(now)));

      await _db.into(_db.assignments).insert(
            AssignmentsCompanion.insert(
              id: _uuid.v4(),
              projectId: projectId,
              targetType: AssignTargetType.photo.code,
              targetId: photoId,
              itemId: itemId,
              source: source.code,
              suggestedItemId: Value(suggestedItemId),
              suggestionConf: Value(suggestionConf),
              confirmedAt: now,
              confirmedBy: deviceName,
            ),
          );

      await (_db.update(_db.photos)..where((t) => t.id.equals(photoId)))
          .write(PhotosCompanion(
        itemId: Value(itemId),
        state: Value(PhotoState.confirmed.code),
      ));
    });
  }

  // ═══════════════════════════════════════════════════════════
  // 批量确认（整理页最显眼的那个按钮）
  // ═══════════════════════════════════════════════════════════

  /// 预览"一键确认高置信"会处理哪些组 —— **必须先给用户看，再执行**。
  ///
  /// 准入条件（三条同时满足）：
  ///   · 组级置信度 ≥ [AppConst.bulkConfirmThreshold]
  ///   · 组内建议一致（suggestState == pending，不是 conflict）
  ///   · 该货品未被其他组占用（一个货品只允许一个主组）
  Future<List<PhotoGroup>> previewBulkConfirm(String projectId) async {
    final taken = await _assignedItemIds(projectId);
    final candidates = await (_db.select(_db.photoGroups)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.itemId.isNull() &
              t.suggestState.equals(GroupSuggestState.pending.code) &
              t.suggestionConf.isBiggerOrEqualValue(
                  AppConst.bulkConfirmThreshold))
          ..orderBy([(t) => OrderingTerm.desc(t.suggestionConf)]))
        .get();

    final out = <PhotoGroup>[];
    final claimed = <String>{...taken};
    for (final g in candidates) {
      final iid = g.suggestedItemId;
      if (iid == null) continue;
      if (claimed.contains(iid)) continue;      // 同一货品已有一组 → 交给人
      claimed.add(iid);
      out.add(g);
    }
    return out;
  }

  /// 预览的**可复核版**：带上清单编码/品名/张数，供 UI 弹窗逐行展示。
  ///
  /// 准入条件与 [previewBulkConfirm] 完全一致（§5.4 S3：必须先给用户看，
  /// 再执行）；差别只是把 PhotoGroup 行补充成 UI 能直接显示的投影 ——
  /// UI 层不能 import data/，所以返回 domain/model/ 里的
  /// [BulkConfirmCandidate]。
  Future<List<BulkConfirmCandidate>> previewBulkConfirmDetailed(
    String projectId,
  ) async {
    final rows = await previewBulkConfirm(projectId);
    if (rows.isEmpty) return const [];

    final ids = rows.map((g) => g.suggestedItemId).whereType<String>().toSet();
    final itemRows = await (_db.select(_db.items)
          ..where((t) => t.id.isIn(ids)))
        .get();
    final byId = {for (final it in itemRows) it.id: it};

    return [
      for (final g in rows)
        if (g.suggestedItemId != null)
          BulkConfirmCandidate(
            groupId: g.id,
            itemId: g.suggestedItemId!,
            code: byId[g.suggestedItemId]?.code ?? '?',
            name: byId[g.suggestedItemId]?.name ?? '',
            confidence: g.suggestionConf ?? 0,
            photoCount: g.photoCount,
          ),
    ];
  }

  /// 执行批量确认。返回处理的组数。
  Future<int> bulkConfirmHighConfidence(String projectId) async {
    final targets = await previewBulkConfirm(projectId);
    if (targets.isEmpty) return 0;

    var n = 0;
    for (final g in targets) {
      final iid = g.suggestedItemId;
      if (iid == null) continue;
      await confirmGroup(
        g.id,
        itemId: iid,
        source: AssignSource.bulkConfirm,
        suggestedItemId: iid,
        suggestionConf: g.suggestionConf,
      );
      n++;
    }
    Log.i('AssignService', '批量确认 $n 组 / 项目 $projectId');
    return n;
  }

  // ═══════════════════════════════════════════════════════════
  // 撤销
  // ═══════════════════════════════════════════════════════════

  /// 撤销一个组的归属。回到"待确认"。
  ///
  /// 注意：**只吊销记录，不删记录**。撤销后 assignments 里仍有痕迹，
  /// 这样"谁在什么时候改过什么"永远查得到。
  Future<void> revokeGroup(String groupId) async {
    await _db.transaction(() async {
      final now = DateTime.now().millisecondsSinceEpoch;

      await (_db.update(_db.assignments)
            ..where((t) =>
                t.targetType.equals(AssignTargetType.group.code) &
                t.targetId.equals(groupId) &
                t.revokedAt.isNull()))
          .write(AssignmentsCompanion(revokedAt: Value(now)));

      await (_db.update(_db.photoGroups)..where((t) => t.id.equals(groupId)))
          .write(const PhotoGroupsCompanion(
        // ⚠️ 必须 Value(null)（清空），不是 Value.absent()（跳过不改）——
        //    旧版这里写成了 absent，撤销动作对 itemId 是**空操作**：
        //    决策记录吊销了，但组和照片的归属原样留着，组永远回不到
        //    待办流。这正是真机「无法修改」的另一半根因
        //    （2026-09-24 仓储测试 watchAssignedGroups 抓出来的）。
        itemId: Value(null),
        confirmedAt: Value(null),
      ));

      // 注意：这里不能写 `const PhotosCompanion(...)` —— `PhotoState.x.code`
      // 是枚举的**实例** getter，const 上下文里取不到（const_eval_property_access）。
      // 去掉外层 const 即可，Value 自身的 const 保留。
      await (_db.update(_db.photos)..where((t) => t.groupId.equals(groupId)))
          .write(PhotosCompanion(
        itemId: const Value(null), // 同上：清空，不是 absent
        state: Value(PhotoState.unassigned.code),
      ));
    });
  }

  /// 把一组照片标记为「未使用」（环境照 / 废片）。
  /// 它们不改归属，只在交付时进 `_未使用/`。
  Future<void> markUnused(String groupId) async {
    await (_db.update(_db.photos)..where((t) => t.groupId.equals(groupId)))
        .write(PhotosCompanion(state: Value(PhotoState.unused.code)));
  }

  // ═══════════════════════════════════════════════════════════
  // 内部
  // ═══════════════════════════════════════════════════════════

  /// 已被占用的货品 id（每一件货只允许一个主组）。
  Future<Set<String>> _assignedItemIds(String projectId) async {
    final rows = await _db.customSelect(
      r'''
      SELECT DISTINCT item_id FROM photo_groups
      WHERE project_id = ? AND item_id IS NOT NULL
      ''',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photoGroups},
    ).get();
    return rows.map((r) => r.read<String>('item_id')).toSet();
  }

  Future<String> _projectOfGroup(String groupId) async {
    final row = await (_db.select(_db.photoGroups)
          ..where((t) => t.id.equals(groupId))
          ..limit(1))
        .getSingle();
    return row.projectId;
  }

  Future<String> _projectOfPhoto(String photoId) async {
    final row = await (_db.select(_db.photos)
          ..where((t) => t.id.equals(photoId))
          ..limit(1))
        .getSingle();
    return row.projectId;
  }
}
