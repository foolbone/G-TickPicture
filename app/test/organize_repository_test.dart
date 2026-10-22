// hide isNull/isNotNull：drift 的列扩展与 matcher 的断言重名 —— 测试里要的是断言
import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/item_repository.dart';
import 'package:g_tick_picture/data/repo/organize_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/assign/assign_service.dart';
import 'package:g_tick_picture/domain/model/assigned_group.dart';
import 'package:g_tick_picture/domain/model/checklist_row.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/model/open_group.dart';

/// [OrganizeRepository] 的契约测试 —— 整理页数据引擎（M3 / §5.4）。
///
/// 断言的不是实现细节，而是四条架构承诺：
///  1. **分组是建议**（2026-09-29 老板拍板：**按批次一组**）：
///     一批（captureSession —— 相册一次导入 / 相机一段连拍）整批一组，
///     不再按时序间隔拆分；跨批次绝不混组（组表有 sessionId 外键）。
///     错分只代价一次合并，不漏不分。
///  2. **幂等可续**：[OrganizeRepository.regroupPending] 处理没组的照片
///     + 未指派的单张组（边拍边触发时先把先到的照片拉回来），多张组与
///     已确认的组永不回收 ——「随手清 + 收工统过」双路径共用同一套数据
///     而不互相踩（S6）。
///  3. **归属不可触碰**：本仓储的任何写路径都到不了 `itemId` /
///     `state` —— 那是 AssignService 的地盘（架构规则 3）。
///  4. **部类卫生**：监装照片不参与分组 —— 游离的留在照片墙，
///     监装组不被回收重组（2026-09-27 修复，2026-09-29 沿用）。
void main() {
  late AppDatabase db;
  late CaptureRepository capture;
  late OrganizeRepository organize;
  late ProjectRepository projects;
  late String projectId;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    capture = CaptureRepository(db);
    organize = OrganizeRepository(db);
    projects = ProjectRepository(db);
    projectId = await projects.create(name: '整理测试');
  });

  tearDown(() async {
    await db.close();
  });

  // ── 夹具 ────────────────────────────────────────────────

  DateTime t(int sec) => DateTime(2026, 9, 23, 10, 0, sec);

  NewPhoto ph(String sessionId, int seq, DateTime takenAt) => NewPhoto(
        sessionId: sessionId,
        filePath: '/tmp/p$seq.jpg',
        seq: seq,
        takenAt: takenAt,
        bytes: 1024,
      );

  /// 开一个相机批次、插 [n] 张（间隔 [gapSec] 秒）、关批次。
  Future<(String, List<String>)> cameraSession(int n, {int gapSec = 10}) async {
    final s = await capture.startSession(projectId);
    final photos = [
      for (var i = 0; i < n; i++) ph(s, i + 1, t(i * gapSec)),
    ];
    final ids = await capture.insertPhotos(projectId, photos);
    await capture.endSession(s);
    return (s, ids);
  }

  /// 同 [cameraSession]，但把结束时间推到**批次续接窗口之外**
  /// （10 分钟前）。2026-09-27 起窗口内退出再进会续用同一批次；
  /// 需要"真两批"的测试用这个夹具越过窗口。
  Future<(String, List<String>)> cameraSessionExpired(
    int n, {
    int gapSec = 10,
  }) async {
    final (s, ids) = await cameraSession(n, gapSec: gapSec);
    await (db.update(db.captureSessions)..where((x) => x.id.equals(s)))
        .write(CaptureSessionsCompanion(
      endedAt: Value(
        DateTime.now().millisecondsSinceEpoch - 10 * 60 * 1000,
      ),
    ));
    return (s, ids);
  }

  /// 开一个相册批次、按给定时间戳插照片、关批次。
  Future<(String, List<String>)> albumSession(List<DateTime> times) async {
    final s = await capture.startSession(projectId, source: CaptureSource.album);
    final photos = [
      for (var i = 0; i < times.length; i++) ph(s, i + 1, times[i]),
    ];
    final ids = await capture.insertPhotos(projectId, photos);
    await capture.endSession(s);
    return (s, ids);
  }

  Future<List<Photo>> photos() => (db.select(db.photos)
        ..where((p) => p.projectId.equals(projectId)))
      .get();

  Future<List<PhotoGroup>> groups() => (db.select(db.photoGroups)
        ..where((g) => g.projectId.equals(projectId)))
      .get();

  /// 某个组实际挂了多少张照片（与 photoCount 字段对比用）。
  Future<int> countInGroup(AppDatabase database, String groupId) async {
    final rows = await (database.select(database.photos)
          ..where((p) => p.groupId.equals(groupId)))
        .get();
    return rows.length;
  }

  /// 轮询等条件成立（drift 的写→推流是异步的，测试不能靠固定 sleep）。
  Future<bool> waitUntil(
    bool Function() cond, {
    Duration timeout = const Duration(seconds: 3),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      if (cond()) return true;
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    return cond();
  }

  /// 模拟 AssignService 确认归属后的终态（组 + 组内照片都写 itemId）。
  Future<void> simulateConfirm(String groupId) async {
    await (db.update(db.photoGroups)..where((g) => g.id.equals(groupId)))
        .write(const PhotoGroupsCompanion(itemId: Value('item-x')));
    await (db.update(db.photos)..where((p) => p.groupId.equals(groupId)))
        .write(PhotosCompanion(
      // 注意：外层 Companion 不能 const —— 内含 enum getter（铁律 16）
      itemId: const Value('item-x'),
      state: Value(PhotoState.confirmed.code),
    ));
  }

  // ═════════════════════════════════════════════════════════
  // regroupPending —— 相机批次（2026-09-29：一批一组）
  // ═════════════════════════════════════════════════════════

  group('regroupPending · 相机批次（一批一组）', () {
    test('同一批次整批一组，与拍摄间隔无关', () async {
      // 间隔 60 秒的 3 张在旧时序规则下会被拆成 3 组；
      // 按批次规则下它们是「连续拍摄的一段」，必须是一组。
      await cameraSession(3, gapSec: 60);

      final created = await organize.regroupPending(projectId);
      expect(created, 1);

      final gs = await groups();
      expect(gs, hasLength(1));
      expect(gs.single.photoCount, 3);
      expect(gs.single.origin, GroupOrigin.camera.code);
      final ps = await photos();
      expect(ps.map((p) => p.groupId), everyElement(gs.single.id));
    });

    test('批次没有张数上限：13 张连续拍也是一组', () async {
      await cameraSession(13, gapSec: 1);

      final created = await organize.regroupPending(projectId);
      expect(created, 1);
      final gs = await groups();
      expect(gs.single.photoCount, 13);
    });

    test('不同批次不混组（时间交错也各归各桶）', () async {
      final (_, idsA) = await cameraSessionExpired(2, gapSec: 2); // t(0), t(2)
      // 再开一个批次，插一张时间落在 A 中间的照片
      final sB = await capture.startSession(projectId);
      final idsB = await capture.insertPhotos(
        projectId,
        [ph(sB, 3, t(1))],
      );
      await capture.endSession(sB);

      await organize.regroupPending(projectId);
      final gs = await groups();
      expect(gs, hasLength(2));

      final byId = {for (final p in (await photos())) p.id: p.groupId};
      expect(byId[idsA[0]], byId[idsA[1]]); // A 的两张同组
      expect(byId[idsB.single], isNot(byId[idsA[0]])); // B 独立
    });
  });

  // ═════════════════════════════════════════════════════════
  // regroupPending —— 相册批次（2026-09-29：一批一组）
  //
  // 「选择导入的一批」就是一组 —— 与照片时间戳是否被转发压平无关，
  // 旧版的时间戳可信度检查随按时序分组一起退场。
  // ═════════════════════════════════════════════════════════

  group('regroupPending · 相册批次（一批一组）', () {
    test('时间戳被转发压平（全同）→ 仍然整批一组', () async {
      final ts = t(0);
      await albumSession([ts, ts, ts]);

      final created = await organize.regroupPending(projectId);
      expect(created, 1);
      final gs = await groups();
      expect(gs, hasLength(1));
      expect(gs.single.photoCount, 3);
      expect(gs.single.origin, GroupOrigin.album.code);
    });

    test('时间戳正常 → 同样整批一组（一批的语义与时间无关）', () async {
      await albumSession([t(0), t(10), t(20)]);

      final created = await organize.regroupPending(projectId);
      expect(created, 1);
      final gs = await groups();
      expect(gs.single.photoCount, 3);
      expect(gs.single.origin, GroupOrigin.album.code);
    });
  });

  // ═════════════════════════════════════════════════════════
  // regroupPending —— 幂等与增量（双路径共用数据的前提）
  // ═════════════════════════════════════════════════════════

  group('regroupPending · 幂等与增量', () {
    test('重复调用不重复建组（第二次返回 0）', () async {
      await cameraSession(3);
      expect(await organize.regroupPending(projectId), 1);

      final again = await organize.regroupPending(projectId);
      expect(again, 0);
      expect(await groups(), hasLength(1));
    });

    test('同批续拍：新照片与已有组整批重聚成一组（10-09 口径）', () async {
      await cameraSession(3, gapSec: 10); // t(0,10,20)
      expect(await organize.regroupPending(projectId), 1);

      // 现场继续拍：startSession 在 5 分钟续接窗口内 → 续用同一批次。
      // ⚠️ 旧口径（只回收单张组、不动已成的组）在这里断言「两组」——
      // 那正是 10-09 真机反馈「连拍拆成两组」的同一个行为：
      // 同批次未指派组按「一批一组」拍板本就该是一组，有新照片落下
      // 就整批重聚。此测试从守护旧口径改为守护新口径。
      final s = await capture.startSession(projectId);
      await capture.insertPhotos(projectId, [ph(s, 4, t(35))]);
      await capture.endSession(s);

      final second = await organize.regroupPending(projectId);
      expect(second, 1);

      final gs = await groups();
      expect(gs, hasLength(1), reason: '同批次 = 一组（一批一组拍板）');
      expect(gs.single.photoCount, 4);
    });

    test('逐张连拍：每拍一张触发一轮 regroup，最终一组 4 张（10-09 真机反馈）',
        () async {
      // 真机节奏：相机每落一张照片就触发一轮 regroup。
      // 旧口径下：{1} → 回收成 {1,2} → {3} 追不上已成组 → {3,4}
      // → 「两两一组」。新口径下每轮都整批重聚 → 始终一组。
      final s = await capture.startSession(projectId);
      for (var i = 1; i <= 4; i++) {
        await capture.insertPhotos(projectId, [ph(s, i, t(i * 2))]);
        await organize.regroupPending(projectId);
      }
      await capture.endSession(s);

      final gs = await groups();
      expect(gs, hasLength(1),
          reason: '同批次连拍 4 张必须是一组 —— 旧口径会拆成两组');
      expect(gs.single.photoCount, 4);
      expect((await photos()).map((p) => p.groupId), everyElement(gs.single.id));
    });

    test('老板指定过箱号的组不被重聚（carton 是人工痕迹）', () async {
      final (_, ids) = await cameraSession(2);
      await organize.regroupPending(projectId);
      final g = (await groups()).single;
      await (db.update(db.photoGroups)..where((x) => x.id.equals(g.id)))
          .write(const PhotoGroupsCompanion(carton: Value('BOX-01')));

      // 同批次续拍 1 张（窗口内续接同一批次）→ 触发重聚
      final s2 = await capture.startSession(projectId);
      await capture.insertPhotos(projectId, [ph(s2, 3, t(30))]);
      await capture.endSession(s2);
      await organize.regroupPending(projectId);

      final gs = await groups();
      expect(gs, hasLength(2), reason: '箱号组保留，新照片自成一组');
      final kept = gs.firstWhere((x) => x.id == g.id);
      expect(kept.carton, 'BOX-01');
      expect(kept.photoCount, 2, reason: '箱号组的照片不能被拉走');
      final byId = {for (final p in (await photos())) p.id: p.groupId};
      expect(byId[ids[0]], g.id);
      expect(byId[ids[1]], g.id);
    });

    test('已归属的组不被重聚（itemId 是 AssignService 的地盘）', () async {
      await cameraSession(2);
      await organize.regroupPending(projectId);
      await simulateConfirm((await groups()).single.id);

      // 同批次续拍 1 张 → 触发重聚
      final s2 = await capture.startSession(projectId);
      await capture.insertPhotos(projectId, [ph(s2, 3, t(30))]);
      await capture.endSession(s2);
      await organize.regroupPending(projectId);

      final gs = await groups();
      expect(gs, hasLength(2), reason: '归属组保留，新照片自成一组');
      final kept = gs.firstWhere((x) => x.itemId != null);
      expect(kept.photoCount, 2);
    });

    test('没有待分组照片时返回 0，不建空组', () async {
      expect(await organize.regroupPending(projectId), 0);
      expect(await groups(), isEmpty);
    });
  });

  // ═════════════════════════════════════════════════════════
  // P4 诉求 3：整理页必须"立刻看到照片"
  //
  // 根因是"查不到"而不是"刷新慢"：新照片 group_id 为 NULL，
  // 不在 photo_groups 表里，而待办流查的是那张表。
  // 修复 = 用 watchPendingPhotoCount 当信号 + regroupPending 加锁。
  // 这两组测试锁住修复的两个要点。
  // ═════════════════════════════════════════════════════════

  group('watchPendingPhotoCount · 未入组信号（P4 诉求 3）', () {
    test('刚拍完还没分组时 = 照片数（这就是"该补组了"的信号）', () async {
      await cameraSession(5, gapSec: 10);
      expect(await organize.watchPendingPhotoCount(projectId).first, 5);
    });

    test('分组之后归零（信号消失，不会再触发无谓的补组）', () async {
      await cameraSession(5, gapSec: 10);
      await organize.regroupPending(projectId);
      expect(await organize.watchPendingPhotoCount(projectId).first, 0);
    });

    test('采集中途新增照片 → 信号从 0 变正数（这正是原来的失效场景）', () async {
      await cameraSession(3, gapSec: 10);
      await organize.regroupPending(projectId);
      expect(await organize.watchPendingPhotoCount(projectId).first, 0);

      // 用户又去拍了两张 —— 修复前这两张永远不会被人看到
      final s = await capture.startSession(projectId);
      await capture.insertPhotos(projectId, [
        ph(s, 4, t(60)),
        ph(s, 5, t(70)),
      ]);
      await capture.endSession(s);

      expect(await organize.watchPendingPhotoCount(projectId).first, 2);

      // 补一轮之后它们就进了组，待办流才看得到
      //（10-09 口径：同批次整批重聚 → 3+2 张合成一组）
      expect(await organize.regroupPending(projectId), 1);
      expect(await organize.watchPendingPhotoCount(projectId).first, 0);
      expect(await groups(), hasLength(1));
      expect((await groups()).single.photoCount, 5);
    });
  });

  group('regroupPending · 并发重入安全（P4 诉求 3 的锁）', () {
    test('并发调用不会产生孤儿空组（每组都真的有照片）', () async {
      await cameraSession(6, gapSec: 10);

      // 三条路径同时触发补组：切 Tab、下拉刷新、采集后自动跟上
      final results = await Future.wait([
        organize.regroupPending(projectId),
        organize.regroupPending(projectId),
        organize.regroupPending(projectId),
      ]);

      // 不管哪一家的返回值是多少，最终状态必须自洽：
      // 1) 照片全部入组 2) 不存在 photoCount == 0 的空壳组
      expect(await organize.watchPendingPhotoCount(projectId).first, 0);
      final gs = await groups();
      expect(gs, isNotEmpty);
      for (final g in gs) {
        final n = await countInGroup(db, g.id);
        expect(
          n,
          greaterThan(0),
          reason: '组 ${g.id} 是空壳 —— 并发重入把同一批照片分到了两个组里',
        );
        expect(g.photoCount, n, reason: '组的 photoCount 字段与实际张数不一致');
      }
      // 返回值的语义：只有真正建了组的那次 > 0
      expect(results.where((r) => r > 0), hasLength(1));
    });

    test('串行化：同一批照片只被建一次组（返回值最能说明问题）', () async {
      await cameraSession(4, gapSec: 10);

      // 连续发起三次（不 await）—— 模拟切 Tab / 下拉 / 自动跟上同时到达。
      // 若实现是并行的，三次都会读到"4 张未入组"各自建组 → 三个返回值都 > 0。
      // 串行化下只有第一次真正建了组，后两次看到 0 张未入组照片。
      final results = await Future.wait([
        organize.regroupPending(projectId),
        organize.regroupPending(projectId),
        organize.regroupPending(projectId),
      ]);

      expect(
        results.where((r) => r > 0),
        hasLength(1),
        reason: '有多次调用都认为自己建了组 —— 说明没串行化，会留下空壳组',
      );
      expect(await organize.watchPendingPhotoCount(projectId).first, 0);
    });
  });

  // ═════════════════════════════════════════════════════════
  // 归属隔离 —— 分组层碰不到 itemId / state
  // ═════════════════════════════════════════════════════════

  group('归属隔离', () {
    test('regroup 之后：所有照片仍 unassigned、itemId 为空', () async {
      await cameraSession(4, gapSec: 10);
      await albumSession([t(100), t(200)]);

      await organize.regroupPending(projectId);

      final ps = await photos();
      expect(ps, isNotEmpty);
      expect(ps.map((p) => p.itemId), everyElement(isNull));
      expect(
        ps.map((p) => p.state),
        everyElement(PhotoState.unassigned.code),
      );
    });

    test('regroup 之后：组表建议字段保持出厂默认（M4 才写）', () async {
      await cameraSession(3);
      await organize.regroupPending(projectId);

      final gs = await groups();
      expect(gs, hasLength(1));
      expect(gs.single.suggestedItemId, isNull);
      expect(gs.single.suggestionConf, isNull);
      expect(gs.single.suggestState, 'pending');
    });
  });

  // ═════════════════════════════════════════════════════════
  // mergeGroups —— 手动合并
  // ═════════════════════════════════════════════════════════

  group('mergeGroups', () {
    test('合并：照片并入目标、目标计数更新、被并组删除', () async {
      await cameraSessionExpired(2, gapSec: 2); // t(0), t(2)
      await cameraSession(1); // 另一批次 t(0)
      await organize.regroupPending(projectId);

      final gs = await groups(); // 2 组
      expect(gs, hasLength(2));
      final target = gs.firstWhere((g) => g.photoCount == 2);
      final other = gs.firstWhere((g) => g.photoCount == 1);

      await organize.mergeGroups(
        projectId,
        targetGroupId: target.id,
        otherGroupIds: [other.id],
      );

      final after = await groups();
      expect(after, hasLength(1));
      expect(after.single.id, target.id);
      expect(after.single.photoCount, 3);
      final ps = await photos();
      expect(ps.map((p) => p.groupId), everyElement(target.id));
    });

    test('已确认的目标组拒绝被并入（会绕过决策记录）', () async {
      await cameraSessionExpired(1);
      await cameraSession(1);
      await organize.regroupPending(projectId);
      final gs = await groups();
      await simulateConfirm(gs.first.id);

      expect(
        () => organize.mergeGroups(
          projectId,
          targetGroupId: gs.first.id,
          otherGroupIds: [gs.last.id],
        ),
        throwsStateError,
      );
    });

    test('已确认的源组拒绝被并走', () async {
      await cameraSessionExpired(1);
      await cameraSession(1);
      await organize.regroupPending(projectId);
      final gs = await groups();
      await simulateConfirm(gs.last.id);

      expect(
        () => organize.mergeGroups(
          projectId,
          targetGroupId: gs.first.id,
          otherGroupIds: [gs.last.id],
        ),
        throwsStateError,
      );
    });

    test('空列表是 no-op，不报错也不删组', () async {
      await cameraSession(2);
      await organize.regroupPending(projectId);

      // otherGroupIds 为空在实现里最先短路，target 不会被触碰
      await organize.mergeGroups(
        projectId,
        targetGroupId: 'no-such-group',
        otherGroupIds: const [],
      );
      expect(await groups(), hasLength(1));
    });
  });

  // ═════════════════════════════════════════════════════════
  // movePhotoOut —— 手动移出
  // ═════════════════════════════════════════════════════════

  group('movePhotoOut', () {
    test('移出：照片搬进新的 manual 组，旧组计数减一', () async {
      await cameraSession(3, gapSec: 5);
      await organize.regroupPending(projectId);

      final group0 = (await groups()).single;
      final members = (await photos())
          .where((p) => p.groupId == group0.id)
          .map((p) => p.id)
          .toList();

      await organize.movePhotoOut(projectId, members.first);

      final gs = await groups();
      expect(gs, hasLength(2));
      final old = gs.firstWhere((g) => g.id == group0.id);
      expect(old.photoCount, 2);
      final fresh = gs.firstWhere((g) => g.id != group0.id);
      expect(fresh.origin, GroupOrigin.manual.code);

      final moved = await (db.select(db.photos)
            ..where((p) => p.id.equals(members.first)))
          .getSingle();
      expect(moved.groupId, fresh.id);
      // 移出不会顺手写归属 —— 仍是 unassigned
      expect(moved.itemId, isNull);
      expect(moved.state, PhotoState.unassigned.code);
    });

    test('单张组移出后旧组删除（不留壳）', () async {
      // 三个独立批次各 1 张 → 3 个单张组
      //（旧夹具靠「时间戳压平产生单张组」已随按时序分组退场）
      await cameraSessionExpired(1);
      await cameraSessionExpired(1);
      await cameraSessionExpired(1);
      await organize.regroupPending(projectId);

      final gs = await groups();
      expect(gs, hasLength(3));
      final single = gs.first;
      final pid = (await photos())
          .firstWhere((p) => p.groupId == single.id)
          .id;

      await organize.movePhotoOut(projectId, pid);

      final after = await groups();
      expect(after, hasLength(3)); // 旧单张组删了，新 manual 组顶上
      expect(after.map((g) => g.id), isNot(contains(single.id)));
    });

    test('已确认照片拒绝移出（itemId 已写）', () async {
      await cameraSession(2);
      await organize.regroupPending(projectId);
      final g = (await groups()).single;
      final pid = (await photos()).first.id;
      await simulateConfirm(g.id);

      expect(
        () => organize.movePhotoOut(projectId, pid),
        throwsStateError,
      );
    });

    test('state=confirmed 但 itemId 仍空的矛盾态也拒绝移出', () async {
      await cameraSession(2);
      await organize.regroupPending(projectId);
      final pid = (await photos()).first.id;
      await (db.update(db.photos)..where((p) => p.id.equals(pid)))
          .write(PhotosCompanion(state: Value(PhotoState.confirmed.code)));

      expect(
        () => organize.movePhotoOut(projectId, pid),
        throwsStateError,
      );
    });

    test('未入组的照片 movePhotoOut 是 no-op', () async {
      await cameraSession(1);
      // 故意不 regroup —— 照片没有组
      final pid = (await photos()).single.id;

      await organize.movePhotoOut(projectId, pid);
      expect((await photos()).single.groupId, isNull);
      expect(await groups(), isEmpty);
    });
  });

  // ═════════════════════════════════════════════════════════
  // watchOpenGroups —— 整理页待办流
  // ═════════════════════════════════════════════════════════

  group('watchOpenGroups', () {
    test('按首张拍摄时间升序返回，组内照片升序', () async {
      // 批次 A 后拍（时间晚），先插 —— 流里应排在批次 B 之后
      await albumSession([t(300)]); // 单张组 @300s
      await cameraSession(2, gapSec: 10); // 组 @0s
      await organize.regroupPending(projectId);

      final flow = await organize.watchOpenGroups(projectId).first;
      expect(flow, hasLength(2));
      expect(flow.first.takenAtMs, t(0).millisecondsSinceEpoch);
      expect(flow.last.takenAtMs, t(300).millisecondsSinceEpoch);

      final pair = flow.first.photos;
      expect(pair, hasLength(2));
      expect(pair[0].takenAtMs, lessThanOrEqualTo(pair[1].takenAtMs));
      // 投影只带缩略图路径 —— 拿不到归属
      expect(pair.first.thumbPath, isNull);
    });

    test('确认归属的组从待办流中消失（只看剩下的）', () async {
      await cameraSessionExpired(2, gapSec: 5);
      await cameraSession(1);
      await organize.regroupPending(projectId);

      var flow = await organize.watchOpenGroups(projectId).first;
      expect(flow, hasLength(2));

      final done = flow.last; // 确认其中一组
      await simulateConfirm(done.groupId);

      flow = await organize.watchOpenGroups(projectId).first;
      expect(flow, hasLength(1));
      expect(flow.single.groupId, isNot(done.groupId));
    });
  });

  // ═════════════════════════════════════════════════════════
  // watchAssignedGroups —— 已指派视图（P4 · 真机反馈 2026-09-24：
  // 「在整理时，无法看到已经指派的照片，导致无法修改」）
  // ═════════════════════════════════════════════════════════

  group('watchAssignedGroups · 已指派视图', () {
    late ItemRepository items;
    late AssignService assign;
    late String itemA;
    late String itemB;

    setUp(() async {
      items = ItemRepository(db);
      assign = AssignService(db, deviceName: 'test-device');
      await items.bulkInsert(projectId, [
        const ChecklistRow(
            sourceRow: 2, code: 'BOX-001', codeSafe: 'BOX-001', name: '货品A'),
        const ChecklistRow(
            sourceRow: 3, code: 'BOX-002', codeSafe: 'BOX-002', name: '货品B'),
      ]);
      final all = await items.watchByProject(projectId).first;
      itemA = all[0].id;
      itemB = all[1].id;
    });

    /// 建两组（各 2 张）。
    Future<(String, String)> twoGroups() async {
      await cameraSessionExpired(2, gapSec: 5);
      await cameraSession(2, gapSec: 5);
      await organize.regroupPending(projectId);
      final gs = await groups();
      return (gs[0].id, gs[1].id);
    }

    test('确认归属的组出现在已指派流，带清单编码/品名/张数', () async {
      final (gidA, _) = await twoGroups();

      var flow = await organize.watchAssignedGroups(projectId).first;
      expect(flow, isEmpty); // 还没指派 → 空

      await assign.confirmGroup(gidA, itemId: itemA, source: AssignSource.manual);

      flow = await organize.watchAssignedGroups(projectId).first;
      expect(flow, hasLength(1));
      expect(flow.single.groupId, gidA);
      expect(flow.single.itemId, itemA);
      expect(flow.single.itemCode, 'BOX-001');
      expect(flow.single.itemName, '货品A');
      expect(flow.single.photoCount, 2);
      expect(flow.single.confirmedAtMs, greaterThan(0));
    });

    test('撤销后从已指派流消失，回到待办流（可重新指派）', () async {
      final (gidA, _) = await twoGroups();
      await assign.confirmGroup(gidA, itemId: itemA, source: AssignSource.manual);

      var assigned = await organize.watchAssignedGroups(projectId).first;
      expect(assigned, hasLength(1));

      await assign.revokeGroup(gidA);

      assigned = await organize.watchAssignedGroups(projectId).first;
      expect(assigned, isEmpty); // 撤销 → 不在已指派流

      final open = await organize.watchOpenGroups(projectId).first;
      expect(open, hasLength(2)); // 回到待办流（连同另一组）
      expect(open.map((g) => g.groupId), contains(gidA));
    });

    test('刚指派的排最前（按确认时间倒序）', () async {
      final (gidA, gidB) = await twoGroups();
      await assign.confirmGroup(gidA, itemId: itemA, source: AssignSource.manual);
      // 把 A 的确认时刻人为拨回 10 秒前，绕开"同毫秒确认"的不确定性
      // —— B 比 A 晚确认，流里 B 必须在前。
      final earlier = DateTime.now().millisecondsSinceEpoch - 10000;
      await (db.update(db.photoGroups)..where((g) => g.id.equals(gidA)))
          .write(PhotoGroupsCompanion(confirmedAt: Value(earlier)));
      await assign.confirmGroup(gidB, itemId: itemB, source: AssignSource.manual);

      final flow = await organize.watchAssignedGroups(projectId).first;
      expect(flow, hasLength(2));
      expect(flow.first.groupId, gidB);
      expect(flow.last.groupId, gidA);
    });
  });

  // ═════════════════════════════════════════════════════════
  // 自动路径的回收口径（2026-09-27 分组 BUG 修复沿用至今）
  //
  // 老板复现场景：相机拍摄、相隔 20 秒的两张没归到一组。
  // 根因：自动补组是实时触发的（每拍一张跑一轮），若「已入组的
  // 照片一律跳过」—— 第 1 张立刻立成单张组，20 秒后第 2 张来了，
  // 第 1 张已被跳过，永远聚不到一起。修复后自动路径**回收未指派的
  // 单张组**：新照片触发的那一轮把先前的单张组拉回来重新按批次成组。
  // （按时序开关语义已随 2026-09-29「一批一组」拍板移除，回收口径保留。）
  // ═════════════════════════════════════════════════════════

  group('regroupPending · 回收口径', () {
    test('边拍边触发也能聚上：先到的单张组被新照片拉回同一组', () async {
      // 第一轮：第 1 张照片先到、先被自动补组立成单张组
      await cameraSession(1); // t(0)
      expect(await organize.regroupPending(projectId), 1);
      expect((await groups()).single.photoCount, 1);

      // 20 秒后：第 2 张照片到（窗口内退出再进 → 续接同一批次）。
      // 夹具的时间戳是固定的 t(0)，手动把这张改成 +20s 才能模拟间隔。
      final (_, ids2) = await cameraSession(1);
      await (db.update(db.photos)..where((p) => p.id.equals(ids2.single)))
          .write(PhotosCompanion(takenAt: Value(t(20).millisecondsSinceEpoch)));

      // 自动补组（整理页数据驱动触发的那一轮）
      await organize.regroupPending(projectId);

      // 间隔 20s ≤ 45s → 两张必须在同一组（旧 BUG 下是两个单张组）
      final gs = await groups();
      expect(gs, hasLength(1));
      expect(gs.single.photoCount, 2);
    });

    test('已确认的组不被自动路径回收（itemId 是 AssignService 的地盘）', () async {
      await cameraSession(1);
      await organize.regroupPending(projectId);
      final first = (await groups()).single;
      await simulateConfirm(first.id);

      // 新照片来了 —— 自动补组只回收未指派的单张组
      await cameraSession(1);
      await organize.regroupPending(projectId);

      final gs = await groups();
      expect(gs, hasLength(2));
      final confirmed = gs.firstWhere((g) => g.id == first.id);
      expect(confirmed.itemId, 'item-x'); // 归属原样
      expect(confirmed.photoCount, 1); // 没被拆
    });

    test('自动聚出的多张组在同批新照片落下时整批重聚（10-09 口径）', () async {
      // ⚠️ 此测试原断言「多张组不动、新照片自己立组」—— 那正是
      // 10-09 真机反馈「连拍 4 张拆成两组」的行为（本场景就是它的
      // 前两轮）。这里的多张组是 regroup 自动聚的，不是人工成果；
      // 真正的人工痕迹（carton / itemId / 补拍保护）各有专门测试
      // 守护（见「同批续拍」组的三条）。
      await cameraSession(2, gapSec: 10); // 自动聚成一组 2 张
      await organize.regroupPending(projectId);
      final merged = (await groups()).single;
      expect(merged.photoCount, 2);

      await cameraSession(1); // 窗口内续接同批次，新照片触发新一轮
      await organize.regroupPending(projectId);

      final gs = await groups();
      expect(gs, hasLength(1), reason: '同批次 = 一组（一批一组拍板）');
      expect(gs.single.photoCount, 3);
    });
  });

  // （「regroupByTime 手动按时序归组」「分组规则可设置」两组测试已随
  //   该功能移除 —— 2026-09-29 老板拍板：一批一组，规则不再可配，
  //   手动调整组结构走合并/移出。）

  // ═════════════════════════════════════════════════════════
  // 部类卫生（2026-09-27）：监装照片不参与分组
  //
  // 监装照片不与清单对应、不需要入组 —— 它们的家是监装照片墙
  // （watchSupervisionPhotos 直查 photos 表）。分组入口若不按部类
  // 过滤，游离监装照片会被聚进默认 precheck 组、监装单张组会被
  // 重组误回收 —— 照片从墙上消失，还混进预检待办流。
  // ═════════════════════════════════════════════════════════

  group('监装照片不参与分组（部类卫生）', () {
    test('游离监装照片不会被聚进任何组（留在照片墙，不进待办流）', () async {
      await cameraSession(3, gapSec: 10);
      final all = await photos();
      // 把其中一张标成监装（游离照片的兜底入口，M6）
      await organize.setPhotosCategory(
        [all.first.id],
        PhotoCategory.supervision,
      );

      await organize.regroupPending(projectId);

      final marked = await (db.select(db.photos)
            ..where((p) => p.id.equals(all.first.id)))
          .getSingle();
      expect(marked.groupId, isNull, reason: '监装照片不该被聚进任何组');
      // 其余两张预检照片正常聚组（同批次 → 一组）
      final gs = await groups();
      expect(gs, hasLength(1));
      expect(gs.single.photoCount, 2);
      // 组的部类必须是预检
      expect(gs.single.category, PhotoCategory.precheck.code);
    });

    test('监装单张组不会被按批次重组回收', () async {
      await cameraSession(1); // 1 个单张组
      await organize.regroupPending(projectId);
      final g = (await groups()).single;
      // 整组切到监装（M6 主路径：组 + 组内照片一起翻）
      await organize.setGroupCategory(g.id, PhotoCategory.supervision);

      final created = await organize.regroupPending(projectId);
      expect(created, 0, reason: '监装单张组不在回收范围');

      final after = await groups();
      expect(after, hasLength(1));
      expect(after.single.id, g.id);
      expect(after.single.category, PhotoCategory.supervision.code);
      expect(await countInGroup(db, g.id), 1);
    });

    test('监装多张组同样不被按批次重组回收（原有保护 + 部类过滤双保险）', () async {
      await cameraSession(2, gapSec: 5);
      await organize.regroupPending(projectId);
      final g = (await groups()).single;
      await organize.setGroupCategory(g.id, PhotoCategory.supervision);

      expect(await organize.regroupPending(projectId), 0);
      expect(await groups(), hasLength(1));
    });

    test('全部改回预检：照片摘组重新参与分组，不在两墙间消失（2026-10-14 真机 bug）', () async {
      // 现场时序：拍 3 张 → 聚成预检组 → 整组标监装（组+照片行一起翻）
      // → 监装墙看到 3 张 → 点「全部改回预检」。
      await cameraSession(3, gapSec: 10);
      await organize.regroupPending(projectId);
      final g = (await groups()).single;
      await organize.setGroupCategory(g.id, PhotoCategory.supervision);

      // 改回预检（bug 修复前：只改照片行，照片还挂在监装组 ——
      // 预检墙按组查看不到、监装墙按行查也不显示、待入组信号不数它）
      final all = await photos();
      await organize.setPhotosCategory(
        all.map((p) => p.id).toList(),
        PhotoCategory.precheck,
      );

      // ① 照片行：category 回预检、group_id 摘空
      final rows = await photos();
      for (final p in rows) {
        expect(p.category, PhotoCategory.precheck.code);
        expect(p.groupId, isNull, reason: '必须摘出监装组，否则 regroup 捡不回');
      }
      // ② 监装墙：空了（watchSupervisionPhotos 按行查）
      expect(
        await organize.watchSupervisionPhotos(projectId).first,
        isEmpty,
      );
      // ③ 摘空的监装组被清理，不再留脏组
      expect(
        await (db.select(db.photoGroups)
              ..where((x) => x.id.equals(g.id)))
            .get(),
        isEmpty,
      );
      // ④ 重新参与分组：回到预检待办流，聚回一组
      await organize.regroupPending(projectId);
      final gs = await groups();
      expect(gs, hasLength(1));
      expect(gs.single.category, PhotoCategory.precheck.code);
      expect(gs.single.photoCount, 3);
      expect(await countInGroup(db, gs.single.id), 3);
    });

    test('存量坏数据自愈（v5 迁移）：行是预检、组是监装的两栖照片被摘组归位', () async {
      // 现场时序：v0.22.2 之前在旧版上执行「全部改回预检」——
      // 只改照片行不摘组。这里手工构造那个坏状态（等价于用户升级前
      // 的库），然后跑 v5 修复，断言照片回到预检墙。
      await cameraSession(2, gapSec: 5);
      await organize.regroupPending(projectId);
      final g = (await groups()).single;
      await organize.setGroupCategory(g.id, PhotoCategory.supervision);
      // 模拟旧 bug：只改行、不摘组（当时的 setPhotosCategory 行为）
      await (db.update(db.photos)..where((p) => p.category
              .equals(PhotoCategory.supervision.code)))
          .write(const PhotosCompanion(category: Value('precheck')));

      // 修复前的坏状态：照片行是预检，但还挂在监装组里 ——
      // 待入组信号为 0（这正是 regroup 捡不回它们的原因）
      expect(await organize.watchPendingPhotoCount(projectId).first, 0);

      // v5 迁移同款修复
      await rescueMisfiledPrecheckPhotos(db);

      // 🔬 同 tick 内「customStatement 写 → watch 流新订阅」的首值可能还是
      // 旧快照（drift 查询排队时序），给事件循环一拍再断言。真机路径
      // （启动迁移 → 用户进照片页才订阅）不存在这个窗口。
      await Future<void>.delayed(const Duration(milliseconds: 100));

      // 摘组后待入组信号 > 0，regroup 重新聚成预检组
      expect(await organize.watchPendingPhotoCount(projectId).first, 2);
      await organize.regroupPending(projectId);
      final gs = await groups();
      expect(gs, hasLength(1));
      expect(gs.single.category, PhotoCategory.precheck.code);
      expect(gs.single.photoCount, 2);
      // 监装墙空了（两栖照片不再两边都看不见）
      expect(await organize.watchSupervisionPhotos(projectId).first, isEmpty);
    });
  });

  // ═════════════════════════════════════════════════════════
  // 缩略图刷新（2026-10-14 真机「最新照片缩略图显示不出来」）
  //
  // 缩略图是**入库之后**异步落库的（不阻塞快门），而组查询只监听
  // photo_groups —— 照片行的 thumbPath 变化不推新值，列表就永远停在
  // 占位图。触发流（缺缩略图张数，distinct）就是为这个补的。
  // ═════════════════════════════════════════════════════════

  group('缩略图落库后列表自己刷新', () {
    test('watchOpenGroups：thumbPath 从 NULL 落库后推出新值（不用重新进页）', () async {
      await cameraSession(2, gapSec: 5);
      await organize.regroupPending(projectId);
      final ids = (await photos()).map((p) => p.id).toList();

      // 模拟「刚入库、缩略图还没生成」
      await (db.update(db.photos)..where((p) => p.id.isIn(ids)))
          .write(const PhotosCompanion(thumbPath: Value(null)));

      final seen = <List<OpenGroup>>[];
      final sub = organize.watchOpenGroups(projectId).listen(seen.add);
      addTearDown(sub.cancel);
      await waitUntil(() => seen.isNotEmpty);
      expect(seen.last.single.photos.every((p) => p.thumbPath == null), isTrue,
          reason: '前置：首值确实还没有缩略图');

      // 派生异步落库（真实路径：PhotoFileSink 写完 → patchMediaInfo）
      await (db.update(db.photos)..where((p) => p.id.isIn(ids)))
          .write(const PhotosCompanion(thumbPath: Value('/data/thumbs/x.jpg')));

      final refreshed = await waitUntil(() =>
          seen.isNotEmpty &&
          seen.last.single.photos.every((p) => p.thumbPath == '/data/thumbs/x.jpg'));
      expect(refreshed, isTrue,
          reason: '缩略图落库后组流必须自己推新值 —— 否则用户看到的是永久占位图');
    });

    test('watchAssignedGroups：同样跟随缩略图落库刷新', () async {
      await cameraSession(2, gapSec: 5);
      await organize.regroupPending(projectId);
      final g = (await groups()).single;
      final ids = (await photos()).map((p) => p.id).toList();
      // 模拟已确认归属（写 itemId —— 测试里直接写库模拟终态）
      await (db.update(db.photoGroups)..where((t) => t.id.equals(g.id)))
          .write(const PhotoGroupsCompanion(itemId: Value('item-x')));
      await (db.update(db.photos)..where((p) => p.id.isIn(ids)))
          .write(const PhotosCompanion(thumbPath: Value(null)));

      final seen = <List<AssignedGroup>>[];
      final sub = organize.watchAssignedGroups(projectId).listen(seen.add);
      addTearDown(sub.cancel);
      await waitUntil(() => seen.isNotEmpty);

      await (db.update(db.photos)..where((p) => p.id.isIn(ids)))
          .write(const PhotosCompanion(thumbPath: Value('/data/thumbs/y.jpg')));
      final refreshed = await waitUntil(() =>
          seen.isNotEmpty &&
          seen.last.single.photos.every((p) => p.thumbPath == '/data/thumbs/y.jpg'));
      expect(refreshed, isTrue);
    });
  });
}
