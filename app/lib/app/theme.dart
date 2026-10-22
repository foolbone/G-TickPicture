import 'package:flutter/material.dart';

/// 主题：沿用设计方案的配色 —— 深海军蓝（navy）+ 朱砂（accent）。
///
/// 为什么采集页和整理页共用一个主题却长得完全不同：
/// 主题只定"品牌色与字号基线"，两页的**布局密度**是分开设计的（§1.5）。
/// 采集页追求"无界面"，整理页追求"高密度信息"。
class AppTheme {
  const AppTheme._();

  // ── 与设计方案 HTML 里的 CSS 变量一一对应 ──
  static const Color navy = Color(0xFF0D2B45);
  static const Color navy2 = Color(0xFF14395C);
  static const Color navy3 = Color(0xFF1E4E7A);
  static const Color accent = Color(0xFFC8452F); // 朱砂

  static const Color bg = Color(0xFFF6F7F9);
  static const Color card = Color(0xFFFFFFFF);
  static const Color line = Color(0xFFE3E6EA);
  static const Color textMain = Color(0xFF1F2937);
  static const Color textMuted = Color(0xFF6B7280);

  static const Color green = Color(0xFF2F855A);
  static const Color greenBg = Color(0xFFE8F5EE);
  static const Color amber = Color(0xFFB7791F);
  static const Color amberBg = Color(0xFFFDF5E3);
  static const Color orange = Color(0xFFC05621);
  static const Color orangeBg = Color(0xFFFDF0E6);
  static const Color red = Color(0xFFC53030);
  static const Color redBg = Color(0xFFFDEAEA);
  static const Color blue = Color(0xFF2B6CB0);
  static const Color blueBg = Color(0xFFE8F1FB);
  static const Color violet = Color(0xFF6B46C1);
  static const Color violetBg = Color(0xFFF0EAFB);

  /// 现场作业的最小点击尺寸。戴手套 + 单手 + 挂腕带，
  /// 小于这个尺寸会显著提高误触率（§1.3）。
  static const double minTapTarget = 48;

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: navy,
      brightness: Brightness.light,
    ).copyWith(
      primary: navy,
      secondary: accent,
      surface: card,
      error: red,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: bg,
      canvasColor: bg,
      dividerColor: line,
      fontFamily: null, // 交给系统：中文用 PingFang / 思源,避免打包字体
      appBarTheme: const AppBarTheme(
        backgroundColor: navy,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          fontSize: 17,
          fontWeight: FontWeight.w600,
          color: Colors.white,
        ),
      ),
      cardTheme: CardThemeData(
        color: card,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: const BorderSide(color: line),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, minTapTarget),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, minTapTarget),
          side: const BorderSide(color: line),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(minimumSize: const Size(0, 40)),
      ),
      listTileTheme: const ListTileThemeData(
        minVerticalPadding: 12,
        titleTextStyle: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: textMain,
        ),
        subtitleTextStyle: TextStyle(fontSize: 12.5, color: textMuted),
      ),
      snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
      textTheme: const TextTheme(
        titleLarge: TextStyle(fontSize: 19, fontWeight: FontWeight.w700, color: navy),
        titleMedium: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w600, color: textMain),
        bodyMedium: TextStyle(fontSize: 14.5, color: textMain, height: 1.5),
        bodySmall: TextStyle(fontSize: 12.5, color: textMuted, height: 1.5),
      ),
    );
  }
}
