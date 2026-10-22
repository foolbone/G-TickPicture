import 'dart:async';
import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart' show Offset;
import 'package:flutter/services.dart' show MethodChannel;

import '../../core/async_limiter.dart';
import '../../core/constants.dart';
import '../../core/device_tier.dart';
import '../../core/logger.dart';
import '../../core/perf_bridge.dart';
import '../../core/serial_queue.dart';
import '../../data/fs/photo_exif.dart';
import '../../data/fs/photo_file_sink.dart';
import '../../data/fs/project_paths.dart';
import '../../data/repo/capture_repository.dart';
import '../model/enums.dart';
import 'camera_preferences.dart';
import 'capture_service.dart';
import 'gallery_service.dart';

/// M2 实现：把 [CaptureService] 的契约落到真实相机上。
///
/// ── 本类最重要的性质：它**不知道货品的存在** ─────────────────
/// 整个文件没有一处引用 `Item` / `AssignService` / `suggest*`。
/// 归属发生在整理阶段，采集期连"想写归属"的语法都写不出来。
/// 这不是纪律问题，是 import 结构决定的（tools/check_architecture.ps1 会验）。
///
/// ── 三条禁令（§5.2）────────────────────────────────────────
///   ❌ 禁 OCR     —— 不 import domain/suggest/
///   ❌ 禁网络     —— 除 WebDAV 外本类不发起任何请求；此处没有任何 HTTP
///   ❌ 禁弹窗     —— 本类不持有 BuildContext，物理上无法弹窗
///
/// 采集页 UI 只从流里读进度，所有"需要理解的信息"都留给整理阶段。
///
/// ── 相机控制面（09-26 老板诉求「变焦 / 画幅比例 / 提高照片质量」）──
///   · 变焦   —— setZoom + min/max 探测（不支持变焦的镜头回退 [1,1]）
///   · 画幅   —— CameraAspectRatio → ResolutionPreset 映射（preset 只能
///     在控制器初始化时给定，切换画幅必须重建控制器）
///   · 闪光   —— 用户可切（off/auto/torch），默认仍 off（§1.3 反光理由）
///   · 偏好   —— 画幅/闪光持久化在 CameraPreferences（SP），网格线
///     是纯 UI 状态不经过本类。
class CameraCaptureService implements CaptureService {
  /// [gallery] 可空 —— 单测里不注入就完全不触发相册逻辑；
  /// 运行时由 provider 传入（默认开：P4 老板诉求「拍照要进手机相册」）。
  ///
  /// [prefs] 同理可空：null = 全部用默认值且不持久化（单测/老路径）。
  CameraCaptureService(this._repo,
      {GalleryService? gallery, CameraPreferences? prefs})
      : _gallery = gallery,
        _prefs = prefs;

  final CaptureRepository _repo;

  /// 相册镜像（P4）。null = 未注入（测试）。
  final GalleryService? _gallery;

  /// 相机偏好（09-26）。null = 不读不写偏好。
  final CameraPreferences? _prefs;

  /// 项目 → 相册子目录名 的缓存。项目名作业期不会变。
  final Map<String, String> _albumCache = {};

  /// 缩略图并发闸门（2026-09-29 性能排查）。
  ///
  /// 导入 N 张时旧代码对每张都 `unawaited(_enrich(...))` —— N 个整图解码
  /// 同时开跑，低配机内存直接触顶。闸门把并发压到设备档次允许的值，
  /// 排队而非丢弃（一张都不会少生成，只是不一起上）。
  final AsyncLimiter _thumbLimiter =
      AsyncLimiter(DeviceTier.current.thumbConcurrency);

  /// 在途派生任务（缩略图 / 相册镜像 / 指纹）。
  ///
  /// 派生是 fire-and-forget（**必须**是：绝不拖住下一张快门），但**必须
  /// 登记**：系统相机直拍路径（v0.22.2）用的是一次性服务 —— ingest 完
  /// 立刻 `dispose`，派生被中途丢掉，症状就是「最新照片缩略图显示不出来」
  /// （2026-10-14 真机）。[dispose] 会 await 这里全部收尾，与
  /// `[_sink.drain]` 同一套语义：**释放前把在途的活干完**。
  final Set<Future<void>> _derived = <Future<void>>{};

  /// 跑一个派生任务并登记（失败只记日志：各自由 backfill* 补救）。
  void _derive(Future<void> Function() task) {
    final f = task();
    _derived.add(f);
    unawaited(f
        .catchError((Object e) => Log.w('Capture', 'derived task failed: $e'))
        .whenComplete(() => _derived.remove(f)));
  }

  CameraController? _controller;
  CameraDescription? _description;
  List<CameraDescription> _cameras = const [];
  var _lensIndex = 0;

  String? _sessionId;
  var _sessionCount = 0;
  var _nextSeq = 0;

  double _exposure = 0;
  Offset? _focusPoint;

  // ── 暗光自动曝光补偿（2026-10-10 v0.19.0「HDR 的能力内等价物」）──
  //
  // 为什么不是 HDR：camera 包的 Dart API 没有 HDR/RAW 开关（插件架构
  // 限制，升版本也拿不到 —— 2026-10-10 已核实 camera 0.12.x 要 Dart 3.9+，
  // 且 Dart 层依旧不暴露）。等价物是真实相机参数：拍完从缩略图量出
  // 平均亮度（PerfBridge 顺算，零额外解码），暗了就自动加曝光补偿，
  // 下一张直接受益 —— 也就是"半自动的 AE 微调"，与用户手动补偿并存。
  //
  // 取证边界：只动**相机参数**（改变下一张的成像），绝不改已拍的文件
  // —— 已落盘的原图一个像素都不许动。

  /// 当前自动补偿档（EV，0 = 没加）。叠加在用户手动 [_exposure] 之上。
  double _autoEv = 0;

  /// 设备曝光补偿能力（EV 范围与步长）。max<=step<=0 视为不支持。
  double _minEv = 0;
  double _maxEv = 0;
  double _evStep = 0;

  /// 弱光提示节流：连拍同一暗场景会连续量出暗图，90 秒内只提示一次。
  DateTime? _lastLowLightHintAt;

  final _hintController = StreamController<CaptureHint>.broadcast();

  /// 状况提示流（弱光等）。与 [errorStream] 的区别见 [CaptureHint]。
  Stream<CaptureHint> get hintStream => _hintController.stream;

  /// 预对焦节流窗口 —— 详见 [prepareFocus]。
  static const Duration prepareFocusThrottle = Duration(milliseconds: 350);

  DateTime? _lastPrepareAt;

  /// 画幅。默认 4:3（画质优先）。
  CameraAspectRatio _aspect = CameraAspectRatio.ratio4_3;

  /// 闪光。默认 off（§1.3：外包装反光，补光反而更糟）。
  FlashMode _flash = FlashMode.off;

  /// 变焦：当前值与镜头能力范围。不支持变焦时 [1,1]，UI 据此隐藏档位。
  double _zoom = 1.0;
  double _minZoom = 1.0;
  double _maxZoom = 1.0;

  final _countController = StreamController<int>.broadcast();
  final _lastShotController = StreamController<String>.broadcast();
  final _thumbReadyController = StreamController<String>.broadcast();
  final _errorController = StreamController<CaptureError>.broadcast();
  var _capturing = false;
  var _disposed = false;

  /// 落盘 + 入库的串行队列（2026-10-09 拍照流水线）。
  ///
  /// 队列保证 seq 与入库顺序严格一致（并发写会乱序），也保证
  /// `endSession`/`dispose` 前能把已拍到的张全部落完。
  final SerialQueue _sink = SerialQueue();

  /// 本次连拍累计丢张数。连拍结束才上报 —— 逐张报会刷屏。
  var _burstDropped = 0;

  /// 连拍期间是否已把焦点锁住（结束时要恢复自动对焦）。
  var _burstFocusLocked = false;

  @override
  Stream<CaptureError> get errorStream => _errorController.stream;

  /// 还在写盘/入库的张数。UI 用它显示"正在保存…"。
  int get pendingSaves => _sink.pending;

  /// 用户是否手动指定过对焦点。连拍时据此决定要不要锁焦（并在 UI 上说明）。
  bool get hasFocusPoint => _focusPoint != null;

  // ─────────────────────────────────────────────────────────
  // 生命周期
  // ─────────────────────────────────────────────────────────

  bool get isInitialized => _controller?.value.isInitialized ?? false;

  CameraController? get controller => _controller;

  CameraDescription? get description => _description;

  /// 当前曝光补偿（供 UI 显示）。
  double get exposure => _exposure;

  /// 曝光补偿能力（UI 据此决定显示/隐藏手动 EV 滑块）。
  double get minEv => _minEv;
  double get maxEv => _maxEv;

  /// 对焦/测光点（预览坐标 0~1），供 UI 画小方块。null = 无。
  Offset? get focusPoint => _focusPoint;

  /// 新照片落盘的通知（采集页用它触发缩略图刷新）。
  @override
  Stream<String> get lastShotStream => _lastShotController.stream;

