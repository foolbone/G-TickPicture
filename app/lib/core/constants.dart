/// 全项目共享常量。
///
/// 规则：任何"魔法数字"都必须定义在这里，并说明**来源**与**调整依据**。
/// 设计方案的 §2.2 / §5.3 / §8.1 定义了这些值的初始值，
/// 灰度期用真实数据校准后回写到本文件，不要在调用点就地改数。
class AppConst {
  const AppConst._();

  // ─────────────────────────────────────────────────────────
  // 分组（2026-09-29 老板拍板：**按批次一组**）
  //
  // 旧时序聚类三常量（groupGap 45s / groupMaxPhotos 12 /
  // albumTrustworthySpanMs 2000ms）已随「按时序分组」功能一起移除：
  // 一批（captureSession）就是一组，间隔与上限不再是可调参数。
  // ─────────────────────────────────────────────────────────

  /// 采集批次续接窗口：退出相机页后在此时间内再次进入，**续用上一个
  /// 已结束的相机批次**而不是新开一个（2026-09-27）。
  ///
  /// 依据：现场真实节奏是「拍一件 → 对照清单 → 再拍下一件」，两次进入
  /// 相机页往往只隔十几秒。批次一断，同一段连拍就被拆成两批 ——
  /// 按批次分组的语义下，它们会是两组（老板原话：
  /// 「连续拍摄的照片为一组」）。5 分钟：覆盖对照清单/走动换位/
  /// 被电话打断的合理间隙；超过它说明是真正的两段作业，分开批次
  /// 才符合审计语义。
  static const Duration sessionResumeWindow = Duration(minutes: 5);

  // ─────────────────────────────────────────────────────────
  // OCR 建议（设计方案 §5.3.2）
  //
  // 注意：这里的数值只用于「排序」与「标冲突」，
  //       **不再用于任何"自动归档"判定** —— 归属只能由人确认。
  // ─────────────────────────────────────────────────────────

  /// 匹配基数：完全相等
  static const double matchBaseExact = 0.98;

  /// 匹配基数：清单编码是 OCR token 的前缀
  static const double matchBasePrefix = 0.86;

  /// 匹配基数：编辑距离 = 1
  static const double matchBaseEdit1 = 0.88;

  /// 匹配基数：编辑距离 = 2
  static const double matchBaseEdit2 = 0.72;

  /// 编辑距离上限，超过即丢弃候选
  static const int matchMaxEditDistance = 2;

  /// token 长度下限，太短的 token 不参与匹配（噪声）
  static const int matchMinTokenLength = 3;

  /// 组内分歧阈值：第一名与第二名差值比例 < 此值 → 标 conflict
  static const double conflictScoreGap = 0.15;

  /// 组级置信度低于此值 → 标 no_suggestion
  static const double noSuggestionBelow = 0.40;

  /// 「一键确认高置信」的准入线
  static const double bulkConfirmThreshold = 0.90;

  /// OCR 输入图长边像素。降分辨率提速，仍足够识别印刷体。
  static const int ocrImageLongEdge = 1600;

  // ─────────────────────────────────────────────────────────
  // 采集（设计方案 §5.2 / §8.1 / §8.2）
  // ─────────────────────────────────────────────────────────

  /// 长按快门连拍的间隔（毫秒）。
  /// 依据：§5.2「长按快门 = 连拍（每 400ms 一张）」，与"快门到可再次拍摄
  /// ≤ 400ms"是同一个数——连拍间隔不能小于单张落盘时间，否则会积压。
  static const int burstIntervalMs = 400;

  /// 变焦快捷档位（倍率，09-26 老板诉求「相机需要支持变焦」）。
  /// 捏合可连续变焦；按钮只给常用档，超出镜头变焦能力的自动隐藏。
  ///
  /// ⚠️ 这里**只有 ≥1 的放大档**（2026-10-09 修订）：缩小档不写死 0.6。
  /// 「广角/0.6x」是镜头能力，只能由设备上报的 minZoom 决定 ——
  /// 写死 0.6 会让"设备只支持到 0.7"的机器显示一个按了没反应的档，
  /// 也会让"根本不能缩小"的机器看起来少了个功能却不说原因。
  /// 真实 minZoom 由 [CameraCaptureService.zoomStepsFor] 补在最前面。
  static const List<double> zoomStepCandidates = <double>[1, 2, 5];

  /// 单次连拍的最大张数。防止长按误触拍出上百张。
  static const int burstMaxPhotos = 20;

  /// 采集前按此值估算单张体积，用于存储空间预检（§8.2）。
  /// 1200 万像素 JPEG 的典型值；宁可估高，不足时提示得早比写失败好。
  static const int estimatedPhotoBytes = 5 * 1024 * 1024;

