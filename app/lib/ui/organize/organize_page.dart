import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../app/router.dart';
import '../../app/theme.dart';
import '../../domain/model/enums.dart';
import '../../domain/model/open_group.dart';
import '../../domain/model/project_summary.dart';
import '../../domain/suggest/suggest_service.dart';
import '../capture/import_actions.dart';
import '../capture/system_camera_actions.dart';
import '../widgets/stage_progress.dart';
import 'duplicate_sheet.dart';
import 'photo_viewer_page.dart';

/// P3 · **照片**页（工作台底部导航第一项，2026-10-01 改名 + 合并采集）。
///
/// ═══════════════════════════════════════════════════════════════
/// 这一页只管一件事：**把照片按「部类 → 箱号 → 组」摆好，然后交出去。**
/// ═══════════════════════════════════════════════════════════════
/// 2026-10-01 之前：拍照在「采集」Tab、对货品在「整理」Tab。问题是
/// 「采集」Tab 里**只有一个**进相机的按钮 —— 为一个按钮占一条底部导航位
/// 是纯浪费。现在合成一页，顶部常驻「拍照入库 / 相册导入」。
///
/// 相机本身**保留为独立全屏路由**（见 [_openCamera]）：取景必须占满整屏，
/// 内嵌到列表上方只剩半屏，且相机生命周期会和列表刷新互相牵扯。
///
/// 【指派已下线 · 2026-10-01】老板拍板「指派货品没用」，UI 层整条链路
/// 一并拆除：卡片上的「指派货品」按钮、指派面板、「已指派」页签、
/// 「一键确认」入口、「清单缺口」面板。
/// 照片从此**不与货品关联** —— 组织维度只剩「部类 / 箱号 / 组」。
/// AssignService 与 assignments、items 表**刻意保留**：
///   ① 已交付过的项目留痕不能抹；② 日后要接回来不必重建 schema。
///
/// 顶部高度是硬约束（老板 2026-10-01：「选项卡太多，分组空间不足」）：
/// 常态只占「部类 Tab + 拍照条 + 一行状态」三段 ≈ 110px，
/// 覆盖率 / 缺口那些装饰条全部撤掉。
class OrganizePage extends ConsumerStatefulWidget {
  const OrganizePage({
    super.key,
    required this.projectId,
    required this.summary,
  });

  final String projectId;
  final ProjectSummary summary;

  @override
  ConsumerState<OrganizePage> createState() => _OrganizePageState();
}

class _OrganizePageState extends ConsumerState<OrganizePage> {
  bool _mergeMode = false;
  final _picked = <String>{};

  /// 组列表排序（2026-10-08 真机诉求「按箱号排序」）。
  /// false = 按拍摄时间（默认，现场走动顺序）；true = 按箱号（数字感知）。
  bool _sortByCarton = false;

  /// 当前部类：0 = 预检（默认），1 = 监装（老板 2026-09-27 拍板）。
  ///
  /// 部类回答"这批照片是什么"：预检是货品，监装是装柜过程。
  /// 监装不与清单对应，也不分箱 —— 它就是一张照片墙。
  ///
  /// 【曾是两层】这里原先还有一个「待处理 / 已指派」页签开关，
  /// 2026-10-01 随指派下线一起删掉：照片不再"指派完成就从列表消失"，
  /// 列表就是全部组，一眼看到底。
  int _sectionIndex = 0;

  /// OCR 识别进度订阅（v0.24.2 接线）。
  ///
  /// SuggestPipeline 自 M4 起就写好了（识别 → token 落库 → 组级合成），
  /// 但**进页触发一直没接上** —— 全仓没有任何调用点，`ocr_state` 永远
  /// 停在 pending、`ocr_tokens` 永远为空，按编码搜照片自然一个都搜不到
  /// （2026-10-15 真机反馈）。这里把设计文档 §5.3.3 的既定口径补上：
  /// 「进页跑一轮」，采集期零智能，识别只发生在整理阶段。
  StreamSubscription<SuggestProgress>? _ocrSub;

  /// 正在跑的那轮的进度；null = 当前没在识别。
  SuggestProgress? _ocrProgress;

  @override
  void initState() {
    super.initState();
    // P4 · 诉求 3：分组补跑已经移到 `openGroupsProvider` 里（数据驱动）——
    // 这里不再手动调 regroupPending。原因见该 provider 的注释：
    // 「进页跑一次」在 IndexedStack 下只会执行一次，之后新拍的照片
    // 永远不会被分组，导致整理页看起来是空的。

    // 缩略图补齐（2026-09-29「整理页缩略图显示不出来」）：
    // 缩略图是**入库之后**才异步生成的（不阻塞快门、不阻塞导入）。用户导入
    // 完马上进本页时，列表读到的 thumbPath 还是 null，而列表**不会自己刷新**
    // —— 看上去就是一整片空白。进页先补一轮，补完 invalidate 让列表重读。
    // 历史项目里因为失败 / 中断而缺缩略图的照片也一并救回（photosMissingThumb
    // 只挑 thumbPath IS NULL 的那些）。
    Future.microtask(() async {
      try {
        final n = await ref
            .read(captureServiceProvider)
            .backfillThumbnails(widget.projectId);
        if (n <= 0 || !mounted) return;
        ref.invalidate(openGroupsProvider(widget.projectId));
        ref.invalidate(assignedGroupsProvider(widget.projectId));
        ref.invalidate(supervisionPhotosProvider(widget.projectId));
      } catch (_) {/* 缩略图只影响观感，绝不挡路 */}
    });

    // OCR 识别（v0.24.2 接线，见 [_ocrSub] 注释）：
    // 进度先订阅再触发，顺序反了会漏掉前几张的进度。
    _ocrSub = ref.read(suggestPipelineProvider).progressStream.listen((p) {
      if (!mounted) return;
      setState(() => _ocrProgress = p.finished ? null : p);
    });
    Future.microtask(() async {
      try {
        await ref
            .read(suggestPipelineProvider)
            .ensurePendingProcessed(widget.projectId);
      } catch (_) {/* 识别是增强能力：失败绝不挡照片列表 */}
    });
  }

  @override
  void dispose() {
    _ocrSub?.cancel();
    super.dispose();
  }

