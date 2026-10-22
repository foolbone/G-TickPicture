import 'enums.dart';

/// 整理页的组视图模型（M3 数据形状 + M4 建议字段）。
///
/// 属于**领域模型**而非数据层 —— UI 层不得 import `lib/data/`
/// （tools/check_architecture.ps1 规则 2），UI 需要具名引用的类型
/// 必须住在 `domain/model/`（这条已经因 DeliveryReadiness / PhotoThumb
/// 踩过两次，第三次直接放对地方）。
///
/// ═══════════════════════════════════════════════════════════════
/// 权限边界（M4 更新）：
///   · **建议字段**（suggestedItemId / suggestionConf / suggestState /
///     evidence）是 SuggestPipeline 的产出，进 UI 是设计方案的明文承诺
///     （§5.3.2：建议必须可解释）。
///   · **归属字段仍然不存在** —— 本模型没有任何"已归属"的信息，
///     已确认的组根本不会出现在这条流里（§5.4：只看剩下的）。
///     UI 能表达的动作只有"确认这个建议"或"手动指派"，
///     写 itemId 的路径仍然只有 AssignService 一条。
/// ═══════════════════════════════════════════════════════════════
///
/// M3 的版本在类型上没有建议字段（当时建议尚不存在）；
/// M4 按设计方案 §5.3.2 的预告"以另一个字段进 UI"，而不是提前塞占位 null。
class OpenGroup {
  const OpenGroup({
    required this.groupId,
    required this.seq,
    required this.takenAtMs,
    required this.photos,
    this.suggestedItemId,
    this.suggestedCode,
    this.suggestedName,
    this.suggestionConf,
    this.suggestState = GroupSuggestState.none,
    this.evidence = const [],
    this.ocrPendingCount = 0,
    this.ocrFailedCount = 0,
    // ── 部类与箱号（老板 2026-09-27 拍板）──
    this.category = PhotoCategory.precheck,
    this.carton,
  });

  final String groupId;

  /// 项目内的组序号（建组落库时分配，递增）。
  final int seq;

  /// 首张拍摄时刻（毫秒）。**组在列表里的排序键** ——
  /// 与现场走动的顺序一致，人的记忆按时间组织。
  final int takenAtMs;

  /// 组内照片（按拍摄时间升序）。
  final List<GroupPhotoThumb> photos;

  // ── 建议层（SuggestPipeline 写入，AssignService 在确认时消费） ──

  /// 建议的货品 id。null = 没有建议。
  final String? suggestedItemId;

  /// 建议货品的编码（清单原文，显示用）。
  final String? suggestedCode;

  /// 建议货品的品名（清单可能没填 → null）。
  final String? suggestedName;

  /// 组级置信度 0.0~1.0。只用于**排序与展示**，不做自动归档线。
  final double? suggestionConf;

  /// 建议质量状态（§5.3.2：conflict 照给建议但提醒人看一眼）。
  final GroupSuggestState suggestState;

  /// 命中依据，形如 `['张1:exact(0.98)', '张2:exact(0.97)']`。
  /// UI 上点"为什么这么建议"时展示 —— 建议必须可解释（§3 原则 7）。
  final List<String> evidence;

  // ── 组内 OCR 进度（P4 · 真机反馈：失败必须可见，不能和"没匹配到"混说）──

  /// 组内还在排队识别的照片数。> 0 表示识别还没跑完这一组。
  final int ocrPendingCount;

  // ── 部类（预检 / 监装）与箱号（老板 2026-09-27 拍板）─────────────
  //
  // 这两个字段**不是归属**：它们不决定"这组照片属于哪件货"，
  // 只决定"它们在交付包里放在哪个文件夹"。因此：
  //   · 可以在整理页由人直接改（不必经 AssignService）；
  //   · 但改的时候必须同步组内照片的 category（一致性由仓储保证）。
  //
  // 箱号由**人输入**，不看清单的 containerSummary —— 老板拍板：
  // 「分组时由用户输入或指定箱号，不依赖货品清单」。

  /// 部类。默认预检 —— 老数据与未分类的组都按预检走，交付不丢照片。
  final PhotoCategory category;

  /// **用户指定**的箱号。null / 空 = 还没指定 → 交付时进 `_未分箱/`。
  /// 监装照片不看这个字段（监装不分箱，全部进一个文件夹）。
  final String? carton;

  /// 组内识别**失败**的照片数（管道单张失败不终止的产物）。
  ///
  /// > 0 时组建议永远不会合成（组没"全部完成"），界面上的
  /// 「未识别到清晰编码」必须换成失败提示，否则人会把
  /// "识别崩了"误读成"照片里没有编码"。
  final int ocrFailedCount;

  int get photoCount => photos.length;

  /// 只有 1 张的组。§5.4 的提示信号（可能漏拍/该货只有一处可拍），
  /// 仅用于 UI 提示，不做任何自动决策。
  bool get looksUnderShot => photos.length < 2;

  /// 有可用建议（待确认状态且有对应货品）。
  bool get hasSuggestion =>
      suggestState == GroupSuggestState.pending &&
      suggestedItemId != null &&
      suggestedCode != null;

  /// 组内识别不一致 —— 建议照给，但 UI 必须引导人工核对。
  bool get isConflict => suggestState == GroupSuggestState.conflict;

  /// 没识别出可用编码 → 只能手动指派。
  bool get isNoSuggestion =>
      suggestState == GroupSuggestState.noSuggestion || suggestedItemId == null;

  /// 这组是**监装**照片（装柜过程，与清单无关、不分箱）。
  bool get isSupervision => category == PhotoCategory.supervision;

  /// 是否已指定箱号。空串当没指定 —— 输入框里只打了个空格不算。
  bool get hasCarton => (carton ?? '').trim().isNotEmpty;

  /// 首张缩略图路径（卡片封面）。
  String? get coverThumbPath =>
      photos.isEmpty ? null : photos.first.thumbPath;
}

/// 组内一张照片的最小投影。
class GroupPhotoThumb {
  const GroupPhotoThumb({
    required this.id,
    required this.takenAtMs,
    required this.thumbPath,
    this.originalPath,
  });

  final String id;

  /// 拍摄时刻（毫秒）。组内排序与组间排序都靠它。
  final int takenAtMs;

  /// 256px 缩略图路径。null = 还没生成（异步补图未跑完），
  /// UI 必须能画占位块。**UI 只允许读缩略图**（R1b：绝不解码原图）。
  final String? thumbPath;

  /// 原图路径（P4 诉求 2 新增）。
  ///
  /// ⚠️ **只有一个合法用途：全屏单张查看页**（`PhotoViewerPage`）。
  /// 那里的尺寸是"一次一张"，解码一张原图是可接受的。
  ///
  /// **绝对禁止**在列表 / 胶片条 / 拖拽 feedback 里用它 ——
  /// 一天上千张照片，列表里解码原图会把内存和 UI 线程一起拖死
  /// （R1b 的教训）。列表一律用 [thumbPath]。
  final String? originalPath;
}
