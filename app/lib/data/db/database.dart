import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';

import 'tables.dart';

part 'database.g.dart';

/// v5 数据修复（2026-10-14 真机 bug「改回预检的照片消失」）：
/// 把挂在**监装组**里的**预检照片**摘组，并清掉摘空的监装组。
///
/// 坏状态来源：v0.22.2 之前的 `setPhotosCategory` 只改照片行的
/// category、不动 group_id —— 整组标过监装的照片被改回预检后，
/// 留下「行是 precheck、组是 supervision」的两栖态：
/// 预检墙按组查看不到、监装墙按行查不显示、待入组信号
/// （group_id IS NULL）又不数它 —— 照片两墙同时消失且永不回来。
///
/// 幂等：修复后再跑一遍影响 0 行，migration 重入安全。
/// migration 与回归测试共用这一份 SQL —— 修复逻辑不许有两份。
Future<void> rescueMisfiledPrecheckPhotos(DatabaseConnectionUser db) async {
  // ① 摘组：预检照片从监装组里拿出来（group_id = NULL → 待入组信号
  //    > 0 → regroup 自动把它们重新聚成预检组）。
  await db.customStatement(
    'UPDATE photos SET group_id = NULL '
    "WHERE category = 'precheck' AND group_id IS NOT NULL AND group_id IN "
    "(SELECT id FROM photo_groups WHERE category = 'supervision')",
  );
  // ② 清掉摘空的监装组（不进任何流，空着只是脏数据）。
  //    只清「无归属的监装组」—— 有 itemId 的组绝不碰（防御）。
  await db.customStatement(
    "DELETE FROM photo_groups WHERE category = 'supervision' "
    'AND item_id IS NULL AND id NOT IN '
    '(SELECT group_id FROM photos WHERE group_id IS NOT NULL)',
  );
}

/// 检索索引的**变更版本**表 + 触发器（2026-10-15 v0.24.1）。
///
/// 用途：`PhotoSearchRepository` 把「照片 → 编码」建了内存索引缓存，
/// 后续搜索只付内存比对；但这套缓存必须能**及时失效** —— 拍完新照片
/// 回来搜不到是不能接受的。
///
/// 为什么不用 `PRAGMA data_version`：它对**同一连接自己的提交**不递增
/// （SQLite 文档原文），而 App 全程单连接（drift 单例）—— 用它等于
/// 缓存永不失效。
///
/// 所以用触发器：五张业务表（photos / items / photo_groups /
/// ocr_tokens / projects）上各挂 INSERT / UPDATE / DELETE 三个触发器，
/// 任何写事务提交都把版本号 +1。检索前读一次版本号即可判断索引是否
/// 过期。**写入侧零改动** —— 没有哪个仓储需要知道检索索引的存在。
///
/// 幂等：全部 `IF NOT EXISTS`，在 beforeOpen 里每次打开都执行（16 条
/// DDL，微秒级）；新库（createAll）与老库走同一条路径，结构不漂。
Future<void> ensureSearchIndexVersion(DatabaseConnectionUser db) async {
  await db.customStatement(
    'CREATE TABLE IF NOT EXISTS search_index_version ('
    'id INTEGER PRIMARY KEY CHECK (id = 0), '
    'v INTEGER NOT NULL DEFAULT 0)',
  );
  await db.customStatement(
    'INSERT OR IGNORE INTO search_index_version (id, v) VALUES (0, 0)',
  );
  for (final t in const [
    'photos',
    'items',
    'photo_groups',
    'ocr_tokens',
    'projects',
  ]) {
    for (final op in const ['INSERT', 'UPDATE', 'DELETE']) {
      await db.customStatement(
        'CREATE TRIGGER IF NOT EXISTS trg_${t}_search_index_$op '
        'AFTER $op ON $t BEGIN '
        'UPDATE search_index_version SET v = v + 1 WHERE id = 0; END',
      );
    }
  }
}