  /// 下拉刷新（P4 · 诉求 3 的手动兜底）。
  ///
  /// 先补一轮分组（把刚拍还没入组的照片聚起来），再让待办流重新读一次。
  /// `regroupPending` 有重入锁，与自动路径并发也不会重复建组。
  Future<void> _manualRefresh() async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final n = await ref
          .read(organizeRepositoryProvider)
          .regroupPending(widget.projectId);
      // provider 是 family 流的，补组写库后 watchOpenGroups 会自动推新值；
      // 但 invalidate 一次能确保「下拉」这个动作有确定的反馈。
      ref.invalidate(openGroupsProvider(widget.projectId));
      // OCR 补跑（v0.24.2）：下拉 = 人主动要「最新」。进页那一轮之后
      // 新拍的照片可能还没识别，这里一并排上。**不 await** ——
      // 几百张要跑几分钟，进度走 [_OcrStrip]，别把刷新手势挂住；
      // 管道内部有防并发 + 排队，撞上正在跑的一轮会自动续跑。
      unawaited(ref
          .read(suggestPipelineProvider)
          .ensurePendingProcessed(widget.projectId));
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            n > 0 ? '已整理出 $n 组新照片' : '已是最新 —— 没有待整理的照片',
          ),
          duration: const Duration(seconds: 2),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(content: Text('刷新失败：$e')));
    }
  }

  void _enterMergeMode() => setState(() => _mergeMode = true);
  void _exitMergeMode() => setState(() {
        _mergeMode = false;
        _picked.clear();
      });

  void _togglePick(String groupId) {
    setState(() {
      if (_picked.contains(groupId)) {
        _picked.remove(groupId);
      } else {
        _picked.add(groupId);
      }
    });
  }

  /// 把一张照片移出组（长按缩略图）。它会落进新的独立组，仍在待办流里。
  Future<void> _moveOut(String photoId) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref
          .read(organizeRepositoryProvider)
          .movePhotoOut(widget.projectId, photoId);
      messenger.showSnackBar(
        const SnackBar(content: Text('已移出 —— 它现在自成一组')),
      );
    } on StateError {
      messenger.showSnackBar(
        const SnackBar(content: Text('这张刚被确认过，稍后再试')),
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('移出失败：$e')));
    }
  }

  /// 合并所选：先选中的是目标组，其余并进去。
  Future<void> _merge() async {
    if (_picked.length < 2) return;
    final messenger = ScaffoldMessenger.of(context);
    final ids = _picked.toList();
    try {
      await ref.read(organizeRepositoryProvider).mergeGroups(
            widget.projectId,
            targetGroupId: ids.first,
            otherGroupIds: ids.sublist(1),
          );
      setState(_exitMergeMode);
      messenger.showSnackBar(
        SnackBar(content: Text('已合并 ${ids.length} 组')),
      );
    } on StateError {
      messenger.showSnackBar(
        const SnackBar(content: Text('其中一组刚被确认过，稍后再试')),
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('合并失败：$e')));
    }
  }

  /// 打开全屏查看（P4 诉求 2）。
  ///
  /// ⚠️ 全屏页是**唯一**允许解码原图的地方（见 `GroupPhotoThumb.originalPath`）。
  Future<void> _openViewer(OpenGroup g, int index) async {
    if (g.photos.isEmpty) return;
    await Navigator.of(context).push<int>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => PhotoViewerPage(
              projectId: widget.projectId,
              group: g,
              initialIndex: index,
            ),
      ),
    );
  }

  /// 删除一张照片（组内逐张删 / 监装墙逐张删共用入口，M7）。
  ///
  /// 走 [photoDeletionServiceProvider] —— 事务内连带清理 OCR token /
  /// 一照多货附加关联 / 照片级归属记录，并维护所在组的封面与计数
  /// （删空则连组一起删）；磁盘文件尽力而为删。不碰 itemId。
  Future<void> _deletePhoto(String photoId) async {
    final messenger = ScaffoldMessenger.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除这张照片？'),
        content: const Text(
          '照片与它的缩略图、OCR 缓存会从本项目中删除。\n'
          '若它是所在组的最后一张，该组也会被移除。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppTheme.red),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    try {
      await ref.read(photoDeletionServiceProvider).deletePhoto(photoId);
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(content: Text('删除失败：$e')));
      return;
    }
    if (!mounted) return;
    // 三条流都靠 drift watch 自动刷新，这里显式 invalidate 一次确保即时
    ref.invalidate(openGroupsProvider(widget.projectId));
    ref.invalidate(assignedGroupsProvider(widget.projectId));
    ref.invalidate(supervisionPhotosProvider(widget.projectId));
    messenger.showSnackBar(const SnackBar(content: Text('已删除照片')));
  }

  /// 删除整组（含组内全部照片、从属数据、磁盘文件、组级归属记录，M7）。
  Future<void> _deleteGroup(String groupId, int seq) async {
    final messenger = ScaffoldMessenger.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除整组？'),
        content: Text('第 $seq 组及其全部照片会一并删除，且不可恢复。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppTheme.red),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('删除整组'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    try {
      await ref.read(photoDeletionServiceProvider).deleteGroup(groupId);
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(content: Text('删除失败：$e')));
      return;
    }
    if (!mounted) return;
    ref.invalidate(openGroupsProvider(widget.projectId));
    ref.invalidate(assignedGroupsProvider(widget.projectId));
    ref.invalidate(supervisionPhotosProvider(widget.projectId));
    messenger.showSnackBar(SnackBar(content: Text('已删除第 $seq 组')));
  }

  // ── 组内添加照片（2026-09-30）──────────────────────────────

  /// 给一个**待处理**组补照片：从相册选，或现场补拍。
  ///
  /// 两条路殊途同归：照片先照常入库（source=album 批次 / 相机批次），
  /// 由 [OrganizeRepository.attachPhotosToGroup] 挂进目标组 ——
  /// 挂组是移动语义，即便自动分组抢先收走了照片也能搬回来。
  /// 打开相机拍照入库（2026-10-01：采集 Tab 下线后的入口）。
  ///
  /// v0.22.2（老板反馈"经由内置相机到系统相机，整个路径是错误的"）：
  /// **系统相机模式下不再路由进 App 内相机页** —— 点这里直接拉起系统
  /// 相机，拍完 ingest 完人在照片页。v0.24.2 起为连拍会话：相机普通
  /// 模式想拍多少拍多少，按返回一次性收图入库（详见 system_camera_
  /// actions.dart）。全屏采集页只剩内置相机模式（设置回退）在用。
  ///
  /// 组内补拍走另一条链路（[_addPhotosToGroup]，路由带 `?group=`），
  /// 那条同样分流；这里是"往项目里加照片"的通用入口。
  Future<void> _openCamera() async {
    final projectId = widget.projectId;
    // v0.24.11：系统相机收图 + ingest 那几秒原来**干等**，照片页毫无
    // 反馈（老板：「等很久，以为拍照失败了」）。带进度卡的入口把这段
    // 补齐 —— 卡片随 ingest 张数走，撤卡后晚到照片用 SnackBar 补。
    final (outcome, shotIds, shotCount) = await runSystemCameraWithProgress(
      context: context,
      ref: ref,
      projectId: projectId,
    );
    if (outcome == null) {
      // 内置相机模式 → 全屏采集页（相机生命周期重，保持独立路由）。
      if (!mounted) return;
      await context.push(
        '${AppRoutes.project}/$projectId/${AppRoutes.capture}',
      );
    } else if (outcome != SystemShotOutcome.cancelled && mounted) {
      _showShotOutcome(outcome, count: shotIds.length, shotCount: shotCount);
    }
    if (!mounted) return;
    // 拍完回来：照片入库时分好组，流推送本身会更新；这里再 invalidate
    // 一次，是为了让"回来就能看见"这件事有确定反馈，而不是等下一次推送。
    ref.invalidate(openGroupsProvider(projectId));
    ref.invalidate(supervisionPhotosProvider(projectId));
    ref.invalidate(projectSummaryProvider(projectId));
  }

  /// 系统直拍的结局提示（照片页无 HUD，用 SnackBar；cancelled 静默不提示
  /// —— 用户反悔不是错误）。文案说清"拍了没有、没拍上怎么办"。
  /// v0.24.2 连拍会话：一次能收多张，count > 1 时文案带张数。
  /// v0.24.5：[shotCount] 是原生媒体库拿到的张数；它大于实际入库张数
  /// 说明有照片留在系统相册里没进 App，必须明说并指下一步（现场等于
  /// 白拍，用户不知道就等于没拍）。
  void _showShotOutcome(
    SystemShotOutcome outcome, {
    int count = 0,
    int shotCount = 0,
  }) {
    final partial = shotCount > count;
    final msg = switch (outcome) {
      SystemShotOutcome.shot when partial =>
        '相机 ${shotCount > 0 ? shotCount : count} 张 · 只存下 $count 张'
            ' · 缺的可在照片库用「从相册导入」补收',
      SystemShotOutcome.shot =>
        count > 1 ? '已收下 $count 张照片' : '已拍照入库',
      SystemShotOutcome.missed =>
        '没收到照片 · 相机里拍的照片仍在系统相册，可从「从相册导入」补收',
      SystemShotOutcome.noImage =>
        '系统相机没有返回原图，这张没收下 · 可再拍一次，'
            '或在相机设置里改用内置相机',
      _ => '拍照没成功 · 请再试一次',
    };
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        duration: outcome == SystemShotOutcome.shot && !partial
            ? const Duration(milliseconds: 900)
            : const Duration(seconds: 5),
      ),
    );
  }

  Future<void> _addPhotosToGroup(OpenGroup g) async {
    final projectId = widget.projectId;
    final label = '第 ${g.seq} 组';
    // ⚠️ 补拍全程锁住目标组（2026-10-08 真机事故修复）：单张组在补拍
    // 期间会被 regroup 当"未指派单张组"回收掉，拍完回来 attach 就炸
    // 「目标组不存在」，新照片被孤在自动建的小组里。进流程先上保护，
    // 挂组结束（无论成败）再解除。
    final repo = ref.read(organizeRepositoryProvider);
    repo.protectGroupFromRegroup(g.groupId);
    try {
      await _addPhotosToGroupInner(g, projectId, label);
    } finally {
      repo.unprotectGroup(g.groupId);
    }
  }

  Future<void> _addPhotosToGroupInner(
    OpenGroup g,
    String projectId,
    String label,
  ) async {

    final choice = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 6),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: Text('从相册选择 → 加入$label'),
              subtitle: const Text('在手机相册里选中照片补进这组',
                  style: TextStyle(fontSize: 12)),
              onTap: () => Navigator.of(ctx).pop('gallery'),
            ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: Text('相机拍摄 → 加入$label'),
              subtitle: const Text('打开相机补拍，拍完自动加入这组',
                  style: TextStyle(fontSize: 12)),
              onTap: () => Navigator.of(ctx).pop('camera'),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (choice == null || !mounted) return;

    if (choice == 'gallery') {
      await runGalleryImport(
        context,
        ref,
        projectId,
        intoGroupId: g.groupId,
        groupLabel: label,
      );
      return;
    }

    // 相机补拍（v0.22.2 分流；v0.24.2 系统模式升级为连拍会话，可收多张）：
    // 系统相机模式直拍（不进 App 内相机页，拍完回来整批挂组）；
    // 内置相机模式照旧走全屏采集页带回整批。
    final messenger = ScaffoldMessenger.of(context);
    List<String>? shots;
    // v0.24.11：组内补拍同样带进度卡（与 _openCamera 同口径）——
    // 补拍常是多张连拍，收图等待比单张更长，更不能没有反馈。
    final (outcome, shotIds, nativeCount) = await runSystemCameraWithProgress(
      context: context,
      ref: ref,
      projectId: projectId,
      // 2026-10-21：系统相机返回即回 App，首批/晚到都走后台 ingest ——
      // 目标组交给会话状态，收一张挂一张（页面拿不到 ids 了）。
      intoGroupId: g.groupId,
    );
    if (outcome == null) {
      if (!mounted) return;
      shots = await context.push<List<String>>(
        '${AppRoutes.project}/$projectId/${AppRoutes.capture}'
        '?group=${Uri.encodeComponent(g.groupId)}&gseq=${g.seq}',
      );
    } else {
      if (outcome != SystemShotOutcome.cancelled && mounted) {
        _showShotOutcome(outcome, count: shotIds.length, shotCount: nativeCount);
      }
      if (outcome == SystemShotOutcome.shot) shots = shotIds;
    }
    if (shots == null || shots.isEmpty || !mounted) return;

    try {
      await ref
          .read(organizeRepositoryProvider)
          .attachPhotosToGroup(projectId, g.groupId, shots);
      ref.invalidate(openGroupsProvider(projectId));
      messenger.showSnackBar(
        SnackBar(content: Text('已把 ${shots.length} 张照片加入$label')),
      );
    } catch (e) {
      // ⚠️ 提示必须说清「照片没丢」+ 下一步（2026-10-08 真机反馈：
      // 原文案抛了个 Bad state 给老板看，看不出照片去了哪、该干什么）。
      messenger.showSnackBar(SnackBar(
        content: Text(
          '已拍 ${shots.length} 张，但$label在补拍期间被自动整理调整了，'
          '照片没有丢 —— 它们已按拍摄批次自动成组，'
          '如需并回$label，请在照片页长按组卡片拖拽合并。',
        ),
        duration: const Duration(seconds: 5),
      ));
      ref.invalidate(openGroupsProvider(projectId));
    }
  }

  /// 拖拽合并（P4 诉求 2）：把 [draggedGroupId] 并进 [targetGroupId]。
  ///
  /// 与 [_merge] 走同一个仓储方法 —— 拖拽只是换了种**输入方式**，
  /// 落库路径完全一致（同样要过「已确认组不可合并」的校验）。
  ///
  /// 确认弹窗是刻意的：合并会让整组照片换归属对象，误拖一次就要
  /// 重新拆开。给一次"看清楚了再点"的机会，成本远低于返工。
  Future<void> _mergeByDrag({
    required String draggedGroupId,
    required String targetGroupId,
    required List<OpenGroup> allGroups,
  }) async {
    if (draggedGroupId == targetGroupId) return;

    final dragged = allGroups.firstWhere(
      (g) => g.groupId == draggedGroupId,
      orElse: () => allGroups.first,
    );
    final target = allGroups.firstWhere(
      (g) => g.groupId == targetGroupId,
      orElse: () => allGroups.first,
    );
    // 兜底：万一 id 都没匹配上（列表已刷新），直接放弃而不是乱合并
    if (dragged.groupId != draggedGroupId || target.groupId != targetGroupId) {
      return;
    }

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('合并这两组？'),
        content: Text(
          '把「第 ${dragged.seq} 组（${dragged.photoCount} 张）」'
          '并进「第 ${target.seq} 组（${target.photoCount} 张）」。\n\n'
          '合并后是第 ${target.seq} 组，共 '
          '${dragged.photoCount + target.photoCount} 张照片。',
          style: const TextStyle(fontSize: 13.5, height: 1.6),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppTheme.accent),
            child: const Text('合并'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(organizeRepositoryProvider).mergeGroups(
            widget.projectId,
            targetGroupId: target.groupId,
            otherGroupIds: [dragged.groupId],
          );
      messenger.showSnackBar(
        SnackBar(content: Text('已并入第 ${target.seq} 组')),
      );
    } on StateError {
      messenger.showSnackBar(
        const SnackBar(content: Text('其中一组刚被确认过，不能再合并了')),
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('合并失败：$e')));
    }
  }

  // ── 箱号 / 部类（老板 2026-09-27 拍板）────────────────────
  //
  // ⚠️ 这两个动作**都不碰归属**：箱号与部类只决定"交付包里放哪个
  // 文件夹"，与"这组照片属于哪件货"正交。所以它们走 OrganizeRepository
  // 而不是 AssignService —— 不需要决策凭据（那不是事实判断）。

  /// 指定 / 修改 / 清除一组照片的箱号。
  ///
  /// 箱号**由人输入**，不查清单（老板拍板原话：
  /// 「分组时，由用户输入或指定箱号，不依赖货品清单」）。
  /// 清单里的箱号列只作为清单信息保留，不参与分箱。
  Future<void> _setCarton(OpenGroup g) async {
    final result = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(14)),
      ),
      builder: (ctx) => _CartonSheet(
        projectId: widget.projectId,
        current: g.carton,
        photoCount: g.photos.length,
      ),
    );
    // null = 用户取消（面板 pop 时不带值）；'' = 明确要清除箱号
    if (result == null || !mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref
          .read(organizeRepositoryProvider)
          .setGroupCarton(g.groupId, result);
      ref.invalidate(cartonsProvider(widget.projectId));
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(
          content: Text(result.isEmpty ? '已清除箱号' : '已归入「$result」箱'),
          duration: const Duration(seconds: 2),
        ),
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('设置失败：$e')));
    }
  }

  /// 把一组照片标为**监装**（装柜过程，与清单无关）。
  Future<void> _markSupervision(String groupId, int seq) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('标为监装照片？'),
        content: Text(
          '第 $seq 组会被移到「监装」：\n\n'
          '· 不再需要对应货品编码\n'
          '· 不参与箱号分组，交付时全部进「监装」文件夹\n'
          '· 用原始文件名，不再按编码重命名\n\n'
          '标错了可以在监装页改回预检。',
          style: const TextStyle(fontSize: 13.5, height: 1.6),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppTheme.accent),
            child: const Text('标为监装'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref
          .read(organizeRepositoryProvider)
          .setGroupCategory(groupId, PhotoCategory.supervision);
      if (!mounted) return;
      messenger.showSnackBar(
        const SnackBar(
          content: Text('已标为监装 —— 在「监装」页可以看到，'
              '交付时进「监装」文件夹'),
          duration: Duration(seconds: 3),
        ),
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('标记失败：$e')));
    }
  }

  /// 移动整组到另一个项目（2026-10-08 真机诉求④）。
  ///
  /// 两步确认（选目标 + 确认框）：搬走的是**整组照片**，误触一次就要
  /// 去另一个项目里搬回来。库与文件搬移由 OrganizeRepository.moveGroupToProject
  /// 负责，这里只管选人、确认、汇报结果。
  Future<void> _moveGroupToProject(OpenGroup g) async {
    final projects =
        ref.read(projectListProvider).valueOrNull ?? const <ProjectSummary>[];
    final others =
        projects.where((pr) => pr.id != widget.projectId).toList();
    if (!mounted) return;
    if (others.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('还没有其他项目 —— 先回首页新建一个，再回来移动这组。'),
      ));
      return;
    }

    // ⚠️ 列表必须可滚动（2026-10-09 真机反馈）：项目一多 Column 直排
    // 就超出屏幕 —— 最后一行被裁一半、剩下的项目既看不到也点不到。
    // 标题固定，列表交给 Flexible+ListView(shrinkWrap)：项目少时高度
    // 照旧包住内容，多时在面板内滚动，两不误。
    final target = await showModalBottomSheet<ProjectSummary>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 6),
            const ListTile(title: Text('移动到哪个项目？')),
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
        title: Text('移动到「${target.name}」？'),
        content: Text(
          '把第 ${g.seq} 组（${g.photos.length} 张'
          '${(g.carton ?? '').trim().isNotEmpty ? ' · 箱号 ${g.carton}' : ''}）'
          '移到「${target.name}」。\n\n'
          '移动后这组照片从本项目消失，在目标项目里继续成组；'
          '文件、缩略图与箱号都随行。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppTheme.accent),
            child: const Text('移动'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(organizeRepositoryProvider).moveGroupToProject(
            fromProjectId: widget.projectId,
            groupId: g.groupId,
            toProjectId: target.id,
          );
      ref.invalidate(openGroupsProvider(widget.projectId));
      ref.invalidate(projectSummaryProvider(widget.projectId));
      ref.invalidate(projectPhotoCountProvider(widget.projectId));
      ref.invalidate(duplicateReportProvider(widget.projectId));
      messenger.showSnackBar(SnackBar(
        content: Text(
            '已把第 ${g.seq} 组（${g.photos.length} 张）移到「${target.name}」'),
      ));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('移动失败：$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final groups = ref.watch(openGroupsProvider(widget.projectId));
    final s = widget.summary;

    // 状态条用的三个数**直接从列表算**，不再另开流。
    // 指派下线后已没有"正视组/把组从列表移走"这回事 ——
    // 列表就是全部，count 即真相（不用 summary 里的 groupPending 兜底了）。
    final list = groups.valueOrNull ?? const <OpenGroup>[];
    final photoCount =
        list.fold<int>(0, (sum, g) => sum + g.photos.length);
    final cartonCount = list
        .where((g) => (g.carton ?? '').trim().isNotEmpty)
        .length;

    // 重复照片报告（2026-10-04）。provider 内部会先把缺失的指纹补算完，
    // 所以 loading 期间显示「正在核查」而不是隐藏横幅 ——
    // 藏起来等于骗人说"没问题"。
    final dupState = ref.watch(duplicateReportProvider(widget.projectId));
    final dup = dupState.valueOrNull;

    return Column(
      children: [
        // ── ① 部类切换（预检 / 监装）──
        _PartSwitch(
          index: _sectionIndex,
          onChanged: (i) => setState(() {
            _sectionIndex = i;
            if (_mergeMode) _exitMergeMode();
          }),
        ),

        // ── ② 主行动条 / 监装提示 ──
        // 拍照是这一页最高频的动作，给最显眼的位置（实心 + 占 3/5 宽）；
        // 相册导入是补漏手段，次级样式。
        //
        // ⚠️ 只在**预检**部类下出现：入库的照片固定是预检（photos.category
        // 默认 precheck），在监装部类下按快门会拍出"这里看不见的照片"。
        // 监装照片的来源是：在预检里把整组标为监装 —— 见下面那行提示。
        if (_sectionIndex == 0)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 2),
            child: Row(
              children: [
                Expanded(
                  flex: 3,
                  child: SizedBox(
                    height: 46,
                    child: FilledButton.icon(
                      onPressed: _openCamera,
                      style: FilledButton.styleFrom(
                        backgroundColor: AppTheme.accent,
                      ),
                      icon: const Icon(Icons.photo_camera, size: 19),
                      label: const Text('拍照入库'),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  flex: 2,
                  child: SizedBox(
                    height: 46,
                    child: OutlinedButton.icon(
                      // 导入手机里已有的照片 —— 目的就是"补进这批去对应货品"，
                      // 放在干这活的页面最顺手。导入成功后待办流自动重读。
                      onPressed: () =>
                          runGalleryImport(context, ref, widget.projectId),
                      icon: const Icon(Icons.photo_library_outlined, size: 18),
                      label: const Text('相册导入'),
                    ),
                  ),
                ),
              ],
            ),
          )
        else
          const Padding(
            padding: EdgeInsets.fromLTRB(14, 8, 14, 4),
            child: Text(
              '监装照片在「预检」里拍 —— 拍完回到预检列表，'
              '把整组标为监装即可。',
              style: TextStyle(
                fontSize: 11.5,
                color: AppTheme.textMuted,
                height: 1.5,
              ),
            ),
          ),
        // 监装：一张照片墙就够（不与清单对应、不分箱、不指派）。
        if (_sectionIndex == 1)
          Expanded(
            child: _SupervisionWall(
              projectId: widget.projectId,
              onDeletePhoto: (id) => _deletePhoto(id),
            ),
          )
        else ...[
          // ── ③ 重复照片横幅（2026-10-04「照片不能重复」）──
          // 位置在拍照条**之下**、状态条之上：横幅要显眼，但压住
          // 顶部那三个数字的注意力没意义 —— 数字是"信息"，重复是"警报"。
          // 监装部类下不显示（监装墙是流水，不存在"重复"这个业务概念）。
          DuplicateBanner(
            loading: dupState.isLoading,
            duplicateCount: dup?.redundantTotal ?? 0,
            // 2026-10-05 具体化：把「几组重复」与「其中几组跨组」摆到
            // 横幅上，让人不用点开就知道这事有多严重。
            setCount: dup?.sets.length ?? 0,
            crossGroupCount: dup?.crossGroupCount ?? 0,
            onScanning: dup?.pendingCount ?? 0,
            onOpen: () {
              final sets = dup?.sets ?? const [];
              if (sets.isEmpty) return;
              showDuplicateSheet(context, ref,
                  projectId: widget.projectId, sets: sets);
            },
          ),
          // ── ④ 一行状态：组数 · 张数 · 已分箱 + 合并入口 ──
          // 取代原先的 _CoverageHeader（约 130px：页签 + 覆盖率标题 +
          // 百分比 + 进度条 + 缺口行 + 提示文字）。指派下线后那些都没有
          // 意义了 —— 这里只留人真正要看的三个数，一行 34px 收工。
          _StatusStrip(
            groupCount: list.length,
            photoCount: photoCount,
            cartonCount: cartonCount,
            mergeMode: _mergeMode,
            onToggleMerge: _mergeMode ? _exitMergeMode : _enterMergeMode,
            // 2026-10-08 真机诉求：按箱号排序（交付时按箱装车，按箱号
            // 翻组最顺手）。默认关 —— 保持拍摄时间序。
            sortByCarton: _sortByCarton,
            onToggleSort: () => setState(() => _sortByCarton = !_sortByCarton),
          ),
          // ── ④b OCR 识别状态（v0.24.2）──
          // 回答现场提问「怎么知道这些照片识别过了没有」—— 识别结果
          // 就是按编码搜照片的数据来源，覆盖情况必须摆在明面上。
          _OcrStrip(
            projectId: widget.projectId,
            progress: _ocrProgress,
          ),
          Expanded(
            child: RefreshIndicator(
                // P4 · 诉求 3 的手动兜底：万一自动补组因为某些原因没跟上，
                // 下拉一下就能强制补一轮分组 + 重读待办流。
                // 自动路径已由 openGroupsProvider 负责，这是"人的手指"这一层保险。
                onRefresh: _manualRefresh,
                child: groups.when(
                  loading: () =>
                      const Center(child: CircularProgressIndicator()),
                  error: (e, st) => StageEmptyState(
                    icon: Icons.error_outline,
                    title: '组读取失败',
                    hint: '$e',
                  ),
                  data: (list) {
                    // 2026-10-08 真机诉求「按箱号排序」：默认仍按拍摄时间
                    // （现场走动顺序），开「按箱号」后已分箱的组按箱号
                    // 数字感知排序排前面，没分箱的沉底按时间排。
                    final ordered =
                        _sortByCarton ? _sortByCartonLabel(list) : list;
                    if (ordered.isEmpty) {
                      // 空态也要能下拉 —— 用 AlwaysScrollable 让它可滚动
                      return ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        children: [
                          SizedBox(
                            height: MediaQuery.of(context).size.height * 0.5,
                            child: _AllDoneCard(summary: s),
                          ),
                        ],
                      );
                    }
                    return ListView.builder(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
                      itemCount: ordered.length,
                      itemBuilder: (_, i) {
                        final g = ordered[i];
                        return _GroupCard(
                          group: g,
                          mergeMode: _mergeMode,
                          picked: _picked.contains(g.groupId),
                          onPick: () => _togglePick(g.groupId),
                          onAddPhotos: () => _addPhotosToGroup(g),
                          onMoveOut: (photoId) => _moveOut(photoId),
                          onOpenPhoto: (index) => _openViewer(g, index),
                          onSetCarton: () => _setCarton(g),
                          onMarkSupervision: () =>
                              _markSupervision(g.groupId, g.seq),
                          onDeletePhoto: (photoId) => _deletePhoto(photoId),
                          onDeleteGroup: () =>
                              _deleteGroup(g.groupId, g.seq),
                          onMoveProject: () => _moveGroupToProject(g),
                          // 拖拽合并：拖到本卡片上就并入本组。
                          // 合并模式下禁用（那时用的是"勾选 + 合并按钮"这套）。
                          onDroppedOn:
                              _mergeMode ? null : (draggedId) => _mergeByDrag(
                                    draggedGroupId: draggedId,
                                    targetGroupId: g.groupId,
                                    allGroups: ordered,
                                  ),
                        );
                      },
                    );
                  },
                ),
              ),
            ),
        if (_mergeMode)
          _MergeBar(
            pickedCount: _picked.length,
            onMerge: _merge,
          ),
        ],
      ],
    );
  }
}


