
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:share_plus/share_plus.dart';

import '../../app/providers.dart';
import '../../app/router.dart';
import '../../app/theme.dart';
import '../../domain/capture/gallery_service.dart';
import '../../domain/export/delivery_history.dart';
import '../../domain/export/delivery_share.dart';
import '../../domain/export/export_service.dart';
import '../../domain/export/export_service_impl.dart';
import '../../domain/model/delivery_plan.dart';
import '../../domain/model/delivery_readiness.dart';
import '../../domain/model/project_summary.dart';
import '../organize/organize_page.dart';
import '../widgets/stage_progress.dart';
import 'about_sheet.dart';

/// P2 · 项目工作台。
///
/// ═══════════════════════════════════════════════════════════════
/// 2026-10-01 重构：**四个 Tab 收敛成两个**。
/// ═══════════════════════════════════════════════════════════════
/// 旧结构：概览 / 采集 / 整理 / 交付。问题在于前三个都在讲同一件事，
/// 于是每一页都变得没什么可看：
///   · 「采集」Tab 里**只有**一个按钮（进全屏相机）—— 为一个按钮
///     占一条底部导航位，是纯粹的浪费；
///   · 「概览」Tab 是一堆装饰（进度条、四个数字卡片、作业流程说明），
///     真正有价值的只有「清单缺口」这一块；
///   · 真正在干活的只有「整理」。
///
/// 现在的结构：**照片 / 交付**。
///   · 「照片」= 拍照入库 + 归组成箱（拍照、相册导入、预检组列表、
///     监装墙全在这一页）；
///   · 「交付」= 打包发送。
///
/// 相册镜像开关收进 AppBar 的 ⋯ 菜单。
///
/// ═══════════════════════════════════════════════════════════════
/// 2026-10-01（同日第二刀）：**指派下线**。
/// ═══════════════════════════════════════════════════════════════
/// 「指派货品」被判定为没用，UI 层整条链路拆除：指派面板、已指派页签、
/// 一键确认、清单缺口面板、照片页的覆盖率仪表。
/// 照片的组织维度收敛为**部类 → 箱号 → 组**，不再与货品关联。
/// 交付不受影响 —— 未指派照片本来就走「原始文件名 + 箱号目录」那一路。
class ProjectConsolePage extends ConsumerStatefulWidget {
  const ProjectConsolePage({
    super.key,
    required this.projectId,
    this.initialTab = 0,
  });

  final String projectId;
  final int initialTab;

  @override
  ConsumerState<ProjectConsolePage> createState() => _ProjectConsolePageState();
}

class _ProjectConsolePageState extends ConsumerState<ProjectConsolePage> {
  late int _tab;

  @override
  void initState() {
    super.initState();
    _tab = widget.initialTab.clamp(0, 1);
  }

