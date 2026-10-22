import 'dart:async';

import 'package:flutter/painting.dart';
import 'package:flutter/widgets.dart';

import 'perf_bridge.dart';

/// 设备档次（2026-09-29 全 App 性能排查）。
enum DeviceClass { low, mid, high }

/// 按设备档次给出的**性能预算**。
///
/// 为什么需要它：现场用的是几百到一千块的安卓机，RAM 2GB / 4 核的机器
/// 跟旗舰机跑同一套参数必然卡死。此前所有常量都是写死的"旗舰值"
/// （一次并发 N 张缩略图、网格一页 120 格、缩略图 256px），低配机上
/// 就是：并发解码 → 内存峰值翻倍 → GC 抖动 → 掉帧甚至 OOM 重启。
///
/// 用法：启动时 [DeviceTier.init] 后台取一次画像（不阻塞启动），
/// 各处读 [DeviceTier.current]。画像取不到时按 mid —— 既不会像 high 那样
/// 冒险，也不至于像 low 那样把正常机器也拖慢。
class DeviceTier {
  const DeviceTier._({
    required this.klass,
    required this.thumbConcurrency,
    required this.galleryPageSize,
    required this.galleryThumbPx,
    required this.thumbLongEdge,
    required this.imageCacheBytes,
    required this.gridCacheExtentPx,
    required this.importChunkSize,
  });

  /// 默认（未取到画像前）。
  static const DeviceTier mid = DeviceTier._(
    klass: DeviceClass.mid,
    thumbConcurrency: 2,
    galleryPageSize: 90,
    galleryThumbPx: 224,
    thumbLongEdge: 256,
    imageCacheBytes: 64 * 1024 * 1024,
    gridCacheExtentPx: 400,
    importChunkSize: 25,
  );

  static const DeviceTier low = DeviceTier._(
    klass: DeviceClass.low,
    // 低配机绝不同时解码两张大图：一张 4000×3000 的 ARGB 缓冲就是 48MB，
    // 两张并排在 2GB 机器上直接触顶。
    thumbConcurrency: 1,
    galleryPageSize: 60,
    galleryThumbPx: 192,
    thumbLongEdge: 192,
    imageCacheBytes: 32 * 1024 * 1024,
    gridCacheExtentPx: 200,
    importChunkSize: 15,
  );

  static const DeviceTier high = DeviceTier._(
    klass: DeviceClass.high,
    thumbConcurrency: 3,
    galleryPageSize: 120,
    galleryThumbPx: 256,
    thumbLongEdge: 256,
    imageCacheBytes: 96 * 1024 * 1024,
    gridCacheExtentPx: 600,
    importChunkSize: 40,
  );

  final DeviceClass klass;

  /// 同时进行的缩略图任务数上限。
  final int thumbConcurrency;

  /// 相册网格每页张数。
  final int galleryPageSize;

  /// 相册网格缩略图的请求像素（原生按它出图）。
  final int galleryThumbPx;

  /// 项目内缩略图长边（入库缩略图）。
  final int thumbLongEdge;

  /// Flutter 图片缓存上限（字节）。低配机必须收紧，否则列表滚一圈
  /// 就吃掉上百 MB 常驻内存。
  final int imageCacheBytes;

  /// 网格预构建区域的像素高度。低配机调小 = 少建屏外 widget。
  final double gridCacheExtentPx;

  /// 导入时分批提交给原生的张数（每批之间给 UI 一次喘息 + 进度刷新）。
  final int importChunkSize;

  static DeviceTier _current = mid;
  static DeviceTier get current => _current;

  /// 后台取画像并更新 [current]。**不 await**：启动路径上不做任何等待。
  ///
  /// 失败静默 —— 拿不到画像就按 mid 跑，绝不能因为探测失败阻塞使用。
  static Future<void> init() async {
    final p = await PerfBridge.deviceProfile();
    _current = _of(p);
    _applyImageCache();
    return;
  }

  /// 按档次收紧 Flutter 图片缓存。
  ///
  /// 默认上限对不同机型一视同仁（100MB 起步且会随使用增长），低配机上
  /// 就是"越用越卡最后被系统杀"。这里按档次压到 32/64/96MB。
  static void _applyImageCache() {
    try {
      final cache = PaintingBinding.instance.imageCache;
      cache.maximumSizeBytes = _current.imageCacheBytes;
      cache.maximumSize = 300;
    } catch (_) {
      // 没有 binding（纯 Dart 单测 / 未初始化）时就不管，不影响功能
    }
  }

  static DeviceTier _of(DeviceProfile p) {
    // 拿不到真实数据（桌面 / 测试 / 通道异常）→ mid，别把正常机器判成低配。
    if (p.totalMemMB <= 0 && p.memoryClassMB <= 0) return mid;
    final memMB = p.memoryClassMB > 0
        ? p.memoryClassMB
        : (p.totalMemMB / 16).round(); // 无 memoryClass 时按总内存的 1/16 估
    if (p.lowRam || memMB <= 128 || (p.totalMemMB > 0 && p.totalMemMB <= 3072)) {
      return low;
    }
    if (memMB <= 256 || p.totalMemMB <= 4096 || p.cpuCores <= 4) return mid;
    return high;
  }
}
