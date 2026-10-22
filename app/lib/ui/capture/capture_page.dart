import 'dart:async';
import 'dart:io' show File;

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../app/providers.dart';
import '../../app/theme.dart';
import '../../core/constants.dart';
import '../../core/logger.dart';
import '../../core/sensor_bridge.dart';
import '../../core/volume_key.dart';
import '../../domain/capture/camera_capture_service.dart';
import '../../domain/capture/camera_preferences.dart';
import '../../domain/capture/capture_service.dart';
import '../../domain/capture/gallery_service.dart';
import '../../domain/model/enums.dart';
import '../../domain/model/project_summary.dart';
import 'system_camera_actions.dart';
import 'widgets/film_strip.dart';
import 'widgets/frame_overlay.dart';
import 'widgets/shutter_button.dart';

/// P4 · 采集页 —— 全屏相机，**界面元素只有三个**（§4.3）。
///
/// ═══════════════════════════════════════════════════════════════
/// 这一页的全部设计目标：**不干扰。**
/// ═══════════════════════════════════════════════════════════════
///
/// 反面清单（这一页**不允许**出现的东西）：
///   ✗ 「识别中…」「已归档」「置信度」「候选列表」
///   ✗ 任何与"这张照片属于哪个货品"有关的元素
///   ✗ 任何 loading 转圈（写盘提示只允许是一圈细弧）
///   ✗ 任何 SnackBar / Dialog（唯一例外：存储不足、写盘失败）
///
/// 三条禁令（§5.2）在本页的落点：
///   ① 禁 OCR —— 本文件不 import domain/suggest/（架构校验会验）
///   ② 禁网络 —— 本文件不发起任何请求
///   ③ 禁弹窗 —— 只保留两个**允许**的提示（见 _showBlocker）
class CapturePage extends ConsumerStatefulWidget {
  const CapturePage({
    super.key,
    required this.projectId,
    this.summary,
    this.intoGroupId,
    this.groupSeq,
  });

  final String projectId;

  /// 从工作台带过来的摘要（用于"还没导入清单"的轻微提示）。
  final ProjectSummary? summary;

  /// 非空 = **组内补拍模式**（2026-09-30）：本次会话拍的照片在退出时
  /// 全部挂进这个组。路由 `?group=<id>&gseq=<seq>` 传入。
  ///
  /// 实现说明：快门 id 在本页收集（[capture] 每次返回照片 id），
  /// 退出时随 pop 结果带回，由整理页调 OrganizeRepository 挂组 ——
  /// 采集服务不碰分组（那是整理层的地盘，架构边界）。
  final String? intoGroupId;

  /// 补拍目标的组序号，仅用于顶部横幅文案。
  final int? groupSeq;

  @override
  ConsumerState<CapturePage> createState() => _CapturePageState();
}