  /// 存储预检的写探针大小。
  ///
  /// 取 4 MB 而不是 1 KB：空间濒临耗尽时小文件往往还能写进去，
  /// 但相机一张就要几 MB —— 探针太小会给出**假阳性**（报"能拍"却很快写失败）。
  static const int storageProbeBytes = 4 * 1024 * 1024;

  /// 存储预检要求的余量倍数（§8.2 / §5.5 的 freeSpaceFactor 同源）。
  static const double captureFreeSpaceFactor = 1.5;

  /// 「结束采集」需要长按的时长 —— 防误触（§4.3 P4）。
  static const Duration endSessionHoldDuration = Duration(seconds: 1);

  /// 缩略图 JPEG 质量
  static const int thumbQuality = 78;

  // ─────────────────────────────────────────────────────────
  // 缩略图 / 文件
  // ─────────────────────────────────────────────────────────

  /// 列表缩略图长边
  static const int thumbLongEdge = 256;

  /// 单个采集批次（capture_session）的照片数软上限。
  /// 仅用于提示，不阻断 —— 按 v3.1 真实规模（600~1600 张）设定。
  static const int sessionSoftLimit = 1600;

  /// 系统相册里的根文件夹名（P4 · 诉求「拍照要进手机相册」）。
  ///
  /// 最终布局：`相册 / 集刻-采集 / {项目名} / 20260924_103012_00003.jpg`
  /// 按项目分文件夹 —— 一天跑两三个项目时，相册里一眼分得开。
  static const String galleryRootAlbum = '集刻-采集';

  // ─────────────────────────────────────────────────────────
  // 拍照提示 / 回看（2026-10-10「拍照体验对标系统相机」v0.19.0）
  //
  // 阈值来源：缩略图平均亮度按 Rec.601 归一到 0~255。仓库预检的典型
  // 画面是仓库顶灯 + 外包装纸箱：正常室内 ~90-150，黄昏/角落 ~40-70，
  // 几乎全黑 <30。分级与 [CameraCaptureService.nextAutoEv] 配套使用；
  // 现场校准后回写到这里，不要在调用点就地改数。
  // ─────────────────────────────────────────────────────────

  /// 缩略图平均亮度低于此值 → 「光线不足」提示 + 自动曝光补偿开始加档。
  static const int lowLightLuma = 64;

  /// 低于此值 → 强提示（编码/唛头在这种亮度下基本拍不清）。
  static const int veryLowLightLuma = 36;

  /// 亮度高于此值（且自动补偿在加）→ 逐步退档回 0，防止白天残留补档过曝。
  static const int autoEvBrightLuma = 110;

  /// 暗光自动曝光补偿的每档步进（EV）。0.5 与相机插件常见硬件步长一致。
  static const double autoEvStep = 0.5;

  /// 暗光自动曝光补偿的封顶值（EV）。
  ///
  /// 依据：补档是"下一张受益"的慢反馈，补到 1.5 已是显著提亮；再高就
  /// 侵入"画面失真"的领域 —— 取证照片宁可偏暗也要真实，这是上限的
  /// 存在理由。用户手动补偿（±4）不受此限制。
  static const double autoEvMax = 1.5;

  /// 手抖 jerk RMS（m/s²）≥ 此值 → 轻度抖动（只记录，不提示 —— 提示
  /// 必须可操作，轻度抖动提示只会变成噪音；铁律 16）。
  static const double shakeMildJerk = 1.0;

  /// 手抖 jerk RMS ≥ 此值 → 强提示「稳一下再按」（明显手抖 1.5~4 的
  /// 区间取下限：抖到这个程度拍唛头小字必糊，提示是可操作的）。
  static const double shakeHeavyJerk = 2.5;

  // ─────────────────────────────────────────────────────────
  // 交付（设计方案 §5.5）
  // ─────────────────────────────────────────────────────────

  /// 超过此体积时：ZIP 分片、并提示改走网盘
  static const int splitThresholdBytes = 50 * 1024 * 1024;

  /// 生成交付包前要求的剩余空间倍数
  static const double freeSpaceFactor = 1.5;

  /// 目录名里品名简称的最大字数
  static const int dirNameShortMax = 12;

  // ─────────────────────────────────────────────────────────
  // WebDAV 上传（设计方案 §5.5）
  // ─────────────────────────────────────────────────────────

  static const int uploadMaxParallel = 3;
  static const int uploadMaxAttempts = 5;

  /// 退避间隔（分钟）：1 / 5 / 15 / 60
  static const List<int> uploadBackoffMinutes = <int>[1, 5, 15, 60];

  // ─────────────────────────────────────────────────────────
  // 导入校验（设计方案 §5.1）
  // ─────────────────────────────────────────────────────────

  /// 超过此行数时提示"清单异常大，是否确认"
  static const int checklistWarnRows = 5000;

  /// 文件名不安全字符（会被替换为 _ ）
  static const List<String> unsafeFilenameChars = <String>[
    '/', '\\', ':', '*', '?', '"', '<', '>', '|',
  ];
}
