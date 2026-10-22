import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import '../../domain/model/enums.dart';
import '../../domain/model/project_summary.dart';
import '../db/database.dart';
import '../fs/project_paths.dart';

/// 项目仓储。所有对 projects 表的读写都从这里走。
///
/// 列表与工作台共用同一条聚合 SQL —— 保证两处显示的数字永远一致，
/// 不会出现"列表说还剩 3 组、点进去变 5 组"这种丢信任的事。
class ProjectRepository {
  ProjectRepository(this._db);

  final AppDatabase _db;
  static const _uuid = Uuid();

  /// 聚合 SELECT（不含 WHERE）。列表 / 回收站 / 单项目共用同一份，
  /// 只是 WHERE 子句不同（活跃 vs 已删除）。
  static const String _summarySelect = r'''
    SELECT
      p.id, p.name, p.client, p.created_at, p.status,
      (SELECT COUNT(*) FROM items i
        WHERE i.project_id = p.id AND i.deleted_at IS NULL AND i.state = 'normal')  AS item_total,
      (SELECT COUNT(*) FROM items i
        WHERE i.project_id = p.id AND i.deleted_at IS NULL
          AND EXISTS (SELECT 1 FROM photos ph
                      WHERE ph.item_id = i.id AND ph.state = 'confirmed'))         AS item_done,
      (SELECT COUNT(*) FROM photos ph WHERE ph.project_id = p.id)                    AS photo_total,
      (SELECT COUNT(*) FROM photos ph
        WHERE ph.project_id = p.id AND ph.state = 'confirmed')                       AS photo_confirmed,
      (SELECT COUNT(*) FROM photos ph
        WHERE ph.project_id = p.id AND ph.state = 'unassigned')                      AS photo_unassigned,
      (SELECT COUNT(*) FROM photos ph
        WHERE ph.project_id = p.id AND ph.group_id IS NULL
          AND ph.category = 'precheck')                                              AS photo_orphan,
      (SELECT COUNT(*) FROM photo_groups g
        WHERE g.project_id = p.id AND g.item_id IS NULL)                             AS group_pending
    FROM projects p
  ''';

  static const String _activeWhere = ' WHERE p.deleted_at IS NULL';
  static const String _deletedWhere = ' WHERE p.deleted_at IS NOT NULL';

  /// 项目列表页：全部**未删除**项目，按创建时间倒序。
  Stream<List<ProjectSummary>> watchAll() {
    return _db
        .customSelect(
          '$_summarySelect$_activeWhere ORDER BY p.created_at DESC',
          readsFrom: {_db.projects, _db.items, _db.photos, _db.photoGroups},
        )
        .watch()
        .map((rows) => rows.map(_mapSummary).toList());
  }

  /// 回收站：全部**已软删**的项目，按删除时间倒序。
  ///
  /// 软删只打 `deletedAt` 标记，DB 与磁盘照片**全部保留**（§宁多勿失），
  /// 所以这里的项目仍可一键恢复，或二次确认后彻底清盘（[purge]）。
  Stream<List<ProjectSummary>> watchDeleted() {
    return _db
        .customSelect(
          '$_summarySelect$_deletedWhere ORDER BY p.deleted_at DESC',
          readsFrom: {_db.projects, _db.items, _db.photos, _db.photoGroups},
        )
        .watch()
        .map((rows) => rows.map(_mapSummary).toList());
  }

  /// 工作台：单个项目的实时进度（仅活跃项目）。
  Stream<ProjectSummary?> watchOne(String projectId) {
    return _db
        .customSelect(
          '$_summarySelect$_activeWhere AND p.id = ?',
          variables: [Variable.withString(projectId)],
          readsFrom: {_db.projects, _db.items, _db.photos, _db.photoGroups},
        )
        .watchSingleOrNull()
        .map((row) => row == null ? null : _mapSummary(row));
  }

  Future<String> create({
    required String name,
    String? client,
    String? checklistFile,
  }) async {
    final id = _uuid.v4();
    await _db.into(_db.projects).insert(
          ProjectsCompanion.insert(
            id: id,
            name: name,
            createdAt: DateTime.now().millisecondsSinceEpoch,
            client: Value(client),
            checklistFile: Value(checklistFile),
          ),
        );
    return id;
  }

  Future<void> rename(String id, String name, {String? client}) async {
    await (_db.update(_db.projects)..where((t) => t.id.equals(id))).write(
      ProjectsCompanion(name: Value(name), client: Value(client)),
    );
  }

