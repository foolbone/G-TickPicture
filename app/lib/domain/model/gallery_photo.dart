/// 存入相册的一张图（P4 · 诉求「拍照要进手机相册」）。
///
/// 三样东西够了 —— 相册侧不需要知道项目结构、更不需要知道归属。
class GalleryPhoto {
  const GalleryPhoto({
    required this.srcPath,
    required this.displayName,
    this.takenAt,
  });

  /// App 私有目录里的原图路径（**复制源，永不被移动/删除**）。
  final String srcPath;

  /// 相册里显示的文件名。用原图文件名（含 5 位序号），与原图一一对应 ——
  /// 事后核对、或重排交付包时能对上号。
  final String displayName;

  /// 拍摄时刻。不填的话相册按插入时间排序（批量补存时会乱序）。
  final DateTime? takenAt;
}

/// 批量补存的结果。
///
/// 三档计数，对应原生写入点的三种结局：
///  · [saved]   —— 本次新写入；
///  · [skipped] —— 相册里已有同名文件，幂等跳过（**不算失败** ——
///    去重做在原生写入点，自动存过、手动补存不会出第二份）；
///  · [failed]  —— 真失败（原因见 [reason]）。
class GallerySaveResult {
  const GallerySaveResult({
    required this.saved,
    this.skipped = 0,
    required this.failed,
    this.reason,
  });

  final int saved;

  /// 已在相册里、自动跳过未重复写入的张数。
  final int skipped;

  final int failed;

  /// 失败原因原文（最后一条）。同一原因在批次里通常批量出现，
  /// 所以只留一条就够 —— UI 要展示的是「为什么没成」，不是日志流。
  final String? reason;

  bool get isEmpty => saved == 0 && skipped == 0 && failed == 0;
}
