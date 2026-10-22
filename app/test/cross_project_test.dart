// 跨项目搬移 + 补拍保护（2026-10-08 真机反馈 ①②③④）。
//
// 三块契约：
//  1. **补拍保护**：「补充照片」进行中的目标组不被 regroup 回收 ——
//     不加保护的话，单张组会在补拍期间被回收掉，拍完回来 attach
//     炸「目标组不存在」（真机截图 2026-10-08），新照片被孤成小组。
//  2. **组跨项目移动**：照片/组换项目、换新批次、seq 接目标项目续排、
//     物理文件搬家不改名；已指派组拒绝移动。
//  3. **项目合并**：源项目全部照片/组/批次/交付记录并入目标项目，
//     seq 重排，源项目归档（从列表消失、可追溯）；有已归属组时拒绝。
//
// ⚠️ 文件搬移测试用真实临时目录 + [ProjectPaths.overrideRootForTest]。
// tearDown 顺序（铁律 10）：删目录 → 解除覆写 → 关库。
import 'dart:io';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/fs/project_paths.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/organize_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:path/path.dart' as p;

void main() {
  late AppDatabase db;
  late CaptureRepository capture;
  late OrganizeRepository organize;
  late ProjectRepository projects;
  late Directory tempRoot;
  late String projA;
  late String projB;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    capture = CaptureRepository(db);
    organize = OrganizeRepository(db);
    projects = ProjectRepository(db);
    tempRoot = await Directory.systemTemp.createTemp('gtick_xproj');
    ProjectPaths.overrideRootForTest(tempRoot);
    projA = await projects.create(name: '项目A');
    projB = await projects.create(name: '项目B');
  });

  tearDown(() async {
    // 顺序：删目录 → 解覆写 → 关库（铁律 10）
    try {
      await tempRoot.delete(recursive: true);
    } catch (_) {}
    ProjectPaths.overrideRootForTest(null);
    await db.close();
  });

  DateTime t(int sec) => DateTime(2026, 10, 8, 10, 0, sec);

  /// 项目 [pid] 里开一个相机批次并拍 [n] 张真实文件，关批次，返回
  /// (sessionId, photoIds)。
  ///
  /// ⚠️ 结束时间**回拨 10 分钟**（越过 5 分钟续接窗口）：否则连续两次
  /// cameraBatch 会被 startSession 续接成同一批次，regroup 只建一个组
  /// ——「真两批」的测试前提就塌了（同 organize_repository_test 的
  /// cameraSessionExpired 机理）。
  Future<(String, List<String>)> cameraBatch(String pid, int n) async {
    final s = await capture.startSession(pid);
    final ids = <String>[];
    for (var i = 1; i <= n; i++) {
      final takenAt = t(i);
      final dir = await ProjectPaths.rawDir(pid, s);
      final f = File(p.join(dir.path, 'f_${s.substring(0, 6)}_$i.jpg'));
      await f.writeAsBytes(List.generate(64, (i) => i));
      ids.addAll(await capture.insertPhotos(pid, [
        NewPhoto(
          sessionId: s,
          filePath: f.path,
          seq: i,
          takenAt: takenAt,
          bytes: 64,
        ),
      ]));
    }
    await capture.endSession(s);
    await (db.update(db.captureSessions)..where((x) => x.id.equals(s)))
        .write(CaptureSessionsCompanion(
      endedAt: Value(
        DateTime.now().millisecondsSinceEpoch - 10 * 60 * 1000,
      ),
    ));
    return (s, ids);
  }

  /// 同 [cameraBatch]，但**不回拨结束时间** —— 下一次 startSession 会在
  /// 5 分钟续接窗口内续用同一批次（补拍的真实节奏）。
  Future<(String, List<String>)> cameraBatchSameSession(
    String pid,
    int n, {
    int startSeq = 1,
  }) async {
    final s = await capture.startSession(pid);
    final ids = <String>[];
    for (var i = 1; i <= n; i++) {
      final takenAt = t(startSeq + i - 1);
      final dir = await ProjectPaths.rawDir(pid, s);
      final f = File(
          p.join(dir.path, 'f_${s.substring(0, 6)}_${startSeq + i - 1}.jpg'));
      await f.writeAsBytes(List.generate(64, (i) => i));
      ids.addAll(await capture.insertPhotos(pid, [
        NewPhoto(
          sessionId: s,
          filePath: f.path,
          seq: startSeq + i - 1,
          takenAt: takenAt,
          bytes: 64,
        ),
      ]));
    }
    await capture.endSession(s);
    return (s, ids);
  }

  Future<List<PhotoGroup>> groupsOf(String pid) => (db.select(db.photoGroups)
        ..where((g) => g.projectId.equals(pid)))
      .get();

  Future<List<Photo>> photosOf(String pid) => (db.select(db.photos)
        ..where((p) => p.projectId.equals(pid)))
      .get();

  group('补拍保护：目标组不被 regroup 回收', () {
    test('保护期间：单张目标组存活，attach 成功', () async {
      // 源头：先拍 1 张 → regroup 建出单张组（老板"先拍一张再回来补"的常态）
      await cameraBatch(projA, 1);
      await organize.regroupPending(projA);
      final g0 = await groupsOf(projA);
      expect(g0, hasLength(1));
      final targetId = g0.first.id;

      // 补拍开始：上保护 → 再进 2 张（新批次）→ regroup 触发
      organize.protectGroupFromRegroup(targetId);
      await cameraBatch(projA, 2);
      await organize.regroupPending(projA);

      // 目标组还在，老照片没被挪走
      final g1 = await groupsOf(projA);
      expect(g1.any((x) => x.id == targetId), isTrue,
          reason: '保护期间目标组不能被回收');

      // 拍完回来 attach —— 修复前这里炸「目标组不存在」。
      // ⚠️ 新照片此时**已经在 regroup 建的新组里**（同批次自动成组），
      // 不是游离的 —— attach 是移动语义，会把它们从新组搬进目标组。
      final all = await photosOf(projA);
      final newOnes = all.where((x) => x.groupId != targetId).toList();
      expect(newOnes, hasLength(2));
      final n = await organize.attachPhotosToGroup(
          projA, targetId, newOnes.map((x) => x.id).toList());
      expect(n, 2);
      organize.unprotectGroup(targetId);

      final after = await photosOf(projA);
      expect(after.every((x) => x.groupId == targetId), isTrue);
    });

    test('无保护 + 同批补拍：单张组被回收，attach 炸「目标组不存在」', () async {
      // ⚠️ 必须**同批次**：10-09 起回收口径收窄到「活跃批次」—— 跨批次的
      // 老组不再被别的批次的 regroup 碰（两批各自成组才符合「一批一组」，
      // 10-09 真机反馈的另一半）。补拍在 5 分钟续接窗口内续用同一批次
      // —— 这才是目标组会被回收的真实场景，也是 protectGroupFromRegroup
      // 存在的理由。
      await cameraBatchSameSession(projA, 1);
      await organize.regroupPending(projA);
      final targetId = (await groupsOf(projA)).first.id;

      // 不加保护：同批续拍 2 张触发 regroup → 目标组被回收重聚
      await cameraBatchSameSession(projA, 2, startSeq: 2);
      await organize.regroupPending(projA);

      final g1 = await groupsOf(projA);
      expect(g1.any((x) => x.id == targetId), isFalse,
          reason: '这就是真机事故的机理：目标组被回收掉了');

      // 拿全部照片 attach 到已死的组（模拟老板点了「加入第 N 组」
      // 返回的那一下）→ 必须炸「目标组不存在」
      final all = (await photosOf(projA)).map((x) => x.id).toList();
      expect(all, isNotEmpty);
      await expectLater(
        organize.attachPhotosToGroup(projA, targetId, all),
        throwsA(isA<StateError>()),
      );
    });
  });

  group('组跨项目移动', () {
    test('照片/组换项目、新批次承接、seq 续排、文件搬家不改名', () async {
      final (sidA, ids) = await cameraBatch(projA, 2);
      await organize.regroupPending(projA);
      final g = (await groupsOf(projA)).single;
      final gSeq = g.seq;

      // B 项目先有 1 张（photo seq = 1），移过去的要从 2 开始。
      // ⚠️ 必须给 B 也跑 regroupPending —— B 那张不归组的话 B 组数为 0，
      // 「seq 接 B 的组序」就退化成 seq==1，断言失去意义（前提写错 =
      // 永远绿的拐杖，10-08 教训同 Flutter 侧）。
      final (sidB, _) = await cameraBatch(projB, 1);
      await organize.regroupPending(projB);

      final oldPaths = (await photosOf(projA)).map((x) => x.filePath).toList();
      final oldNames =
          oldPaths.map((x) => p.basename(x)).toList(); // 文件名必须保持不变

      await organize.moveGroupToProject(
        fromProjectId: projA,
        groupId: g.id,
        toProjectId: projB,
      );

      // A 里没有照片了
      expect(await photosOf(projA), isEmpty);
      expect(await groupsOf(projA), isEmpty);

      // B 里：原 1 张 + 移来 2 张 = 3；组 2 个
      final bPhotos = await photosOf(projB);
      expect(bPhotos, hasLength(3));
      final moved = bPhotos.where((x) => ids.contains(x.id)).toList();
      expect(moved, hasLength(2));
      // seq 接目标项目最大值续排（B 原有 1 → 2、3）
      final movedSeq = moved.map((x) => x.seq).toSet();
      expect(movedSeq.containsAll([2, 3]), isTrue, reason: 'seq 必须续排');
      // 新批次：不是 A 的批次，也不是 B 原批次
      expect(moved.every((x) => x.sessionId != sidA && x.sessionId != sidB),
          isTrue);
      // 文件搬到 B 的 raw/{新批次}/ 下：文件名不变（§6.4 永不改名），旧文件消失
      final movedNames = moved.map((x) => p.basename(x.filePath)).toSet();
      expect(movedNames, equals(oldNames.toSet()));
      for (final ph in moved) {
        expect(File(ph.filePath).existsSync(), isTrue,
            reason: '新路径文件必须真实存在');
        expect(ph.filePath.contains(projB), isTrue);
      }
      for (final op in oldPaths) {
        expect(File(op).existsSync(), isFalse, reason: '旧路径文件必须已搬走');
      }

      // 组换项目 + seq 接 B 的组序（B 原有 1 组 → 移来的 seq = 2）
      final bGroups = await groupsOf(projB);
      expect(bGroups, hasLength(2));
      final movedGroup = bGroups.firstWhere((x) => x.id == g.id);
      expect(movedGroup.seq, greaterThan(gSeq));
      expect(movedGroup.projectId, projB);

      // 承接批次已关闭（不能被相机续拍续进去）
      final sessionRow = await (db.select(db.captureSessions)
            ..where((s) => s.id.equals(moved.first.sessionId)))
          .getSingle();
      expect(sessionRow.projectId, projB);
      expect(sessionRow.endedAt, isNotNull);
    });

    test('已指派组拒绝移动', () async {
      await cameraBatch(projA, 2);
      await organize.regroupPending(projA);
      final g = (await groupsOf(projA)).single;
      await (db.update(db.photoGroups)..where((x) => x.id.equals(g.id)))
          .write(const PhotoGroupsCompanion(itemId: Value('item-x')));

      await expectLater(
        organize.moveGroupToProject(
            fromProjectId: projA, groupId: g.id, toProjectId: projB),
        throwsA(isA<StateError>()),
      );
    });

    test('同项目拒绝', () async {
      await cameraBatch(projA, 1);
      await organize.regroupPending(projA);
      final g = (await groupsOf(projA)).single;
      await expectLater(
        organize.moveGroupToProject(
            fromProjectId: projA, groupId: g.id, toProjectId: projA),
        throwsA(isA<ArgumentError>()),
      );
    });
  });

  group('项目合并', () {
    test('全部照片/组/批次并入目标，seq 重排，源项目归档', () async {
      // A：两个批次 → 2 组 3 张（一批 2 张 + 一批 1 张）
      final (s1, _) = await cameraBatch(projA, 2);
      final (s2, _) = await cameraBatch(projA, 1);
      await organize.regroupPending(projA);
      final aGroups = await groupsOf(projA);
      expect(aGroups, hasLength(2));

      // B：先有 1 组 1 张（seq 1 / photo seq 1）
      await cameraBatch(projB, 1);
      await organize.regroupPending(projB);

      // A 有一条交付记录 —— 历史凭证跟照片走
      await db.into(db.deliveries).insert(DeliveriesCompanion.insert(
            id: 'dlv-1',
            projectId: projA,
            createdAt: DateTime.now().millisecondsSinceEpoch,
            optionsJson: '{}',
          ));

      await organize.mergeProjectInto(
          fromProjectId: projA, toProjectId: projB);

      // A 清空、归档
      expect(await photosOf(projA), isEmpty);
      expect(await groupsOf(projA), isEmpty);
      final aRow = await (db.select(db.projects)
            ..where((x) => x.id.equals(projA)))
          .getSingle();
      expect(aRow.deletedAt, isNotNull, reason: '源项目必须归档而不是物理删除');

      // B：4 张照片，seq 1..4 连续；2 组（原 1 + 移来 2）
      final bPhotos = await photosOf(projB);
      expect(bPhotos, hasLength(4));
      final seqs = bPhotos.map((x) => x.seq).toList()..sort();
      expect(seqs, [1, 2, 3, 4], reason: '合并照片的 seq 必须接目标项目重排');

      final bGroups = await groupsOf(projB);
      expect(bGroups, hasLength(3));
      final gseqs = bGroups.map((x) => x.seq).toList()..sort();
      expect(gseqs, [1, 2, 3], reason: '组 seq 同样接目标项目重排');

      // 批次都归 B；原文件路径指向 B 项目目录且文件真实存在
      final sessionsB = await (db.select(db.captureSessions)
            ..where((x) => x.projectId.equals(projB)))
          .get();
      expect(sessionsB.map((x) => x.id).toSet(), containsAll([s1, s2]));
      for (final ph in bPhotos) {
        expect(File(ph.filePath).existsSync(), isTrue,
            reason: '合并后文件必须真实存在：${ph.filePath}');
      }

      // 交付记录跟着走
      final dlv = await (db.select(db.deliveries)
            ..where((x) => x.id.equals('dlv-1')))
          .getSingle();
      expect(dlv.projectId, projB);

      // 活跃项目列表里 A 消失
      final list = await projects.watchAll().first;
      expect(list.any((x) => x.id == projA), isFalse);
      expect(list.any((x) => x.id == projB), isTrue);
    });

    test('源项目有已归属组时拒绝合并', () async {
      await cameraBatch(projA, 2);
      await organize.regroupPending(projA);
      final g = (await groupsOf(projA)).single;
      await (db.update(db.photoGroups)..where((x) => x.id.equals(g.id)))
          .write(const PhotoGroupsCompanion(itemId: Value('item-x')));

      await expectLater(
        organize.mergeProjectInto(
            fromProjectId: projA, toProjectId: projB),
        throwsA(isA<StateError>()),
      );
      // 拒绝后 A 的数据原封不动
      expect(await photosOf(projA), hasLength(2));
    });
  });
}
