import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
import 'core/device_tier.dart';

/// 入口。
///
/// 刻意保持极简 —— 启动路径上不做任何 IO。
/// 数据库是懒加载的（第一次读 provider 时才建），
/// 保证冷启动到可用时间不被 DB 初始化拖住（§8.1 目标 ≤2s）。
void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // 设备画像：一次极轻的原生调用，**不 await**（启动路径零等待）。
  // 拿到后只影响"一次干多少活"这类预算值，不影响任何功能可用性。
  unawaited(DeviceTier.init());
  // 图片缓存上限按设备档次收紧。默认 100MB 起步、无上限地在低配机上
  // 是 OOM 的常见来源 —— 列表滚一圈就能吃掉上百 MB 常驻内存。
  PaintingBinding.instance.imageCache.maximumSizeBytes =
      DeviceTier.current.imageCacheBytes;
  PaintingBinding.instance.imageCache.maximumSize = 300;
  runApp(const ProviderScope(child: GtickApp()));
}
