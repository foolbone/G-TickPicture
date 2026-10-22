import 'package:flutter/foundation.dart';

/// 最小日志封装。
///
/// 为什么不用 print：analysis_options 禁用了 `avoid_print`，
/// 而且 release 包里 print 不会被裁剪、会拖性能。
/// 采集期（每 400ms 一次快门）绝不能有高频日志——见 §8.1。
class Log {
  const Log._();

  static bool verbose = kDebugMode;

  static void d(String tag, Object? msg) {
    if (verbose) debugPrint('[D/$tag] $msg');
  }

  static void i(String tag, Object? msg) => debugPrint('[I/$tag] $msg');

  static void w(String tag, Object? msg) => debugPrint('[W/$tag] $msg');

  static void e(String tag, Object? msg, [Object? err, StackTrace? st]) {
    debugPrint('[E/$tag] $msg${err == null ? '' : ' :: $err'}');
    if (kDebugMode && st != null) debugPrint(st.toString());
  }
}
