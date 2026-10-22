import 'dart:convert';

import 'package:camera/camera.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 相机画幅比例（09-26 老板诉求「画幅比例等设置，提高照片质量」）。
enum CameraAspectRatio {
  /// 4:3 —— 传感器原生比例。映射 [ResolutionPreset.max]，
  /// 像素最大化（主流机型 4000×3000 起），唛头小字的清晰度最好。
  ratio4_3,

  /// 16:9 —— 与预览/屏幕同比例的宽幅。映射 [ResolutionPreset.ultraHigh]。
  ratio16_9,
}

extension CameraAspectRatioX on CameraAspectRatio {
  /// UI 显示名。
  String get label => switch (this) {
        CameraAspectRatio.ratio4_3 => '4:3',
        CameraAspectRatio.ratio16_9 => '16:9',
      };

  /// 设置面板里的说明。
  String get note => switch (this) {
        CameraAspectRatio.ratio4_3 => '传感器原生 · 画质最大化（推荐）',
        CameraAspectRatio.ratio16_9 => '宽幅 · 与屏幕同比例',
      };
}

/// 拍照方式（2026-10-14 v0.22.0「拍照委托系统相机」）。
///
/// - [system]：`ACTION_IMAGE_CAPTURE` 委托系统相机 —— 取景、对焦、变焦、
///   HDR/夜景、音量键快门全部白拿（正是自研相机追不动的那些），
///   拍完原图经 FileProvider 落临时文件，再走存量管线入库。
/// - [builtin]：App 内全屏相机（原有实现，含画幅/闪光/EV/连拍）。
///
/// 为什么保留 [builtin]：委托有 ROM 风险（极少数 ROM 不尊重 EXTRA_OUTPUT
/// 或没有相机 App），现场工具不能有「相机打不开」的单点。默认 [system]。
enum CameraCaptureMode {
  system,
  builtin;

  String get label => switch (this) {
        CameraCaptureMode.system => '系统相机',
        CameraCaptureMode.builtin => '内置相机',
      };

  String get note => switch (this) {
        CameraCaptureMode.system =>
          '用手机自带的相机拍：画质、夜景、抓拍、音量键快门全都有；'
              '拍完自动回到集刻，照片直接进当前批次',
        CameraCaptureMode.builtin =>
          'App 内取景器：支持画幅/闪光/曝光调节与连拍；'
              '取景所见即成片，不受系统相机设置影响',
      };
}

/// 相机偏好（画幅 / 闪光 / 网格线）。
///
/// ── 为什么用 SharedPreferences 而不是 AppSettings 表 ──────────
/// 与相册镜像开关（GalleryService 的 `capture.save_to_gallery`）同域
/// 同款：采集域的轻量偏好走 SP，构造时允许注入 override 便于单测。
/// 整理域的 `organize.auto_group_by_time` 之所以走 AppSettings 表，
/// 是因为 OrganizeRepository 本来就持有 db —— 各随其主，不硬统一。
///
/// ── 与服务的关系 ─────────────────────────────────────────────
/// 画幅与闪光由 CameraCaptureService 在开控制器时读取并应用；
/// 网格线是纯 UI 状态，采集页直接读本类。写入口只有设置面板。
class CameraPreferences {
  CameraPreferences({SharedPreferences? prefs}) : _prefsOverride = prefs;

  final SharedPreferences? _prefsOverride;
  SharedPreferences? _prefsCache;

  Future<SharedPreferences> get _prefs async =>
      _prefsCache ??= _prefsOverride ?? await SharedPreferences.getInstance();

  static const _kAspect = 'camera.aspect_ratio';
  static const _kFlash = 'camera.flash_mode';
  static const _kGrid = 'camera.grid_lines';
  static const _kReview = 'camera.review_after_shot';
  static const _kMode = 'camera.capture_mode';
  static const _kSessionDiag = 'camera.session_diag';

  /// 最近一次连拍会话收图的诊断摘要（v0.24.6）。
  ///
  /// 为什么存在：「拍 3 张只存 1 张」返工过两版，每次都要靠猜——
  /// 这次把原生收图过程的「媒体库几张 / 每轮快照 / 等待多久 / 文件
  /// 兜底补了几张」存下来，「关于」面板直接展示。现场截图即可定位，
  /// 不用教用户抓 logcat。
  Future<String> sessionDiag() async =>
      (await _prefs).getString(_kSessionDiag) ?? '';

