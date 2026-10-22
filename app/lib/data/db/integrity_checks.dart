import 'package:drift/drift.dart';

import '../../domain/model/delivery_readiness.dart';
import 'database.dart';

/// 交付包生成前的**强制校验** —— 实现设计方案 §6.3。
///
/// 这两条不是"统计"，是**不变式断言**。它们的期望值恒为 0，
/// 因为架构上不存在"机器写归属"的路径（合法归属必须先写
/// assignments 记录，再改 photos/photo_groups.itemId）。
///
/// 如果哪天真返回了非 0，说明有人绕过了 AssignService —— 那是阻断级缺陷。
class IntegrityChecks {
  IntegrityChecks(this._db);

  final AppDatabase _db;

  /// 校验 ①：不存在"有归属但没有确认记录"的照片。
  ///
  /// 期望恒为 0。
  Future<int> orphanPhotoAssignments(String projectId) async {
    final row = await _db.customSelect(
      r'''
      SELECT COUNT(*) AS c FROM photos p
      WHERE p.project_id = ? AND p.item_id IS NOT NULL AND p.state = 'confirmed'
        AND NOT EXISTS (
          SELECT 1 FROM assignments a
          WHERE a.target_type = 'photo' AND a.target_id = p.id
            AND a.confirmed_at IS NOT NULL AND a.revoked_at IS NULL
        )
      ''',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photos, _db.assignments},
    ).getSingle();
    return row.read<int>('c');
  }

  /// 校验 ②：不存在"有归属但没有确认时间"的组。
  ///
  /// 期望恒为 0。
  Future<int> orphanGroupAssignments(String projectId) async {
    final row = await _db.customSelect(
      r'''
      SELECT COUNT(*) AS c FROM photo_groups g
      WHERE g.project_id = ? AND g.item_id IS NOT NULL AND g.confirmed_at IS NULL
      ''',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photoGroups},
    ).getSingle();
    return row.read<int>('c');
  }

  /// 校验 ③：不阻塞交付，只用于灰度期评估建议质量（§9.1 指标 3）。
  ///
  /// 返回采纳率 0.0~1.0；无样本时返回 null。
  Future<double?> ocrAcceptRate(String projectId) async {
    final row = await _db.customSelect(
      r'''
      SELECT COUNT(*) AS total,
             SUM(CASE WHEN item_id = suggested_item_id THEN 1 ELSE 0 END) AS accepted
      FROM assignments
      WHERE project_id = ?
        AND source IN ('suggestion_confirmed', 'bulk_confirm')
        AND suggested_item_id IS NOT NULL
        AND revoked_at IS NULL
      ''',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.assignments},
    ).getSingle();

    final total = row.read<int>('total');
    if (total == 0) return null;
    final accepted = row.readNullable<int>('accepted') ?? 0;
    return accepted / total;
  }

  /// 「一键确认覆盖率」：被批量确认的照片 / 已确认照片总数（§9.1 指标 4）。
  Future<double?> bulkConfirmCoverage(String projectId) async {
    final row = await _db.customSelect(
      r'''
      SELECT
        (SELECT COUNT(*) FROM assignments
          WHERE project_id = ? AND target_type = 'group'
            AND source = 'bulk_confirm' AND revoked_at IS NULL) AS bulk,
        (SELECT COUNT(*) FROM assignments
          WHERE project_id = ? AND target_type = 'group'
            AND revoked_at IS NULL) AS total
      ''',
      variables: [Variable.withString(projectId), Variable.withString(projectId)],
      readsFrom: {_db.assignments},
    ).getSingle();
    final total = row.read<int>('total');
    if (total == 0) return null;
    return row.read<int>('bulk') / total;
  }

  /// 一次性跑完全部校验，供交付页使用。
  Future<DeliveryReadiness> readiness(String projectId) async {
    final a = await orphanPhotoAssignments(projectId);
    final b = await orphanGroupAssignments(projectId);

    final counts = await _db.customSelect(
      r'''
      SELECT
        (SELECT COUNT(*) FROM items
          WHERE project_id = ? AND deleted_at IS NULL AND state = 'normal') AS item_total,
        (SELECT COUNT(*) FROM items i
          WHERE i.project_id = ? AND i.deleted_at IS NULL AND i.state = 'normal'
            AND NOT EXISTS (
              SELECT 1 FROM photos p
              WHERE p.item_id = i.id AND p.state = 'confirmed')) AS item_gap,
        (SELECT COUNT(*) FROM photos
          WHERE project_id = ? AND state = 'unassigned') AS photo_unassigned,
        (SELECT COUNT(*) FROM photos
          WHERE project_id = ? AND state = 'confirmed') AS photo_confirmed,
        (SELECT COUNT(*) FROM photos
          WHERE project_id = ? AND state = 'unused') AS photo_unused
      ''',
      variables: List.generate(5, (_) => Variable.withString(projectId)),
      readsFrom: {_db.items, _db.photos},
    ).getSingle();

    return DeliveryReadiness(
      orphanPhotoAssignments: a,
      orphanGroupAssignments: b,
      itemTotal: counts.read<int>('item_total'),
      itemGap: counts.read<int>('item_gap'),
      photoUnassigned: counts.read<int>('photo_unassigned'),
      photoConfirmed: counts.read<int>('photo_confirmed'),
      photoUnused: counts.read<int>('photo_unused'),
    );
  }
}