// ═══════════════════════════════════════════════════════════════
// 一行状态条（2026-10-01 取代 _CoverageHeader）
// ═══════════════════════════════════════════════════════════════
//
// 指派下线后，「清单覆盖率 / 已指派 / 清单缺口」这条挂 `itemId` 的装饰链
// 整个失效 —— 没有写 itemId 的路径了，`itemDone` 永远停在 0，
// 覆盖率会恒显示 0%，留着就是骗人。
//
// 照片现在的组织维度只剩「部类 → 箱号 → 组」，状态条也就只回答这三件事：
// 几组、几张、几个指定了箱号。
//
// 高度是硬指标（老板 2026-10-01「选项卡太多，分组空间不足」）：34px 封顶，
// 合并入口作为文字按钮并进同一行，不再单独占一行。
class _StatusStrip extends StatelessWidget {
  const _StatusStrip({
    required this.groupCount,
    required this.photoCount,
    required this.cartonCount,
    required this.mergeMode,
    required this.onToggleMerge,
    required this.sortByCarton,
    required this.onToggleSort,
  });

  final int groupCount;
  final int photoCount;
  final int cartonCount;
  final bool mergeMode;
  final VoidCallback onToggleMerge;
  final bool sortByCarton;
  final VoidCallback onToggleSort;