  Future<void> saveSessionDiag(String value) async {
    await (await _prefs).setString(_kSessionDiag, value);
  }

  /// 拍照方式（v0.22.0）。**默认系统相机**。
  ///
  /// 老版本升级上来没有这个键 → 回落 [CameraCaptureMode.system]
  /// （新语义是默认值，不是「保持旧行为」—— 旧行为只有一条：内置）。
  Future<CameraCaptureMode> captureMode() async {
    final v = (await _prefs).getString(_kMode);
    return v == CameraCaptureMode.builtin.name
        ? CameraCaptureMode.builtin
        : CameraCaptureMode.system;
  }

  Future<void> setCaptureMode(CameraCaptureMode value) async {
    await (await _prefs).setString(_kMode, value.name);
  }

  /// 画幅。默认 4:3（画质优先 —— 老板 09-26 诉求的直接落点）。
  Future<CameraAspectRatio> aspectRatio() async {
    final v = (await _prefs).getString(_kAspect);
    if (v == CameraAspectRatio.ratio16_9.name) {
      return CameraAspectRatio.ratio16_9;
    }
    // 未知/缺失值一律回落 4:3 —— 老版本升级上来也没有这个键
    return CameraAspectRatio.ratio4_3;
  }

  Future<void> setAspectRatio(CameraAspectRatio value) async {
    await (await _prefs).setString(_kAspect, value.name);
  }

  /// 闪光灯。默认关（§1.3：外包装反光，补光反而更糟 —— 但用户可切）。
  Future<FlashMode> flashMode() async {
    final v = (await _prefs).getString(_kFlash);
    return switch (v) {
      'auto' => FlashMode.auto,
      'always' => FlashMode.always,
      'torch' => FlashMode.torch,
      _ => FlashMode.off,
    };
  }

  Future<void> setFlashMode(FlashMode value) async {
    await (await _prefs).setString(_kFlash, value.name);
  }

  /// 九宫格构图线。默认关（§4.3「不干扰」—— 网格是可选项不是默认项）。
  Future<bool> gridLines() async => (await _prefs).getBool(_kGrid) ?? false;

  Future<void> setGridLines(bool value) async {
    await (await _prefs).setBool(_kGrid, value);
  }

  /// 拍后回看（2026-10-10 v0.19.0）。**默认开**。
  ///
  /// 为什么默认开：拍完那张糊没糊，当场看一眼是系统相机的默认动作 ——
  /// 收工才发现整批糊了，现场一天白跑。关掉留给"节奏优先"的人，
  /// 不是为了让默认值变成关（与相册镜像开关同一取向，纪律 3）。
  Future<bool> reviewAfterShot() async =>
      (await _prefs).getBool(_kReview) ?? true;

  Future<void> setReviewAfterShot(bool value) async {
    await (await _prefs).setBool(_kReview, value);
  }

  // ── 进程被杀的恢复（v0.24.9）──────────────────────────────
  //
  // 拍照期间 App 在系统相机的后台，低内存设备随时可能杀掉进程。重启后
  // 内存全丢：内存里的导航栈（回到项目列表页）、连拍会话的归属（照片
  // 没入库）都靠这两组持久化键找回来。原生侧同时持久化了收图三要素
  // （媒体库基线/起点/目录，SharedPreferences "syscam_pending"）。

  static const _kPendingSession = 'camera.pending_session';
  static const _kLastLocation = 'ui.last_location';
  static const _kLastLocationAt = 'ui.last_location_at';

  /// 记下「一次连拍会话已挂起、归属某项目」。
  ///
  /// 在 invoke `launchSession` **之前**写：invoke 的 future 要等收图完成
  /// 才回来，而被杀发生在等的那段窗口里 —— 写晚了就等于没写。
  Future<void> savePendingSession(String projectId, {String? sessionId}) async {
    await (await _prefs).setString(
      _kPendingSession,
      jsonEncode({
        'projectId': projectId,
        'at': DateTime.now().millisecondsSinceEpoch,
        if (sessionId != null && sessionId.isNotEmpty) 'sessionId': sessionId,
      }),
    );
  }

