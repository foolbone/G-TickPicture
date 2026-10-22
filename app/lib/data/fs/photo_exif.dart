import 'dart:io';
import 'dart:isolate';

import 'package:image/image.dart' as img;

import '../../core/logger.dart';

/// 照片的 EXIF 拍摄时间。
///
/// 为什么需要它（§5.3.1 规则 5）：相册导入的照片，文件修改时间
/// 反映的是「复制 / 转发到本机的时刻」，不是「按下快门的时刻」。
/// 微信转发过的照片，修改时间全部是转发那一刻 → 排序与交付命名
/// 失去真实先后。EXIF 的 `DateTimeOriginal` 才是快门时刻。
///
/// 失败语义：**任何一步失败都返回 null**（文件不存在 / 非 JPEG /
/// 没有 EXIF / 时间字符串格式不认识）—— 调用方退化用文件修改时间。
/// EXIF 读不出来只影响排序与交付命名，绝不能让导入失败。
class PhotoExif {
  const PhotoExif._();

  /// 读拍摄时间。走 isolate，避免大文件的 I/O 卡 UI 线程
  /// （一次导入可能几十张，每张 3~8 MB）。
  static Future<DateTime?> takenAt(String path) =>
      Isolate.run(() => _readSync(path));

  static DateTime? _readSync(String path) {
    try {
      final f = File(path);
      if (!f.existsSync()) return null;
      final bytes = f.readAsBytesSync();

      final exif = img.decodeJpgExif(bytes);
      if (exif == null) return null;

      // DateTimeOriginal：按下快门的时刻（首选，在 EXIF SubIFD 里）
      final original = _parse(exif.exifIfd['DateTimeOriginal']?.toString());
      if (original != null) return original;

      // DateTime：照片文件的最后修改时刻（次选，在 IFD0 里）。
      // 相机直拍一般两者都有；只写了 DateTime 的（少数老机型）也认。
      return _parse(exif.imageIfd['DateTime']?.toString());
    } catch (e) {
      // 损坏文件 / 格式不认 —— 记日志、退化，绝不抛
      Log.d('PhotoExif', 'read failed for $path: $e');
      return null;
    }
  }

  /// EXIF 规范的时间格式是 `yyyy:MM:dd HH:mm:ss`（日期用冒号分隔）。
  ///
  /// 现实里的手机厂商经常不守规矩（`-` 或 `/` 分隔、带时区尾巴），
  /// 所以这里宽进严出：分隔符放行 `: - / .`，但数值区间逐位校验 ——
  /// 越界直接 null（`DateTime` 构造会静默进位，13 月会变明年 1 月，
  /// 那种"能解析但明显不是真时间"的字符串宁可不要）。
  static DateTime? _parse(String? raw) {
    if (raw == null) return null;
    final s = raw.trim();
    if (s.length < 19) return null;

    final m = RegExp(
      r'^(\d{4})[:\-/.](\d{1,2})[:\-/.](\d{1,2})[ T](\d{1,2}):(\d{1,2}):(\d{1,2})',
    ).firstMatch(s);
    if (m == null) return null;

    final y = int.parse(m.group(1)!);
    final mo = int.parse(m.group(2)!);
    final d = int.parse(m.group(3)!);
    final h = int.parse(m.group(4)!);
    final mi = int.parse(m.group(5)!);
    final sec = int.parse(m.group(6)!);

    // 逐位校验：只接受物理上可能的时刻。
    // 年份下限 2000 —— 预检拍照发生在今天，2000 年前的时钟必然是
    // 相机没电后重置的假时间（1970/1980 最常见），用它排序是纯噪声。
    if (y < 2000 || y > 2100) return null;
    if (mo < 1 || mo > 12) return null;
    if (d < 1 || d > 31) return null;
    if (h > 23 || mi > 59 || sec > 59) return null;

    return DateTime(y, mo, d, h, mi, sec);
  }
}
