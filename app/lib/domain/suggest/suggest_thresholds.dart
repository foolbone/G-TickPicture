/// 建议合成的全部阈值 —— **只在这一个文件里，调优不动算法**。
///
/// 语义（§5.3.2 的 v3.0 约定）：这些阈值**不决定归不归属**，
/// 只决定「排在多前」「要不要标冲突」。机器永远写不了 itemId。
abstract final class SuggestThresholds {
  /// 组级平均分低于它 → no_suggestion（不给建议，必须手动指派）。
  static const double minConfidence = 0.40;

  /// 第二名与胜者的平均分差小于它 → conflict（提醒人看一眼）。
  static const double conflictGap = 0.15;

  /// 进「一键确认高置信」候选列表的门槛（§5.4 S1：≥0.90 且组内一致）。
  /// 注意：进了列表也不自动执行 —— 弹出的是可复核列表，确认的人是用户。
  static const double bulkConfirmConfidence = 0.90;
}

/// 位置权重的量化（§5.3.2 第 5 步）。
///
/// 设计只给了两端：中心/大字号 1.0，边缘 0.85。中间线性插值。
/// 「大字号」权重留作调优项（第一版只用中心距 —— 编码通常印在包装
/// 正面中心区，中心距已能拉开主要差距；加字号需要字体高度基线，等
/// 真实标签样本到了再标定）。
abstract final class SuggestWeights {
  /// 中心区（归一化中心偏移 ≤ [edgeStart]）不打折。
  static const double edgeStart = 0.25;

  /// 归一化中心偏移 ≥ [edgeFull] 按边缘算（0.85）。
  static const double edgeFull = 0.45;

  /// 边缘折扣（设计值）。
  static const double edgeFactor = 0.85;

  /// 从归一化坐标（中心点相对整图的比例位置）算权重。
  ///
  /// [cx] / [cy] ∈ [0,1]；越接近 0.5 越靠中心。
  /// 信息缺失（无法定位）→ 1.0 —— **未知不打折**（unknown 沉默原则）。
  static double positionWeight({required double cx, required double cy}) {
    final off = (cx - 0.5).abs() > (cy - 0.5).abs()
        ? (cx - 0.5).abs()
        : (cy - 0.5).abs();
    if (off <= edgeStart) return 1.0;
    if (off >= edgeFull) return edgeFactor;
    final t = (off - edgeStart) / (edgeFull - edgeStart);
    return 1.0 - t * (1.0 - edgeFactor);
  }
}
