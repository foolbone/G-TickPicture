/// 系统相机拍照 ingest 的规格说明（2026-10-14 v0.22.0）。
///
/// [CameraCaptureService.captureFromFile] 是「拍照委托系统相机」的服务侧
/// 落点：拍照发生在系统相机里（全尺寸原图落在 App 临时文件），本方法把
/// 文件收进当前批次。钉死的承诺：
///   ① 续接当前 open camera 批次，**不开新批**（一批一组的根基；
///      与相册导入的 album 批次严格分列，审计可分）；
///   ② takenAt = EXIF 拍摄时刻 → 文件修改时间（**不用 now()**：
///      系统相机往返有几秒，now() 会把「回来的时刻」当「快门时刻」）；
///   ③ 临时文件被**移动**（rename 同根原子移动）进项目 raw 目录；
///   ④ seq 连续、批次计数同步、事件派发；
///   ⑤ 文件缺失/为空 = 这张没拍上（shot 错误），**批次不结束**；
///   ⑥ 相册镜像被调用（P4「拍照要进手机相册」不因委托而丢）。
@Timeout(Duration(minutes: 2))
library;

import 'dart:io';

import 'package:drift/native.dart';
import 'package:flutter/services.dart' show MethodChannel;
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/fs/project_paths.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/capture/camera_capture_service.dart';
import 'package:g_tick_picture/domain/capture/capture_service.dart';
import 'package:g_tick_picture/domain/capture/gallery_service.dart';
import 'package:g_tick_picture/domain/model/gallery_photo.dart';
import 'package:image/image.dart' as img;

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
  // mock 平台通道前必须初始化 binding（gallery_picker_position_test 同款）
  TestWidgetsFlutterBinding.ensureInitialized();

  late AppDatabase db;
  late CaptureRepository capture;
  late ProjectRepository projects;
  late _RecordingGallery gallery;
  late CameraCaptureService svc;
  late String projectId;
  late Directory projRoot; // ProjectPaths 覆盖根
  late Directory tempDir; // 系统相机临时目录（gt_temp 的同构替身）

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    capture = CaptureRepository(db);
    projects = ProjectRepository(db);
    gallery = _RecordingGallery();
    svc = CameraCaptureService(capture, gallery: gallery);
    projectId = await projects.create(name: '系统相机拍照测试');
    projRoot = await Directory.systemTemp.createTemp('gt_syscam_proj_');
    tempDir = await Directory.systemTemp.createTemp('gt_syscam_temp_');
    ProjectPaths.overrideRootForTest(projRoot);

    // perf 通道 mock：缩略图/指纹的后台派生不该把测试拖进平台依赖。
    // 返回 ok=true 的假结果（本测试不断言缩略图本身）。
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(const MethodChannel('gtick/perf'),
            (call) async {
      switch (call.method) {
        case 'makeThumbs':
          final jobs = (call.arguments as Map)['jobs'] as List;
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
  });

  tearDown(() async {
    await svc.dispose();
    await db.close();
    ProjectPaths.overrideRootForTest(null);
    // Windows 句柄占用重试删（photo_exif_test 同款教训：立即删必红门禁）
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

  /// 造一张「系统相机写出来的」JPEG（带可选 EXIF 快门时刻）。
  Future<File> makeShot(String name, {String? exifWhen}) async {
    final image = img.Image(width: 8, height: 8);
    if (exifWhen != null) {
      image.exif.exifIfd['DateTimeOriginal'] = exifWhen;
    }
    final f = File('${tempDir.path}${Platform.pathSeparator}$name');
    await f.writeAsBytes(img.encodeJpg(image, quality: 80), flush: true);
    return f;
  }

  /// 等后台派生尾巴（缩略图/镜像/指纹）跑完再收摊，避免 teardown 竞态。
  Future<void> settle() =>
      Future<void>.delayed(const Duration(milliseconds: 500));

  test('冷启动直接 ingest：自开 camera 批次，不入 album 批次', () async {
    final shot = await makeShot('cold.jpg', exifWhen: '2026:10:14 09:20:00');
    final id = await svc.captureFromFile(projectId, shot.path);
    expect(id, isNotEmpty);

    final photo = await capture.getPhoto(id);
    expect(photo, isNotNull);
    expect(photo!.sessionId, isNotNull);
    final session = await capture.getSession(photo.sessionId);
    // 系统相机拍的照片必须是 camera 来源（与相册导入分列，审计可分）
    expect(session!.source, 'camera');
    expect(session.photoCount, 1);
  });

  test('续接当前 open 批次，不开新批（一批一组的根基）', () async {
    final sid = await svc.startSession(projectId);
    await capture.insertPhotos(projectId, [
      for (var i = 0; i < 2; i++)
        NewPhoto(
          sessionId: sid,
          filePath: '/fake/existing_$i.jpg',
          seq: i + 1,
          takenAt: DateTime(2026, 10, 14, 9, 0, i),
        ),
    ]);

    final shot = await makeShot('join.jpg', exifWhen: '2026:10:14 09:21:00');
    final id = await svc.captureFromFile(projectId, shot.path);

    final photo = await capture.getPhoto(id);
    expect(photo!.sessionId, sid, reason: '必须进同一批次，不能新开');
    expect((await capture.getSession(sid))!.photoCount, 3);
    // 全库只有这一个批次（没有第二个 session 行）
    final sessions = await db.select(db.captureSessions).get();
    expect(sessions.length, 1);
  });

  test('takenAt 取 EXIF 快门时刻，不是文件 mtime，更不是 now()', () async {
    await svc.startSession(projectId);
    final shot = await makeShot('exif.jpg', exifWhen: '2026:10:13 15:30:45');
    // 把 mtime 改成一个明显不同的时刻：证明 EXIF 赢
    await shot.setLastModified(DateTime(2020, 1, 1, 0, 0, 0));

    final id = await svc.captureFromFile(projectId, shot.path);
    final photo = await capture.getPhoto(id);
    // photos.takenAt 是 int 毫秒（drift 惯例）—— 换算成本地时间再比
    expect(
      DateTime.fromMillisecondsSinceEpoch(photo!.takenAt),
      DateTime(2026, 10, 13, 15, 30, 45),
    );
  });

  test('无 EXIF 时退化到文件修改时间', () async {
    await svc.startSession(projectId);
    final shot = await makeShot('noexif.jpg');
    await shot.setLastModified(DateTime(2026, 10, 1, 12, 0, 0));

    final id = await svc.captureFromFile(projectId, shot.path);
    final photo = await capture.getPhoto(id);
    expect(
      DateTime.fromMillisecondsSinceEpoch(photo!.takenAt),
      DateTime(2026, 10, 1, 12, 0, 0),
    );
  });

  test('临时文件被移动（不是复制）进项目 raw 目录', () async {
    await svc.startSession(projectId);
    final shot = await makeShot('move.jpg', exifWhen: '2026:10:14 09:22:00');

    final id = await svc.captureFromFile(projectId, shot.path);
    final photo = await capture.getPhoto(id);

    expect(await shot.exists(), isFalse, reason: '同根 rename 是移动，临时文件不该还在');
    final dst = File(photo!.filePath);
    expect(await dst.exists(), isTrue);
    expect(dst.parent.path, contains('raw'));
    expect(photo.bytes, greaterThan(0));
  });

  test('seq 连续：新 ingest 接着全项目最大 seq 往后排', () async {
    // 真实时序：上一场拍过（seq 1）→ 结束 → 再进采集页。
    // startSession 时 _nextSeq 按全项目 MAX(seq)+1 取，与插入先后无关。
    final oldSid = await capture.startSession(projectId);
    await capture.insertPhotos(projectId, [
      NewPhoto(
        sessionId: oldSid,
        filePath: '/fake/one.jpg',
        seq: 1,
        takenAt: DateTime(2026, 10, 14, 9),
      ),
    ]);
    await capture.endSession(oldSid);

    final sid = await svc.startSession(projectId);
    final a = await makeShot('s1.jpg', exifWhen: '2026:10:14 09:23:00');
    final b = await makeShot('s2.jpg', exifWhen: '2026:10:14 09:24:00');
    final id1 = await svc.captureFromFile(projectId, a.path);
    final id2 = await svc.captureFromFile(projectId, b.path);

    final p1 = await capture.getPhoto(id1);
    final p2 = await capture.getPhoto(id2);
    expect(p1!.seq, 2, reason: '接着旧批次的 MAX(seq)+1');
    expect(p2!.seq, 3);
    expect(p1.sessionId, sid);
    expect(p2.sessionId, sid);
  });

  test('空文件 = 没拍上：shot 错误、不入库、批次不结束', () async {
    final sid = await svc.startSession(projectId);
    final errors = <CaptureError>[];
    svc.errorStream.listen(errors.add);
    final empty = File('${tempDir.path}/empty.jpg');
    await empty.writeAsBytes(const []);

    final id = await svc.captureFromFile(projectId, empty.path);
    await settle();

    expect(id, isEmpty);
    expect(errors, hasLength(1));
    expect(errors.first.kind, CaptureErrorKind.shot);
    // 批次没被结束、没被新开 —— 用户还在连续拍节奏里
    expect((await capture.getSession(sid))!.endedAt, isNull);
    expect((await capture.getSession(sid))!.photoCount, 0);
  });

  test('文件缺失 = 没拍上：同样 shot 错误、不建批次', () async {
    final sid = await svc.startSession(projectId);
    final errors = <CaptureError>[];
    svc.errorStream.listen(errors.add);

    final id = await svc.captureFromFile(
      projectId,
      '${tempDir.path}/never_existed.jpg',
    );
    await settle();

    expect(id, isEmpty);
    expect(errors.single.kind, CaptureErrorKind.shot);
    expect((await capture.getSession(sid))!.photoCount, 0);
  });

  test('相册镜像被调用（P4：拍照要进手机相册）', () async {
    await svc.startSession(projectId);
    final shot = await makeShot('mirror.jpg', exifWhen: '2026:10:14 09:25:00');

    final id = await svc.captureFromFile(projectId, shot.path);
    await settle();

    final photo = await capture.getPhoto(id);
    expect(gallery.saves, hasLength(1));
    expect(gallery.saves.single['srcPath'], photo!.filePath);
    expect(
      gallery.saves.single['album'],
      GalleryService.safeFolderName('系统相机拍照测试'),
    );
  });

  test('批次计数流与最后一张流都派发（UI 的数字与胶片条有源）', () async {
    await svc.startSession(projectId);
    final counts = <int>[];
    final lastShots = <String>[];
    svc.photoCountStream.listen(counts.add);
    svc.lastShotStream.listen(lastShots.add);

    final shot = await makeShot('stream.jpg', exifWhen: '2026:10:14 09:26:00');
    final id = await svc.captureFromFile(projectId, shot.path);
    await settle();

    expect(counts, contains(1));
    expect(lastShots, contains(id));
  });

  test('ingest 完立刻 dispose：缩略图派生已落库（直拍一次性服务的收摊语义）', () async {
    // 2026-10-14 真机「最新照片缩略图显示不出来」：系统相机直拍用的是
    // 一次性服务 —— ingest 返回就 dispose。派生（缩略图/镜像/指纹）是
    // fire-and-forget，但 dispose 必须等它们收尾，否则派生被丢掉。
    await svc.startSession(projectId);
    final shot = await makeShot('dispose.jpg', exifWhen: '2026:10:14 09:28:00');
    final id = await svc.captureFromFile(projectId, shot.path);

    // 关键：**不 settle**，直接收摊 —— 派生必须由 dispose 自己等
    await svc.dispose();
    svc = CameraCaptureService(
      capture,
      gallery: gallery,
      prefs: null,
    ); // tearDown 还会 dispose 一次，给个新实例

    final photo = await capture.getPhoto(id);
    expect(photo!.thumbPath, isNotNull,
        reason: 'dispose 不等在途派生 → 缩略图永久缺失（列表停在占位图）');
    expect(photo.thumbPath, isNotEmpty);
  });
}
