import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show MethodChannel;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
// 注意：`g_tick_picture` 排在 `go_router` 之前 —— '_'(0x5F) < 'o'，
// directives_ordering 按 ASCII 比，写反了 analyze 会报 info 并挡住发版。
import 'package:g_tick_picture/app/providers.dart';
import 'package:g_tick_picture/domain/model/assigned_group.dart';
import 'package:g_tick_picture/domain/model/bulk_confirm_candidate.dart';
import 'package:g_tick_picture/domain/model/delivery_readiness.dart';
import 'package:g_tick_picture/domain/model/duplicate_photos.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/model/open_group.dart';
import 'package:g_tick_picture/domain/model/project_summary.dart';
import 'package:g_tick_picture/ui/project/project_console_page.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 工作台导航结构（2026-10-01 重构）。
///
/// 这次改动的全部意义就是**底部少两条、拍照不用切页** —— 这正是那种
/// "改完肉眼一扫好像对了，但漏一个入口就没人发现"的改动，所以钉住：
///   ① 底部只剩「照片 / 交付」两个 Tab，概览与采集必须消失；
///   ② 「照片」页里直接有拍照入口：系统相机模式（默认）直拍不进
///      App 内相机页（v0.22.2），内置相机模式才进全屏相机路由；
///   ③ 切到「交付」后照片页的内容不再占屏（IndexedStack 索引正确）。
void main() {
  final summary = ProjectSummary(
    id: 'p1',
    name: '测试项目',
    client: null,
    createdAt: DateTime(2026),
    status: ProjectStatus.collecting,
    itemTotal: 0,
    itemDone: 0,
    photoTotal: 0,
    photoConfirmed: 0,
    photoUnassigned: 0,
    photoOrphan: 0,
    groupPending: 0,
  );

  final pushed = <String>[];

  GoRouter buildRouter() => GoRouter(
        initialLocation: '/',
        routes: [
          GoRoute(
            path: '/',
            builder: (_, __) => const ProjectConsolePage(projectId: 'p1'),
          ),
          GoRoute(
            path: '/project/:id/capture',
            builder: (_, __) {
              pushed.add('capture');
              return const Scaffold(body: Text('camera'));
            },
          ),
        ],
      );

  Widget buildApp() => ProviderScope(
        overrides: [
          projectSummaryProvider.overrideWith(
            (ref, id) => Stream<ProjectSummary?>.value(summary),
          ),
          // 照片页的三条流给空列表 —— 本测试只验导航骨架，不验数据流。
          openGroupsProvider.overrideWith(
            (ref, id) => Stream<List<OpenGroup>>.value(const []),
          ),
          assignedGroupsProvider.overrideWith(
            (ref, id) => Stream<List<AssignedGroup>>.value(const []),
          ),
          // 注意：这两个是 FutureProvider（不是 StreamProvider）。
          bulkConfirmPreviewProvider.overrideWith(
            (ref, id) async => const <BulkConfirmCandidate>[],
          ),
          // 交付页也在 IndexedStack 里（不可见但已构建），不覆写就会真的
          // 去开库查询，测试会卡在 pumpAndSettle。
          deliveryReadinessProvider.overrideWith(
            (ref, id) async => const DeliveryReadiness(
              orphanPhotoAssignments: 0,
              orphanGroupAssignments: 0,
              itemTotal: 0,
              itemGap: 0,
              photoUnassigned: 0,
              photoConfirmed: 0,
              photoUnused: 0,
            ),
          ),
          // 查重横幅（2026-10-04）同理：它是 FutureProvider，不覆写就会
          // 真去跑 backfillHashes 走原生通道，而 loading 态的
          // CircularProgressIndicator 永远在转 → pumpAndSettle 必超时。
          // 空报告 = 无重复、横幅收起，不影响本测试验的是导航骨架。
          duplicateReportProvider.overrideWith(
            (ref, id) async => const DuplicateReport.empty(),
          ),
        ],
        child: MaterialApp.router(routerConfig: buildRouter()),
      );

  testWidgets('底部只剩「照片 / 交付」，概览与采集都已下线', (tester) async {
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    expect(find.text('照片'), findsWidgets);
    expect(find.text('交付'), findsWidgets);
    expect(find.text('概览'), findsNothing);
    expect(find.text('采集'), findsNothing);

    // NavigationBar 只有两个目的地
    final bar = tester.widget<NavigationBar>(find.byType(NavigationBar));
    expect(bar.destinations.length, 2);
  });

  testWidgets('拍照入口（系统相机默认）：直拍，不进 App 内相机页', (tester) async {
    // 系统相机通道回 false = 用户取消 —— 最轻的直拍结局：静默、不路由。
    // 若实现退化成"先 push 相机页"，pushed 里就会出现 capture。
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('gtick/system_camera'),
      (call) async => <String, Object?>{'ok': false},
    );
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    expect(find.text('拍照入库'), findsOneWidget);
    expect(find.text('相册导入'), findsOneWidget);

    await tester.tap(find.text('拍照入库'));
    await tester.pumpAndSettle();

    expect(pushed, isNot(contains('capture')));
  });

  testWidgets('拍照入口（内置相机回退）：照旧进全屏相机页', (tester) async {
    SharedPreferences.setMockInitialValues(
      {'camera.capture_mode': 'builtin'},
    );
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('拍照入库'));
    await tester.pumpAndSettle();

    expect(pushed, contains('capture'));
  });

  testWidgets('指派 UI 已彻底下线', (tester) async {
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    // 卡片按钮、视图页签、一键确认入口一个都不该剩。
    // 这几个词四处散落，靠人review 很容易漏掉某一个入口。
    expect(find.text('指派货品'), findsNothing);
    expect(find.text('待处理 0 组'), findsNothing);
    expect(find.text('已指派 0 组'), findsNothing);
    expect(find.textContaining('一键确认'), findsNothing);
    expect(find.textContaining('清单缺口'), findsNothing);
    // 取而代之的是一行紧凑状态条
    expect(find.text('0 组'), findsOneWidget);
  });

  testWidgets('切到「交付」后照片页不再占屏', (tester) async {
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('交付'));
    await tester.pumpAndSettle();

    // 照片页的主行动条随 IndexedStack 切换而移出（依然在树里但不可见）
    expect(find.text('拍照入库'), findsNothing);
  });
}
