/// 「一键确认高置信」预览面板的一行（M4 / §5.4 S3）。
///
/// 住在 domain/model/ 而不是 data/ —— UI 需要具名引用的类型
/// 必须能被 UI 层 import（架构规则 2，DeliveryReadiness / PhotoThumb /
/// OpenGroup 三次实证后放对的第四个）。
///
/// 注意：这是**预览投影**，不是归属 —— 执行仍然走
/// [AssignService.bulkConfirmHighConfidence]，每组都过 confirmGroup
/// 的事务与决策记录，一个都不会被绕过。
class BulkConfirmCandidate {
  const BulkConfirmCandidate({
    required this.groupId,
    required this.itemId,
    required this.code,
    required this.name,
    required this.confidence,
    required this.photoCount,
  });

  final String groupId;
  final String itemId;

  /// 清单编码（显示用，永不改写原文）。
  final String code;

  /// 品名（清单没填时为空串）。
  final String name;

  /// 组级置信度 0.0~1.0。
  final double confidence;

  /// 组内张数。
  final int photoCount;
}
