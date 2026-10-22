import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/app/providers.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';

/// OCR 覆盖统计（v0.24.2）——「照片识别过了没有」的唯一数据源。
///
/// 现场提问（2026-10-15）：「怎么知道图片已经进行过 ocr 了」。
/// 答案分两层，本测试钉的是数据层那一层：
///   · 整理页状态行（UI 层）读本项目口径；
///   · 搜索页空态（UI 层）读全库口径（null）。
/// 口径必须与检索可见范围一致：**软删项目的照片不计入**。
void main() {
  late AppDatabase db;
  late ProjectRepository projects;
  late CaptureRepository capture;
  late ProviderContainer container;

  setUp(() {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    projects = ProjectRepository(db);
    capture = CaptureRepository(db);
    container = ProviderContainer(overrides: [
      appDatabaseProvider.overrideWithValue(db),
    ]);
  });

  tearDown(() async {
    container.dispose();
    await db.close();
  });

  /// 拍 [n] 张进 [projectId]，返回第一张的 id。
  Future<String> shoot(String projectId, {int n = 1}) async {
    final s = await capture.startSession(projectId);
    final ids = await capture.insertPhotos(projectId, [
      for (var i = 0; i < n; i++)
        NewPhoto(
          sessionId: s,
          filePath: '/tmp/cov$i.jpg',
          seq: i + 1,
          takenAt: DateTime(2026, 10, 15, 9, 0, i),
          bytes: 1024,
        ),
    ]);
    await capture.endSession(s);
    return ids.first;
  }

  Future<void> setOcrState(String photoId, String code) async {
    await (db.update(db.photos)..where((p) => p.id.equals(photoId)))
        .write(PhotosCompanion(ocrState: Value(code)));
  }

  /// 等流的第一个数据值（StreamProvider 起手是 loading）。
  Future<OcrPhotoStats> stats(String? projectId) =>
      container.read(ocrPhotoStatsProvider(projectId).future);

  test('本项目口径：pending / done / failed 分开计数', () async {
    final pid = await projects.create(name: '口径A');
    final p1 = await shoot(pid);
    final p2 = await shoot(pid);
    await shoot(pid); // 第 3 张保持 pending（不设状态）
    await setOcrState(p1, 'done');
    await setOcrState(p2, 'failed');

    final s = await stats(pid);
    expect(s.done, 1);
    expect(s.failed, 1);
    expect(s.pending, 1);
    expect(s.total, 3);
    expect(s.hasFailed, isTrue);
  });

  test('running 计入 pending、skipped 计入 done（都是"未完成/已完成"语义）', () async {
    final pid = await projects.create(name: '口径B');
    final p1 = await shoot(pid);
    final p2 = await shoot(pid);
    await setOcrState(p1, 'running');
    await setOcrState(p2, 'skipped');

    final s = await stats(pid);
    expect(s.pending, 1);
    expect(s.done, 1);
    expect(s.failed, 0);
  });

  test('全库口径：跨项目汇总，但排除软删项目', () async {
    final alive = await projects.create(name: '活着');
    final dead = await projects.create(name: '删掉');
    await shoot(alive, n: 2);
    await shoot(dead, n: 5);
    await projects.softDelete(dead);

    final s = await stats(null);
    expect(s.total, 2, reason: '软删项目的 5 张不许进全库口径');
    expect(s.pending, 2);
  });

  test('全库口径与项目口径互不串味', () async {
    final a = await projects.create(name: '甲');
    final b = await projects.create(name: '乙');
    final pa = await shoot(a, n: 2);
    await shoot(b, n: 3);
    await setOcrState(pa, 'done');

    final sa = await stats(a);
    expect(sa.done, 1);
    expect(sa.pending, 1);

    final all = await stats(null);
    expect(all.total, 5);
    expect(all.done, 1);
    expect(all.pending, 4);
  });

  test('空库：total 为 0（UI 据此说"还没有照片"而不是"0 张已识别"）', () async {
    final s = await stats(null);
    expect(s.total, 0);
    expect(s.hasFailed, isFalse);
  });

  test('流式更新：照片状态一变，统计自动推新', () async {
    final pid = await projects.create(name: '流');
    final p1 = await shoot(pid);
    await setOcrState(p1, 'done');
    expect((await stats(pid)).done, 1);

    // 同库再拍一张（pending）——流应推出 total=2 / done=1。
    await shoot(pid);
    expect((await stats(pid)).total, 2);
    expect((await stats(pid)).pending, 1);
  });
}