  Future<void> setStatus(String id, ProjectStatus status) async {
    await (_db.update(_db.projects)..where((t) => t.id.equals(id)))
        .write(ProjectsCompanion(status: Value(status.code)));
  }

  /// 软删除。项目文件与照片不物理删除 —— 现场数据宁多勿失。
  /// 列表因此隐藏它，但 [watchDeleted] 仍能找到，可 [restore] 或 [purge]。
  Future<void> softDelete(String id) async {
    await (_db.update(_db.projects)..where((t) => t.id.equals(id))).write(
      ProjectsCompanion(deletedAt: Value(DateTime.now().millisecondsSinceEpoch)),
    );
  }

  /// 从回收站恢复：清空 `deletedAt` 标记，项目重回列表。
  Future<void> restore(String id) async {
    await (_db.update(_db.projects)..where((t) => t.id.equals(id)))
        .write(const ProjectsCompanion(deletedAt: Value<int?>(null)));
  }

  /// 彻底清盘：**删除全部关联数据 + 磁盘目录**。
  ///
  /// ⚠️ 这是破坏性操作的终点，调用方必须先二次确认。
  /// 与 `softDelete` 相反，这里真的删：子表按依赖顺序级联删干净，
  /// 最后删项目目录（尽力而为，删不掉不报错）。
  Future<void> purge(String id) async {
    await _db.transaction(() async {
      // 依赖 photos 的子表（单列 subquery 取本项目的 photo id）
      final photoIdStmt = _db.selectOnly(_db.photos)
        ..addColumns([_db.photos.id])
        ..where(_db.photos.projectId.equals(id));
      await (_db.delete(_db.ocrTokens)
            ..where((t) => t.photoId.isInQuery(photoIdStmt)))
          .go();
      await (_db.delete(_db.itemPhotoExtras)
            ..where((t) => t.photoId.isInQuery(photoIdStmt)))
          .go();

      // 有 projectId 的列直接按项目删
      await (_db.delete(_db.assignments)
            ..where((t) => t.projectId.equals(id)))
          .go();

      // upload_tasks 依赖 deliveries（单列 subquery）
      final deliveryIdStmt = _db.selectOnly(_db.deliveries)
        ..addColumns([_db.deliveries.id])
        ..where(_db.deliveries.projectId.equals(id));
      await (_db.delete(_db.uploadTasks)
            ..where((t) => t.deliveryId.isInQuery(deliveryIdStmt)))
          .go();

      await (_db.delete(_db.deliveries)
            ..where((t) => t.projectId.equals(id)))
          .go();
      await (_db.delete(_db.photos)..where((t) => t.projectId.equals(id))).go();
      await (_db.delete(_db.photoGroups)
            ..where((t) => t.projectId.equals(id)))
          .go();
      await (_db.delete(_db.items)..where((t) => t.projectId.equals(id))).go();
      await (_db.delete(_db.captureSessions)
            ..where((t) => t.projectId.equals(id)))
          .go();

      // 项目行最后删
      await (_db.delete(_db.projects)..where((t) => t.id.equals(id))).go();
    });

    // 磁盘目录：尽力而为（清盘是收尾动作，删不掉不该报红）
    await _deleteProjectDir(id);
  }

  /// 回收站计数（列表底部"已删除 N 个"用）。
  Future<int> deletedCount() async {
    final row = await _db.customSelect(
      'SELECT COUNT(*) AS c FROM projects WHERE deleted_at IS NOT NULL',
      readsFrom: {_db.projects},
    ).getSingle();
    return row.read<int>('c');
  }

  ProjectSummary _mapSummary(QueryRow r) => ProjectSummary(
        id: r.read<String>('id'),
        name: r.read<String>('name'),
        client: r.readNullable<String>('client'),
        createdAt: DateTime.fromMillisecondsSinceEpoch(r.read<int>('created_at')),
        status: ProjectStatus.fromCode(r.read<String>('status')),
        itemTotal: r.read<int>('item_total'),
        itemDone: r.read<int>('item_done'),
        photoTotal: r.read<int>('photo_total'),
        photoConfirmed: r.read<int>('photo_confirmed'),
        photoUnassigned: r.read<int>('photo_unassigned'),
        photoOrphan: r.read<int>('photo_orphan'),
        groupPending: r.read<int>('group_pending'),
      );
}

/// 磁盘目录删除（private 顶层函数，避免给仓储加多余方法）。
Future<void> _deleteProjectDir(String projectId) async {
  try {
    final dir = await ProjectPaths.projectDir(projectId);
    if (await dir.exists()) await dir.delete(recursive: true);
  } catch (_) {
    // 尽力而为：目录可能已被清过或正被占用
  }
}
