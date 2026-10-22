import 'dart:io';

import '../../core/constants.dart';
import '../../core/logger.dart';

/// 存储空间预检的结论（§8.2）。
class StorageAudit {
  const StorageAudit({
    required this.freeBytes,
    required this.requiredBytes,
    required this.unknown,
  });

  /// 可用字节。[-1] 表示查不到（见 [unknown]）。
  final int freeBytes;

  /// 本次预计需要的字节（含余量倍数）。
  final int requiredBytes;

  /// 是否**无法判定** —— 查询失败或平台不支持。
  ///
  /// 这一档非常重要：查不到 ≠ 不足。此时既不拦人也不吓人，
  /// 只是不显示余量数字（§8.2 的原则是"提示得早"，不是"宁可误报"）。
  final bool unknown;

  bool get enough => unknown || freeBytes >= requiredBytes;
}

/// 采集前的存储空间预检。
///
/// 设计取向（§8.2）：**这是采集页唯一允许出现的提示**。
/// 所以它必须：
///  - 在开拍前就算出来（不能等写失败才说）；
///  - 只给一个结论 + 一个动作（"仅拍标清" / "知道了"）；
///  - 查不到时保持沉默 —— 不当拦路虎。
///
/// ── 为什么不查"还剩多少 GB" ───────────────────────────────
/// Flutter/Dart 标准库里**没有**跨平台的"可用磁盘空间" API。
/// 要拿到精确余量必须引插件（`disk_space_plus` 之类），而它：
///   · 0.2.4 的 Android 端仍在用已移除的 `PluginRegistry.Registrar`
///     → Gradle Kotlin 编译直接失败；
///   · 0.2.5+ 已修，但要求 Dart >= 3.7.2（本机是 3.7.0）。
/// 为这个"锦上添花"的预检去升级整个 Flutter SDK，代价与收益不成比例。
///
/// 更重要的是：**采集场景真正要回答的不是"还剩多少 GB"，而是"现在能不能开拍"。**
/// 那就用写探针直接回答 —— 它比读数更贴近事实（读数会因配额、
/// 只读挂载、SELinux 等因素与实际可写性脱节）。
///
/// 需要精确余量时（如 M5 上传前的检查）再引入插件，届时先确认 Dart >= 3.7.2。
class StorageService {
  const StorageService._();

  /// 按"预计张数 × 单张典型体积 × 余量倍数"估算。
  ///
  /// [expectedPhotos] 传 0 表示未知规模，此时按 [AppConst.sessionSoftLimit]
  /// 的一个小比例试算，避免一进页面就报"空间不足"。
  static Future<StorageAudit> audit({
    required String projectRootPath,
    required int expectedPhotos,
    int? bytesPerPhoto,
  }) async {
    final per = bytesPerPhoto ?? AppConst.estimatedPhotoBytes;
    final n = expectedPhotos > 0 ? expectedPhotos : 200;
    final required = (per * n * AppConst.captureFreeSpaceFactor).round();

    final free = await _freeSpace(projectRootPath);
    if (free == null) {
      return StorageAudit(
        freeBytes: -1,
        requiredBytes: required,
        unknown: true,
      );
    }
    return StorageAudit(
      freeBytes: free,
      requiredBytes: required,
      unknown: false,
    );
  }

  /// 查可用空间。返回 null 表示**给不出精确数字**（含"能写但不知道余量"）。
  ///
  /// 策略：写一个探针文件 → 校验长度 → 删掉。三种结局：
  ///  · 探针完整写入并删掉 → **能写**。但我们仍然不知道精确余量 ——
  ///    此时返回 null（调用方标 unknown），【绝不】返回 -1 之类的小数字：
  ///    那会让 `freeBytes >= requiredBytes` 判成 false，把"能写"误判成"不足"
  ///    （这个 bug 已被单测抓过一次：能写的目录被拦在采集页外面）。
  ///  · 写入抛异常 / 长度不对 → 空间确实不可用，返回 0 ——
  ///    这是**唯一**会触发"空间不足"提示的情况。
  ///
  /// 为什么探针用 4 MB 而不是 1 KB：
  /// 空间濒临耗尽时，小文件往往还能写进去，但相机一张就要几 MB ——
  /// 探针太小会给出假阳性。4 MB 接近单张照片的真实体积量级。
  static Future<int?> _freeSpace(String path) async {
    // 目录可能还不存在（首次进采集页），先确保它在那儿。
    try {
      final dir = Directory(path);
      if (!dir.existsSync()) {
        dir.createSync(recursive: true);
      }
    } catch (e) {
      // 目录都建不出来 → 确实写不进去。这不是"查不到"，是明确的空间/权限问题。
      Log.w('Storage', 'cannot create project dir: $path :: $e');
      return 0;
    }

    final probe = File('$path/.space_probe');
    try {
      await probe.writeAsBytes(
        List<int>.filled(AppConst.storageProbeBytes, 0),
        flush: true,
      );
      final len = await probe.length();
      await probe.delete();

      if (len != AppConst.storageProbeBytes) {
        // 写了但长度不对 → 结果不可信，按"给不出数字"处理（沉默，不拦人）
        Log.w('Storage', 'probe size mismatch: $len');
        return null;
      }
      // 能完整写入并删掉 → 能拍。精确余量给不出 → null（unknown）
      return null;
    } catch (e) {
      Log.w('Storage', 'probe write failed: $e');
      return 0;
    }
  }

  /// 人类可读的体积。
  static String humanBytes(int bytes) {
    if (bytes < 0) return '未知';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var v = bytes.toDouble();
    var i = 0;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i++;
    }
    return '${v.toStringAsFixed(v >= 100 || i == 0 ? 0 : 1)} ${units[i]}';
  }
}
