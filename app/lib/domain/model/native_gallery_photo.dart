/// 相册选择器读到的单张照片（原生 MediaStore 直读，2026-09-29）。
///
/// 只放 UI 需要展示与落库的字段 —— 不放文件路径（路径要等用户点「导入」
/// 时由原生日用 ContentResolver 流式复制出来，见 [NativeGalleryService.readImages]）。
/// 住 `domain/model/` 是架构纪律：UI 层需要具名类型时不能 import `data/`。
class NativeGalleryPhoto {
  const NativeGalleryPhoto({
    required this.id,
    required this.displayName,
    required this.dateTaken,
    required this.sizeBytes,
    required this.bucket,
    required this.mimeType,
  });

  /// MediaStore 行 id（导入时据此定位内容 URI）。
  final int id;

  /// 文件名（如 IMG_20260922_085012.jpg）。
  final String displayName;

  /// 真实拍摄时刻：DATE_TAKEN 优先，缺失退化 DATE_ADDED。
  /// null = 两者都缺（极端情况，落库端退 EXIF/mtime 老路）。
  final DateTime? dateTaken;

  /// 字节数（UI 展示文件大小用）。
  final int sizeBytes;

  /// 所属相册（bucket_display_name），如「Camera」「WeiXin」「Screenshots」。
  final String bucket;

  /// MIME 类型（image/jpeg / image/png / image/heic …）。
  final String mimeType;

  /// 同一天（本地时区，按日期截断）的毫秒起点 —— 给「全选本日」用。
  DateTime? get dayStart {
    final d = dateTaken;
    return d == null
        ? null
        : DateTime(d.year, d.month, d.day);
  }
}

/// 相册分桶（顶部「只看某相册」下拉项）。
class NativeGalleryBucket {
  const NativeGalleryBucket({required this.name, required this.count});

  final String name;
  final int count;
}

/// 相册读取授权状态（原生 `galleryStatus` 的翻译，2026-09-29 空态排查产物）。
///
/// [granted] 含 Android 14 的「仅允许选中的照片」部分授权 —— 那种状态下
/// MediaStore 只回用户勾选过的行，查询不报错但结果骤减；UI 必须拿
/// [partial] 明说，不能让用户以为相册真的空了。
class NativeGalleryStatus {
  const NativeGalleryStatus({
    required this.sdkInt,
    required this.granted,
    required this.fullAccess,
  });

  final int sdkInt;
  final bool granted;
  final bool fullAccess;

  /// 授权了，但只是「仅允许选中的照片」。
  bool get partial => granted && !fullAccess;
}

/// 用户点「导入」后，由原生把选中原图复制出来的临时结果。
///
/// [tempPath] 是 cache 下的临时副本（已带真实拍摄时刻），直接喂给
/// [CaptureService.importFromGallery]；[dateTaken] 一路带进落库，
/// 不再需要「按文件名+大小回查」的 hack。
class NativeGalleryReadResult {
  const NativeGalleryReadResult({
    required this.id,
    required this.tempPath,
    required this.displayName,
    required this.sizeBytes,
    required this.dateTaken,
  });

  final int id;
  final String tempPath;
  final String displayName;
  final int sizeBytes;
  final DateTime? dateTaken;
}