  /// 某张照片的**缩略图已生成**的通知（2026-10-08 真机反馈修复）。
  ///
  /// 为什么必须单独有一条：[lastShotStream] 在**入库瞬间**就发了，而那时
  /// `thumbPath` 还是 NULL（缩略图是异步补的）。采集页胶片条只听
  /// lastShot 的话，刷出来的永远是灰块 —— 之后缩略图好了也没人再通知它，
  /// 表现就是「拍照后的缩略图没有马上显示出来」。
  Stream<String> get thumbReadyStream => _thumbReadyController.stream;

  // ── 相机控制面状态（UI 只读；写走对应方法）────────────────

  /// 当前变焦倍率。
  double get zoom => _zoom;

  /// 镜头最小变焦倍率。
  double get minZoom => _minZoom;

  /// 镜头最大变焦倍率（== min 时表示不支持变焦）。
  double get maxZoom => _maxZoom;

  /// 当前画幅。
  CameraAspectRatio get aspectRatio => _aspect;

  /// 当前闪光模式。
  FlashMode get flashMode => _flash;

  // ── 镜头（2026-10-09：0.6x 的真身是"另一颗后置镜头"）──────
  //
  // 数码变焦只能放大，视野变宽**只能靠换镜头**。超广角在 Android 上有
  // 两种暴露方式：①聚合进主摄（这时主摄 minZoom 会 <1，走变焦档位即可）；
  // ②独立成一颗 camera（这时它出现在 availableCameras 里，必须**切镜头**
  // 才能用上）。真机反馈「看不到 0.6x」的设备属于后者（或压根没有广角），
  // 所以这里把"后置镜头名单"如实交给界面。

  /// 后置镜头在枚举表里的下标（按系统枚举顺序）。
  List<int> get backLensIndices => _backLensIndicesOf(_cameras);

  /// 后置镜头数量。1 = 只有主摄（没有可换的广角）。
  int get backLensCount => backLensIndices.length;

  /// 当前用的第几颗后置镜头（1 起）。当前是前置时返回 0。
  int get backLensPosition {
    final i = backLensIndices.indexOf(_lensIndex);
    return i < 0 ? 0 : i + 1;
  }

  /// 是否还有另一颗后置镜头可切（广角/副摄）。
  bool get hasAlternateBackLens => backLensCount > 1;

  /// 切到下一颗后置镜头（循环）。false = 本机只有一颗后置，没得切。
  ///
  /// 与 [switchCamera] 的区别：后者在**全部**镜头里循环（会切到前置），
  /// 这个只在后置里走 —— "我要看得更全"不需要在前置上绕一圈。
  Future<bool> switchBackLens() async {
    final next = nextBackLensIndex(_cameras, _lensIndex);
    if (next < 0) return false;
    _lensIndex = next;
    _description = _cameras[next];
    await _openController(_description!);
    return true;
  }

  static List<int> _backLensIndicesOf(List<CameraDescription> cameras) => [
        for (var i = 0; i < cameras.length; i++)
          if (cameras[i].lensDirection == CameraLensDirection.back) i,
      ];

  /// 下一个后置镜头下标；没有可切的（后置 < 2 颗）返回 -1。
  ///
  /// 当前是前置时回到第一颗后置 —— 用户点"换镜头"是想继续拍背面场景。
  @visibleForTesting
  static int nextBackLensIndex(List<CameraDescription> cameras, int current) {
    final backs = _backLensIndicesOf(cameras);
    if (backs.length < 2) return -1;
    final cur = backs.indexOf(current);
    return cur < 0 ? backs.first : backs[(cur + 1) % backs.length];
  }

  /// 打开相机。
  ///
  /// ⚠️ 相机初始化是采集页"冷启动到可拍摄 ≤ 2.0s"（§8.1）的主要成本。
  /// 这里只做必须的事：枚举设备 → 初始化预览。DB、胶片条、存储预检
  /// 都排在它后面（由 UI 层并发调度，本类不主动做）。
  Future<void> initialize({bool preferBack = true}) async {
    try {
      // 偏好先于控制器：画幅决定 preset，闪光在 _openController 里重放。
      // 读失败不阻塞开相机 —— 回落默认值（4:3 / off）。
      final prefs = _prefs;
      if (prefs != null) {
        try {
          _aspect = await prefs.aspectRatio();
          _flash = await prefs.flashMode();
        } catch (e) {
          Log.w('Capture', 'load camera prefs failed: $e');
        }
      }

      _cameras = await availableCameras();
      if (_cameras.isEmpty) {
        // 设备上没有可用相机 —— 这在采集场景是"先装错了机器"，
        // 不是可恢复状态，直接抛出由 UI 全屏说明（§8.2 唯一允许的打断）。
        throw CameraException('no_camera', '设备上没有可用相机');
      }

      _lensIndex = _pickLens(preferBack);
      _description = _cameras[_lensIndex];
      await _openController(_description!);
      Log.i('Capture', 'camera ready: ${_description?.name}');
    } on CameraException catch (e) {
      // §8.2「相机被其他 APP 占用」由 UI 层展示与重试，这里只上抛。
      Log.e('Capture', 'initialize failed: ${e.code} / ${e.description}');
      rethrow;
    }
  }

  int _pickLens(bool preferBack) {
    final want =
        preferBack ? CameraLensDirection.back : CameraLensDirection.front;
    final i = _cameras.indexWhere((c) => c.lensDirection == want);
    return i >= 0 ? i : 0;
  }

  Future<void> _openController(CameraDescription desc) async {
    // 分辨率选型（09-26 升级）：
    //  · 原 M2 选 veryHigh 的理由是存储压力（R7：max 单张 4~8MB）；
    //  · 老板 09-26 明确「提高照片质量」→ 默认改走画幅映射：
    //    4:3 → max（传感器原生，4000×3000 起）；16:9 → ultraHigh（4K 级）。
    //  · 存储预检（§8.2）用的 estimatedPhotoBytes=5MB 本来就按高画质估算，
    //    不需要联动改。
    final res = presetFor(_aspect);
    final c = CameraController(
      desc,
      res,
      enableAudio: false, // 不录音 → 不申请麦克风权限
      imageFormatGroup: ImageFormatGroup.jpeg,
    );
    await c.initialize();

    // 每次开新控制器都重放一遍用户偏好（首次初始化 / 换镜头 / 换画幅共用）。
    // 全部 try-catch：部分机型不支持某项能力时静默降级，绝不阻塞开相机。
    try {
      await c.setFlashMode(_flash);
    } catch (_) {/* 部分机型无闪光灯 */}
    try {
      await c.setExposureMode(ExposureMode.auto);
    } catch (_) {}

    // 对焦：每次开新控制器都回到"全画面连续自动对焦"。
    //
    // ⚠️ 旧对焦点必须清掉：留着它，镜头会一直盯着上一件货的位置，
    //    换一件货就得再点一次屏幕 —— 现场要快时这是最不该有的动作。
    //    换镜头/换画幅/切前后摄都走这里，一并覆盖。
    _focusPoint = null;
    _lastPrepareAt = null;
    try {
      await c.setFocusMode(FocusMode.auto);
    } catch (_) {/* 个别 ROM 不支持设置对焦模式，靠默认连续 AF 兜底 */}
    if (_exposure != 0 || _autoEv != 0) {
      // 换镜头/画幅后曝光补偿不丢 —— 现场调好的明暗不该被一键清零。
      // 手动档 + 自动档一起重放；总档位钳在设备能力范围内。
      try {
        final total = (_exposure + _autoEv).clamp(-8.0, 8.0);
        await c.setExposureOffset(total);
      } catch (_) {}
    }

    // 曝光补偿能力探测（2026-10-10 暗光自动补偿）：三个通道往返毫秒级。
    // step<=0 或 max<=step 视为不支持 —— 不支持的机器 autoEv 恒为 0，
    // 提示也不发（能力探测失败 ≠ 暗光，别拿补偿失败吓人）。
    try {
      final lo = await c.getMinExposureOffset();
      final hi = await c.getMaxExposureOffset();
      final st = await c.getExposureOffsetStepSize();
      _minEv = lo;
      _maxEv = hi;
      _evStep = st > 0 ? st : 0;
      if (_evStep <= 0 || _maxEv <= _evStep) {
        _evStep = 0;
        _maxEv = 0;
      }
    } catch (_) {
      _minEv = 0;
      _maxEv = 0;
      _evStep = 0;
    }
    Log.d('Capture', 'ev compensation: [$_minEv, $_maxEv] step=$_evStep'
        ' autoEv=$_autoEv');

    // 变焦范围探测：两个通道往返，毫秒级；不支持时回退 [1,1]。
    // ⚠️ minZoom<1.0 要**如实采纳**（2026-10-08 老板诉求「预览要支持缩小」）
    //    —— 广角/超广角机型会报 0.5~0.7，原来是硬钳到 1.0，等于把
    //    镜头本来就有的"看得更全"能力禁掉了。钳 0.5 下限是防御：
    //    个别 ROM 报 0 时 setZoomLevel(0) 会直接崩。
    try {
      final lo = await c.getMinZoomLevel();
      final hi = await c.getMaxZoomLevel();
      // 只有 hi 确实大于 lo 时才信任 <1.0 的 min（个别 ROM 上报异常值）。
      _minZoom = (lo >= 0.5 && lo < hi) ? lo : 1.0;
      _maxZoom = hi > _minZoom ? hi : _minZoom;
    } catch (_) {
      _minZoom = 1.0;
      _maxZoom = 1.0;
    }
    _zoom = 1.0; // 新控制器一律回 1x —— 残留的倍率会让人找不到北
    try {
      await c.setZoomLevel(1.0);
    } catch (_) {}

    // 能力落日志（2026-10-09）：「看不到 0.6x」这类反馈只能靠这一行定位
    // —— 广角到底是"镜头不支持"还是"我们没给入口"，看 min 与后置颗数即可。
    // v0.20.0 补 previewSize：与成片比例对比是「所见即所得」的定量验证
    // （2026-10-12 真机反馈「成片比取景远」的排查基线）。
    final previewSize = c.value.previewSize;
    Log.i(
      'Capture',
      'lens=${desc.name} zoom=[${_minZoom.toStringAsFixed(2)},'
          ' ${_maxZoom.toStringAsFixed(2)}] backLenses=${backLensIndices.length}'
          ' cameras=${_cameras.length}'
          ' preview=${previewSize?.width}x${previewSize?.height}'
          ' aspect=${_aspect.name} ev=[$_minEv,$_maxEv]/$_evStep',
    );

    if (_disposed) {
      await c.dispose();
      return;
    }
    final old = _controller;
    _controller = c;
    await old?.dispose();
  }

