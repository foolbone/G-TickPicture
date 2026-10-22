import '../search/code_matcher.dart';

/// OCR 建议服务 —— **M4 落地**。
///
/// ═══════════════════════════════════════════════════════════════
/// 这个类的全部职责边界，用一句话说清：
///
///   **它写 `suggested_item_id`，永远不写 `item_id`。**
///
/// 这不是纪律要求，是类型系统层面的事实 ——
/// 本接口没有任何一个方法接收 `itemId` 参数。
/// 归属只能由 [AssignService] 写入，且必须带 `confirmedBy`。
/// ═══════════════════════════════════════════════════════════════
///
/// 为什么要有这个接口而不是直接调 ML Kit：
///   1. 它必须能**整体关闭**（设置里的一个开关），关闭后其余流程零变化
///   2. 它必须能**降级**（ML Kit 初始化失败/机型不支持 → 无建议模式）
///   3. 它跑在**采集结束之后**，不占用现场的任何一毫秒
abstract interface class SuggestService {
  /// 是否可用。false 时整理页不显示任何建议，全部走手动指派。
  bool get isEnabled;

  /// 用户是否在设置里关掉了建议功能。
  bool get isDisabledByUser;

  /// 全量预处理：对项目里所有 `ocr_state = pending` 的照片跑识别，
  /// 然后合成组级建议。
  ///
  /// 要求（§5.3.3）：
  ///   · 可中断、可续跑（进度落在 photos.ocr_state 上）
  ///   · 已完成的组立即可操作，不做全屏阻塞
  ///   · 返回一个可监听的进度流，供整理页顶部的进度条使用
  Stream<SuggestProgress> runForProject(String projectId);

  /// 单张重试（用户在整理页点"重新识别"时用）。
  Future<void> retryPhoto(String projectId, String photoId);

  /// 关闭/开启建议功能。关闭后应清空所有 `suggested_*` 字段吗？
  ///
  /// **不清空。** 只把 `suggest_state` 置为 `none`，让 UI 不显示。
  /// 重新打开时立即恢复 —— 避免用户来回切一次就丢掉十几分钟的识别结果。
  Future<void> setDisabledByUser(bool disabled);
}

/// 预处理进度。
class SuggestProgress {
  const SuggestProgress({
    required this.total,
    required this.done,
    required this.groupsPending,
    required this.groupsConflict,
    required this.groupsNoSuggestion,
  });

  final int total;
  final int done;

  /// 有建议、待人工确认
  final int groupsPending;

  /// 组内识别分歧
  final int groupsConflict;

  /// 无建议（需手动指派）
  final int groupsNoSuggestion;

  double get ratio => total == 0 ? 0 : (done / total).clamp(0.0, 1.0);
  bool get finished => done >= total;
}

/// 组级建议合成（§5.3.2）。
///
/// 已在设计方案里给出完整算法，实现放 M4。
/// 这里先把**输入输出的形状**固定下来，避免 M4 时又改数据模型。
class GroupSuggestion {
  const GroupSuggestion({
    required this.itemId,
    required this.confidence,
    required this.candidates,
    required this.evidence,
    required this.state,
  });

  const GroupSuggestion.none()
      : itemId = null,
        confidence = 0,
        candidates = const [],
        evidence = const [],
        state = 'no_suggestion';

  /// 最佳候选。null 表示完全没识别出可用编码。
  final String? itemId;

  /// 0.0~1.0，用于**排序与标冲突**，不用于自动归档。
  final double confidence;

  /// 前 3 个候选，按分数降序 —— 整理页"改派"面板直接用它排序。
  final List<MatchCandidate> candidates;

  /// 命中依据，例如 ["#1:exact(0.95)", "#2:prefix(0.81)"]。
  /// UI 上点开"为什么这么建议"时展示。
  final List<String> evidence;

  /// GroupSuggestState.code
  final String state;

  /// 打包成 `photo_groups.suggestion_json`。
  Map<String, Object?> toJson() => {
        'itemId': itemId,
        'confidence': confidence,
        'state': state,
        'evidence': evidence,
        'candidates': candidates
            .map((c) => {
                  'itemId': c.itemId,
                  'score': c.score,
                  'mode': c.mode,
                })
            .toList(),
      };
}