  /// 合并到其他项目（2026-10-08 真机诉求③）。
  ///
  /// 把本项目**全部**照片 / 组 / 批次 / 交付记录并进所选项目，本项目
  /// 归档（从项目列表消失）。两步确认 + 红字强调不可逆 —— 合并是
  /// 少数"批量动别人数据"的操作，弹窗措辞必须让人看清方向：
  /// 是「本项目 → 目标项目」，不是反过来。
  Future<void> _mergeIntoOtherProject(ProjectSummary summary) async {
    // ⚠️ 不收 BuildContext 参数：参数 context 守不到 State.mounted，
    // analyze 会报 use_build_context_synchronously（unrelated mounted）。
    final projects =
        ref.read(projectListProvider).valueOrNull ?? const <ProjectSummary>[];
    final others = projects.where((pr) => pr.id != widget.projectId).toList();
    if (!mounted) return;
    if (others.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('还没有其他项目 —— 先回首页新建一个，再回来合并。'),
      ));
      return;
    }

    // ⚠️ 列表必须可滚动（2026-10-09，同「移动分组」面板）：项目一多
    // Column 直排超出屏幕，最后一行被裁一半、点不到。标题固定，列表
    // Flexible+ListView(shrinkWrap)：少时包住内容，多时面板内滚动。
    final target = await showModalBottomSheet<ProjectSummary>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              title: Text('「${summary.name}」合并到哪个项目？'),
              subtitle: const Text('合并后本项目归档，照片全部进入目标项目'),
            ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final pr in others)
                    ListTile(
                      leading: const Icon(Icons.folder_outlined),
                      title: Text(pr.name),
                      subtitle: Text('${pr.photoTotal} 张'),
                      onTap: () => Navigator.of(ctx).pop(pr),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (target == null || !mounted) return;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('确认合并？'),
        content: Text(
          '把「${summary.name}」的全部照片与分组并进「${target.name}」。\n\n'
          '· 照片、分组、批次、箱号全部随行，序号在目标项目里重排\n'
          '· 本项目将归档，从项目列表消失\n'
          '· 若本项目有已确认归属货品的组，合并会被拒绝\n'
          '· 合并不可自动撤销',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppTheme.red),
            child: const Text('合并'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(organizeRepositoryProvider).mergeProjectInto(
            fromProjectId: widget.projectId,
            toProjectId: target.id,
          );
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(
        content: Text('已合并进「${target.name}」—— 本项目已归档'),
      ));
      // 回项目列表（本项目已归档，留在本页会看到"项目不存在"）
      context.go(AppRoutes.projects);
    } catch (e) {
      messenger.showSnackBar(SnackBar(
        content: Text('合并失败：$e'),
        duration: const Duration(seconds: 5),
      ));
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(projectSummaryProvider(widget.projectId));

    return async.when(
      loading: () => Scaffold(
        appBar: AppBar(
          leading: const _BackToListButton(),
          title: const Text('项目'),
        ),
        body: const Center(child: CircularProgressIndicator()),
      ),
      error: (e, st) => Scaffold(
        appBar: AppBar(
          leading: const _BackToListButton(),
          title: const Text('项目'),
        ),
        body: StageEmptyState(
          icon: Icons.error_outline,
          title: '读取项目失败',
          hint: '$e',
        ),
      ),
      data: (summary) {
        if (summary == null) {
          return Scaffold(
            appBar: AppBar(
              leading: const _BackToListButton(),
              title: const Text('项目'),
            ),
            body: const StageEmptyState(
              icon: Icons.search_off,
              title: '项目不存在',
              hint: '它可能已被删除。',
            ),
          );
        }

        // 底栏角标 = 「待办件数」：待确认的组 + 没进任何组的预检照片。
        // ⚠️ 不能用 photoUnassigned（2026-10-15 老板反馈"统计数对不上"）：
        // 预检流程里照片入了组也还是 unassigned（归属确认才写 state），
        // 组内照片会同时被「组待办」和「照片待办」数两遍 —— 6 组 · 19 张
        // 的项目角标显示 25，看起来像照片数对不上。已入组的照片由
        // groupPending 代表，photoOrphan 只数真正散着的（监装照片无组
        // 语义，不计）。photoUnassigned 的「确认进度」口径继续给
        // organizeDone 与交付就绪用，不受影响。
        final pending = summary.groupPending + summary.photoOrphan;

        return Scaffold(
          appBar: AppBar(
            // 老板诉求：进入项目后要能退出去换别的项目。
            // 不能依赖系统返回手势 —— 列表页可能是 go() 替换掉的，栈里未必有它。
            leading: const _BackToListButton(),
            title: Text(summary.name),
            actions: [
              // 低频设置收进 ⋯ 菜单（2026-09-30 老板拍板弱化「导入清单」，
              // 2026-10-01 概览 Tab 下线后「相册镜像」也搬到这里）。
              // 顶栏只留这一个入口，不抢「照片 / 交付」这两个主行动的视觉。
              PopupMenuButton<String>(
                tooltip: '更多',
                icon: const Icon(Icons.more_vert, color: Colors.white),
                onSelected: (v) {
                  if (v == 'import') {
                    context.push('${AppRoutes.project}/'
                        '${widget.projectId}/${AppRoutes.import}');
                  } else if (v == 'gallery') {
                    _openGalleryMirror(context, widget.projectId);
                  } else if (v == 'merge') {
                    _mergeIntoOtherProject(summary);
                  } else if (v == 'about') {
                    openAboutSheet(context);
                  }
                },
                itemBuilder: (_) => [
                  // 「导入清单」只在还没导入时出现 —— 已导入就是一次性
                  // 动作的收尾，再摆出来只会让人以为要点它。
                  if (summary.itemTotal == 0)
                    const PopupMenuItem(
                      value: 'import',
                      child: Row(
                        children: [
                          Icon(Icons.upload_file, size: 18),
                          SizedBox(width: 8),
                          Text('导入货品清单'),
                        ],
                      ),
                    ),
                  // 「合并项目」（2026-10-08 真机诉求③）：把本项目全部
                  // 照片/组/批次并进另一个项目。低频但重要 —— 分错项目
                  // 或分两天拍同一批货时，唯一的救回手段。
                  const PopupMenuItem(
                    value: 'merge',
                    child: Row(
                      children: [
                        Icon(Icons.merge, size: 18),
                        SizedBox(width: 8),
                        Text('合并到其他项目'),
                      ],
                    ),
                  ),
                  // 「搜索本项目照片」已移到首页（2026-10-20 老板：「把项目里
                  // 的按编码搜索操作放到外面」）—— 找照片的起点常是「记不清
                  // 在哪个项目拍的」，限制在本项目反而挡路。首页入口见
                  // project_list_page 顶栏。
                  const PopupMenuItem(
                    value: 'gallery',
                    child: Row(
                      children: [
                        Icon(Icons.photo_album_outlined, size: 18),
                        SizedBox(width: 8),
                        Text('拍照同步到手机相册'),
                      ],
                    ),
                  ),
                  // 「关于」（2026-10-14 v0.23.0）：APP 介绍 + 版本号。
                  // 放菜单最末位 —— 低频中的低频，但它必须在（现场反馈
                  // 「这是第几版、怎么升级」时，唯一该去的地方）。
                  const PopupMenuItem(
                    value: 'about',
                    child: Row(
                      children: [
                        Icon(Icons.info_outline, size: 18),
                        SizedBox(width: 8),
                        Text('关于集刻-采集'),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
          body: IndexedStack(
            index: _tab,
            children: [
              OrganizePage(
                projectId: widget.projectId,
                summary: summary,
              ),
              _DeliverTab(projectId: widget.projectId),
            ],
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            destinations: [
              NavigationDestination(
                // 角标留在「照片」上：这是唯一**行为驱动**的 Tab ——
                // 有活儿干才亮数字（§4.2 P6）。
                icon: pending == 0
                    ? const Icon(Icons.photo_library_outlined)
                    : Badge(
                        label: Text('$pending'),
                        child: const Icon(Icons.photo_library_outlined),
                      ),
                selectedIcon: pending == 0
                    ? const Icon(Icons.photo_library)
                    : Badge(
                        label: Text('$pending'),
                        child: const Icon(Icons.photo_library),
                      ),
                label: '照片',
              ),
              const NavigationDestination(
                icon: Icon(Icons.ios_share_outlined),
                selectedIcon: Icon(Icons.ios_share),
                label: '交付',
              ),
            ],
          ),
        );
      },
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 返回项目列表（AppBar leading）
// ═══════════════════════════════════════════════════════════════

/// 左上角统一的「所有项目」出口。
///
/// 2026-10-20：进项目的入口已从 `go` 改成 `push`（老板反馈「在项目里按
/// 返回直接退出 App」—— go 是**替换**导航栈，栈里没有上一页，返回键就退出
/// 应用）。所以这里优先 `pop` 回到真正的上一页（列表 / 搜索结果）；
/// 只有深链直接进项目、栈里确实没有上一页时，才 `go` 兜底回列表。
class _BackToListButton extends StatelessWidget {
  const _BackToListButton();

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: const Icon(Icons.arrow_back, color: Colors.white),
      tooltip: '所有项目',
      onPressed: () => context.canPop()
          ? context.pop()
          : context.go(AppRoutes.projects),
    );
  }
}

/// 打开「拍照同步到手机相册」面板（AppBar ⋯ 菜单项）。
///
/// 2026-10-01：概览 Tab 下线，这块从概览页搬到这里。它是低频设置，
/// 用底部抽屉而不是常驻卡片 —— 抽屉关掉后就不再占视觉。
///
/// ⚠️ 底部贴边 UI 必查 SafeArea：补存按钮在最底下，不消费 bottom inset
/// 就会画在导航栏下面（三键导航会整块盖住）。
void _openGalleryMirror(BuildContext context, String projectId) {
  showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (ctx) => SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 14),
        child: _GalleryCard(projectId: projectId),
      ),
    ),
  );
}

// ═══════════════════════════════════════════════════════════════
// Tab 2 · 交付
// ═══════════════════════════════════════════════════════════════

class _DeliverTab extends ConsumerStatefulWidget {
  const _DeliverTab({required this.projectId});

  final String projectId;

  @override
  ConsumerState<_DeliverTab> createState() => _DeliverTabState();
}

class _DeliverTabState extends ConsumerState<_DeliverTab> {
  ExportOptions _options = const ExportOptions();

  /// 「交付内容」明细是否展开。默认收起 —— 老板 2026-10-01：说明太多占屏。
  bool _showDetail = false;

  /// 打包进行中。非空即表示正在跑 —— 此时禁用按钮、显示进度与取消。
  _PackProgress? _packing;

  DeliveryResult? _lastResult;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(deliveryReadinessProvider(widget.projectId));

    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, st) => StageEmptyState(
        icon: Icons.error_outline,
        title: '校验失败',
        hint: '$e',
      ),
      data: (r) => _buildReady(context, r),
    );
  }

  Widget _buildReady(BuildContext context, DeliveryReadiness r) {
    final planAsync = ref.watch(deliveryPlanProvider(widget.projectId));
    final plan = planAsync.valueOrNull;
    final packing = _packing;

    // 指派下线后「已对应编码」恒为 0，所以不再单独列这一堆 ——
    // 显示一个永远是 0 的行纯属占地方。
    //
    // ⚠️ 顺手修掉一处潜伏 bug：plan 尚未算完时原本是
    //    `photoConfirmed - photoUnassigned`。这两个是**互斥的 photos.state**
    //    （见 integrity_checks.readiness 的 SQL），相减没有意义，
    //    一旦 unassigned > confirmed 还会显示负数。改成相加（预检总量）。
    final supervision = plan?.supervisionPhotos.length ?? 0;
    final precheckTotal = plan == null
        ? (r.photoConfirmed + r.photoUnassigned)
        : plan.photos.length + plan.unmatchedPhotos.length;

    return ListView(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 28),
      children: [
        // ── 交付内容预览 ──
        // ⚠️ 没有自检卡片是刻意的：老板 09-27 拍板「交付时去掉原来的检查，
        //    直接按分组打包」。异常只在包内 manifest 留痕，不在现场打扰人。
        //
        // 2026-10-01 压缩：原先这里是一张「交付内容预览」卡（4 行 + 一段
        // 两行说明），加上下面「包内布局」「关于交付」两张说明卡，三段文字
        // 占了半个屏幕，而人真正要点的只有最底下那个「生成交付包」。
        // 现在把全部数字压成**一行**，说明全部收起。
        Card(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 11, 14, 11),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Text(
                      '交付内容',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.navy,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      _packing == null
                          ? '预检 $precheckTotal 张 · 监装 $supervision 张'
                          : '打包中',
                      style: const TextStyle(
                          fontSize: 12.5, color: AppTheme.textMuted),
                    ),
                    const Spacer(),
                    if (r.photoUnused > 0)
                      _MiniChip(text: '不用 ${r.photoUnused}'),
                    const SizedBox(width: 4),
                    // 明细与包内布局说明折叠在这里 —— 想看的人才展开。
                    IconButton(
                      tooltip: '展开明细',
                      visualDensity: VisualDensity.compact,
                      constraints: const BoxConstraints(
                          minWidth: 32, minHeight: 32),
                      padding: EdgeInsets.zero,
                      icon: Icon(
                        _showDetail
                            ? Icons.expand_less
                            : Icons.expand_more,
                        size: 20,
                        color: AppTheme.textMuted,
                      ),
                      onPressed: () =>
                          setState(() => _showDetail = !_showDetail),
                    ),
                  ],
                ),
                    if (_showDetail) ...[
                      const SizedBox(height: 8),
                      const Divider(height: 1),
                      const SizedBox(height: 6),
                      _Line('预检照片', '$precheckTotal 张'),
                      _Line('监装照片', '$supervision 张'),
                      _Line('标记不用的照片', '${r.photoUnused} 张'),
                      const SizedBox(height: 4),
                      const Text(
                        '原件不会被改名或移动 —— 包里放的一直是副本。',
                        style: TextStyle(
                            fontSize: 11.5, color: AppTheme.textMuted),
                      ),
                      planAsync.maybeWhen(
                    data: (plan) => _PackageLayoutCard(
                      plan: plan,
                      groupByCarton: _options.groupByCarton,
                    ),
                    orElse: () => const SizedBox.shrink(),
                  ),
                ],
              ],
            ),
          ),
        ),

        const SizedBox(height: 10),

        // ── 勾选项（§4.3 P9）──
        Card(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 8),
            child: Column(
              children: [
                // 勾选项：只留标题 + 极短副标题。
                // 原先每个选项都带两三行说明（"长边 2560 / 质量 85，标签和
                // 箱号依然清晰；原图不会被改动…"），六项加起来占掉一整屏。
                // 这些解释是**选完之后**才关心的，要解释也只在点开的那一瞬，
                // 所以压成一个 ⓘ：按住看一眼即可。
                _OptionSwitch(
                  title: '原始照片',
                  subtitle: null,
                  value: _options.includeRaw,
                  enabled: packing == null,
                  hint: '交付按「预检 / 监装」分开的照片本身。关掉就只剩清单文件。',
                  onChanged: (v) => setState(
                    () => _options = _copyOptions(includeRaw: v),
                  ),
                ),
                if (_options.includeRaw)
                  _OptionSwitch(
                    title: '按箱号分文件夹',
                    subtitle: null,
                    value: _options.groupByCarton,
                    enabled: packing == null,
                    indent: true,
                    hint: '按整理时你指定的箱号分文件夹；没指定箱号的进「_未分箱」。',
                    onChanged: (v) => setState(
                      () => _options = _copyOptions(groupByCarton: v),
                    ),
                  ),
                _OptionSwitch(
                  title: '照片清单文件',
                  subtitle: null,
                  value: _options.includeManifest,
                  enabled: packing == null,
                  hint: '给程序读的完整记录（manifest.json），不用于人工核对。',
                  onChanged: (v) => setState(
                    () => _options = _copyOptions(includeManifest: v),
                  ),
                ),
                _OptionSwitch(
                  title: '含未使用照片',
                  subtitle: null,
                  value: _options.includeUnused,
                  enabled: packing == null,
                  hint: '标记为「这张不用」的照片，放进「_未使用」文件夹。',
                  onChanged: (v) => setState(
                    () => _options = _copyOptions(includeUnused: v),
                  ),
                ),
                _OptionSwitch(
                  title: '压缩画质（微信传输）',
                  subtitle: null,
                  value: _options.compressPhotos,
                  enabled: packing == null,
                  // 2026-10-20 老板拍板：**默认不压缩**，交付带原图画质。
                  // 只有要发微信、嫌包太大时才手动打开（长边 2560 / 质量 85）。
                  hint: '默认关闭：交付原图，画质零损失。'
                      '打开后长边压到 2560 / 质量 85，适合发微信；'
                      'App 内的原图始终不会被改动。',
                  onChanged: (v) => setState(
                    () => _options = _copyOptions(compressPhotos: v),
                  ),
                ),
                _OptionSwitch(
                  title: '自动分卷',
                  subtitle: null,
                  value: _options.splitVolumes,
                  enabled: packing == null,
                  // 【2026-10-01】原来它是「压缩画质」的**子选项**（`if (compressPhotos)`），
                  // 理由是"压缩过才会超微信上限"。这个耦合是错的：
                  // 关掉压缩后走原图，单包更容易破 1GB —— 恰恰是更需要分卷的场景。
                  // 老板拍板两者独立，于是提到顶层、去掉 indent。
                  hint: '超过 500MB 自动拆成多个 ZIP（每卷都能独立解压），'
                      '适配微信单文件 1GB 上限；关掉就出单个包（走网盘用）。'
                      '注意：分卷后要逐卷发送，微信不收一次多文件。',
                  onChanged: (v) => setState(
                    () => _options = _copyOptions(splitVolumes: v),
                  ),
                ),
              ],
            ),
          ),
        ),

        const SizedBox(height: 12),

        // ── 主按钮 / 进度 ──
        // 老板 09-27 拍板：交付不设检查 —— 点了就打包，没有任何确认框。
        if (packing == null) ...[
          FilledButton.icon(
            onPressed: _startPack,
            style: FilledButton.styleFrom(
              backgroundColor: AppTheme.accent,
              minimumSize: const Size(double.infinity, 52),
            ),
            icon: const Icon(Icons.inventory_2_outlined, size: 19),
            label: const Text('生成交付包'),
          ),
        ] else
          _PackingPanel(
            progress: packing,
            onCancel: _cancelPack,
          ),

              // ── 上一次的产物 ──
              if (_lastResult != null) ...[
                const SizedBox(height: 12),
                _DoneCard(
                  result: _lastResult!,
                  sentVolumes: _sentVolumes,
                  onShareVolume: _shareVolume,
                  onShareAll: _shareAllVolumes,
                ),
              ],

              // ── 历史交付包（2026-10-20 v0.24.8）──
              // 「已经交付打包，退出重进看不到前面打的包」：记录早就落库了
              // （deliveries 表），只是一直没人读。现在把本项目最近几个包
              // 列出来，退出重进、杀进程重开都还在，且能直接重新分享。
              _HistoryCard(
                projectId: widget.projectId,
                currentDeliveryId: _lastResult?.deliveryId,
                onShare: _shareHistoryItem,
              ),
      ],
    );
  }

  // ─────────────────────────────────────────────────────────

  ExportOptions _copyOptions({
    bool? includeRaw,
    bool? includeManifest,
    bool? includeUnused,
    bool? groupByCarton,
    bool? compressPhotos,
    bool? splitVolumes,
  }) =>
      ExportOptions(
        includeRaw: includeRaw ?? _options.includeRaw,
        includeManifest: includeManifest ?? _options.includeManifest,
        includeUnused: includeUnused ?? _options.includeUnused,
        groupByCarton: groupByCarton ?? _options.groupByCarton,
        compressPhotos: compressPhotos ?? _options.compressPhotos,
        splitVolumes: splitVolumes ?? _options.splitVolumes,
      );

  Future<void> _startPack() async {
    // 老板 2026-09-27 拍板：交付时去掉原来的检查，直接按分组打包。
    // 所以这里不再有任何前置校验与确认框 —— 点了就出包。
    _cancelledFlag = false;
    setState(() {
      _packing = const _PackProgress(ratio: 0, stage: '准备中');
      _lastResult = null;
      // 上一次各卷的「已发送」标记跟旧包一起作废。
      _sentVolumes.clear();
    });

    try {
      final result = await ref.read(exportServiceProvider).build(
            projectId: widget.projectId,
            options: _options,
            onProgress: (ratio, stage) {
              if (!mounted) return;
              setState(
                () => _packing = _PackProgress(ratio: ratio, stage: stage),
              );
            },
            // ⚠️ 读的是 state 字段，不是局部变量 —— 取消按钮在
            //    build 里改的就是这个字段。用局部变量会让取消失效。
            isCancelled: () => _cancelledFlag,
          );
      if (!mounted) return;
      setState(() {
        _packing = null;
        _lastResult = result;
      });
      // 新包已落库 —— 刷新「历史交付包」，否则列表里还是打之前那几个
      // （v0.24.8：交付记录要退出重进也看得到）。
      ref.invalidate(deliveryHistoryProvider(widget.projectId));
    } on ExportCancelled {
      if (!mounted) return;
      setState(() => _packing = null);
      _toast('已取消');
    } catch (e) {
      if (!mounted) return;
      setState(() => _packing = null);
      _showError('$e');
    }
  }

  void _cancelPack() {
    // 只置标志，不 kill：文件写入必须走完当前一张，
    // 否则可能留下半张图（下一次 tick 时打包循环自己抛 ExportCancelled）。
    _cancelledFlag = true;
    setState(() {
      _packing = _packing?.copyWith(cancelling: true);
    });
  }

  bool _cancelledFlag = false;

  @override
  void initState() {
    super.initState();
    _cancelledFlag = false;
    // share_plus 10.x 的 API 是静态 `Share.shareXFiles`。
    // （11.x 改成了 `SharePlus.instance.share(ShareParams(...))`，
    //  本工程钉在 pubspec 的 `^10.0.2`，别按 11 的写法改。）
    _sharer = DeliverySharer((paths, {required subject, required text}) async {
      await Share.shareXFiles(
        [for (final path in paths) XFile(path)],
        subject: subject,
        text: text,
      );
    });
  }

  // ═══════════════════════════════════════════════════════════
  // 分享
  // ═══════════════════════════════════════════════════════════

  /// 已经发出去的卷（路径集合）。只用于界面上的「已发送」标记，
  /// 不作 truth —— Android 的分享结果本来就不可靠（share_plus 文档明说
  /// "not guaranteed that the user actually shared something"）。
  final _sentVolumes = <String>{};

  /// 分享策略收口在 [DeliverySharer] —— 那里管"一次传几个文件"，
  /// 这是微信能不能出现在面板里的决定性因素。
  late final DeliverySharer _sharer;

  /// 逐卷发送完整一次性分享：
  ///   1 个文件  → ACTION_SEND        （微信在面板里）
  ///   ≥2 个文件 → ACTION_SEND_MULTIPLE（微信**不在**，故不可用于常规交付）
  /// 想看这条平台差异的依据，见 share_plus-10.1.4 的 `Share.kt`。
  Future<void> _shareVolume(DeliveryVolume v) async {
    final result = _lastResult;
    if (result == null) return;
    try {
      await _sharer.shareVolume(result, v);
      if (!mounted) return;
      setState(() => _sentVolumes.add(v.path));
    } catch (e) {
      if (!mounted) return;
      _showError('分享失败：$e');
    }
  }

  /// 一次发送全部卷（ACTION_SEND_MULTIPLE —— **不含微信**）。
  Future<void> _shareAllVolumes() async {
    final result = _lastResult;
    if (result == null) return;
    try {
      await _sharer.shareAll(result);
    } catch (e) {
      if (!mounted) return;
      _showError('分享失败：$e');
    }
  }

  /// 分享一条**历史**交付包（2026-10-20 v0.24.8）。
  ///
  /// 退出重进后 `_lastResult` 是空的，但文件还在、交付记录还在库里 ——
  /// 这里用记录重建 [DeliveryResult] 再走同一套分享策略：
  ///  · 单卷 → 直接发（ACTION_SEND，微信在面板里）；
  ///  · 多卷 → 弹菜单让用户挑卷（微信只收单文件，现场就是逐卷发）。
  Future<void> _shareHistoryItem(DeliveryHistoryItem item) async {
    if (item.volumePaths.isEmpty) {
      _showError('这个包的文件已不在手机上（可能被清理了）。重新打一次即可。');
      return;
    }
    final result = DeliveryResult(
      deliveryId: item.id,
      zipPath: item.volumePaths.first,
      folderPath: item.folderPath,
      bytes: item.bytes,
      itemCount: item.itemCount,
      photoCount: item.photoCount,
      volumes: [
        for (final path in item.volumePaths)
          DeliveryVolume(path: path, bytes: 0),
      ],
    );

    if (!item.isSplit) {
      try {
        await _sharer.shareVolume(result, result.volumes.first);
        if (!mounted) return;
        setState(() => _sentVolumes.add(item.volumePaths.first));
      } catch (e) {
        if (mounted) _showError('分享失败：$e');
      }
      return;
    }

    final picked = await showModalBottomSheet<int>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const ListTile(
              dense: true,
              title: Text(
                '这个包分成了多卷 —— 微信一次只能收一个文件，请逐卷发送',
                style: TextStyle(fontSize: 12.5),
              ),
            ),
            for (var i = 0; i < result.volumes.length; i++)
              ListTile(
                leading: const Icon(Icons.inventory_2_outlined),
                title: Text(result.volumes[i].fileName),
                trailing: _sentVolumes.contains(item.volumePaths[i])
                    ? const Icon(Icons.check, size: 18, color: AppTheme.green)
                    : null,
                onTap: () => Navigator.of(ctx).pop(i),
              ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.send_and_archive_outlined),
              title: const Text('全部一起发（不含微信）'),
              onTap: () => Navigator.of(ctx).pop(-1),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (picked == null || !mounted) return;
    try {
      if (picked < 0) {
        await _sharer.shareAll(result);
      } else {
        await _sharer.shareVolume(result, result.volumes[picked]);
        if (!mounted) return;
        setState(() => _sentVolumes.add(item.volumePaths[picked]));
      }
    } catch (e) {
      if (mounted) _showError('分享失败：$e');
    }
  }

  void _toast(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), duration: const Duration(seconds: 2)),
    );
  }

  void _showError(String msg) {
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('打包失败'),
        content: Text(msg, style: const TextStyle(height: 1.6)),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('知道了'),
          ),
        ],
      ),
    );
  }
}

