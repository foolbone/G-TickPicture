import '../model/delivery_readiness.dart';

/// 打包导出服务 —— **M5 落地**。
///
/// 契约说明（老板 2026-09-26 拍板更新：交付**不设限制条件**）：
/// 归属完整性异常（orphanCount > 0）不再是打包的硬闸门 —— 打包继续，
/// 异常数经 manifest.json 留痕（toSummaryJson 含 orphanCount/canDeliver），
/// 供报告员知情核对。缺口与未指派项本来就只进汇总文件，不阻塞。
abstract interface class ExportService {
  /// 生成交付包。
  ///
  /// [onProgress] 回调 0.0~1.0，UI 上必须有可取消的进度条 ——
  /// 1.5GB 的打包可能要 5 分钟，不能是黑屏等待。
  Future<DeliveryResult> build({
    required String projectId,
    required ExportOptions options,
    void Function(double ratio, String stage)? onProgress,
    bool Function()? isCancelled,
  });

  /// 生成前的预检（§5.5 前置校验）。**不通过就不要开始打包**，
  /// 避免跑 5 分钟后才发现磁盘不够。
  Future<ExportPrecheck> precheck(String projectId, ExportOptions options);

  /// 交付包内各部分的预计体积，用于"生成前先算一遍"。
  Future<ExportEstimate> estimate(String projectId, ExportOptions options);
}

/// 打包选项。对应交付页上的勾选框（§4.3 P9）。
///
/// ⚠️ 2026-09-30：**PDF 联系表已整体移除**。旧实现（`_writeContactSheet`
/// 把 1000+ 张图的字节全攒进内存 + `buildContactSheetPdf` 的 `List<int>`
/// 展开 + `BytesBuilder` 多份副本）在 1000+ 张 / 70+ 组的项目上必然 OOM，
/// 直接让 APP 崩溃退出。老板拍板「不需要 PDF 联系表」→ 连选项一起删掉。
class ExportOptions {
  const ExportOptions({
    this.includeRaw = true,
    this.includeManifest = true,
    this.includeUnused = false,
    this.groupByCarton = true,
    this.compressPhotos = false,
    this.splitVolumes = true,
    this.volumeLimitBytes = defaultVolumeLimitBytes,
  });

  /// 自动分卷的单卷上限（老板 2026-09-30 拍板：500MB，微信单文件 1GB
  /// 上限留一半余量，弱网重传代价也小）。
  static const int defaultVolumeLimitBytes = 500 * 1024 * 1024;

  /// 原始照片（按货品命名）
  final bool includeRaw;

  /// manifest.json
  final bool includeManifest;

  /// 未使用的照片（进 `_未使用/`）
  final bool includeUnused;

  /// 按箱号分文件夹（老板 2026-09-26 拍板：打包时按箱号分文件夹）。
  ///
  /// 默认**开**。清单里一件箱号都没有时自动保持平铺（见
  /// DeliveryPlan.hasCartonData）—— 这个开关只决定"有箱号时是否用"，
  /// 不负责兜底。清掉箱号的旧清单照常出平铺包。
  final bool groupByCarton;

  /// 压缩交付照片。
  ///
  /// **默认关**（2026-10-20 老板拍板：交付默认不要压缩画质）—— 交付包
  /// 直接带原图，取证画质优先；需要发微信、嫌包大时才手动打开。
  ///
  /// 打开后：长边 2560px / JPEG 质量 85 —— 压到「标签、箱号文字依然
  /// 清晰」的程度（老板 09-30 拍板：压缩不能丢关键信息）。原图长边不超
  /// 目标时**原图直出**（零画质损失）；压缩失败的单张回退复制原图。
  /// **App 内的原图永远不被改动**，压坏了随时重打。
  final bool compressPhotos;

  /// 超过单卷上限自动分卷（老板 2026-09-30 拍板：可选开关，默认开）。
  ///
  /// 每卷都是**独立可解压**的完整 ZIP（含 manifest.json），卷内按交付
  /// 顺序整文件分配，绝不把一张照片拆进两卷。关掉它就出单个 ZIP
  /// （走网盘等不限大小的渠道时用）。
  final bool splitVolumes;

  /// 单卷上限字节。放进选项而非写死常量：测试用小上限就能驱动
  /// 多卷路径，不需要造 500MB 数据。UI 不暴露。
  final int volumeLimitBytes;

  Map<String, Object?> toJson() => {
        'includeRaw': includeRaw,
        'includeManifest': includeManifest,
        'includeUnused': includeUnused,
        'groupByCarton': groupByCarton,
        'compressPhotos': compressPhotos,
        'splitVolumes': splitVolumes,
        'volumeLimitBytes': volumeLimitBytes,
      };
}

/// 预检结果。
class ExportPrecheck {
  const ExportPrecheck({
    required this.readiness,
    required this.estimatedBytes,
    required this.freeBytes,
    required this.warnings,
  });

  /// 归属完整性等硬性校验（§6.3）
  final DeliveryReadiness readiness;

  final int estimatedBytes;
  final int freeBytes;

  /// 不阻塞交付、但需要显性提示的问题
  final List<String> warnings;

  /// 硬闸门：归属完整性被破坏 → 必须阻断。
  bool get blocked => !readiness.canDeliver;

  /// 空间不足 → 阻断（跑了 5 分钟才失败更糟）。
  bool get enoughSpace => freeBytes >= estimatedBytes * 1.5;
}

/// 体积估算。
class ExportEstimate {
  const ExportEstimate({
    required this.rawBytes,
    required this.totalBytes,
    required this.photoCount,
    required this.itemCount,
  });

  final int rawBytes;
  final int totalBytes;
  final int photoCount;
  final int itemCount;

  /// 超过这个体积就建议改走网盘（微信直传体验差）
  bool get shouldPreferWebdav => totalBytes > 200 * 1024 * 1024;
}

/// 一卷 ZIP（2026-09-30 分卷交付）。单卷交付时列表长度为 1。
class DeliveryVolume {
  const DeliveryVolume({required this.path, required this.bytes});

  final String path;
  final int bytes;

  /// 文件名（UI 显示用）。
  String get fileName => path.split('/').last.split('\\').last;
}

/// 打包产物。
class DeliveryResult {
  const DeliveryResult({
    required this.deliveryId,
    required this.zipPath,
    required this.folderPath,
    required this.bytes,
    required this.itemCount,
    required this.photoCount,
    this.volumes = const [],
  });

  final String deliveryId;

  /// ZIP 包路径（单卷 = 那个包；多卷 = 第一卷，DB 记录兼容用）
  final String zipPath;

  /// 未压缩的目录（可单独 SAF 导出）
  final String folderPath;

  /// 全部卷的字节总和
  final int bytes;
  final int itemCount;
  final int photoCount;

  /// 分卷产物。空 = 旧记录（v0.11 及以前只有单 zip 字段）。
  final List<DeliveryVolume> volumes;

  /// 是否分了多卷（UI 显示「N 卷」用）。
  bool get isSplit => volumes.length > 1;
}
