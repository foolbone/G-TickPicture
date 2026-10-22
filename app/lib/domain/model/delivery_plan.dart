/// 交付计划 —— 打包前的完整「账本」。
///
/// 这是 M5 的核心数据结构：在真正写文件之前，先把
/// **哪些照片进包 / 每张叫什么名 / 它属于哪件货 / 哪些货没有照片**
/// 全部算出来，形成一个纯数据快照。
///
/// 为什么要有这一层（而不是在 ExportService 里边查边写）：
///   1. **可测**：计划是纯函数产物，给它一份数据就能断言命名与缺口，
///      不需要真的建 ZIP、不需要碰文件系统。
///   2. **可预检**：体积估算、空间校验、闸门判定都基于计划，
///      写完才发现空间不够是最糟的顺序。
///   3. **可审**：manifest.json 是计划的直接投影，不会与包内目录不一致。
///
/// 层级：`domain/model/` —— UI 需要具名引用它（交付页预览），
/// 而 UI 不得 import `lib/data/`（架构约束规则 2）。
library;

import 'enums.dart';

/// 一件货在交付包里的呈现。
class DeliveryItem {
  const DeliveryItem({
    required this.itemId,
    required this.seq,
    required this.code,
    required this.codeSafe,
    required this.name,
    required this.spec,
    required this.containerSummary,
    required this.state,
    required this.requiredPhotos,
    required this.photos,
    this.carton,
  });

  final String itemId;

  /// 清单行序（1 起）—— 平铺命名里的 3 位序号来源
  final int seq;
  final String code;
  final String codeSafe;
  final String? name;
  final String? spec;

  /// 所在包装箱汇总（P4 诉求 1）。同一件货分散多箱时形如「箱A、箱B」
  /// 顿号连接；null / 空 = 清单没提供箱号。
  ///
  /// ⚠️ 2026-09-27 起它**只作为清单信息保留**，不参与分箱：
  /// 老板拍板「分组时，由用户输入或指定箱号，不依赖货品清单」。
  /// 分箱目录看 [carton]。
  final String? containerSummary;

  /// **用户指定**的箱号（这组照片在整理时归到的箱）。
  ///
  /// 这是交付目录名的来源。null / 空 = 没指定 → `_未分箱/`。
  /// 取组内第一张照片所在组的箱号（同一件货的照片通常同箱）。
  final String? carton;

  /// ItemState.code
  final String state;
  final int requiredPhotos;

  /// 已确认归属到此货品的照片（按拍摄时间升序）
  final List<DeliveryPhoto> photos;

  String get displayName => (name == null || name!.isEmpty) ? code : name!;

  /// 缺口的货品：清单里有、却没有一张照片。
  ///
  /// 注意：这不等于「现场未见」—— 原因是多样的（货未到/已提走/压垛底/漏拍）。
  bool get isGap => photos.isEmpty && state == 'normal';

  /// 张数未达标（要求 2 张、实际 1 张）。不阻塞交付，仅提醒。
  bool get isUnderShot => photos.isNotEmpty && photos.length < requiredPhotos;
}

/// 一张照片在交付包里的呈现。
class DeliveryPhoto {
  const DeliveryPhoto({
    required this.photoId,
    required this.sourcePath,
    required this.takenAt,
    required this.photoSeq,
    required this.itemSeq,
    required this.codeSafe,
    required this.indexInItem,
    required this.fileName,
    required this.itemCode,
    required this.itemName,
    this.category = PhotoCategory.precheck,
    this.carton,
    this.originalName = '',
  });

  final String photoId;

  /// 原始文件绝对路径。**只读，永不改名**（§6.4）。
  final String sourcePath;

  final int takenAt;

  /// 项目内全局序号（photos.seq）
  final int photoSeq;

  /// 所属货品的清单行序
  final int itemSeq;
  final String codeSafe;

  /// 该货品的第几张（1 起）
  final int indexInItem;

  /// 交付包内的相对路径（含目录）。
  ///
  /// 平铺时就是文件名本身；按箱号分文件夹时形如 `箱A/007_X_01.jpg`
  /// （`_未使用/` 与 `_未分箱/` 同理）。**原始文件永不改名** —— 这只是
  /// 包内副本的路径，与 §6.4 不冲突。
  final String fileName;

  final String itemCode;
  final String? itemName;

  /// 部类（老板 2026-09-27 拍板）：决定它进「预检」还是「监装」。
  ///
  /// 默认 precheck —— 老数据与没归类的照片都按预检处理，
  /// 保证**不丢照片**（默认值选错会丢照片，选保守的那一侧）。
  final PhotoCategory category;

  /// **用户指定**的箱号（整理时输入的那个）。
  ///
  /// ⚠️ 不是清单里的 containerSummary —— 老板拍板：
  /// 「分组时，由用户输入或指定箱号，不依赖货品清单」。
  /// null / 空 = 没指定 → 进 `_未分箱/`。
  final String? carton;

  /// 原始文件名（源路径的 basename）。
  ///
  /// 「有对应的就对应，没有对应的就用原始文件名」—— 对应不上的照片
  /// 保留它拍出来时的名字，报告员还能按时间/相册顺序对照，
  /// 而不是变成一堆看不出来源的序号。
  final String originalName;

  String get displayName =>
      (itemName == null || itemName!.isEmpty) ? itemCode : itemName!;

  /// 是否对应到了货品（对应上了才有 itemCode）。
  bool get isMatched => itemCode.isNotEmpty;
}

