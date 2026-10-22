import 'dart:io';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/fs/project_paths.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/capture/camera_capture_service.dart';

/// 微信导入「真实拍摄时刻」贯通测试（2026-09-27 · BUG 修复）。
///
/// 老板报的 BUG：相隔 20 秒的照片没有被按 45 秒规则归组。
/// 根因：微信保存的图**没有 EXIF**，旧链路只把临时文件路径交给
/// importFromGallery，落库 takenAt 退化为临时副本的修改时间
/// （= 导入时刻）→ 整批时间戳挤在同一两秒 → 分组算法判定
/// 「时间戳不可信」→ 每张独立成组，时序聚类永远出不来。
///
/// 修复：微信选择器把 MediaStore DATE_TAKEN 一路带回，
/// [CameraCaptureService.importFromGallery] 新增 takenAts 覆盖参数，
/// 优先级：覆盖值 > EXIF > 文件修改时间。
/// 本文件锁住这条优先级链 —— 它是「导入的照片也能按时序归组」的前提。
void main() {
  late AppDatabase db;
  late Directory tempRoot;
  late Directory srcDir;
  late String projectId;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    tempRoot = await Directory.systemTemp.createTemp('gtick_wechat_takenat');
    srcDir = Directory('${tempRoot.path}/src')..createSync(recursive: true);
    ProjectPaths.overrideRootForTest(tempRoot);
    projectId = await ProjectRepository(db).create(name: '微信导入测试');
  });

  tearDown(() async {
    // ⚠️ 顺序有讲究：
    //  1. importFromGallery 会 unawaited 派发缩略图回填（_enrich），
    //     它可能在本测试结束后才跑 —— 先保持覆写，让任何在途写入
    //     都落在 tempRoot 里，别污染真实应用目录；
    //  2. 删除用"尽力而为"：与在途回填存在竞态（errno 145 目录非空），
    //     清理失败不值得让测试失败 —— 系统临时目录会被系统兜底清理
    //     （与产品侧 AtLeastOnceDelete 同一纪律）；
    //  3. 最后才解除覆写、关库。
    if (await tempRoot.exists()) {
      try {
        await tempRoot.delete(recursive: true);
      } catch (_) {/* 尽力而为 */}
    }
    ProjectPaths.overrideRootForTest(null);
    await db.close();
  });

  Future<String> fakeJpeg(String name) async {
    final f = File('${srcDir.path}/$name');
    // 3 字节假图足够：EXIF 解析会失败（返回 null），文件存在即可走通主路径
    await f.writeAsBytes(const [0xFF, 0xD8, 0xFF]);
    return f.path;
  }

  group('importFromGallery takenAts 覆盖链', () {
    test('覆盖值直接落库 —— 微信导入的真实拍摄时刻不再丢失', () async {
      final svc = CameraCaptureService(CaptureRepository(db));
      final t0 = DateTime(2026, 9, 27, 9, 0, 0);
      final t1 = t0.add(const Duration(seconds: 20)); // 老板说的"相隔 20 秒"

      final paths = [
        await fakeJpeg('a.jpg'),
        await fakeJpeg('b.jpg'),
      ];

      final ids = await svc.importFromGallery(
        projectId,
        paths,
        note: '微信导入 2 张',
        takenAts: [t0, t1],
      );
      expect(ids, hasLength(2));

      final rows = await (db.select(db.photos)
            ..where((p) => p.projectId.equals(projectId))
            ..orderBy([(p) => OrderingTerm.asc(p.takenAt)]))
          .get();
      expect(rows, hasLength(2));
      // 修复前：两行都是"现在"（导入时刻），间隔 ≈ 0
      // 修复后：真实的 20 秒间隔被保留
      expect(rows[0].takenAt, t0.millisecondsSinceEpoch);
      expect(rows[1].takenAt, t1.millisecondsSinceEpoch);
      expect(rows[1].takenAt - rows[0].takenAt, 20000);
    });

    test('覆盖值为 null 的下标退回 mtime 兜底（不阻塞导入）', () async {
      final svc = CameraCaptureService(CaptureRepository(db));
      final before = DateTime.now().millisecondsSinceEpoch;

      final path = await fakeJpeg('c.jpg');
      final ids = await svc.importFromGallery(
        projectId,
        [path],
        note: '微信导入 1 张',
        takenAts: [null], // MediaStore 也没记时间 → 走 EXIF/mtime 老路
      );
      expect(ids, hasLength(1));

      final row = await (db.select(db.photos)
            ..where((p) => p.projectId.equals(projectId)))
          .getSingle();
      // mtime 在部分文件系统上按秒截断 —— 给 5 秒窗口，
      // 断言的是"退回了文件时间"而不是"毫秒级等于现在"。
      expect(row.takenAt, greaterThanOrEqualTo(before - 5000),
          reason: '假图没有 EXIF，应退回文件修改时间（≈ 导入时刻）');
      expect(row.takenAt, lessThanOrEqualTo(before + 60000));
    });

    test('不传 takenAts（相册导入老路径）行为完全不变', () async {
      final svc = CameraCaptureService(CaptureRepository(db));
      final before = DateTime.now().millisecondsSinceEpoch;

      final path = await fakeJpeg('d.jpg');
      final ids = await svc.importFromGallery(projectId, [path]);
      expect(ids, hasLength(1));

      final row = await (db.select(db.photos)
            ..where((p) => p.projectId.equals(projectId)))
          .getSingle();
      expect(row.takenAt, greaterThanOrEqualTo(before - 5000),
          reason: 'mtime 按秒截断的容差');
    });

    test('takenAts 长度不足时按下标对齐，缺省下标走兜底', () async {
      final svc = CameraCaptureService(CaptureRepository(db));
      final t0 = DateTime(2026, 9, 27, 8, 0, 0);

      final paths = [
        await fakeJpeg('e.jpg'),
        await fakeJpeg('f.jpg'),
      ];
      final ids = await svc.importFromGallery(
        projectId,
        paths,
        takenAts: [t0], // 只给了第一张
      );
      expect(ids, hasLength(2));

      final rows = await (db.select(db.photos)
            ..where((p) => p.projectId.equals(projectId))
            ..orderBy([(p) => OrderingTerm.asc(p.seq)]))
          .get();
      expect(rows[0].takenAt, t0.millisecondsSinceEpoch);
      expect(rows[1].takenAt, greaterThanOrEqualTo(t0.millisecondsSinceEpoch),
          reason: '缺省下标退回 mtime，不会越界也不会丢照片');
    });
  });
}