  @override
  Widget build(BuildContext context) {
    final allCartoned = groupCount > 0 && cartonCount == groupCount;

    return SizedBox(
      height: 34,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(
          children: [
            Text(
              '$groupCount 组',
              style: const TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w700,
                color: AppTheme.navy,
              ),
            ),
            const _Dot(),
            Text('$photoCount 张',
                style:
                    const TextStyle(fontSize: 12.5, color: AppTheme.textMain)),
            if (groupCount > 0) ...[
              const _Dot(),
              Text(
                allCartoned ? '已全部分箱' : '已分箱 $cartonCount',
                style: TextStyle(
                  fontSize: 12.5,
                  color: allCartoned ? AppTheme.green : AppTheme.amber,
                ),
              ),
            ],
            const Spacer(),
            // 排序切换（2026-10-08 真机诉求「按箱号排序」）：
            // 时间序（默认）↔ 箱号序。只有分过箱才给这个入口 ——
            // 一个箱号都没有时切过去什么都不会变，是假按钮。
            if (cartonCount > 0)
              TextButton.icon(
                onPressed: onToggleSort,
                style: TextButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  minimumSize: Size.zero,
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  foregroundColor:
                      sortByCarton ? AppTheme.accent : AppTheme.textMuted,
                ),
                icon: Icon(
                  sortByCarton ? Icons.inventory_2 : Icons.sort,
                  size: 15,
                ),
                label: Text(
                  sortByCarton ? '按箱号' : '按时间',
                  style: const TextStyle(fontSize: 12.5),
                ),
              ),
            // 合并 / 退出合并。低频但必须有个固定落点 ——
            // 长按拖拽也能合并，但那招要"发现"才用得上。
            TextButton.icon(
              onPressed: onToggleMerge,
              style: TextButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                foregroundColor:
                    mergeMode ? AppTheme.accent : AppTheme.textMuted,
              ),
              icon: Icon(mergeMode ? Icons.close : Icons.merge, size: 15),
              label: Text(
                mergeMode ? '退出合并' : '合并',
                style: const TextStyle(fontSize: 12.5),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// OCR 识别状态行（v0.24.2）
// ═══════════════════════════════════════════════════════════════
//
// 一条 26px 的小行，只在「有事可说」时出现：
//   · 正在识别   → 进度条 + done/total（实时，来自 progressStream）；
//   · 有失败     → 失败张数 + 重试入口（P4 真机反馈：失败必须可见可恢复）；
//   · 还有 pending → 还剩几张，并说明「打开本页会自动开始」；
//   · 全部完成   → 「已识别 N 张 · 可按编码搜索」—— 这是「照片识别过
//     了没有」的正面回答（2026-10-15 真机提问）。
//
// 统计走 [ocrPhotoStatsProvider]（drift 流）：照片状态一变自动推新。
class _OcrStrip extends ConsumerWidget {
  const _OcrStrip({required this.projectId, this.progress});

  final String projectId;

  /// 来自 `SuggestPipeline.progressStream` 的实时进度（null = 没在跑）。
  final SuggestProgress? progress;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final stats = ref.watch(ocrPhotoStatsProvider(projectId)).valueOrNull;

    // 正在识别：进度优先于统计 —— 统计要等写库才变，进度是实时的。
    final p = progress;
    if (p != null && p.total > 0 && !p.finished) {
      return _OcrLine(
        icon: Icons.document_scanner_outlined,
        color: AppTheme.accent,
        text: '正在识别 ${p.done}/${p.total}…',
        trailing: SizedBox(
          width: 72,
          child: LinearProgressIndicator(
            value: p.ratio,
            minHeight: 3,
            backgroundColor: AppTheme.line,
          ),
        ),
      );
    }

    // 没照片 / 流还没就绪：什么都不说（显示「0 张」比不说更糟）。
    if (stats == null || stats.total == 0) return const SizedBox.shrink();

    if (stats.hasFailed) {
      return _OcrLine(
        icon: Icons.error_outline,
        color: AppTheme.red,
        text: '识别失败 ${stats.failed} 张',
        trailing: TextButton(
          onPressed: () => _retryFailed(context, ref),
          style: TextButton.styleFrom(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            minimumSize: Size.zero,
            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
          child: const Text('重试', style: TextStyle(fontSize: 12)),
        ),
      );
    }

    if (stats.pending > 0) {
      return _OcrLine(
        icon: Icons.hourglass_bottom,
        color: AppTheme.amber,
        text: '还有 ${stats.pending} 张待识别 —— 打开本页会自动开始',
      );
    }

    return _OcrLine(
      icon: Icons.check_circle_outline,
      color: AppTheme.green,
      text: '已识别 ${stats.done} 张 · 可按编码搜索',
    );
  }

  /// 失败重试（P4 真机反馈）。管道内部把 failed 标回 pending 再跑一轮，
  /// 进度照常走 progressStream；撞上正在跑的一轮会排队，不丢请求。
  Future<void> _retryFailed(BuildContext context, WidgetRef ref) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final n =
          await ref.read(suggestPipelineProvider).retryFailedPhotos(projectId);
      messenger.showSnackBar(
        SnackBar(
          content: Text(n > 0 ? '已重新识别 $n 张' : '没有失败的照片'),
          duration: const Duration(seconds: 2),
        ),
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('重试失败：$e')));
    }
  }
}

/// [_OcrStrip] 的一行排版（图标 + 文字 + 尾部控件）。
class _OcrLine extends StatelessWidget {
  const _OcrLine({
    required this.icon,
    required this.color,
    required this.text,
    this.trailing,
  });