class _CapturePageState extends ConsumerState<CapturePage>
    with WidgetsBindingObserver {
  CaptureService? _svc;
  CameraCaptureService? _camera;

  /// 拍照方式（2026-10-14 v0.22.0）。默认系统相机；内置相机是设置回退。
  var _captureMode = CameraCaptureMode.system;

  /// 系统相机启动中（快门忙态）：launch 到 onResult 之间忽略再次点击。
  var _systemLaunching = false;

  /// 本次进入页面已自动拉起过系统相机（2026-10-14 v0.22.1：点拍照 =
  /// 直接进系统相机，不再要求先看发射台再按一次快门）。只自动一次 ——
  /// 拍完回来若再自动拉起，想退出的用户会被"返回→又弹相机"困住；
  /// 回来后继续拍是快门一下的事，可控性优先。
  var _systemAutoLaunched = false;

  var _phase = _Phase.init;
  String? _blocker; // 唯一允许的两种打断：存储不足 / 写盘失败
  var _bursting = false;

  /// 本次连拍是否会锁焦（= 用户点过对焦点）。UI 在连拍条上说明。
  bool _burstLocksFocus = false;
  Offset? _reticle;

  /// 对焦框是否**已合焦**（黄框=对焦中，白框=对上了）。
  ///
  /// 现场快速拍时这是"可以拍了"的唯一信号 —— 没有它，点完屏幕只能靠
  /// 画面自己变清楚来判断，暗处/低对比时那一下很难看出来。
  var _reticleLocked = false;
  var _readyShots = 0; // 首张之前的快门次数（用于"准备中"文案）
  var _sessionStartedAt = DateTime.now();

  // ── 相机控制面状态（09-26 老板诉求：变焦/画幅/闪光/网格）──
  FlashMode _flash = FlashMode.off;
  CameraAspectRatio _aspect = CameraAspectRatio.ratio4_3;
  var _grid = false;
  var _zoom = 1.0;
  var _minZoom = 1.0;
  var _maxZoom = 1.0;
  List<double> _zoomSteps = const [1.0];
  var _backLensCount = 1; // 后置镜头颗数（>1 才有"换广角"这件事）
  var _backLensPosition = 1; // 当前第几颗后置（1 起；0 = 当前是前置）
  double? _pinchBase; // 捏合起点时的倍率
  bool _switching = false; // 正在重建控制器（切画幅）
  String? _hudText; // 临时提示（倍率/闪光/画幅/失败），一抬手就淡出
  Timer? _hudTimer;

  /// 快门黑闪（按下瞬间的物理反馈，见 [_playShutterFlash]）。
  bool _shutterFlash = false;

  /// 拍照指引条是否可见（老板 09-27 诉求）。
  ///
  /// 默认可见，可随手关掉。关掉只是本次进页生效 —— 下次进来还会出现，
  /// 因为"这张该拍什么"是每次作业都要对齐的一件事，不该被永久关掉。
  var _guideVisible = true;

  // ── 拍后回看（2026-10-10 v0.19.0）────────────────────────
  // 非空 = 正在回看刚拍的这张。回看是全屏覆盖层：按"保留"关掉继续拍，
  // 按"重拍"删掉（库行+原图+缩略图+相册镜像）后继续拍。连拍不弹
  // （burst 的 id 走 stream，不经过 [_onShutter] 的回看分支）。
  String? _reviewPhotoId;
  String? _reviewPath;

  /// 重拍删除进行中（防双击连删）。
  var _reviewBusy = false;

  /// 「拍后回看」开关（偏好，默认开；_boot 时读一次）。
  var _reviewEnabled = true;

  // ── 手抖提示（2026-10-10 v0.19.0）────────────────────────
  /// 上次手抖提示的时刻（节流 4s：快门连按时只提示第一次）。
  DateTime? _lastShakeHintAt;

  StreamSubscription<int>? _countSub;
  StreamSubscription<String>? _shotSub;
  StreamSubscription<String>? _thumbSub;
  StreamSubscription<CaptureError>? _errorSub;
  StreamSubscription<CaptureHint>? _hintSub;
  StreamSubscription<Object?>? _volumeKeySub;

  /// 画幅容器（预览区）的定位锚 —— 点击对焦按容器内坐标算。
  final GlobalKey _previewAreaKey = GlobalKey();
  var _sessionCount = 0;
  List<FilmFrame> _frames = const [];

  /// 组内补拍模式：本会话成功入库的照片 id（退出时带回给整理页挂组）。
  final List<String> _groupShots = [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // 采集期锁竖屏：横屏会让单手快门的位置变化，现场不需要。
    SystemChrome.setPreferredOrientations([
      DeviceOrientation.portraitUp,
    ]);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
    unawaited(_boot());
  }

  @override
  void dispose() {
    _hudTimer?.cancel();
    _countSub?.cancel();
    _shotSub?.cancel();
    _thumbSub?.cancel();
    _errorSub?.cancel();
    _hintSub?.cancel();
    // 音量键：cancel 触发原生 onCancel → 音量调节恢复
    _volumeKeySub?.cancel();
    // 加速度计随页面离开立刻停（常开是实打实的耗电，R1b 续航指标）。
    unawaited(ShakeSensor.stop());
    WidgetsBinding.instance.removeObserver(this);
    SystemChrome.setPreferredOrientations(DeviceOrientation.values);
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    // 相机释放必须 await 到底，否则下次进入会拿到"被占用"
    unawaited(_camera?.dispose() ?? Future<void>.value());
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // §8.2「息屏 / 来电 / 切后台」：暂停预览，**保留 session 与计数**。
    // 回来时 resume 同一批次 —— 这是"进度不丢"的关键。
    switch (state) {
      case AppLifecycleState.inactive:
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
        unawaited(_svc?.pauseSession());
        // 后台不采样 —— 加速度计常开耗电，且后台也拍不了照。
        unawaited(ShakeSensor.stop());
      case AppLifecycleState.resumed:
        unawaited(_resume());
        unawaited(ShakeSensor.start());
      case AppLifecycleState.detached:
        break;
    }
  }

  // ─────────────────────────────────────────────────────────
  // 启动
  // ─────────────────────────────────────────────────────────

  Future<void> _boot() async {
    // 拍照方式（2026-10-14 v0.22.0）：默认系统相机，内置是设置回退。
    var mode = CameraCaptureMode.system;
    try {
      mode = await ref.read(cameraPreferencesProvider).captureMode();
    } catch (_) {}
    if (!mounted) return;
    setState(() => _captureMode = mode);

    setState(() => _phase = _Phase.permission);

    // 权限：只在真正需要时才申请（§8.3）。
    // 系统相机路径**不需要** CAMERA —— 相机是系统相机 App 的事，我们只
    // 提供一个它可写的临时文件 URI（白拿的收益：采集少一个运行时权限）。
    if (mode == CameraCaptureMode.builtin) {
      final cam = await Permission.camera.request();
      if (!cam.isGranted) {
        setState(() {
          _phase = _Phase.denied;
        });
        return;
      }
    }

    // 存储预检（§8.2）—— 采集前算，不是写失败才说。
    // 查不到空间时保持沉默（StorageAudit.unknown）。
    setState(() => _phase = _Phase.preflight);
    final audit = await ref.read(storageAuditProvider(widget.projectId).future);
    if (!audit.enough) {
      setState(() {
        _phase = _Phase.blocked;
        _blocker = 'storage';
      });
      return;
    }

    // 相机初始化 —— §8.1「冷启动到可拍摄 ≤ 2.0s」的主要成本
    setState(() => _phase = _Phase.camera);
    try {
      // 直接构造而不是走 captureServiceProvider：本页自己管理生命周期
      // （boot 失败/退出时要 await 释放相机），autoDispose provider 需要
      // 持续 watch 才保活。依赖一件不少 ——
      // gallery：相册镜像（此前这里漏传导致镜像没生效，09-26 修复）；
      // prefs：画幅/闪光偏好。
      final svc = CameraCaptureService(
        ref.read(captureRepositoryProvider),
        gallery: ref.read(galleryServiceProvider),
        prefs: ref.read(cameraPreferencesProvider),
      );
      // 内置路径才开控制器；系统相机路径取景是系统相机的事，服务只为
      // ingest 与批次而存在（不 initialize 也能 startSession / captureFromFile）。
      if (mode == CameraCaptureMode.builtin) {
        await svc.initialize();
        if (!mounted) {
          await svc.dispose();
          return;
        }
      }
      _camera = svc;
      _svc = svc;
      _wireService(svc);

      // 续接或新开批次（两条路径同口径：5 分钟窗内回到采集页 = 同一批）
      await svc.startSession(widget.projectId);
      _sessionStartedAt = DateTime.now();

      var review = true;
      try {
        review = await ref.read(cameraPreferencesProvider).reviewAfterShot();
      } catch (_) {}

      if (mode == CameraCaptureMode.builtin) {
        // 相机控制面初始状态：网格来自偏好，其余从服务同步
        // （initialize 时服务已把画幅/闪光从偏好里读出来并应用）。
        var grid = false;
        try {
          grid = await ref.read(cameraPreferencesProvider).gridLines();
        } catch (_) {}
        if (!mounted) return;
        setState(() {
          _grid = grid;
          _reviewEnabled = review;
          _flash = svc.flashMode;
          _aspect = svc.aspectRatio;
          _syncCameraState(svc);
          _phase = _Phase.ready;
        });
      } else {
        if (!mounted) return;
        setState(() {
          _reviewEnabled = review;
          _phase = _Phase.ready;
        });
        // 方案 D7：进程在系统相机前台被系统杀掉 → 回来补收拍好的那张
        unawaited(_recoverSystemShot());

        // 进入即拍（2026-10-14 v0.22.1，老板反馈"要进入两次"）：点「拍照」
        // 直接进系统相机 —— 发射台不再是必经的一步，只在拍完回来后作为
        // "再拍一张"的操作台出现。只自动一次，防止"返回→又弹相机"困住人。
        if (!_systemAutoLaunched) {
          _systemAutoLaunched = true;
          unawaited(_onSystemShutter(svc));
        }
      }

      // 首帧之后把最近几张读出来（胶片条），**不阻塞首屏**
      unawaited(_refreshFrames());
    } on CameraException catch (e) {
      Log.e('CapturePage', 'camera boot failed: ${e.code}');
      if (!mounted) return;
      setState(() {
        _phase = _Phase.blocked;
        // §8.2「相机被其他 APP 占用」→ 给重试，已拍内容不受影响
        _blocker = 'camera';
      });
    } catch (e) {
      Log.e('CapturePage', 'boot failed', e);
      if (!mounted) return;
      setState(() {
        _phase = _Phase.blocked;
        _blocker = 'camera';
      });
    }
  }

  /// 流的统一接线（2026-10-14 v0.22.0 起两条拍照路径共用）。
  void _wireService(CameraCaptureService svc) {
    _countSub = svc.photoCountStream.listen((n) {
      if (mounted) setState(() => _sessionCount = n);
    });
    _shotSub = svc.lastShotStream.listen((_) => unawaited(_refreshFrames()));
    // 缩略图生成完成也刷一次（2026-10-08）：快门信号到达时 thumbPath 还是
    // NULL，胶片条会一直停在灰块 —— 真机反馈「拍照后缩略图不马上显示」。
    _thumbSub = svc.thumbReadyStream.listen((_) => unawaited(_refreshFrames()));
    // 失败上报（写盘/单张/连拍丢张）—— 静默失败在采集现场等于"照片
    // 凭空少了"。分派见 [_onCaptureError]。
    _errorSub = svc.errorStream.listen(_onCaptureError);
    // 状况提示（弱光等）—— 拍上了但环境值得知道。与错误同用 HUD 展示。
    _hintSub = svc.hintStream.listen((h) {
      if (mounted) _showHudFor(h.hint, const Duration(seconds: 3));
    });

    // 手抖检测：页面可见期间采样（离开/切后台停，见 dispose/生命周期）。
    // 返回 false = 本机没有加速度计，之后 jerk 恒 null，分级闭嘴。
    unawaited(ShakeSensor.start());

    // 音量键快门（2026-10-12 v0.20.0，对标原生标配）：本页 listen 期间
    // 原生拦截音量上下键转发为快门；dispose 取消订阅 → 原生自动恢复
    // 音量调节。系统相机路径下它=「打开系统相机」（相机到前台后音量键
    // 归系统相机管，那是更 native 的快门）。回看层打开时不响应。
    _volumeKeySub = VolumeKeyShutter.events.listen((_) {
      if (_phase == _Phase.ready && _reviewPath == null) {
        unawaited(_onShutter());
      }
    });
  }

  /// 收摊当前服务（切换拍照方式 / 页面退出共用）。
  Future<void> _releaseService() async {
    _countSub?.cancel();
    _countSub = null;
    _shotSub?.cancel();
    _shotSub = null;
    _thumbSub?.cancel();
    _thumbSub = null;
    _errorSub?.cancel();
    _errorSub = null;
    _hintSub?.cancel();
    _hintSub = null;
    _volumeKeySub?.cancel();
    _volumeKeySub = null;
    final cam = _camera;
    _camera = null;
    _svc = null;
    if (cam != null) await cam.dispose();
  }

  /// 方案 D7：补收进程被杀前拍好的那张系统相机照片。
  Future<void> _recoverSystemShot() async {
    final svc = _svc;
    if (svc == null || !SystemCameraLaunch.hasPending) return;
    final id = await recoverPendingSystemShot(
      projectId: widget.projectId,
      svc: svc,
    );
    if (id.isNotEmpty && mounted) {
      _showHudFor('已收下刚才拍好的照片', const Duration(seconds: 3));
      await _maybeShowReview(id);
    }
  }

  /// 切换拍照方式（设置面板）：换路径 = 换引擎，收摊当前服务重走 _boot。
  /// 批次不断 —— startSession 会续接同一个 open 批次（5 分钟窗）。
  Future<void> _switchCaptureMode(CameraCaptureMode mode) async {
    if (mode == _captureMode || _systemLaunching) return;
    await ref.read(cameraPreferencesProvider).setCaptureMode(mode);
    setState(() {
      _captureMode = mode;
      // 切回系统相机 = 重新"进入即拍"（与首次进页同语义）。
      if (mode == CameraCaptureMode.system) _systemAutoLaunched = false;
    });
    await _releaseService();
    await _boot();
  }

  Future<void> _resume() async {
    final c = _camera;
    if (c == null) return;
    try {
      final ctrl = c.controller;
      if (ctrl != null && !ctrl.value.isInitialized) {
        await c.initialize();
      } else {
        await ctrl?.resumePreview();
      }
    } catch (e) {
      Log.w('CapturePage', 'resume failed: $e');
    }
  }

  Future<void> _refreshFrames() async {
    try {
      final rows = await ref
          .read(captureRepositoryProvider)
          .watchLatestThumbs(widget.projectId, limit: 5)
          .first;
      if (!mounted) return;
      setState(() {
        _frames = rows
            .map((p) => FilmFrame(photoId: p.id, thumbPath: p.thumbPath))
            .toList();
      });
    } catch (e) {
      Log.d('CapturePage', 'refreshFrames: $e');
    }
  }

  // ─────────────────────────────────────────────────────────
  // 交互
  // ─────────────────────────────────────────────────────────

  Future<void> _onShutter() async {
    final svc = _svc;
    if (svc == null || _phase != _Phase.ready) return;
    // 系统相机路径（2026-10-14 v0.22.0）：快门 = 拉起系统相机，
    // 拍完回来 ingest。取景/对焦/变焦/音量键全部委托。
    if (_captureMode == CameraCaptureMode.system) {
      await _onSystemShutter(svc);
      return;
    }
    // 快门防抖（2026-10-12 v0.20.0）：上一张还在取帧时，这次点击**静默
    // 忽略**（不是报错）。旧行为下插件抛 CameraException → 上报「这张没
    // 拍上」，快速连点的现场表现就是提示刷屏 + 张数对不上；原生相机的
    // 语义是"上一张还没好就不响应"，但保留一次轻震动表示收到了。
    if (_camera?.isCapturing ?? false) {
      HapticFeedback.selectionClick();
      return;
    }
    HapticFeedback.lightImpact();
    _readyShots++;
    // 黑闪与快门音都放在"按下"这一刻：它们是**按下的反馈**，
    // 放在"落库成功"就晚了半拍（而且落库已改成后台队列）。
    unawaited(_playShutterFlash());

    try {
      final id = await svc.capture(widget.projectId);
      if (id.isEmpty) {
        // 相机偶发失败（对焦未完成等）—— 静默，不打扰。
        Log.d('CapturePage', 'capture returned empty');
      } else {
        if (widget.intoGroupId != null) {
          _groupShots.add(id);
        }
        // 拍后回看（2026-10-10）：单拍才弹，连拍不弹（连拍拍的是同一件
        // 货的不同角度，逐张打断等于把连拍废掉）。开关在偏好里。
        unawaited(_maybeShowReview(id));
      }
    } catch (e) {
      // §8.2「采集过程中真的写失败」→ 暂停采集（少数允许打断的情况）
      if (mounted) {
        setState(() {
          _phase = _Phase.blocked;
          _blocker = 'write';
        });
      }
    }
  }

  /// 系统相机快门（2026-10-14 v0.22.0；v0.24.2 升级为连拍会话）。
  ///
  /// 与内置路径的差别只在「字节从哪来」：取景与成像都在系统相机里完成，
  /// 回来走 [CaptureService.captureFromFile] —— 续接批次、EXIF 时刻、
  /// 原子移动、入库、镜像、缩略图一环不少（存量管线全继承）。
  /// v0.24.2 起会话模式：相机普通模式拉起想拍多少拍多少，按返回一次性
  /// 收图；会话不可用时编排层自动退回单张往返，这里两种结局都按列表收。
  ///
  /// v0.24.11 渐进式收图：原生首批（文件稳定 800ms）交回即开始 ingest，
  /// HUD 随张数走；相机还在写盘的部分由 sweep 后台推送（晚到），HUD 与
  /// 胶片条跟着更新，**最终对账等 sweep 收尾**才下结论 —— 中途看到
  /// 「只存下 M 张」可能是晚到照片还没到，不能提早吓人。
  Future<void> _onSystemShutter(CaptureService svc) async {
    // 忙态防抖：系统相机往返有几秒，这期间的再次点击静默忽略
    // （原生语义：上一张还没回来就不响应），给一次轻震动表示收到。
    if (_systemLaunching) {
      HapticFeedback.selectionClick();
      return;
    }
    HapticFeedback.lightImpact();
    setState(() => _systemLaunching = true);
    // v0.24.4：HUD 改常驻 + 随收图进度刷新。原来「正在打开系统相机…」
    // 只显示 8 秒，多张 ingest 期间界面没有任何反馈 —— 老板反馈
    // 「一次拍多张，很久才进 App」，感知放大器就是这段静默。
    // v0.24.11：文案分阶段（打开相机 → 提示按返回 → 等相机保存 →
    // 收图中已 N 张 → 晚到又收 N 张），用户任何时刻都知道在等什么。
    // v0.24.4：HUD 改常驻 + 随收图进度刷新。原来「正在打开系统相机…」
    // 只显示 8 秒，多张 ingest 期间界面没有任何反馈 —— 老板反馈
    // 「一次拍多张，很久才进 App」，感知放大器就是这段静默。
    // v2（2026-10-22）：同步契约 —— ingest 用本页 svc（晚到轮询也是），
    // lastShotStream 是真进度；结局随函数返回一并确定，无需跨页订阅。
    _showHud('正在打开系统相机…');
    var ingested = 0;
    final progressSub = svc.lastShotStream.listen((_) {
      ingested++;
      if (mounted) _showHud('正在收图… 已 $ingested 张');
    });
    // v0.24.7：相机 App 是**在用户按返回之后**才把最后一张写完盘的
    // （4~8MB 大图 + 低端机，1~3 秒很常见），原生会等文件写完才交回。
    // 这期间 HUD 一直停在「正在打开系统相机…」会让人以为卡死了 ——
    // 2 秒时提示「按返回就收」，5 秒还没动静就明说「相机可能还在保存」。
    final backHint = Timer(const Duration(seconds: 2), () {
      if (mounted && ingested == 0) {
        _showHud('拍完请按返回键 · 照片会自动收进 App');
      }
    });
    final saveHint = Timer(const Duration(seconds: 5), () {
      if (mounted && ingested == 0) {
        _showHud('正在收照片，请稍候…（相机保存有时偏慢）');
      }
    });
    try {
      final (outcome, ids, shotCount) = await runSystemCameraSession(
        ref: ref,
        projectId: widget.projectId,
        svc: svc,
        intoGroupId: widget.intoGroupId,
      );
      if (!mounted) return;
      switch (outcome) {
        case SystemShotOutcome.shot:
          // 直接入库，不弹「保留/重拍」回看（2026-10-14 v0.22.1，老板
          // 反馈"确认两次"）：取景画面用户刚在系统相机里亲眼看过，
          // 拍糊了重拍一张就行 —— 删图入口在整理页，采集期不拦截。
          if (widget.intoGroupId != null) _groupShots.addAll(ids);
          // 入库张数以实测为准（ids 就是真入库的 id）。
          final stored = ids.length;
          if (shotCount > stored) {
            _showHudFor(
              '相机 $shotCount 张 · 只存下 $stored 张 · 缺的可在相册里补收',
              const Duration(seconds: 6),
            );
          } else if (stored > 1) {
            _showHudFor('已收下 $stored 张', const Duration(seconds: 2));
          } else {
            // 单张：ingest 已完成，清掉常驻 HUD（胶片条自己会刷新）
            _hudTimer?.cancel();
            setState(() => _hudText = null);
          }
          unawaited(_refreshFrames());
        case SystemShotOutcome.missed:
          // 静默零（v2）：大概率拍了但一张没收到 —— 必须明说。
          _showHudFor(
            '没收到照片 · 相机里拍的照片仍在系统相册，可从「从相册导入」补收',
            const Duration(seconds: 6),
          );
        case SystemShotOutcome.cancelled:
          // 用户反悔（一张没拍就返回）—— 静默收场；清掉常驻 HUD，
          // 别把「正在打开系统相机…」留在屏幕上。
          _hudTimer?.cancel();
          setState(() => _hudText = null);
        case SystemShotOutcome.noImage:
          _showHudFor('系统相机没有返回原图 · 可重试，或设置里改用内置相机',
              const Duration(seconds: 5));
        case SystemShotOutcome.failed:
          _showHudFor('拍照没成功 · 请再按一次快门', const Duration(seconds: 3));
      }
    } finally {
      backHint.cancel();
      saveHint.cancel();
      await progressSub.cancel();
      if (mounted) setState(() => _systemLaunching = false);
    }
  }

  // ── 手抖提示（2026-10-10 v0.19.0）────────────────────────

  /// 快门按下瞬间 / 连拍开始时查一次抖动。**只有 heavy 才提示** ——
  /// mild 提示是噪音（提示必须可操作，铁律 16），节流 4 秒防快门连按刷屏。
  Future<void> _checkShake() async {
    if (_phase != _Phase.ready) return;
    final level = shakeLevelOf(await ShakeSensor.jerk());
    if (level != ShakeLevel.heavy) return;
    final now = DateTime.now();
    final last = _lastShakeHintAt;
    if (last != null && now.difference(last) < const Duration(seconds: 4)) {
      return;
    }
    _lastShakeHintAt = now;
    if (mounted) {
      _showHudFor('手抖明显 · 画面容易糊，稳一下再按', const Duration(seconds: 2));
    }
  }

  // ── 拍后回看（2026-10-10 v0.19.0）────────────────────────

  /// 拍完弹出原图回看。四个闸门：
  ///  · 连拍不弹（[_onShutter] 之外没有调用点，这里再防一层时序竞态）；
  ///  · 开关关了不弹；
  ///  · 已经在回看不弹（上一张还没决定，又拍了一张 —— 不可能：回看层
  ///    挡住了快门，但防御性保留）；
  ///  · 照片行查不到（异常时序）不弹。
  Future<void> _maybeShowReview(String photoId) async {
    if (!_reviewEnabled || _reviewPhotoId != null) return;
    final photo = await ref.read(captureRepositoryProvider).getPhoto(photoId);
    if (!mounted || photo == null || _reviewPhotoId != null) return;
    setState(() {
      _reviewPhotoId = photoId;
      _reviewPath = photo.filePath;
    });
  }

  /// 「保留」：关掉回看继续拍。
  void _onReviewKeep() {
    setState(() {
      _reviewPhotoId = null;
      _reviewPath = null;
      _reviewBusy = false;
    });
  }

  /// 「重拍」：删掉这张（库行 + 原图 + 缩略图 + 相册镜像）后继续拍。
  ///
  /// 删除复用 [PhotoDeletionService]（整理页同款：事务删行 + 尽力删文件
  /// + 组连带 —— 重拍场景下这张还没归属，连带分支天然为空）。
  /// 相册镜像先删（删完 DB 行文件名就查不到了），失败静默 —— 相册里
  /// 多一张废图，远小于让重拍卡住。
  Future<void> _onReviewRetake() async {
    final id = _reviewPhotoId;
    final path = _reviewPath;
    if (id == null || _reviewBusy) return;
    setState(() => _reviewBusy = true);
    try {
      if (path != null && path.isNotEmpty) {
        try {
          final name = await ref
              .read(captureRepositoryProvider)
              .projectName(widget.projectId);
          await ref.read(galleryServiceProvider).deleteMirror(
                srcPath: path,
                album: GalleryService.safeFolderName(name),
              );
        } catch (e) {
          Log.w('CapturePage', 'mirror delete failed: $e');
        }
      }
      await ref.read(photoDeletionServiceProvider).deletePhoto(id);
      if (mounted) {
        _showHudFor('已删掉，请重拍', const Duration(milliseconds: 900));
      }
    } catch (e) {
      Log.e('CapturePage', 'retake delete failed: $e');
      if (mounted) {
        // 删失败：照片还在库里（删除是事务，行没删成），不能当没拍过 ——
        // 明说并**保留回看层**，让人能再按一次重试。
        _showHudFor('删除失败 · 可再试一次，或退出后在整理页删', const Duration(seconds: 3));
        setState(() => _reviewBusy = false);
      }
      return;
    }
    if (!mounted) return;
    setState(() {
      _reviewPhotoId = null;
      _reviewPath = null;
      _reviewBusy = false;
    });
    unawaited(_refreshFrames());
  }

  void _onBurstStart() {
    final svc = _svc;
    if (svc == null || _phase != _Phase.ready) return;
    setState(() {
      _bursting = true;
      // 点过对焦点 → 连拍会锁焦（同一件货连拍不该中途追焦）。把这件事
      // 说出来：锁焦期间画面不会自动重新对焦，这是"看得见的差异"。
      _burstLocksFocus = _camera?.hasFocusPoint ?? false;
    });
    HapticFeedback.mediumImpact();
    // 连拍开始这一下也查抖动：边走边连拍是最容易整批糊的场景。
    unawaited(_checkShake());

    // 长按连拍：松手即停（用一个可取消的订阅）
    _burstSub?.cancel();
    _burstSub = svc
        .burst(
      widget.projectId,
      count: AppConst.burstMaxPhotos,
      intervalMs: AppConst.burstIntervalMs,
    )
        .listen(
      (id) {
        // 组内补拍：连拍同样要收集（退出时挂组）
        if (widget.intoGroupId != null && id.isNotEmpty) {
          _groupShots.add(id);
        }
      },
      onError: (Object e) => Log.w('CapturePage', 'burst: $e'),
      cancelOnError: false,
    );
  }

  StreamSubscription<String>? _burstSub;

  void _onBurstEnd() {
    _burstSub?.cancel();
    _burstSub = null;
    if (mounted) setState(() => _bursting = false);
  }

  Future<void> _onTapPreview(TapDownDetails d) async {
    final svc = _svc;
    // 坐标按**画幅容器**算（v0.20.0）：预览不再铺满全屏，容器内局部坐标
    // / 容器尺寸 = 相机收到的归一化对焦点。旧实现按全屏算，预览被裁剪时
    // 点击位置与相机对焦点是错位的。
    final box =
        _previewAreaKey.currentContext?.findRenderObject() as RenderBox?;
    if (svc == null || box == null) return;
    final size = box.size;
    final x = (d.localPosition.dx / size.width).clamp(0.0, 1.0);
    final y = (d.localPosition.dy / size.height).clamp(0.0, 1.0);

    setState(() {
      _reticle = Offset(x, y);
      _reticleLocked = false; // 黄框 = 对焦中
    });
    await svc.focusAt(x, y);
    if (!mounted) return;

    // 合焦完成 → 白框。focusAt 是 await 到 AF 动作下发/完成的，
    // 所以这个切换与镜头真的合上焦是同一时刻（不是定时假象）。
    setState(() => _reticleLocked = true);

    // 指示方块自动消失
    await Future<void>.delayed(const Duration(milliseconds: 620));
    if (mounted) setState(() => _reticle = null);
  }

  Future<void> _onFinish() async {
    HapticFeedback.mediumImpact();
    // 落盘已改成后台队列：点"结束采集"时可能还有几张在写。如实说明，
    // 否则用户会看到"结束按钮按下去没反应"（实际是在等写盘）。
    final pend = _camera?.pendingSaves ?? 0;
    if (pend > 0) {
      _showHudFor('正在保存 $pend 张…', const Duration(seconds: 2));
    }
    await _svc?.endSession();
    if (!mounted) return;
    // 组内补拍：把本会话拍到的照片 id 带回给整理页（由它挂组）。
    // 普通采集 pop(null)，调用方按"没有补拍"处理。
    final shots =
        widget.intoGroupId == null ? null : List<String>.of(_groupShots);
    Navigator.of(context).pop(shots);
  }

  // ─────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: switch (_phase) {
        _Phase.denied => _buildDenied(),
        _Phase.blocked => _buildBlocked(),
        _ => _buildCamera(),
      },
    );
  }

  // ── 相机界面：三样元素 ────────────────────────────────────
  Widget _buildCamera() {
    final ctrl = _camera?.controller;
    // 系统相机路径（2026-10-14 v0.22.0）：取景委托系统相机，本页没有
    // App 内取景器，相机控制面（变焦/画幅/闪光/EV）全部不出现。
    final systemMode = _captureMode == CameraCaptureMode.system;

    return Stack(
      fit: StackFit.expand,
      children: [
        // 系统相机路径：这块区域是「发射台说明」—— 取景是系统相机的事，
        // 这里只讲清「点快门会发生什么、拍完照片去哪」。
        if (systemMode)
          _buildLaunchpad()
        // 预览（双指变焦在外层；点击对焦在画幅容器内，见 _buildPreview）。
        // 切画幅重建控制器期间先收黑，避免 CameraPreview 拿着已 dispose
        // 的控制器绘制。
        else if (_switching)
          const ColoredBox(color: Colors.black)
        else
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onScaleStart: _phase == _Phase.ready ? _onScaleStart : null,
            onScaleUpdate: _phase == _Phase.ready ? _onScaleUpdate : null,
            onScaleEnd: _phase == _Phase.ready ? _onScaleEnd : null,
            child: _buildPreview(ctrl),
          ),

        // 变焦档位 + 换镜头（右侧竖排）—— 仅内置路径。
        //
        // 显示条件（2026-10-09 放宽）：原来只认"能放大"（max>1.05），
        // 于是"只能缩小"的广角机型（min<1、max≈1）整条档位都不出现 ——
        // 真机反馈「看不到 0.6x」的一种可能。现在能放大**或**能缩小都出。
        if (!systemMode &&
            !_switching &&
            _phase == _Phase.ready &&
            (_zoomSteps.length > 1 || _backLensCount > 1))
          Positioned(
            right: 10,
            top: 0,
            bottom: 240,
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  // 换镜头：数码变焦只能放大，"看得更全"必须换一颗镜头。
                  // 文案只说第几颗，不写"广角"—— 副摄是广角还是长焦由
                  // 硬件决定，猜错了就是把人往更窄的画面上引。
                  if (_backLensCount > 1)
                    _ZoomStepButton(
                      label: '镜头$_backLensPosition',
                      active: false,
                      onTap: () => unawaited(_onSwitchBackLens()),
                    ),
                  if (_zoomSteps.length > 1)
                    for (final step in _zoomSteps.reversed)
                      _ZoomStepButton(
                        label: '${_zoomStepLabel(step)}x',
                        active: (_zoom - step).abs() < 0.05,
                        onTap: () => unawaited(_applyZoomStep(step)),
                      ),
                ],
              ),
            ),
          ),

        // 拍照指引（老板 09-27 诉求：采集界面要有拍照指引 + 照片要求说明）。
        //
        // 位置压在顶部条下方、HUD 上方 —— 三者互不遮挡：
        // 指引常驻（一句话），HUD 是瞬时的操作反馈，取景优先不被破坏。
        // 可随手关掉（_guideVisible），关掉后本页只剩快门。
        // 组内补拍横幅（2026-09-30）：本页唯一的"模式提示"。
        // 补拍模式下替换掉拍照指引条 —— 用户已经知道该拍什么（他正在
        // 给一个具体的组补照片），这时指引条反而占地方。
        if (_phase == _Phase.ready && widget.intoGroupId != null)
          Positioned(
            top: 64,
            left: 12,
            right: 12,
            child: _GlassChip(
              child: Text(
                '补拍：照片将在退出后加入第 ${widget.groupSeq ?? '?'} 组',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          )
        else if (_phase == _Phase.ready && _guideVisible)
          Positioned(
            top: 64,
            left: 12,
            right: 12,
            child: _ShootingGuideBar(
              onOpenRequirements: _openPhotoRequirements,
              onDismiss: () => setState(() => _guideVisible = false),
            ),
          ),

        // 临时提示（倍率 / 闪光 / 画幅）：一抬手就淡出，不驻留
        if (_hudText != null)
          Positioned(
            top: 112,
            left: 0,
            right: 0,
            child: Center(
              child: _GlassChip(
                child: Text(
                  _hudText!,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
          ),

        // 顶部：返回 + 张数 + 时长 + 闪光 + 相机设置
        Positioned(
          top: 0,
          left: 0,
          right: 0,
          child: SafeArea(child: _buildTopBar()),
        ),

        // 底部：胶片条 + 快门 + 结束
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: SafeArea(child: _buildBottomBar()),
        ),

        // 初始化遮罩（只在准备阶段出现，且不含任何进度文案以外的信息）
        if (_phase != _Phase.ready) _buildPreparingOverlay(),

        // 快门黑闪：盖在最上层（连准备遮罩之上），只有 120ms。
        // IgnorePointer —— 它绝不能吃掉这一下点击，否则会吞掉连拍。
        if (_shutterFlash)
          const Positioned.fill(
            child: IgnorePointer(
              child: ColoredBox(color: Color(0x24000000)),
            ),
          ),

        // 拍后回看（2026-10-10）：真正的最顶层。全屏覆盖，快门被挡住
        // —— 回看没决定之前不能拍下一张（这层存在的意义）。
        if (_reviewPath != null)
          _ReviewOverlay(
            path: _reviewPath!,
            busy: _reviewBusy,
            onKeep: _onReviewKeep,
            onRetake: _onReviewRetake,
          ),
      ],
    );
  }

  /// 发射台（2026-10-14 v0.22.0 系统相机路径的中屏）。
  ///
  /// 取景与成像都在系统相机里，这块地方不摆取景器，只负责说清三件事：
  /// 快门会打开什么、拍完照片去哪、现在这批拍了多少。胶片条在底栏，
  /// 拍后回看走 [_ReviewOverlay] —— 存量 UI 一件不浪费。
  Widget _buildLaunchpad() {
    return const ColoredBox(
      color: Colors.black,
      child: SafeArea(
        child: Padding(
          // 上让顶栏、下让底栏（它们在 Stack 里浮在这层之上）
          padding: EdgeInsets.fromLTRB(28, 110, 28, 230),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.photo_camera_outlined,
                  size: 42, color: Color(0x66FFFFFF)),
              SizedBox(height: 14),
              Text(
                '拍照由系统相机完成',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
              SizedBox(height: 10),
              Text(
                '照片已入库当前批次。继续拍就再按一下快门 —— '
                '系统相机会再次打开，取景、对焦、变焦、夜景都能用；'
                '拍完回到这里，不用确认。',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Color(0x99FFFFFF),
                  fontSize: 13,
                  height: 1.55,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildPreview(CameraController? ctrl) {
    if (ctrl == null || !ctrl.value.isInitialized) {
      return const ColoredBox(color: Colors.black);
    }

    // ── 所见即所得（2026-10-12 v0.20.0，老板真机反馈「成片比取景远」）──
    //
    // 旧实现把预览流 FittedBox(cover) 无脑铺满 ~20:9 屏幕：4:3 的流被
    // 横向裁掉约 2/3（取景只看到中间 1/3），而成片是 4:3 全幅不裁 ——
    // 拍到的永远比看到的多，取景完全失真。
    //
    // 新结构（原生相机「比例选择」的标准做法）：
    //   全屏黑底 → 画幅容器（AspectRatio = 成片比例）→ 流在容器内 cover。
    // 插件层 Preview 与 ImageCapture 共用同一 ResolutionSelector
    // （android_camera_camerax.dart:381-404，同源同 FOV），所以
    // 容器裁剪与成片裁剪**同向同量**（4:3 两边不裁；16:9 两边各裁 25%）
    // —— 容器里看到的 = 成片里拍到的，严格成立，且不受机型流比例影响。
    // 黑边区留给 UI（顶栏/档位/快门），网格与对焦框按画幅区域画。
    final ar =
        _aspect == CameraAspectRatio.ratio16_9 ? 9.0 / 16.0 : 3.0 / 4.0;

    return Stack(
      fit: StackFit.expand,
      children: [
        const ColoredBox(color: Colors.black),
        Center(
          key: _previewAreaKey,
          child: AspectRatio(
            aspectRatio: ar,
            child: ClipRect(
              child: Stack(
                fit: StackFit.expand,
                children: [
                  // 流在容器内 cover —— 容器比例=画幅比例，裁剪=成片裁剪
                  FittedBox(
                    fit: BoxFit.cover,
                    child: SizedBox(
                      width: ctrl.value.previewSize?.height ?? 1,
                      height: ctrl.value.previewSize?.width ?? 1,
                      child: CameraPreview(ctrl),
                    ),
                  ),
                  // 取景框 / 网格：按画幅区域画（不再画到黑边上）
                  if (_phase == _Phase.ready || _phase == _Phase.camera)
                    FrameOverlay(visible: !_bursting, grid: _grid),
                  // 对焦指示：坐标 = 容器内归一化 = 相机真实坐标
                  if (_reticle != null)
                    FocusReticle(offset: _reticle!, locked: _reticleLocked),
                  // 点击对焦：局部坐标按容器算（旧实现按全屏算，预览被
                  // 裁剪时点击位置与相机收到的对焦点是错位的）
                  if (_phase == _Phase.ready)
                    GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTapDown: _onTapPreview,
                      child: const SizedBox.expand(),
                    ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  /// 顶部只有三样：返回、张数、时长（§4.3 的"顶部只有张数+时长"）。
  Widget _buildTopBar() {
    final elapsed = DateTime.now().difference(_sessionStartedAt);

    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 12, 8),
      child: Row(
        children: [
          _GlassIconButton(
            icon: Icons.arrow_back_ios_new,
            onTap: _onFinish,
          ),
          const SizedBox(width: 6),
          // 张数 —— 最有存在感的一个数字，也是唯一的"成就感"来源
          _GlassChip(
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.photo_camera, size: 14, color: Colors.white),
                const SizedBox(width: 6),
                Text(
                  '$_sessionCount',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    fontFeatures: [FontFeature.tabularFigures()],
                  ),
                ),
                const SizedBox(width: 4),
                const Text(
                  '张',
                  style: TextStyle(color: Color(0xCCFFFFFF), fontSize: 11.5),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          if (_bursting)
            _GlassChip(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.burst_mode, size: 14, color: Colors.white),
                  const SizedBox(width: 4),
                  Text(
                    _burstLocksFocus ? '连拍中 · 锁焦' : '连拍中',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 11.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            )
          else
            _GlassChip(
              child: Text(
                _fmtElapsed(elapsed),
                style: const TextStyle(
                  color: Color(0xCCFFFFFF),
                  fontSize: 11.5,
                  fontFeatures: [FontFeature.tabularFigures()],
                ),
              ),
            ),
          const Spacer(),
          // 闪光 + 相机设置（09-26 老板诉求「变焦/画幅/提高照片质量」）。
          // 克制：只有两颗小钮，面板里也只放「画幅/网格线」两个真正
          // 影响拍摄的选项 —— 识别/归属相关入口仍然禁止出现在采集期（§5.2）。
          //
          // 闪光仅内置路径（v0.22.0）：系统相机的闪光是它自己的事，
          // 且它有更完整的 HDR/夜景，不需要我们在这里给一个半吊子开关。
          if (_captureMode == CameraCaptureMode.builtin) ...[
            _GlassIconButton(
              icon: switch (_flash) {
                FlashMode.off => Icons.flash_off,
                FlashMode.auto => Icons.flash_auto,
                _ => Icons.flash_on,
              },
              onTap: _phase == _Phase.ready ? _cycleFlash : null,
              compact: true,
            ),
            const SizedBox(width: 8),
          ],
          _GlassIconButton(
            icon: Icons.tune,
            onTap: _phase == _Phase.ready ? _openCameraSettings : null,
            compact: true,
          ),
        ],
      ),
    );
  }

  /// 底部：胶片条（左）+ 相册钮 + 快门（中）+ 结束（右）。
  Widget _buildBottomBar() {
    final ready = _phase == _Phase.ready;

    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 18),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0x00000000), Color(0x99000000)],
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // 胶片条
          if (_frames.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: FilmStrip(items: _frames),
            ),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              // ── 导入入口已移走（老板 09-27 拍板）──
              // 从相册导入 / 微信导入 现在并排在**采集 Tab** 上，
              // 与「进入全屏相机」同一级。这一页只留快门。
              // 理由：举着手机取景时，"选文件"的操作会挡住画面，
              // 也会让人在现场犹豫"现在该拍还是该导"。
              const Spacer(),
              ShutterButton(
                enabled: ready && !_systemLaunching,
                busy: _bursting || _systemLaunching,
                onTap: _onShutter,
                // 半按对焦：手指落下就开始对焦，抬手时焦距已合上 → 快门更快
                // 顺手查一次抖动：按下这刻手在抖，拍出来就是糊的。
                // 仅内置路径（v0.22.0）：系统相机路径下取景不在 App 里，
                // 预对焦/手抖都无从谈起（系统相机自己会追焦）——
                // 三个回调签名非空，系统路径传 no-op。
                onPressDown: _captureMode == CameraCaptureMode.system
                    ? () {}
                    : () {
                        unawaited(_svc?.prepareFocus());
                        unawaited(_checkShake());
                      },
                // 连拍（长按）仅内置路径：系统相机往返有几秒，
                // 400ms×N 的 App 内连拍在该路径下物理不存在，
                // 替代是「拍完一张再拍一张」的循环（发射台快门）。
                onLongPressStart: _captureMode == CameraCaptureMode.system
                    ? () {}
                    : _onBurstStart,
                onLongPressEnd: _captureMode == CameraCaptureMode.system
                    ? () {}
                    : _onBurstEnd,
                onSwitchCamera: _captureMode == CameraCaptureMode.system
                    ? () {}
                    : () => unawaited(_onSwitchCamera()),
              ),
              const Spacer(),
              // 曝光补偿：左右两个小钮。不做滑杆 —— 滑杆要看着调。
              // 仅内置路径（v0.22.0）：系统相机的曝光/HDR 是它自己的事。
              if (_captureMode == CameraCaptureMode.builtin)
                Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _GlassIconButton(
                      icon: Icons.exposure_plus_1,
                      onTap: ready ? () => _nudgeExposure(0.5) : null,
                      compact: true,
                    ),
                    const SizedBox(height: 8),
                    _GlassIconButton(
                      icon: Icons.exposure_minus_1,
                      onTap: ready ? () => _nudgeExposure(-0.5) : null,
                      compact: true,
                    ),
                  ],
                ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              HoldToFinishButton(onFinish: _onFinish),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _nudgeExposure(double d) async {
    final svc = _svc;
    if (svc is! CameraCaptureService) return;
    final next = (svc.exposure + d).clamp(-4.0, 4.0);
    await svc.setExposureCompensation(next);
    if (mounted) setState(() {});
  }

  // ── 变焦（双指捏合 + 档位按钮）──────────────────────────

  void _onScaleStart(ScaleStartDetails d) {
    if (d.pointerCount < 2) return;
    _pinchBase = _camera?.zoom;
  }

  void _onScaleUpdate(ScaleUpdateDetails d) {
    // 只认双指：单指拖动是误触，不是变焦。
    if (d.pointerCount < 2 || _pinchBase == null) return;
    final svc = _camera;
    if (svc == null || _switching) return;
    unawaited(svc.setZoom(_pinchBase! * d.scale));
    _showHud('${svc.zoom.toStringAsFixed(1)}x');
    if (mounted) setState(() => _zoom = svc.zoom);
  }

  void _onScaleEnd(ScaleEndDetails d) {
    _pinchBase = null;
    _scheduleHudHide();
  }

  Future<void> _applyZoomStep(double step) async {
    final svc = _camera;
    if (svc == null || _switching) return;
    HapticFeedback.selectionClick();
    await svc.setZoom(step);
    _showHud('${svc.zoom.toStringAsFixed(1)}x');
    if (mounted) setState(() => _zoom = svc.zoom);
  }

  // ── 闪光 / 切镜头 / 设置面板 ──────────────────────────────

  Future<void> _cycleFlash() async {
    final svc = _camera;
    if (svc == null || _switching) return;
    final next = switch (svc.flashMode) {
      FlashMode.off => FlashMode.auto,
      FlashMode.auto => FlashMode.torch,
      _ => FlashMode.off,
    };
    HapticFeedback.selectionClick();
    await svc.setFlashMode(next);
    _showHud(switch (next) {
      FlashMode.off => '闪光灯 关',
      FlashMode.auto => '闪光灯 自动',
      _ => '闪光灯 常亮',
    });
    if (mounted) setState(() => _flash = next);
  }

  Future<void> _onSwitchCamera() async {
    final svc = _camera;
    if (svc == null || _switching) return;
    await svc.switchCamera();
    if (!mounted) return;
    // 换镜头后变焦范围可能不同（广角/长焦），重算档位（服务已回 1x）
    setState(() => _syncCameraState(svc));
  }

  /// 把服务的镜头能力同步到界面（开相机 / 换镜头 / 换画幅共用一份）。
  ///
  /// 三处各写一遍必然漂移 —— 真机反馈「看不到 0.6x」就是这类漂移的后果：
  /// 只同步了 max 没同步 min，档位条按 max 判断，广角机型整条消失。
  void _syncCameraState(CameraCaptureService svc) {
    _zoom = svc.zoom;
    _minZoom = svc.minZoom;
    _maxZoom = svc.maxZoom;
    _zoomSteps = CameraCaptureService.zoomStepsFor(svc.minZoom, svc.maxZoom);
    _backLensCount = svc.backLensCount;
    _backLensPosition = svc.backLensPosition;
  }

  /// 换一颗后置镜头（广角/副摄）。
  ///
  /// 与快门旁的前后翻转不同：这个只在后置里循环，意图是"换视野"而不是
  /// "换方向"。切镜头必须重建控制器（几百毫秒黑屏），所以用与换画幅
  /// 相同的全屏提示，避免人以为卡死。
  Future<void> _onSwitchBackLens() async {
    final svc = _camera;
    if (svc == null || _switching) return;
    HapticFeedback.selectionClick();
    setState(() {
      _switching = true;
      _hudText = '正在切换镜头…';
    });
    try {
      final ok = await svc.switchBackLens();
      if (!mounted) return;
      if (!ok) {
        // 只有一颗后置：明确说出原因和下一步，而不是按了没反应。
        setState(() {
          _switching = false;
          _hudText = '本机只有一颗后置镜头';
        });
        _scheduleHudHide();
        return;
      }
      setState(() {
        _syncCameraState(svc);
        _switching = false;
        _hudText = '后置镜头 $_backLensPosition / $_backLensCount';
      });
      _scheduleHudHide();
    } catch (e) {
      Log.e('CapturePage', 'back lens switch failed: $e');
      if (!mounted) return;
      setState(() {
        _switching = false;
        _hudText = '镜头切换失败，请重试';
      });
      _scheduleHudHide();
    }
  }

  Future<void> _openCameraSettings() async {
    if (_switching) return;
    // EV 支持：min==max 说明机型不支持曝光补偿（_openController 探测），
    // 面板里隐藏滑块而不是显示一个推不动的杆。
    final cam = _camera;
    final evSupported = cam != null && cam.maxEv > cam.minEv;
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      builder: (_) => _CameraSettingsSheet(
        aspect: _aspect,
        grid: _grid,
        review: _reviewEnabled,
        ev: evSupported ? cam.exposure : null,
        lens: _lensSummary(),
        mode: _captureMode,
        onGridChanged: _setGrid,
        onReviewChanged: _setReview,
        onEvChanged: _setExposure,
        onAspectSelected: _onAspectRatioSelected,
        // 切换拍照方式 = 换引擎：先收面板，再由 _switchCaptureMode
        // 收摊旧服务、按新路径重走 _boot（批次不断，5 分钟窗续接）。
        onModeSelected: (m) {
          Navigator.of(context).pop();
          unawaited(_switchCaptureMode(m));
        },
      ),
    );
  }

  Future<void> _setExposure(double value) async {
    final cam = _camera;
    if (cam == null) return;
    await cam.setExposureCompensation(value);
    if (mounted) setState(() {});
  }

  Future<void> _setGrid(bool value) async {
    try {
      await ref.read(cameraPreferencesProvider).setGridLines(value);
    } catch (_) {}
    if (mounted) setState(() => _grid = value);
  }

  Future<void> _setReview(bool value) async {
    try {
      await ref.read(cameraPreferencesProvider).setReviewAfterShot(value);
    } catch (_) {}
    if (mounted) setState(() => _reviewEnabled = value);
  }

  /// 设置面板选了新画幅：先收面板 → 全屏提示 → 重建控制器。
  Future<void> _onAspectRatioSelected(CameraAspectRatio ratio) async {
    final svc = _camera;
    if (svc == null || _switching || ratio == _aspect) return;
    Navigator.of(context).pop();
    setState(() {
      _switching = true;
      _hudText = '正在切换画幅…';
    });
    try {
      await svc.setAspectRatio(ratio);
      if (!mounted) return;
      setState(() {
        _aspect = ratio;
        _syncCameraState(svc);
        _switching = false;
        _hudText = '已切换为 ${ratio.label}';
      });
      _scheduleHudHide();
    } catch (e) {
      Log.e('CapturePage', 'aspect switch failed: $e');
      if (!mounted) return;
      // 服务内部已做过一次兜底重开；到这里说明两次都失败，
      // 相机大概率被占用 —— 提示后仍允许返回/重试拍摄。
      setState(() {
        _switching = false;
        _hudText = '画幅切换失败';
      });
      _scheduleHudHide();
    }
  }

  void _showHud(String text) {
    _hudTimer?.cancel();
    if (mounted) setState(() => _hudText = text);
  }

  /// 失败提示（2026-10-09 拍照链路体检）。
  ///
  /// 三种失败给三种**可执行**的下一步 —— 只说"失败"等于让人猜：
  ///  · 写盘失败 → 停采集（全屏红条，已有）—— 数据在丢，不能装作没事；
  ///  · 这张没拍上 → 「再按一次快门」；
  ///  · 连拍丢张 → 说清丢了多少、能怎么补。
  void _onCaptureError(CaptureError e) {
    Log.w('CapturePage', 'capture error ${e.kind.name}: ${e.message}');
    if (!mounted) return;
    switch (e.kind) {
      case CaptureErrorKind.write:
        setState(() {
          _phase = _Phase.blocked;
          _blocker = 'write';
        });
      case CaptureErrorKind.shot:
      case CaptureErrorKind.burstDropped:
        // 读数类提示要停留得够久（900ms 一闪而过等于没说）。
        _showHudFor(e.hint, const Duration(seconds: 3));
    }
  }

  /// 停留更久的 HUD（错误类提示要读得完，900ms 一闪而过等于没说）。
  void _showHudFor(String text, Duration keep) {
    _hudTimer?.cancel();
    setState(() => _hudText = text);
    _hudTimer = Timer(keep, () {
      if (mounted) setState(() => _hudText = null);
    });
  }

  /// 快门黑闪（拍照的"实感"来源之一）。
  ///
  /// 为什么需要：按下去只有按钮内芯缩一下，画面毫无反应 —— 现场戴手套
  /// 单手操作时，人判断"这一下有没有拍上"靠的是**听到咔嚓 + 画面一暗**
  /// 这两个物理反馈。系统相机都有这一下。
  ///
  /// 只暗 14%、120ms：够被感知，又不至于让人以为按错了重拍。
  Future<void> _playShutterFlash() async {
    if (!mounted) return;
    setState(() => _shutterFlash = true);
    await Future<void>.delayed(const Duration(milliseconds: 120));
    if (mounted) setState(() => _shutterFlash = false);
  }

  void _scheduleHudHide() {
    _hudTimer?.cancel();
    _hudTimer = Timer(const Duration(milliseconds: 900), () {
      if (mounted) setState(() => _hudText = null);
    });
  }

  /// 档位文本：整数倍率不带小数点（1x / 2x / 5x）。
  String _zoomStepLabel(double step) => step == step.roundToDouble()
      ? step.toInt().toString()
      : step.toStringAsFixed(1);

  /// 镜头能力一句话（相机设置面板）。
  ///
  /// 必须写它，是因为"少了 0.6x"这件事**静默发生**时，人只会以为 App
  /// 没做。这里把机器的真实能力摆出来，并给出下一步：能换镜头就说换
  /// 镜头，不能换就明说"没有广角镜头"并指向后退取景 / 相册导入。
  String _lensSummary() {
    final range = _minZoom < 0.95
        ? '${_minZoom.toStringAsFixed(1)}x–${_maxZoom.toStringAsFixed(1)}x'
        : (_maxZoom > 1.05
            ? '1x–${_maxZoom.toStringAsFixed(1)}x（只能放大）'
            : '不支持变焦');
    if (_backLensCount > 1) {
      return '后置镜头 $_backLensCount 颗，当前第 $_backLensPosition 颗；'
          '变焦 $range。右侧「镜头」按钮换一颗 —— 视野更宽的通常是副摄。';
    }
    return '后置镜头 1 颗，变焦 $range。本机没有可切换的广角镜头，'
        '要拍得更全请后退取景，或用系统相机的广角拍完从「相册导入」进来。';
  }

  /// 打开「照片要求说明」（老板 09-27 诉求：采集界面要有照片要求说明）。
  ///
  /// 用底部弹层而不是 AlertDialog：单手可读、往下滑就走，
  /// 不会像对话框那样把取景整个盖住还要找按钮。
  ///
  /// ⚠️ 「采集期禁弹窗」禁的是**系统主动打断**（"识别中""已归档"之类）。
  ///    这里是用户自己点开的说明，属于用户发起的动作，不违反该纪律。
  Future<void> _openPhotoRequirements() async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (ctx) => const _PhotoRequirementsSheet(),
    );
  }

  // ── 准备中（不带任何"识别"字样）──────────────────────────
  Widget _buildPreparingOverlay() {
    final text = switch (_phase) {
      // 系统相机路径（v0.22.0）不申请相机权限 —— intent 委托，
      // 这一态只持续到偏好读完（几毫秒），文案也说实际发生的事。
      _Phase.permission => _captureMode == CameraCaptureMode.system
          ? '正在准备…'
          : '正在申请相机权限…',
      _Phase.preflight => '正在检查存储空间…',
      _Phase.camera => '正在启动相机…',
      _ => '',
    };
    return ColoredBox(
      color: Colors.black87,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(
              width: 26,
              height: 26,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: Colors.white70),
            ),
            const SizedBox(height: 14),
            Text(
              text,
              style: const TextStyle(color: Colors.white70, fontSize: 13.5),
            ),
            if (_readyShots == 0 && _phase == _Phase.camera) ...[
              const SizedBox(height: 6),
              const Text(
                '首次启动约 1~2 秒',
                style: TextStyle(color: Colors.white38, fontSize: 11.5),
              ),
            ],
          ],
        ),
      ),
    );
  }

  // ── 权限被拒 ──────────────────────────────────────────────
  Widget _buildDenied() {
    return _BlockerScaffold(
      icon: Icons.no_photography_outlined,
      title: '需要相机权限',
      body: '拍照是这个工具的核心功能，没有相机权限就无法工作。\n'
          '请在系统设置里允许「相机」权限后重试。',
      primaryLabel: '去设置',
      onPrimary: () async {
        await openAppSettings();
        if (mounted) setState(() => _phase = _Phase.init);
        unawaited(_boot());
      },
      secondaryLabel: '返回',
      onSecondary: () => Navigator.of(context).pop(),
    );
  }

  // ── 打断：只允许这两种（§8.2）─────────────────────────────
  Widget _buildBlocked() {
    if (_blocker == 'storage') {
      return _BlockerScaffold(
        icon: Icons.sd_card_alert_outlined,
        title: '存储空间不足',
        body: '已拍的照片都安全保存在本机。\n'
            '建议先到「交付」生成一次包并上传/分享，或清理空间后再继续拍摄。',
        secondaryLabel: '返回',
        onSecondary: () => Navigator.of(context).pop(),
      );
    }
    if (_blocker == 'write') {
      return _BlockerScaffold(
        icon: Icons.error_outline,
        title: '照片写入失败',
        body: '已拍的内容没有丢失，采集已暂停。\n'
            '请检查存储空间是否耗尽，然后重试。',
        primaryLabel: '重试',
        onPrimary: () {
          setState(() => _phase = _Phase.init);
          unawaited(_boot());
        },
        secondaryLabel: '返回',
        onSecondary: () => Navigator.of(context).pop(),
      );
    }
    // 相机被占用 / 初始化失败
    return _BlockerScaffold(
      icon: Icons.videocam_off_outlined,
      title: '相机无法启动',
      body: '可能是其他应用正在使用相机。\n'
          '请关闭其他相机类应用后重试。已拍的照片不受影响。',
      primaryLabel: '重试',
      onPrimary: () {
        setState(() => _phase = _Phase.init);
        unawaited(_boot());
      },
      secondaryLabel: '返回',
      onSecondary: () => Navigator.of(context).pop(),
    );
  }

  static String _fmtElapsed(Duration d) {
    final h = d.inHours;
    final m = d.inMinutes % 60;
    final s = d.inSeconds % 60;
    String two(int v) => v.toString().padLeft(2, '0');
    return h > 0 ? '${two(h)}:${two(m)}:${two(s)}' : '${two(m)}:${two(s)}';
  }
}

// ═══════════════════════════════════════════════════════════════
// 内部组件
// ═══════════════════════════════════════════════════════════════

enum _Phase { init, permission, preflight, camera, ready, denied, blocked }

class _GlassChip extends StatelessWidget {
  const _GlassChip({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.34),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: Colors.white.withValues(alpha: 0.18)),
      ),
      child: child,
    );
  }
}