/// 打包进度快照。
class _PackProgress {
  const _PackProgress({
    required this.ratio,
    required this.stage,
    this.cancelling = false,
  });

  final double ratio;
  final String stage;
  final bool cancelling;

  _PackProgress copyWith({double? ratio, String? stage, bool? cancelling}) =>
      _PackProgress(
        ratio: ratio ?? this.ratio,
        stage: stage ?? this.stage,
        cancelling: cancelling ?? this.cancelling,
      );
}

/// 打包进行中面板：进度条 + 阶段文字 + 取消。
///
/// 1.5GB 的包可能要几分钟 —— 不能是黑屏等待（§4.3 P9）。
class _PackingPanel extends StatelessWidget {
  const _PackingPanel({required this.progress, required this.onCancel});

  final _PackProgress progress;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const SizedBox(
                  width: 15,
                  height: 15,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    progress.cancelling ? '正在取消…' : progress.stage,
                    style: const TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.navy,
                    ),
                  ),
                ),
                Text(
                  '${(progress.ratio * 100).round()}%',
                  style: const TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.accent,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: progress.ratio,
                minHeight: 7,
                backgroundColor: AppTheme.line,
              ),
            ),
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: progress.cancelling ? null : onCancel,
                child: const Text('取消'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 包内布局说明 —— 让用户知道会得到什么，而不是打包完才惊讶。
class _PackageLayoutCard extends StatelessWidget {
  const _PackageLayoutCard({
    required this.plan,
    required this.groupByCarton,
  });

  final DeliveryPlan plan;

  /// 交付页当前勾选的「按箱号分文件夹」。实际是否分箱由
  /// [DeliveryPlan.hasCartonData]（清单里有没有箱号）共同决定。
  final bool groupByCarton;

  @override
  Widget build(BuildContext context) {
    // 取前两个货品做示例（真实文件名，不是编的）
    final samples = <String>[];
    for (final it in plan.items) {
      for (final ph in it.photos) {
        samples.add(ph.fileName);
        if (samples.length >= 2) break;
      }
      if (samples.length >= 2) break;
    }

    // 预览计划按默认选项（按箱号）构建；这里的「生效」判断与
    // ExportServiceImpl._manifestOf 的 layout 口径完全一致。
    final byCarton = groupByCarton && plan.hasCartonData;

    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: AppTheme.blueBg,
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: AppTheme.blue.withValues(alpha: 0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.folder_outlined, size: 16, color: AppTheme.blue),
              SizedBox(width: 6),
              Text(
                '交付包里是什么',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.blue,
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          Text(
            samples.isEmpty
                ? (byCarton
                    ? '照片先分「预检 / 监装」，预检再按你指定的箱号分文件夹。'
                    : '照片分「预检 / 监装」两个文件夹，预检内部平铺。')
                : byCarton
                    ? '预检按你指定的箱号分文件夹（没指定的进 _未分箱），例如：\n'
                        '${samples.map((s) => '   $s').join('\n')}'
                    : '预检平铺在一个文件夹里，例如：\n'
                        '${samples.map((s) => '   $s').join('\n')}',
            style: const TextStyle(
              fontSize: 11.5,
              color: AppTheme.navy,
              height: 1.7,
              fontFamily: 'monospace',
            ),
          ),
          const SizedBox(height: 9),
          Text(
            '监装/          — ${plan.supervisionPhotos.length} 张，'
            '与清单无关，用原始文件名\n'
            'manifest.json — 机器可读的交付清单',
            style: const TextStyle(
              fontSize: 11.5,
              color: AppTheme.navy,
              height: 1.7,
            ),
          ),
        ],
      ),
    );
  }
}