/// 读检索索引的当前版本号（[ensureSearchIndexVersion] 保证表存在）。
Future<int> readSearchIndexVersion(DatabaseConnectionUser db) async {
  final row = await db
      .customSelect('SELECT v FROM search_index_version WHERE id = 0')
      .getSingle();
  return row.read<int>('v');
}

/// 系统相机收图账本（2026-10-21）。
///
/// 为什么用 raw SQL 而不是 drift 表：
///  · 同步收图链路需要一个「项目 + 原图路径」唯一键做幂等，避免
///    「进程被杀后恢复重收」/「晚到推送与新会话首批重叠」重复入库；
///  · 加 drift 表要重新跑 build_runner 生成 database.g.dart，代价大；
///  · 这张表只被 CaptureRepository 的几个方法读写，不参与 drift 流。
///
/// 新建库与老库都走 beforeOpen（幂等 CREATE IF NOT EXISTS），
/// 所以不需要动 schemaVersion / 迁移分支。
Future<void> ensureSystemCaptureLedger(DatabaseConnectionUser db) async {
  await db.customStatement(
    'CREATE TABLE IF NOT EXISTS system_capture_shots ('
    'id TEXT NOT NULL PRIMARY KEY, '
    'session_id TEXT NOT NULL, '
    'project_id TEXT NOT NULL, '
    'source_path TEXT NOT NULL, '
    'source_size INTEGER, '
    'source_mtime INTEGER, '
    'taken_at INTEGER, '
    'state TEXT NOT NULL DEFAULT \'seen\', '
    'photo_id TEXT, '
    'error TEXT, '
    'updated_at INTEGER NOT NULL, '
    'UNIQUE (project_id, source_path))',
  );
  await db.customStatement(
    'CREATE INDEX IF NOT EXISTS system_capture_shots_state '
    'ON system_capture_shots (project_id, state)',
  );
  await db.customStatement(
    'CREATE INDEX IF NOT EXISTS system_capture_shots_session '
    'ON system_capture_shots (session_id)',
  );
}

