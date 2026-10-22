import 'dart:async';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/app/providers.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/model/duplicate_photos.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/model/open_group.dart';
import 'package:g_tick_picture/domain/model/project_summary.dart';
import 'package:g_tick_picture/domain/ocr/ocr_text_extractor.dart';
import 'package:g_tick_picture/domain/suggest/suggest_pipeline.dart';
import 'package:g_tick_picture/ui/organize/organize_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 整理页 OCR 状态行（v0.24.2）——「怎么知道照片识别过了没有」的正面回答。
///
/// 接线本身也在这里被验到：进 OrganizePage 会触发一轮识别
/// （SuggestPipeline.ensurePendingProcessed），状态行把结果摆出来。
///
/// 两个替身：
///   · 抽取器换假的 —— 每张照片的识别成败与时机都可控，不碰 ML Kit；
///   · 覆盖统计喂控制器 —— 状态行的显示口径（数字 → 文案）由这里钉，
///     真 SQL 口径由 ocr_coverage_test.dart 钉；同时避开 drift 流缓存
///     定时器与「树已销毁但 timer 未决」的 widget 测试断言打架。
class _GatedExtractor implements OcrTextExtractor {
  _GatedExtractor(int n) {
    for (var i = 0; i < n; i++) {
      gates.add(Completer<List<OcrTokenResult>>());
    }
  }

  final List<Completer<List<OcrTokenResult>>> gates = [];
  int _next = 0;

  @override
  Future<List<OcrTokenResult>> extract(String filePath) {
    final i = _next < gates.length ? _next : gates.length - 1;
    _next++;
    return gates[i].future;
  }
}

class _FailExtractor implements OcrTextExtractor {
  @override
  Future<List<OcrTokenResult>> extract(String filePath) async =>
      throw Exception('simulated failure');
}

class _OkExtractor implements OcrTextExtractor {
  @override
  Future<List<OcrTokenResult>> extract(String filePath) async => const [];
}