  // ─────────────────────────────────────────────────────────
  // 会话
  // ─────────────────────────────────────────────────────────

  @override
  String? get activeSessionId => _sessionId;

  @override
  int get sessionPhotoCount => _sessionCount;

  @override
  Stream<int> get photoCountStream => _countController.stream;

  @override
  Future<String> startSession(String projectId) async {
    // 续接语义（APP 被杀续接 / 「退出对照清单 20 秒再进」的批次续接窗口）
    // 全部在仓储 [CaptureRepository.startSession] 里 —— 服务层只委托并
    // 恢复会话计数。photoCount > 0 即说明是续上的旧批次。
    final id = await _repo.startSession(projectId);
    _sessionId = id;
    final s = await _repo.getSession(id);
    _sessionCount = s?.photoCount ?? 0;
    if (_sessionCount > 0) {
      Log.i('Capture', 'resumed session $id ($_sessionCount photos)');
    } else {
      Log.i('Capture', 'started session $id');
    }

    await ProjectPaths.ensureProject(projectId);
    _nextSeq = await _repo.nextSeq(projectId);
    _emitCount();
    return _sessionId!;
  }

  @override
  Future<void> pauseSession() async {
    // 暂停 ≠ 结束：只释放相机，保留 sessionId 与计数。
    // 回来时 initialize() 后可直接续拍（startSession 会命中 findOpenSession）。
    await _controller?.pausePreview().catchError((_) {});
  }

  @override
  Future<void> endSession() async {
    // ⚠️ 必须先 drain：照片已拍下、还在落盘队列里。此时就 endSession
    // 会关掉批次，队列里那几张随后才写进来 —— 表现是"退出后张数少几张"，
    // 而且照片文件在、库里没有，交付时成了"缺口"。
    await _sink.drain();

    // 自动曝光补偿档随批次结束归零：暗光批次结束后，下一个项目（可能
    // 光线正常）不该背上上一场的补档 —— 残留会让白天第一张过曝。
    // 用户手动档 [_exposure] 保留（那是人调的，批次语义上跨场次有效）。
    if (_autoEv != 0) {
      _autoEv = 0;
      final c = _controller;
      if (c != null && c.value.isInitialized) {
        try {
          await c.setExposureOffset(_exposure);
        } catch (_) {}
      }
    }

    final id = _sessionId;
    _sessionId = null;
    _sessionCount = 0;
    if (id != null) {
      await _repo.endSession(id);
      Log.i('Capture', 'ended session $id');
    }
    _emitCount();
  }

  // ─────────────────────────────────────────────────────────
  // 拍摄
  // ─────────────────────────────────────────────────────────

  @override
  Future<String> capture(String projectId) async {
    return _shoot(projectId).then((id) => id ?? '');
  }

  /// 拍一张。返回新照片的 id；[skipIfBusy] 用于连拍（丢张会计数并上报）。
  ///
  /// ── 流水线（2026-10-09「全面提升拍照体验」的核心改造）────────
  /// 原来这里是**一整条 await 链**：取帧 → 写文件 → 入库，期间
  /// `_capturing` 一直被占着。两个后果，都能在现场看见：
  ///   ① 连拍每张的实际周期 = 相机耗时 **+ 磁盘耗时 + 400ms 间隔**，
  ///      而 `burst()` 又按 400ms 固定间隔发起 —— 上一张没落完就直接
  ///      `skipIfBusy` **静默丢掉**，20 张实际可能只拍到十几张；
  ///   ② 写 4~8MB + flush 跑在主 isolate 上，按下快门到出图之间
  ///      UI 是卡的（低配机上肉眼可见"点一下顿一下"）。
  ///
  /// 改法：**只 await 到取帧**，剩下的落盘/入库排进 [_sink] 串行队列，
  /// 写文件本身在后台 isolate（见 `PhotoFileSink.writeRaw`）。
  /// 串行保证 seq 与入库顺序严格一致；`endSession`/`dispose` 前 drain
  /// 保证最后几张不会在关批次后才落盘。
  ///
  /// 返回的 id 要等入库完成才有 —— 因为补拍模式要拿它挂组。返回得晚
  /// 不影响连点：`_capturing` 在取帧结束就释放了。
  Future<String?> _shoot(String projectId, {bool skipIfBusy = false}) async {
    final c = _controller;
    if (c == null || !c.value.isInitialized) {
      Log.w('Capture', 'shoot skipped: camera not ready');
      _reportError(CaptureErrorKind.shot, 'camera not ready');
      return null;
    }
    if (_capturing) {
      // 连拍时"上一张还没取完帧"是正常现象。跳过而不是排队 ——
      // 排队会让连拍节奏失控（越拍越慢）。但**必须记账**：
      // 丢张不给提示，现场表现就是"我按了 20 下怎么只有 12 张"。
      if (skipIfBusy) {
        _burstDropped++;
        return null;
      }
    }

    // ── ① 取帧：这段是唯一必须同步等的相机动作 ──
    final sw = Stopwatch()..start();
    final Uint8List bytes;
    try {
      final shot = await c.takePicture();
      bytes = await shot.readAsBytes();
    } on CameraException catch (e) {
      Log.w('Capture', 'takePicture failed: ${e.code} / ${e.description}');
      _reportError(CaptureErrorKind.shot, '${e.code}/${e.description}');
      return null;
    } finally {
      // 锁在这里就放：相机已经出帧了，磁盘爱多慢慢去。
      _capturing = false;
    }

    // 快门音（2026-10-08 老板诉求；v0.20.0 时机修正）：**取帧成功就响**
    // —— 此时照片已在内存（相机已写完临时文件），"响 = 真的拍上了"
    // 的口径不变，只是不再等落库入库（那还有 100~300ms，原生相机都是
    // 按下即响，晚响等于没响）。失败只记日志，绝不影响拍照。
    unawaited(
      const MethodChannel('gtick/gallery')
          .invokeMethod<void>('playShutter')
          .catchError((_) {}),
    );

    final session = _sessionId ?? await startSession(projectId);
    final takenAt = DateTime.now();
    final seq = _nextSeq++;
    final done = Completer<String>();

    // ── ② 落盘 + 入库：串行队列，主线程不等 ──
    _sink.add(
      () => _persist(
        projectId: projectId,
        session: session,
        takenAt: takenAt,
        seq: seq,
        bytes: bytes,
        sw: sw,
        done: done,
      ),
      onError: (e, st) {
        Log.e('Capture', 'write failed', e, st);
        _reportError(CaptureErrorKind.write, '$e');
        if (!done.isCompleted) done.complete('');
      },
    );
    return done.future;
  }

  /// 队列内的一环：原图直写（含 flush）→ 入库 → 派发派生任务。
  ///
  /// 原图直写、不改名、不转码（§6.4）—— 相机已经给了 JPEG，
  /// 再编码一次只会掉画质又费电。
  Future<void> _persist({
    required String projectId,
    required String session,
    required DateTime takenAt,
    required int seq,
    required Uint8List bytes,
    required Stopwatch sw,
    required Completer<String> done,
  }) async {
    final w = await PhotoFileSink.writeRaw(
      projectId: projectId,
      sessionId: session,
      takenAt: takenAt,
      seq: seq,
      bytes: bytes,
    );

    // 入库（item_id 为空，state = unassigned）
    final ids = await _repo.insertPhotos(projectId, [
      NewPhoto(
        sessionId: session,
        filePath: w.filePath,
        seq: seq,
        takenAt: takenAt,
        bytes: w.bytes,
      ),
    ]);
    final photoId = ids.first;

    _sessionCount++;
    _emitCount();
    _lastShotController.add(photoId);

    sw.stop();
    Log.d('Capture', 'shot ok in ${sw.elapsedMilliseconds}ms → ${w.filePath}');

    // 缩略图 + 尺寸：**不 await**（异步补，失败不影响入库）
    _derive(() => _enrich(projectId, photoId, w.filePath));

    // 相册镜像：同样不 await。哪怕复制慢半拍，也绝不拖住下一张快门
    //    —— 它排 缩略图 后面，失败静默（GalleryService 纪律 2）。
    _derive(() => _toGallery(projectId, w.filePath, takenAt));

    // 内容指纹（查重用，2026-10-04）：同样不 await。
    //    刚拍完的文件在页缓存里，读 64KB 是微秒级；等它算完只会
    //    让快门下一张迟到。失败留 NULL —— backfillHashes 会补。
    _derive(() => _hashOne(photoId, w.filePath));

    if (!done.isCompleted) done.complete(photoId);
  }

