/// App 身份信息（2026-10-14 v0.23.0「关于」面板）的展示口径。
///
/// 只测纯函数那一半 —— 「版本号读出来长什么样」是关于面板唯一需要
/// 钉住的行为；读 pubspec 那一步靠 rootBundle，在单测里没有那份资产
/// （[AppInfo.version] 会按设计回落「版本未知」，不抛）。
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/core/app_info.dart';

void main() {
  group('AppInfo.formatVersion（关于面板的展示口径）', () {
    test('pubspec 的 name+code → 「版本 (code)」', () {
      expect(AppInfo.formatVersion('0.23.0+34'), '0.23.0 (34)');
    });

    test('只有版本号时原样展示（不硬造括号）', () {
      expect(AppInfo.formatVersion('0.23.0'), '0.23.0');
    });

    test('尾部空白被吃掉（pubspec 行尾换行）', () {
      expect(AppInfo.formatVersion(' 0.23.0+34 \n'), '0.23.0 (34)');
    });

    test('读不到 / 空串 → 版本未知（关于面板不许崩）', () {
      expect(AppInfo.formatVersion(null), kUnknownVersion);
      expect(AppInfo.formatVersion(''), kUnknownVersion);
      expect(AppInfo.formatVersion('   '), kUnknownVersion);
    });

    test('只有 + 没有 code 时不显示空括号', () {
      expect(AppInfo.formatVersion('0.23.0+'), '0.23.0');
    });
  });

  test('App 名称与介绍非空（关于面板与主页标题共用同一口径）', () {
    expect(kAppName.trim(), isNotEmpty);
    expect(AppInfo.tagline.trim(), isNotEmpty);
    expect(AppInfo.intro.trim(), isNotEmpty);
  });

  test('pubspec.yaml 声明为资产且带 version（版本号展示的地基）', () {
    // v0.24.2 踩坑：曾假设"Flutter 会自动把 pubspec.yaml 打进 assets"，
    // 实际不显式声明就没有这份资产 → release 包里
    // rootBundle.loadString('pubspec.yaml') 必失败 → 关于面板显示
    // 「版本未知」。这里把地基钉住：谁把 assets 段删了，这个测试就红。
    // flutter test 的 cwd 就是包根目录。
    final yaml = File('pubspec.yaml').readAsStringSync();

    expect(
      yaml
          .split('\n')
          .any((l) => l.startsWith('version:') && l.substring(8).trim().isNotEmpty),
      isTrue,
      reason: '顶层 version: 行是 AppInfo._rawVersion 的数据源',
    );

    final flutterAt = yaml.indexOf(RegExp(r'^flutter:$', multiLine: true));
    expect(flutterAt, greaterThan(-1), reason: 'flutter: 段必须存在');
    expect(
      RegExp(r'^\s*-\s*pubspec\.yaml\s*$', multiLine: true)
          .hasMatch(yaml.substring(flutterAt)),
      isTrue,
      reason: 'pubspec.yaml 必须显式声明为 asset，否则 release 包读不到',
    );
  });
}
