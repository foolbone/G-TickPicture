/// App 身份信息（2026-10-14 v0.23.0：设置-关于面板）。
///
/// 版本号来源：**读 pubspec.yaml**（必须以 assets 显式声明它才会进包，
/// 见 app/pubspec.yaml 的 flutter.assets —— v0.24.2 修复「版本未知」：
/// 曾假设 Flutter 自动打包 pubspec，实际不声明就没有这份资产，
/// release 包里 rootBundle.loadString 必失败），而不是加
/// package_info_plus 依赖 —— 一条版本号不值得给发布链加一个原生插件
/// （每个插件都要过发版门禁、真机验证、签名体积）。
///
/// 读不到时（单测环境、极端 ROM 裁剪资产）回落 [unknownVersion]：
/// 「关于」面板只用于展示，绝不能因为读不到版本号就抛。
library;

import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:flutter/services.dart' show rootBundle;

/// App 名称（对外统一口径；导出包名与归档文件名同源）。
const String kAppName = '集刻-采集';

/// 版本号读不出来时的占位文案。
const String kUnknownVersion = '版本未知';

class AppInfo {
  const AppInfo._();

  /// 一句话介绍（「关于」面板顶部 + 后续商店文案都从这里取）。
  static const String tagline = '仓库预检监装取证';

  /// 面向使用者的介绍（不是给工程师看的，是给老板看这三行字）。
  static const String intro =
      '现场拍照 → 自动成组 → 对应货品 → 交付打包，一条线走完。\n'
      '采集期只管按快门：识别、分组、归属都在整理阶段做，'
      '不会打断拍照的节奏。';

  /// 版本号（含 build 号），如 `0.23.0 (34)`。
  ///
  /// 读 pubspec 的 `version:` 字段（`0.23.0+34` → 展示成 `0.23.0 (34)`）。
  static Future<String> version() async {
    final raw = await _rawVersion();
    return formatVersion(raw);
  }

  /// `1.2.3+45` → `1.2.3 (45)`；`1.2.3` → 原样；空/读不到 → 「版本未知」。
  ///
  /// 抽成纯函数是为了能直接测它（「关于」面板的展示口径不许靠真机看）。
  @visibleForTesting
  static String formatVersion(String? raw) {
    if (raw == null || raw.trim().isEmpty) return kUnknownVersion;
    final v = raw.trim();
    final plus = v.indexOf('+');
    if (plus <= 0) return v;
    final name = v.substring(0, plus).trim();
    final code = v.substring(plus + 1).trim();
    return code.isEmpty ? name : '$name ($code)';
  }

  static Future<String?> _rawVersion() async {
    try {
      final yaml = await rootBundle.loadString('pubspec.yaml');
      // 只认行首的顶层 `version:`（缩进的同名键不是它）。
      for (final line in yaml.split('\n')) {
        if (line.startsWith('version:')) {
          return line.substring('version:'.length).trim();
        }
      }
    } catch (_) {
      // 单测环境没有这份资产 —— 关于面板会显示「版本未知」，不该炸。
    }
    return null;
  }
}