  /// 只清**属于这一场**的挂起标记（2026-10-21）。
  ///
  /// 两场会话重叠时，旧场 final 不能清掉新场刚写下的标记 —— 用 sessionId
  /// 比对。旧标记没有 id 时，只有调用方也拿不到 id（空串）才清。
  Future<void> clearPendingSessionIfSession(String sessionId) async {
    final prefs = await _prefs;
    final raw = prefs.getString(_kPendingSession);
    if (raw == null) return;
    try {
      final m = jsonDecode(raw);
      final stored = m is Map ? m['sessionId'] : null;
      final match = sessionId.isEmpty
          ? (stored == null || stored == '')
          : stored == sessionId;
      if (match) await prefs.remove(_kPendingSession);
    } catch (_) {
      // 坏数据：拿不到归属，按「调用方没有 id」处理。
      if (sessionId.isEmpty) await prefs.remove(_kPendingSession);
    }
  }

  /// 取走未完结的会话（读后即清，防重复恢复）。无则 null。
  Future<({String projectId, DateTime launchedAt})?> takePendingSession() async {
    final prefs = await _prefs;
    final raw = prefs.getString(_kPendingSession);
    if (raw == null) return null;
    await prefs.remove(_kPendingSession);
    try {
      final m = jsonDecode(raw);
      if (m is! Map) return null;
      final pid = m['projectId'];
      final at = m['at'];
      if (pid is! String || pid.isEmpty || at is! int) return null;
      return (
        projectId: pid,
        launchedAt: DateTime.fromMillisecondsSinceEpoch(at),
      );
    } catch (_) {
      return null;
    }
  }

  /// 直接清挂起标记（正常流程收尾用 —— 拍了/没拍/降级/失败都算「完结」）。
  Future<void> clearPendingSession() async {
    await (await _prefs).remove(_kPendingSession);
  }

  // ── 渐进式收图的已入库登记（v0.24.11）──────────────────────
  //
  // sweep 期间进程被杀 → 重启恢复走的是原生**全量**重收（恢复没有渐进
  // 式可言），首批已入库的照片会被再收一遍 → 项目里出现重复行。
  // 每入库一张就往这个集合里记一条原图路径，恢复时按集合过滤。

  static const _kIngestedPaths = 'camera.ingested_paths';

  /// 记一条「已入库的原图路径」（每张一次，SP 内存缓存，开销可忽略）。
  Future<void> addIngestedSessionPath(String path) async {
    final prefs = await _prefs;
    final cur = prefs.getStringList(_kIngestedPaths)?.toSet() ?? <String>{};
    if (cur.contains(path)) return;
    cur.add(path);
    await prefs.setStringList(_kIngestedPaths, cur.toList());
  }

  /// 取走已入库路径集合并清空（恢复过滤用，读后即清防跨会话串味）。
  Future<Set<String>> takeIngestedSessionPaths() async {
    final prefs = await _prefs;
    final raw = prefs.getStringList(_kIngestedPaths);
    if (raw == null) return const {};
    await prefs.remove(_kIngestedPaths);
    return raw.toSet();
  }

  Future<void> clearIngestedSessionPaths() async {
    await (await _prefs).remove(_kIngestedPaths);
  }

  /// 记「最后在用的项目页路由」+ 时间。
  Future<void> saveLastLocation(String location) async {
    final prefs = await _prefs;
    await prefs.setString(_kLastLocation, location);
    await prefs.setInt(_kLastLocationAt, DateTime.now().millisecondsSinceEpoch);
  }

  Future<void> clearLastLocation() async {
    final prefs = await _prefs;
    await prefs.remove(_kLastLocation);
    await prefs.remove(_kLastLocationAt);
  }

  /// 最后在用的项目页路由；null = 没有（或太久远，由调用方定时效）。
  Future<(String location, DateTime at)?> lastLocation() async {
    final prefs = await _prefs;
    final loc = prefs.getString(_kLastLocation);
    final at = prefs.getInt(_kLastLocationAt);
    if (loc == null || loc.isEmpty || at == null) return null;
    return (loc, DateTime.fromMillisecondsSinceEpoch(at));
  }
}