  final IconData icon;
  final Color color;
  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 26,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 0, 8, 0),
        child: Row(
          children: [
            Icon(icon, size: 13, color: color),
            const SizedBox(width: 5),
            Expanded(
              child: Text(
                text,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 11.5, color: color),
              ),
            ),
            if (trailing != null) trailing!,
          ],
        ),
      ),
    );
  }
}

class _Dot extends StatelessWidget {
  const _Dot();

  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.symmetric(horizontal: 6),
        child: Text('·',
            style: TextStyle(fontSize: 12.5, color: AppTheme.textMuted)),
      );
}

/// 按箱号排序（2026-10-08 真机诉求）。
///
/// 规则：已分箱的组在前，箱号**数字感知**比较 —— 「702」必须排在
/// 「1002」前面（字典序会反过来）；箱号里的非数字段（如「A排-702」）
/// 按字符参与比较。没分箱的沉底，组内按拍摄时间排。
/// 同箱号的组保持拍摄时间序。
List<OpenGroup> _sortByCartonLabel(List<OpenGroup> groups) {
  bool hasCarton(OpenGroup g) => (g.carton ?? '').trim().isNotEmpty;
  final sorted = [...groups]..sort((a, b) {
      final ra = hasCarton(a) ? 0 : 1;
      final rb = hasCarton(b) ? 0 : 1;
      if (ra != rb) return ra - rb;
      if (ra == 1) return a.takenAtMs.compareTo(b.takenAtMs);
      final c = _compareCarton(a.carton!.trim(), b.carton!.trim());
      if (c != 0) return c;
      return a.takenAtMs.compareTo(b.takenAtMs);
    });
  return sorted;
}

/// 箱号的数字感知比较：逐段扫，连续数字段按**数值**比（去前导零），
/// 非数字段按字符码比。「702」 < 「1002」，「箱10」 < 「箱9」不成立 →
/// 「箱9」 < 「箱10」。
int _compareCarton(String a, String b) {
  var i = 0;
  var j = 0;
  bool isDigit(int c) => c >= 0x30 && c <= 0x39;
  while (i < a.length && j < b.length) {
    final da = isDigit(a.codeUnitAt(i));
    final db = isDigit(b.codeUnitAt(j));
    if (da && db) {
      var i2 = i;
      while (i2 < a.length && isDigit(a.codeUnitAt(i2))) {
        i2++;
      }
      var j2 = j;
      while (j2 < b.length && isDigit(b.codeUnitAt(j2))) {
        j2++;
      }
      // 去前导零后：先比有效长度，再比字典序 —— 等价于按数值比，
      // 但不会溢出（箱号可能是超长数字串）。
      final ta = a.substring(i, i2).replaceAll(RegExp('^0+'), '');
      final tb = b.substring(j, j2).replaceAll(RegExp('^0+'), '');
      final c = ta.length != tb.length
          ? ta.length.compareTo(tb.length)
          : ta.compareTo(tb);
      if (c != 0) return c;
      i = i2;
      j = j2;
    } else {
      final c = a.codeUnitAt(i).compareTo(b.codeUnitAt(j));
      if (c != 0) return c;
      i++;
      j++;
    }
  }
  // 前缀相同：短的小（「702」 < 「702A」）
  return (a.length - i).compareTo(b.length - j);
}

// ═══════════════════════════════════════════════════════════════
// 组卡片
// ═══════════════════════════════════════════════════════════════

class _GroupCard extends StatelessWidget {
  const _GroupCard({
    required this.group,
    required this.mergeMode,
    required this.picked,
    required this.onPick,
    required this.onAddPhotos,
    required this.onMoveOut,
    required this.onOpenPhoto,
    required this.onSetCarton,
    required this.onMarkSupervision,
    required this.onDeletePhoto,
    required this.onDeleteGroup,
    required this.onMoveProject,
    this.onDroppedOn,
  });

