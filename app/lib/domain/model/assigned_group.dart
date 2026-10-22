import 'enums.dart';
import 'open_group.dart';

/// 整理页「已指派」视图的组投影（P4 · 真机反馈修复）。
///
/// ═══════════════════════════════════════════════════════════════
/// 为什么是独立类型而不是给 [OpenGroup] 加字段：
///
///   v3.1 的「只显示缺口」把已确认的组从待办流里**整个拿掉了**，
///   这在类型上就是自洽的 —— [OpenGroup] 里没有归属字段，UI 想表达
///   「已归属」也无从表达。真机实测（2026-09-24）暴露了它的另一面：
///   指派错了想改，人却**找不到那组照片在哪**。
///
///   修法不是把归属塞回 [OpenGroup]（那会让「建议投影」和「归属投影」
///   两种语义搅在同一个类型里），而是给「已指派」这个视图一个自己的
///   投影：只带 UI 要展示的字段。两个视图，两个类型，边界清晰。
/// ═══════════════════════════════════════════════════════════════
///
/// ⚠️ 本类型是**只读投影**：修改归属的唯一写入口仍然是
///    [AssignService]（revokeGroup / confirmGroup），UI 拿它只做展示
///    与发起动作，绝不直接写库（架构规则 3）。
class AssignedGroup {
  const AssignedGroup({
    required this.groupId,
    required this.seq,
    required this.takenAtMs,
    required this.itemId,
    required this.itemCode,
    this.itemName,
    this.containerSummary,
    required this.confirmedAtMs,
    // ── 部类与箱号（老板 2026-09-27 拍板）──
    this.category = PhotoCategory.precheck,
    this.carton,
    this.photos = const [],
  });

  final String groupId;
  final int seq;
  final int takenAtMs;

  /// 归属货品（AssignService 写入的那条记录）。
  final String itemId;
  final String itemCode;
  final String? itemName;

  /// 货品所在包装箱汇总（M5.1 · 老板 09-26 拍板：整理按箱号分组）。
  /// 同一件货分散多箱时形如「箱A、箱B」；null = 清单没提供箱号。
  final String? containerSummary;

  /// 归属确认时刻（毫秒）。列表里显示「几点指派的」。
  final int confirmedAtMs;

  /// 部类（预检 / 监装）。已指派视图按它分流 ——
  /// 监装的组不该出现在"预检待办"里（它本来就不需要对应编码）。
  final PhotoCategory category;

  /// **用户指定**的箱号（不是清单里的 containerSummary）。
  /// 交付时按它建文件夹；null / 空 = 进 `_未分箱/`。
  final String? carton;

  /// 组内照片（按拍摄时间升序，缩略图投影，与 [OpenGroup.photos] 同构）。
  final List<GroupPhotoThumb> photos;

  int get photoCount => photos.length;

  String? get coverThumbPath =>
      photos.isEmpty ? null : photos.first.thumbPath;

  /// 「已指派 X 张照片」的副标题。
  String get subtitle => '已指派 · $photoCount 张照片';

  /// 全屏查看页要的是一个 [OpenGroup]（它只用 photos / seq / takenAtMs）。
  ///
  /// 这里构造一个**纯展示用**的 OpenGroup：不带任何建议字段，
  /// 也不代表该组回到了待办流 —— 只是借它走 PhotoViewerPage。
  OpenGroup toOpenGroup() => OpenGroup(
        groupId: groupId,
        seq: seq,
        takenAtMs: takenAtMs,
        photos: photos,
        category: category,
        carton: carton,
      );
}
