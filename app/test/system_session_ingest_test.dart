/// 系统相机拍照入库 v2 的钉子测试（2026-10-22，feat/system-camera-v2）。
///
/// v2 同步契约：`launchSession` 同步回首批 → 入库 → Dart 轮询
/// `collectLate` 拉晚到 → 实测对账 → 收口。fake 桩按新契约实现：
/// `shots` 是首批，`lateBatches` 按 collectLate 调用次序吐晚到批，
/// 吐完即 done。
///
/// 测试纪律（历史教训都在，别删）：
///  · 不写真实库（NativeDatabase.memory）；
///  · 造 UI 数据必须真生成 jpg（makeShot）；
///  · mock makeThumbs 必须真写非空目标文件；
///  · 断言「入库实测」而不是「收到几批」。
library;

import 'dart:async';
import 'dart:io';

import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show MethodChannel;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/app/providers.dart';
import 'package:g_tick_picture/core/constants.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/fs/project_paths.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/organize_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/capture/camera_capture_service.dart';
import 'package:g_tick_picture/domain/capture/camera_preferences.dart';
import 'package:g_tick_picture/domain/capture/gallery_service.dart';
import 'package:g_tick_picture/domain/capture/system_camera_service.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/model/gallery_photo.dart';
import 'package:g_tick_picture/ui/capture/system_camera_actions.dart';
import 'package:image/image.dart' as img;
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';

/// 假系统相机服务（v2 契约）。
///
/// **同一个对象改内容**（不换实例）—— ProviderScope 的 override 在
/// pumpWidget 时就把对象封进了 provider。
class _FakeSystemCamera extends SystemCameraService {
  /// launchSession 的首批。
  List<SystemSessionShot> shots = const [];

  /// collectLate 按调用次序吐的晚到批；吐完返回空 + done=true。
  List<List<SystemSessionShot>> lateBatches = const [];

  /// 空首批时是否「大概率拍了」（决定 cancelled 还是 missed）。
  bool likely = false;

  int sessionCalls = 0;
  int collectLateCalls = 0;

  /// recoverSession 的预置返回。null = 原生没有挂起上下文（默认）。
  List<SystemSessionShot>? recoveryShots;

  String sessionId = 'test-session';

  @override
  Future<(List<SystemSessionShot>, String, String, bool)> launchSession() async {
    sessionCalls++;
    return (
      shots,
      '测试桩：首批 ${shots.length} 张',
      sessionId,
      likely,
    );
  }

  @override
  Future<({List<SystemSessionShot> shots, bool done})> collectLate(
    String sessionId,
  ) async {
    collectLateCalls++;
    if (collectLateCalls <= lateBatches.length) {
      return (shots: lateBatches[collectLateCalls - 1], done: false);
    }
    return (shots: const <SystemSessionShot>[], done: true);
  }

  @override
  Future<void> endCollect(String sessionId) async {}

  @override
  Future<SessionRecovery> recoverSession() async {
    final r = recoveryShots;
    return SessionRecovery(
      shots: r ?? const [],
      hasContext: r != null,
      diag: r == null ? '' : '测试桩：恢复 ${r.length} 张',
      sessionId: sessionId,
    );
  }
}

/// 假相册服务：记录 save 调用，不碰平台通道。
class _RecordingGallery extends GalleryService {
  final List<Map<String, Object?>> saves = [];

  @override
  Future<bool> get isEnabled async => true;

  @override
  Future<GallerySaveResult> save({
    required String srcPath,
    required String album,
    String? displayName,
    DateTime? takenAt,
  }) async {
    saves.add({'srcPath': srcPath, 'album': album, 'takenAt': takenAt});
    return const GallerySaveResult(saved: 1, failed: 0);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late AppDatabase db;
  late CaptureRepository capture;
  late OrganizeRepository organize;
  late ProjectRepository projects;
  late _RecordingGallery gallery;
  late CameraCaptureService svc;
  late String projectId;
  late Directory projRoot; // ProjectPaths 覆盖根
  late Directory tempDir; // 系统相册（DCIM 的同构替身）
  late _FakeSystemCamera fake;

  /// perf 通道 mock：缩略图/指纹的后台派生不该把测试拖进平台依赖。
  ///
  /// makeThumbs **必须真的写一个非空目标文件** —— makeThumbnails 对原生
  /// 结果要「验货」（stat dstPath 非空），不写就回退 isolate 真实生成，
  /// 而 isolate 在 runAsync 里的完成时序不可靠（钉子测试会假挂）。
  void mockPerf({Duration thumbDelay = Duration.zero}) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(const MethodChannel('gtick/perf'),
            (call) async {
      switch (call.method) {
        case 'makeThumbs':
          if (thumbDelay > Duration.zero) {
            await Future<void>.delayed(thumbDelay);
          }
          final jobs = (call.arguments as Map)['jobs'] as List;
          for (final j in jobs) {
            final dst = (j as Map)['dstPath'] as String;
            final dir = Directory(p.dirname(dst));
            if (!dir.existsSync()) dir.createSync(recursive: true);
            File(dst).writeAsBytesSync(const [1, 2, 3], flush: true);
          }
          return [
            for (var i = 0; i < jobs.length; i++)
              {'ok': true, 'w': 32, 'h': 24, 'luma': 0.42}
          ];
        case 'hashFiles':
          final paths = (call.arguments as Map)['paths'] as List;
          return [for (var i = 0; i < paths.length; i++) 'h$i'];
        default:
          return null;
      }
    });
  }

