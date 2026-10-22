import 'package:flutter/services.dart';

/// 原生侧拿到的设备画像。
///
/// 这些值 Dart 侧**无从获取**，而它们直接决定"一次能干多少活"：
/// 低配机上按高配参数并发解码 20 张 4000×3000 的图 = 内存峰值翻倍 =
/// 卡顿或 OOM 重启。有了它，并发数 / 分页大小 / 缩略图尺寸都能按机器降级。
class DeviceProfile {
  const DeviceProfile({
    required this.totalMemMB,
    required this.memoryClassMB,
    required this.lowRam,
    required this.cpuCores,
    required this.sdkInt,
  });

  /// 不可用时的保守画像（按中低配处理，宁可保守也不冒险）。
  const DeviceProfile.unknown()
      : totalMemMB = 0,
        memoryClassMB = 0,
        lowRam = false,
        cpuCores = 2,
        sdkInt = 0;

  final int totalMemMB;

  /// 单进程可用内存上限（MB）—— 比 totalMem 更能反映"能开多大缓冲"。
  final int memoryClassMB;

  /// 系统自己判定的低内存设备。
  final bool lowRam;
  final int cpuCores;
  final int sdkInt;
}

/// 一个缩略图任务（原生侧串行执行）。
class ThumbJob {
  const ThumbJob({
    required this.srcPath,
    required this.dstPath,
    required this.longEdge,
    this.quality,
  });

  final String srcPath;
  final String dstPath;
  final int longEdge;

  /// JPEG 质量；null = 原生用默认（78）。
  final int? quality;

  Map<String, Object?> toMap() => {
        'src': srcPath,
        'dst': dstPath,
        'px': longEdge,
        if (quality != null) 'quality': quality,
      };
}

class ThumbResult {
  const ThumbResult({
    required this.ok,
    required this.width,
    required this.height,
    this.luma,
  });

  final bool ok;
  final int width;
  final int height;

  /// 平均亮度（0~255，Rec.601 luma）。**null = 没量到**（解码失败 /
  /// 老版本原生不支持）。
  ///
  /// 只用于「光线够不够」的提示，**绝不参与任何画面修改** ——
  /// 取证原图一个像素都不许动（2026-10-10 拍照体验对标）。
  final int? luma;
}

/// 一个交付照片压缩任务（原生侧串行执行）。
class CompressJob {
  const CompressJob({
    required this.srcPath,
    required this.dstPath,
    this.longEdge = 2560,
    this.quality = 85,
  });

  final String srcPath;
  final String dstPath;
  final int longEdge;
  final int quality;

  Map<String, Object?> toMap() => {
        'src': srcPath,
        'dst': dstPath,
        'px': longEdge,
        'quality': quality,
      };
}

/// 压缩结果。
///
/// - `ok == true && skipped == true`：原图长边已不超目标 → **没有写 dst**，
///   调用方应复制原图（零画质损失）。
/// - `ok == true && skipped == false`：压缩产物已写到 dst，[bytes] 是其大小。
/// - `ok == false`：压缩失败（文件损坏等）→ 调用方回退复制原图。
///   **压缩失败绝不能丢照片** —— 这是交付，不是优化。
class CompressResult {
  const CompressResult({
    required this.ok,
    required this.skipped,
    required this.width,
    required this.height,
    required this.bytes,
  });

  final bool ok;
  final bool skipped;
  final int width;
  final int height;
  final int bytes;
}

/// `gtick/perf` 通道封装（2026-09-29 全 App 性能排查）。
///
/// 只做两件事：问设备档次、批量生成缩略图。都是"Dart 做不好、原生很便宜"的活。
class PerfBridge {
  const PerfBridge._();

  static const MethodChannel _channel = MethodChannel('gtick/perf');