/// 历史交付包（2026-10-20 v0.24.8）。
///
/// 数据来自 `deliveries` 表 —— 打包那一刻就落库了，只是一直没人读。
/// 所以**退出重进、杀进程重开都还在**（老板 10-20：「看不到前面打的包」）。
/// 行内显示时间 / 张数 / 体积 / 是否压缩过；文件还在就能直接重新分享。
class _HistoryCard extends ConsumerWidget {
  const _HistoryCard({
    required this.projectId,
    required this.currentDeliveryId,
    required this.onShare,
  });

  final String projectId;

  /// 本次运行里刚打的包 —— 打上「刚打的」标记，避免和上面的完成卡片混。
  final String? currentDeliveryId;

  final ValueChanged<DeliveryHistoryItem> onShare;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(deliveryHistoryProvider(projectId)).valueOrNull;
    if (items == null || items.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 8, 6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Text(
                    '历史交付包',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.navy,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    '最近 ${items.length} 次',
                    style: const TextStyle(
                        fontSize: 12, color: AppTheme.textMuted),
                  ),
                ],
              ),
              const SizedBox(height: 2),
              for (final it in items)
                _HistoryRow(
                  item: it,
                  isCurrent: it.id == currentDeliveryId,
                  onShare: () => onShare(it),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _HistoryRow extends StatelessWidget {
  const _HistoryRow({
    required this.item,
    required this.isCurrent,
    required this.onShare,
  });

  final DeliveryHistoryItem item;
  final bool isCurrent;
  final VoidCallback onShare;

  @override
  Widget build(BuildContext context) {
    final t = item.createdAt;
    final time = '${t.month.toString().padLeft(2, '0')}-'
        '${t.day.toString().padLeft(2, '0')} '
        '${t.hour.toString().padLeft(2, '0')}:'
        '${t.minute.toString().padLeft(2, '0')}';
    final size = item.bytes >= 1024 * 1024
        ? '${(item.bytes / (1024 * 1024)).toStringAsFixed(1)} MB'
        : '${(item.bytes / 1024).toStringAsFixed(0)} KB';
    final parts = <String>[
      time,
      '${item.photoCount} 张',
      size,
      if (item.isSplit) '${item.volumePaths.length} 卷',
      if (item.compressed) '压缩过',
      if (item.missing) '文件已清理',
    ];
    return Row(
      children: [
        Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(
              children: [
                Flexible(
                  child: Text(
                    parts.join(' · '),
                    style: TextStyle(
                      fontSize: 12.5,
                      color:
                          item.missing ? AppTheme.textMuted : AppTheme.navy,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                if (isCurrent) ...[
                  const SizedBox(width: 6),
                  const Text(
                    '刚打的',
                    style: TextStyle(fontSize: 11, color: AppTheme.green),
                  ),
                ],
              ],
            ),
          ),
        ),
        if (item.missing)
          const Padding(
            padding: EdgeInsets.only(right: 14),
            child: Icon(Icons.link_off, size: 18, color: AppTheme.textMuted),
          )
        else
          IconButton(
            tooltip: '重新分享',
            visualDensity: VisualDensity.compact,
            icon: const Icon(Icons.share_outlined, size: 19),
            onPressed: onShare,
          ),
      ],
    );
  }
}

/// 打包完成卡片。
class _DoneCard extends StatelessWidget {
  const _DoneCard({
    required this.result,
    required this.sentVolumes,
    required this.onShareVolume,
    required this.onShareAll,
  });

  final DeliveryResult result;

  /// 已发过的卷（路径）。见 _DeliverTabState 里的同名集合。
  final Set<String> sentVolumes;

  /// 逐卷发送（单文件 ACTION_SEND —— 微信会出现在系统面板里）。
  final Future<void> Function(DeliveryVolume volume) onShareVolume;

  /// 一次发送全部（ACTION_SEND_MULTIPLE —— **不含微信**）。
  final VoidCallback onShareAll;

  @override
  Widget build(BuildContext context) {
    final mb = result.bytes / (1024 * 1024);
    final volumes = result.volumes;

    return Card(
      color: AppTheme.greenBg,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(Icons.check_circle, size: 19, color: AppTheme.green),
                SizedBox(width: 7),
                Text(
                  '交付包已生成',
                  style: TextStyle(
                    fontSize: 14.5,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.green,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 9),
            Text(
              '${result.itemCount} 件货品 · ${result.photoCount} 张照片 · '
              '${mb.toStringAsFixed(1)} MB'
              '${result.isSplit ? ' · 分 ${volumes.length} 卷' : ''}',
              style: const TextStyle(
                fontSize: 12.5,
                color: AppTheme.green,
                height: 1.6,
              ),
            ),
            const SizedBox(height: 13),

            // ── 单卷：一个按钮搞定，与以前完全一致 ──
            if (!result.isSplit)
              SizedBox(
                width: double.infinity,
                height: 46,
                child: FilledButton.icon(
                  onPressed: () => onShareVolume(
                    volumes.isEmpty
                        // 兼容旧记录（v0.11 只存单个 zip 路径）
                        ? DeliveryVolume(path: result.zipPath, bytes: result.bytes)
                        : volumes.first,
                  ),
                  style: FilledButton.styleFrom(
                    backgroundColor: AppTheme.green,
                  ),
                  icon: const Icon(Icons.ios_share, size: 18),
                  label: const Text('发送交付包'),
                ),
              )
            else ...[
              // ── 多卷 ──
              // 这句话必须说清楚，否则用户会以为 App 坏了：
              // "为什么分了卷反而发不出去"。
              Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
                decoration: BoxDecoration(
                  color: AppTheme.card,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AppTheme.line),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.info_outline, size: 15, color: AppTheme.textMuted),
                    SizedBox(width: 7),
                    Expanded(
                      child: Text(
                        '微信一次只收一个文件，请逐卷发送。'
                        '每一卷都能独立解压。',
                        style: TextStyle(
                            fontSize: 11.5, color: AppTheme.textMain, height: 1.5),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              for (var i = 0; i < volumes.length; i++)
                _VolumeRow(
                  index: i + 1,
                  total: volumes.length,
                  volume: volumes[i],
                  sent: sentVolumes.contains(volumes[i].path),
                  onShare: () => onShareVolume(volumes[i]),
                ),
              const SizedBox(height: 4),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: onShareAll,
                  icon: const Icon(Icons.drive_folder_upload_outlined, size: 17),
                  label: const Text('一次发送全部（走网盘 / 邮件，不含微信）',
                      style: TextStyle(fontSize: 12)),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 一卷一行：文件名、体积、发送按钮。
///
/// 发过的显示「已发送」而不是继续"原样" —— 十几卷的交付包发出去发了一半，
/// 中间接个电话回来就忘了发到第几卷，是最真实的事故现场。
class _VolumeRow extends StatelessWidget {
  const _VolumeRow({
    required this.index,
    required this.total,
    required this.volume,
    required this.sent,
    required this.onShare,
  });

  final int index;
  final int total;
  final DeliveryVolume volume;
  final bool sent;
  final VoidCallback onShare;

  @override
  Widget build(BuildContext context) {
    final mb = volume.bytes / (1024 * 1024);

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Icon(
            sent ? Icons.check_circle : Icons.description_outlined,
            size: 17,
            color: sent ? AppTheme.green : AppTheme.textMuted,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  volume.fileName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: sent ? AppTheme.textMuted : AppTheme.navy,
                  ),
                ),
                Text(
                  '第 $index / $total 卷 · ${mb.toStringAsFixed(1)} MB',
                  style: const TextStyle(
                      fontSize: 11, color: AppTheme.textMuted),
                ),
              ],
            ),
          ),
          SizedBox(
            height: 34,
            child: sent
                ? OutlinedButton.icon(
                    onPressed: onShare,
                    icon: const Icon(Icons.replay, size: 15),
                    label: const Text('已发送',
                        style: TextStyle(fontSize: 12)),
                  )
                : FilledButton.icon(
                    onPressed: onShare,
                    style: FilledButton.styleFrom(
                      backgroundColor: AppTheme.green,
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                    ),
                    icon: const Icon(Icons.ios_share, size: 15),
                    label: const Text('发送', style: TextStyle(fontSize: 12)),
                  ),
          ),
        ],
      ),
    );
  }
}

/// 明细里的一行「标签 —— 值」。
///
/// 【2026-10-01】`alert` 参数曾用于「清单缺口」那一行（有缺口时数值转琥珀色）。
/// 缺口随指派一起下线后没有任何调用方用得上，留着就是拿不到的假能力 ——
/// 删掉。真要强调某一行时再加回来。
class _Line extends StatelessWidget {
  const _Line(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Expanded(
            child: Text(label,
                style: const TextStyle(
                    fontSize: 13, color: AppTheme.textMuted)),
          ),
          Text(
            value,
            style: const TextStyle(
              fontSize: 13.5,
              fontWeight: FontWeight.w700,
              color: AppTheme.textMain,
            ),
          ),
        ],
      ),
    );
  }
}