  setUp(() async {
    // 全文件统一 mock SP（挂起标记/诊断读写在这里）。
    SharedPreferences.setMockInitialValues({});
    db = AppDatabase.forTesting(NativeDatabase.memory());
    capture = CaptureRepository(db);
    organize = OrganizeRepository(db);
    projects = ProjectRepository(db);
    gallery = _RecordingGallery();
    svc = CameraCaptureService(capture, gallery: gallery);
    projectId = await projects.create(name: '会话收图测试');
    projRoot = await Directory.systemTemp.createTemp('gt_sess_proj_');
    tempDir = await Directory.systemTemp.createTemp('gt_sess_dcim_');
    ProjectPaths.overrideRootForTest(projRoot);
    fake = _FakeSystemCamera();
    mockPerf();
  });

  tearDown(() async {
    await svc.dispose();
    await db.close();
    ProjectPaths.overrideRootForTest(null);
    for (final d in [projRoot, tempDir]) {
      for (var i = 0; i < 5; i++) {
        try {
          if (!d.existsSync()) break;
          await d.delete(recursive: true);
          break;
        } on FileSystemException {
          await Future<void>.delayed(const Duration(milliseconds: 200));
        }
      }
    }
  });

  /// 造一张「相机 App 写进相册的」JPEG（会话原图，只复制不移动）。
  Future<File> makeShot(
    String name, {
    int width = 8,
    int height = 8,
  }) async {
    final image = img.Image(width: width, height: height);
    final f = File('${tempDir.path}${Platform.pathSeparator}$name');
    await f.writeAsBytes(img.encodeJpg(image, quality: 80), flush: true);
    return f;
  }

