import 'package:flutter/services.dart';

import '../../core/logger.dart';

/// 从媒体库回查照片「真实拍摄时刻」的薄封装（2026-09-29）。
///
/// 为什么需要它：相册导入走 file_picker，它只回传**缓存副本路径** ——
/// 副本的修改时间 = 复制那一刻（导入时刻），原文件的元数据全丢了。
/// 微信保存图 / 截图 / 部分机型的 HEIC 又没有 EXIF，落库时间便整批
/// 退化成导入时刻 → 排序与交付命名失去真实先后
/// （「导入的照片时间是导入时刻」的根因；分组不受影响 —— 一批一组）。
///
/// 解法：file_picker 同时回传原始**文件名与字节数**，这对键在媒体库
/// 里几乎唯一 —— 拿它回查 MediaStore 的 DATE_TAKEN 找回真实时刻。
/// 查不到（下载目录等非媒体库文件 / 权限受限）返回 null，调用方退化
/// 走 EXIF → 文件时间的老路 —— **尽力而为，绝不阻塞导入**（与
/// `PhotoExif` 同一条纪律：时间读不出来只影响排序与交付命名，不影响
/// 可用性）。
class GalleryMetaService {
  const GalleryMetaService();

  static const MethodChannel _channel = MethodChannel('gtick/gallery');

  /// 与 [items] 按下标对齐的拍摄时刻；查不到为 null。
  Future<List<DateTime?>> dateTakenByNames(
    List<({String name, int sizeBytes})> items,
  ) async {
    if (items.isEmpty) return const [];
    try {
      final res = await _channel.invokeListMethod<Object?>(
        'queryDateTakenByNames',
        {
          'items': [
            for (final it in items)
              {'name': it.name, 'size': it.sizeBytes},
          ],
        },
      );
      return [
        for (var i = 0; i < items.length; i++)
          _msToDateTime(_msAt(res, i)),
      ];
    } on PlatformException catch (e) {
      // 原生侧任何问题（低版本 / 查询失败）都整批静默退化 ——
      // 时间查不到只影响分组质量，绝不能让导入失败。
      Log.d('GalleryMeta', 'dateTakenByNames failed: $e');
      return List<DateTime?>.filled(items.length, null);
    }
  }

  /// 结果比请求短（理论不该发生）按下标安全退化，不抛 RangeError。
  static Object? _msAt(List<Object?>? res, int i) =>
      (res != null && i < res.length) ? res[i] : null;

  /// 0 = 媒体库没记时间（或没查到）→ null。
  static DateTime? _msToDateTime(Object? raw) {
    final ms = (raw as num?)?.toInt() ?? 0;
    if (ms <= 0) return null;
    return DateTime.fromMillisecondsSinceEpoch(ms);
  }
}
