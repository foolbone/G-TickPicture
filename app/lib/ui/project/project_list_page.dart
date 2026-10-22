import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../app/providers.dart';
import '../../app/router.dart';
import '../../app/theme.dart';
import '../../core/app_info.dart';
import '../../domain/model/enums.dart';
import '../../domain/model/project_summary.dart';
import '../widgets/stage_progress.dart';

/// P1 · 项目列表页 —— App 首页。
///
/// ═══════════════════════════════════════════════════════════════
/// 2026-10-01 重写：从「一堆大卡」改成「能翻能找能收」的工具。
/// ═══════════════════════════════════════════════════════════════
/// 原实现是一张卡 ≈ 130px（标题 + 副标题 + 三段式进度条 + 下一步指引），
/// 一屏只放得下 4 个。仓库一天一个项目、几个月下来几十个项目，就得一路翻。
///
/// 五处改动，全部针对"项目多了以后"：
///   ① **紧凑行**：一屏 8~10 个，两行放完（名称 + 一行信息）；
///   ② **搜索**：匹配项目名与客户 —— 项目一多，唯一能直接捞出来的手段；
///   ③ **排序**：最近新建 / 名称 / 照片最多；
///   ④ **已交付折叠**：干完的收进可展开区，活动项目永远排前面；
///   ⑤ **左滑归档 + 长按多选**：删除不必再钻两级 ⋯ 菜单。
///
/// 进度条为什么整条撤掉：它画的是「清单覆盖率」，而指派下线后
/// `itemDone` 永远是 0 —— 留着就是一根恒为 0% 的假仪表（见 _ProjectRow）。
class ProjectListPage extends ConsumerStatefulWidget {
  const ProjectListPage({super.key});

  @override
  ConsumerState<ProjectListPage> createState() => _ProjectListPageState();
}

/// 排序方式。
///
/// ⚠️ 刻意没有「最近更新」 —— Projects 表只有 createdAt，没有 updatedAt。
/// 拿"最近新建"冒充"最近更新"会在用户按实际作业顺序找东西时指错地方。
enum _SortMode {
  recent('最近新建', Icons.schedule_outlined),
  name('名称', Icons.sort_by_alpha),
  photos('照片最多', Icons.photo_library_outlined);

  const _SortMode(this.label, this.icon);

  final String label;
  final IconData icon;
}

class _ProjectListPageState extends ConsumerState<ProjectListPage> {
  final _query = TextEditingController();
  _SortMode _sort = _SortMode.recent;

  /// 已交付区是否展开。默认收起 —— 它存在的意义就是别挡着活动项目。
  bool _doneExpanded = false;

  /// 多选模式的选中集合。空 = 不在多选模式。
  final _selected = <String>{};

