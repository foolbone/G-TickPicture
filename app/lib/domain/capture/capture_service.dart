import 'dart:async';

/// 导入进度回调：`(已完成, 总数)`。
///
/// 加它的理由（2026-09-29 全 App 性能排查）：导入 N 张要复制 N 份原图，
/// 现场选上百张时是几十秒的等待。没有进度，用户只看到"点了没反应"，
/// 主观感受就是"卡死"——进度条不改变耗时，但改变"是否可信"。
typedef ImportProgress = void Function(int done, int total);

/// 采集过程中出问题的**种类**。
///
/// 采集期禁弹窗，但"按了快门没反应"绝不能只有一行日志 —— 用户只会
/// 以为手机卡了然后狂点（现场还可能误触连拍）。所以失败必须分类上报，
/// 由 UI 决定给什么动作（§5.2 禁的是系统主动打断，不是可操作提示）。
enum CaptureErrorKind {
  /// 写文件/入库失败 —— 真正的硬故障，采集必须停（数据在丢）。
  write,

  /// 这一张没拍成（相机忙、对焦未完成、存储瞬时异常）。
  /// 现场动作：再按一次快门。
  shot,

  /// 连拍期间有张没拍成（相机来不及）。现场动作：可以再连拍一次补。
  burstDropped,
}

/// 一次采集错误。UI 拿它换算成一句**可执行**的话。
class CaptureError {
  const CaptureError(this.kind, this.message, {this.count});

  final CaptureErrorKind kind;

  /// 技术描述（给日志与排查用；**不要**直接原样显示给用户）。
  final String message;

  /// [CaptureErrorKind.burstDropped] 用：这次连拍丢了多少张。
  final int? count;

  /// 面向用户的提示：**必须带下一步动作**。
  ///
  /// ⚠️ 文案住在这里而不是 UI：提示口径一旦有两份（页面一份、
  /// 提醒一份）就会漂 —— 而"照片少了但没人告诉"是这类工具最伤人的
  /// 一种 bug（铁律 23 的同源精神）。
  String get hint => switch (kind) {
        CaptureErrorKind.write => '保存失败 · 已暂停拍摄，请检查存储空间',
        CaptureErrorKind.shot => '这张没拍上 · 请再按一次快门',
        CaptureErrorKind.burstDropped =>
          '连拍有 ${count ?? 0} 张没拍成 · 可以再连拍一次补',
      };
}

/// 一次采集**状况提示**（不是错误 —— 拍摄本身成功了，是环境提醒）。
///
/// 与 [CaptureError] 的区别：错误 = 这张没拍上/没存上，必须处理；
/// 提示 = 拍上了，但光线这类环境因素值得知道。文案同住这里
/// （铁律 23：提示口径不许有两份），且必须**可操作**（铁律 16）。
enum CaptureHintKind {
  /// 光线不足（缩略图平均亮度低于 AppConst.lowLightLuma）。
  /// 自动曝光补偿已开始加档，但仍暗时提示换位/开灯。
  lowLight,

  /// 光线很差（低于 AppConst.veryLowLightLuma）—— 强提示。
  veryLowLight,
}

/// 一次状况提示。UI 拿 [hint] 直接显示（短暂 HUD，不打断拍摄）。
class CaptureHint {
  const CaptureHint(this.kind, this.message);

  final CaptureHintKind kind;

  /// 技术描述（日志用）。
  final String message;

  /// 面向用户的一句话，必须带下一步。
  String get hint => switch (kind) {
        CaptureHintKind.lowLight =>
          '光线较暗 · 已自动提高曝光，仍暗建议开灯或换角度',
        CaptureHintKind.veryLowLight => '光线很差 · 建议开灯或换亮处再拍',
      };
}