class _GlassIconButton extends StatelessWidget {
  const _GlassIconButton({
    required this.icon,
    this.onTap,
    this.compact = false,
  });

  final IconData icon;
  final VoidCallback? onTap;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final side = compact ? 42.0 : AppTheme.minTapTarget;
    return InkWell(
      onTap: onTap,
      customBorder: const CircleBorder(),
      child: Container(
        width: side,
        height: side,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Colors.black.withValues(alpha: 0.34),
          border: Border.all(color: Colors.white.withValues(alpha: 0.2)),
        ),
        child: Icon(
          icon,
          size: compact ? 19 : 21,
          color: Colors.white.withValues(alpha: onTap == null ? 0.32 : 0.94),
        ),
      ),
    );
  }
}

/// 打断页（§8.2）。
///
/// 这是采集页**唯一允许的"对话框"**，而且它不是 Dialog ——
/// 它是替换整个界面的全屏页，因为现场的一秒钟都不该被浮层遮挡取景。
class _BlockerScaffold extends StatelessWidget {
  const _BlockerScaffold({
    required this.icon,
    required this.title,
    required this.body,
    this.primaryLabel,
    this.onPrimary,
    this.secondaryLabel,
    this.onSecondary,
  });

  final IconData icon;
  final String title;
  final String body;
  final String? primaryLabel;
  final VoidCallback? onPrimary;
  final String? secondaryLabel;
  final VoidCallback? onSecondary;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(26),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 46, color: AppTheme.amber),
            const SizedBox(height: 16),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 18,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 10),
            Text(
              body,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Color(0xCCFFFFFF),
                fontSize: 13.5,
                height: 1.7,
              ),
            ),
            const SizedBox(height: 22),
            if (primaryLabel != null)
              FilledButton(
                onPressed: onPrimary,
                style: FilledButton.styleFrom(
                  backgroundColor: AppTheme.accent,
                  minimumSize: const Size(160, AppTheme.minTapTarget),
                ),
                child: Text(primaryLabel!),
              ),
            if (secondaryLabel != null) ...[
              const SizedBox(height: 8),
              TextButton(
                onPressed: onSecondary,
                child: Text(
                  secondaryLabel!,
                  style: const TextStyle(color: Color(0xAAFFFFFF)),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 采集期的批次类型（相册导入提示用）。
extension CaptureSourceLabel on CaptureSource {
  String get captureLabel => switch (this) {
        CaptureSource.camera => '现场拍摄',
        CaptureSource.album => '相册导入',
      };
}

/// 变焦档位按钮（右侧竖排小圆钮，46 ≥ 44 最小触控）。
class _ZoomStepButton extends StatelessWidget {
  const _ZoomStepButton({
    required this.label,
    required this.active,
    required this.onTap,
  });

  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        onTap: onTap,
        customBorder: const CircleBorder(),
        child: Container(
          width: 46,
          height: 46,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: active
                ? AppTheme.accent.withValues(alpha: 0.9)
                : Colors.black.withValues(alpha: 0.38),
            border: Border.all(
              color:
                  active ? Colors.white : Colors.white.withValues(alpha: 0.3),
              width: active ? 1.6 : 1,
            ),
          ),
          child: Center(
            child: Text(
              label,
              style: TextStyle(
                color: Colors.white,
                fontSize: 12.5,
                fontWeight: active ? FontWeight.w800 : FontWeight.w600,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 相机设置面板（09-26）：只有「画幅 / 网格线」两样。
///
/// 闪光不在面板里 —— 它是拍摄中的高频动作，放顶栏一键循环。
/// 选画幅后立即关面板，由页面全屏提示重建进度（控制器先关后开，
/// 约几百毫秒）；网格线即时生效并落偏好。
/// EV 滑块：自持本地状态 —— 拖动时流畅更新本地值，onChangeEnd 才落
/// 服务（每次 onChanged 都走通道下发会刷屏）。sheet 是 StatelessWidget，
/// 若滑块直接读父状态，拖动中父级不重建 → 滑块跳回原位。
class _EvSlider extends StatefulWidget {
  const _EvSlider({required this.initial, required this.onChanged});

  final double initial;
  final Future<void> Function(double) onChanged;

  @override
  State<_EvSlider> createState() => _EvSliderState();
}

class _EvSliderState extends State<_EvSlider> {
  late double _value = widget.initial;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 2),
          child: Row(
            children: [
              const Icon(Icons.exposure, size: 16, color: Colors.white70),
              const SizedBox(width: 8),
              const Text(
                '曝光补偿',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 14.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const Spacer(),
              Text(
                '${_value > 0 ? '+' : ''}${_value.toStringAsFixed(1)} EV',
                style: TextStyle(
                  color: _value == 0
                      ? Colors.white.withValues(alpha: 0.5)
                      : AppTheme.accent,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ),
        Slider(
          value: _value.clamp(-4.0, 4.0),
          min: -4,
          max: 4,
          divisions: 16,
          label: '${_value > 0 ? '+' : ''}${_value.toStringAsFixed(1)}',
          onChanged: (v) => setState(() => _value = v),
          onChangeEnd: (v) => widget.onChanged(v),
        ),
      ],
    );
  }
}

class _CameraSettingsSheet extends StatelessWidget {
  const _CameraSettingsSheet({
    required this.aspect,
    required this.grid,
    required this.review,
    required this.ev,
    required this.lens,
    required this.mode,
    required this.onGridChanged,
    required this.onReviewChanged,
    required this.onEvChanged,
    required this.onAspectSelected,
    required this.onModeSelected,
  });

  final CameraAspectRatio aspect;
  final bool grid;

  /// 拍后回看开关（2026-10-10 v0.19.0）。
  final bool review;

  /// 手动曝光补偿（EV）。null = 当前机型不支持（隐藏滑块）。
  final double? ev;

  /// 本机镜头能力一句话（为什么有/没有 0.6x，下一步怎么办）。
  final String lens;

  /// 拍照方式（2026-10-14 v0.22.0）。两条路径共用本面板。
  final CameraCaptureMode mode;
  final Future<void> Function(bool) onGridChanged;
  final Future<void> Function(bool) onReviewChanged;
  final Future<void> Function(double) onEvChanged;
  final void Function(CameraAspectRatio) onAspectSelected;

  /// 切换拍照方式：调用方负责收摊旧引擎并按新路径重走 _boot。
  final void Function(CameraCaptureMode) onModeSelected;

  @override
  Widget build(BuildContext context) {
    final builtin = mode == CameraCaptureMode.builtin;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Container(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 14),
          decoration: BoxDecoration(
            color: const Color(0xF7141B26),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: Colors.white.withValues(alpha: 0.12)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '相机设置',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                builtin
                    ? '画幅影响照片的像素与比例，记住选择，下次拍摄仍生效。'
                    : '拍照由系统相机完成 —— 画质、夜景、抓拍、音量键'
                        '快门用的都是系统相机的能力，拍完自动回到集刻入库。',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.55),
                  fontSize: 12,
                ),
              ),
              const SizedBox(height: 12),
              // 拍照方式（2026-10-14 v0.22.0）：放最前面 —— 它决定下面
              // 哪些行还有意义。切换立即生效（收摊旧引擎重走启动）。
              for (final m in CameraCaptureMode.values)
                _CaptureModeOption(
                  mode: m,
                  selected: m == mode,
                  onTap: () => onModeSelected(m),
                ),
              if (builtin) ...[
                const Divider(color: Colors.white12, height: 22),
                for (final r in CameraAspectRatio.values)
                  _AspectOption(
                    ratio: r,
                    selected: r == aspect,
                    onTap: () => onAspectSelected(r),
                  ),
              ],
              const Divider(color: Colors.white12, height: 22),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                value: review,
                onChanged: (v) => onReviewChanged(v),
                activeColor: AppTheme.accent,
                title: const Text(
                  '拍后回看',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 14.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                subtitle: Text(
                  '仅内置相机路径生效；系统相机拍完直接入库不打断'
                  '（画面刚在系统相机里看过）',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.55),
                    fontSize: 12,
                  ),
                ),
              ),
              // 以下都是内置路径专属：系统相机路径下取景不在 App 里，
              // 网格/EV/镜头能力都归系统相机管。
              if (builtin) ...[
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  value: grid,
                  onChanged: (v) => onGridChanged(v),
                  activeColor: AppTheme.accent,
                  title: const Text(
                    '九宫格构图线',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 14.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  subtitle: Text(
                    '辅助对准水平与三分位，仅取景显示，不进照片',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.55),
                      fontSize: 12,
                    ),
                  ),
                ),
                // 手动曝光补偿（2026-10-12 v0.20.0）：暗处压亮 / 反光包装
                // 压暗。服务 API 早已存在（自动补偿叠加在其上）；机型不支持
                // 时（_minEv==_maxEv）不显示滑块。
                if (ev != null)
                  _EvSlider(
                    initial: ev!,
                    onChanged: onEvChanged,
                  ),
                const SizedBox(height: 4),
                Text(
                  lens,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.55),
                    fontSize: 12,
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  '对焦：镜头连续自动追焦；手指按下快门的瞬间就开始对焦，'
                  '抬手即拍（现场快拍不用等）。想指定焦点就点一下取景框 —— '
                  '黄框是对焦中，转白框就是对上了。',
                  style: TextStyle(
                    color: Colors.white54,
                    fontSize: 12,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// 拍照方式选项行（2026-10-14 v0.22.0）。
class _CaptureModeOption extends StatelessWidget {
  const _CaptureModeOption({
    required this.mode,
    required this.selected,
    required this.onTap,
  });

  final CameraCaptureMode mode;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
        child: Row(
          children: [
            Icon(
              selected ? Icons.radio_button_checked : Icons.radio_button_unchecked,
              size: 18,
              color: selected ? AppTheme.accent : const Color(0x66FFFFFF),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    mode.label,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 14.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    mode.note,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.55),
                      fontSize: 12,
                      height: 1.4,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AspectOption extends StatelessWidget {
  const _AspectOption({
    required this.ratio,
    required this.selected,
    required this.onTap,
  });

  final CameraAspectRatio ratio;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 4),
        child: Row(
          children: [
            Icon(
              selected ? Icons.radio_button_checked : Icons.radio_button_off,
              size: 20,
              color: selected ? AppTheme.accent : Colors.white54,
            ),
            const SizedBox(width: 12),
            Text(
              ratio.label,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 15,
                fontWeight: FontWeight.w700,
                fontFeatures: [FontFeature.tabularFigures()],
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                ratio.note,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.6),
                  fontSize: 12.5,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 拍照指引 + 照片要求说明（老板 2026-09-27 诉求）
//
// 要求写成常量数据而不是散在 Text 里：指引条（一句话）与说明弹层
// （完整版）共用同一份来源，不会出现两处说法不一致。
// ═══════════════════════════════════════════════════════════════

/// 一条拍照要求。
class _GuideRule {
  const _GuideRule(this.icon, this.text);

  final IconData icon;
  final String text;
}

/// 预检照片要求 —— 与货品清单有关，收工后要按编码对应。
const _precheckRules = <_GuideRule>[
  _GuideRule(Icons.straighten_outlined, '远景一张：把货品整体和堆放位置拍进去'),
  _GuideRule(Icons.qr_code_2_outlined, '近景一张：对准编码 / 唛头，字迹要能看清'),
  _GuideRule(Icons.crop_free, '拍全：外包装、唛头、数量标识尽量在同一张里'),
  _GuideRule(Icons.wb_sunny_outlined, '光线均匀，避免逆光和反光糊掉标签'),
  _GuideRule(Icons.report_problem_outlined, '破损、变形、水湿要单独补拍一张'),
];

/// 监装照片要求 —— 记录装柜过程，与货品清单无关。
const _supervisionRules = <_GuideRule>[
  _GuideRule(Icons.inventory_2_outlined, '空箱一张：装货前的箱体内部'),
  _GuideRule(Icons.density_medium_outlined, '半载一张：装到一半时的堆放状态'),
  _GuideRule(Icons.done_all_outlined, '满载一张：装满后的整体与加固情况'),
  _GuideRule(Icons.lock_outlined, '封条：封条号要拍清楚'),
  _GuideRule(Icons.local_shipping_outlined, '车号 / 箱号：车牌与集装箱号各一张'),
];

/// 指引条 —— 常驻一句话 + 「要求」入口 + 关闭。
///
/// 一句话就够了：现场举着手机，没人会读完一整页说明；
/// 想看完整要求的人点「要求」，那是一个底部弹层（往下滑即走）。
class _ShootingGuideBar extends StatelessWidget {
  const _ShootingGuideBar({
    required this.onOpenRequirements,
    required this.onDismiss,
  });

  final VoidCallback onOpenRequirements;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    return _GlassChip(
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.tips_and_updates_outlined,
              size: 14, color: Color(0xCCFFFFFF)),
          const SizedBox(width: 6),
          const Flexible(
            child: Text(
              '远景看整体 · 近景拍清编码 —— 一件拍完再拍下一件',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: Colors.white, fontSize: 12, height: 1.3),
            ),
          ),
          const SizedBox(width: 2),
          InkWell(
            onTap: onOpenRequirements,
            borderRadius: BorderRadius.circular(12),
            child: const Padding(
              padding: EdgeInsets.symmetric(horizontal: 7, vertical: 4),
              child: Text(
                '要求',
                style: TextStyle(
                  color: AppTheme.accent,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  decoration: TextDecoration.underline,
                  decorationColor: AppTheme.accent,
                ),
              ),
            ),
          ),
          InkWell(
            onTap: onDismiss,
            customBorder: const CircleBorder(),
            child: const Padding(
              padding: EdgeInsets.all(3),
              child: Icon(Icons.close, size: 13, color: Colors.white54),
            ),
          ),
        ],
      ),
    );
  }
}

/// 「照片要求说明」底部弹层。
///
/// 用弹层而不是对话框：单手可读、往下滑就走，不会像对话框那样
/// 把取景整个盖住还要找按钮（现场不想被卡住）。
class _PhotoRequirementsSheet extends StatelessWidget {
  const _PhotoRequirementsSheet();

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints:
          BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.78),
      decoration: const BoxDecoration(
        color: Color(0xFF171A1F),
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 8),
            Container(
              width: 34,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.28),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(height: 10),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                children: [
                  Icon(Icons.rule_outlined, size: 18, color: AppTheme.accent),
                  SizedBox(width: 8),
                  Text(
                    '照片要求',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 4),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
                children: [
                  const _RuleSection(
                    title: '预检照片',
                    hint: '与货品清单有关，收工后按编码对应',
                    rules: _precheckRules,
                  ),
                  const SizedBox(height: 14),
                  const _RuleSection(
                    title: '监装照片',
                    hint: '记录装柜过程，与清单无关',
                    rules: _supervisionRules,
                  ),
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.06),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: const Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '拍的时候不用分',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        SizedBox(height: 6),
                        Text(
                          '预检和监装怎么分，收工后在「整理」页整组一选就行 —— '
                          '现场只需要把该拍的都拍进去。\n'
                          '每件货 2 张（一远一近）；拿不准就多拍一张，'
                          '不用的照片整理时可以标掉，不会进交付包。',
                          style: TextStyle(
                            color: Colors.white70,
                            fontSize: 12.5,
                            height: 1.7,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RuleSection extends StatelessWidget {
  const _RuleSection({
    required this.title,
    required this.hint,
    required this.rules,
  });
  final String title;
  final String hint;
  final List<_GuideRule> rules;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              title,
              style: const TextStyle(
                color: AppTheme.accent,
                fontSize: 13.5,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                hint,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.45),
                  fontSize: 11.5,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        for (final r in rules)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(r.icon, size: 16, color: Colors.white70),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    r.text,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      height: 1.5,
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// 拍后回看覆盖层（2026-10-10 v0.19.0）。
///
/// 全屏黑底 + 原图 contain + 「重拍 / 保留」。它是 Stack 最顶层，
/// 出现期间快门被物理挡住 —— "上一张还没决定"时不能拍下一张，
/// 否则重拍的语义（删掉这张重拍一张）就乱了。
///
/// 原图加载纪律（铁律 13）：`cacheWidth` 限定解码宽度（1440 ≈ 屏幕宽的
/// 3 倍余量），绝不让一张 12MP 原图整幅解码进内存 —— 回看是高频动作，
/// 连拍几十次就是几十次全图解码，低配机直接 OOM。
class _ReviewOverlay extends StatelessWidget {
  const _ReviewOverlay({
    required this.path,
    required this.busy,
    required this.onKeep,
    required this.onRetake,
  });

  final String path;
  final bool busy;
  final VoidCallback onKeep;
  final VoidCallback onRetake;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.black.withValues(alpha: 0.94),
      child: SafeArea(
        child: Column(
          children: [
            const Padding(
              padding: EdgeInsets.only(top: 14, bottom: 6),
              child: Text(
                '拍好了吗？',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const Text(
              '重拍会删掉这张（含相册里的副本），拍糊 / 拍漏就重来',
              style: TextStyle(color: Colors.white38, fontSize: 11.5),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                // 双指放大核对细节（2026-10-12 v0.20.0）：唛头小字拍清
                // 没拍清，当场要能放大看 —— 这是取证刚需，原生相机都有。
                child: InteractiveViewer(
                  maxScale: 4,
                  child: Center(
                    child: Image.file(
                      File(path),
                      cacheWidth: 1440,
                      fit: BoxFit.contain,
                      // 原图文件异常（被清/占用）不该把采集页卡死 —— 给一句
                      // 说明，人可以选"保留"继续干活，之后在整理页处理。
                      errorBuilder: (_, __, ___) => const Text(
                        '照片文件读取失败\n仍会保留在相册整理中',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Colors.white54, fontSize: 13),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 4, 24, 18),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: busy ? null : onRetake,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: const Color(0xFFFF6B6B),
                        side: const BorderSide(color: Color(0xFFFF6B6B)),
                        minimumSize: const Size(0, AppTheme.minTapTarget),
                      ),
                      icon: const Icon(Icons.replay_outlined, size: 20),
                      label: const Text('重拍', style: TextStyle(fontSize: 15)),
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: busy ? null : onKeep,
                      style: FilledButton.styleFrom(
                        backgroundColor: AppTheme.accent,
                        minimumSize: const Size(0, AppTheme.minTapTarget),
                      ),
                      icon: const Icon(Icons.check_outlined, size: 20),
                      label: const Text('保留', style: TextStyle(fontSize: 15)),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
