import 'enums.dart';

/// 项目列表页与工作台共用的聚合视图。
///
/// 三段式进度是 v3.0 的门面 —— 列表页每张卡都要显示它（§4.2 P1），
/// 工作台则用同一份数据决定"你现在该去哪一步"（§4.2 P2）。
class ProjectSummary {
  const ProjectSummary({
    required this.id,
    required this.name,
    required this.client,
    required this.createdAt,
    required this.status,
    required this.itemTotal,
    required this.itemDone,
    required this.photoTotal,
    required this.photoConfirmed,
    required this.photoUnassigned,
    required this.photoOrphan,
    required this.groupPending,
  });

  final String id;
  final String name;
  final String? client;
  final DateTime createdAt;
  final ProjectStatus status;

  /// 清单货品总数
  final int itemTotal;

  /// 已有照片的货品数
  final int itemDone;

  // ── 阶段 ① 采集的进度由 photoTotal 表达 ──
  final int photoTotal;

  /// 已确认归属的照片
  final int photoConfirmed;

  /// 还没指派归属的照片（photos.state = 'unassigned'）。
  ///
  /// ⚠️ 口径注意（2026-10-15 老板"多处统计数对不上"）：预检流程里
  /// 照片**入了组也算 unassigned** —— 归属确认才写 state。所以这个数
  /// 回答的是「确认进度」，不能当「没整理的照片」用；后者看
  /// [photoOrphan]。交付就绪与 organizeDone 用它是对的（确认了才算完）。
  final int photoUnassigned;

  /// **没进任何组**的预检照片（group_id IS NULL）。
  ///
  /// 真正的"散着没人管"口径 —— 已入组的照片由 [groupPending] 代表待办，
  /// 不在这里重复计数（角标 6 组 + 19 张 = 25 的重复计量事故就出在
  /// 把两者相加上）。监装照片无组语义，刻意不算（2026-10-15）。
  final int photoOrphan;

  /// 待人工确认的组数（"待处理"）
  final int groupPending;

  // ─────────────────────────────────────────────────────────

  /// 整理阶段是否已清零。清零后交付 Tab 才亮起引导。
  bool get organizeDone => photoUnassigned == 0 && groupPending == 0;

  /// 清单缺口：有货品但没照片
  int get itemGap => (itemTotal - itemDone).clamp(0, itemTotal);

  bool get hasAnyPhoto => photoTotal > 0;

  /// 0.0~1.0，用于列表页的微型进度条
  double get organizeProgress {
    if (itemTotal == 0) return 0;
    return (itemDone / itemTotal).clamp(0.0, 1.0);
  }

  /// 一句话告诉用户"现在该干什么"（工作台主按钮文案 + Tab 高亮依据）。
  String get nextActionLabel {
    if (itemTotal == 0) return '导入货品清单';
    if (!hasAnyPhoto) return '开始采集';
    if (!organizeDone) return '继续整理（待处理 $groupPending 组）';
    return '生成交付包';
  }
}
