import '../search/code_norm.dart';

/// 一条照片检索命中（2026-10-15 v0.24.0「按编码搜历史照片」）。
///
/// 住在 `domain/model/` 而不是 data 层 —— UI 层不得 import `lib/data/`
/// （tools/check_architecture.ps1 规则 2），这条已经踩过三次。
///
/// 全部字段 final，本类天然不可变（不引 flutter 的 @immutable ——
/// domain 层不该依赖 Flutter，架构检查按目录分层）。
class PhotoSearchHit {
  /// 构造一条命中。
  const PhotoSearchHit({
    required this.photoId,
    required this.projectId,
    required this.projectName,
    required this.filePath,
    required this.takenAtMs,
    required this.matchedCode,
    required this.source,
    required this.kind,
    this.groupId,
    this.groupSeq,
    this.thumbPath,
  });

  /// 照片 id。
  final String photoId;

  /// 所属项目 id（深链回项目用）。
  final String projectId;

  /// 所属项目名（结果卡片要显示，否则跨项目搜出来分不清是谁的）。
  final String projectName;

  /// 原图路径 —— 大图查看用。列表只准读 [thumbPath]。
  final String filePath;

  /// 拍摄时刻（毫秒）。同分时按它倒序（新照片在前）。
  final int takenAtMs;

  /// **命中的那个编码原文**（如 `ABC-123`）。
  ///
  /// 存原文而不是规范化后的串：显示给人看的是唛头上的写法，
  /// 而高亮需要原文下标（见 `highlightRangeInRaw`）。
  final String matchedCode;

  /// 这条编码是哪来的（决定可信度与徽标）。
  final PhotoSearchSource source;

  /// 命中方式（精确 / 后缀 / 前缀 / 包含）—— 排序键之一。
  final CodeMatchKind kind;

  /// 所在组 id。游离照片为 null。
  final String? groupId;

  /// 组序号（显示「第 N 组」用）。
  final int? groupSeq;

  /// 缩略图路径。还没生成出来时为 null（UI 显示占位）。
  final String? thumbPath;

  /// 排序分：来源权重 × 10 + 命中方式权重。大者在前。
  int get score => source.weight * 10 + kind.weight;
}

/// 命中编码的**来源**。权威度不同，UI 必须标注出来。
enum PhotoSearchSource {
  /// 归属编码 —— 人在整理阶段确认过的（`photos.itemId` → `items.code`）。
  ///
  /// 权威：这张照片属于这个编码，是人的决定。
  assigned,

  /// 建议编码 —— 组的 AI 建议（`photo_groups.suggestedItemId` → 码），
  /// 人**没有**确认过。可能是错的。
  suggested,

  /// OCR 识别码 —— 照片上识别出来的文本。可能误识。
  ocr,
}

/// 来源的可信度权重（用于排序，大 = 更可信）。
extension PhotoSearchSourceWeight on PhotoSearchSource {
  /// assigned 3 / suggested 2 / ocr 1。
  int get weight => switch (this) {
        PhotoSearchSource.assigned => 3,
        PhotoSearchSource.suggested => 2,
        PhotoSearchSource.ocr => 1,
      };

  /// 结果卡片上的徽标文案。权威来源不标（没标 = 已确认）。
  String? get badge => switch (this) {
        PhotoSearchSource.assigned => null,
        PhotoSearchSource.suggested => '建议',
        PhotoSearchSource.ocr => 'OCR',
      };
}