  void _reportError(CaptureErrorKind kind, String message, {int? count}) {
    if (_errorController.isClosed) return;
    _errorController.add(CaptureError(kind, message, count: count));
  }

  /// 缩略图 + 尺寸回填。
  ///
  /// 过 [AsyncLimiter] 排队：并发数由设备档次决定（低配 = 1）。
  /// 长边也按档次降（低配 192px）—— 列表格子只有 74dp，256px 是浪费。
  Future<void> _enrich(String projectId, String photoId, String srcPath) async {
    _thumbLimiter.max = DeviceTier.current.thumbConcurrency;
    await _thumbLimiter.run(() async {
      await _enrichNow(projectId, photoId, srcPath);
    });
  }

  Future<void> _enrichNow(
    String projectId,
    String photoId,
    String srcPath,
  ) async {
    try {
      final dst = await ProjectPaths.thumbPath(projectId, photoId);
      final size = await PhotoFileSink.makeThumbnail(
        srcPath: srcPath,
        dstPath: dst,
        longEdge: DeviceTier.current.thumbLongEdge,
      );
      // ⚠️ 失败时**绝不写 thumbPath**（2026-09-29「整理页缩略图显示不出来」
      // 的第二层根因）：写一个打不开的路径有两个恶果 —— ①列表拿着它去
      // 显示，永远是一张碎图；②`photosMissingThumb` 只挑 `thumbPath IS NULL`
      // 的照片，写上去之后这张照片**再也不会被补齐捞到**，缩略图等于永久
      // 报废。留空 = 下一轮 backfill 还会救它。
      if (size == null) {
        Log.w('Capture', 'thumb failed for $photoId — keep null for backfill');
        return;
      }
      await _repo.patchMediaInfo(
        photoId,
        thumbPath: dst,
        width: size.width,
        height: size.height,
      );
      // 成片实际尺寸落日志（v0.20.0）：与 preview 尺寸对比 = 所见即所得
      // 的定量验证；比例偏差 >8% 的机型要在真机矩阵里标注复核。
      Log.d('Capture', 'capture size ${size.width}x${size.height}'
          ' (${(size.width / size.height).toStringAsFixed(3)})');
      // 弱光判定 + 暗光自动曝光补偿（2026-10-10）：亮度是生成缩略图时
      // 原生/isolate 顺算的，这里零成本拿到。没量到（null）就当不知道。
      _onLumaMeasured(size.luma);
      // 缩略图已就位 —— 通知胶片条再刷一次（否则它拿到的还是灰块）。
      if (!_thumbReadyController.isClosed) _thumbReadyController.add(photoId);
    } catch (e) {
      Log.w('Capture', 'enrich failed for $photoId :: $e');
    }
  }

  /// 给一张照片算内容指纹并回填（查重依据，2026-10-04）。
  ///
  /// 失败**不上报也不抛出**，只留 NULL —— 指纹只影响"提不提示重复"，
  /// 绝不能因为它失败就让一次快门白按。
  Future<void> _hashOne(String photoId, String srcPath) async {
    try {
      final r = await PerfBridge.hashFiles([srcPath]);
      final h = r.isEmpty ? null : r.first;
      if (h == null || h.isEmpty) return;
      await _repo.patchContentHash(photoId, h);
    } catch (e) {
      Log.w('Capture', 'hash failed for $photoId :: $e');
    }
  }

  /// 补算本项目缺失的内容指纹，返回补上的张数。
  ///
  /// 为什么需要：**v4 迁移只加列不回填**（老项目上千张，升级时同步算
  /// 会把升级卡死几分钟）。所以老照片一律 content_hash = NULL，
  /// 由这个方法在进照片页时后台分批补。
  ///
  /// 形状照抄 [backfillThumbnails]：分批 20 张、一次原生往返、
  /// **有失败就停**（那些张仍是 NULL，不停会死循环）。
  @override
  Future<int> backfillHashes(String projectId) async {
    var done = 0;
    const batchSize = 20;
    while (true) {
      final missing =
          await _repo.photosMissingHash(projectId, limit: batchSize);
      if (missing.isEmpty) break;

      final hashes = await PerfBridge.hashFiles([
        for (final p in missing) p.filePath,
      ]);
      var failed = false;
      for (var i = 0; i < missing.length; i++) {
        final h = i < hashes.length ? hashes[i] : null;
        if (h == null || h.isEmpty) {
          failed = true; // 文件读不到 —— 停在这批，下轮再来
          continue;
        }
        await _repo.patchContentHash(missing[i].id, h);
        done++;
      }

      if (failed) break;
      if (missing.length < batchSize) break;
    }
    if (done > 0) Log.i('Capture', 'backfilled $done content hashes');
    return done;
  }

  /// 补齐本项目缺失的缩略图，返回补上的张数。
  ///
  /// 为什么需要（2026-09-29「整理页缩略图显示不出来」的第三层根因）：
  /// 缩略图是**入库之后**才异步生成的（不阻塞快门、不阻塞导入）。用户导入
  /// 完立刻进整理页时，列表读到的 `thumbPath` 还是 null，而列表**不会自己
  /// 刷新** —— 看上去就是"缩略图全都显示不出来"。
  ///
  /// 整理页进来先跑一次这个方法，补完再 invalidate，图就出来了；历史项目里
  /// 因为失败或中断而缺缩略图的照片也一并救回。
  ///
  /// 批量走原生（一次通道往返处理 20 张），比逐张排队快一个量级。
  @override
  Future<int> backfillThumbnails(String projectId) async {
    var done = 0;
    const batchSize = 20;
    while (true) {
      final missing =
          await _repo.photosMissingThumb(projectId, limit: batchSize);
      if (missing.isEmpty) break;

      final specs = <ThumbSpec>[];
      for (final p in missing) {
        specs.add(
          ThumbSpec(
            srcPath: p.filePath,
            dstPath: await ProjectPaths.thumbPath(projectId, p.id),
            longEdge: DeviceTier.current.thumbLongEdge,
          ),
        );
      }

      final sizes = await PhotoFileSink.makeThumbnails(specs);
      for (var i = 0; i < missing.length; i++) {
        final s = sizes[i];
        if (s == null) continue; // 留空，下一轮再试（见 _enrichNow 的说明）
        await _repo.patchMediaInfo(
          missing[i].id,
          thumbPath: specs[i].dstPath,
          width: s.width,
          height: s.height,
        );
        done++;
      }

      // 整批都成才继续翻下一批；有失败就停 —— 失败的那些 thumbPath 仍是
      // null，下一轮查询还会把它们捞出来，不停就会死循环。
      if (sizes.any((e) => e == null)) break;
      if (missing.length < batchSize) break;
    }
    if (done > 0) Log.i('Capture', 'backfilled $done thumbnails');
    return done;
  }

  /// 把刚落盘的照片**复制**一份进系统相册（P4 · 老板诉求）。
  ///
  /// 为什么在采集服务里做而不是 UI 层：相册镜像跟落盘是同一件事的
  /// 两个副本，都发生在"快门之后"；UI 层做会让采集页多一个
  /// "忘记调"的单点失败，服务层做则一次注入、永远生效。
  ///
  /// 纪律（与 [GalleryService] 对齐）：失败静默 —— 相册存不进去，
  /// 照片在 App 里照样能用，不打断拍照。
  Future<void> _toGallery(
    String projectId,
    String filePath,
    DateTime takenAt,
  ) async {
    final gallery = _gallery;
    if (gallery == null) return;
    try {
      if (!await gallery.isEnabled) return;
      await gallery.save(
        srcPath: filePath,
        album: await _albumFor(projectId),
        takenAt: takenAt,
      );
    } catch (e) {
      Log.w('Capture', 'gallery mirror failed: $filePath :: $e');
    }
  }

  /// 相册子目录名 = 项目名（已做非法字符清理）。每个项目只查一次。
  Future<String> _albumFor(String projectId) async {
    final cached = _albumCache[projectId];
    if (cached != null) return cached;
    final name = await _repo.projectName(projectId);
    final album = GalleryService.safeFolderName(name);
    _albumCache[projectId] = album;
    return album;
  }

  @override
  Stream<String> burst(
    String projectId, {
    int count = AppConst.burstMaxPhotos,
    int intervalMs = AppConst.burstIntervalMs,
  }) async* {
    // 用 Stream 而不是 Future.wait 的理由：UI 要能一张一张地
    // 看到张数跳动（那是现场唯一的反馈），而不是等全部拍完才动。
    final n = count.clamp(1, AppConst.burstMaxPhotos);
    _burstDropped = 0;
    await _lockFocusForBurst();
    try {
      for (var i = 0; i < n; i++) {
        final id = await _shoot(projectId, skipIfBusy: true);
        if (id != null && id.isNotEmpty) yield id;
        if (i < n - 1) {
          await Future<void>.delayed(Duration(milliseconds: intervalMs));
        }
      }
    } finally {
      await _unlockFocusAfterBurst();
      // 丢张必须在连拍**结束后**一次性报：逐张提示会在 400ms 的节奏里
      // 刷屏，用户根本来不及看，结束时的汇总才有意义。
      if (_burstDropped > 0) {
        _reportError(
          CaptureErrorKind.burstDropped,
          'burst dropped $_burstDropped',
          count: _burstDropped,
        );
      }
      _burstDropped = 0;
    }
  }