/// 打包选项的一行开关。
///
/// 用 SwitchListTile 而不是 Checkbox：现场是戴手套操作，
/// 开关的触控面积更大、状态更显眼（§4.2 的触控纪律）。
class _OptionSwitch extends StatelessWidget {
  const _OptionSwitch({
    required this.title,
    required this.value,
    required this.enabled,
    required this.onChanged,
    this.subtitle,
    this.hint,
    this.indent = false,
  });

  final String title;

  /// 副标题。2026-10-01 起六项全部改为 null —— 它现在是**罕见产物**，
  /// 真正该常态显示的是标题本身（见 [hint]）。
  final String? subtitle;

  /// 按住标题旁的 ⓘ 才看得到的完整解释。
  ///
  /// 交付页被"说明太多占太多空间"点名审查，根因就是这六项各自带了
  /// 两三行副标题。它们是**选完之后**才关心的（`ᐧ自动分卷`到底分多大、
  /// 压缩到什么画质），而人在现场要做的只是「勾上、点生成」。
  /// 挪进 tooltip 后信息一条没丢，但常态下不占一行。
  final String? hint;

  final bool value;
  final bool enabled;
  final ValueChanged<bool> onChanged;

  /// 子选项缩进（如「按箱号分文件夹」挂在「原始照片」下）。
  final bool indent;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(left: indent ? 14 : 0),
      child: SwitchListTile(
        dense: true,
        contentPadding: const EdgeInsets.symmetric(horizontal: 8),
        value: value,
        onChanged: enabled ? onChanged : null,
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Flexible(
              child: Text(
                title,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: indent ? 13 : 13.5,
                  fontWeight: indent ? FontWeight.w500 : FontWeight.w600,
                  color: enabled ? AppTheme.textMain : AppTheme.textMuted,
                ),
              ),
            ),
            if (hint != null) ...[
              const SizedBox(width: 4),
              Tooltip(
                message: hint!,
                triggerMode: TooltipTriggerMode.tap,
                child: const Icon(Icons.info_outline,
                    size: 14, color: AppTheme.textMuted),
              ),
            ],
          ],
        ),
        // ⚠️ 没有 subtitle 时**必须传 null** —— 传 '' 会让 ListTile
        // 照样留出副标题那一行（每份 Timing ~15px × 6 ≈ 90px 纯浪费）。
        subtitle: subtitle == null
            ? null
            : Text(
                subtitle!,
                style: const TextStyle(
                  fontSize: 11.5,
                  color: AppTheme.textMuted,
                  height: 1.5,
                ),
              ),
      ),
    );
  }
}