  final OpenGroup group;
  final bool mergeMode;
  final bool picked;
  final VoidCallback onPick;

  /// 「补充照片」—— 给本组补拍 / 补导。
  ///
  /// 【2026-10-01】原「添加照片」。指派按钮取消后它独占次按钮整行，
  /// 措辞改成"补充"更贴它的实际用途：往已有的一组里补几张。
  final VoidCallback onAddPhotos;

  final void Function(String photoId) onMoveOut;

  /// 点缩略图看全图（P4 诉求 2），参数是组内索引。
  final void Function(int index) onOpenPhoto;

  /// 有别的组被拖到本卡片上时触发（P4 诉求 2），参数是**被拖来**的组 id。
  /// null = 当前不允许拖拽合并（合并模式下用勾选那套）。
  final void Function(String draggedGroupId)? onDroppedOn;

  /// 「指定箱号」（老板 2026-09-27 拍板：箱号由人输入，不依赖清单）。
  final VoidCallback onSetCarton;

  /// 「这组是监装」—— 装柜过程的照片，与货品清单无关、不对应编码。
  final VoidCallback onMarkSupervision;

  /// 删除这一张照片（缩略图右上角的删除按钮，M7）。
  final void Function(String photoId) onDeletePhoto;

  /// 删除整组（卡片右上角菜单「删除整组」，M7）。
  final VoidCallback onDeleteGroup;

  /// 移动到其他项目（2026-10-08 真机诉求④）。
  final VoidCallback onMoveProject;

  @override
  Widget build(BuildContext context) {
    final g = group;
    final n = g.photos.length;
    final taken = DateTime.fromMillisecondsSinceEpoch(g.takenAtMs);
    final hh = taken.hour.toString().padLeft(2, '0');
    final mm = taken.minute.toString().padLeft(2, '0');
    final underShot = n < 2; // §5.3.1：单张组提示"可能漏拍"
    final cartonLabel = (g.carton ?? '').trim();
    final hasCarton = cartonLabel.isNotEmpty;

    final card = Card(
      // margin 放在外层 Padding 里（见下方拖拽分支）——
      // 否则拖拽时的 AnimatedContainer 边框会把 Card 的
      // bottom margin 也一起框进来，视觉上多出 9px 空隙。
      margin: EdgeInsets.zero,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(11),
        side: BorderSide(
          color: picked ? AppTheme.accent : AppTheme.line,
          width: picked ? 2 : 1,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(11),
        onTap: mergeMode ? onPick : null,
        child: Padding(
          padding: const EdgeInsets.all(11),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── 头行 ──
              Row(
                children: [
                  if (mergeMode)
                    Icon(
                      picked
                          ? Icons.check_box
                          : Icons.check_box_outline_blank,
                      size: 19,
                      color: picked ? AppTheme.accent : AppTheme.textMuted,
                    )
                  else
                    const Icon(Icons.photo_library_outlined,
                        size: 17, color: AppTheme.textMuted),
                  const SizedBox(width: 7),
                  Text(
                    '第 ${g.seq} 组',
                    style: const TextStyle(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.navy,
                    ),
                  ),
                  const SizedBox(width: 7),
                  Text(
                    '$n 张',
                    style: const TextStyle(
                        fontSize: 12, color: AppTheme.textMain),
                  ),
                  if (underShot) ...[
                    const SizedBox(width: 6),
                    const StageBadge(
                        text: '可能漏拍', color: AppTheme.amber),
                  ],
                  const Spacer(),
                  Text(
                    '$hh:$mm',
                    style: const TextStyle(
                        fontSize: 12, color: AppTheme.textMuted),
                  ),
                  // 拖拽提示：只有在能拖的时候才显示，
                  // 否则一个不能用的手柄是纯噪声
                  if (!mergeMode) ...[
                    const SizedBox(width: 4),
                    const Icon(Icons.drag_indicator,
                        size: 16, color: AppTheme.textMuted),
                    const SizedBox(width: 2),
                    // 删除整组入口（M7）：非合并模式下可见
                    PopupMenuButton<String>(
                      tooltip: '更多',
                      icon: const Icon(Icons.more_vert, size: 18),
                      padding: EdgeInsets.zero,
                      constraints:
                          const BoxConstraints(minWidth: 28, minHeight: 28),
                      onSelected: (v) {
                        if (v == 'supervise') onMarkSupervision();
                        if (v == 'moveProject') onMoveProject();
                        if (v == 'delete') onDeleteGroup();
                      },
                      itemBuilder: (_) => [
                        const PopupMenuItem(
                          value: 'moveProject',
                          child: Row(
                            children: [
                              Icon(Icons.drive_file_move_outlined, size: 18),
                              SizedBox(width: 8),
                              Text('移动到其他项目'),
                            ],
                          ),
                        ),
                        const PopupMenuItem(
                          value: 'supervise',
                          child: Row(
                            children: [
                              Icon(Icons.local_shipping_outlined, size: 18),
                              SizedBox(width: 8),
                              Text('标为监装'),
                            ],
                          ),
                        ),
                        const PopupMenuItem(
                          value: 'delete',
                          child: Row(
                            children: [
                              Icon(Icons.delete_outline,
                                  size: 18, color: AppTheme.red),
                              SizedBox(width: 8),
                              Text('删除整组',
                                  style: TextStyle(color: AppTheme.red)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 9),
              // ── 缩略图行 ──
              SizedBox(
                height: 74,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: g.photos.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 7),
                  itemBuilder: (_, i) {
                    final p = g.photos[i];
                    return _GroupThumb(
                      thumbPath: p.thumbPath,
                      // 点一下看全图（P4 诉求 2）
                      onTap: mergeMode ? null : () => onOpenPhoto(i),
                      // 多张组才允许"移出单张"—— 单张组移出没有意义
                      onLongPress:
                          (!mergeMode && n > 1) ? () => onMoveOut(p.id) : null,
                      // 逐张删除（M7）：缩略图右上角的删除按钮
                      onDelete: !mergeMode ? () => onDeletePhoto(p.id) : null,
                    );
                  },
                ),
              ),
              // （建议层 / 一键确认已随 OCR 与指派一并下线，2026-10-01。）
              const SizedBox(height: 9),
                // ── 第一主按钮：指定箱号（2026-09-29 老板拍板）──
                // 箱号是每组的主要操作，从角标 chip 升级为卡片第一主按钮。
                // 未指定时 accent 高亮引导；已指定时换蓝底并带箱号名。
                SizedBox(
                  width: double.infinity,
                  height: 42,
                  child: FilledButton.icon(
                    onPressed: onSetCarton,
                    style: FilledButton.styleFrom(
                      backgroundColor:
                          hasCarton ? AppTheme.blue : AppTheme.accent,
                    ),
                    icon: const Icon(Icons.inventory_2, size: 17),
                    label: Text(
                      hasCarton ? '箱号：$cartonLabel · 点击修改' : '指定箱号',
                      style: const TextStyle(
                          fontSize: 13.5, fontWeight: FontWeight.w700),
                    ),
                  ),
                ),
                const SizedBox(height: 6),
                // ── 次按钮行 ──
                // 2026-10-01：指派下线后这行只剩「添加照片」，两个半宽按钮
                // 变成孤零零一个半宽 —— 索性让它占满整行，卡片也矮了一截。
                // 2026-10-08 真机反馈「按钮偏小」：36→42 与箱号按钮同高，
                // 字号 12→13.5 —— 这两个按钮是现场唯一的手动入口，触达
                // 面积不能比主按钮还小一截。
                Row(
                  children: [
                    Expanded(
                      child: SizedBox(
                        height: 42,
                        child: OutlinedButton.icon(
                          onPressed: onAddPhotos,
                          style: OutlinedButton.styleFrom(
                            foregroundColor: AppTheme.textMain,
                            side: BorderSide(
                              color: AppTheme.line.withValues(alpha: 0.9),
                            ),
                            padding: const EdgeInsets.symmetric(horizontal: 6),
                          ),
                          icon: const Icon(Icons.add_photo_alternate_outlined,
                              size: 17),
                          label: const Text('补充照片',
                              style: TextStyle(
                                  fontSize: 13.5,
                                  fontWeight: FontWeight.w700)),
                        ),
                      ),
                    ),
                  ],
                ),
                // 「标为监装」是低频操作（一个项目标不了几次），从动作区
                // 收进右上角「更多」菜单，把按钮位让给箱号。
            ],
          ),
        ),
      ),
    );

    // 不能拖时不包任何手势层 —— 保持原来的样子
    if (onDroppedOn == null || mergeMode) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 9),
        child: card,
      );
    }

    // ── 拖拽合并（P4 诉求 2）──
    // 外层 DragTarget：接住拖到本卡片上的组。
    // 内层 LongPressDraggable：长按本卡片把它拖走。
    // 顺序不能反 —— DragTarget 要在外层，否则它的命中区域会被
    // Draggable 的 hit-test 行为影响。
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: DragTarget<String>(
        // 只接受"另一个组"，拖到自己身上无意义
        onWillAcceptWithDetails: (d) => d.data != g.groupId,
        onAcceptWithDetails: (d) => onDroppedOn!(d.data),
        builder: (context, candidates, rejected) {
          final hovering = candidates.isNotEmpty;
          return LongPressDraggable<String>(
            data: g.groupId,
            // ⚠️ feedback **只能用缩略图** —— 它在拖动时一直挂在屏幕上，
            //    用原图会在几百张的量级上直接把内存吃掉（R1b 铁律）。
            feedback: _DragFeedback(group: g),
            // 拖走时原卡片半透明，让人看清"它被提起来了"
            childWhenDragging: Opacity(opacity: 0.35, child: card),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 120),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(11),
                // 悬停高亮：告诉人"松手会并到这里"
                border: Border.all(
                  color: hovering ? AppTheme.accent : Colors.transparent,
                  width: 2,
                ),
              ),
              child: card,
            ),
          );
        },
      ),
    );
  }
}