  /// 连拍前锁焦：把焦点钉在用户点过的那个点上，别让镜头在连拍中途追焦。
  ///
  /// 理由：一批一组 = 同一件货。连拍时拍的是**同一件货的不同角度**，
  /// 距离几乎不变 —— 追焦不但没必要，还会因为中途重新对焦把某几张拍糊
  /// （系统相机的"连拍"同样是锁焦的）。
  ///
  /// **同时锁曝光**（2026-10-12 v0.20.0 新增）：`setExposureMode(locked)`
  /// 在插件内部走 Camera2 的 `CONTROL_AE_LOCK`——不锁的话，连拍中途 AE
  /// 重新收敛会让同一件货的不同角度明暗跳变（取证照片要的是一致）。
  /// 只在用户**点过对焦点**时才锁：没点过就别替他决定，让镜头连续
  /// 追焦更稳。锁失败（机型不支持）静默 —— 只是少一个优化，不是故障。
  Future<void> _lockFocusForBurst() async {
    final c = _controller;
    final p = _focusPoint;
    if (c == null || !c.value.isInitialized || p == null) return;
    try {
      await c.setFocusPoint(p);
      await c.setFocusMode(FocusMode.locked);
      // AE 锁与对焦锁同步上（插件内部 = CONTROL_AE_LOCK，见 4.1 查证）
      await c.setExposureMode(ExposureMode.locked);
      _burstFocusLocked = true;
      Log.d('Capture', 'burst focus+AE locked at ${p.dx.toStringAsFixed(2)},'
          '${p.dy.toStringAsFixed(2)}');
    } catch (e) {
      Log.d('Capture', 'burst focus lock unsupported: $e');
    }
  }

  /// 连拍结束/中止后恢复自动对焦 + 自动曝光（锁着走出会导致后面换场景
  /// 永远糊、永远曝光错）。
  Future<void> _unlockFocusAfterBurst() async {
    if (!_burstFocusLocked) return;
    _burstFocusLocked = false;
    try {
      await _controller?.setFocusMode(FocusMode.auto);
      await _controller?.setExposureMode(ExposureMode.auto);
    } catch (e) {
      Log.d('Capture', 'burst focus unlock failed: $e');
    }
  }

  // ─────────────────────────────────────────────────────────
  // 相机控制
  // ─────────────────────────────────────────────────────────

  @override
  Future<void> switchCamera() async {
    if (_cameras.length < 2) return;
    _lensIndex = (_lensIndex + 1) % _cameras.length;
    _description = _cameras[_lensIndex];
    await _openController(_description!);
  }

  @override
  Future<void> focusAt(double x, double y) async {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    _focusPoint = Offset(x.clamp(0.0, 1.0), y.clamp(0.0, 1.0));
    try {
      await c.setFocusPoint(_focusPoint!);
      await c.setExposurePoint(_focusPoint!);
      // 锁一次 AE/AF，避免"对上了又跑掉"
      await c.setFocusMode(FocusMode.auto);
    } catch (e) {
      // 部分机型不支持任意点对焦 —— 静默降级为中央对焦，不打扰用户。
      Log.d('Capture', 'focusAt unsupported: $e');
    }
  }

  /// 快门**按下瞬间**触发一次对焦 —— 手机上的"半按对焦"。
  ///
  /// 为什么要有它：CameraX 在按下快门后自己会跑一次 AF 再出片，
  /// 暗处/低对比场景（外包装、木箱、唛头）要几百毫秒 —— 现场的手感
  /// 就是"按下去等一下才拍上，有时还糊"。而手指按下→抬起本来就有
  /// 100ms 以上白等的时间，用它把 AF 提前跑起来，抬手时焦距已经合上，
  /// 快门几乎零延迟。这是"现场快速拍照"最省动作的一处。
  ///
  /// 三条纪律：
  ///  · 不画对焦框 —— 焦点不是用户主动选的，凭空冒个方块是干扰；
  ///  · 不动曝光   —— 按下瞬间画面明暗跳一下很吓人；
  ///  · 有节流     —— 连拍/手抖时不重复触发（AF 反复重启只会更慢）。
  @override
  Future<void> prepareFocus() async {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    final now = DateTime.now();
    if (!shouldPrepareFocus(_lastPrepareAt, now)) return;
    _lastPrepareAt = now;
    try {
      await c.setFocusPoint(focusTargetFor(_focusPoint));
    } catch (e) {
      // 不支持任意点对焦的机型：静默退回全画面连续 AF。
      Log.d('Capture', 'prepareFocus unsupported: $e');
    }
  }

  /// 预对焦点：有用户点过的对焦点就复用它（那是刚被指定的位置），
  /// 否则用画面中心。
  ///
  /// 抽成静态纯函数是为了单测能直接验 —— 本类的实例方法依赖真相机。
  @visibleForTesting
  static Offset focusTargetFor(Offset? last) => last ?? const Offset(0.5, 0.5);

  /// 节流判定：距上次预对焦不足 [prepareFocusThrottle] 就不再触发。
  @visibleForTesting
  static bool shouldPrepareFocus(DateTime? last, DateTime now) =>
      last == null || now.difference(last) >= prepareFocusThrottle;

  @override
  Future<void> setExposureCompensation(double ev) async {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    _exposure = ev.clamp(-4.0, 4.0);
    try {
      await c.setExposureOffset(_exposure + _autoEv);
    } catch (e) {
      Log.d('Capture', 'setExposure unsupported: $e');
    }
  }

  // ── 暗光自动曝光补偿（v0.19.0，与 [CaptureHintKind.lowLight] 配套）──

  /// 由一张图的亮度算出下一个自动补偿档。**纯函数**（单测直接验）。
  ///
  /// 口径：
  ///  · 亮度没量到（null）→ 不动 —— **不知道 ≠ 要补偿**（纪律 17）；
  ///  · 设备不支持（step/max ≤ 0）→ 恒为 0，永远不动；
  ///  · 暗（< [AppConst.lowLightLuma]）→ 加一档，钳到 [AppConst.autoEvMax]；
  ///  · 亮（> [AppConst.autoEvBrightLuma]）且有残留 → 退一档回 0；
  ///  · 中间带 → 不动（防止在阈值附近抖动）。
  @visibleForTesting
  static double nextAutoEv({
    required double current,
    required int? luma,
    required double step,
    required double maxBoost,
    required int darkBelow,
    required int brightAbove,
  }) {
    if (luma == null || step <= 0 || maxBoost <= 0) return current;
    if (luma < darkBelow) {
      final next = current + step;
      return next > maxBoost ? maxBoost : next;
    }
    if (luma > brightAbove && current > 0) {
      final next = current - step;
      return next < 0 ? 0 : next;
    }
    return current;
  }

  /// 一张照片量出亮度后的处理：调自动补偿档 + 按节流发弱光提示。
  ///
  /// 时序说明：缩略图在入库后异步生成（约快门后 0.5~2s），所以补偿
  /// 生效在**下一张** —— 连拍同一件货/同一片暗区正是受益场景。
  void _onLumaMeasured(int? luma) {
    if (luma == null) return;

    final before = _autoEv;
    // ⚠️ 闸门优先：设备不支持（_evStep/_maxEv ≤ 0）→ 原样传 0，
    //    nextAutoEv 恒返回 current —— "不支持就不动"。在这里回退成
    //    AppConst 常量会击穿闸门（算加了档、下发又被 clamp 成 0）。
    //  · step：取 max(硬件步长, 0.5) —— 0.1 一档要拍 15 张才爬到顶，
    //    自动补偿是"下一张受益"的慢反馈，爬太慢等于没用；
    //  · maxBoost：取 min(设备上限, 1.5) —— 1.5 是产品上限（取证宁暗
    //    勿失真），设备范围只是硬边界不是目标。
    final step = _evStep <= 0
        ? 0.0
        : (_evStep > AppConst.autoEvStep ? _evStep : AppConst.autoEvStep);
    final maxBoost = _maxEv <= 0
        ? 0.0
        : (_maxEv < AppConst.autoEvMax ? _maxEv : AppConst.autoEvMax);
    final next = nextAutoEv(
      current: _autoEv,
      luma: luma,
      step: step,
      maxBoost: maxBoost,
      darkBelow: AppConst.lowLightLuma,
      brightAbove: AppConst.autoEvBrightLuma,
    );

    // maxBoost 取值说明见上方 step/maxBoost 的注释（闸门与上限口径）。
    if (next != before) {
      _autoEv = next;
      Log.i('Capture', 'auto ev: $before → $next (luma=$luma)');
      unawaited(_applyAutoEv());
    }

    // 弱光提示（节流 90s：连拍同一暗场景会连续量出暗图，逐张报是噪音）。
    final now = DateTime.now();
    final last = _lastLowLightHintAt;
    final throttled = last != null && now.difference(last) < const Duration(seconds: 90);
    if (!throttled && luma < AppConst.veryLowLightLuma) {
      _lastLowLightHintAt = now;
      _emitHint(CaptureHintKind.veryLowLight, 'luma=$luma');
    } else if (!throttled && luma < AppConst.lowLightLuma) {
      _lastLowLightHintAt = now;
      _emitHint(CaptureHintKind.lowLight, 'luma=$luma');
    }
  }

