import 'package:flutter/material.dart';

import '../../app/theme.dart';

/// 三段式进度 —— v3.0 的招牌组件。
///
/// 它同时承担三个职责（§4.1 / §4.2）：
///   1. 让用户永远知道"现在走到哪一段了"
///   2. 让用户知道"还剩多少"（列表页与工作台用同一份数据，数字永远一致）
///   3. 用颜色暗示"下一步该干什么"
///
/// 采集 / 整理 / 交付三段在视觉上必须是**分立的**，
/// 不允许做成一条连续的进度条 —— 那会让人以为必须顺序完成才能休息。
class StageProgressBar extends StatelessWidget {
  const StageProgressBar({
    super.key,
    required this.captureRatio,
    required this.organizeRatio,
    required this.deliverDone,
    this.captureLabel,
    this.organizeLabel,
    this.deliverLabel,
    this.activeStage,
  });

  /// 0.0~1.0
  final double captureRatio;
  final double organizeRatio;
  final bool deliverDone;

  final String? captureLabel;
  final String? organizeLabel;
  final String? deliverLabel;

  /// 0/1/2 = 采集/整理/交付；传 null 表示不强调任何一段
  final int? activeStage;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _StageChip(
            index: 1,
            title: '采集',
            label: captureLabel ?? '${(captureRatio * 100).round()}%',
            ratio: captureRatio,
            color: AppTheme.navy,
            active: activeStage == 0,
          ),
        ),
        const SizedBox(width: 6),
        Expanded(
          child: _StageChip(
            index: 2,
            title: '整理',
            label: organizeLabel ?? '${(organizeRatio * 100).round()}%',
            ratio: organizeRatio,
            color: AppTheme.accent,
            active: activeStage == 1,
          ),
        ),
        const SizedBox(width: 6),
        Expanded(
          child: _StageChip(
            index: 3,
            title: '交付',
            label: deliverLabel ?? (deliverDone ? '已完成' : '未开始'),
            ratio: deliverDone ? 1 : 0,
            color: AppTheme.green,
            active: activeStage == 2,
          ),
        ),
      ],
    );
  }
}

class _StageChip extends StatelessWidget {
  const _StageChip({
    required this.index,
    required this.title,
    required this.label,
    required this.ratio,
    required this.color,
    required this.active,
  });

  final int index;
  final String title;
  final String label;
  final double ratio;
  final Color color;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final r = ratio.clamp(0.0, 1.0);
    return Container(
      padding: const EdgeInsets.fromLTRB(8, 6, 8, 7),
      decoration: BoxDecoration(
        color: active ? color.withValues(alpha: 0.06) : Colors.transparent,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(
          color: active ? color.withValues(alpha: 0.5) : AppTheme.line,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '$index',
                style: TextStyle(
                  fontSize: 9.5,
                  fontWeight: FontWeight.w800,
                  color: color,
                  letterSpacing: 0.5,
                ),
              ),
              const SizedBox(width: 4),
              Text(
                title,
                style: TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w700,
                  color: active ? color : AppTheme.textMain,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: LinearProgressIndicator(
              value: r,
              minHeight: 3.5,
              backgroundColor: AppTheme.line,
              valueColor: AlwaysStoppedAnimation<Color>(color),
            ),
          ),
          const SizedBox(height: 3),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 10, color: AppTheme.textMuted),
          ),
        ],
      ),
    );
  }
}

/// 缺口语义的小标签。用于"缺口 / 清单外 / 张数不足"这类状态。
class StageBadge extends StatelessWidget {
  const StageBadge({
    super.key,
    required this.text,
    this.color = AppTheme.textMuted,
    this.background,
    this.icon,
  });

  final String text;
  final Color color;
  final Color? background;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: background ?? color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 11, color: color),
            const SizedBox(width: 3),
          ],
          Text(
            text,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

/// 空状态。现场工具的空状态必须**直接告诉人下一步点哪里**，
/// 而不是只画一个插画。
class StageEmptyState extends StatelessWidget {
  const StageEmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.hint,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String hint;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 48),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 46, color: AppTheme.line),
            const SizedBox(height: 14),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: AppTheme.navy,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              hint,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 13,
                color: AppTheme.textMuted,
                height: 1.6,
              ),
            ),
            if (actionLabel != null && onAction != null) ...[
              const SizedBox(height: 20),
              FilledButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}