  /// 设备画像。失败返回 [DeviceProfile.unknown]（保守值，绝不抛）。
  static Future<DeviceProfile> deviceProfile() async {
    try {
      final res = await _channel.invokeMapMethod<String, Object?>('deviceProfile');
      if (res == null) return const DeviceProfile.unknown();
      return DeviceProfile(
        totalMemMB: (res['totalMemMB'] as num?)?.toInt() ?? 0,
        memoryClassMB: (res['memoryClassMB'] as num?)?.toInt() ?? 0,
        lowRam: (res['lowRam'] as bool?) ?? false,
        cpuCores: (res['cpuCores'] as num?)?.toInt() ?? 2,
        sdkInt: (res['sdkInt'] as num?)?.toInt() ?? 0,
      );
    } on PlatformException catch (_) {
      return const DeviceProfile.unknown();
    } catch (_) {
      return const DeviceProfile.unknown();
    }
  }

  /// 批量生成缩略图（原生 inSampleSize 降采样 + RGB_565）。
  ///
  /// **失败返回空列表** —— 调用方据此回退到 Dart isolate 方案，
  /// 缩略图不是关键路径，绝不能因为通道问题让照片入库失败。
  static Future<List<ThumbResult>> makeThumbs(List<ThumbJob> jobs) async {
    if (jobs.isEmpty) return const [];
    try {
      final res = await _channel.invokeListMethod<Object?>(
        'makeThumbs',
        {'jobs': [for (final j in jobs) j.toMap()]},
      );
      if (res == null || res.length != jobs.length) return const [];
      return [
        for (final row in res)
          if (row is Map)
            ThumbResult(
              ok: (row['ok'] as bool?) ?? false,
              width: (row['w'] as num?)?.toInt() ?? 0,
              height: (row['h'] as num?)?.toInt() ?? 0,
              // 老版本原生不回 luma → null。查不到就当没量到，不猜。
              luma: (row['luma'] as num?)?.toInt(),
            )
          else
            const ThumbResult(ok: false, width: 0, height: 0),
      ];
    } on PlatformException catch (_) {
      return const [];
    } catch (_) {
      return const [];
    }
  }

  /// 批量压缩交付照片（原生 inSampleSize + ARGB_8888 + JPEG q85）。
  ///
  /// 与 [makeThumbs] 同样的失败口径：**异常/通道不可用返回空列表**，
  /// 调用方据此把所有任务回退成「复制原图」—— 压缩只是优化，绝不能
  /// 因为它失败而少交付一张照片。
  static Future<List<CompressResult>> compressPhotos(List<CompressJob> jobs) async {
    if (jobs.isEmpty) return const [];
    try {
      final res = await _channel.invokeListMethod<Object?>(
        'compressPhotos',
        {'jobs': [for (final j in jobs) j.toMap()]},
      );
      if (res == null || res.length != jobs.length) return const [];
      return [
        for (final row in res)
          if (row is Map)
            CompressResult(
              ok: (row['ok'] as bool?) ?? false,
              skipped: (row['skipped'] as bool?) ?? false,
              width: (row['w'] as num?)?.toInt() ?? 0,
              height: (row['h'] as num?)?.toInt() ?? 0,
              bytes: (row['bytes'] as num?)?.toInt() ?? 0,
            )
          else
            const CompressResult(ok: false, skipped: false, width: 0, height: 0, bytes: 0),
      ];
    } on PlatformException catch (_) {
      return const [];
    } catch (_) {
      return const [];
    }
  }

  /// 批量算内容指纹（查重专用，2026-10-04）。
  ///
  /// 返回与 [paths] 等长、按下标对齐；`null` = 该文件读不到。
  /// **失败返回全 null 列表而不是空列表** —— 这里与 [makeThumbs] 的口径
  /// 故意不同：查重是"宁可不提示、不可错提示"，通道一挂返回空列表会被
  /// 误读成"整批都没算过"而反复重试；返回 null 则调用方按"这张失败"
  /// 记账，下轮只补这一张。
  static Future<List<String?>> hashFiles(List<String> paths) async {
    if (paths.isEmpty) return const [];
    try {
      final res = await _channel.invokeListMethod<Object?>(
        'hashFiles',
        {'paths': paths},
      );
      if (res == null || res.length != paths.length) {
        return List<String?>.filled(paths.length, null);
      }
      return [for (final row in res) row as String?];
    } on PlatformException catch (_) {
      return List<String?>.filled(paths.length, null);
    } catch (_) {
      return List<String?>.filled(paths.length, null);
    }
  }
}