/// 应用数据库。
///
/// 只在 `lib/data/` 下被 import —— 由 tools/check_architecture.ps1 强制。
/// domain 与 ui 层只能通过 Repository 访问（设计方案 §3.3）。
@DriftDatabase(
  tables: [
    Projects,
    Items,
    CaptureSessions,
    PhotoGroups,
    Photos,
    OcrTokens,
    Assignments,
    Deliveries,
    UploadTasks,
    ItemPhotoExtras,
    AppSettings,
  ],
)
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(driftDatabase(name: 'g_tick_picture'));

  /// 测试用：注入内存数据库
  AppDatabase.forTesting(super.e);

  @override
  int get schemaVersion => 5;

  /// 表 `table` 是否已有 `column` 列。
  ///
  /// **这个探测是 2026-10-05 一次真机事故逼出来的**，不要"优化"掉。
  Future<bool> _hasColumn(String table, String column) async {
    final cols = await customSelect('PRAGMA table_info($table)').get();
    return cols.any((r) => r.read<String>('name') == column);
  }

  /// 索引 `name` 是否已存在。
  Future<bool> _hasIndex(String name) async {
    final rows = await customSelect(
      "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
      variables: [Variable.withString(name)],
    ).get();
    return rows.isNotEmpty;
  }

  /// 加列；**已存在就跳过**。
  ///
  /// 为什么必须有这个幂等保护（2026-10-05 事故复盘）：
  /// drift 的 `onUpgrade` **不在事务里**（db_base.dart 里 `beforeOpen`
  /// 直接 await，没有 transaction 包裹），而 `user_version` 是在
  /// `beforeOpen` 返回**之后**才写的（engines.dart `_runMigrations`
  /// 的注释原话："We only update the schema version after migrations ran"）。
  ///
  /// 于是只要迁移执行到一半被中断 —— 用户杀进程、系统回收、崩溃，
  /// 或后一步 `createIndex` 抛错 —— 就留下「DDL 已落盘、版本号还是旧的」
  /// 这个中间态。**下次启动重跑同一条 ALTER，报 `duplicate column name`
  /// 直接卡死，点多少次重试都不会好。**
  ///
  /// 真机症状：`duplicate column name: content_hash, SQL logic error
  /// (code 1)`，`Causing statement: ALTER TABLE "photos" ADD COLUMN ...`。
  Future<void> _addColumnIfMissing(
    TableInfo table,
    GeneratedColumn column,
  ) async {
    if (await _hasColumn(table.entityName, column.name)) return;
    await createMigrator().addColumn(table, column);
  }

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (m) async {
          await m.createAll();
        },
        onUpgrade: (m, from, to) async {
          // v1 → v2（P4 诉求 1）：Items 增加箱号汇总额与原行数。
          // 纯增列，老数据补默认值即可 —— 已导入的清单没有箱号信息，
          // 留 NULL / 1 是**语义正确**的（那时确实没采集这个字段）。
          if (from < 2) {
            await _addColumnIfMissing(items, items.containerSummary);
            await _addColumnIfMissing(items, items.sourceLineCount);
          }
          // v2 → v3（老板 2026-09-27 拍板）：
          //   · photos.category / photo_groups.category —— 预检 / 监装 两大部分
          //   · photo_groups.carton —— **用户指定**的箱号（交付分文件夹依据）
          //
          // 三列都是**默认 precheck / NULL**，老数据不需要回填：
          // 老照片按预检处理（交付不丢照片），箱号等人在整理页指定。
          // 这是语义正确的默认值，不是"先凑合" —— 见 enums.dart 的注释。
          if (from < 3) {
            await _addColumnIfMissing(photos, photos.category);
            await _addColumnIfMissing(photoGroups, photoGroups.category);
            await _addColumnIfMissing(photoGroups, photoGroups.carton);
          }
          // v3 → v4（老板 2026-10-04「照片不能重复」）：
          //   · photos.content_hash —— 内容指纹，查重的唯一依据。
          //
          // **只加列不回填**：老照片一律 NULL（= 还没算过，不是"不重复"）。
          // 现场项目动辄上千张，迁移里同步算指纹会把升级卡死几分钟；
          // 交给 backfillHashes 在进照片页时后台分批补算，补算完才开始提示。
          if (from < 4) {
            await _addColumnIfMissing(photos, photos.contentHash);
            // 索引名与 tables.dart 的 @TableIndex 必须一致，否则
            // 全新库（createAll 建的）与迁移库（这里建的）结构会漂。
            //
            // ⚠️ 第二参是**完整的 CREATE INDEX 语句**，不是列名 ——
            // 写错会让 drift 把裸串当整条 SQL 执行，报
            // `near "content_hash": syntax error`（2026-10-05 踩过）。
            if (!await _hasIndex('photos_content_hash')) {
              await m.createIndex(
                Index(
                  'photos_content_hash',
                  'CREATE INDEX photos_content_hash ON photos (content_hash)',
                ),
              );
            }
          }
          // v4 → v5（2026-10-14「全部改回预检后照片消失」存量自愈）：
          // v0.22.2 之前改档只改照片行不摘组，留下「行是预检、组是
          // 监装」的两栖坏数据。摘组 → 待入组信号恢复 → regroup 自动
          // 重新聚成预检组；摘空的监装组一并清掉。纯数据修复，幂等。
          if (from < 5) {
            await rescueMisfiledPrecheckPhotos(this);
          }
        },
        beforeOpen: (details) async {
          // 外键约束：项目删除时级联清掉子表，避免孤儿数据
          await customStatement('PRAGMA foreign_keys = ON');
          // 检索索引版本表 + 触发器（v0.24.1）：让搜索缓存能及时失效，
          // 又不逼任何仓储知道检索索引的存在。幂等，新老库同一路径。
          await ensureSearchIndexVersion(this);
          // 系统相机收图账本（2026-10-21）：raw SQL 建表，幂等。
          await ensureSystemCaptureLedger(this);
        },
      );
}