/// 一行成本低的小计数徽标（比 _Line 更省地方）。
class _MiniChip extends StatelessWidget {
  const _MiniChip({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: AppTheme.bg,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: AppTheme.line),
        ),
        child: Text(
          text,
          style:
              const TextStyle(fontSize: 11, color: AppTheme.textMuted),
        ),
      );
}

// ═══════════════════════════════════════════════════════════════
// 相册镜像面板（P4 · 老板 2026-09-24 诉求「拍照要进手机相册」）
// ═══════════════════════════════════════════════════════════════

/// 「拍照同时存入手机相册」的开关 + 把已有照片补存进去的入口。
///
/// 为什么不放进采集现场：采集页是**取景优先**的全屏相机，任何设置项
/// 放进去都会变成拍完还得找地方关的东西（§4.2 纪律）。它是"出门前
/// 拨一次"的开关，所以 2026-10-01 概览 Tab 下线后收进了 AppBar 的
/// ⋯ 菜单（见 [_openGalleryMirror]），而不是占一屏。
///
/// ⚠️ **只管 App 内拍的照片**（老板 2026-09-29 拍板）：
/// 相册 / 微信导入的照片本来就在手机里，再抄一份进
/// `相册/集刻-采集/<项目>` 就是相册里的重复件。所以这里的张数、
/// 补存范围、入口显隐全部以「相机来源的照片」为准。
class _GalleryCard extends ConsumerStatefulWidget {
  const _GalleryCard({required this.projectId});