/// 拖拽时跟着手指走的浮层。
///
/// 刻意做得小：它是"我手里拿着第 N 组"的提示，不是内容预览 ——
/// 内容预览（整张大图）在拖动时会疯狂重绘，是卡顿的主要来源。
class _DragFeedback extends StatelessWidget {
  const _DragFeedback({required this.group});

  final OpenGroup group;

  @override
  Widget build(BuildContext context) {
    final p = group.coverThumbPath;
    return Material(
      color: Colors.transparent,
      child: Container(
        width: 116,
        padding: const EdgeInsets.all(7),
        decoration: BoxDecoration(
          color: AppTheme.card,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppTheme.accent, width: 2),
          boxShadow: const [
            BoxShadow(color: Color(0x33000000), blurRadius: 10),
          ],
        ),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: SizedBox(
                width: 34,
                height: 34,
                // ⚠️ 性能（09-29 排查）：build 里的 `existsSync()` 是同步文件
                // IO —— 列表每重建一次就跑一遍（几百个格子时肉眼可见的卡顿）。
                // 文件缺失由 errorBuilder 兜底。
                child: (p != null)
                    ? Image.file(
                        File(p),
                        fit: BoxFit.cover,
                        filterQuality: FilterQuality.low,
                        gaplessPlayback: true,
                        // 34dp 的格子按 256px 解码是浪费（09-29 性能排查）
                        cacheWidth: 72,
                        errorBuilder: (_, __, ___) =>
                            const ColoredBox(color: AppTheme.bg),
                      )
                    : const ColoredBox(color: AppTheme.bg),
              ),
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    '第 ${group.seq} 组',
                    style: const TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.navy,
                    ),
                  ),
                  Text(
                    '${group.photoCount} 张',
                    style: const TextStyle(
                        fontSize: 11, color: AppTheme.textMuted),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 缩略图 / 合并模式底栏 / 清零态
// ═══════════════════════════════════════════════════════════════

class _GroupThumb extends StatelessWidget {
  const _GroupThumb({
    required this.thumbPath,
    this.onTap,
    this.onLongPress,
    this.onDelete,
  });

  final String? thumbPath;

  /// 点一下看全图（P4 诉求 2）。
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  /// 逐张删除（M7）：非 null 时在右上角显示删除按钮。
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    final p = thumbPath;
    final content = Container(
      width: 74,
      height: 74,
      decoration: BoxDecoration(
        color: AppTheme.bg,
        borderRadius: BorderRadius.circular(7),
        border: Border.all(color: AppTheme.line),
      ),
      clipBehavior: Clip.antiAlias,
      // ⚠️ 性能（09-29 排查）：去掉 build 里的同步 existsSync()，缺失由
      // errorBuilder 兜底（照片墙几百格时，每帧几百次文件 IO 是掉帧主因）。
      child: (p != null)
          ? Image.file(
              File(p),
              fit: BoxFit.cover,
              filterQuality: FilterQuality.low,
              gaplessPlayback: true,
              // 74dp 的格子（09-29 性能排查）：按 2 倍显示尺寸解码足够
              cacheWidth: 160,
              errorBuilder: (_, __, ___) => const Icon(
                Icons.broken_image_outlined,
                size: 18,
                color: AppTheme.textMuted,
              ),
            )
          : const Icon(
              Icons.image_outlined,
              size: 18,
              color: AppTheme.textMuted,
            ),
    );

    final tappable = GestureDetector(
      onTap: onTap,
      onLongPress: onLongPress,
      child: content,
    );

    if (onDelete == null) return tappable;

    // 右上角叠一个红色删除按钮（M7）
    return SizedBox(
      width: 74,
      height: 74,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          tappable,
          Positioned(
            top: 2,
            right: 2,
            child: GestureDetector(
              onTap: onDelete,
              behavior: HitTestBehavior.opaque,
              child: Container(
                decoration: BoxDecoration(
                  color: AppTheme.red,
                  shape: BoxShape.circle,
                  border: Border.all(color: Colors.white, width: 1.5),
                ),
                padding: const EdgeInsets.all(2.5),
                child: const Icon(Icons.close, size: 13, color: Colors.white),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MergeBar extends StatelessWidget {
  const _MergeBar({required this.pickedCount, required this.onMerge});

  final int pickedCount;
  final VoidCallback onMerge;

  @override
  Widget build(BuildContext context) {
    final ready = pickedCount >= 2;
    return Container(
      color: AppTheme.card,
      padding: EdgeInsets.only(
        left: 14,
        right: 14,
        top: 10,
        bottom: 10 + MediaQuery.of(context).padding.bottom,
      ),
      child: Row(
        children: [
          Text(
            '已选 $pickedCount 组（先选的为目标组）',
            style: const TextStyle(
                fontSize: 12, color: AppTheme.textMuted),
          ),
          const Spacer(),
          FilledButton(
            onPressed: ready ? onMerge : null,
            style: FilledButton.styleFrom(
              backgroundColor: AppTheme.accent,
            ),
            child: const Text('合并所选'),
          ),
        ],
      ),
    );
  }
}

class _AllDoneCard extends StatelessWidget {
  const _AllDoneCard({required this.summary});

  final ProjectSummary summary;

  @override
  Widget build(BuildContext context) {
    final s = summary;
    // 指派下线后不再有"缺口"这回事 —— 空态只回答"下一步干什么"，
    // 不拿 itemGap / itemTotal 去讲一个已经没有人关心的话题。
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.photo_library_outlined,
                size: 52, color: AppTheme.green),
            const SizedBox(height: 14),
            Text(
              s.hasAnyPhoto ? '照片都归好组了' : '这个项目还没有照片',
              style: const TextStyle(
                fontSize: 16.5,
                fontWeight: FontWeight.w800,
                color: AppTheme.navy,
              ),
            ),
            const SizedBox(height: 7),
            Text(
              s.hasAnyPhoto
                  ? '每组都指定了箱号的话，就可以去「交付」出包了。'
                  : '点上面的「拍照入库」开拍，或用「相册导入」把已有的照片拿进来。',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 13,
                color: AppTheme.textMuted,
                height: 1.65,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 预检 / 监装 部类切换（老板 2026-09-27 拍板）
// ═══════════════════════════════════════════════════════════════

/// 顶部两段切换：预检 / 监装。
///
/// 放在整理页最顶端而不是塞进设置：这是**整理的第一刀** ——
/// 拿到几百张照片，先分"哪些是预检、哪些是监装"，再往下做。
class _PartSwitch extends StatelessWidget {
  const _PartSwitch({required this.index, required this.onChanged});

  final int index;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 2),
      child: SegmentedButton<int>(
        segments: const [
          ButtonSegment<int>(
            value: 0,
            icon: Icon(Icons.fact_check_outlined, size: 17),
            label: Text('预检'),
          ),
          ButtonSegment<int>(
            value: 1,
            icon: Icon(Icons.local_shipping_outlined, size: 17),
            label: Text('监装'),
          ),
        ],
        selected: <int>{index},
        onSelectionChanged: (s) => onChanged(s.first),
        style: SegmentedButton.styleFrom(
          minimumSize: const Size(0, 38),
          textStyle: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 监装照片墙
// ═══════════════════════════════════════════════════════════════

/// 监装照片：一张照片墙，没有别的。
///
/// 为什么不给它分组/建议：监装照片与货品清单**无关**
/// （老板拍板原话：「监装照片与货品清单无关，放一个文件夹即可」）。
/// 任何"对应到哪件货"的入口出现在这里都是噪声 —— 它只需要被看见、
/// 被数清楚，然后打包时整体进「监装」文件夹。
class _SupervisionWall extends ConsumerWidget {
  const _SupervisionWall({
    required this.projectId,
    required this.onDeletePhoto,
  });

  final String projectId;

  /// 删除监装照片（M7）。参数是照片 id。
  final void Function(String photoId) onDeletePhoto;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(supervisionPhotosProvider(projectId));

    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, st) => StageEmptyState(
        icon: Icons.error_outline,
        title: '监装照片读取失败',
        hint: '$e',
      ),
      data: (photos) {
        if (photos.isEmpty) {
          return ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
            children: const [
              _SupervisionEmpty(),
            ],
          );
        }

        // 监装照片没有"组"的概念，但 [PhotoViewerPage] 以组为单位工作 ——
        // 构一个影子组把整面墙的照片装进去，点哪张从哪张开始翻。
        // groupLabel 覆盖页脚的「第 0 组」为「监装照片」（09-30）。
        final viewerGroup = OpenGroup(
          groupId: 'supervision-$projectId',
          seq: 0,
          takenAtMs: photos.first.takenAtMs,
          photos: photos,
          category: PhotoCategory.supervision,
        );

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 14, 8),
              child: Row(
                children: [
                  const Icon(Icons.local_shipping_outlined,
                      size: 17, color: AppTheme.accent),
                  const SizedBox(width: 8),
                  Text(
                    '监装 ${photos.length} 张',
                    style: const TextStyle(
                      fontSize: 14.5,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.navy,
                    ),
                  ),
                  const Spacer(),
                  TextButton.icon(
                    onPressed: () => _markAllBackToPrecheck(context, ref, photos),
                    icon: const Icon(Icons.undo, size: 15),
                    label: const Text('全部改回预检'),
                    style: TextButton.styleFrom(
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                  ),
                ],
              ),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(14, 0, 14, 8),
              child: Text(
                '装柜过程的照片，与货品清单无关。'
                '交付时全部放进「监装」文件夹，用原始文件名。',
                style: TextStyle(
                  fontSize: 11.5,
                  color: AppTheme.textMuted,
                  height: 1.6,
                ),
              ),
            ),
            Expanded(
              child: GridView.builder(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 3,
                  crossAxisSpacing: 6,
                  mainAxisSpacing: 6,
                ),
                itemCount: photos.length,
                itemBuilder: (_, i) => _SupervisionTile(
                  photo: photos[i],
                  onDelete: () => onDeletePhoto(photos[i].id),
                  // 点看大图（09-30）：复用全屏查看页，双指缩放看细节；
                  // 删除按钮在查看页右上角同样可用（M7 流已覆盖监装墙）。
                  onTap: () => _openViewer(context, viewerGroup, i),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  /// 打开监装照片的大图查看（09-30）。
  ///
  /// 复用 [PhotoViewerPage]（与组卡片同一套交互：双指缩放、
  /// 左右翻页、右上角删除）。监装墙在 IndexedStack 下没有
  /// `_openViewer(OpenGroup, int)` 可用（那是 State 的方法，且参数语义
  /// 是"组"），所以这里是独立入口 —— 影子组在 build 时已备好。
  Future<void> _openViewer(
    BuildContext context,
    OpenGroup group,
    int index,
  ) async {
    await Navigator.of(context).push<int>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => PhotoViewerPage(
          projectId: projectId,
          group: group,
          initialIndex: index,
          groupLabel: '监装照片',
        ),
      ),
    );
  }

  static Future<void> _markAllBackToPrecheck(
    BuildContext context,
    WidgetRef ref,
    List<GroupPhotoThumb> photos,
  ) async {
    // messenger 必须在 await 之前取好 —— 跨 async 之后再碰 context
    // 会触发 use_build_context_synchronously，而且那时它可能已经失效。
    final messenger = ScaffoldMessenger.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('全部改回预检？'),
        content: Text(
          '${photos.length} 张监装照片会回到「预检」，'
          '重新参与编码对应与箱号分组。',
          style: const TextStyle(fontSize: 13.5, height: 1.6),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppTheme.accent),
            child: const Text('改回预检'),
          ),
        ],
      ),
    );
    if (ok != true) return;

    try {
      await ref.read(organizeRepositoryProvider).setPhotosCategory(
            photos.map((p) => p.id).toList(),
            PhotoCategory.precheck,
          );
      if (!context.mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text('已把 ${photos.length} 张改回预检')),
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('操作失败：$e')));
    }
  }
}

/// 监装空态 —— 说清楚"监装是什么、怎么来的"。
class _SupervisionEmpty extends StatelessWidget {
  const _SupervisionEmpty();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.blueBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.blue.withValues(alpha: 0.25)),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.local_shipping_outlined, size: 17, color: AppTheme.blue),
              SizedBox(width: 8),
              Text(
                '还没有监装照片',
                style: TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.blue,
                ),
              ),
            ],
          ),
          SizedBox(height: 8),
          Text(
            '装柜时拍的照片（空箱 / 半载 / 满载 / 封条 / 车号）'
            '都属于这一类。\n\n'
            '怎么标：到「预检」页，在某一组照片上点「标为监装」—— '
            '整组就过来了。标错了随时能改回。\n\n'
            '监装照片不与货品编码对应，交付时全部放进「监装」文件夹。',
            style: TextStyle(
              fontSize: 12,
              color: AppTheme.navy,
              height: 1.7,
            ),
          ),
        ],
      ),
    );
  }
}

