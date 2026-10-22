import 'package:flutter/services.dart';

/// 音量键快门事件流（2026-10-12 v0.20.0，对标原生相机标配）。
///
/// 原生侧（MainActivity）在 Dart **listen 期间**把音量上下键拦截为快门
/// 事件（keyCode 原样下发），cancel 后自动恢复系统音量调节 —— 拦截
/// 范围严格限定在采集页可见期间，退出页面按键行为零改变。
///
/// 音量上/下两个键都是快门：单手握持时拇指按快门键、食指按音量键
/// 是现场常见的两种持机姿势，都覆盖。
class VolumeKeyShutter {
  const VolumeKeyShutter._();

  static const EventChannel _channel = EventChannel('gtick/keys');

  /// 快门事件流。事件值是 keyCode（VOLUME_UP=24 / VOLUME_DOWN=25），
  /// 调用方通常不关心是哪个键 —— 两个都是拍。
  static Stream<Object?> get events => _channel.receiveBroadcastStream();
}
