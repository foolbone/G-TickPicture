import 'dart:io';

import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';

/// 迁移幂等性（2026-10-05 真机事故复盘）。
///
/// **事故现象**：装 v0.15.0 后打开 App 直接卡死，报
/// ```
/// SqliteException(1): while executing, duplicate column name: content_hash,
///   SQL logic error (code 1)
/// Causing statement: ALTER TABLE "photos" ADD COLUMN "content_hash" TEXT NULL;
/// ```
/// 项目列表整个读不出来，App 进不去。
///
/// **根因**（读 drift 2.31 源码确认，不是猜的）：
///   · `onUpgrade` **不在事务里** —— `db_base.dart` 的 `beforeOpen` 直接
///     `await _resolvedMigration.onUpgrade(...)`，没有 transaction 包裹；
///   · `user_version` 是在 `beforeOpen` 返回**之后**才写的
///     —— `engines.dart` 的 `_runMigrations`，注释原话
///     "We only update the schema version after migrations ran"。
///
/// 两者叠加就产生了一个致命中间态：**DDL 已落盘、版本号还是旧的**。
/// 一旦迁移执行到一半被中断（用户杀进程 / 系统回收 / 崩溃 /
/// 后一步 `createIndex` 抛错），下次启动会重跑同一条 ALTER，
/// 撞上"列已存在"，于是**永久性打不开** —— 重试一万次也一样。
///
/// 本文件的每条用例都在构造那个中间态，验证重开能自愈。
void main() {
  late Directory tmp;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('gtick_migrate_');
  });

  tearDown(() async {
    // 尽力而为：Windows 上文件锁偶发（见 photo_exif_test 的教训）
    for (var i = 0; i < 5; i++) {
      try {
        if (!tmp.existsSync()) return;
        await tmp.delete(recursive: true);
        return;
      } on FileSystemException {
        await Future<void>.delayed(const Duration(milliseconds: 200));
      }
    }
  });

  File dbFile() => File('${tmp.path}/g_tick_picture.sqlite');

  /// **不开迁移**的裸连接 —— 专供"造种子"和"看现状"用。
  ///
  /// ⚠️ 这是本文件最容易踩的坑，我踩了两轮才明白：
  ///
  /// drift 的 `beforeOpen` 是在**第一次 customStatement / 查询**时触发的
  /// （engines.dart `_runMigrations` 末尾 `await user.beforeOpen(...)`）。
  /// 也就是说 —— 只要你用**默认** `NativeDatabase` 打开一个 v3 库然后
  /// 随便读一行，迁移就已经跑完了、版本号也已经写成 5 了。
  ///
  /// 于是：
  ///   · 种子想造"半迁移库"，结果自己先触发了迁移 → 手工再 ADD COLUMN
  ///     就撞 `duplicate column name`（我第一版的红就是这个）；
  ///   · 想断言"迁移前 user_version == 3"，结果断言函数自己就是那次迁移
  ///     的触发者 → 断言拿到的是 5。
  ///
  /// `enableMigrations: false` 让 versionDelegate 变成 `NoVersionDelegate`，
  /// drift 直接假设"已是最新"，一条 DDL 都不跑。种子与探查必须全走这里。
  AppDatabase rawDb() => AppDatabase.forTesting(
        NativeDatabase(dbFile(), enableMigrations: false),
      );

  /// 会真正跑迁移的连接 —— 用来模拟用户打开 App。
  AppDatabase migratingDb() =>
      AppDatabase.forTesting(NativeDatabase(dbFile()));

  /// 跑一次迁移（等价于用户打开 App）。返回后版本号应已是 5。
  Future<void> openAndMigrate() async {
    final db = migratingDb();
    // 真读一行数据：只 assert 不抛异常太弱，建表失败也算"不抛"。
    await db.customSelect('SELECT COUNT(*) AS c FROM photos').getSingle();
    await db.close();
  }

  // ── 探查（全部走裸连接，理由见 rawDb 的注释）─────────────────
  // ⚠️ 位置很要紧：Dart 的局部函数**不能前向引用**，所以这三个必须
  // 排在 seedV3 之前（seedV3 内部要拿它们做前置断言）。

  Future<int> userVersion() async {
    final db = rawDb();
    final v = await db.customSelect('PRAGMA user_version').getSingle();
    final n = v.data.values.first as int;
    await db.close();
    return n;
  }

  Future<List<String>> columnsOf(String table) async {
    final db = rawDb();
    final rows = await db.customSelect('PRAGMA table_info($table)').get();
    await db.close();
    return [for (final r in rows) r.read<String>('name')];
  }

  Future<List<String>> indexesOfPhotos() async {
    final db = rawDb();
    final rows = await db.customSelect(
      "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='photos'",
    ).get();
    await db.close();
    return [for (final r in rows) r.read<String>('name')];
  }

  /// 造一个 v3 库：完整的表结构，但 photos **没有** content_hash，
  /// 且 user_version = 3 —— 这就是升级前的正常状态。
  ///
  /// ⚠️ **顺序陷阱**：SQLite 不允许 DROP 掉"被索引引用"的列，会报
  /// `error in index ... after drop column: no such column`。
  /// 必须先 `DROP INDEX` 再 `DROP COLUMN` —— 我第一版种子就是顺序
  /// 写反了，列压根没被删掉，探针跑出来 8 条红但理由是错的
  /// （学到：探针红了还要看**红的理由对不对**）。
  Future<void> seedV3() async {
    // 先用会迁移的连接建出当前（v5）结构，这样拿到的是 drift 真实
    // 生成的 DDL，不手抄一遍 SQL。
    await openAndMigrate();
    expect(await userVersion(), 5, reason: '前置：确认建出了 v5 结构');

    // 再用裸连接手工"退回"到 v3。
    final db = rawDb();
    await db.customStatement('DROP INDEX IF EXISTS photos_content_hash');
    await db.customStatement('ALTER TABLE photos DROP COLUMN content_hash');
    await db.customStatement('PRAGMA user_version = 3');
    await db.close();

    expect(await columnsOf('photos'), isNot(contains('content_hash')),
        reason: '前置：确认 v3 种子造对了（列真的没了）');
  }

  /// 事故现场的库：列**已在**（ADD COLUMN 已落盘），但 user_version 仍 3
  /// （setSchemaVersion 还没跑到），索引也没建。
  Future<void> seedHalfMigrated() async {
    await seedV3();
    final db = rawDb();
    await db.customStatement(
      'ALTER TABLE photos ADD COLUMN content_hash TEXT NULL',
    );
    // 索引故意不建 —— 模拟"死在 addColumn 之后、createIndex 之前"
    await db.close();
  }

  group('事故复现：列已存在、版本号还是 3', () {
    test('重开数据库不再抛 duplicate column（核心回归）', () async {
      await seedHalfMigrated();

      // 修复前：这里会抛
      //   SqliteException(1): duplicate column name: content_hash
      await openAndMigrate();
    });

    test('迁移后 version 被补齐到 5（否则下次还会重跑）', () async {
      await seedHalfMigrated();
      expect(await userVersion(), 3, reason: '前置：确认种子造的是 3');

      await openAndMigrate();

      expect(await userVersion(), 5,
          reason: '版本不补齐 = 下次启动重跑迁移 = 卡死循环');
    });

    test('缺失的索引被补建（列在、索引不在的中间态）', () async {
      await seedHalfMigrated();
      expect(await indexesOfPhotos(), isNot(contains('photos_content_hash')));

      await openAndMigrate();

      expect(await indexesOfPhotos(), contains('photos_content_hash'),
          reason: '索引缺了不影响判重功能，但结构会与全新库漂移');
    });

    test('content_hash 列没有重复出现', () async {
      await seedHalfMigrated();

      await openAndMigrate();

      final cols = await columnsOf('photos');
      expect(cols.where((c) => c == 'content_hash'), hasLength(1));
    });
  });

  group('连续重开不会退化（幂等不是一次性的）', () {
    test('连开三次都正常，结构稳定', () async {
      await seedHalfMigrated();

      for (var i = 0; i < 3; i++) {
        await openAndMigrate();
      }

      expect(await userVersion(), 5);
      final cols = await columnsOf('photos');
      expect(cols.where((c) => c == 'content_hash'), hasLength(1));
    });
  });

  group('正常路径没被改坏', () {
    test('v3 正常升级：列与索引都建出来', () async {
      await seedV3();
      expect(await columnsOf('photos'), isNot(contains('content_hash')));

      await openAndMigrate();

      expect(await columnsOf('photos'), contains('content_hash'));
      expect(await indexesOfPhotos(), contains('photos_content_hash'));
      expect(await userVersion(), 5);
    });

    test('全新库（onCreate 路径）不受影响', () async {
      await openAndMigrate();

      expect(await columnsOf('photos'), contains('content_hash'));
      expect(await indexesOfPhotos(), contains('photos_content_hash'));
      expect(await userVersion(), 5);
    });

    test('v1 老库连跳到 v5 也正常（多级 if 的组合路径）', () async {
      // user_version=1 + 手工砍掉 v2/v3/v4 的列，模拟最老的库。
      // ⚠️ 同样先删索引再删列（见 seedV3 的注释）。
      await openAndMigrate();
      final db0 = rawDb();
      await db0.customStatement('DROP INDEX IF EXISTS photos_content_hash');
      await db0.customStatement('ALTER TABLE photos DROP COLUMN content_hash');
      await db0.customStatement('ALTER TABLE photos DROP COLUMN category');
      await db0
          .customStatement('ALTER TABLE photo_groups DROP COLUMN category');
      await db0.customStatement('ALTER TABLE photo_groups DROP COLUMN carton');
      await db0
          .customStatement('ALTER TABLE items DROP COLUMN container_summary');
      await db0
          .customStatement('ALTER TABLE items DROP COLUMN source_line_count');
      await db0.customStatement('PRAGMA user_version = 1');
      await db0.close();

      // 确认种子真的造对了（v1/v2/v3 的列确实没了）
      expect(await columnsOf('photos'),
          isNot(anyOf(contains('content_hash'), contains('category'))));

      await openAndMigrate();

      final photos = await columnsOf('photos');
      expect(photos, containsAll(['content_hash', 'category']));
      final groups = await columnsOf('photo_groups');
      expect(groups, containsAll(['category', 'carton']));
      expect(await userVersion(), 5);
    });
  });

  group('事故的另一半：数据不能丢', () {
    test('半迁移库里的老照片行还在（修复不删数据）', () async {
      await seedHalfMigrated();

      // 塞一行"迁移前就在的老照片"。注意必须用裸连接写 ——
      // 用会迁移的连接写，第一句 insert 就把库迁到 v4 了，
      // 等于绕过了我们要验的中间态。
      final setup = rawDb();
      await setup.into(setup.projects).insert(
            ProjectsCompanion.insert(id: 'p1', name: '老项目', createdAt: 1),
          );
      await setup.into(setup.captureSessions).insert(
            CaptureSessionsCompanion.insert(
              id: 's1',
              projectId: 'p1',
              startedAt: 1,
            ),
          );
      await setup.into(setup.photos).insert(
            PhotosCompanion.insert(
              id: 'ph1',
              projectId: 'p1',
              sessionId: 's1',
              filePath: '/tmp/a.jpg',
              seq: 1,
              takenAt: 1,
              createdAt: 1,
            ),
          );
      await setup.close();

      // 修复流程
      final db = migratingDb();
      final rows = await (db.select(db.photos)
            ..where((p) => p.id.equals('ph1')))
          .getSingle();
      expect(rows.filePath, '/tmp/a.jpg');
      // 指纹是 NULL（= 还没算过），不是空串也不是被填了假值
      expect(rows.contentHash, isNull);
      await db.close();
    });
  });
}