  @override
  void initState() {
    super.initState();
    _query.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  List<ProjectSummary> _visible(List<ProjectSummary> all,
      {required bool done}) {
    final q = _query.text.trim().toLowerCase();
    final list = all.where((s) {
      if ((s.status == ProjectStatus.done) != done) return false;
      if (q.isEmpty) return true;
      // 客户也参与匹配 —— 现场往往是" XX 客户那单在哪"。
      final hay = '${s.name} ${s.client ?? ''}'.toLowerCase();
      return hay.contains(q);
    }).toList();

    switch (_sort) {
      case _SortMode.recent:
        list.sort((a, b) => b.createdAt.compareTo(a.createdAt));
        break;
      case _SortMode.name:
        list.sort((a, b) => a.name.compareTo(b.name));
        break;
      case _SortMode.photos:
        // 照片数相同时再按时间，避免顺序每次渲染都抖。
        list.sort((a, b) {
          final c = b.photoTotal.compareTo(a.photoTotal);
          return c != 0 ? c : b.createdAt.compareTo(a.createdAt);
        });
        break;
    }
    return list;
  }

  void _clearSelection() => setState(_selected.clear);

  void _toggle(String id) => setState(() {
        if (_selected.contains(id)) {
          _selected.remove(id);
        } else {
          _selected.add(id);
        }
      });

  Future<void> _archiveOne(ProjectSummary s) async {
    await ref.read(projectRepositoryProvider).softDelete(s.id);
    if (!mounted) return;
    _scaffold('已把「${s.name}」移到回收站', undo: s.id, name: s.name);
  }

  Future<void> _archiveSelected(List<ProjectSummary> all) async {
    final targets =
        all.where((s) => _selected.contains(s.id)).toList(growable: false);
    if (targets.isEmpty) return;

    final n = targets.length;
    final repo = ref.read(projectRepositoryProvider);
    final failed = <String>[];
    for (final s in targets) {
      try {
        await repo.softDelete(s.id);
      } catch (_) {
        failed.add(s.name);
      }
    }
    if (!mounted) return;
    setState(_selected.clear);
    _scaffold(
      failed.isEmpty
          ? '已把 $n 个项目移到回收站'
          : '$n 个里 ${failed.length} 个失败：${failed.join('、')}',
      undo: targets.length == 1 ? targets.first.id : null,
      name: targets.length == 1 ? targets.first.name : null,
    );
  }

  void _scaffold(String text, {String? undo, String? name}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(text),
        duration: const Duration(seconds: 4),
        action: undo == null
            ? null
            : SnackBarAction(
                label: '撤销',
                onPressed: () =>
                    ref.read(projectRepositoryProvider).restore(undo),
              ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(projectListProvider);
    final selecting = _selected.isNotEmpty;

    return Scaffold(
      appBar: AppBar(
        // 多选模式下顶栏换成"选中 N 个 + 归档" —— 不改标题让人以为还能点进去。
        leading: selecting
            ? IconButton(
                tooltip: '取消多选',
                icon: const Icon(Icons.close),
                onPressed: _clearSelection,
              )
            : null,
        // 主页显示 APP 名称（2026-10-14 v0.23.0 老板诉求）：主标题是
        // App 名，下面挂一行小字说明这一页是干什么的 —— 两个信息都在，
        // 且不与项目工作台顶栏（那里显示项目名）打架。
        title: selecting
            ? Text('已选 ${_selected.length} 个')
            : const Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(kAppName),
                  Text(
                    '仓库预检监装取证',
                    style: TextStyle(
                        fontSize: 11.5, fontWeight: FontWeight.w400),
                  ),
                ],
              ),
        actions: [
          if (selecting)
            TextButton.icon(
              onPressed: () =>
                  _archiveSelected(async.valueOrNull ?? const []),
              icon: const Icon(Icons.delete_sweep_outlined, size: 19),
              label: const Text('移到回收站'),
              style: TextButton.styleFrom(foregroundColor: AppTheme.red),
            )
          else ...[
            // 按编码搜历史照片（2026-10-15 v0.24.0，全局跨项目）。
            // 放主页是因为"找照片"这件事的起点总是"我记不清在哪个项目
            // 拍的了" —— 让人先猜项目再进去翻，等于让人自己找。
            //
            // 2026-10-20 老板：「把项目里的按编码搜索操作放到外面」——
            // 项目页那个入口已删，这里升格成**带文字的常驻按钮**
            // （原来只是个二维码小图标，现场没人发现）。
            TextButton.icon(
              onPressed: () => context.push(AppRoutes.search),
              icon: const Icon(Icons.qr_code_2_outlined, size: 19),
              label: const Text('按编码搜照片'),
              style: TextButton.styleFrom(
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                visualDensity: VisualDensity.compact,
              ),
            ),
            IconButton(
              tooltip: '刷新',
              onPressed: () => ref.invalidate(projectListProvider),
              icon: const Icon(Icons.refresh),
            ),
          ],
        ],
      ),
      floatingActionButton: selecting
          ? null
          : FloatingActionButton.extended(
              onPressed: () => _createProject(context),
              backgroundColor: AppTheme.accent,
              foregroundColor: Colors.white,
              icon: const Icon(Icons.add),
              label: const Text('新建项目'),
            ),
      body: Column(
        children: [
          _SearchBar(
            controller: _query,
            sort: _sort,
            onSortChanged: (m) => setState(() => _sort = m),
            total: async.valueOrNull?.length ?? 0,
            shown: async.maybeWhen(
              data: (list) => _visible(list, done: false).length,
              orElse: () => 0,
            ),
          ),
          Expanded(
            child: async.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, st) => StageEmptyState(
                icon: Icons.error_outline,
                title: '读取项目失败',
                hint: '$e',
              ),
              data: (all) => _buildList(all),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildList(List<ProjectSummary> all) {
    final active = _visible(all, done: false);
    final done = _visible(all, done: true);
    final filtering = _query.text.trim().isNotEmpty;

    return ListView(
      padding: const EdgeInsets.fromLTRB(10, 6, 10, 96),
      children: [
        if (active.isEmpty)
          StageEmptyState(
            icon: Icons.inventory_2_outlined,
            title: filtering
                ? '没有匹配的项目'
                : (all.isEmpty ? '还没有项目' : '没有进行中的项目'),
            hint: filtering
                ? '换个关键词试试 —— 搜索会同时匹配项目名和客户。'
                : '一个项目 = 一次预检任务。新建后就去现场拍照。',
            actionLabel: filtering ? null : '新建项目',
            onAction: filtering ? null : () => _createProject(context),
          )
        else
          // Dismissible 只在非多选、非搜索时挂上：拖着删和勾选是两套互斥的
          // 意图，同时开着会出现"想勾却把它划走了"；搜索态下列表正在实时变，
          // 误划风险更高，也一并关掉。
          //
          // ⚠️ Dismissible **没有 enabled 参数**（要禁只能改 direction），
          // 所以这里是"包或不包"，而不是传个开关。
          ...active.map((s) {
            final row = _ProjectRow(
              summary: s,
              selected: _selected.contains(s.id),
              selecting: _selected.isNotEmpty,
              // ⚠️ 必须 push 不能 go（2026-10-20 老板反馈「按返回直接退出
              // APP」）：`go` 是**替换**导航栈，项目页栈里就只剩它自己，
              // 系统返回键没有上一页可退 → 直接退出应用。push 才有
              // 「列表 → 项目」的层级，返回键回到列表。
              onTap: () => context.push('${AppRoutes.project}/${s.id}'),
              onLongPress: () => _toggle(s.id),
              onSelect: () => _toggle(s.id),
            );
            if (_selected.isNotEmpty || filtering) return row;
            return Dismissible(
              key: ValueKey('project-${s.id}'),
              direction: DismissDirection.endToStart,
              background: Container(
                alignment: Alignment.centerRight,
                padding: const EdgeInsets.only(right: 20),
                color: AppTheme.redBg,
                child: const Icon(Icons.delete_sweep_outlined,
                    color: AppTheme.red),
              ),
              // 左滑直接归档 + SnackBar 撤销。
              // 不再先弹"确定吗" —— 软删可一键还原，弹确认反而把每一次
              // 正常操作的成本抬高，而真正的风险 covered 在"可撤销"上。
              onDismissed: (_) => _archiveOne(s),
              child: row,
            );
          }),

        // ── 已交付区 ──
        // 干完的项目默认收起：现场天天看的只有当天那几个，
        // 历史项目要能被找到，但不能排在进行中的前面挡路。
        if (done.isNotEmpty)
          Card(
            margin: const EdgeInsets.only(top: 8),
            child: Column(
              children: [
                ListTile(
                  dense: true,
                  leading: const Icon(Icons.task_alt,
                      size: 18, color: AppTheme.green),
                  title: Text(
                    '已交付（${done.length}）',
                    style: const TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.navy,
                    ),
                  ),
                  trailing: Icon(
                    _doneExpanded ? Icons.expand_less : Icons.expand_more,
                    size: 20,
                    color: AppTheme.textMuted,
                  ),
                  onTap: () => setState(() => _doneExpanded = !_doneExpanded),
                ),
                if (_doneExpanded)
                  ...done.map(
                    (s) => _ProjectRow(
                      summary: s,
                      selected: false,
                      selecting: false,
                      dimmed: true,
                      // ⚠️ 必须 push 不能 go（2026-10-20 老板反馈「按返回直接退出
              // APP」）：`go` 是**替换**导航栈，项目页栈里就只剩它自己，
              // 系统返回键没有上一页可退 → 直接退出应用。push 才有
              // 「列表 → 项目」的层级，返回键回到列表。
              onTap: () => context.push('${AppRoutes.project}/${s.id}'),
                    ),
                  ),
              ],
            ),
          ),

        const SizedBox(height: 14),
        const _RecycleBin(),
      ],
    );
  }

  Future<void> _createProject(BuildContext context) async {
    final created = await showDialog<({String name, String? client})>(
      context: context,
      builder: (_) => const _NewProjectDialog(),
    );
    if (created == null || !context.mounted) return;

    final repo = ref.read(projectRepositoryProvider);
    final id = await repo.create(name: created.name, client: created.client);

    if (!context.mounted) return;
    // 建完直接进工作台 —— 少一次点击。同样用 push：返回键要能回列表。
    context.push('${AppRoutes.project}/$id');
  }
}

// ═══════════════════════════════════════════════════════════════
// 搜索 + 排序
// ═══════════════════════════════════════════════════════════════

/// 顶部的搜索框与排序切换。
///
/// 放在 body 顶部而不是 AppBar 标题替换件：换成搜索 AppBar 要再点一次返回
/// 才退出搜索态，而这里**随时可见且即时生效**，一目了然还剩几个。
class _SearchBar extends StatelessWidget {
  const _SearchBar({
    required this.controller,
    required this.sort,
    required this.onSortChanged,
    required this.total,
    required this.shown,
  });

  final TextEditingController controller;
  final _SortMode sort;
  final ValueChanged<_SortMode> onSortChanged;
  final int total;
  final int shown;

  @override
  Widget build(BuildContext context) {
    final hasQuery = controller.text.trim().isNotEmpty;

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
      child: Row(
        children: [
          Expanded(
            child: SizedBox(
              height: 40,
              child: TextField(
                controller: controller,
                textInputAction: TextInputAction.search,
                decoration: InputDecoration(
                  isDense: true,
                  prefixIcon: const Icon(Icons.search, size: 19),
                  hintText: '搜项目名或客户',
                  contentPadding: const EdgeInsets.all(0),
                  border: const OutlineInputBorder(
                    borderRadius: BorderRadius.all(Radius.circular(9)),
                    borderSide: BorderSide(color: AppTheme.line),
                  ),
                  enabledBorder: const OutlineInputBorder(
                    borderRadius: BorderRadius.all(Radius.circular(9)),
                    borderSide: BorderSide(color: AppTheme.line),
                  ),
                  suffixIcon: hasQuery
                      ? IconButton(
                          tooltip: '清空',
                          icon: const Icon(Icons.close, size: 17),
                          onPressed: () => controller.clear(),
                        )
                      : null,
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          _SortButton(sort: sort, onChanged: onSortChanged),
          if (hasQuery) ...[
            const SizedBox(width: 8),
            Text(
              '$shown/$total',
              style:
                  const TextStyle(fontSize: 12, color: AppTheme.textMuted),
            ),
          ],
        ],
      ),
    );
  }
}

class _SortButton extends StatelessWidget {
  const _SortButton({required this.sort, required this.onChanged});

  final _SortMode sort;
  final ValueChanged<_SortMode> onChanged;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: OutlinedButton.icon(
        onPressed: () async {
          final picked = await showMenu<_SortMode>(
            context: context,
            position: const RelativeRect.fromLTRB(1000, 90, 8, 0),
            items: [
              for (final m in _SortMode.values)
                PopupMenuItem(
                  value: m,
                  child: Row(
                    children: [
                      Icon(m.icon, size: 17,
                          color: m == sort
                              ? AppTheme.accent
                              : AppTheme.textMuted),
                      const SizedBox(width: 8),
                      Text(m.label),
                    ],
                  ),
                ),
            ],
          );
          if (picked != null) onChanged(picked);
        },
        icon: Icon(sort.icon, size: 17),
        label: Text(sort.label, style: const TextStyle(fontSize: 12.5)),
        style: OutlinedButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 9),
          side: const BorderSide(color: AppTheme.line),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 紧凑行
// ═══════════════════════════════════════════════════════════════

/// 一个项目一行（两行文字搞定，约 62px）。
///
/// 【为什么没有进度条】原来是 StageProgressBar（容器 + 三段文字标签 ≈ 44px）。
/// 它画的"清单覆盖率"依赖 itemDone —— 指派下线后没有任何路径会去写
/// `itemId`，那个数恒为 0。留一根永远是 0% 的进度条等于骗人，撤了。
/// 「下一步该干什么」改由右侧状态 badge 承担。
class _ProjectRow extends ConsumerWidget {
  const _ProjectRow({
    required this.summary,
    required this.selected,
    required this.selecting,
    required this.onTap,
    this.onLongPress,
    this.onSelect,
    this.dimmed = false,
  });

  final ProjectSummary summary;
  final bool selected;
  final bool selecting;
  final VoidCallback onTap;
  final VoidCallback? onLongPress;
  final VoidCallback? onSelect;
  final bool dimmed;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = summary;
    final dateStr = DateFormat('yyyy-MM-dd').format(s.createdAt);

    return Opacity(
      opacity: dimmed ? 0.62 : 1,
      child: Card(
        margin: const EdgeInsets.only(bottom: 8),
        color: selected ? AppTheme.accent.withValues(alpha: 0.07) : null,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: BorderSide(
            color: selected ? AppTheme.accent : AppTheme.line,
            width: selected ? 1.6 : 1,
          ),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: selecting ? onSelect : onTap,
          onLongPress: selecting ? onSelect : onLongPress,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 6, 10),
            child: Row(
              children: [
                if (selecting) ...[
                  Icon(
                    selected
                        ? Icons.check_circle
                        : Icons.radio_button_unchecked,
                    size: 19,
                    color: selected ? AppTheme.accent : AppTheme.textMuted,
                  ),
                  const SizedBox(width: 10),
                ],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        s.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.navy,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        [
                          if (s.client != null && s.client!.isNotEmpty)
                            s.client!,
                          dateStr,
                          '照片 ${s.photoTotal}',
                          '待整理 ${s.groupPending} 组',
                        ].join('  ·  '),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 11.5, color: AppTheme.textMuted),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 6),
                StageBadge(
                  text: s.status.label,
                  color: _statusColor(s.status.code),
                ),
                _RowMenu(summary: s),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Color _statusColor(String code) => switch (code) {
        'collecting' => AppTheme.navy,
        'organizing' => AppTheme.accent,
        'delivering' => AppTheme.green,
        'done' => AppTheme.green,
        _ => AppTheme.textMuted,
      };
}

/// 行尾 ⋯ 菜单。
///
/// 「标记为已交付」是这里唯一的新动作 —— 它是「已交付折叠区」的入口：
/// 没有它，那个区永远为空（以前 setStatus 从未被调用过，所有项目都停在
/// 'collecting'，谁也不可能自己变成已完成）。
class _RowMenu extends ConsumerWidget {
  const _RowMenu({required this.summary});

  final ProjectSummary summary;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = summary;
    final repo = ref.read(projectRepositoryProvider);
    final messenger = ScaffoldMessenger.of(context);
    final isDone = s.status == ProjectStatus.done;

    Future<void> rename() async {
      final name = await showDialog<String>(
        context: context,
        builder: (_) => _RenameDialog(current: s.name),
      );
      if (name == null || name.trim().isEmpty) return;
      await repo.rename(s.id, name.trim());
    }

    Future<void> toggleDone() async {
      await repo.setStatus(
        s.id,
        isDone ? ProjectStatus.delivering : ProjectStatus.done,
      );
      if (!context.mounted) return;
      messenger.showSnackBar(
        SnackBar(
            content: Text(isDone ? '「${s.name}」已移回进行中' : '「${s.name}」已标记为交付完成')),
      );
    }

    Future<void> archive() async {
      await repo.softDelete(s.id);
      if (!context.mounted) return;
      messenger.showSnackBar(
        SnackBar(
          content: Text('已把「${s.name}」移到回收站'),
          action: SnackBarAction(
            label: '撤销',
            onPressed: () => repo.restore(s.id),
          ),
        ),
      );
    }

    return PopupMenuButton<String>(
      tooltip: '更多',
      icon: const Icon(Icons.more_vert, size: 19),
      padding: EdgeInsets.zero,
      onSelected: (v) async {
        switch (v) {
          case 'rename':
            await rename();
            break;
          case 'toggle':
            await toggleDone();
            break;
          case 'archive':
            await archive();
            break;
        }
      },
      itemBuilder: (_) => [
        const PopupMenuItem(
          value: 'rename',
          child: Row(
            children: [
              Icon(Icons.edit_outlined, size: 18),
              SizedBox(width: 8),
              Text('重命名'),
            ],
          ),
        ),
        PopupMenuItem(
          value: 'toggle',
          child: Row(
            children: [
              Icon(isDone ? Icons.undo : Icons.task_alt, size: 18),
              const SizedBox(width: 8),
              Text(isDone ? '移回进行中' : '标记为已交付'),
            ],
          ),
        ),
        const PopupMenuItem(
          value: 'archive',
          child: Row(
            children: [
              Icon(Icons.delete_outline, size: 18, color: AppTheme.red),
              SizedBox(width: 8),
              Text('移到回收站', style: TextStyle(color: AppTheme.red)),
            ],
          ),
        ),
      ],
    );
  }
}

class _RenameDialog extends StatefulWidget {
  const _RenameDialog({required this.current});

  final String current;

  @override
  State<_RenameDialog> createState() => _RenameDialogState();
}

class _RenameDialogState extends State<_RenameDialog> {
  late final TextEditingController _c;

  @override
  void initState() {
    super.initState();
    _c = TextEditingController(text: widget.current);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('重命名项目'),
      content: TextField(
        controller: _c,
        autofocus: true,
        decoration: const InputDecoration(
          labelText: '项目名称',
          border: OutlineInputBorder(),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _c.text.trim()),
          child: const Text('保存'),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 回收站：软删的项目可恢复 / 彻底清盘
// ═══════════════════════════════════════════════════════════════

class _RecycleBin extends ConsumerWidget {
  const _RecycleBin();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deleted = ref.watch(deletedProjectsProvider);

    return deleted.when(
      loading: () => const SizedBox.shrink(),
      error: (_, __) => const SizedBox.shrink(),
      data: (items) {
        if (items.isEmpty) return const SizedBox.shrink();
        return Container(
          decoration: BoxDecoration(
            color: AppTheme.redBg,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppTheme.red.withValues(alpha: 0.25)),
          ),
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.delete_sweep_outlined,
                      size: 16, color: AppTheme.red),
                  const SizedBox(width: 6),
                  Text(
                    '回收站（${items.length}）',
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.red,
                    ),
                  ),
                  const Spacer(),
                  TextButton(
                    onPressed: () => ref.invalidate(deletedProjectsProvider),
                    child: const Text('刷新', style: TextStyle(fontSize: 12)),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              ...items.map((s) => _RecycleTile(summary: s)),
            ],
          ),
        );
      },
    );
  }
}

class _RecycleTile extends ConsumerWidget {
  const _RecycleTile({required this.summary});

  final ProjectSummary summary;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = summary;
    final dateStr = DateFormat('yyyy-MM-dd').format(s.createdAt);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  s.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.navy,
                  ),
                ),
                Text(
                  '$dateStr · 照片 ${s.photoTotal}',
                  style: const TextStyle(
                      fontSize: 11, color: AppTheme.textMuted),
                ),
              ],
            ),
          ),
          TextButton(
            onPressed: () => _restore(context, ref, s),
            child: const Text('恢复'),
          ),
          const SizedBox(width: 4),
          TextButton(
            style: TextButton.styleFrom(foregroundColor: AppTheme.red),
            onPressed: () => _confirmPurge(context, ref, s),
            child: const Text('彻底删除'),
          ),
        ],
      ),
    );
  }

  Future<void> _restore(
    BuildContext context,
    WidgetRef ref,
    ProjectSummary s,
  ) async {
    await ref.read(projectRepositoryProvider).restore(s.id);
    if (!context.mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text('已恢复「${s.name}」')));
  }

  /// 彻底清盘：强确认，删 DB + 磁盘照片。
  Future<void> _confirmPurge(
    BuildContext context,
    WidgetRef ref,
    ProjectSummary s,
  ) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('彻底删除？'),
        content: Text(
          '「${s.name}」及其全部数据库记录、磁盘上的原始照片与缩略图'
          '将被永久删除，无法恢复。\n\n'
          '如果还想保留，请点「取消」回回收站。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppTheme.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('彻底删除'),
          ),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;

    await ref.read(projectRepositoryProvider).purge(s.id);
    if (!context.mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text('已彻底删除「${s.name}」')));
  }
}

// ═══════════════════════════════════════════════════════════════

class _NewProjectDialog extends StatefulWidget {
  const _NewProjectDialog();

  @override
  State<_NewProjectDialog> createState() => _NewProjectDialogState();
}

class _NewProjectDialogState extends State<_NewProjectDialog> {
  late final TextEditingController _name;
  final TextEditingController _client = TextEditingController();

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(
      text: '预检-${DateFormat('yyyyMMdd').format(DateTime.now())}',
    );
  }

  @override
  void dispose() {
    _name.dispose();
    _client.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('新建项目'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _name,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: '项目名称',
              hintText: '例：预检-20260922',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _client,
            decoration: const InputDecoration(
              labelText: '客户（可选）',
              border: OutlineInputBorder(),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () {
            final n = _name.text.trim();
            if (n.isEmpty) return;
            final c = _client.text.trim();
            Navigator.pop(context, (name: n, client: c.isEmpty ? null : c));
          },
          child: const Text('创建'),
        ),
      ],
    );
  }
}
