import 'package:flutter/services.dart';

import 'constants.dart';

/// 手抖分级（阈值口径见 [AppConst.shakeMildJerk] / [AppConst.shakeHeavyJerk]）。
enum ShakeLevel {
  /// 没量到（传感器不可用 / 样本不足）—— **没数据 ≠ 不抖，必须闭嘴**。
  unknown,

  /// 静止或轻微移动 —— 不提示。
  none,

  /// 轻度抖动 —— 只记录，不提示（提示必须可操作，轻度提示是噪音）。
  mild,

  /// 明显手抖 —— 提示「稳一下再按」。
  heavy,
}

/// jerk RMS（m/s²）→ 分级。纯函数，便于单测。
///
/// 阈值来自 SensorBridge.kt 的实测口径：静止手持 0.1~0.4，
/// 明显手抖 1.5~4，边走 5+。heavy 取 [AppConst.shakeHeavyJerk]
/// （抖到这个程度拍唛头必糊，提示是可操作的），
/// mild 取 [AppConst.shakeMildJerk]（只记录，不提示 —— 铁律 16）。
ShakeLevel shakeLevelOf(double? jerk) {
  if (jerk == null) return ShakeLevel.unknown;
  if (jerk >= AppConst.shakeHeavyJerk) return ShakeLevel.heavy;
  if (jerk >= AppConst.shakeMildJerk) return ShakeLevel.mild;
  return ShakeLevel.none;
}

/// `gtick/sensors` 通道封装：加速度计手抖检测（2026-10-10 v0.19.0）。
///
/// 原生实现见 `SensorBridge.kt`：1s 滑动窗口，指标是 **jerk RMS**
/// （加速度模值相邻变化的均方根）—— 用"变化"而不是"模值"，匀速移动
/// 手机（转身去拍下一件货）不会误报。
///
/// 生命周期纪律：**只在采集页可见时 start，离开立刻 stop**。
/// 加速度计常开是实打实的耗电，现场一开就是一天（R1b 续航指标）。
///
/// 全部方法失败静默（返回 false / null / 忽略）：手抖提示是锦上添花，
/// 绝不能因为它让采集页打不开或拍照受阻。
class ShakeSensor {
  const ShakeSensor._();

  static const MethodChannel _channel = MethodChannel('gtick/sensors');

  /// 开始采样。false = 本机没有加速度计（调用方据此不再尝试）。
  static Future<bool> start() async {
    try {
      return await _channel.invokeMethod<bool>('start') ?? false;
    } catch (_) {
      return false;
    }
  }

  /// 停止采样（幂等）。
  static Future<void> stop() async {
    try {
      await _channel.invokeMethod<void>('stop');
    } catch (_) {
      // 通道不可用（页面已在销毁）—— 无所谓，原生侧 engine 销毁会兜底
    }
  }

  /// 最近 1s 窗口内的 jerk RMS。null = 样本不足 / 没在采样。
  static Future<double?> jerk() async {
    try {
      return (await _channel.invokeMethod<double>('jerk'))?.toDouble();
    } catch (_) {
      return null;
    }
  }
}