  final String projectId;

  @override
  ConsumerState<_GalleryCard> createState() => _GalleryCardState();
}

class _GalleryCardState extends ConsumerState<_GalleryCard> {
  /// null = 还没读到偏好（读到的瞬间才渲染开关，避免闪一下）。
  bool? _enabled;

  /// 补存进行中。补存可能要几十秒（几百张 × 100ms），必须给进度。
  bool _running = false;
  var _done = 0;
  String? _error;

  String? _album;

  /// 本项目 **App 内拍的** 照片数（null = 还没读到）。
  /// 导入的照片不计入 —— 它们本来就在手机相册里，不该再存一份。
  int? _captured;

  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      final gallery = ref.read(galleryServiceProvider);
      final on = await gallery.isEnabled;
      final repo = ref.read(captureRepositoryProvider);
      final name = await repo.projectName(widget.projectId);
      final captured = await repo.capturedPhotoCount(widget.projectId);
      if (!mounted) return;
      setState(() {
        _enabled = on;
        _album = GalleryService.safeFolderName(name);
        _captured = captured;
      });
    });
  }

  Future<void> _toggle(bool v) async {
    setState(() => _enabled = v);
    await ref.read(galleryServiceProvider).setEnabled(v);
  }

  /// 把项目里**已有**的照片补存进相册。
  ///
  /// 逐张调 save（而不是 saveAll 一次打包）的唯一理由：几百张的补存
  /// 要几十秒，不给"存到第几张"的进度，现场会以为卡死了。
  /// 去重在原生写入点做：已存过的照片原生直接跳过（skipped），
  /// 反复点补存**不会**在相册里重复保存 —— 跳过不算失败。
  Future<void> _exportAll() async {
    if (_running) return;
    final messenger = ScaffoldMessenger.of(context);
    setState(() {
      _running = true;
      _done = 0;
      _error = null;
    });

    var saved = 0;
    var skipped = 0;
    var failed = 0;
    String? reason;
    try {
      final repo = ref.read(captureRepositoryProvider);
      final gallery = ref.read(galleryServiceProvider);
      final album =
          GalleryService.safeFolderName(await repo.projectName(widget.projectId));
      final photos = await repo.capturedPhotos(widget.projectId);

      for (final ph in photos) {
        final r = await gallery.save(
          srcPath: ph.srcPath,
          displayName: ph.displayName,
          album: album,
          takenAt: ph.takenAt,
        );
        if (r.saved == 1) {
          saved++;
        } else if (r.skipped == 1) {
          skipped++;
        } else {
          failed++;
          reason = gallery.lastError;
        }
        if (!mounted) return;
        setState(() => _done = saved + skipped + failed);
      }
    } catch (e) {
      failed++;
      reason = '$e';
    }

    if (!mounted) return;
    setState(() {
      _running = false;
      if (failed > 0) _error = reason;
    });

    messenger.showSnackBar(
      SnackBar(
        content: Text(
          failed > 0
              ? '新存入 $saved 张，跳过 $skipped 张，失败 $failed 张'
                  '${reason == null ? '' : ' —— $reason'}'
              : saved > 0 && skipped > 0
                  ? '新存入 $saved 张，$skipped 张已在相册里，自动跳过'
                  : saved > 0
                      ? '已把 $saved 张照片存入相册'
                      : skipped > 0
                          ? '$skipped 张都已在相册里，未重复保存'
                          : '没有需要存入的照片',
        ),
        duration: const Duration(seconds: 4),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final enabled = _enabled;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.photo_library_outlined,
                    size: 17, color: AppTheme.accent),
                const SizedBox(width: 9),
                const Expanded(
                  child: Text(
                    '手机相册',
                    style: TextStyle(
                      fontSize: 14.5,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.navy,
                    ),
                  ),
                ),
                if (enabled != null)
                  Switch(value: enabled, onChanged: _toggle),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              _album == null
                  ? '拍照后自动在系统相册里留一份备份，微信里直接就能发。'
                      '从相册或微信导入的照片不再重复存入 —— 它们本来就在手机里。'
                  : '拍照后自动存一份到 ${GalleryService.displayPath(_album!)}，'
                      '微信里直接就能发。App 里的原件不受影响。'
                      '导入的照片不重复存（本来就在手机里）；已存过的补存时自动跳过。',
              style: const TextStyle(
                fontSize: 12,
                color: AppTheme.textMuted,
                height: 1.55,
              ),
            ),
            if (_running) ...[
              const SizedBox(height: 10),
              LinearProgressIndicator(
                value: (_captured ?? 0) > 0
                    ? (_done / (_captured ?? 1)).clamp(0.0, 1.0)
                    : null,
                minHeight: 3,
              ),
              const SizedBox(height: 6),
              Text(
                '存入中 $_done 张…',
                style: const TextStyle(
                    fontSize: 11.5, color: AppTheme.textMuted),
              ),
            ] else if (enabled == true && _captured != null) ...[
              if (_captured! > 0) ...[
                const SizedBox(height: 4),
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: _exportAll,
                    child: Text('把 $_captured 张 App 内拍的照片补存到相册'),
                  ),
                ),
              ] else ...[
                const SizedBox(height: 4),
                const Text(
                  '还没有 App 内拍的照片 —— 导入的照片本来就在手机里，'
                  '不会重复存入相册。',
                  style: TextStyle(
                      fontSize: 11.5, color: AppTheme.textMuted, height: 1.5),
                ),
              ],
            ],
            if (_error != null) ...[
              const SizedBox(height: 4),
              Text(
                '上次有照片没存成功：$_error',
                style: const TextStyle(
                    fontSize: 11.5, color: AppTheme.amber, height: 1.5),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
