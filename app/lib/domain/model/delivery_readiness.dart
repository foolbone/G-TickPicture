/// 交付就绪度快照 —— 交付页的只读视图模型。
///
/// 属于**领域模型**，不属于数据层。
/// 放在这里的原因：UI 层不得直接 import `lib/data/`（见 tools/check_architecture.ps1 规则 2），
/// 而 UI 需要具名引用这个类型，所以它必须住在 `domain/model/`。
library;

class DeliveryReadiness {
  const DeliveryReadiness({
    required this.orphanPhotoAssignments,
    required this.orphanGroupAssignments,
    required this.itemTotal,
    required this.itemGap,
    required this.photoUnassigned,
    required this.photoConfirmed,
    required this.photoUnused,
  });

  /// 期望 0（不变式）：不存在「有归属但没有确认记录」的照片
  final int orphanPhotoAssignments;

  /// 期望 0（不变式）：不存在「有归属但没有确认时间」的组
  final int orphanGroupAssignments;

  /// 清单内货品总数
  final int itemTotal;

  /// 清单里还没有照片的货品数（缺口）
  final int itemGap;

  /// 还没被指派的照片
  final int photoUnassigned;

  /// 已确认归属的照片
  final int photoConfirmed;

  /// 标记为「本张不用」的照片
  final int photoUnused;

  /// 归属完整性健康度（老板 2026-09-26 拍板：交付**不设限制条件**）。
  ///
  /// false 不再拦截打包 —— 只代表检测到归属记录异常（正常操作造不出来，
  /// 通常意味着数据被绕开 AssignService 改过）。打包继续进行，
  /// 异常数写进 manifest 留痕；UI 用它把按钮前换成一次确认弹窗防误触。
  bool get canDeliver =>
      orphanPhotoAssignments == 0 && orphanGroupAssignments == 0;

  bool get hasWarnings => itemGap > 0 || photoUnassigned > 0;
}
