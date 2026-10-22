// hide isNull / isNotNull：drift 的列扩展与 matcher 的断言重名 —— 测试里要的是断言
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/core/naming.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/fs/project_paths.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/assign/assign_service.dart';
import 'package:g_tick_picture/domain/export/delivery_plan_builder.dart';
import 'package:g_tick_picture/domain/export/export_service.dart';
import 'package:g_tick_picture/domain/export/export_service_impl.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:path/path.dart' as p;

/// 交付模块契约测试 —— M5。
///
/// 断言的是**交付包的形状**，不是实现细节。三件事必须有断言：
///   1. **命名自带身份**：`{3位货品序号}_{编码}_{2位张序}.jpg`
///      —— 文件名一旦退化成 `001.jpg`，报告员就失去了唯一线索。
///   2. **归属完整性异常留痕**（老板 09-26 拍板：交付不设限制条件）：
///      orphan > 0 不再拒绝打包，manifest 记录异常数。
///   3. **覆盖率不是闸门**：缺口照样能交付。
void main() {
  late AppDatabase db;
  late CaptureRepository capture;
  late AssignService assign;
  late ProjectRepository projects;
  late DeliveryPlanBuilder builder;
  late String projectId;
  late Directory tmpRoot;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    capture = CaptureRepository(db);
    assign = AssignService(db, deviceName: '测试机');
    projects = ProjectRepository(db);
    builder = DeliveryPlanBuilder(db);
    projectId = await projects.create(name: '交付测试');

    // ProjectPaths 走磁盘 —— 测试里指到临时目录
    tmpRoot = await Directory.systemTemp.createTemp('gt_delivery_test_');
    ProjectPaths.overrideRootForTest(tmpRoot);
  });

  tearDown(() async {
    ProjectPaths.overrideRootForTest(null);
    await db.close();
    if (await tmpRoot.exists()) {
      await tmpRoot.delete(recursive: true);
    }
  });

  // ── 夹具 ────────────────────────────────────────────────

  DateTime t(int sec) => DateTime(2026, 9, 23, 10, 0, sec);

  /// 导入货品清单。返回 itemId 列表（顺序与传入一致）。
  ///
  /// 直接插库而不是走 ChecklistImporter —— 这里测的是交付，
  /// 不该把导入逻辑的错误混进来。
  ///
  /// ⚠️ `seq` 从 **1** 起（不是 0）—— 它是"清单行序"，
  ///    也是平铺命名里 3 位序号的来源。用 0 会得到 `000_` 前缀，
  ///    看起来"能用"但语义是错的（见 ItemRepository.nextSeq 的初值）。
  Future<List<String>> importItems(List<(String code, String name)> defs) async {
    final ids = <String>[];
    for (var i = 0; i < defs.length; i++) {
      final id = 'item-$i';
      await db.into(db.items).insert(
            ItemsCompanion.insert(
              id: id,
              projectId: projectId,
              seq: i + 1,
              code: defs[i].$1,
              codeSafe: safeFileName(defs[i].$1),
              name: Value(defs[i].$2),
            ),
          );
      ids.add(id);
    }
    return ids;
  }

  /// 拍 [n] 张照片（真的落文件，打包会 copy），返回 photoId 列表。
  Future<List<String>> shoot(int n, {String filePrefix = 'p'}) async {
    final s = await capture.startSession(projectId);
    final photos = [
      for (var i = 0; i < n; i++)
        NewPhoto(
          sessionId: s,
          filePath: p.join(tmpRoot.path, '$filePrefix${i + 1}.jpg'),
          seq: i + 1,
          takenAt: t(i * 10),
          bytes: 1024,
        ),
    ];
    final ids = await capture.insertPhotos(projectId, photos);
    await capture.endSession(s);
    for (final ph in photos) {
      await File(ph.filePath).writeAsBytes(List<int>.filled(64, 0xFF));
    }
    return ids;
  }

  /// 确认归属（走 AssignService —— 唯一合法写入口）。
  Future<void> confirmPhoto(String photoId, String itemId) =>
      assign.confirmPhoto(
        photoId,
        itemId: itemId,
        source: AssignSource.manual,
      );

  /// 带箱号的货品夹具（containerSummary 直插库）。
  ///
  /// 与 importItems 分开的原因：seq 必须由测试显式给出并保持唯一，
  /// 它同时决定平铺名里的 3 位序号。
  Future<String> importItemCarton(
    String code,
    String name,
    String? carton, {
    required int seq,
  }) async {
    final id = 'item-c$seq';
    await db.into(db.items).insert(
          ItemsCompanion.insert(
            id: id,
            projectId: projectId,
            seq: seq,
            code: code,
            codeSafe: safeFileName(code),
            name: Value(name),
            containerSummary: Value(carton),
          ),
        );
    return id;
  }

  /// 直接改库制造"无据可查的归属"（绕过 AssignService 的损坏态）。
  Future<void> corruptItemId(String photoId, String ghostItemId) =>
      (db.update(db.photos)..where((x) => x.id.equals(photoId)))
          .write(PhotosCompanion(itemId: Value(ghostItemId)));

  // ── M6 夹具（老板 2026-09-27 拍板）─────────────────────────

  /// 模拟「整理时给这组照片指定箱号」—— 造一个组并把 carton 挂上去。
  ///
  /// ⚠️ 分箱只认**组上的 carton**（人输入的），不认清单的
  /// containerSummary —— 这是 09-27 的语义反转，测试必须走这条路径，
  /// 否则测的还是旧语义。
  Future<void> setCarton(List<String> photoIds, String? carton) async {
    final s = await capture.startSession(projectId);
    final gid = 'grp-${photoIds.join('_')}';
    await db.into(db.photoGroups).insert(
          PhotoGroupsCompanion.insert(
            id: gid,
            projectId: projectId,
            sessionId: s,
            seq: 1,
            createdAt: t(0).millisecondsSinceEpoch,
            carton: Value(carton),
          ),
        );
    await capture.endSession(s);
    await (db.update(db.photos)..where((x) => x.id.isIn(photoIds)))
        .write(PhotosCompanion(groupId: Value(gid)));
  }

  /// 模拟「整理时把这张/这些照片标为监装」。
  Future<void> markSupervision(List<String> photoIds) =>
      (db.update(db.photos)..where((x) => x.id.isIn(photoIds))).write(
            PhotosCompanion(category: Value(PhotoCategory.supervision.code)),
          );

  /// 模拟「这张不用」。
  Future<void> markUnused(List<String> photoIds) =>
      (db.update(db.photos)..where((x) => x.id.isIn(photoIds)))
          .write(const PhotosCompanion(state: Value('unused')));

  // ═════════════════════════════════════════════════════════
  // 1. 平铺命名
  // ═════════════════════════════════════════════════════════

  group('平铺命名', () {
    test('flatDeliveryName 格式为 {3位货品序号}_{编码}_{2位张序}.jpg', () {
      expect(
        flatDeliveryName(itemSeq: 7, codeSafe: '103010013345AMX', index: 2),
        '007_103010013345AMX_02.jpg',
      );
      expect(
        flatDeliveryName(itemSeq: 1, codeSafe: 'BOX-M11', index: 1),
        '001_BOX-M11_01.jpg',
      );
      // 超过 999 件也不截断（补零只保证最小宽度）
      expect(
        flatDeliveryName(itemSeq: 1234, codeSafe: 'X', index: 10),
        '1234_X_10.jpg',
      );
    });

    test('相册导入的 unsafe 字符已被 safeFileName 清掉，平铺名合法', () {
      // 原始编码保留在 items.code（用于显示与匹配），
      // 文件名只用 codeSafe（§5.1 硬性要求：两者都要留）
      const raw = 'A/B:C*D?E"F<G>H|I';
      final safe = safeFileName(raw);
      expect(safe, 'A_B_C_D_E_F_G_H_I');
      final name = flatDeliveryName(itemSeq: 1, codeSafe: safe, index: 1);
      for (final ch in AppConstTestHelper.unsafeChars) {
        expect(name.contains(ch), isFalse, reason: '文件名不得含 $ch');
      }
    });
  });

  // ═════════════════════════════════════════════════════════
  // 2. 计划构建
  // ═════════════════════════════════════════════════════════

  group('DeliveryPlanBuilder', () {
    test('按货品归拢照片，平铺名与张序正确', () async {
      final itemIds = await importItems([
        ('BOX-M11', '底板'),
        ('BOX-M12', '侧板'),
      ]);

      final photoIds = await shoot(3, filePrefix: 'a');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await confirmPhoto(photoIds[1], itemIds[0]);
      await confirmPhoto(photoIds[2], itemIds[1]);

      final plan = await builder.build(projectId);

      expect(plan.itemTotal, 2);
      expect(plan.photoCount, 3);
      expect(plan.itemDone, 2);
      expect(plan.gapCount, 0);

      // 09-27 起包内先分「预检 / 监装」，所以命名带 预检/ 前缀
      final first = plan.items.firstWhere((i) => i.code == 'BOX-M11');
      expect(first.photos.length, 2);
      expect(first.photos[0].fileName, '预检/001_BOX-M11_01.jpg');
      expect(first.photos[1].fileName, '预检/001_BOX-M11_02.jpg');

      final second = plan.items.firstWhere((i) => i.code == 'BOX-M12');
      expect(second.photos.single.fileName, '预检/002_BOX-M12_01.jpg');
    });

    test('没有照片的货品进缺口，且不会出现在照片列表里', () async {
      final itemIds = await importItems([
        ('A-1', '有照片'),
        ('A-2', '没照片'),
        ('A-3', '也没照片'),
      ]);
      final photoIds = await shoot(1, filePrefix: 'b');
      await confirmPhoto(photoIds[0], itemIds[0]);

      final plan = await builder.build(projectId);

      expect(plan.itemTotal, 3);
      expect(plan.itemDone, 1);
      expect(plan.gapCount, 2);
      expect(plan.gaps.map((g) => g.code).toList(), ['A-2', 'A-3']);
      expect(plan.photoCount, 1);
      // 覆盖率 = 1/3
      expect(plan.coverage, closeTo(1 / 3, 0.001));
    });

    test('覆盖率是业务指标，缺口不阻断交付', () async {
      final itemIds = await importItems([('A-1', '甲'), ('A-2', '乙')]);
      final photoIds = await shoot(1, filePrefix: 'c');
      // 只确认一张 → 覆盖率 50%，低于 80% 达标线
      await confirmPhoto(photoIds[0], itemIds[0]);

      final plan = await builder.build(projectId);
      expect(plan.coverage, lessThan(0.8));
      // ★ 关键断言：覆盖率不达标 ≠ 不能交付
      expect(plan.canDeliver, isTrue);
      expect(plan.orphanCount, 0);
    });

    test('没对上编码的预检照片照样进包，用原始文件名（老板 09-27）', () async {
      await importItems([('A-1', '甲')]);
      await shoot(2, filePrefix: 'd'); // 一张都不确认

      final plan = await builder.build(projectId);
      // ★ 关键断言：未对应 ≠ 不交付。它们进包、不算缺口、也不丢。
      expect(plan.photoCount, 2);
      expect(plan.unmatchedPhotos.length, 2);
      expect(plan.photos.length, 0);
      expect(plan.gaps.length, 1);
      // 保留原始文件名（含扩展名），报告员还能按时间/相册顺序对照
      expect(plan.unmatchedPhotos[0].originalName, 'd1.jpg');
      expect(plan.unmatchedPhotos[0].fileName, '预检/d1.jpg');
    });

    test('照片按拍摄时间升序排列，张序稳定可复现', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      // 三张不同时间戳，插入顺序打乱
      final s = await capture.startSession(projectId);
      final paths = [
        p.join(tmpRoot.path, 'ord1.jpg'),
        p.join(tmpRoot.path, 'ord2.jpg'),
        p.join(tmpRoot.path, 'ord3.jpg'),
      ];
      final ids = await capture.insertPhotos(projectId, [
        NewPhoto(
          sessionId: s,
          filePath: paths[0],
          seq: 1,
          takenAt: t(30),
          bytes: 10,
        ),
        NewPhoto(
          sessionId: s,
          filePath: paths[1],
          seq: 2,
          takenAt: t(10),
          bytes: 10,
        ),
        NewPhoto(
          sessionId: s,
          filePath: paths[2],
          seq: 3,
          takenAt: t(20),
          bytes: 10,
        ),
      ]);
      await capture.endSession(s);
      for (final id in ids) {
        await confirmPhoto(id, itemIds[0]);
      }

      final plan = await builder.build(projectId);
      final photos = plan.items.single.photos;
      // 时间序：t(10), t(20), t(30)
      expect(photos[0].takenAt, t(10).millisecondsSinceEpoch);
      expect(photos[1].takenAt, t(20).millisecondsSinceEpoch);
      expect(photos[2].takenAt, t(30).millisecondsSinceEpoch);
      // 张序即时间序
      expect(photos.map((x) => x.indexInItem).toList(), [1, 2, 3]);
      expect(photos[0].fileName, '预检/001_A-1_01.jpg');
      expect(photos[2].fileName, '预检/001_A-1_03.jpg');
    });
  });

  // ═════════════════════════════════════════════════════════
  // 3. 归属完整性闸门
  // ═════════════════════════════════════════════════════════

  group('归属完整性（§6.3 自检 · 老板 09-26 拍板不拦截交付）', () {
    test('正常路径下 orphanCount 恒为 0', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(1, filePrefix: 'e');
      await confirmPhoto(photoIds[0], itemIds[0]);

      final plan = await builder.build(projectId);
      expect(plan.orphanCount, 0);
      expect(plan.canDeliver, isTrue);
    });

    test('照片有 itemId 但无 assignment 记录 → 判定为孤儿（提示，不拦截）', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(1, filePrefix: 'f');
      await confirmPhoto(photoIds[0], itemIds[0]);

      await corruptItemId(photoIds[0], 'ghost-item');

      final plan = await builder.build(projectId);
      expect(plan.orphanCount, greaterThan(0));
      expect(plan.canDeliver, isFalse);
    });

    test('有 itemId 但 state 不是 confirmed → 判定为异常（提示，不拦截）', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(1, filePrefix: 'g');
      await confirmPhoto(photoIds[0], itemIds[0]);

      await (db.update(db.photos)..where((x) => x.id.equals(photoIds[0])))
          .write(const PhotosCompanion(state: Value('unassigned')));

      final plan = await builder.build(projectId);
      expect(plan.canDeliver, isFalse);
    });

    test('orphan 存在时仍可打包（老板 09-26 拍板），manifest 记录异常数', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(1, filePrefix: 'h');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await corruptItemId(photoIds[0], 'ghost');

      final svc = ExportServiceImpl(db);
      // ★ 关键断言：不再抛异常 —— 打包照常完成
      final result = await svc.build(
        projectId: projectId,
        options: const ExportOptions(),
      );
      expect(result, isA<DeliveryResult>());

      // manifest 里留痕：summary.orphanCount > 0 且 canDeliver=false
      final manifest = File(p.join(result.folderPath, 'manifest.json'));
      expect(manifest.existsSync(), isTrue);
      final json = jsonDecode(manifest.readAsStringSync()) as Map<String, dynamic>;
      final summary = json['summary'] as Map<String, dynamic>;
      expect((summary['orphanCount'] as num).toInt(), greaterThan(0));
      expect(summary['canDeliver'], false);
      // ghost 指向不存在的货品 → 不进正片，但**也不许凭空消失**：
      // 按"没对上编码"走原始文件名进包（丢了照片没人知道，比放错位置糟得多）
      expect(result.photoCount, 1);
      expect(
        File(p.join(result.folderPath, '预检', 'h1.jpg')).existsSync(),
        isTrue,
      );
    });
  });

  // ═════════════════════════════════════════════════════════
  // 4.5 按箱号分文件夹（老板 09-26 拍板：打包时按箱号分文件夹）
  // ═════════════════════════════════════════════════════════

  group('预检 / 监装 分流 + 按箱号分文件夹（老板 09-27）', () {
    test('primaryCartonOf / cartonDirName 仍服务清单信息展示', () {
      expect(primaryCartonOf('箱A、箱B'), '箱A');
      expect(primaryCartonOf('箱A'), '箱A');
      expect(primaryCartonOf(' 箱A '), '箱A');
      expect(primaryCartonOf(null), isNull);
      expect(primaryCartonOf(''), isNull);
      expect(primaryCartonOf('   '), isNull);
      expect(primaryCartonOf('、、'), isNull);
      expect(cartonDirName('箱A、箱B'), '箱A');
      expect(cartonDirName(null), '_未分箱');
      expect(cartonDirName('A/B:C'), 'A_B_C');
    });

    test('userCartonDir：用户箱号本身就是一个箱号，不需要拆', () {
      expect(userCartonDir('箱A'), '箱A');
      expect(userCartonDir(' 箱A '), '箱A');
      expect(userCartonDir('A/B:C'), 'A_B_C');
      // 返回 null（而不是 _未分箱）让构建器决定"整体平铺"还是"归 _未分箱"
      expect(userCartonDir(null), isNull);
      expect(userCartonDir(''), isNull);
      expect(userCartonDir('   '), isNull);
    });

    test('监装照片进 监装/ 一个文件夹，用原始文件名', () async {
      await importItems([('A-1', '甲')]);
      final ids = await shoot(2, filePrefix: 's');
      await markSupervision(ids);

      final plan = await builder.build(projectId);
      expect(plan.supervisionPhotos.length, 2);
      expect(plan.photos.length, 0);
      expect(plan.unmatchedPhotos.length, 0);
      // ★ 与清单无关 → 一个文件夹、原始文件名，不按箱号再分
      expect(plan.supervisionPhotos[0].fileName, '监装/s1.jpg');
      expect(plan.supervisionPhotos[1].fileName, '监装/s2.jpg');
      expect(plan.precheckPhotoCount, 0);
      expect(plan.photoCount, 2);
    });

    test('预检按**用户指定**的箱号分文件夹', () async {
      final itemIds = await importItems([('A-1', '甲'), ('A-2', '乙')]);
      final ids = await shoot(2, filePrefix: 'u');
      await confirmPhoto(ids[0], itemIds[0]);
      await confirmPhoto(ids[1], itemIds[1]);
      await setCarton([ids[0]], '箱A');
      await setCarton([ids[1]], null);

      final plan = await builder.build(projectId);
      expect(plan.hasCartonData, isTrue);
      expect(plan.photos[0].fileName, '预检/箱A/001_A-1_01.jpg');
      expect(plan.photos[1].fileName, '预检/_未分箱/002_A-2_01.jpg');
    });

    test('清单写了箱号但用户没指定 → 不参与分箱（语义反转）', () async {
      final idA = await importItemCarton('A-1', '甲', '清单箱', seq: 1);
      final ids = await shoot(1, filePrefix: 'v');
      await confirmPhoto(ids[0], idA);

      final plan = await builder.build(projectId);
      // ★ 分箱只认人指定的：清单箱号再全也不生效
      expect(plan.hasCartonData, isFalse);
      expect(plan.photos[0].fileName, '预检/001_A-1_01.jpg');
      // 但清单信息不丢 —— manifest 里还能看到
      expect(plan.items[0].containerSummary, '清单箱');
    });

    test('没对上编码的预检照片跟着箱号走（原始文件名）', () async {
      final ids = await shoot(2, filePrefix: 'w');
      await setCarton([ids[0]], '箱A');

      final plan = await builder.build(projectId);
      expect(plan.unmatchedPhotos[0].fileName, '预检/箱A/w1.jpg');
      expect(plan.unmatchedPhotos[1].fileName, '预检/_未分箱/w2.jpg');
    });

    test('一个箱号都没指定 → 预检内部平铺（不造 _未分箱）', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final ids = await shoot(1, filePrefix: 'c3');
      await confirmPhoto(ids[0], itemIds[0]);

      final plan = await builder.build(projectId);
      expect(plan.hasCartonData, isFalse);
      expect(plan.photos[0].fileName, '预检/001_A-1_01.jpg');
    });

    test('groupByCarton=false → 预检内部平铺，即使指定过箱号', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final ids = await shoot(1, filePrefix: 'c4');
      await confirmPhoto(ids[0], itemIds[0]);
      await setCarton([ids[0]], '箱A');

      final plan = await builder.build(projectId, groupByCarton: false);
      expect(plan.photos[0].fileName, '预检/001_A-1_01.jpg');
    });

    test('原始文件名撞车时自动加后缀，绝不静默覆盖', () async {
      final dirA =
          await Directory(p.join(tmpRoot.path, 'dupA')).create(recursive: true);
      final dirB =
          await Directory(p.join(tmpRoot.path, 'dupB')).create(recursive: true);
      final s = await capture.startSession(projectId);
      final paths = [
        p.join(dirA.path, 'same.jpg'),
        p.join(dirB.path, 'same.jpg'),
      ];
      await capture.insertPhotos(projectId, [
        for (var i = 0; i < 2; i++)
          NewPhoto(
            sessionId: s,
            filePath: paths[i],
            seq: i + 1,
            takenAt: t(i),
            bytes: 8,
          ),
      ]);
      await capture.endSession(s);
      for (final pp in paths) {
        await File(pp).writeAsBytes(List<int>.filled(8, 0xFF));
      }

      final plan = await builder.build(projectId);
      expect(plan.unmatchedPhotos.length, 2);
      // ★ 覆盖 = 交付少一张照片。撞名必须可见地错开。
      expect(plan.unmatchedPhotos[0].fileName, '预检/same.jpg');
      expect(plan.unmatchedPhotos[1].fileName, '预检/same_2.jpg');
    });

    test('打包：预检/监装两个目录落地，manifest layout=by-part', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final ids = await shoot(3, filePrefix: 'c6');
      await confirmPhoto(ids[0], itemIds[0]); // → 预检/箱A/
      await setCarton([ids[0]], '箱A');
      await markSupervision([ids[1]]); // → 监装/
      // ids[2]：没对上编码、没指定箱号 → 预检/_未分箱/ 原始名

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(),
      );

      expect(
        File(p.join(result.folderPath, '预检', '箱A', '001_A-1_01.jpg'))
            .existsSync(),
        isTrue,
      );
      expect(
        File(p.join(result.folderPath, '预检', '_未分箱', 'c63.jpg'))
            .existsSync(),
        isTrue,
      );
      expect(
        File(p.join(result.folderPath, '监装', 'c62.jpg')).existsSync(),
        isTrue,
      );
      expect(result.photoCount, 3);

      final manifest = jsonDecode(
            File(p.join(result.folderPath, 'manifest.json'))
                .readAsStringSync(),
          )
          as Map<String, dynamic>;
      expect(manifest['layout'], 'by-part');
      expect(manifest['precheckLayout'], 'by-carton');
      final items = manifest['items'] as List<dynamic>;
      expect((items.first as Map)['carton'], '箱A');
      expect((manifest['supervision'] as List).length, 1);
      expect((manifest['unmatched'] as List).length, 1);
    });
  });

  // ═════════════════════════════════════════════════════════
  // 6. 端到端打包
  // ═════════════════════════════════════════════════════════

  group('ExportServiceImpl 端到端', () {
    test('产出目录含平铺照片 + manifest + ZIP，不含对照表/缺口/联系表', () async {
      final itemIds = await importItems([
        ('BOX-M11', '底板'),
        ('BOX-M12', '侧板'),
        ('BOX-M13', '顶板'),
      ]);
      final photoIds = await shoot(3, filePrefix: 'z');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await confirmPhoto(photoIds[1], itemIds[0]);
      await confirmPhoto(photoIds[2], itemIds[1]);
      // BOX-M13 留作缺口

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(),
      );

      final out = Directory(result.folderPath);
      expect(await out.exists(), isTrue);

      final entries = await out.list().toList();
      final names = entries.map((e) => p.basename(e.path)).toSet();

      // 09-30：PDF 联系表（OOM）+ 对照表/缺口（老板「都可以不要」）均已移除
      expect(names, isNot(contains('联系表.pdf')));
      expect(names, isNot(contains('_对照表.csv')));
      expect(names, isNot(contains('_清单缺口.txt')));

      // 09-27 起照片先分「预检 / 监装」；本例全是预检 → 只有一个子目录
      expect(names, contains('预检'));
      expect(names, isNot(contains('监装')));
      final preDir = Directory(p.join(out.path, '预检'));
      final photoNames =
          (await preDir.list().toList()).map((e) => p.basename(e.path)).toSet();
      // 预检内部平铺（没指定过箱号），文件名自带身份
      expect(photoNames, contains('001_BOX-M11_01.jpg'));
      expect(photoNames, contains('001_BOX-M11_02.jpg'));
      expect(photoNames, contains('002_BOX-M12_01.jpg'));
      // 唯一的文本产物是 manifest
      expect(names, contains('manifest.json'));
      // 预检内部没有再套子目录（平铺的含义）
      expect(
        (await preDir.list().toList()).whereType<Directory>().length,
        0,
        reason: '没指定箱号时预检内部应平铺',
      );

      // ZIP 存在且非空
      expect(await File(result.zipPath).exists(), isTrue);
      expect(result.bytes, greaterThan(0));

      // manifest 记录了分部类布局（缺口信息也在这里，不再单出文本）
      final manifest =
          await File(p.join(out.path, 'manifest.json')).readAsString();
      expect(manifest, contains('"layout": "by-part"'));
      expect(manifest, contains('"precheckLayout": "flat"'));
      expect(manifest, contains('BOX-M11'));
    });

    test('生成前后不修改任何原始文件（永不改名）', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(1, filePrefix: 'orig');
      await confirmPhoto(photoIds[0], itemIds[0]);

      final srcPath = (await (db.select(db.photos)
                ..where((x) => x.id.equals(photoIds[0])))
              .getSingle())
          .filePath;
      final before = await File(srcPath).readAsBytes();
      final beforeStat = await File(srcPath).stat();

      await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(),
      );

      expect(await File(srcPath).exists(), isTrue);
      expect(await File(srcPath).readAsBytes(), before);
      expect(
        (await File(srcPath).stat()).modified,
        beforeStat.modified,
        reason: '原始文件的时间戳都不该被碰到',
      );
    });

    test('进度回调单调不减，最终到 1.0', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(2, filePrefix: 'prog');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await confirmPhoto(photoIds[1], itemIds[0]);

      final ratios = <double>[];
      await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(),
        onProgress: (r, _) => ratios.add(r),
      );

      expect(ratios, isNotEmpty);
      expect(ratios.last, 1.0);
      for (var i = 1; i < ratios.length; i++) {
        expect(ratios[i], greaterThanOrEqualTo(ratios[i - 1]));
      }
    });

    test('isCancelled 为 true 时立即抛 ExportCancelled', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(1, filePrefix: 'cancel');
      await confirmPhoto(photoIds[0], itemIds[0]);

      await expectLater(
        ExportServiceImpl(db).build(
          projectId: projectId,
          options: const ExportOptions(),
          isCancelled: () => true,
        ),
        throwsA(isA<ExportCancelled>()),
      );
    });

    test('estimate 在无照片时返回兜底而非 0 体积', () async {
      await importItems([('A-1', '甲')]);
      final est = await ExportServiceImpl(db)
          .estimate(projectId, const ExportOptions());
      expect(est.photoCount, 0);
      expect(est.totalBytes, greaterThan(0), reason: '文本产物仍有体积');
    });

    test('标记「不用」的照片进 _未使用/ 子目录（且不进预检）', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(2, filePrefix: 'un');
      await confirmPhoto(photoIds[0], itemIds[0]);
      // ★ 09-27 起「未对应」照样交付；只有显式标记「不用」才排除
      await markUnused([photoIds[1]]);

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(includeUnused: true),
      );

      expect(result.photoCount, 1, reason: '「不用」的照片不算进交付数');
      final looseDir = Directory(p.join(result.folderPath, '_未使用'));
      expect(await looseDir.exists(), isTrue);
      final looseFiles = await looseDir.list().toList();
      expect(looseFiles.whereType<File>().length, 1);
    });

    test('未对应的预检照片默认就进包（不勾 includeUnused 也在）', () async {
      await importItems([('A-1', '甲')]);
      await shoot(2, filePrefix: 'un2');

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(),
      );

      // 老板 09-27：去掉检查，直接按分组打包 —— 未对应的照样交付
      expect(result.photoCount, 2);
      final preDir = Directory(p.join(result.folderPath, '预检'));
      expect(
        (await preDir.list().toList()).whereType<File>().length,
        2,
      );
    });
  });

  // ═════════════════════════════════════════════════════════
  // 7. precheck
  // ═════════════════════════════════════════════════════════

  group('precheck', () {
    test('把缺口/未指派汇总成 warning，但不阻断', () async {
      final itemIds = await importItems([
        ('A-1', '甲'),
        ('A-2', '乙'),
        ('A-3', '丙'),
      ]);
      final photoIds = await shoot(2, filePrefix: 'pre');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await confirmPhoto(photoIds[1], itemIds[1]);

      final pre = await ExportServiceImpl(db)
          .precheck(projectId, const ExportOptions());

      expect(pre.blocked, isFalse, reason: '缺口不阻断交付');
      expect(pre.warnings, isNotEmpty);
      expect(
        pre.warnings.any((w) => w.contains('没有照片')),
        isTrue,
        reason: '应提示缺口',
      );
    });

    test('归属异常时 blocked 为 true', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(1, filePrefix: 'pre2');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await corruptItemId(photoIds[0], 'ghost');

      final pre = await ExportServiceImpl(db)
          .precheck(projectId, const ExportOptions());
      expect(pre.blocked, isTrue);
    });
  });

  // ═════════════════════════════════════════════════════════
  // 8. 大项目压力（1000+ 张 / 70+ 组）
  //    09-30 真机「打交付包崩溃」回归 —— 数量维度必须被验证，
  //    而且 ZIP 必须真能解压（此前测试只查文件是否存在，
  //    掩盖过「ZIP 产出但内容不完整」这类故障）。
  // ═════════════════════════════════════════════════════════

  group('大项目压力（1000+ 张 / 70+ 组）', () {
    test(
      '1000 张 / 70 组：打包成功，ZIP 真能解压且照片数完整',
      () async {
        // 70 件货品（真实清单规模）
        final itemIds = await importItems([
          for (var i = 0; i < 70; i++)
            ('C-${(i + 1).toString().padLeft(3, '0')}', '货品${i + 1}'),
        ]);

        // 1000 张照片，每张真落 ~64KB 文件（打包会逐张 copy + 打 ZIP）
        const total = 1000;
        const bytesPer = 64 * 1024;
        final s = await capture.startSession(projectId);
        final photos = [
          for (var i = 0; i < total; i++)
            NewPhoto(
              sessionId: s,
              filePath: p.join(
                tmpRoot.path,
                'big${i.toString().padLeft(4, '0')}.jpg',
              ),
              seq: i + 1,
              takenAt: t(i),
              bytes: bytesPer,
            ),
        ];
        final ids = await capture.insertPhotos(projectId, photos);
        await capture.endSession(s);
        final blob = List<int>.filled(bytesPer, 0xAB);
        for (final ph in photos) {
          // 用 openWrite 而非 writeAsBytes —— 后者同为「每文件 ~100ms」的
          // 慢路径（与 File.copy 同源），1000 张会让 setup 自己就超时。
          final s = File(ph.filePath).openWrite();
          s.add(blob);
          await s.close();
        }

        // 每 15 张一组 → ≈67 组；每组前 2 张确认归属到对应货品
        const groupSize = 15;
        var groups = 0;
        for (var g = 0; g * groupSize < total; g++) {
          final start = g * groupSize;
          final end = (start + groupSize).clamp(0, total);
          final slice = ids.sublist(start, end);
          final gs = await capture.startSession(projectId);
          await db.into(db.photoGroups).insert(
                PhotoGroupsCompanion.insert(
                  id: 'grp-$g',
                  projectId: projectId,
                  sessionId: gs,
                  seq: g + 1,
                  createdAt: t(g).millisecondsSinceEpoch,
                ),
              );
          await capture.endSession(gs);
          await (db.update(db.photos)..where((x) => x.id.isIn(slice)))
              .write(PhotosCompanion(groupId: Value('grp-$g')));
          for (final pid in slice.take(2)) {
            await confirmPhoto(pid, itemIds[g % itemIds.length]);
          }
          groups++;
        }
        expect(groups, greaterThanOrEqualTo(60));

        final rssBefore = ProcessInfo.currentRss;
        final sw = Stopwatch()..start();
        final result = await ExportServiceImpl(db).build(
          projectId: projectId,
          // 纯 IO 压力口径：显式关掉压缩 —— 压缩路径有自己的专门用例
          //（见「压缩与分卷」组），这里不掺通道因素。
          options: const ExportOptions(compressPhotos: false),
        );
        sw.stop();
        final rssDelta = ProcessInfo.currentRss - rssBefore;
        // ignore: avoid_print
        print('[stress] ${result.photoCount} 张 / $groups 组：'
            '耗时 ${sw.elapsedMilliseconds}ms，'
            'RSS ${rssBefore ~/ 1048576}MB→'
            '${ProcessInfo.currentRss ~/ 1048576}MB');

        // 成功 + 数量正确
        expect(result.photoCount, total);
        expect(await File(result.zipPath).exists(), isTrue);
        expect(result.bytes, greaterThan(0));

        // ★ 流式实现下，内存增量应远小于「整包读进内存」的量级
        //   （1000 × 64KB = 64MB；整包 + 副本则 ≥ 128MB）
        expect(
          rssDelta,
          lessThan(96 * 1048576),
          reason: '打包内存增量 ${rssDelta ~/ 1048576}MB 过大 —— '
              '疑似退回「整包读内存」实现',
        );

        // ★ ZIP 必须真能解压，且照片条目数完整
        final decoded =
            ZipDecoder().decodeBytes(await File(result.zipPath).readAsBytes());
        final jpgEntries = decoded.files
            .where((f) => f.isFile && f.name.toLowerCase().endsWith('.jpg'))
            .length;
        expect(jpgEntries, total, reason: 'ZIP 内照片条目数必须与计划一致');
        decoded.clear();
      },
      // ⚠️ 这里的**绝对耗时与机器强相关**（同一台 Windows 上实测波动 2-8 倍，
      //    疑似 Defender 首次扫描 / 冷缓存；1000 张同步复制从 9s 到 82s 都出现过）。
      //    本用例真正要守的是「不超时 + 内存有界 + ZIP 条目完整」，
      //    所以超时给足 10 分钟，避免慢机器上假红。
      timeout: const Timeout(Duration(minutes: 10)),
    );
  });

  // ═════════════════════════════════════════════════════════
  // 压缩 + 分卷（微信单文件 1GB 上限 · 老板 2026-09-30 拍板）
  // ═════════════════════════════════════════════════════════

  group('压缩与分卷（微信 1GB · 老板 09-30）', () {
    const channel = MethodChannel('gtick/perf');

    setUp(() {
      TestWidgetsFlutterBinding.ensureInitialized();
    });

    tearDown(() {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null);
    });

    /// 压缩通道替身：把「压缩产物」写成 32 字节 0xAB，回 ok/skipped=false。
    void mockCompressOk({bool skipped = false}) {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel,         (call) async {
        expect(call.method, 'compressPhotos');
        final jobs = (call.arguments as Map)['jobs'] as List;
        if (!skipped) {
          for (final j in jobs) {
            final job = j as Map;
            await File(job['dst'] as String)
                .writeAsBytes(List<int>.filled(32, 0xAB));
          }
        }
        return [
          for (final _ in jobs)
            {'ok': true, 'skipped': skipped, 'w': 100, 'h': 75, 'bytes': 32},
        ];
      });
    }

    test('压缩开：包内是压缩产物，原图一个字节都不动，zip 含 manifest', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(2, filePrefix: 'cmp');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await confirmPhoto(photoIds[1], itemIds[0]);
      mockCompressOk();

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        // 2026-10-20：压缩改成显式开关（默认关，交付带原图）——
        // 这个用例测的就是压缩路径，必须显式打开。
        options: const ExportOptions(compressPhotos: true),
      );

      // 包内 = 压缩产物（32 字节 0xAB），不是原图（64 字节 0xFF）
      final preDir = Directory(p.join(result.folderPath, '预检'));
      final delivered =
          await File(p.join(preDir.path, '001_A-1_01.jpg')).readAsBytes();
      expect(delivered, List<int>.filled(32, 0xAB));

      // ★ 原图不动 —— 压缩只发生在交付输出，取证底稿永远在手机里
      for (final pid in photoIds) {
        final src = (await (db.select(db.photos)
                  ..where((x) => x.id.equals(pid)))
                .getSingle())
            .filePath;
        expect(
          await File(src).readAsBytes(),
          List<int>.filled(64, 0xFF),
          reason: '压缩绝不能改写原图',
        );
      }

      // 默认体积不超限 → 单卷；zip 里要有 manifest（v0.12 起入包）
      expect(result.volumes.length, 1);
      final decoded =
          ZipDecoder().decodeBytes(await File(result.zipPath).readAsBytes());
      expect(decoded.files.map((f) => f.name), contains('manifest.json'));
      expect(
        decoded.files.where((f) => f.name.endsWith('.jpg')).length,
        2,
      );
    });

    test('压缩通道不可用 → 全部回退复制原图，一张不少', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(2, filePrefix: 'nofb');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await confirmPhoto(photoIds[1], itemIds[0]);
      // 不注册 mock —— 通道在测试环境没有实现，等价于原生缺失/异常

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        // 显式开压缩（默认已关，2026-10-20）—— 本用例测「压缩失败回退」
        options: const ExportOptions(compressPhotos: true),
      );

      expect(result.photoCount, 2, reason: '压缩失败绝不能丢照片');
      final preDir = Directory(p.join(result.folderPath, '预检'));
      final delivered =
          await File(p.join(preDir.path, '001_A-1_01.jpg')).readAsBytes();
      expect(delivered, List<int>.filled(64, 0xFF), reason: '回退 = 复制原图');
    });

    test('原生报 skipped（原图长边已够小）→ 原图直出', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(1, filePrefix: 'skip');
      await confirmPhoto(photoIds[0], itemIds[0]);
      mockCompressOk(skipped: true);

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        // 显式开压缩（默认已关，2026-10-20）—— 本用例测「原生 skipped」
        options: const ExportOptions(compressPhotos: true),
      );

      final preDir = Directory(p.join(result.folderPath, '预检'));
      final delivered =
          await File(p.join(preDir.path, '001_A-1_01.jpg')).readAsBytes();
      expect(delivered, List<int>.filled(64, 0xFF),
          reason: '原图够小就不该重编码 —— 零画质损失');
    });

    test('超限自动分卷：多卷 ZIP 独立可解压，照片不重不漏', () async {
      final itemIds = await importItems([('A-1', '甲'), ('A-2', '乙')]);
      final photoIds = await shoot(3, filePrefix: 'vol');
      await confirmPhoto(photoIds[0], itemIds[0]);
      await confirmPhoto(photoIds[1], itemIds[1]);
      await confirmPhoto(photoIds[2], itemIds[1]);
      mockCompressOk();

      // 上限 1KB：压缩产物 32B + 512B 目录开销 > 1KB 放两张 → 一卷一张
      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(volumeLimitBytes: 1024),
      );

      expect(result.volumes.length, 3, reason: '应按上限切成 3 卷');
      expect(result.isSplit, isTrue);
      expect(result.bytes,
          result.volumes.fold<int>(0, (s, v) => s + v.bytes));

      // 卷名带序号与总数，收件端按文件名排序即顺序正确
      expect(p.basename(result.volumes[0].path), contains('第01卷-共03卷'));
      expect(p.basename(result.volumes[2].path), contains('第03卷-共03卷'));

      // 每卷独立可解压：都含 manifest + 自己那部分照片；并集 = 全部、无重复
      final seen = <String>{};
      for (final v in result.volumes) {
        expect(await File(v.path).exists(), isTrue);
        final decoded = ZipDecoder()
            .decodeBytes(await File(v.path).readAsBytes());
        expect(decoded.files.map((f) => f.name), contains('manifest.json'),
            reason: '每卷都要自描述');
        for (final f in decoded.files) {
          if (f.isFile && f.name.endsWith('.jpg')) {
            expect(seen.add(f.name), isTrue,
                reason: '同一张照片绝不能出现在两卷里');
          }
        }
      }
      expect(seen.length, 3, reason: '三张照片必须每卷恰好分到，不重不漏');
    });

    test('关闭分卷 → 永远单卷 ZIP（走网盘场景）', () async {
      final itemIds = await importItems([('A-1', '甲')]);
      final photoIds = await shoot(3, filePrefix: 'nsv');
      for (final pid in photoIds) {
        await confirmPhoto(pid, itemIds[0]);
      }
      mockCompressOk();

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(
          splitVolumes: false,
          volumeLimitBytes: 1024, // 即使远超上限也不许切
        ),
      );

      expect(result.volumes.length, 1);
      final decoded =
          ZipDecoder().decodeBytes(await File(result.zipPath).readAsBytes());
      expect(decoded.files.where((f) => f.name.endsWith('.jpg')).length, 3);
    });

    test('零照片也能出包（空 zip + manifest，不崩）', () async {
      await importItems([('A-1', '甲')]);

      final result = await ExportServiceImpl(db).build(
        projectId: projectId,
        options: const ExportOptions(volumeLimitBytes: 1024),
      );

      expect(result.photoCount, 0);
      expect(result.volumes.length, 1);
      final decoded =
          ZipDecoder().decodeBytes(await File(result.zipPath).readAsBytes());
      expect(decoded.files.map((f) => f.name), contains('manifest.json'));
    });
  });
}

/// 测试用的不安全字符表（与 AppConst.unsafeFilenameChars 同源，
/// 但从测试侧重复声明 —— 这样常量被误改时测试会红，不会跟着一起错）。
class AppConstTestHelper {
  const AppConstTestHelper._();
  static const List<String> unsafeChars = <String>[
    '/', '\\', ':', '*', '?', '"', '<', '>', '|',
  ];
}