  /// 把 手动档+自动档 的总补偿下发到相机（失败静默：补偿失败不该
  /// 让拍照停下来，下一张顶多还是暗的）。
  Future<void> _applyAutoEv() async {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    final total = (_exposure + _autoEv).clamp(_minEv, _maxEv);
    try {
      await c.setExposureOffset(total);
    } catch (e) {
      Log.d('Capture', 'auto ev apply failed: $e');
    }
  }

  void _emitHint(CaptureHintKind kind, String message) {
    if (_hintController.isClosed) return;
    _hintController.add(CaptureHint(kind, message));
    Log.i('Capture', 'hint ${kind.name}: $message');
  }

  // ── 变焦 / 闪光 / 画幅（09-26 老板诉求）──────────────────

  /// 连续变焦（捏合手势 / 档位按钮共用）。
  ///
  /// 越界自动 clamp；不支持变焦的镜头上调用是 no-op。
  /// 失败静默 —— 变焦不成功不该打断"拍"这个主动作。
  Future<void> setZoom(double value) async {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    final v = value.clamp(_minZoom, _maxZoom);
    try {
      await c.setZoomLevel(v);
      _zoom = v;
    } catch (e) {
      Log.d('Capture', 'setZoom unsupported: $e');
    }
  }

  /// 切闪光（用户循环 off → auto → torch）。落偏好，下次开控制器仍生效。
  Future<void> setFlashMode(FlashMode mode) async {
    _flash = mode;
    final c = _controller;
    if (c != null && c.value.isInitialized) {
      try {
        await c.setFlashMode(mode);
      } catch (e) {
        // 前置镜头等无闪光灯场景：状态照记，效果没有 —— 不打扰
        Log.d('Capture', 'flash unsupported: $e');
      }
    }
    await _persistPrefs();
  }

  /// 切换画幅。
  ///
  /// ⚠️ preset 只能在控制器初始化时给定 → 必须**重建控制器**。
  /// 同一摄像头无法双开 → 与 [_openController] 的"先挂新再 dispose 旧"
  /// 不同，这里必须**先关后开**（间隙约几百毫秒，UI 层显示切换提示）。
  /// 失败时按当前镜头再兜底重开一次；再失败就上抛，由 UI 提示。
  Future<void> setAspectRatio(CameraAspectRatio ratio) async {
    if (ratio == _aspect) return;
    _aspect = ratio;
    await _persistPrefs();

    final desc = _description;
    if (desc == null) return; // 相机还没开过：下次 initialize 生效

    final old = _controller;
    _controller = null;
    try {
      await old?.dispose();
    } catch (_) {}

    try {
      await _openController(desc);
    } catch (e) {
      Log.e('Capture', 'aspect reopen failed: $e');
      // 兜底：再试一次（偶发的相机占用恢复后重开通常能成）
      await _openController(desc);
    }
  }

  /// 画幅 → 分辨率映射。
  ///
  ///  · 4:3 → max：传感器原生比例，像素最大化（主流机型 4000×3000 起），
  ///    唛头小字的清晰度最好 —— 画质优先的默认档；
  ///  · 16:9 → ultraHigh：4K 级宽幅。不用 max 的原因是插件在宽幅档
  ///    仍按比例出图，ultraHigh 已是 16:9 下的最高有效档。
  static ResolutionPreset presetFor(CameraAspectRatio ratio) => switch (ratio) {
        CameraAspectRatio.ratio4_3 => ResolutionPreset.max,
        CameraAspectRatio.ratio16_9 => ResolutionPreset.ultraHigh,
      };

  /// 变焦快捷档位：候选里滤掉超出镜头能力的；一个都不剩时保底 1x。
  ///
  /// ⚠️ 缩小档（<1x）**只用设备上报的 minZoom，不写死 0.6**（2026-10-09）：
  /// 「能不能看得更全」是镜头物理能力，写死一个数字就是许诺一个
  /// 按下去没反应的按钮 —— 真机反馈「看不到 0.6x」的根因正是这里：
  /// 设备 minZoom=1.0（镜头不支持缩小）时 0.6 被过滤，界面什么都不
  /// 说，人只看到"少了这个功能"。现在：
  ///   · minZoom<0.95（镜头能缩小）→ 档位是**设备真实值**（0.5x/0.6x/
  ///     0.7x…，按上报值显示，不美化）；
  ///   · minZoom≥0.95（只能放大）→ 只出放大档，缩小这件事交给
  ///     切广角镜头（[switchBackLens]）—— 那是唯一真能扩大视野的办法。
  static List<double> zoomStepsFor(double minZoom, double maxZoom) {
    final steps = <double>[];
    if (minZoom > 0 && minZoom < 0.95) {
      // 一位小数即可：0.62 这种上报值显示成 0.6x，按下去 clamp 到 0.62。
      steps.add((minZoom * 10).round() / 10);
    }
    for (final z in AppConst.zoomStepCandidates) {
      if (z >= minZoom && z <= maxZoom && !steps.contains(z)) steps.add(z);
    }
    if (steps.isEmpty) return const <double>[1.0];
    return steps;
  }

  Future<void> _persistPrefs() async {
    final prefs = _prefs;
    if (prefs == null) return;
    try {
      await prefs.setFlashMode(_flash);
      await prefs.setAspectRatio(_aspect);
    } catch (e) {
      Log.w('Capture', 'persist camera prefs failed: $e');
    }
  }

  // ─────────────────────────────────────────────────────────
  // 相册导入
  // ─────────────────────────────────────────────────────────

  @override
  Future<List<String>> importFromGallery(
    String projectId,
    List<String> filePaths, {
    String? note,
    List<DateTime?>? takenAts,
    ImportProgress? onProgress,
  }) async {
    if (filePaths.isEmpty) return const [];

    // 相册导入**自成一个批次**（source = album）——
    // 分组按批次进行（2026-09-29 拍板：一批一组），相册导入与相机
    // 连拍天然分属不同批次、不会混组。
    // 来源写进批次备注：相册导入与微信导入共用本入口，审计可分。
    final session = await _repo.startSession(
      projectId,
      source: CaptureSource.album,
      note: note ?? '相册导入 ${filePaths.length} 张',
    );

    var seq = await _repo.nextSeq(projectId);
    final batch = <NewPhoto>[];

    for (var i = 0; i < filePaths.length; i++) {
      final path = filePaths[i];
      final f = File(path);
      if (!await f.exists()) continue;
      // 时间戳优先级（2026-09-29 修订）：
      //   ① 调用方覆盖值 —— 微信导入传 MediaStore DATE_TAKEN；相册导入
      //      传按「文件名+大小」回查媒体库的 DATE_TAKEN（GalleryMetaService
      //      ，file_picker 缓存副本把原始元数据丢了，只能回查）。
      //      微信保存的图 / 截图没有 EXIF，不覆盖落库就全是导入时刻，
      //      排序与交付命名会失去真实先后（分组不受影响：一批一组）。
      //   ② EXIF DateTimeOriginal（相册原图大多有 = 快门时刻）。
      //   ③ 文件修改时间（最后的兜底；转发图上它是转发时刻，
      //      排序会有偏差 —— 但宁可时间不准也不能阻塞导入）。
      // exists() + stat() 是两次 IO；直接 stat，失败即当作已丢失。
      FileStat stat;
      try {
        stat = await f.stat();
      } catch (_) {
        continue;
      }
      if (stat.type == FileSystemEntityType.notFound) continue;
      final DateTime? override =
          (takenAts != null && i < takenAts.length) ? takenAts[i] : null;
      // 有覆盖值时**不再读 EXIF** —— 相册导入的 takenAts 来自 MediaStore
      // DATE_TAKEN，比 EXIF 更可靠，且省掉一次文件读取。
      final takenAt =
          override ?? await PhotoExif.takenAt(path) ?? stat.modified;

      final ext = _ext(path);
      final dst = await ProjectPaths.importedFile(
        projectId: projectId,
        sessionId: session,
        takenAt: takenAt,
        seq: seq,
        ext: ext,
      );

      // ⚠️ 性能（2026-09-29 排查）：旧代码无脑 `f.copy(dst)` —— 那是把
      // 临时副本**再全量复制一遍**（选 100 张 = 多写 500MB）。原生临时目录
      // 已改到与项目目录同根的外部私有 files，同根就能 `rename`：
      // 一次原子重命名，零字节拷贝。跨分区等异常情况下回退 copy。
      var bytes = 0;
      try {
        final moved = await f.rename(dst);
        bytes = await moved.length();
      } catch (_) {
        await f.copy(dst);
        bytes = await File(dst).length();
      }
      if (bytes <= 0) continue;

      batch.add(NewPhoto(
        sessionId: session,
        filePath: dst,
        seq: seq,
        takenAt: takenAt,
        bytes: bytes,
      ));
      seq++;
      onProgress?.call(i + 1, filePaths.length);
    }

    if (batch.isEmpty) {
      await _repo.endSession(session);
      return const [];
    }

    // insertPhotos 返回的就是入库照片 id（与 batch 顺序一致）
    final ids = await _repo.insertPhotos(projectId, batch);
    await _repo.endSession(session);

    // 内容指纹（查重，2026-10-04）：**一次原生往返算整批**。
    // 这里 await 而不是 unawaited：导入本来就跑在进度对话框里（≥8 张），
    // 而"导完就知道有没有重复"是刚需（用户最可能就是在这一步重复选了图）。
    // 不走 unawaited 是刻意的 —— 那会引入测试竞态（见下面 backfill 的说明），
    // 且 hashFiles 内部已吞掉全部异常，这里再兜一层，绝不让指纹失败影响导入。
    try {
      final hashes = await PerfBridge.hashFiles([
        for (final p in batch) p.filePath,
      ]);
      for (var i = 0; i < ids.length && i < hashes.length; i++) {
        final h = hashes[i];
        if (h == null || h.isEmpty) continue;
        await _repo.patchContentHash(ids[i], h);
      }
    } catch (e) {
      Log.w('Capture', 'hash batch failed :: $e');
    }

    // 不在这里主动跑 backfillThumbnails（2026-09-30 修法）：
    // ① 整理页 initState 已经无条件跑一次 backfill，用户进页就有；
    // ② 在导入路径里 `unawaited` 调 backfill 会引入**测试竞态**：
    //   backfill 内部要 `path_provider` channel 拿 thumbDir，测试
    //   await 完 `importFromGallery` 就 teardown，但 backfill 的尾巴
    //   还在跑，platform channel 抛 "pending async work" 让整组测试
    //   偶发失败（单独跑过、跑全套时挂，+336 -1 而不是 +337）。
    // 不主动跑不影响 UX：用户进整理页触发 backfill，几秒内补齐。

    Log.i('Capture', 'gallery imported ${batch.length} photos');
    return ids;
  }