/// 计划总账。
class DeliveryPlan {
  const DeliveryPlan({
    required this.projectId,
    required this.projectName,
    required this.client,
    required this.generatedAt,
    required this.items,
    required this.unusedPhotos,
    required this.orphanCount,
    // ── 预检 / 监装 两大部分（老板 2026-09-27 拍板）──
    this.supervisionPhotos = const [],
    this.unmatchedPhotos = const [],
  });

  final String projectId;
  final String projectName;
  final String? client;
  final int generatedAt;

  /// 全部货品（含没有照片的 —— 缺口靠它们算出来）
  final List<DeliveryItem> items;

  /// 标记为"本张不用"的照片（不进交付包，除非勾选"含未使用"）
  ///
  /// 这是**唯一的排除口** —— 老板 09-27 拍板「去掉原来的检查，直接按
  /// 分组打包」之后，只有人显式说"这张不用"的照片才被排除；
  /// 没对应上编码的预检照片照样进包（见 [unmatchedPhotos]）。
  final List<DeliveryPhoto> unusedPhotos;

  /// **监装**照片（装柜过程，与清单无关）。
  ///
  /// 全部进「监装」一个文件夹，用原始文件名 —— 老板拍板：
  /// 「监装照片与货品清单无关，放一个文件夹即可」。
  final List<DeliveryPhoto> supervisionPhotos;

  /// **预检里没能对应上编码**的照片。
  ///
  /// 老板拍板：「能对应则对应，不能对应不影响后面交付」+「没有对应的
  /// 就用原始文件名」。所以它们照样进包，跟着自己的箱号走。
  final List<DeliveryPhoto> unmatchedPhotos;

  /// 归属完整性违规数（期望 0）。>0 表示数据损坏，必须阻断交付。
  final int orphanCount;

  /// 进包的已确认照片（平铺后就是这些文件）
  List<DeliveryPhoto> get photos =>
      [for (final it in items) ...it.photos];

  /// 清单内货品总数
  int get itemTotal => items.where((i) => i.state != 'extra').length;

  /// 清单外货品数（现场发现清单没有的货）
  int get extraCount => items.where((i) => i.state == 'extra').length;

  /// 有照片的货品数
  int get itemDone => items.where((i) => i.photos.isNotEmpty).length;

  /// 缺口货品（清单里有、无照片）
  List<DeliveryItem> get gaps => items.where((i) => i.isGap).toList();

  /// 张数未达标的货品
  List<DeliveryItem> get underShot => items.where((i) => i.isUnderShot).toList();

  int get gapCount => gaps.length;

  /// 进包的正片总数 = 已对应 + 预检未对应 + 监装。
  ///
  /// 三类都是要交付的照片 —— 老板 09-27 拍板后，交付不再要求
  /// "每张都得对上编码"，所以未对应的也要算进来，否则数字会骗人。
  int get photoCount => photos.length + unmatchedPhotos.length + supervisionPhotos.length;

  /// 是否指定过**任意**箱号（用户指定的，不是清单里的）。
  ///
  /// 「按箱号分文件夹」只在有人指定过箱号时生效 —— 一个箱号都没指定
  /// 时自动保持平铺，否则会为"没指定"制造一个装着全部照片的
  /// `_未分箱/` 目录，反而不如平铺。
  bool get hasCartonData =>
      items.any((i) => (i.carton ?? '').trim().isNotEmpty) ||
      unmatchedPhotos.any((p) => (p.carton ?? '').trim().isNotEmpty);

  /// 预检部分（已对应 + 未对应）的照片总数。
  int get precheckPhotoCount => photos.length + unmatchedPhotos.length;

  /// 进包照片的**完整清单**（已对应 + 预检未对应 + 监装）。
  ///
  /// 打包循环只认这一个列表 —— 三堆照片分散在三个字段里，
  /// 逐个遍历很容易漏掉一堆，而漏一堆就等价于"交付少了一批照片"。
  List<DeliveryPhoto> get packagePhotos =>
      [...photos, ...unmatchedPhotos, ...supervisionPhotos];

  /// 清单覆盖率 = 有照片的清单内货品 / 清单内货品总数。
  ///
  /// ⚠️ 这是**业务指标**（达标线 ≥80%，按项目可配），
  /// 不是正确性指标。正确性看 [orphanCount]（必须为 0）。
  double get coverage =>
      itemTotal == 0 ? 0.0 : itemDone / itemTotal;

  /// 归属完整性健康度（老板 2026-09-26 拍板：交付**不设限制条件**，
  /// 不再用它拦截打包）。false = 检测到归属记录异常，打包继续、
  /// [orphanCount] 随 manifest 留痕；UI 据此在打包前弹一次确认框防误触。
  ///
  /// 与 [coverage] 严格区分：覆盖率是业务指标，从来不阻塞交付。
  bool get canDeliver => orphanCount == 0;

  /// 计划摘要（写进 manifest + 交付页展示）。
  Map<String, Object?> toSummaryJson() => {
        'projectId': projectId,
        'projectName': projectName,
        'client': client,
        'generatedAt': generatedAt,
        'itemTotal': itemTotal,
        'extraCount': extraCount,
        'itemDone': itemDone,
        'gapCount': gapCount,
        'photoCount': photoCount,
        'precheckPhotoCount': precheckPhotoCount,
        'unmatchedCount': unmatchedPhotos.length,
        'supervisionCount': supervisionPhotos.length,
        'unusedCount': unusedPhotos.length,
        'coverage': double.parse(coverage.toStringAsFixed(4)),
        'orphanCount': orphanCount,
        'canDeliver': canDeliver,
      };
}
