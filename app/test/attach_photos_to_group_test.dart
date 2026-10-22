import 'dart:io';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/fs/project_paths.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/organize_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';

/// 「组内添加照片」挂组链路测试（2026-09-30）。
///
/// [OrganizeRepository.attachPhotosToGroup] 是组内补拍 / 组内补导的
/// 落库终点。这里锁三件事：
///  1. 游离照片（groupId NULL）直接挂进目标组，photoCount 实算同步
///     —— 这列被 regroup 回收单张组的逻辑依赖，虚了就会拆错组；
///  2. 照片已被 regroup 抢先聚进临时组时，attach 是**移动**语义：
///     照片搬进目标组、搬空的临时组删掉、不留空壳组；
///  3. 已指派（itemId 非空）的组拒绝收人 —— confirmGroup 按组回填
///     照片 itemId，事后加进来的照片 itemId 是 NULL，会漏出交付计划。
void main() {
  late AppDatabase db;
  late Directory tempRoot;
  late String projectId;
  late String sessionId;
  late CaptureRepository captureRepo;
  late OrganizeRepository organizeRepo;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    tempRoot = await Directory.systemTemp.createTemp('gtick_attach');
    ProjectPaths.overrideRootForTest(tempRoot);
    projectId = await ProjectRepository(db).create(name: '挂组测试');
    captureRepo = CaptureRepository(db);
    organizeRepo = OrganizeRepository(db);
    sessionId = await captureRepo.startSession(projectId);
  });

  tearDown(() async {
    if (await tempRoot.exists()) {
      try {
        await tempRoot.delete(recursive: true);
      } catch (_) {/* 尽力而为 */}
    }
    ProjectPaths.overrideRootForTest(null);
    await db.close();
  });

  Future<List<String>> seedPhotos(int count) => captureRepo.insertPhotos(
        projectId,
        [
          for (var i = 0; i < count; i++)
            NewPhoto(
              sessionId: sessionId,
              filePath: '${tempRoot.path}/p$i.jpg',
              seq: i + 1,
              takenAt: DateTime(2026, 9, 30, 10, 0, i),
              bytes: 100,
            ),
        ],
      );

  Future<PhotoGroup> groupRow(String groupId) =>
      (db.select(db.photoGroups)..where((g) => g.id.equals(groupId)))
          .getSingle();

  test('游离照片直接挂组：groupId 写入 + photoCount 同步', () async {
    final ids = await seedPhotos(2);
    final target = await organizeRepo.createGroup(projectId, sessionId);

    final moved = await organizeRepo.attachPhotosToGroup(
        projectId, target, ids);
    expect(moved, 2);

    final rows = await (db.select(db.photos)
          ..where((p) => p.id.isIn(ids)))
        .get();
    for (final r in rows) {
      expect(r.groupId, target, reason: '照片应挂在目标组上');
    }
    expect((await groupRow(target)).photoCount, 2,
        reason: 'photoCount 列必须实算 —— regroup 靠它回收单张组');
  });

  test('照片已被临时组收走时：移动进目标组，空壳临时组被删除', () async {
    final ids = await seedPhotos(2);
    final target = await organizeRepo.createGroup(projectId, sessionId);
    final temp = await organizeRepo.createGroup(projectId, sessionId);

    // 模拟 regroup 抢先：照片已在临时组里
    await (db.update(db.photos)..where((p) => p.id.isIn(ids)))
        .write(PhotosCompanion(groupId: Value(temp)));
    await (db.update(db.photoGroups)..where((g) => g.id.equals(temp)))
        .write(const PhotoGroupsCompanion(photoCount: Value(2)));

    final moved = await organizeRepo.attachPhotosToGroup(
        projectId, target, ids);
    expect(moved, 2);

    final rows = await (db.select(db.photos)
          ..where((p) => p.id.isIn(ids)))
        .get();
    for (final r in rows) {
      expect(r.groupId, target);
    }
    // 空壳临时组必须删掉 —— 留着会在待办流里显示一个 0 张的幽灵组
    expect(
      await (db.select(db.photoGroups)..where((g) => g.id.equals(temp)))
          .getSingleOrNull(),
      isNull,
    );
    expect((await groupRow(target)).photoCount, 2);
  });

  test('已指派的组拒绝收人（StateError）', () async {
    final ids = await seedPhotos(1);
    final target = await organizeRepo.createGroup(projectId, sessionId);
    // 直接把组标记为已指派（confirmGroup 的等效最小状态）
    await (db.update(db.photoGroups)..where((g) => g.id.equals(target)))
        .write(const PhotoGroupsCompanion(itemId: Value('item-x')));

    expect(
      () => organizeRepo.attachPhotosToGroup(projectId, target, ids),
      throwsStateError,
    );
  });
}
