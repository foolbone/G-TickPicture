// 注意：directives_ordering 按 ASCII 比，`g_tick_picture` 的 '_'(0x5F)
// 排在 `go_router` 的 'o' 之前。写反了 analyze 会报 info 并挡住发版。
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/app/providers.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/model/project_summary.dart';
import 'package:g_tick_picture/ui/project/project_list_page.dart';
import 'package:go_router/go_router.dart';

/// 项目列表页（2026-10-01 重写）。
///
/// 这一版专治"项目多了就翻不到" —— 搜索 / 排序 / 已交付折叠 / 多选归档
/// 四项能力全是**逻辑**（不是画面对齐），最适合钉在测试里：
///   ① 搜索同时匹配项目名与客户，命中数实时显示；
///   ② 已交付默认折叠，展开才看得到；
///   ③ 长按进入多选，顶栏切换成「已选 N 个」；
///   ④ 排序切到「照片最多」后顺序按照片数降序。
void main() {
  ProjectSummary s(
    String id,
    String name, {
    String? client,
    int photos = 0,
    bool done = false,
    DateTime? createdAt,
  }) =>
      ProjectSummary(
        id: id,
        name: name,
        client: client,
        createdAt: createdAt ?? DateTime(2026, 1, 1),
        status: done ? ProjectStatus.done : ProjectStatus.collecting,
        itemTotal: 0,
        itemDone: 0,
        photoTotal: photos,
        photoConfirmed: 0,
        photoUnassigned: 0,
        photoOrphan: 0,
        groupPending: 0,
      );

  final projects = [
    // p1 / p3 同属一个客户 —— 专门用来验证「客户」这个字段也参与匹配，
    // 而不只是项目名。
    s('p1', '预检-20260901', client: '宏远物流', photos: 10,
        createdAt: DateTime(2026, 9, 1)),
    s('p2', '监装-太仓仓', client: '远洋供应链', photos: 320,
        createdAt: DateTime(2026, 9, 20)),
    s('p3', '预检-20260925', client: '宏远物流', photos: 55,
        createdAt: DateTime(2026, 9, 25)),
    s('p4', '已完结项目', client: '和一贸易', photos: 8, done: true,
        createdAt: DateTime(2026, 8, 1)),
  ];

  final opened = <String>[];

  GoRouter buildRouter() => GoRouter(
        initialLocation: '/',
        routes: [
          GoRoute(
            path: '/',
            builder: (_, __) => const ProjectListPage(),
          ),
          GoRoute(
            path: '/project/:id',
            builder: (context, state) {
              opened.add(state.pathParameters['id']!);
              return Scaffold(
                  body: Text('console:${state.pathParameters['id']}'));
            },
          ),
        ],
      );

  Widget buildApp() => ProviderScope(
        overrides: [
          projectListProvider.overrideWith(
            (ref) => Stream<List<ProjectSummary>>.value(projects),
          ),
          deletedProjectsProvider.overrideWith(
            (ref) => Stream<List<ProjectSummary>>.value(const []),
          ),
        ],
        child: MaterialApp.router(routerConfig: buildRouter()),
      );

  // TEMP-DIAG：把渲染期异常完整打出来（定位偶发失败用，查完删）
  FlutterError.onError = (d) {
    // ignore: avoid_print
    print('>>> FLUTTER-ERROR: ${d.exception}');
    // ignore: avoid_print
    print('>>> CONTEXT: ${d.context?.toString()}');
    FlutterError.presentError(d);
  };

  testWidgets('搜索同时匹配项目名与客户，并显示命中数', (tester) async {
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    // 默认：3 个进行中的项目可见（p4 已交付，被折叠收着）
    expect(find.text('预检-20260901'), findsOneWidget);
    expect(find.text('监装-太仓仓'), findsOneWidget);
    expect(find.text('预检-20260925'), findsOneWidget);

    // 按**客户**搜 —— 命中两个宏远的项目
    await tester.enterText(find.byType(TextField), '宏远');
    await tester.pumpAndSettle();

    expect(find.text('预检-20260901'), findsOneWidget);
    expect(find.text('预检-20260925'), findsOneWidget);
    expect(find.text('监装-太仓仓'), findsNothing);
    // 命中计数 2/4
    expect(find.text('2/4'), findsOneWidget);
  });

  testWidgets('已交付默认折叠，点开才看得到', (tester) async {
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    // 折叠区标题在，里面的项目名不在
    expect(find.text('已交付（1）'), findsOneWidget);
    expect(find.text('已完结项目'), findsNothing);

    await tester.tap(find.text('已交付（1）'));
    await tester.pumpAndSettle();

    expect(find.text('已完结项目'), findsOneWidget);
  });

  testWidgets('长按进入多选，顶栏切成「已选 N 个」', (tester) async {
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    // 常态顶栏 = App 名 + 职能副标题（2026-10-14 v0.23.0 老板诉求
    // 「主页显示 APP 名称」；原「预检拍照」降为副标题）。
    expect(find.text('集刻-采集'), findsOneWidget);
    expect(find.text('仓库预检监装取证'), findsOneWidget);

    await tester.longPress(find.text('预检-20260901'));
    await tester.pumpAndSettle();

    expect(find.text('已选 1 个'), findsOneWidget);
    expect(find.text('集刻-采集'), findsNothing,
        reason: '多选态顶栏必须是「已选 N 个」，不让人以为还能点标题');

    // 再点一次同一行取消选择 → 退出多选模式
    await tester.tap(find.text('预检-20260901'));
    await tester.pumpAndSettle();

    expect(find.text('已选 1 个'), findsNothing);
    expect(find.text('集刻-采集'), findsOneWidget);
  });

  testWidgets('排序切到「照片最多」后按照片数降序', (tester) async {
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    // 默认最近新建：p3(09-25) > p2(09-20) > p1(09-01)
    expect(
      tester.getTopLeft(find.text('预检-20260925')).dy <
          tester.getTopLeft(find.text('监装-太仓仓')).dy,
      isTrue,
    );

    await tester.tap(find.text('最近新建'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('照片最多'));
    await tester.pumpAndSettle();

    // 照片最多：p2(320) > p3(55) > p1(10)
    expect(
      tester.getTopLeft(find.text('监装-太仓仓')).dy <
          tester.getTopLeft(find.text('预检-20260925')).dy,
      isTrue,
    );
    expect(
      tester.getTopLeft(find.text('预检-20260925')).dy <
          tester.getTopLeft(find.text('预检-20260901')).dy,
      isTrue,
    );
  });

  testWidgets('普通点击仍然进工作台', (tester) async {
    await tester.pumpWidget(buildApp());
    await tester.pumpAndSettle();

    await tester.tap(find.text('预检-20260901'));
    await tester.pumpAndSettle();

    expect(opened, contains('p1'));
  });
}