  /// 挂上 provider override 的 WidgetRef（权限确认在测试平台非
  /// Android/iOS 直接放行，无需 mock）。
  Future<WidgetRef> warmRef(WidgetTester tester) async {
    late WidgetRef got;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          systemCameraServiceProvider.overrideWithValue(fake),
          appDatabaseProvider.overrideWithValue(db),
          galleryServiceProvider.overrideWithValue(gallery),
        ],
        child: Consumer(
          builder: (context, r, _) {
            got = r;
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    return got;
  }

  testWidgets('会话 ingest 全链：N 张收得回、入库、原图不动、不写相册镜像',
      (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final a = await makeShot('ok_a.jpg');
      final b = await makeShot('ok_b.jpg');
      final c = await makeShot('ok_c.jpg');
      fake.shots = [
        SystemSessionShot(
            path: a.path, takenAt: DateTime(2026, 10, 15, 10, 0, 1)),
        SystemSessionShot(
            path: b.path, takenAt: DateTime(2026, 10, 15, 10, 0, 2)),
        SystemSessionShot(
            path: c.path, takenAt: DateTime(2026, 10, 15, 10, 0, 3)),
      ];

      final (outcome, ids, shotCount) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );

      expect(outcome, SystemShotOutcome.shot);
      expect(ids, hasLength(3));
      expect(shotCount, 3, reason: '原生收图张数要如实报出');
      // move:false —— DCIM 归相册管，「原始文件永不改名」的边界在项目外
      expect(await a.exists(), isTrue);
      expect(await b.exists(), isTrue);
      expect(await c.exists(), isTrue);
      // galleryMirror:false —— 照片本来就在相册里，不写镜像
      expect(gallery.saves, isEmpty);
      // takenAt 用 MediaStore DATE_TAKEN 覆盖（不是 now，也不是文件 mtime）
      for (var i = 0; i < ids.length; i++) {
        final p = await capture.getPhoto(ids[i]);
        expect(
          DateTime.fromMillisecondsSinceEpoch(p!.takenAt),
          DateTime(2026, 10, 15, 10, 0, i + 1),
        );
      }
      // 同一批次、seq 不重复（并发 ingest 的正确性）
      final rows = await db.select(db.photos).get();
      expect(rows, hasLength(3));
      expect(rows.map((p) => p.seq).toSet(), hasLength(3));
      final session = await capture.getSession(rows.first.sessionId);
      expect(session!.photoCount, 3);
      // v2 收口：一场拍照结束时批次必须结束（下一拍 5 分钟内 resumable）。
      expect(session.endedAt, isNotNull, reason: '一场拍照 = 一个收口的批次');
      // 挂起标记被消费（一次完整的「拍 → 收 → 入库」闭环）。
      expect(
        await CameraPreferences().takePendingSession(),
        isNull,
        reason: '收口后挂起标记必须清掉，否则重启会误恢复',
      );
    });
  });

  testWidgets('组内补拍闭环：会话收图 → attachPhotosToGroup 挂得上',
      (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final a = await makeShot('grp_a.jpg');
      final b = await makeShot('grp_b.jpg');
      fake.shots = [
        SystemSessionShot(
            path: a.path, takenAt: DateTime(2026, 10, 15, 10, 5, 1)),
        SystemSessionShot(
            path: b.path, takenAt: DateTime(2026, 10, 15, 10, 5, 2)),
      ];

      final (outcome, ids, shotCount) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );
      expect(outcome, SystemShotOutcome.shot);
      expect(ids, hasLength(2));

      // 整理页已有一个开放组（补拍的目标）
      final sessionId = (await capture.getPhoto(ids.first))!.sessionId;
      final groupId = await organize.createGroup(projectId, sessionId);
      final moved = await organize.attachPhotosToGroup(projectId, groupId, ids);
      expect(moved, 2);

      final rows = await (db.select(db.photos)
            ..where((p) => p.id.isIn(ids)))
          .get();
      for (final r in rows) {
        expect(r.groupId, groupId, reason: '补拍照片必须挂进目标组');
      }
    });
  });

  testWidgets('组内补拍：传 intoGroupId 时收完自动挂组', (tester) async {
    // 挂组由会话自己完成（页面拿 ids 只做二次确认），否则组内补拍会变成
    // "照片进了项目但没进组"。
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final sid = await capture.startSession(projectId);
      final groupId = await organize.createGroup(projectId, sid);
      final a = await makeShot('grp_auto.jpg');
      fake.shots = [
        SystemSessionShot(
            path: a.path, takenAt: DateTime(2026, 10, 15, 10, 6, 1)),
      ];

      final (outcome, ids, _) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
        intoGroupId: groupId,
      );
      expect(outcome, SystemShotOutcome.shot);
      expect(ids, hasLength(1));
      final row = await capture.getPhoto(ids.single);
      expect(row!.groupId, groupId, reason: '照片必须自动挂进目标组');
    });
  });

  testWidgets('一张没拍就返回：cancelled 静默，且不建空批次', (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      fake.shots = const [];
      fake.likely = false; // 停留短：原生判定「大概率没拍」

      final (outcome, ids, shotCount) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );

      expect(outcome, SystemShotOutcome.cancelled);
      expect(ids, isEmpty);
      expect(shotCount, 0);
      // 空批次会被 5 分钟窗续上添乱 —— cancelled 不许建批
      final sessions = await db.select(db.captureSessions).get();
      expect(sessions, isEmpty);
      expect(fake.sessionCalls, 1);
      expect(fake.collectLateCalls, 0,
          reason: '大概率没拍时不轮询（原生空窗已等过，快进快出）');
    });
  });

  testWidgets('单张坏路径不拖垮整批：有序回填剩下的', (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final a = await makeShot('bad_a.jpg');
      final b = await makeShot('bad_b.jpg');
      fake.shots = [
        SystemSessionShot(
            path: a.path, takenAt: DateTime(2026, 10, 15, 10, 9, 1)),
        SystemSessionShot(path: '${tempDir.path}/gone.jpg'), // 索引给了条不存在的
        SystemSessionShot(
            path: b.path, takenAt: DateTime(2026, 10, 15, 10, 9, 3)),
      ];

      final (outcome, ids, shotCount) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );

      expect(outcome, SystemShotOutcome.shot);
      expect(ids, hasLength(2));
      // ⚠️ v0.24.5 钉子：原生收到 3 张、只存下 2 张时，shotCount 必须
      // 如实报 3 —— UI 据此显示「相机 3 张 · 只存下 2 张 · 缺的可在
      // 相册里补收」。
      expect(shotCount, 3);
      expect(shotCount, greaterThan(ids.length));
      final rows = await db.select(db.photos).get();
      expect(rows, hasLength(2));
      final byTaken = rows.map((p) => p.takenAt).toList()..sort();
      expect(byTaken.first,
          DateTime(2026, 10, 15, 10, 9, 1).millisecondsSinceEpoch);
      expect(byTaken.last,
          DateTime(2026, 10, 15, 10, 9, 3).millisecondsSinceEpoch);
    });
  });

  testWidgets('晚到照片：collectLate 拉到 → 进同批次（5 分钟续接）→ 收口',
      (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final a = await makeShot('late_first.jpg');
      final b = await makeShot('late_second.jpg');
      fake.shots = [
        SystemSessionShot(
            path: a.path, takenAt: DateTime(2026, 10, 21, 9, 0, 1)),
      ];
      // 相机在返回后又写完一张 —— 第一次 collectLate 吐出来。
      fake.lateBatches = [
        [
          SystemSessionShot(
              path: b.path, takenAt: DateTime(2026, 10, 21, 9, 0, 2)),
        ],
      ];

      final (outcome, ids, shotCount) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );

      expect(outcome, SystemShotOutcome.shot);
      expect(ids, hasLength(2), reason: '首批 + 晚到 = 2 张都要入库');
      expect(shotCount, 2);
      final rows = await db.select(db.photos).get();
      expect(rows, hasLength(2));
      expect(rows.map((p) => p.sessionId).toSet(), hasLength(1),
          reason: '晚到照片必须进同批次（一批一组）');
      final session = await capture.getSession(rows.first.sessionId);
      expect(session!.endedAt, isNotNull, reason: '轮询结束必须收口');
    });
  });

  testWidgets('changed=true 走修复：重拷覆盖，不重复插行', (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final a = await makeShot('fix_a.jpg');
      fake.shots = [
        SystemSessionShot(
            path: a.path, takenAt: DateTime(2026, 10, 21, 9, 5, 1)),
      ];
      // 相机把同一张补写完（内容更大）—— 按修复推，不许再插一行。
      // 重跑 makeShot 让源文件字节变化（40×40）。
      unawaited(makeShot('fix_a.jpg', width: 40, height: 40));
      fake.lateBatches = [
        [
          SystemSessionShot(
              path: a.path,
              takenAt: DateTime(2026, 10, 21, 9, 5, 1),
              changed: true),
        ],
      ];

      final (outcome, ids, _) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );
      expect(outcome, SystemShotOutcome.shot);
      expect(ids, hasLength(1), reason: '修复不产生第二行');
      final rows = await db.select(db.photos).get();
      expect(rows, hasLength(1));
    });
  });

  testWidgets('空首批 + likely=true：继续轮询；轮完仍空 → missed',
      (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      fake.shots = const [];
      fake.likely = true; // 停留 ≥2.5s：原生判定「大概率拍了」

      final (outcome, ids, shotCount) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );

      expect(outcome, SystemShotOutcome.missed,
          reason: '大概率拍了却一张没收到 —— 必须明说，不许静默');
      expect(ids, isEmpty);
      expect(fake.collectLateCalls, greaterThanOrEqualTo(1),
          reason: 'likely 时空首批也要轮询（照片可能还在写盘）');
      final sessions = await db.select(db.captureSessions).get();
      expect(sessions, isEmpty, reason: '没收到就不建批次');
    });
  });

  testWidgets('问题1钉子：owned 一次性服务 ingest 完不等派生（立刻回 App）',
      (tester) async {
    // 慢派生 mock：缩略图要 4 秒。owned 一次性服务 dispose(awaitDerived:
    // false) 必须立即返回（老板反馈「一次拍多张，很久才进 App」）。
    mockPerf(thumbDelay: const Duration(seconds: 4));
    late WidgetRef got;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appDatabaseProvider.overrideWithValue(db),
          galleryServiceProvider.overrideWithValue(gallery),
          systemCameraServiceProvider.overrideWithValue(fake),
        ],
        child: Consumer(
          builder: (context, r, _) {
            got = r;
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    await tester.runAsync(() async {
      final shot = await makeShot('slow.jpg');
      fake.shots = [
        SystemSessionShot(
            path: shot.path, takenAt: DateTime(2026, 10, 15, 10, 12)),
      ];

      final sw = Stopwatch()..start();
      final (outcome, ids, shotCount) = await runSystemCameraSession(
        ref: got,
        projectId: projectId,
      );
      sw.stop();
      expect(outcome, SystemShotOutcome.shot);
      expect(shotCount, 1, reason: '单张会话：原生 1 张 = 入库 1 张');
      expect(sw.elapsedMilliseconds, lessThan(3500),
          reason: 'owned 一次性服务不许等派生（拍完很久才进 App）');

      // 主链已完成：照片行在库（返回不靠派生）
      final before = await capture.getPhoto(ids.single);
      expect(before, isNotNull);
      expect(before!.thumbPath, isNull, reason: '派生还没跑完（mock 4s）');
    });
  });

  testWidgets('正常会话收完图：挂起标记清、批次收口、5 分钟内再拍续接同批',
      (tester) async {
    final prefs = CameraPreferences();
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final shot = await makeShot('close_a.jpg');
      fake.shots = [
        SystemSessionShot(
            path: shot.path, takenAt: DateTime(2026, 10, 20, 11, 5)),
      ];
      final (outcome, ids, _) = await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );
      expect(outcome, SystemShotOutcome.shot);
      expect(await prefs.takePendingSession(), isNull,
          reason: '正常收完，挂起标记必须清');

      final open = await capture.findOpenSession(projectId,
          source: CaptureSource.camera);
      expect(open, isNull, reason: '一场拍照结束必须收口');

      // 5 分钟内再拍 → startSession 复活同批次（分组语义不变）。
      final resumed = await capture.startSession(projectId);
      final rows = await db.select(db.photos).get();
      expect(resumed, rows.single.sessionId);
      final s = await capture.getSession(resumed);
      expect(s!.endedAt, isNull, reason: 'resumable 复活后批次重新 open');
      expect(
        s.startedAt,
        lessThanOrEqualTo(DateTime.now().millisecondsSinceEpoch),
      );
      expect(
        AppConst.sessionResumeWindow,
        const Duration(minutes: 5),
        reason: '续接窗口是产品语义，别悄悄改',
      );
    });
  });

  testWidgets('进程被杀恢复：pending 存在 → 补收入库 → 已入库过滤不重复',
      (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final a = await makeShot('rec_a.jpg');
      final b = await makeShot('rec_b.jpg');
      // 被杀前 a 已入库（账本里有），b 没来得及。
      await svc.startSession(projectId);
      await svc.captureFromFile(projectId, a.path, move: false);

      fake.recoveryShots = [
        SystemSessionShot(
            path: a.path, takenAt: DateTime(2026, 10, 20, 11, 0, 1)),
        SystemSessionShot(
            path: b.path, takenAt: DateTime(2026, 10, 20, 11, 0, 2)),
      ];

      final recovered = await recoverPendingCameraSession(
        ref,
        projectId,
        DateTime.now(),
      );
      expect(recovered, 1, reason: '只有没入库的 b 需要补收');
      final rows = await db.select(db.photos).get();
      expect(rows, hasLength(2), reason: 'a 不重复入库');
    });
  });

  testWidgets('恢复无上下文：recentTempShots 兜底（单张残留补收）',
      (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      // 单张降级路径被杀：EXTRA_OUTPUT 文件留在 gt_temp/。
      final root = await ProjectPaths.filesRoot();
      final gtTemp = Directory('${root.path}${Platform.pathSeparator}gt_temp');
      gtTemp.createSync(recursive: true);
      final image = img.Image(width: 8, height: 8);
      final leftover = File(
          '${gtTemp.path}${Platform.pathSeparator}gt_shot_leftover.jpg');
      await leftover.writeAsBytes(img.encodeJpg(image, quality: 80),
          flush: true);
      fake.recoveryShots = null; // 原生没有上下文

      final recovered = await recoverPendingCameraSession(
        ref,
        projectId,
        DateTime.now(),
      );
      expect(recovered, 1, reason: 'gt_temp 里的残留要补收');
      final rows = await db.select(db.photos).get();
      expect(rows, hasLength(1));
    });
  });

  testWidgets('诊断摘要落「关于」面板（现场排障入口）', (tester) async {
    final ref = await warmRef(tester);
    await tester.runAsync(() async {
      final shot = await makeShot('diag_a.jpg');
      fake.shots = [
        SystemSessionShot(
            path: shot.path, takenAt: DateTime(2026, 10, 22, 9, 0, 1)),
      ];
      await runSystemCameraSession(
        ref: ref,
        projectId: projectId,
        svc: svc,
      );
      final prefs = CameraPreferences();
      expect(await prefs.sessionDiag(), contains('测试桩'),
          reason: '正常路径的诊断必须可见 —— 现场少收/没收截图即可定位');
    });
  });
}