  // ─────────────────────────────────────────────────────────
  // 系统相机拍照（2026-10-14 v0.22.0）
  // ─────────────────────────────────────────────────────────

  /// 系统相机路径的快门：把系统相机写好的临时文件收进当前批次。
  ///
  /// 与 [_persist]（内置相机路径）是同一条管子的两个源头：那里字节来自
  /// `takePicture()`，这里字节来自系统相机落的文件。续接批次、EXIF 时刻、
  /// 原子移动、入库、镜像、缩略图、指纹——**一环不少，全部复用现有机制**。
  @override
  /// 把一张已落盘的照片收进当前项目（2026-10-14 v0.22.0 系统相机路径）。
  ///
  /// [takenAtOverride] 非空时直接用作拍摄时刻（2026-10-15 v0.24.2 连拍
  /// 会话传 MediaStore DATE_TAKEN —— 比重读 EXIF 更可靠还省一次文件读取，
  /// 与 importFromGallery 的 takenAts 覆盖同款优先级）。
  ///
  /// [move] 默认 true：临时文件与项目目录同根，rename 是同卷原子移动。
  /// 连拍会话传 **false** —— 会话原图在 DCIM（媒体库），主人是系统相册，
  /// 动它等于偷用户的底片；且跨卷 rename 会失败，这里明确走 copy。
  ///
  /// [galleryMirror] 默认 true（拍一张抄一份进「集刻-采集」相册）。
  /// 连拍会话传 **false** —— 会话照片本来就在相册里（DCIM），再抄一份
  /// 就是相册重复件（GalleryService 纪律 6：只有 App 内拍的照片才进相册）。
  Future<String> captureFromFile(
    String projectId,
    String filePath, {
    DateTime? takenAtOverride,
    bool move = true,
    bool galleryMirror = true,
  }) async {
    if (_disposed) return '';

    // ① 文件校验：个别 ROM 返回 RESULT_OK 却不写 EXTRA_OUTPUT 的文件。
    // 没文件 = 这张没拍上 —— 上报 shot 错误，**不结束批次**：用户正在
    // 连续拍的节奏里，一张失败就收摊等于把现场半途丢下。
    FileStat stat;
    try {
      stat = await File(filePath).stat();
    } catch (_) {
      _reportError(CaptureErrorKind.shot, 'system camera shot missing: $filePath');
      return '';
    }
    if (stat.type == FileSystemEntityType.notFound || stat.size <= 0) {
      _reportError(CaptureErrorKind.shot, 'system camera shot empty: $filePath');
      return '';
    }

    final sw = Stopwatch()..start();

    // ② 批次：与 capture() 完全同口径 —— 当前 open camera 批次，没有就开。
    // startSession 内部命中 findOpenSession / findResumableSession，
    // 5 分钟窗口内回到采集页拍的照片仍属同一批（DB 语义零改动）。
    final session = _sessionId ?? await startSession(projectId);

    // ③ 拍摄时刻：调用方覆盖值（连拍会话的 MediaStore DATE_TAKEN）→
    // EXIF（系统相机写的真快门时刻）→ 文件修改时间。
    // 不用 DateTime.now()：往返有几秒，now() 会把「回来的时刻」当成
    // 「快门时刻」，批量交付时排序失真（与 importFromGallery 同款优先级）。
    final takenAt =
        takenAtOverride ?? await PhotoExif.takenAt(filePath) ?? stat.modified;

    // ③.5 账本幂等（2026-10-21）：同一张原图可能因「进程被杀恢复」、
    // 「晚到推送与新会话首批重叠」被收两次。账本按 (项目, 原图路径)
    // 唯一 —— 已入库的直接复用 photoId，不再复制、不再插行。
    final claim = await _repo.claimSystemShot(
      projectId: projectId,
      sessionId: session,
      sourcePath: filePath,
      sourceSize: stat.size,
      sourceMtime: stat.modified.millisecondsSinceEpoch,
      takenAtMs: takenAt.millisecondsSinceEpoch,
    );
    final reused = claim.photoId;
    if (reused != null) {
      Log.i('Capture', 'system shot already stored, reuse: $reused');
      return reused;
    }
    if (claim.inFlight) {
      // 另一路正在收同一张（旧场晚到 vs 新场首批）。跳过，别抢；
      // 它会写入账本/照片行，收尾对账能看到。
      Log.i('Capture', 'system shot in flight elsewhere, skip: $filePath');
      return '';
    }

    Future<void> markFailed(String reason) async {
      try {
        await _repo.markSystemShotFailed(
          projectId: projectId,
          sourcePath: filePath,
          error: reason,
        );
      } catch (_) {
        // 账本写失败不影响主流程（下次 recover 会按 ingesting 重试）。
      }
    }

    final seq = _nextSeq++;
    final ext = _ext(filePath);
    final dst = await ProjectPaths.importedFile(
      projectId: projectId,
      sessionId: session,
      takenAt: takenAt,
      seq: seq,
      ext: ext,
    );

    // ④ 落点：move=true（默认）时临时目录与项目目录**同根**（都在
    // getExternalFilesDir 下），rename 是同一卷原子移动，零字节拷贝；
    // 跨卷等异常回退 copy（与 importFromGallery 同款，含文件大小校验）。
    // move=false（连拍会话）：直接 copy —— 原图在 DCIM 归相册管，不能动。
    //
    // ⚠️ v0.24.5：会话分支的 copy 原来**没有 try** —— DCIM 偶发读失败
    // （MediaStore 索引刚就绪、文件句柄未释放等）时异常一路冒到调用方，
    // 只被编排层的 catch 记一条日志就吞掉，用户既看不到提示、
    // errorStream 也没上报，那张就凭空少了（真机复测「拍 3 张只存 1
    // 张」的第二种可能）。现在失败一律走 write 错误上报 + 返回空，
    // UI 会看到「收到 N 张、只存下 M 张」并指引去相册补收。
    var bytes = 0;
    if (move) {
      try {
        final moved = await File(filePath).rename(dst);
        bytes = await moved.length();
      } catch (_) {
        try {
          await File(filePath).copy(dst);
          bytes = await File(dst).length();
        } catch (e) {
          Log.e('Capture', 'system shot copy failed: $filePath', e);
          await markFailed('copy failed: $e');
          _reportError(CaptureErrorKind.write, '照片复制失败：$filePath');
          return '';
        }
      }
    } else {
      try {
        await File(filePath).copy(dst);
        bytes = await File(dst).length();
      } catch (e) {
        Log.e('Capture', 'session shot copy failed: $filePath', e);
        await markFailed('copy failed: $e');
        _reportError(CaptureErrorKind.write, '会话照片复制失败：$filePath');
        return '';
      }
    }
    if (bytes <= 0) {
      await markFailed('not landed: $filePath');
      await _deleteQuietly(File(dst));
      _reportError(CaptureErrorKind.write, 'system shot not landed: $filePath');
      return '';
    }

    // ⑤ 入库（item_id 为空，state = unassigned）—— 写失败按 §5.2
    // 「保存失败」处理：照片已经在项目目录里，但库没记上，必须明说。
    List<String> ids;
    try {
      ids = await _repo.insertPhotos(projectId, [
        NewPhoto(
          sessionId: session,
          filePath: dst,
          seq: seq,
          takenAt: takenAt,
          bytes: bytes,
        ),
      ]);
    } catch (e) {
      Log.e('Capture', 'system shot insert failed: $filePath', e);
      await markFailed('insert failed: $e');
      // 行没插进去，落盘副本就是无主文件 —— 删掉，别留孤儿。
      await _deleteQuietly(File(dst));
      _reportError(CaptureErrorKind.write, '$e');
      return '';
    }
    final photoId = ids.first;
    try {
      await _repo.markSystemShotStored(
        projectId: projectId,
        sourcePath: filePath,
        photoId: photoId,
      );
    } catch (e) {
      // 账本写失败不影响这张照片：主键已入库，重复收最多多一行
      // （恢复时还能按路径再做一次判断）。
      Log.w('Capture', 'ledger mark stored failed: $photoId :: $e');
    }

    _sessionCount++;
    _emitCount();
    _lastShotController.add(photoId);

    // ⑥ 派生三连：缩略图 / 相册镜像 / 指纹 —— 与 _persist 完全同款，
    // 全部不 await（失败各自由 backfill* 补救，绝不拖住下一张快门），
    // 但登记进 [_derived]：dispose 会等它们收尾（直拍一次性服务）。
    _derive(() => _enrich(projectId, photoId, dst));
    if (galleryMirror) {
      _derive(() => _toGallery(projectId, dst, takenAt));
    }
    _derive(() => _hashOne(photoId, dst));

    sw.stop();
    Log.i('Capture', 'system shot ingested in ${sw.elapsedMilliseconds}ms → $dst');
    return photoId;
  }

