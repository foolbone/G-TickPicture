import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../ui/capture/capture_page.dart';
import '../ui/checklist/checklist_import_page.dart';
import '../ui/project/project_console_page.dart';
import '../ui/project/project_list_page.dart';
import '../ui/search/photo_search_page.dart';

/// 路由表。
///
/// 结构（§4.1，2026-10-01 改）：
///   /                     项目列表（App 首页）
///   /project/:id          项目工作台（两个 Tab：照片 / 交付）
///   /project/:id/import   清单导入向导
///   /project/:id/capture  全屏相机（**不在 Tab 内**）
///
/// 为什么相机是独立路由而不是工作台里的 Tab：
/// 它是**全屏相机**，必须能覆盖底部导航栏（沉浸式）。
/// 放在 Tab 里会被 NavigationBar 占掉一条，取景范围变小，
/// 而且底部手势区会和快门冲突。
///
/// 2026-10-01：工作台从「概览 / 采集 / 整理 / 交付」四个 Tab 收敛成
/// 「照片 / 交付」两个 —— 拍照入口并进了照片页（见 OrganizePage），
/// 但相机本身仍然是这条全屏路由。
class AppRoutes {
  const AppRoutes._();

  static const String projects = '/';
  static const String project = '/project';
  static const String import = 'import';
  static const String capture = 'capture';

  /// 按编码搜历史照片（2026-10-15 v0.24.0）。
  /// `?project=<id>` 可选 —— 有则只搜该项目，无则跨项目搜。
  static const String search = '/search';
}

final GoRouter appRouter = GoRouter(
  initialLocation: AppRoutes.projects,
  routes: [
    GoRoute(
      path: AppRoutes.projects,
      name: 'projects',
      builder: (context, state) => const ProjectListPage(),
    ),
    // 字面量端点必须排在 `/project/:id` 之前（2026-10-14 纪律）：
    // 否则 `:id` 会把 `search` 当成项目 id 吃掉。
    GoRoute(
      path: AppRoutes.search,
      name: 'search',
      builder: (context, state) => PhotoSearchPage(
        projectId: state.uri.queryParameters['project'],
      ),
    ),
    GoRoute(
      path: '${AppRoutes.project}/:id',
      name: 'project',
      builder: (context, state) => ProjectConsolePage(
        projectId: state.pathParameters['id']!,
        initialTab: int.tryParse(state.uri.queryParameters['tab'] ?? '') ?? 0,
      ),
      routes: [
        GoRoute(
          path: AppRoutes.import,
          name: 'import',
          builder: (context, state) => ChecklistImportPage(
            projectId: state.pathParameters['id']!,
          ),
        ),
        GoRoute(
          path: AppRoutes.capture,
          name: 'capture',
          builder: (context, state) => CapturePage(
            projectId: state.pathParameters['id']!,
            // 组内补拍（2026-09-30）：?group=<groupId>&gseq=<组序号>。
            // 两个都给才进补拍模式；退出时照片 id 随 pop 结果带回。
            intoGroupId: state.uri.queryParameters['group'],
            groupSeq: int.tryParse(
                state.uri.queryParameters['gseq'] ?? ''),
          ),
        ),
      ],
    ),
  ],
  errorBuilder: (context, state) => Scaffold(
    appBar: AppBar(title: const Text('页面不存在')),
    body: Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          '找不到这个页面。\n${state.uri}',
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 14),
        ),
      ),
    ),
  ),
);
