import 'dart:io';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/db/integrity_checks.dart';
import 'package:g_tick_picture/data/fs/project_paths.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/organize_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/assign/assign_service.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/photo/photo_deletion_service.dart';

/// 删除功能的契约测试（M7 · 老板诉求：删项目 / 删项目里的图片）。
///
/// 断言的不是实现细节，而是三条承诺：
///  1. **删除不留脏数据**：照片行消失时，OCR token、一照多货附加关联、
///     照片级归属记录一起消失；删空组时连组级归属记录一起删 ——
///     `IntegrityChecks` 的孤儿数在删除前后都保持 0。
///  2. **组结构自洽**：封面被删会改派给剩余最早一张，photoCount 实算。
///  3. **文件尽力而为**：磁盘文件删掉是应该的，删不掉（不存在）不阻断。
///     归属（itemId）**永不被删除服务改写** —— 它只删行，不做归属决定。
void main() {
  late AppDatabase db;
  late CaptureRepository capture;
  late OrganizeRepository organize;
  late ProjectRepository projects;
  late AssignService assign;
  late PhotoDeletionService deletion;
  late IntegrityChecks checks;
  late String projectId;
  late Directory tempRoot;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    capture = CaptureRepository(db);
    organize = OrganizeRepository(db);
    projects = ProjectRepository(db);
    assign = AssignService(db, deviceName: 'tester');
    deletion = PhotoDeletionService(db);
    checks = IntegrityChecks(db);
    projectId = await projects.create(name: '删除测试');

    // 文件系统隔离：把 ProjectPaths 根目录指到临时目录，测试后清掉
    tempRoot = await Directory.systemTemp.createTemp('gtick_deletion_test');
    ProjectPaths.overrideRootForTest(tempRoot);
  });

  tearDown(() async {
    ProjectPaths.overrideRootForTest(null);
    try {
      if (await tempRoot.exists()) await tempRoot.delete(recursive: true);
    } catch (_) {/* 临时目录删不掉不影响测试结论 */}
    await db.close();
  });

  // ── 夹具 ────────────────────────────────────────────────

  DateTime t(int sec) => DateTime(2026, 9, 23, 10, 0, sec);

  Future<String> insertItem(String code) async {
    final id = 'item-$code';
    await db.into(db.items).insert(
          ItemsCompanion.insert(
            id: id,
            projectId: projectId,
            seq: 1,
            code: code,
            codeSafe: code.replaceAll('-', ''),
          ),
        );
    return id;
  }

  /// 开一个相机批次、插 [n] 张（间隔 [gapSec] 秒）、关批次、聚成组。
  /// 返回（sessionId, photoIds, groupId）。
  Future<(String, List<String>, String?)> groupedSession(
    int n, {
    int gapSec = 10,
  }) async {
    final s = await capture.startSession(projectId);
    final photos = [
      for (var i = 0; i < n; i++)
        NewPhoto(
          sessionId: s,
          filePath: '/tmp/p$i.jpg',
          seq: i + 1,
          takenAt: t(i * gapSec),
          bytes: 1024,
        ),
    ];
    final ids = await capture.insertPhotos(projectId, photos);
    await capture.endSession(s);
    await organize.regroupPending(projectId);
    final g = await (db.select(db.photoGroups)
          ..where((row) => row.projectId.equals(projectId)))
        .get();
    return (s, ids, g.isEmpty ? null : g.first.id);
  }

  Future<PhotoGroup?> groupOf(String groupId) =>
      (db.select(db.photoGroups)..where((row) => row.id.equals(groupId)))
          .getSingleOrNull();

  Future<List<Assignment>> groupAssignments(String groupId) =>
      (db.select(db.assignments)
            ..where((row) =>
                row.targetType.equals(AssignTargetType.group.code) &
                row.targetId.equals(groupId)))
          .get();

  Future<List<Assignment>> photoAssignments(String photoId) =>
      (db.select(db.assignments)
            ..where((row) =>
                row.targetType.equals(AssignTargetType.photo.code) &
                row.targetId.equals(photoId)))
          .get();

  Future<int> ocrTokenCount(String photoId) async {
    final rows = await (db.select(db.ocrTokens)
          ..where((row) => row.photoId.equals(photoId)))
        .get();
    return rows.length;
  }

  Future<void> insertOcrToken(String photoId) async {
    await db.into(db.ocrTokens).insert(
          OcrTokensCompanion.insert(
            id: 'ocr-$photoId',
            photoId: photoId,
            rawText: 'A-001',
            confidence: 0.9,
            boxJson: '[]',
          ),
        );
  }

  // ═════════════════════════════════════════════════════════
  // deletePhoto
  // ═════════════════════════════════════════════════════════

  group('deletePhoto', () {
    test('删除单张：照片行与从属数据一起消失，组计数递减', () async {
      final (_, ids, groupId) = await groupedSession(3);
      final target = ids[0];

      await insertOcrToken(target);
      // 一照多货附加关联（P2 表，M7 起删除时要连带清理）
      await db.into(db.itemPhotoExtras).insert(
            ItemPhotoExtrasCompanion.insert(
              id: 'ipe-1',
              photoId: target,
              itemId: await insertItem('A-001'),
              createdAt: t(0).millisecondsSinceEpoch,
            ),
          );

      await deletion.deletePhoto(target);

      final remaining = await (db.select(db.photos)
            ..where((row) => row.id.equals(target)))
          .get();
      expect(remaining, isEmpty);
      expect(await ocrTokenCount(target), 0);
      expect(await photoAssignments(target), isEmpty);
      final extras = await db.select(db.itemPhotoExtras).get();
      expect(extras, isEmpty);

      // 组还在（还剩 2 张），计数已递减
      final g = await groupOf(groupId!);
      expect(g, isNotNull);
      expect(g!.photoCount, 2);
    });

    test('被删的是封面 → 改派给剩余最早一张', () async {
      final (_, ids, groupId) = await groupedSession(3);
      final g0 = await groupOf(groupId!);
      expect(g0!.coverPhotoId, ids[0]); // 聚类时封面 = 最早一张

      await deletion.deletePhoto(ids[0]);

      final g1 = await groupOf(groupId);
      expect(g1, isNotNull);
      expect(g1!.coverPhotoId, ids[1]);
      expect(g1.photoCount, 2);
    });

    test('被删的不是封面 → coverPhotoId 不动', () async {
      final (_, ids, groupId) = await groupedSession(3);

      await deletion.deletePhoto(ids[1]); // 非封面

      final g = await groupOf(groupId!);
      expect(g!.coverPhotoId, ids[0]);
      expect(g.photoCount, 2);
    });

    test('删空整组：组与组级归属记录一起删除，孤儿校验保持 0', () async {
      final itemId = await insertItem('A-001');
      final (s, ids, groupId) = await groupedSession(1);
      final (sessionId, photoId) = (s, ids.single);

      // 真实路径确认归属：先写 assignments，再写 itemId（架构规则 3）
      await assign.confirmGroup(groupId!, itemId: itemId, source: AssignSource.manual);
      expect(await groupAssignments(groupId), hasLength(1));

      await deletion.deletePhoto(photoId);

      // 组空了 → 连组一起删，组级归属记录不留孤儿
      expect(await groupOf(groupId), isNull);
      expect(await groupAssignments(groupId), isEmpty);
      expect(await (db.select(db.captureSessions)
            ..where((row) => row.id.equals(sessionId)))
          .get(), hasLength(1)); // session 不动
      expect(await checks.orphanGroupAssignments(projectId), 0);
    });

    test('删除单张确认的照片：照片级归属记录连带删，孤儿校验保持 0', () async {
      final itemId = await insertItem('A-001');
      final (_, ids, _) = await groupedSession(1);
      final photoId = ids.single;

      await assign.confirmPhoto(photoId, itemId: itemId, source: AssignSource.manual);
      expect(await checks.orphanPhotoAssignments(projectId), 0);

      await deletion.deletePhoto(photoId);

      expect(await photoAssignments(photoId), isEmpty);
      expect(await checks.orphanPhotoAssignments(projectId), 0);
    });

    test('磁盘文件尽力而为删除：存在的删掉，不存在的也不报错', () async {
      final (_, ids, _) = await groupedSession(1);
      final photoId = ids.single;

      // 造两个真实文件 + 一个不存在的路径
      final rawFile = File('${tempRoot.path}/raw_test.jpg')..writeAsBytesSync([1, 2, 3]);
      final thumbFile = File('${tempRoot.path}/thumb_test.jpg')
        ..writeAsBytesSync([4, 5, 6]);
      await (db.update(db.photos)..where((row) => row.id.equals(photoId)))
          .write(PhotosCompanion(
        filePath: Value(rawFile.path),
        thumbPath: Value(thumbFile.path),
      ));

      // OCR 缓存文件（路径由 ProjectPaths 推导）
      final ocrFile = await ProjectPaths.ocrCacheFile(projectId, photoId);
      await ocrFile.create(recursive: true);
      await ocrFile.writeAsString('{}');

      await deletion.deletePhoto(photoId);

      expect(await rawFile.exists(), isFalse);
      expect(await thumbFile.exists(), isFalse);
      expect(await ocrFile.exists(), isFalse);
    });

    test('删除不存在的照片：幂等，不抛异常', () async {
      await deletion.deletePhoto('no-such-photo');
      await deletion.deleteGroup('no-such-group');
    });
  });

  // ═════════════════════════════════════════════════════════
  // deleteGroup
  // ═════════════════════════════════════════════════════════

  group('deleteGroup', () {
    test('整组删除：照片、从属数据、组级归属记录全部消失', () async {
      final itemId = await insertItem('A-001');
      final (_, ids, groupId) = await groupedSession(3);

      await insertOcrToken(ids[0]);
      await assign.confirmGroup(groupId!, itemId: itemId, source: AssignSource.manual);
      expect(await groupAssignments(groupId), hasLength(1));

      await deletion.deleteGroup(groupId);

      expect(await groupOf(groupId), isNull);
      final left = await db.select(db.photos).get();
      expect(left, isEmpty);
      expect(await groupAssignments(groupId), isEmpty);
      expect(await ocrTokenCount(ids[0]), 0);
      expect(await checks.orphanGroupAssignments(projectId), 0);
      expect(await checks.orphanPhotoAssignments(projectId), 0);
    });

    test('磁盘文件全部尽力而为删除', () async {
      final (_, ids, groupId) = await groupedSession(3);
      final files = <File>[];
      for (var i = 0; i < ids.length; i++) {
        final f = File('${tempRoot.path}/g_$i.jpg')..writeAsBytesSync([i]);
        files.add(f);
        await (db.update(db.photos)..where((row) => row.id.equals(ids[i])))
            .write(PhotosCompanion(
          filePath: Value(f.path),
          thumbPath: const Value<String?>.absent(),
        ));
      }

      await deletion.deleteGroup(groupId!);

      for (final f in files) {
        expect(await f.exists(), isFalse);
      }
    });
  });

  // ═════════════════════════════════════════════════════════
  // ProjectRepository · 回收站与彻底清盘
  // ═════════════════════════════════════════════════════════

  group('ProjectRepository 回收站', () {
    test('softDelete 后从列表消失、出现在回收站；restore 后回来', () async {
      final p2 = await projects.create(name: '回收站测试');

      final before = await projects.watchAll().first;
      expect(before.map((e) => e.id), contains(p2));

      await projects.softDelete(p2);

      final active = await projects.watchAll().first;
      expect(active.map((e) => e.id), isNot(contains(p2)));
      final deleted = await projects.watchDeleted().first;
      expect(deleted.map((e) => e.id), contains(p2));
      expect(await projects.deletedCount(), 1);

      await projects.restore(p2);

      final back = await projects.watchAll().first;
      expect(back.map((e) => e.id), contains(p2));
      expect((await projects.watchDeleted().first), isEmpty);
    });

    test('purge 级联删除全部关联数据 + 磁盘目录', () async {
      final itemId = await insertItem('A-001');
      final (_, ids, groupId) = await groupedSession(2);

      await insertOcrToken(ids[0]);
      await assign.confirmGroup(groupId!, itemId: itemId, source: AssignSource.manual);

      final ms = DateTime.now().millisecondsSinceEpoch;
      await db.into(db.deliveries).insert(
            DeliveriesCompanion.insert(
              id: 'dlv-1',
              projectId: projectId,
              createdAt: ms,
              optionsJson: '{}',
            ),
          );
      await db.into(db.uploadTasks).insert(
            UploadTasksCompanion.insert(
              id: 'up-1',
              deliveryId: 'dlv-1',
              localPath: '/x.zip',
              remotePath: '/y.zip',
              bytes: 1,
            ),
          );

      // 项目目录里放一个文件，验证目录被清盘
      final dir = await ProjectPaths.projectDir(projectId);
      final marker = File('${dir.path}/marker.txt')..writeAsStringSync('x');

      await projects.purge(projectId);

      expect(await db.select(db.projects).get(), isEmpty);
      expect(await db.select(db.items).get(), isEmpty);
      expect(await db.select(db.photos).get(), isEmpty);
      expect(await db.select(db.photoGroups).get(), isEmpty);
      expect(await db.select(db.captureSessions).get(), isEmpty);
      expect(await db.select(db.assignments).get(), isEmpty);
      expect(await db.select(db.ocrTokens).get(), isEmpty);
      expect(await db.select(db.deliveries).get(), isEmpty);
      expect(await db.select(db.uploadTasks).get(), isEmpty);
      expect(await marker.exists(), isFalse);
      expect(await dir.exists(), isFalse);
    });
  });
}