  /// 重拷一张**已入库**照片的原图（v0.24.11 渐进式收图的修复路径）。
  ///
  /// 场景：sweep 发现首批交回后文件大小变了（首批交早了 / 相机补写）——
  /// 项目里那份可能是截断的，照片还在但取证上不合格。用原图重新覆盖
  /// 拷贝、刷新字节数，缩略图/指纹按新文件重新派生。
  ///
  /// 与 [captureFromFile] 的分工：那个是「新收一张」（插行），这个只
  /// 修不插 —— 重复插行会让项目里出现两张同一原图的照片。
  ///
  /// ⚠️ 三条安全线（2026-10-21）：
  ///  1. **源必须完整**：JPEG 必须以 `FFD9` 收尾。相机可能还在写，半成品
  ///     直接拒掉 —— sweep 会在写完后再推一次，绝不把截断图覆盖进去。
  ///  2. **先写临时文件再原子替换**：`File.copy` 直接覆盖会先截断目标，
  ///     中途失败/进程被杀会把项目里唯一的副本写坏。现在写 `.repair`
  ///     临时文件、校验长度与尾标，再 rename 覆盖。
  ///  3. **只更新 bytes**：不传宽高/缩略图，避免把它们清空（见
  ///     [CaptureRepository.patchMediaInfo] 的 null 语义）。
  ///
  /// 返回 true = 修复完成（false = 照片行不存在 / 原图不完整或读不到 /
  /// 复制校验失败；调用方只记日志：照片仍在相册，sweep 会再试）。
  Future<bool> recopyPhoto(
    String projectId,
    String photoId,
    String srcPath,
  ) async {
    if (_disposed) return false;
    final photo = await _repo.getPhoto(photoId);
    if (photo == null) return false;

    final src = File(srcPath);
    if (!await src.exists()) return false;
    final srcLen = await src.length();
    if (srcLen <= 0) return false;
    if (!await isCompleteImage(src)) {
      Log.w('Capture', 'repair skipped (source incomplete): $srcPath');
      return false;
    }

    final target = File(photo.filePath);
    final tmp = File('${photo.filePath}.repair');
    try {
      await src.copy(tmp.path);
      if (await tmp.length() != srcLen) {
        Log.w('Capture', 'repair aborted (copy size mismatch): $photoId');
        await _deleteQuietly(tmp);
        return false;
      }
      if (!await isCompleteImage(tmp)) {
        Log.w('Capture', 'repair aborted (copy incomplete): $photoId');
        await _deleteQuietly(tmp);
        return false;
      }
      // Android 上同目录 rename 是原子替换；Windows 不允许覆盖同名文件，
      // 回退「删旧再改名」（只影响桌面单测，现场走不到）。
      try {
        await tmp.rename(target.path);
      } on FileSystemException {
        if (!Platform.isWindows) rethrow; // 非"目标已存在"的失败：保留旧文件
        await _deleteQuietly(target);
        await tmp.rename(target.path);
      }
    } catch (e) {
      await _deleteQuietly(tmp);
      Log.w('Capture', 'repair failed: $photoId :: $e');
      return false;
    }

    await _repo.patchMediaInfo(photoId, bytes: srcLen);
    _derive(() => _enrich(projectId, photoId, photo.filePath));
    _derive(() => _hashOne(photoId, photo.filePath));
    Log.i('Capture', 'photo repaired: $photoId '
        '(${photo.bytes} -> $srcLen bytes)');
    return true;
  }

  /// 这张图是否已经写完整（供修复路径判断，2026-10-21）。
  ///
  /// JPEG 的权威判据：**头是 `FF D8`、尾是 `FF D9`**（SOI/EOI）。
  /// 相机写盘时先出现文件、后补齐内容 —— 只看大小会把它当完整
  /// （部分实现会预分配文件长度）。按文件头判断而不是扩展名，是为了
  /// 让修复用的临时文件（`xxx.repair`）也能走同一套校验。
  ///
  /// HEIC/PNG/WebP 没有统一尾标，退化为"由调用方按大小/稳定轮询判断"，
  /// 这里返回 true。读失败一律 false —— 宁可这次不修，也不能拿半成品
  /// 覆盖原图。
  @visibleForTesting
  static Future<bool> isCompleteImage(File f) async {
    RandomAccessFile? raf;
    try {
      final len = await f.length();
      if (len < 4) return false;
      raf = await f.open();
      await raf.setPosition(0);
      final head = await raf.read(2);
      final isJpeg = head.length == 2 && head[0] == 0xFF && head[1] == 0xD8;
      if (!isJpeg) return true;
      // 末尾 16 字节内找 EOI：个别相机会在 FFD9 后补零/对齐字节，
      // 只认"最后两字节"会把完整照片误判成半成品（照片收不进来）。
      final tailLen = len < 16 ? len : 16;
      await raf.setPosition(len - tailLen);
      final tail = await raf.read(tailLen);
      for (var i = 0; i + 1 < tail.length; i++) {
        if (tail[i] == 0xFF && tail[i + 1] == 0xD9) return true;
      }
      return false;
    } catch (_) {
      return false;
    } finally {
      final file = raf;
      if (file != null) {
        try {
          await file.close();
        } catch (_) {}
      }
    }
  }

  static Future<void> _deleteQuietly(File f) async {
    try {
      if (await f.exists()) await f.delete();
    } catch (_) {}
  }

  static String _ext(String path) {
    final dot = path.lastIndexOf('.');
    if (dot <= 0 || dot == path.length - 1) return 'jpg';
    final e = path.substring(dot + 1).toLowerCase();
    // 只放行图片扩展名，避免把奇怪的东西复制进来
    const ok = {'jpg', 'jpeg', 'png', 'heic', 'heif', 'webp'};
    return ok.contains(e) ? e : 'jpg';
  }

  // ─────────────────────────────────────────────────────────

  @override
  Future<void> dispose({bool awaitDerived = true}) async {
    _disposed = true;
    _sessionId = null;
    // 队列排空再放相机：正在写的文件用的是项目目录，与相机无关，
    // 但入库完会把张数/事件发出去 —— 排在 dispose 之后发就等于丢事件。
    await _sink.drain();
    // 在途派生（缩略图 / 镜像 / 指纹）收尾：
    //  · awaitDerived=true（页面级服务退出）：等全部跑完再放 ——
    //    系统相机直拍是一次性服务时 ingest 完就 dispose，不等就是
    //    「最新照片缩略图出不来」（2026-10-14 真机）；
    //  · awaitDerived=false（v0.24.4 一次性会话服务）：**不等** ——
    //    会话收完图要立刻回 App（老板反馈「一次拍多张，很久才进
    //    App」）。派生任务本身是独立 future，dispose 返回后继续
    //    跑完并落库（DB 更新会触发整理页流查询自动刷新）；万一
    //    进程被杀的半成品，backfillThumbnails/backfillHashes 兜底。
    if (awaitDerived && _derived.isNotEmpty) {
      await Future.wait(_derived.toList());
    }
    await _unlockFocusAfterBurst();
    await _controller?.dispose();
    _controller = null;
    await _countController.close();
    await _lastShotController.close();
    await _thumbReadyController.close();
    await _errorController.close();
    await _hintController.close();
  }

  void _emitCount() {
    if (!_countController.isClosed) _countController.add(_sessionCount);
  }

  /// 供 UI 在首帧显示（避免要等第一次快门才有数）。
  int get projectPhotoCountHint => _nextSeq - 1;

  /// 当前是否正在写盘。UI 用它给快门一个极轻的视觉反馈。
  bool get isCapturing => _capturing;

  /// 测试/调试用：直接注入一个假状态（不启动真实相机）。
  @visibleForTesting
  void debugInjectState({
    required String sessionId,
    required int count,
    required int nextSeq,
  }) {
    _sessionId = sessionId;
    _sessionCount = count;
    _nextSeq = nextSeq;
    _emitCount();
  }
}