/// 采集服务 —— M2 实现见 `camera_capture_service.dart`。
///
/// 接口刻意**没有任何识别/建议相关的方法**。
/// 理由：采集页是"零界面"的，一旦接口里出现"识别结果"，
/// M4 就会顺手把 OCR 拖回采集流程里，那正是 v2.0 犯的错。
///
/// ┌─ 架构约束（tools/check_architecture.ps1 会强制）───────────┐
/// │ 本文件所属目录 domain/capture/ 不得 import domain/suggest/ │
/// │ 也就是说：采集流程在编译期就无法接触 OCR。                  │
/// └───────────────────────────────────────────────────────────┘
abstract interface class CaptureService {
  /// 当前批次（capture_session）id。null 表示未在采集中。
  String? get activeSessionId;

  /// 本批次已拍张数。
  int get sessionPhotoCount;

  /// 张数变化流（UI 据此更新顶部数字与胶片条）。
  Stream<int> get photoCountStream;

  /// 新照片落库的通知流（每 ingest 一张发一次其 id）。
  ///
  /// 采集页系统相机路径用它做收图进度 HUD（v0.24.4）；内置路径的
  /// 胶片条刷新也走它（thumbReady 之前的即时反馈）。
  Stream<String> get lastShotStream;

  /// 开始一次采集。写入 capture_sessions(source=camera)。
  ///
  /// ⚠️ 若项目下已有**未结束**的批次，实现必须**续接**它而不是新开——
  /// 这是 §8.2「息屏/来电/切后台自动暂停、回来自动续接同一批次」的落点。
  Future<String> startSession(String projectId);

  /// 快门：拍一张并落盘。
  ///
  /// 实现要求（§8.1）：快门到可再次拍摄 ≤ 400ms。
  /// 做法：原图直写文件（含 flush），主线程只收路径；
  /// 缩略图与尺寸异步回填，DB 单事务提交。
  ///
  /// 返回新照片的 id；相机未就绪或拍摄失败时返回空串。
  Future<String> capture(String projectId);

  /// 把**系统相机**拍好的照片文件收进当前采集批次（2026-10-14 v0.22.0
  /// 「拍照委托系统相机」的快门落点）。
  ///
  /// 拍照发生在系统相机里（全尺寸原图落在 App 临时文件），本方法负责
  /// 剩下的**全部存量管线**，与 [capture] 的区别只是「字节从哪来」：
  /// 续接当前 camera 批次 → EXIF 拍摄时刻 → 原文件**同根 rename 原子
  /// 移动**进项目目录（零拷贝，比写字节更省）→ 入库 → 相册镜像 →
  /// 缩略图/指纹派生，一环不少。
  ///
  /// [filePath] 临时文件绝对路径。文件缺失/为空 = 这张没拍上（个别 ROM
  /// 不尊重 EXTRA_OUTPUT）——上报 shot 错误、**不结束批次**（用户在连续
  /// 拍节奏里，不能因一张失败就收摊），返回空串。
  Future<String> captureFromFile(
    String projectId,
    String filePath, {
    DateTime? takenAtOverride,
    bool move = true,
    bool galleryMirror = true,
  });

  /// 连拍：每 [intervalMs] 一张，共 [count] 张。
  ///
  /// 用 Stream 而不是 Future<List> 的理由：UI 要能一张一张地
  /// 看到张数跳动 —— 那是现场唯一的反馈。
  Stream<String> burst(String projectId, {int count, int intervalMs});

  /// 切换前后摄。
  Future<void> switchCamera();

  /// 对焦/测光到预览坐标（0.0~1.0）。
  Future<void> focusAt(double x, double y);

  /// 快门按下瞬间触发一次对焦（"半按对焦"，2026-10-09 现场快拍诉求）。
  ///
  /// 把 AF 提前到"手指按下→抬起"这段白等的时间里跑，抬手时焦距已合上，
  /// 快门几乎没有延迟。不动曝光、不画对焦框、带节流（连拍不重复触发）。
  ///
  /// 相机未就绪或机型不支持时静默 no-op —— 预对焦是加速项，不是必经步骤。
  Future<void> prepareFocus();

  /// 设置曝光补偿（-4.0 ~ 4.0）。
  Future<void> setExposureCompensation(double ev);