class _SupervisionTile extends StatelessWidget {
  const _SupervisionTile({required this.photo, this.onDelete, this.onTap});

  final GroupPhotoThumb photo;

  /// 逐张删除（M7）：非 null 时在右上角显示删除按钮。
  final VoidCallback? onDelete;

  /// 点按看大图（老板 2026-09-30 拍板：监装照片要允许查看大图）。
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final p = photo.thumbPath;
    final img = p == null
        ? const Icon(Icons.image_outlined, size: 22, color: AppTheme.textMuted)
        : Image.file(
            File(p),
            fit: BoxFit.cover,
            filterQuality: FilterQuality.low,
            gaplessPlayback: true,
            // 照片墙网格：按 2 倍显示宽度解码（09-29 性能排查）
            cacheWidth: 220,
            errorBuilder: (_, __, ___) => const Icon(
              Icons.broken_image_outlined,
              size: 20,
              color: AppTheme.textMuted,
            ),
          );

    final tile = ClipRRect(
      borderRadius: BorderRadius.circular(7),
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Container(
          color: AppTheme.bg,
          child: img,
        ),
      ),
    );

    if (onDelete == null) return tile;

    // 右上角叠一个红色删除按钮（M7）
    return Stack(
      fit: StackFit.expand,
      clipBehavior: Clip.none,
      children: [
        tile,
        Positioned(
          top: 3,
          right: 3,
          child: GestureDetector(
            onTap: onDelete,
            behavior: HitTestBehavior.opaque,
            child: Container(
              decoration: BoxDecoration(
                color: AppTheme.red,
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white, width: 1.5),
              ),
              padding: const EdgeInsets.all(2.5),
              child: const Icon(Icons.close, size: 12, color: Colors.white),
            ),
          ),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 箱号（用户指定）
// ═══════════════════════════════════════════════════════════════

/// 「指定箱号」面板：输入新箱号 + 选已用过的箱号 + 清除。
///
/// 返回：新箱号字符串（'' = 清除），null = 取消。
class _CartonSheet extends ConsumerStatefulWidget {
  const _CartonSheet({
    required this.projectId,
    required this.current,
    required this.photoCount,
  });

  final String projectId;
  final String? current;
  final int photoCount;

  @override
  ConsumerState<_CartonSheet> createState() => _CartonSheetState();
}

class _CartonSheetState extends ConsumerState<_CartonSheet> {
  late final TextEditingController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: widget.current ?? '');
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final used = ref.watch(cartonsProvider(widget.projectId));
    final list = used.valueOrNull ?? const <String>[];
    final bottom = MediaQuery.of(context).viewInsets.bottom;

    return Padding(
      padding: EdgeInsets.fromLTRB(16, 14, 16, 16 + bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.inventory_2_outlined,
                  size: 18, color: AppTheme.accent),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '指定箱号（${widget.photoCount} 张）',
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.navy,
                  ),
                ),
              ),
              IconButton(
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close, size: 20),
                visualDensity: VisualDensity.compact,
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            '箱号由你指定，不看清单。交付时这组照片会放进这个箱号的文件夹。',
            style: TextStyle(
              fontSize: 11.5,
              color: AppTheme.textMuted,
              height: 1.6,
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _ctrl,
            autofocus: widget.current == null,
            textInputAction: TextInputAction.done,
            decoration: const InputDecoration(
              hintText: '例如：箱A / BOX-0012',
              isDense: true,
              border: OutlineInputBorder(),
            ),
            onSubmitted: (v) => Navigator.of(context).pop(v.trim()),
          ),
          if (list.isNotEmpty) ...[
            const SizedBox(height: 10),
            const Text(
              '本项目已用过的箱号',
              style: TextStyle(fontSize: 11.5, color: AppTheme.textMuted),
            ),
            const SizedBox(height: 6),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                for (final c in list)
                  ActionChip(
                    label: Text(c),
                    onPressed: () => Navigator.of(context).pop(c),
                  ),
              ],
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              if (widget.current != null)
                TextButton(
                  onPressed: () => Navigator.of(context).pop(''),
                  child: const Text('清除箱号'),
                ),
              const Spacer(),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(_ctrl.text.trim()),
                style: FilledButton.styleFrom(
                  backgroundColor: AppTheme.accent,
                ),
                child: const Text('确定'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
