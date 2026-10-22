// v0.19.0（2026-10-10）拍后回看·重拍的删除口径单测。
//
// 重拍 = PhotoDeletionService.deletePhoto（复用整理页同款删除），
// 本文件钉死它对**采集批次计数**的承诺：photo_count 必须随删除递减
// 且不跌破 0 —— 否则「拍后回看」删一张重拍一张，顶部数字越走越高，
// 现场一眼就能看出账对不上（铁律 23：数字与明细必须同源）。
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/photo/photo_deletion_service.dart';

void main() {
  late AppDatabase db;
  late CaptureRepository capture;
  late ProjectRepository projects;
  late PhotoDeletionService deletion;
  late String projectId;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    capture = CaptureRepository(db);
    projects = ProjectRepository(db);
    deletion = PhotoDeletionService(db);
    projectId = await projects.create(name: '重拍计数测试');
  });

  tearDown(() async {
    await db.close();
  });

  Future<(String, List<String>)> sessionWith(int n) async {
    final sid = await capture.startSession(projectId);
    final ids = await capture.insertPhotos(
      projectId,
      [
        for (var i = 0; i < n; i++)
          NewPhoto(
            sessionId: sid,
            filePath: '/fake/path_${sid}_$i.jpg',
            seq: i + 1,
            takenAt: DateTime(2026, 10, 10, 10, 0, i),
          ),
      ],
    );
    return (sid, ids);
  }

  Future<int> countOf(String sid) async =>
      (await capture.getSession(sid))?.photoCount ?? -1;

  test('删一张 → photo_count 递减 1，照片行消失', () async {
    final (sid, ids) = await sessionWith(3);
    expect(await countOf(sid), 3);

    await deletion.deletePhoto(ids[1]);

    expect(await countOf(sid), 2, reason: '批次计数必须跟着明细走');
    expect(await capture.getPhoto(ids[1]), isNull);
    expect(await capture.getPhoto(ids[0]), isNotNull);
  });

  test('重复删（幂等）→ 计数不再递减，不出现负数', () async {
    final (sid, ids) = await sessionWith(1);
    await deletion.deletePhoto(ids[0]);
    expect(await countOf(sid), 0);

    // 再删一次（不存在）→ 静默返回，计数保持 0
    await deletion.deletePhoto(ids[0]);
    expect(await countOf(sid), 0);

    // 从 0 再删别的也不许出现 -1
    await deletion.deletePhoto('never-existed');
    expect(await countOf(sid), 0);
  });

  test('删到 0 后再插回 → 计数正常累加（递减没破坏累加通路）', () async {
    final (sid, ids) = await sessionWith(2);
    await deletion.deletePhoto(ids[0]);
    await deletion.deletePhoto(ids[1]);
    expect(await countOf(sid), 0);

    await capture.insertPhotos(
      projectId,
      [
        NewPhoto(
          sessionId: sid,
          filePath: '/fake/again.jpg',
          seq: 99,
          takenAt: DateTime(2026, 10, 10, 11, 0),
        ),
      ],
    );
    expect(await countOf(sid), 1);
  });
}