  /// 相册导入：把选中的照片并入当前项目的"待整理池"。
  ///
  /// 它们会写成 `source = album` 的批次，与相机批次分列（审计可分）。
  ///
  /// [takenAts] 与 [filePaths] 按下标对齐的**拍摄时刻覆盖值**（可整体为 null）。
  /// 微信导入必传：微信保存的图没有 EXIF，且旧链路只拿到临时副本的
  /// 修改时间（=导入时刻），整批时间戳挤在同一两秒，排序与交付命名
  /// 会失去真实先后（分组不受影响 —— 一批一组）。
  /// 覆盖值为 null 的下标退回 EXIF → 文件修改时间的老路。
  ///
  /// [note] 批次备注（审计留痕用）。微信导入传「微信导入 N 张」，
  /// 缺省为「相册导入 N 张」。
  ///
  /// 返回**成功入库的照片 id**（数量 = length；与入参顺序不保证一致，
  /// 不存在的文件会被跳过）。返回 id 而不是张数，是因为「往指定组里
  /// 补照片」（2026-09-30）要在导入后把这些照片挂到目标组 ——
  /// 挂组是 OrganizeRepository 的地盘，采集服务只负责交出"导入了哪些"。
  Future<List<String>> importFromGallery(
    String projectId,
    List<String> filePaths, {
    String? note,
    List<DateTime?>? takenAts,
    ImportProgress? onProgress,
  });

  /// 补齐本项目缺失的缩略图，返回补上的张数。
  ///
  /// 缩略图是入库后异步生成的，列表不会自动刷新 —— 进整理页前跑一次，
  /// 补完由调用方 invalidate 刷新即可见。
  Future<int> backfillThumbnails(String projectId);

  /// 补算本项目缺失的内容指纹，返回补上的张数。
  ///
  /// 指纹是**重复照片提示**的唯一依据（老板 2026-10-04「照片不能重复」）。
  /// v4 迁移只加列不回填，所以老照片一律 NULL，由这个方法分批补算；
  /// 补算完成前 UI 显示「正在核查」而不是「无重复」。
  Future<int> backfillHashes(String projectId);

  /// 暂停当前批次（释放相机，保留 session 与计数）。
  Future<void> pauseSession();

  /// 错误上报流（写盘失败 / 单张没拍成 / 连拍丢张）。
  ///
  /// 为什么不靠返回值：落盘已改成后台队列（见 `SerialQueue`），失败
  /// 发生在**快门返回之后**——没有返回值可挂。静默失败在采集现场等于
  /// "照片凭空少了"。
  Stream<CaptureError> get errorStream;

  /// 结束当前批次。
  Future<void> endSession();

  /// 释放相机资源。离开采集页时调用。
  ///
  /// [awaitDerived]（2026-10-15 v0.24.4）：是否等在途派生任务
  /// （缩略图 / 相册镜像 / 指纹）收尾再放。
  ///  · true（默认）= 页面级服务退出用：等完再放，胶片条不丢
  ///    thumbReady 刷新事件（2026-10-14 真机「最新照片缩略图
  ///    显示不出来」的修复语义）；
  ///  · false = 一次性会话服务（系统相机连拍收图）用：ingest 完
  ///    立刻回 App（老板反馈「拍完很久才进来」）。派生是独立
  ///    future，不等也会继续跑完并落库；万一半路中断，由
  ///    [backfillThumbnails] / [backfillHashes] 在整理页兜底。
  Future<void> dispose({bool awaitDerived = true});
}

/// 采集期被禁止的行为 —— 用注释固化，M2 实现时对照检查。
///
/// ❌ 不调用 OCR / 任何 SuggestService
/// ❌ 不发起任何 HTTP 请求（包括 WebDAV 上传）
/// ❌ 不弹任何 Dialog / SnackBar（唯一例外：存储空间不足）
/// ❌ 不写 photo.item_id（归属属于整理阶段）
/// ❌ 不在预览帧上做任何逐帧分析（耗电 + 发热 + 掉帧）
