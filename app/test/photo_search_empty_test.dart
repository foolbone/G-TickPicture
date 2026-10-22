import 'dart:async';

import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/app/providers.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/ui/search/photo_search_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 搜索页零命中空态（v0.24.2）。
///
/// 真机反馈（2026-10-15）：「用编码搜一个都没搜到」。当时 OCR 管道
/// 从未被调用，库里一条 token 都没有 —— 而空态只会说「试试后几位」，
/// 把人往错的方向引。现在空态先分清三件事：
///   ① 库里没有照片 → 让去拍照；
///   ② 有照片但没识别完 → 明说「没识别」，并指出识别在哪发生；
///   ③ 识别完了确实没匹配 → 才建议换关键词。
///
/// OCR 覆盖统计在本文件里用覆写值喂进去（真 SQL 的口径由
/// ocr_coverage_test.dart 钉）—— 这里只验「数字 → 文案」的映射，
/// 不重复验查询；同时避开 drift 流缓存定时器与 widget 测试
/// 「树已销毁但 timer 未决」断言的冲突。
void main() {
  late AppDatabase db;

  setUp(() async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    db = AppDatabase.forTesting(NativeDatabase.memory());
  });

  tearDown(() async {
    await db.close();
  });

  Future<void> pumpPage(
    WidgetTester tester, {
    required OcrPhotoStats stats,
  }) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appDatabaseProvider.overrideWithValue(db),
          ocrPhotoStatsProvider.overrideWith(
            (ref, key) => Stream.value(stats),
          ),
        ],
        child: const MaterialApp(home: PhotoSearchPage()),
      ),
    );
    await tester.pump();
  }

  /// 输一个够长的编码，等去抖与查询都过去。
  Future<void> search(WidgetTester tester, String code) async {
    await tester.enterText(find.byType(TextField), code);
    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpAndSettle();
  }

  testWidgets('全库一张照片都没有 → 提示先拍照入库', (tester) async {
    await pumpPage(tester, stats: const OcrPhotoStats(pending: 0, done: 0, failed: 0));
    await search(tester, '123');

    expect(find.text('没找到「123」'), findsOneWidget);
    expect(find.textContaining('还没有可用于搜索的照片'), findsOneWidget);
  });

  testWidgets('有照片但都没识别 → 明说"没识别"，不让人瞎换关键词',
      (tester) async {
    await pumpPage(
      tester,
      stats: const OcrPhotoStats(pending: 3, done: 0, failed: 0),
    );
    await search(tester, '123');

    expect(find.textContaining('还有 3 张照片没识别'), findsOneWidget);
    // 不该出现"换个关键词"式的误导文案
    expect(find.textContaining('试试编码的后几位'), findsNothing);
  });

  testWidgets('有识别失败的 → 空态把失败张数摆在最前面', (tester) async {
    await pumpPage(
      tester,
      stats: const OcrPhotoStats(pending: 2, done: 5, failed: 1),
    );
    await search(tester, '123');

    expect(find.textContaining('1 张识别失败'), findsOneWidget);
    expect(find.textContaining('打开项目照片页可查看进度并重试'), findsOneWidget);
  });

  testWidgets('全部已识别、确实没匹配 → 才建议换关键词 / 换范围',
      (tester) async {
    await pumpPage(
      tester,
      stats: const OcrPhotoStats(pending: 0, done: 4, failed: 0),
    );
    await search(tester, '123');

    expect(find.textContaining('试试编码的后几位'), findsOneWidget);
    expect(find.textContaining('搜全部项目'), findsOneWidget);
  });
}
