import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/model/enums.dart';

/// [CaptureRepository] 的契约测试。
///
/// 这一组用例是「采集期能写什么、不能写什么」的规格说明。
/// 最关键的一条：**这个仓储自始至终没有写 itemId 的能力** ——
/// 断言它,等于断言「采集期零判断」不是靠自觉而是靠结构（§6.1）。
void main() {
  late AppDatabase db;
  late CaptureRepository repo;
  late ProjectRepository projects;
  late String projectId;

  /// 把某个批次的结束时间推到续接窗口之外（10 分钟前）——
  /// 模拟"隔了很久才回来"，下一次 startSession 必然新开批次。
  Future<void> expireSession(String sessionId) async {
    await (db.update(db.captureSessions)..where((t) => t.id.equals(sessionId)))
        .write(CaptureSessionsCompanion(
      endedAt: Value(
        DateTime.now().millisecondsSinceEpoch - 10 * 60 * 1000,
      ),
    ));
  }

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    repo = CaptureRepository(db);
    projects = ProjectRepository(db);
    projectId = await projects.create(name: '测试项目');  });

  tearDown(() async {
    await db.close();
  });

  NewPhoto photo({
    required String sessionId,
    required int seq,
    DateTime? takenAt,
  }) =>
      NewPhoto(
        sessionId: sessionId,
        filePath: '/tmp/p$seq.jpg',
        seq: seq,
        takenAt: takenAt ?? DateTime(2026, 9, 23, 10, 0, seq),
        bytes: 1024,
      );

  // ═══════════════════════════════════════════════════════════
  group('批次（session）生命周期', () {
    test('开批次后 findOpenSession 能找回它', () async {
      final s = await repo.startSession(projectId);
      expect(await repo.findOpenSession(projectId), s);
    });

    test('结束批次后 findOpenSession 返回 null；窗口外可再开新批次', () async {
      final s = await repo.startSession(projectId);
      await repo.endSession(s);
      expect(await repo.findOpenSession(projectId), isNull);

      // 2026-09-27 批次续接窗口（5 分钟）：窗口内再开会**续用**同一批次
      // （「退出对照清单 → 20 秒后再拍」不该被切成两批 —— 时序聚类
      // 按批次分桶，切批就永远无法把跨批照片归到一组）。
      final resumed = await repo.startSession(projectId);
      expect(resumed, s);

      // 把结束时间推到窗口之外，才真正开新批次
      await repo.reopenSession(s); // 先复活再重新结束，保证 endedAt 可控
      await repo.endSession(s);
      await expireSession(s);
      final s2 = await repo.startSession(projectId);
      expect(s2, isNot(s));
    });

    test('endSession 是幂等的 —— 重复结束不报错、不误改别的批次', () async {
      final s = await repo.startSession(projectId);
      await repo.endSession(s);
      await repo.endSession(s);
      expect(await repo.findOpenSession(projectId), isNull);
    });

    test('相册批次带 source=album —— 分组算法据此跳过时序聚类', () async {
      final s = await repo.startSession(
        projectId,
        source: CaptureSource.album,
        note: '相册导入 3 张',
      );
      final row = await repo.getSession(s);
      expect(row?.source, CaptureSource.album.code);
      expect(row?.note, '相册导入 3 张');
    });

    test('按项目隔离：另一个项目的开放批次不会串味', () async {
      final other = await projects.create(name: '另一个项目');
      final s1 = await repo.startSession(projectId);
      final s2 = await repo.startSession(other);
      expect(await repo.findOpenSession(projectId), s1);
      expect(await repo.findOpenSession(other), s2);
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 批次续接窗口（2026-09-27 相机 → 2026-09-29 扩展到相册）
  //
  // 根因：时序聚类按批次分桶（组表 sessionId 外键），切批就永远
  // 无法把时间相邻的照片归到一组。两个来源各有切批节奏 ——
  //   · 相机：「拍一件 → 退出对照清单 → 20 秒后再进拍下一件」；
  //   · 相册：「导一批 → 想起漏了几张 → 过一两分钟再导一批」。
  // 修法：同来源批次 5 分钟内结束的，下一次 startSession 复活续用；
  // 来源隔离不破（album 只续 album、camera 只续 camera）。
  // ═══════════════════════════════════════════════════════════
  group('批次续接窗口', () {
    test('窗口内结束的相机批次会被 findResumableSession 找回', () async {
      final s = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [photo(sessionId: s, seq: 1)]);
      await repo.endSession(s);

      final r = await repo.findResumableSession(
        projectId,
        source: CaptureSource.camera,
        window: const Duration(minutes: 5),
      );
      expect(r, isNotNull);
      expect(r!.id, s);
      expect(r.photoCount, 1);
    });

    test('超过窗口的批次不续接', () async {
      final s = await repo.startSession(projectId);
      await repo.endSession(s);
      await expireSession(s);

      final r = await repo.findResumableSession(
        projectId,
        source: CaptureSource.camera,
        window: const Duration(minutes: 5),
      );
      expect(r, isNull);
    });

    test('相机路径不续用相册批次（来源隔离）；相册查询只命中相册批次', () async {
      final album = await repo.startSession(
        projectId,
        source: CaptureSource.album,
      );
      await repo.endSession(album);

      // 相册批次不能被 camera 路径续走
      expect(
        await repo.findResumableSession(
          projectId,
          source: CaptureSource.camera,
          window: const Duration(minutes: 5),
        ),
        isNull,
      );
      // album 来源的查询命中它自己的批次 —— source 过滤是双向生效的
      expect(
        (await repo.findResumableSession(
          projectId,
          source: CaptureSource.album,
          window: const Duration(minutes: 5),
        ))!
            .id,
        album,
      );
    });

    test('续接不跨项目', () async {
      final other = await projects.create(name: 'B 项目');
      final s = await repo.startSession(projectId);
      await repo.endSession(s);

      expect(
        await repo.findResumableSession(
          other,
          source: CaptureSource.camera,
          window: const Duration(minutes: 5),
        ),
        isNull,
      );
    });

    test('reopenSession 复活批次；对开放批次是 no-op', () async {
      final s = await repo.startSession(projectId);
      await repo.endSession(s);
      await repo.reopenSession(s);

      final row = await repo.getSession(s);
      expect(row?.endedAt, isNull); // 已复活
      expect(await repo.findOpenSession(projectId), s);

      // 对开放批次再 reopen —— 无害（where 条件挡住，endedAt 保持 NULL）
      await repo.reopenSession(s);
      expect((await repo.getSession(s))?.endedAt, isNull);
    });

    test('取「最近结束」的那一个续接（多次退出后回到最后一段作业）', () async {
      final s1 = await repo.startSession(projectId);
      await repo.endSession(s1);
      await expireSession(s1); // 很久以前的一段

      final s2 = await repo.startSession(projectId);
      await repo.endSession(s2); // 刚结束的一段

      final r = await repo.findResumableSession(
        projectId,
        source: CaptureSource.camera,
        window: const Duration(minutes: 5),
      );
      expect(r?.id, s2);
    });

    test('窗口内结束的相册批次会被下一次相册导入续用（2026-09-29）', () async {
      // 「导一批 → 想起漏了几张 → 过一两分钟再导一批」：
      // 两批照片时间相邻，分属两批就永远聚不到一组
      final s1 = await repo.startSession(
        projectId,
        source: CaptureSource.album,
      );
      await repo.insertPhotos(projectId, [photo(sessionId: s1, seq: 1)]);
      await repo.endSession(s1);

      final s2 = await repo.startSession(
        projectId,
        source: CaptureSource.album,
        note: '相册导入 2 张',
      );
      expect(s2, s1); // 续用，不是新开

      // 复活后的批次仍是 album 来源、photoCount 续读
      final row = await repo.getSession(s2);
      expect(row?.source, CaptureSource.album.code);
      expect(row?.photoCount, 1);
      expect(row?.endedAt, isNull);
    });

    test('相册导入不续用相机批次（来源隔离）', () async {
      final cam = await repo.startSession(projectId); // 刚结束的相机批次
      await repo.endSession(cam);

      final s = await repo.startSession(
        projectId,
        source: CaptureSource.album,
      );
      expect(s, isNot(cam));
      expect((await repo.getSession(s))?.source, CaptureSource.album.code);
    });

    test('超过窗口的相册批次不续接', () async {
      final s = await repo.startSession(
        projectId,
        source: CaptureSource.album,
      );
      await repo.endSession(s);
      await expireSession(s);

      final s2 = await repo.startSession(
        projectId,
        source: CaptureSource.album,
      );
      expect(s2, isNot(s));
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 「补存到相册」的范围：只有 App 内拍的（老板 2026-09-29 拍板）
  //
  // 相册 / 微信导入的照片本来就在手机里，再抄一份进「集刻-采集」
  // 就是相册里的重复件 —— 补存的输入必须是**相机来源**的照片。
  // ═══════════════════════════════════════════════════════════
  group('相册补存范围', () {
    test('capturedPhotos 只收相机来源的照片，按 seq 升序', () async {
      final cam = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [
        photo(sessionId: cam, seq: 1),
        photo(sessionId: cam, seq: 2),
      ]);
      final album = await repo.startSession(
        projectId,
        source: CaptureSource.album,
      );
      await repo.insertPhotos(projectId, [photo(sessionId: album, seq: 3)]);

      final photos = await repo.capturedPhotos(projectId);
      expect(photos, hasLength(2));
      expect(photos.first.srcPath, '/tmp/p1.jpg');
      expect(photos.first.displayName, 'p1.jpg');
      expect(photos.last.srcPath, '/tmp/p2.jpg');
      // 拍摄时刻要带上 —— 相册按它排序（补存几百张时不能乱序）
      expect(photos.first.takenAt, isNotNull);
    });

    test('capturedPhotoCount 与 capturedPhotos 同口径（导入照片不计）', () async {
      final cam = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [photo(sessionId: cam, seq: 1)]);
      final album = await repo.startSession(
        projectId,
        source: CaptureSource.album,
      );
      await repo.insertPhotos(projectId, [
        photo(sessionId: album, seq: 2),
        photo(sessionId: album, seq: 3),
      ]);

      expect(await repo.capturedPhotoCount(projectId), 1);
      expect(await repo.capturedPhotos(projectId), hasLength(1));
    });

    test('只有导入照片的项目：补存范围为空（相册卡不显示补存入口）', () async {
      final album = await repo.startSession(
        projectId,
        source: CaptureSource.album,
      );
      await repo.insertPhotos(projectId, [photo(sessionId: album, seq: 1)]);

      expect(await repo.capturedPhotos(projectId), isEmpty);
      expect(await repo.capturedPhotoCount(projectId), 0);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('序号（seq）', () {
    test('空项目 nextSeq 从 1 开始', () async {
      expect(await repo.nextSeq(projectId), 1);
    });

    test('插入后 nextSeq 接着最大值往下（跨批次连续，不复用）', () async {
      final s = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
        photo(sessionId: s, seq: 2),
      ]);
      await repo.endSession(s);

      await repo.startSession(projectId);
      // 关键：新批次不从头编号 —— 否则交付时 `{编码}_{2位序号}` 会撞名
      expect(await repo.nextSeq(projectId), 3);
    });

    test('seq 按项目独立计算', () async {
      final other = await projects.create(name: 'B 项目');
      final s = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [photo(sessionId: s, seq: 1)]);

      expect(await repo.nextSeq(other), 1);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('照片入库', () {
    test('新照片一律是 unassigned 且 itemId 为 null —— 采集期不可能带归属', () async {
      final s = await repo.startSession(projectId);
      final ids = await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
      ]);
      expect(ids.length, 1);

      final row = await repo.getPhoto(ids.first);
      expect(row, isNotNull);
      expect(row!.itemId, isNull);
      expect(row.state, PhotoState.unassigned.code);
    });

    test('批量插入是一次事务 —— 中途失败不会留下半批照片', () async {
      final s = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
        photo(sessionId: s, seq: 2),
        photo(sessionId: s, seq: 3),
      ]);

      // 用同一 seq 再插一次（假设有唯一约束会失败）——
      // 无论约束在不在，这条断言的意义是：要么全进要么全不进。
      expect(await repo.watchLatestThumbs(projectId).first, hasLength(3));
    });

    test('插入后会话计数随之增长', () async {
      final s = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
        photo(sessionId: s, seq: 2),
      ]);
      final row = await repo.getSession(s);
      expect(row?.photoCount, 2);
    });

    test('张数流随插入变化（采集页顶部的数字来源）', () async {
      final s = await repo.startSession(projectId);
      expect(await repo.watchPhotoCount(projectId).first, 0);

      await repo.insertPhotos(projectId, [photo(sessionId: s, seq: 1)]);
      expect(await repo.watchPhotoCount(projectId).first, 1);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('媒体信息回填（缩略图 / 尺寸）', () {
    test('patchMediaInfo 只动那几列，不碰归属也不碰 state', () async {
      final s = await repo.startSession(projectId);
      final id = (await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
      ]))
          .first;

      await repo.patchMediaInfo(
        id,
        thumbPath: '/tmp/t$id.jpg',
        width: 1920,
        height: 1080,
      );

      final row = await repo.getPhoto(id);
      expect(row?.thumbPath, '/tmp/t$id.jpg');
      expect(row?.width, 1920);
      expect(row?.height, 1080);
      // 不变的部分必须一点没变
      expect(row?.itemId, isNull);
      expect(row?.state, PhotoState.unassigned.code);
      expect(row?.seq, 1);
    });

    test('尺寸回填可以为 null（缩略图失败时不影响入库）', () async {
      final s = await repo.startSession(projectId);
      final id = (await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
      ]))
          .first;

      await repo.patchMediaInfo(id, thumbPath: null, width: null, height: null);
      final row = await repo.getPhoto(id);
      expect(row?.width, isNull);
      expect(row?.thumbPath, isNull);
    });

    test('patchMediaInfo 只更新传入列：回填缩略图不抹 bytes，修 bytes 不抹缩略图',
        () async {
      // 2026-10-21 修复：旧实现对未传字段也写 Value(null) ——
      // 缩略图回填把 bytes 清空、修复路径又把 thumbPath/width/height 清空。
      final s = await repo.startSession(projectId);
      final id = (await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
      ]))
          .first;

      await repo.patchMediaInfo(
        id,
        thumbPath: '/tmp/t.jpg',
        width: 100,
        height: 80,
      );
      var row = await repo.getPhoto(id);
      expect(row!.bytes, 1024, reason: '缩略图回填不能把 bytes 写成 NULL');
      expect(row.thumbPath, '/tmp/t.jpg');
      expect(row.width, 100);

      await repo.patchMediaInfo(id, bytes: 2048);
      row = await repo.getPhoto(id);
      expect(row!.bytes, 2048);
      expect(row.thumbPath, '/tmp/t.jpg', reason: '修复只改 bytes，缩略图路径必须保留');
      expect(row.width, 100, reason: '修复只改 bytes，宽高必须保留');
    });

    test('photosMissingThumb 只挑还没缩略图的那些', () async {
      final s = await repo.startSession(projectId);
      final ids = await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
        photo(sessionId: s, seq: 2),
      ]);

      await repo.patchMediaInfo(ids[0], thumbPath: '/tmp/a.jpg');

      final missing = await repo.photosMissingThumb(projectId);
      expect(missing.map((p) => p.id), [ids[1]]);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('缩略图视图（PhotoThumb）—— 类型层面的隔离', () {
    test('watchLatestThumbs 按拍摄时间倒序，返回 id + 缩略图路径', () async {
      final s = await repo.startSession(projectId);
      final ids = await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1, takenAt: DateTime(2026, 9, 23, 10, 0, 1)),
        photo(sessionId: s, seq: 2, takenAt: DateTime(2026, 9, 23, 10, 0, 2)),
        photo(sessionId: s, seq: 3, takenAt: DateTime(2026, 9, 23, 10, 0, 3)),
      ]);
      await repo.patchMediaInfo(ids[2], thumbPath: '/tmp/newest.jpg');

      final thumbs = await repo.watchLatestThumbs(projectId).first;
      expect(thumbs.map((t) => t.id).toList(), [
        ids[2],
        ids[1],
        ids[0],
      ]);
      expect(thumbs.first.thumbPath, '/tmp/newest.jpg');
      expect(thumbs[1].thumbPath, isNull);
    });

    test('limit 生效（胶片条只要最近几张）', () async {
      final s = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [
        for (var i = 1; i <= 8; i++) photo(sessionId: s, seq: i),
      ]);

      final thumbs = await repo.watchLatestThumbs(projectId, limit: 5).first;
      expect(thumbs, hasLength(5));
    });

    test('没有照片时返回空表，不抛', () async {
      expect(await repo.watchLatestThumbs(projectId).first, isEmpty);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('读取辅助', () {
    test('hasChecklist 反映清单是否已导入', () async {
      expect(await repo.hasChecklist(projectId), isFalse);
    });

    test('totalPhotoBytes 汇总字节数', () async {
      final s = await repo.startSession(projectId);
      await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
        photo(sessionId: s, seq: 2),
      ]);
      expect(await repo.totalPhotoBytes(projectId), 2048);
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 系统相机收图账本（2026-10-21）
  // ═══════════════════════════════════════════════════════════
  group('系统相机收图账本', () {
    const src = '/dcim/Camera/IMG_20261021_100000.jpg';

    Future<SystemShotClaim> claim(String sessionId) => repo.claimSystemShot(
          projectId: projectId,
          sessionId: sessionId,
          sourcePath: src,
          sourceSize: 1024,
          sourceMtime: 100,
          takenAtMs: 200,
        );

    test('claim → stored → claim 复用同一 photoId，不重复插行', () async {
      final s = await repo.startSession(projectId);
      final id = (await repo.insertPhotos(projectId, [
        photo(sessionId: s, seq: 1),
      ]))
          .single;

      final first = await claim(s);
      expect(first.reused, isFalse, reason: '首次认领不该返回照片 id');

      // 同一瞬间第二路（旧场晚到 vs 新场首批）来认领：必须让路，
      // 不许两路同时复制/插行。
      final concurrent = await claim(s);
      expect(concurrent.inFlight, isTrue);
      expect(concurrent.reused, isFalse);

      await repo.markSystemShotStored(
        projectId: projectId,
        sourcePath: src,
        photoId: id,
      );

      final again = await claim(s);
      expect(again.photoId, id, reason: '同一原图路径必须复用已入库的照片');
      expect(again.alreadyStored, isTrue);
      expect(await repo.storedSystemPaths(projectId), contains(src));
      expect(
        await repo.systemShotPhotoId(projectId: projectId, sourcePath: src),
        id,
      );

      // 项目里仍然只有一行
      expect(await repo.watchPhotoCount(projectId).first, 1);
    });

    test('失败后重试：状态回到 ingesting，stored 集合不命中', () async {
      final s = await repo.startSession(projectId);
      final first = await claim(s);
      expect(first.reused, isFalse);

      await repo.markSystemShotFailed(
        projectId: projectId,
        sourcePath: src,
        error: 'copy failed',
      );
      expect(await repo.storedSystemPaths(projectId), isEmpty);

      final retry = await claim(s);
      expect(retry.reused, isFalse, reason: '失败的行要允许重新收');
      expect(await repo.storedSystemPaths(projectId), isEmpty);
    });
  });
}
