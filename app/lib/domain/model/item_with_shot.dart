/// 货品 + 已拍张数（列表投影）。
///
/// 住在 `domain/model/` 的原因（架构规则 2 / 历史教训同
/// [DeliveryReadiness]、PhotoThumb）：UI（指派面板、缺口视图）需要
/// **具名引用**这个类型，而 UI 不得 import `data/`。它是只读投影，
/// 没有任何行为依赖数据库句柄，天然属于 domain 层。
///
/// 数据来源：[ItemRepository.watchByProject] / watchGaps /
/// watchUnderShot / search（data 层负责查，本类型只管形状）。
class ItemWithShot {
  const ItemWithShot({
    required this.id,
    required this.seq,
    required this.code,
    required this.codeSafe,
    required this.name,
    required this.spec,
    required this.qty,
    required this.unit,
    required this.requiredPhotos,
    required this.state,
    required this.notFoundReason,
    required this.shotCount,
    this.containerSummary,
    this.sourceLineCount = 1,
  });

  final String id;
  final int seq;
  final String code;
  final String codeSafe;
  final String? name;
  final String? spec;
  final double? qty;
  final String? unit;
  final int requiredPhotos;

  /// ItemState.code
  final String state;
  final String? notFoundReason;
  final int shotCount;

  /// 所在包装箱汇总（P4 诉求 1）。同一件货分散多箱时形如「箱A、箱B」。
  /// null / 空 = 清单没提供箱号信息（多数清单如此）。
  final String? containerSummary;

  /// 这件货由清单里的几行合并而来（P4 诉求 1）。单行货品 = 1。
  final int sourceLineCount;

  String get displayName => (name == null || name!.isEmpty) ? code : name!;

  bool get reachedRequired => shotCount >= requiredPhotos;

  /// 这件货是否散布在多个箱子里（P4 诉求 1 的展示开关）。
  bool get spansMultipleContainers =>
      containerSummary != null && containerSummary!.contains('、');
}
