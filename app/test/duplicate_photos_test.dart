import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/app/providers.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/capture/camera_capture_service.dart';
import 'package:g_tick_picture/domain/model/duplicate_photos.dart';
import 'package:g_tick_picture/ui/organize/duplicate_sheet.dart';

/// 照片查重（2026-10-04 老板「同一组间照片和不同分组间的照片不能重复」）。
///
/// 这套功能的**全部价值**在于两件事，所以测试也只钉这两件：
///  ① **不漏报**：同一张图重复出现（不论同组还是跨组）必须被查出来 ——
///     重复照片混进交付包是甲方的质量问题，漏报等于功能没做；
///  ② **不骗人**：没查完的时候不许显示"无重复"。老照片的指纹是
///     NULL（v4 迁移只加列不回填），若把 NULL 当成"同一个值"，
///     上千张老照片会被误报成彼此重复；反过来，若没算完就说
///     "没有重复"，用户会以为已经查过了。
///
/// 指纹算法本身（原生 64KB SHA-256）不在这里测 —— 那是 Kotlin 侧，
/// Dart 单测跑不到；这里用**直接写 content_hash** 的方式测 SQL 与
/// 判定逻辑，算法对不对靠真机双击同一张图肉眼验证。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late AppDatabase db;
  late CaptureRepository repo;
  late String projectId;
  late String sessionId;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    repo = CaptureRepository(db);
    projectId = await ProjectRepository(db).create(name: '查重测试');
    sessionId = await repo.startSession(projectId);
  });

  tearDown(() async {
    await db.close();
  });

  /// 塞照片：hash 传 null = 模拟"还没算过指纹"（v4 迁移后的老照片）。
  Future<List<String>> seed(
    List<String?> hashes, {
    Map<int, String> groupOf = const {},
    String? otherProjectSession,
  }) async {
    var seq = 0;
    final ids = <String>[];
    for (final h in hashes) {
      seq++;
      final id = (await repo.insertPhotos(projectId, [
        NewPhoto(
          sessionId: sessionId,
          filePath: '/tmp/dup_$seq.jpg',
          seq: seq,
          takenAt: DateTime(2026, 10, 4, 9, 0, seq),
          bytes: 100,
        ),
      ]))
          .single;
      ids.add(id);
      if (h != null) await repo.patchContentHash(id, h);
      final g = groupOf[seq - 1];
      if (g != null) {
        await (db.update(db.photos)..where((p) => p.id.equals(id)))
            .write(PhotosCompanion(groupId: Value(g)));
      }
    }
    // 让第二个项目也有照片（验证查重不跨项目）
    if (otherProjectSession != null) {
      final other = await ProjectRepository(db).create(name: '别的项目');
      var oseq = 0;
      for (final h in hashes) {
        if (h == null) continue;
        oseq++;
        await repo.insertPhotos(other, [
          NewPhoto(
            sessionId: otherProjectSession,
            filePath: '/tmp/other_$oseq.jpg',
            seq: oseq,
            takenAt: DateTime(2026, 10, 4, 10, 0, oseq),
            bytes: 100,
          ),
        ]);
      }
    }
    return ids;
  }

  // ═══════════════════════════════════════════════════════════
  group('findDuplicates —— 判定口径', () {
    test('相同指纹的两张被查出，且只报一组', () async {
      await seed(['h1', 'h1', 'h2']);

      final sets = await repo.findDuplicates(projectId);

      expect(sets, hasLength(1), reason: 'h1 重复一次 = 一组；h2 唯一不该出现');
      expect(sets.first.hash, 'h1');
      expect(sets.first.photoIds, hasLength(2));
      expect(sets.first.duplicateCount, 2);
    });

    test('指纹全不同 → 空结果（不误报）', () async {
      await seed(['h1', 'h2', 'h3']);

      expect(await repo.findDuplicates(projectId), isEmpty,
          reason: '连拍两张角度不同的照片字节不同，绝不能算重复');
    });

    test('三张同指纹 → 一组，冗余 2 张', () async {
      await seed(['h1', 'h1', 'h1']);

      final sets = await repo.findDuplicates(projectId);
      expect(sets, hasLength(1));
      expect(sets.first.photoIds, hasLength(3));
      expect(sets.first.redundantCount, 2);
      expect(sets.first.redundantIds, hasLength(2));
    });

    test('两组各自重复 → 报两组，互不串味', () async {
      await seed(['h1', 'h1', 'h2', 'h2']);

      final sets = await repo.findDuplicates(projectId);
      expect(sets, hasLength(2));
      expect(sets.map((s) => s.hash).toSet(), {'h1', 'h2'});
      for (final s in sets) {
        expect(s.photoIds, hasLength(2));
      }
    });

    test('保留的是最早那张（seq 最小），其余标冗余', () async {
      final ids = await seed(['h1', 'h1', 'h1']);

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.earliestPhotoId, ids.first);
      expect(s.redundantIds, ids.sublist(1),
          reason: '第一张才是用户真正按下快门的那次，后面的都是重复选择');
    });

    test('不跨项目判重：A 项目的重复不会牵连 B 项目', () async {
      // 另一个项目里也放两张同指纹 —— 若 SQL 漏了 project_id 过滤，
      // 这里会变成 4 张一组
      final other = await ProjectRepository(db).create(name: '对照项目');
      final otherSession = await repo.startSession(other);
      await seed(['h1', 'h1'], otherProjectSession: otherSession);

      final sets = await repo.findDuplicates(projectId);
      expect(sets, hasLength(1));
      expect(sets.single.photoIds, hasLength(2),
          reason: '判重只在当前项目内进行');
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('NULL 指纹语义（"还没算过" ≠ "重复"）', () {
    test('多张 NULL 不算重复', () async {
      await seed([null, null, null]);

      expect(await repo.findDuplicates(projectId), isEmpty,
          reason: '把 NULL 当同一组会把上千张老照片误报成彼此重复');
    });

    test('NULL 与有指纹的混在一起，也只报真有重复的那些', () async {
      await seed([null, 'h1', 'h1', null]);

      final sets = await repo.findDuplicates(projectId);
      expect(sets, hasLength(1));
      expect(sets.single.photoIds, hasLength(2));
    });

    test('hashCoverage：已算 / 未算分开计数', () async {
      await seed(['h1', 'h1', null, null, null]);

      final cov = await repo.hashCoverage(projectId);
      expect(cov.hashed, 2);
      expect(cov.pending, 3);
    });

    test('hashCoverage：全算完时 pending = 0（横幅据此显示"无重复"）', () async {
      await seed(['h1', 'h2']);
      final cov = await repo.hashCoverage(projectId);
      expect(cov.pending, 0);
      expect(cov.hashed, 2);
    });

    test('空项目不炸（COUNT/SUM 皆 NULL 的老坑）', () async {
      final cov = await repo.hashCoverage(projectId);
      expect(cov.hashed, 0);
      expect(cov.pending, 0);
      expect(await repo.findDuplicates(projectId), isEmpty);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('跨组 vs 同组', () {
    test('两张分属不同组 → crossesGroups = true', () async {
      await seed(['h1', 'h1'], groupOf: {0: 'g-a', 1: 'g-b'});

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.crossesGroups, isTrue,
          reason: '同一张图出现在两个组，意味着分组本身出了问题，必须显眼提示');
      expect(s.groupIds, ['g-a', 'g-b']);
    });

    test('两张同属一组 → crossesGroups = false', () async {
      await seed(['h1', 'h1'], groupOf: {0: 'g-a', 1: 'g-a'});

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.crossesGroups, isFalse);
    });

    test('还没进组的游离照片不算"跨组"', () async {
      // 一张在组里、一张游离 —— 只有 1 个真实组，不该报"跨组"
      await seed(['h1', 'h1'], groupOf: {0: 'g-a'});

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.crossesGroups, isFalse);
      expect(s.groupIds, ['g-a', '']);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('photosMissingHash —— 补算的取数顺序', () {
    test('只取指纹为空的，按 seq 升序，遵守 limit', () async {
      final ids = await seed(['h1', null, 'h3', null]);

      final missing = await repo.photosMissingHash(projectId, limit: 1);
      expect(missing.map((p) => p.id).toList(), [ids[1]],
          reason: 'limit=1 时只能拿到最靠前的那张没算的');

      final all = await repo.photosMissingHash(projectId);
      expect(all.map((p) => p.id).toList(), [ids[1], ids[3]],
          reason: '已算指纹的永远不该被捞回来重算');
    });

    test('全部算完时返回空', () async {
      await seed(['h1', 'h2']);
      expect(await repo.photosMissingHash(projectId), isEmpty);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('DuplicateReport 派生量', () {
    DuplicateSetWithGroups setOf(List<String> ids, List<String> groups) =>
        DuplicateSetWithGroups(
          hash: ids.join(),
          photoIds: ids,
          earliestPhotoId: ids.first,
          groupIds: groups,
          thumbPaths: List<String?>.filled(ids.length, null),
          photos: [
            for (var i = 0; i < ids.length; i++)
              DuplicatePhoto(
                id: ids[i],
                groupId: i < groups.length ? groups[i] : '',
                // 测试里组 id 形如 'g1'，次序就按尾号推 —— 真实次序由
                // SQL JOIN photo_groups 取，这里只测派生逻辑。
                groupSeq: i < groups.length && groups[i].isNotEmpty
                    ? int.tryParse(groups[i].substring(1))
                    : null,
                seq: i + 1,
                thumbPath: null,
              ),
          ],
        );

    test('空报告：无重复、不在核查', () {
      const r = DuplicateReport.empty();
      expect(r.hasDuplicate, isFalse);
      expect(r.isScanning, isFalse);
      expect(r.redundantTotal, 0);
      expect(r.affectedGroupCount, 0);
    });

    test('有重复：冗余总数与涉及组数正确', () {
      final r = DuplicateReport(
        sets: [
          setOf(['a1', 'a2', 'a3'], ['g1', 'g2', '']), // 冗余 2，跨 2 组
          setOf(['b1', 'b2'], ['g2', 'g2']), // 冗余 1，1 组
        ],
        hashedCount: 5,
        pendingCount: 0,
      );
      expect(r.hasDuplicate, isTrue);
      expect(r.redundantTotal, 3);
      // g1 + g2（空串不计）
      expect(r.affectedGroupCount, 2);
    });

    test('pendingCount > 0 → isScanning（此时不许显示"无重复"）', () {
      const r = DuplicateReport(
        sets: [],
        hashedCount: 10,
        pendingCount: 7,
      );
      expect(r.isScanning, isTrue);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('backfillHashes —— 分批补算 + 有失败就停', () {
    const perfChannel = MethodChannel('gtick/perf');

    /// 装一个假的 hashFiles：按 [plan] 决定每个路径返回什么。
    /// [calls] 记录被调了几次（验证不死循环）。
    void mockHashes(
      List<String?> Function(List<String> paths) plan, {
      List<int>? calls,
    }) {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(perfChannel, (call) async {
        if (call.method != 'hashFiles') return null;
        calls?.add(1);
        final args = (call.arguments as Map)['paths'] as List;
        return plan(args.cast<String>());
      });
    }

    tearDown(() {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(perfChannel, null);
    });

    test('老照片（NULL）被一次补齐，之后再调返回 0', () async {
      await seed([null, null, null]);
      mockHashes((paths) => [for (final p in paths) 'h_${p.hashCode}']);

      final svc = CameraCaptureService(repo);
      expect(await svc.backfillHashes(projectId), 3);
      expect((await repo.hashCoverage(projectId)).pending, 0);
      // 第二轮没有可补的了 —— 幂等
      expect(await svc.backfillHashes(projectId), 0);
    });

    test('超过一批（25 张）时按批走完，不漏张', () async {
      await seed(List<String?>.filled(25, null));
      final calls = <int>[];
      mockHashes((paths) {
        // 同内容 → 同指纹，制造一大组重复
        return [for (final _ in paths) 'same'];
      }, calls: calls);

      final done = await CameraCaptureService(repo).backfillHashes(projectId);
      expect(done, 25);
      expect((await repo.hashCoverage(projectId)).pending, 0);
      expect(calls.length, 2, reason: 'batchSize=20 → 20 + 5 两轮');
    });

    test('有文件读不到就停：已成功的写下，读不到的那张留 NULL', () async {
      // 25 张 = 2 批。第 1 批里第 4 张（index 3）读不到。
      await seed(List<String?>.filled(25, null));
      final calls = <int>[];
      mockHashes((paths) => [
        for (var i = 0; i < paths.length; i++) i == 3 ? null : 'h$i',
      ], calls: calls);

      final done = await CameraCaptureService(repo).backfillHashes(projectId);
      expect(done, 19, reason: '第 1 批 20 张里成功 19 张');
      expect(calls.length, 1,
          reason: '第 2 批不能跑 —— 失败不 break 就是死循环');

      final cov = await repo.hashCoverage(projectId);
      expect(cov.pending, 6, reason: '1 张读不到 + 第 2 批 5 张没轮到');
      final stillMissing =
          await repo.photosMissingHash(projectId, limit: 50);
      expect(stillMissing, hasLength(6));
    });

    test('通道整个挂掉：一张都不写，也不死循环', () async {
      await seed([null, null]);
      final calls = <int>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(perfChannel, (call) async {
        calls.add(1);
        throw PlatformException(code: 'HASH_ERROR');
      });

      final done = await CameraCaptureService(repo).backfillHashes(projectId);
      expect(done, 0);
      expect(calls.length, 1);
      expect((await repo.hashCoverage(projectId)).pending, 2,
          reason: '宁可一直"正在核查"，也不谎报无重复');
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 2026-10-05 老板追加需求：
  //   ①「重复提示要更具体明确地告诉用户」
  //   ②「当跨组重复时，让用户选择删除哪个组里的哪张」
  //
  // 这组测试钉的就是这两条。**「具体」是可测的** —— 数据里必须能
  // 拿到「第 N 组」这个次序，光有 group_id 的话 UI 只能写
  // 「出现在 2 个组」，用户没法判断该动哪张。
  group('组归属说得清（提示要具体的前提）', () {
    /// 造一个真实组（带 seq），返回组 id。
    Future<String> makeGroup(String id, int seq) async {
      await db.into(db.photoGroups).insert(
            PhotoGroupsCompanion.insert(
              id: id,
              projectId: projectId,
              sessionId: sessionId,
              seq: seq,
              createdAt: 1,
            ),
          );
      return id;
    }

    test('跨组重复：每张都能说出自己属于第几组', () async {
      await makeGroup('g-a', 2);
      await makeGroup('g-b', 5);
      final ids = await seed(['h1', 'h1'], groupOf: {0: 'g-a', 1: 'g-b'});

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.photoAt(0)!.groupSeq, 2);
      expect(s.photoAt(0)!.groupLabel, '第 2 组');
      expect(s.photoAt(1)!.groupSeq, 5);
      expect(s.photoAt(1)!.groupLabel, '第 5 组');
      // 顺序与 photoIds 对齐 —— UI 是按下标渲染的，错了就张冠李戴
      expect([for (final p in s.photos) p.id], ids);
    });

    test('groupSummary 写成「第 2 组 ↔ 第 5 组」（按次序升序）', () async {
      // 故意让第 2 张的组次序更小，验证是**排序后**拼接而非按数组顺序
      await makeGroup('g-x', 5);
      await makeGroup('g-y', 2);
      await seed(['h1', 'h1'], groupOf: {0: 'g-x', 1: 'g-y'});

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.groupSummary(), '第 2 组 ↔ 第 5 组');
    });

    test('组超过 3 个时写「…等 N 个组」（不把卡片撑爆）', () async {
      for (var i = 1; i <= 5; i++) {
        await makeGroup('g$i', i);
      }
      await seed(
        List<String?>.filled(5, 'h1'),
        groupOf: {0: 'g1', 1: 'g2', 2: 'g3', 3: 'g4', 4: 'g5'},
      );

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.groupSummary(), '第 1 组 ↔ 第 2 组 ↔ 第 3 组 等 5 个组');
    });

    test('同组内重复：soleGroupSeq 给出组号，标签不出现"↔"', () async {
      await makeGroup('g-a', 3);
      await seed(['h1', 'h1'], groupOf: {0: 'g-a', 1: 'g-a'});

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.soleGroupSeq, 3);
      expect(s.crossesGroups, isFalse);
    });

    test('游离照片：groupLabel 明确写「未分组」，groupSeq 为 null', () async {
      await seed(['h1', 'h1'], groupOf: {0: 'g-a'});

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.photoAt(1)!.isFloating, isTrue);
      expect(s.photoAt(1)!.groupLabel, '未分组');
      expect(s.photoAt(1)!.groupSeq, isNull);
    });

    test('组被删掉后残留的 group_id 不炸（LEFT JOIN 拿到 null）', () async {
      // 直接写一个不存在的 group_id —— 模拟组被删但照片还在的脏数据。
      final ids = await seed(['h1', 'h1'], groupOf: {0: 'ghost', 1: 'ghost'});

      final s = (await repo.findDuplicates(projectId)).single;
      expect(s.photoAt(0)!.groupSeq, isNull,
          reason: '组没了就不能说「第 N 组」，LEFT JOIN 保证不炸');
      expect(s.photoAt(0)!.isFloating, isFalse,
          reason: 'group_id 还在，只是查不到次序 —— 不能谎称"未分组"');
      expect(s.photoAt(0)!.id, ids.first);
    });

    test('crossGroupCount / withinGroupCount 分开计数', () async {
      await makeGroup('g1', 1);
      await makeGroup('g2', 2);
      await makeGroup('g3', 3);
      await seed(
        ['cross', 'cross', 'same', 'same'],
        groupOf: {0: 'g1', 1: 'g2', 2: 'g3', 3: 'g3'},
      );

      final r = DuplicateReport(
        sets: await repo.findDuplicates(projectId),
        hashedCount: 4,
        pendingCount: 0,
      );
      expect(r.crossGroupCount, 1);
      expect(r.withinGroupCount, 1);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('DuplicateBanner 三形态（显眼提示）', () {
    Future<void> pump(
      WidgetTester tester, {
      required bool loading,
      required int duplicateCount,
      required int scanning,
      int setCount = 0,
      int crossGroupCount = 0,
      VoidCallback? onOpen,
    }) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: DuplicateBanner(
            loading: loading,
            duplicateCount: duplicateCount,
            onScanning: scanning,
            setCount: setCount,
            crossGroupCount: crossGroupCount,
            onOpen: onOpen ?? () {},
          ),
        ),
      ));
    }

    testWidgets('一切正常 → 完全不占空间', (tester) async {
      await pump(tester, loading: false, duplicateCount: 0, scanning: 0);
      expect(find.textContaining('重复'), findsNothing);
    });

    testWidgets('有重复 → 橙色横幅写出「几组 + 要删几张」', (tester) async {
      await pump(tester,
          loading: false,
          duplicateCount: 9,
          scanning: 0,
          setCount: 3);
      expect(find.text('3 组照片重复 · 要删 9 张'), findsOneWidget);
    });

    testWidgets('跨组重复在横幅上点明（严重程度不是一个量级）', (tester) async {
      await pump(tester,
          loading: false,
          duplicateCount: 5,
          scanning: 0,
          setCount: 2,
          crossGroupCount: 2);
      final t = find.textContaining('2 组跨组');
      expect(t, findsOneWidget);
    });

    testWidgets('没给组数时退回「发现 N 张」（兼容旧调用方）', (tester) async {
      await pump(tester, loading: false, duplicateCount: 3, scanning: 0);
      expect(find.text('发现 3 张重复照片 · 要删 3 张'), findsOneWidget);
    });

    testWidgets('有重复时可点开处理面板', (tester) async {
      var opened = 0;
      await pump(tester,
          loading: false,
          duplicateCount: 2,
          scanning: 0,
          setCount: 1,
          onOpen: () => opened++);
      await tester.tap(find.textContaining('要删 2 张'));
      expect(opened, 1);
    });

    testWidgets('还在核查 → 显示剩余张数，且绝不出现"发现 0 张"', (tester) async {
      await pump(tester, loading: false, duplicateCount: 0, scanning: 8);
      expect(find.textContaining('正在核查'), findsOneWidget);
      expect(find.textContaining('还剩 8 张'), findsOneWidget);
      expect(find.textContaining('发现'), findsNothing);
    });

    testWidgets('首帧加载中 → 显示"正在核查"，不是"发现 0 张"',
        (tester) async {
      // 这一条是 2026-10-04 修出来的真缺陷：provider 在飞时
      // duplicateCount 还是 0，旧逻辑直接渲染橙色「发现 0 张重复照片」——
      // 还没查就宣布"没有"，比不提示更糟。
      await pump(tester, loading: true, duplicateCount: 0, scanning: 0);
      expect(find.textContaining('正在核查'), findsOneWidget);
      expect(find.textContaining('发现'), findsNothing);
    });

    testWidgets('核查中不可点（避免打开一个还不全的面板）', (tester) async {
      var opened = 0;
      await pump(tester,
          loading: true,
          duplicateCount: 0,
          scanning: 5,
          onOpen: () => opened++);
      await tester.tap(find.textContaining('正在核查'));
      expect(opened, 0);
    });
  });

  // ═══════════════════════════════════════════════════════════
  // 需求②：跨组重复时「让用户选择删除哪个组里的哪张」。
  //
  // 这组是**真跑删除**的端到端验证，不只验文案。
  // 关键判据有三条：
  //   ① 默认一张都不预勾（机器按"最早"猜保留，跨组时猜错就删掉有用的）；
  //   ② 用户只勾第 2 组的 → **只删那一张**，另一组的不动；
  //   ③ 每张缩略图都写着它属于第几组。
  group('跨组重复：逐张选删哪张', () {
    late List<String> photoIds;

    Future<void> seedTwoGroups(String hash) async {
      for (final (gid, seq) in [('g-a', 2), ('g-b', 5)]) {
        await db.into(db.photoGroups).insert(
              PhotoGroupsCompanion.insert(
                id: gid,
                projectId: projectId,
                sessionId: sessionId,
                seq: seq,
                createdAt: 1,
              ),
            );
      }
      photoIds = await seed([hash, hash], groupOf: {0: 'g-a', 1: 'g-b'});
    }

    /// 面板测试共用的 provider 覆写。
    ///
    /// ⚠️ 四个 provider 一个都不能少（2026-10-05 踩过）：删除成功后
    /// _deletePicked 会 invalidate 它们，全是 StreamProvider/FutureProvider，
    /// loading 态带 CircularProgressIndicator → **pumpAndSettle 永不返回**，
    /// 症状是「点完删除后 pumpAndSettle timed out」，看着像删除卡住，
    /// 实际是测试环境问题（测试环境不需要真重算这些流）。
    List<Override> overrides() => [
          appDatabaseProvider.overrideWithValue(db),
          openGroupsProvider.overrideWith((ref, id) => const Stream.empty()),
          supervisionPhotosProvider
              .overrideWith((ref, id) => const Stream.empty()),
          projectPhotoCountProvider.overrideWith((ref, id) => Stream.value(0)),
          duplicateReportProvider
              .overrideWith((ref, id) async => const DuplicateReport.empty()),
        ];

    /// 点完「删除」之后等异步删除落地。
    ///
    /// ⚠️ **不能用 `pumpAndSettle`**（2026-10-05 踩过）：删除走真实
    /// drift 事务 + 文件 IO，帧循环里总有未完成的 future，
    /// pumpAndSettle 会一直等到超时（症状：`pumpAndSettle timed out`，
    /// 看着像"删除卡住了"，其实只是测试等待方式不对）。
    ///
    /// 正确姿势：`runAsync` + `pump` 交替。**只 pump 帧推不动 drift 事务** ——
    /// 表现是"删了 1 张（第一张恰好在同步段完成）、第二张卡住不动"，
    /// 我为此误判过一次"第二次 deletePhoto 抛异常"，其实只是没等够。
    Future<void> settleAfterDelete(WidgetTester tester) async {
      for (var i = 0; i < 6; i++) {
        // 真异步：让 drift 事务、文件 IO 在真实事件循环里跑完
        await tester.runAsync(() => Future<void>.delayed(
            const Duration(milliseconds: 30)));
        await tester.pump();
      }
    }

    /// 打开面板并 pump 到底。
    ///
    /// ⚠️ [DuplicatePhoto.id] **必须用真实 photoId**（不能写空串）：
    /// 勾选状态是以 id 为键的 Map，id 对不上就永远选不中 —— 这类
    /// 「测试数据造得不像真的」会表现成"按钮点不动"，很难一眼看出。
    Future<void> openSheet(WidgetTester tester, String hash) async {
      // 关键：删除服务是 photoDeletionServiceProvider（它 watch
      // appDatabaseProvider）。不覆写就会真去开磁盘上的库，
      // 点「删除」删的是另一个库 —— 断言会莫名其妙地绿/红。
      // 覆写 appDatabaseProvider 就够了，它会顺着依赖传下去。
      //
      // showDuplicateSheet 要的是 **WidgetRef**（不是 container），
      // 所以按钮必须长在 ConsumerWidget 里 —— Builder 给不了。
      //
      await tester.pumpWidget(ProviderScope(
        overrides: overrides(),
        child: MaterialApp(
          home: Scaffold(
            body: _OpenButton(
              projectId: projectId,
              sets: [DuplicateSetWithGroups(
                hash: hash,
                photoIds: photoIds,
                earliestPhotoId: photoIds.first,
                groupIds: const ['g-a', 'g-b'],
                thumbPaths: [null, null],
                photos: [
                  DuplicatePhoto(
                      id: photoIds[0],
                      groupId: 'g-a',
                      groupSeq: 2,
                      seq: 1,
                      thumbPath: null),
                  DuplicatePhoto(
                      id: photoIds[1],
                      groupId: 'g-b',
                      groupSeq: 5,
                      seq: 2,
                      thumbPath: null),
                ],
              )],
            ),
          ),
        ),
      ));
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
    }

    testWidgets('每张缩略图标明属于第几组', (tester) async {
      await seedTwoGroups('h1');
      await openSheet(tester, 'h1');

      expect(find.text('第 2 组'), findsOneWidget);
      expect(find.text('第 5 组'), findsOneWidget);
      expect(find.textContaining('跨组重复 · 第 2 组 ↔ 第 5 组'), findsOneWidget);
      expect(find.textContaining('分组可能出错了'), findsOneWidget,
          reason: '跨组要说明白为什么这不只是"多拍了一张"');
    });

    testWidgets('默认一张都不预勾，且按钮禁用并说明下一步', (tester) async {
      await seedTwoGroups('h1');
      await openSheet(tester, 'h1');

      expect(find.text('选中删除'), findsNothing,
          reason: '跨组时机器猜不出该留哪张，绝不能替用户预勾');
      expect(find.text('请点缩略图选中要删的张'), findsOneWidget,
          reason: '禁用按钮必须解释怎么用，否则是可用性反模式');
    });

    testWidgets('只勾第 5 组那张 → 只删它，第 2 组的留下', (tester) async {
      await seedTwoGroups('h1');
      await openSheet(tester, 'h1');

      // 点第 5 组那张（第二个缩略图）
      await tester.tap(find.text('第 5 组'));
      await tester.pumpAndSettle();
      expect(find.text('删掉选中的 1 张'), findsOneWidget);

      await tester.tap(find.text('删掉选中的 1 张'));
      await settleAfterDelete(tester);

      // 断言落到数据库：第 5 组那张（photoIds[1]）没了，第 2 组的还在
      final left = await db.select(db.photos).get();
      expect(left.map((p) => p.id).toList(), [photoIds.first],
          reason: '用户勾的是第 5 组那张，就只能删那一张');
    });

    testWidgets('勾选可取消（点两次回到未选）', (tester) async {
      await seedTwoGroups('h1');
      await openSheet(tester, 'h1');

      await tester.tap(find.text('第 2 组'));
      await tester.pumpAndSettle();
      expect(find.text('删掉选中的 1 张'), findsOneWidget);

      await tester.tap(find.text('第 2 组'));
      await tester.pumpAndSettle();
      expect(find.text('请点缩略图选中要删的张'), findsOneWidget);
    });

    testWidgets('两张都勾 → 都删（用户自己确认过就是全要删）', (tester) async {
      await seedTwoGroups('h1');
      await openSheet(tester, 'h1');

      await tester.tap(find.text('第 2 组'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('第 5 组'));
      await tester.pumpAndSettle();
      expect(find.text('删掉选中的 2 张'), findsOneWidget);

      await tester.tap(find.text('删掉选中的 2 张'));
      await settleAfterDelete(tester);

      expect(await db.select(db.photos).get(), isEmpty);
      expect(find.text('重复照片已处理完'), findsOneWidget);
    });

    testWidgets('删 1 张后还有 2 张重复 → 明确说"还没删干净"', (tester) async {
      // ⚠️ 这条测的是**部分处理完**的提示，所以必须造 3 张重复：
      // 删掉 1 张后还剩 2 张 —— 2 张仍然彼此重复，没处理完。
      //
      // 我第一版用 2 张（删 1 剩 1），可 1 张**根本不重复**了
      // （判重要求 >= 2 张），"还剩 1 张重复"是句假话 ——
      // **测试前提写错，断言就成了一根永远绿的拐杖**。
      for (final (gid, seq) in [('g-a', 1), ('g-b', 2), ('g-c', 3)]) {
        await db.into(db.photoGroups).insert(
              PhotoGroupsCompanion.insert(
                id: gid,
                projectId: projectId,
                sessionId: sessionId,
                seq: seq,
                createdAt: 1,
              ),
            );
      }
      photoIds = await seed(
        ['h1', 'h1', 'h1'],
        groupOf: {0: 'g-a', 1: 'g-b', 2: 'g-c'},
      );

      await tester.pumpWidget(ProviderScope(
        overrides: overrides(),
        child: MaterialApp(
          home: Scaffold(
            body: _OpenButton(
              projectId: projectId,
              sets: [DuplicateSetWithGroups(
                hash: 'h1',
                photoIds: photoIds,
                earliestPhotoId: photoIds.first,
                groupIds: const ['g-a', 'g-b', 'g-c'],
                thumbPaths: [null, null, null],
                photos: [
                  for (var i = 0; i < 3; i++)
                    DuplicatePhoto(
                      id: photoIds[i],
                      groupId: 'g-${['a', 'b', 'c'][i]}',
                      groupSeq: i + 1,
                      seq: i + 1,
                      thumbPath: null,
                    ),
                ],
              )],
            ),
          ),
        ),
      ));
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('第 2 组'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('删掉选中的 1 张'));
      await settleAfterDelete(tester);

      expect(find.textContaining('已删掉 1 张'), findsOneWidget);
      expect(find.textContaining('还剩 2 张重复待处理'), findsOneWidget,
          reason: '还剩 2 张彼此重复 = 这组还没处理完，必须说出来');
      // 还剩重复就不该显示"已处理完"
      expect(find.text('重复照片已处理完'), findsNothing);
    });

    testWidgets('两张里删 1 张 → 这一组已清干净（剩 1 张不再重复）',
        (tester) async {
      await seedTwoGroups('h1');
      await openSheet(tester, 'h1');

      await tester.tap(find.text('第 5 组'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('删掉选中的 1 张'));
      await settleAfterDelete(tester);

      expect(find.textContaining('这一组已清干净'), findsOneWidget,
          reason: '剩 1 张不构成重复，这时候说"还剩 1 张重复"是骗人');
      expect(find.text('重复照片已处理完'), findsOneWidget);
    });
  });
}

/// 只为测试用的开面板按钮 —— 必须长在 ConsumerWidget 里才能拿到
/// [WidgetRef]（showDuplicateSheet 的第二个参数就是它）。
class _OpenButton extends ConsumerWidget {
  const _OpenButton({required this.projectId, required this.sets});

  final String projectId;
  final List<DuplicateSetWithGroups> sets;

  @override
  Widget build(BuildContext context, WidgetRef ref) => TextButton(
        onPressed: () => showDuplicateSheet(context, ref,
            projectId: projectId, sets: sets),
        child: const Text('打开'),
      );
}
