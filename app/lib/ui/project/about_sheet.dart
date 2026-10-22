/// 「关于集刻-采集」面板（2026-10-14 v0.23.0）。
///
/// 入口：项目工作台 AppBar 的 ⋯ 菜单最后一项（现场反馈「这是第几版、
/// 怎么升级」时唯一该去的地方）。
///
/// 与相册镜像面板同款形态：底部抽屉 + SafeArea —— 底部贴边 UI 不消费
/// bottom inset 会被三键导航整块盖住（见 project_console_page 的注释）。
///
/// ⚠️ 展示型页面，不碰任何数据：不查库、不写库、不依赖项目上下文 ——
/// 菜单入口在项目页，但面板本身对 context 无假设。
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../app/theme.dart';
import '../../core/app_info.dart';

Future<void> openAboutSheet(BuildContext context) => showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (_) => const _AboutSheet(),
    );

class _AboutSheet extends ConsumerWidget {
  const _AboutSheet();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final version = ref.watch(appVersionProvider);
    final sessionDiag = ref.watch(sessionDiagProvider).valueOrNull ?? '';
    final theme = Theme.of(context);

    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: AppTheme.accent,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(Icons.inventory_2_outlined,
                      color: Colors.white, size: 24),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        kAppName,
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      Text(
                        AppInfo.tagline,
                        style: theme.textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Text(
              AppInfo.intro,
              style: theme.textTheme.bodyMedium?.copyWith(height: 1.7),
            ),
            const SizedBox(height: 16),
            const Divider(height: 1),
            const SizedBox(height: 12),
            _Row(
              label: '版本',
              // 版本号读 pubspec（见 AppInfo）：读不到显示「版本未知」，
              // 绝不因为展示信息缺失而报错或卡住面板。
              value: version.valueOrNull ?? '…',
            ),
            const SizedBox(height: 8),
            const _Row(label: '数据存放', value: '仅本机，不上传'),
            const SizedBox(height: 8),
            const _Row(label: '拍照方式', value: '系统相机（可在相机设置切换内置）'),
            // ⚠️ 最近一次系统相机收图的诊断（v0.24.6）：「拍 3 张只存 1 张」
            // 返工过两版，每次都在猜原因。把收图过程的关键数字显示出来，
            // 现场复测后**截图这一行**即可定位，不必抓 logcat。
            if (sessionDiag.isNotEmpty) ...[
              const SizedBox(height: 8),
              _Row(label: '收图诊断', value: sessionDiag),
            ],
            const SizedBox(height: 16),
            Text(
              '升级方式：安装新版本覆盖安装即可，项目数据与照片都保留。',
              style: theme.textTheme.bodySmall?.copyWith(height: 1.6),
            ),
          ],
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 76,
          child: Text(label, style: theme.textTheme.bodySmall),
        ),
        Expanded(
          child: Text(
            value,
            style: theme.textTheme.bodyMedium?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    );
  }
}