void main() {
  late AppDatabase db;
  late String projectId;
  late SharedPreferences prefs;
  late StreamController<OcrPhotoStats> statsCtrl;

  final summary = ProjectSummary(
    id: 'p1',
    name: 'OCR 状态行测试',
    client: null,
    createdAt: DateTime(2026, 10, 15),
    status: ProjectStatus.collecting,
    itemTotal: 0,
    itemDone: 0,
    photoTotal: 0,
    photoConfirmed: 0,
    photoUnassigned: 0,
    photoOrphan: 0,
    groupPending: 0,
  );

  setUp(() async {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    prefs = await SharedPreferences.getInstance();
    statsCtrl = StreamController<OcrPhotoStats>.broadcast();
    db = AppDatabase.forTesting(NativeDatabase.memory());
    projectId = await ProjectRepository(db).create(name: '状态行');
  });

  tearDown(() async {
    await statsCtrl.close();
    await db.close();
  });

  /// 拍 [n] 张（不入组也行 —— 状态行只数 ocr_state）。
  Future<List<String>> shoot(int n) async {
    final capture = CaptureRepository(db);
    final s = await capture.startSession(projectId);
    final ids = await capture.insertPhotos(projectId, [
      for (var i = 0; i < n; i++)
        NewPhoto(
          sessionId: s,
          filePath: '/tmp/strip$i.jpg',
          seq: i + 1,
          takenAt: DateTime(2026, 10, 15, 9, 0, i),
          bytes: 1024,
        ),
    ]);
    await capture.endSession(s);
    return ids;
  }

  Future<void> setDone(String photoId) async {
    await (db.update(db.photos)..where((p) => p.id.equals(photoId)))
        .write(const PhotosCompanion(ocrState: Value('done')));
  }

  /// 喂一份统计并让页面渲染稳定。
  Future<void> emitStats(
    WidgetTester tester,
    OcrPhotoStats stats,
  ) async {
    statsCtrl.add(stats);
    await tester.pump();
  }

  Future<void> pumpOrganize(
    WidgetTester tester, {
    required OcrTextExtractor extractor,
  }) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appDatabaseProvider.overrideWithValue(db),
          openGroupsProvider.overrideWith(
            (ref, id) => Stream<List<OpenGroup>>.value(const []),
          ),
          duplicateReportProvider.overrideWith(
            (ref, id) async => const DuplicateReport.empty(),
          ),
          ocrPhotoStatsProvider.overrideWith((ref, key) => statsCtrl.stream),
          // 管道换假抽取器：进度与成败都可控，不碰 ML Kit 原生插件。
          suggestPipelineProvider.overrideWithValue(
            SuggestPipeline(db: db, extractor: extractor, prefs: prefs),
          ),
        ],
        child: MaterialApp(
          // OrganizePage 自己不带 Scaffold（真实结构里由项目工作台的
          // Scaffold 包着）—— 裸包会让状态行的 SnackBar 反馈无处落地。
          home: Scaffold(
            body: OrganizePage(projectId: projectId, summary: summary),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('全部已识别 → 状态行明说「已识别 N 张 · 可按编码搜索」',
      (tester) async {
    final ids = await shoot(2);
    await setDone(ids[0]);
    await setDone(ids[1]);

    await pumpOrganize(tester, extractor: _OkExtractor());
    await emitStats(tester, const OcrPhotoStats(pending: 0, done: 2, failed: 0));

    expect(find.text('已识别 2 张 · 可按编码搜索'), findsOneWidget);
    expect(find.textContaining('待识别'), findsNothing);
    expect(find.textContaining('失败'), findsNothing);
  });

  testWidgets('还有没识别的 → 状态行说明「打开本页会自动开始」', (tester) async {
    final ids = await shoot(3);
    await setDone(ids[0]); // 1 done + 2 pending

    // 抽取器挂住不返回：两张 pending 永远完不成，状态行停在"待识别"。
    await pumpOrganize(tester, extractor: _GatedExtractor(2));
    await emitStats(tester, const OcrPhotoStats(pending: 2, done: 1, failed: 0));

    expect(find.textContaining('还有 2 张待识别'), findsOneWidget);
    expect(find.textContaining('打开本页会自动开始'), findsOneWidget);
  });

  testWidgets('识别失败 → 状态行报失败张数，重试入口可点', (tester) async {
    await shoot(1);

    await pumpOrganize(tester, extractor: _FailExtractor());

    // 等管道把那张标成 failed（微任务链 + 写库），再喂失败统计。
    await tester.runAsync(() => Future.delayed(const Duration(milliseconds: 200)));
    await emitStats(tester, const OcrPhotoStats(pending: 0, done: 0, failed: 1));

    expect(find.text('识别失败 1 张'), findsOneWidget);

    // 点重试：管道会把 failed 标回 pending 再跑一轮（照样失败），
    // 但人要有一个"我试过了"的确定反馈。
    await tester.tap(find.text('重试'));
    await tester.pump();
    await tester.runAsync(() => Future.delayed(const Duration(milliseconds: 200)));
    await tester.pump();
    expect(find.text('已重新识别 1 张'), findsOneWidget);
  });

  testWidgets('识别进行中 → 状态行显示实时进度', (tester) async {
    await shoot(2);
    final gated = _GatedExtractor(2);

    await pumpOrganize(tester, extractor: gated);
    // 管道已挂起在第一张上：还没有任何进度事件，"待识别"。
    await emitStats(tester, const OcrPhotoStats(pending: 2, done: 0, failed: 0));
    expect(find.textContaining('还有 2 张待识别'), findsOneWidget);

    // 放行第一张 → 管道推 done=1/2 → 状态行切到"正在识别"。
    gated.gates[0].complete(const []);
    await tester.runAsync(() => Future.delayed(const Duration(milliseconds: 100)));
    await tester.pump();
    expect(find.text('正在识别 1/2…'), findsOneWidget);

    // 放行第二张 → 收工 → "已识别 2 张"。
    gated.gates[1].complete(const []);
    await tester.runAsync(() => Future.delayed(const Duration(milliseconds: 100)));
    await emitStats(tester, const OcrPhotoStats(pending: 0, done: 2, failed: 0));
    expect(find.text('已识别 2 张 · 可按编码搜索'), findsOneWidget);
  });

  testWidgets('一张照片都没有 → 状态行不占地方', (tester) async {
    await pumpOrganize(tester, extractor: _OkExtractor());
    await emitStats(tester, const OcrPhotoStats(pending: 0, done: 0, failed: 0));

    expect(find.textContaining('已识别'), findsNothing);
    expect(find.textContaining('待识别'), findsNothing);
    expect(find.textContaining('正在识别'), findsNothing);
  });
}
