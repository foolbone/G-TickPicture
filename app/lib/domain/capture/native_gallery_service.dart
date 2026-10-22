import 'dart:async';

import 'package:flutter/services.dart';

import '../model/native_gallery_photo.dart';

/// 「相册选择器」原生服务（2026-09-29「优化从相册选择照片」）。
///
/// 只是对 `gtick/gallery` 通道几个方法的薄封装，把原生返回的 `Map`
/// 翻译成域模型。纯无状态、单例即可。
///
/// 为什么不用 file_picker：它的系统对话框不支持连选 / 时间定位 / 记忆位置 /
/// 大图预览，而这些是现场取证挑图的高频动作。原生直读 MediaStore +
/// 自建网格 UI 才能把这几点都做出来。
class NativeGalleryService {
  const NativeGalleryService();

  static const MethodChannel _channel = MethodChannel('gtick/gallery');

  /// 相册读取授权状态（进选择器先问这个，别拿查询异常当权限探测）。
  Future<NativeGalleryStatus> galleryStatus() async {
    final res = await _channel.invokeMapMethod<String, Object?>('galleryStatus');
    return NativeGalleryStatus(
      sdkInt: (res?['sdkInt'] as num?)?.toInt() ?? 0,
      granted: (res?['granted'] as bool?) ?? false,
      fullAccess: (res?['fullAccess'] as bool?) ?? false,
    );
  }

  /// 分页查询相册图片，按拍摄时间倒序（[ascending]=true 时正序）。
  ///
  /// [bucket] 非空 = 只看某个相册（顶部下拉）。[limit]/[offset] 用于滚动加载，
  /// 避免一次把整部手机几千张全拉进内存。
  ///
  /// [day] 非空 = **只看这一天**（2026-10-12 v0.20.0 日期过滤）。当天边界
  /// 按**本地时区**算好传下去（[DateTime] 构造即本地时区）—— 原生 SQLite
  /// 直接归日是 UTC，国内会差 8 小时，边界必须在 Dart 算。
  Future<List<NativeGalleryPhoto>> queryImages({
    int limit = 120,
    int offset = 0,
    String? bucket,
    bool ascending = false,
    DateTime? day,
  }) async {
    final res = await _channel.invokeListMethod<Object?>(
      'queryGalleryImages',
      {
        'limit': limit,
        'offset': offset,
        if (bucket != null) 'bucket': bucket,
        'ascending': ascending,
        if (day != null) ...{
          'dayStartMs': DateTime(day.year, day.month, day.day)
              .millisecondsSinceEpoch,
          'dayEndMs': DateTime(day.year, day.month, day.day + 1)
              .millisecondsSinceEpoch,
        },
      },
    );
    return [
      for (final row in res ?? const <Object?>[])
        if (row is Map)
          NativeGalleryPhoto(
            id: (row['id'] as num).toInt(),
            displayName: (row['displayName'] as String?) ?? '',
            dateTaken: _toDate(row['dateTakenMs']),
            sizeBytes: (row['sizeBytes'] as num?)?.toInt() ?? 0,
            bucket: (row['bucket'] as String?) ?? '',
            mimeType: (row['mimeType'] as String?) ?? 'image/jpeg',
          ),
    ];
  }

  /// 有照片的日期（本地时区归日，倒序，上限 2000 天）。
  ///
  /// 日期选择器据此把没有照片的日子置灰 —— 从源头消除「选了没反应」
  /// （旧定位语义下，目标日期没照片时画面纹丝不动且无提示）。
  /// 失败返回空列表（调用方把谓词关掉：全部日期可选，选了没图就空态）。
  Future<List<DateTime>> queryDays({String? bucket}) async {
    try {
      final tz = DateTime.now().timeZoneOffset.inMilliseconds;
      final res = await _channel.invokeListMethod<Object?>(
        'queryGalleryDays',
        {'tzOffsetMs': tz, if (bucket != null) 'bucket': bucket},
      );
      return [
        for (final row in res ?? const <Object?>[])
          if (row is num) _dayFromIndex(row.toInt()),
      ];
    } on PlatformException {
      return const [];
    } catch (_) {
      return const [];
    }
  }

  /// 本地天序号：`(归一化毫秒 + 时区偏移) / 86400000` 取整。
  /// 与原生 `queryGalleryDays` 的归日公式严格一致（v3 核对口径）。
  static int dayIndexOf(DateTime day) =>
      (DateTime(day.year, day.month, day.day).millisecondsSinceEpoch +
              DateTime.now().timeZoneOffset.inMilliseconds) ~/
      Duration.millisecondsPerDay;

  static DateTime _dayFromIndex(int idx) => DateTime.fromMillisecondsSinceEpoch(
        idx * Duration.millisecondsPerDay -
            DateTime.now().timeZoneOffset.inMilliseconds,
      );

  /// 相册分桶清单（顶部「只看某相册」下拉）。
  Future<List<NativeGalleryBucket>> queryBuckets() async {
    final res = await _channel.invokeListMethod<Object?>('queryGalleryBuckets');
    return [
      for (final row in res ?? const <Object?>[])
        if (row is Map)
          NativeGalleryBucket(
            name: (row['bucket'] as String?) ?? '',
            count: (row['count'] as num?)?.toInt() ?? 0,
          ),
    ];
  }

  /// 单张网格缩略图（原生走系统缩略图缓存，绝不解码原图）。
  /// 失败返回 null，格子显示占位图。
  Future<Uint8List?> thumbnail(int id, {int sizePx = 256}) async {
    try {
      return await _channel.invokeMethod<Uint8List>(
        'galleryThumb',
        {'id': id, 'sizePx': sizePx},
      );
    } on PlatformException {
      return null;
    }
  }

  /// 把选中的相册原图流式复制进 cache 临时目录，返回可被
  /// [CaptureService.importFromGallery] 直接消费的本地路径 + 真实拍摄时刻。
  ///
  /// 逐张容错：单张失败不会出现在结果里（被静默跳过），不挡整批导入。
  Future<List<NativeGalleryReadResult>> readImages(List<int> ids) async {
    if (ids.isEmpty) return const [];
    final res = await _channel.invokeListMethod<Object?>(
      'readGalleryImages',
      {'ids': ids},
    );
    return [
      for (final row in res ?? const <Object?>[])
        if (row is Map && row['tempPath'] != null)
          NativeGalleryReadResult(
            id: (row['id'] as num).toInt(),
            tempPath: row['tempPath'] as String,
            displayName: (row['displayName'] as String?) ?? '',
            sizeBytes: (row['sizeBytes'] as num?)?.toInt() ?? 0,
            dateTaken: _toDate(row['dateTakenMs']),
          ),
    ];
  }

  /// 清理导入产生的临时副本（导入完成后调用）。失败静默。
  Future<void> cleanupTemp() async {
    try {
      await _channel.invokeMethod('cleanupGalleryTemp');
    } on PlatformException {
      // cache 系统会兜底清理
    }
  }

  static DateTime? _toDate(Object? v) {
    final ms = (v as num?)?.toInt() ?? 0;
    return ms > 0 ? DateTime.fromMillisecondsSinceEpoch(ms) : null;
  }
}
