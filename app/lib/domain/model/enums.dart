// 领域枚举。
//
// 设计约定：数据库里存 [code]（字符串，可读、可迁移），
// 代码里用枚举。**不引入 drift TypeConverter** —— 手写 fromCode 更省心，
// 且迁移时不会被生成代码绑住。
library;

// ─────────────────────────────────────────────────────────────
// 项目
// ─────────────────────────────────────────────────────────────

/// 项目所处阶段（驱动工作台高亮哪个 Tab）。
enum ProjectStatus {
  collecting('collecting'),
  organizing('organizing'),
  delivering('delivering'),
  done('done');

  const ProjectStatus(this.code);
  final String code;

  static ProjectStatus fromCode(String? c) => ProjectStatus.values
      .firstWhere((e) => e.code == c, orElse: () => ProjectStatus.collecting);

  /// 【2026-10-01 措辞更新】以前是「采集中 / 整理中」—— 那是四段式导航
  /// （概览/采集/整理/交付）时代的说法，现在采集与整理合并进了「照片」页，
  /// 再叫「采集中」指的是已经不存在的页面。改成贴作业实际进展的说法。
  /// code 一律不动 —— 那是落库的值，改了等于改数据。
  String get label => switch (this) {
        ProjectStatus.collecting => '待拍照',
        ProjectStatus.organizing => '待整理',
        ProjectStatus.delivering => '待交付',
        ProjectStatus.done => '已交付',
      };
}

// ─────────────────────────────────────────────────────────────
// 货品
// ─────────────────────────────────────────────────────────────

/// 货品状态。
///
/// [notFound] 是 v3.0 独有的能力：清单里有、现场找不到。
/// 它对报告员的"未装/短装"结论是直接依据，必须能表达出来。
enum ItemState {
  /// 清单里的正常货品
  normal('normal'),

  /// 缺口（清单里有、却没有照片的货品）。
  ///
  /// ⚠️ 措辞纪律（设计方案 §原则 13）：界面上**一律说「缺口」**，
  /// 禁止说「现场未见」—— 后者替业务下了判断。没拍到照片的原因是多样的：
  /// 货未到 / 已被提走 / 压在垛底 / 只是漏拍。App 只如实反映"缺照片"这个事实。
  notFound('not_found'),

  /// 现场有、清单没有（整理阶段"创建为新货品"的产物）
  extra('extra');

  const ItemState(this.code);
  final String code;

  static ItemState fromCode(String? c) =>
      ItemState.values.firstWhere((e) => e.code == c, orElse: () => ItemState.normal);

  String get label => switch (this) {
        ItemState.normal => '正常',
        ItemState.notFound => '缺口',
        ItemState.extra => '清单外',
      };
}

// ─────────────────────────────────────────────────────────────
// 采集批次
// ─────────────────────────────────────────────────────────────

enum CaptureSource {
  camera('camera'),
  album('album');

  const CaptureSource(this.code);
  final String code;

  static CaptureSource fromCode(String? c) =>
      CaptureSource.values.firstWhere((e) => e.code == c, orElse: () => CaptureSource.camera);
}

// ─────────────────────────────────────────────────────────────
// 照片
// ─────────────────────────────────────────────────────────────

/// 照片状态。
///
/// 关键：**没有 `suggested` 状态**。OCR 建议根本不落在照片上，
/// 它落在 `photo_groups.suggested_item_id`。这是 §6.1 的物理隔离。
enum PhotoState {
  /// 未处理（默认）。item_id 为空。
  unassigned('unassigned'),

  /// 已由人确认归属。item_id 非空。
  confirmed('confirmed'),

  /// 主动归入"未使用"（环境照 / 废片），交付时进 `_未使用/`
  unused('unused');

  const PhotoState(this.code);
  final String code;

  static PhotoState fromCode(String? c) =>
      PhotoState.values.firstWhere((e) => e.code == c, orElse: () => PhotoState.unassigned);
}

/// 照片部类（老板 2026-09-27 拍板：整理时把照片分成「预检」和「监装」两大部分）。
///
/// 语义：
///   [precheck]    预检 —— 与货品清单有关。能对应编码就对应，对应不上
///                 也不影响交付（用原始文件名跟着箱号走）。按箱号分文件夹交付。
///   [supervision] 监装 —— 装柜过程的照片（空箱 / 半载 / 满载 / 封条 / 车号）。
///                 与货品清单**无关**，不对应编码、不分箱，全部进一个文件夹。
///
/// ⚠️ 类别**不是归属**：切换类别不触碰 `item_id`，所以不受
/// 「归属只由 AssignService 写」这条铁律的约束（§6.1）。
/// 归属（给哪件货）与部类（预检还是监装）是两个正交的维度。
///
/// 归类时机：只在整理阶段做（老板拍板），采集时不问、不猜、不弹窗
/// —— 现场分类会让预检员在几百张照片上反复切换。
enum PhotoCategory {
  precheck('precheck'),
  supervision('supervision');

  const PhotoCategory(this.code);
  final String code;

  static PhotoCategory fromCode(String? c) => PhotoCategory.values
      .firstWhere((e) => e.code == c, orElse: () => PhotoCategory.precheck);

  String get label => switch (this) {
        PhotoCategory.precheck => '预检',
        PhotoCategory.supervision => '监装',
      };

  /// 一句话说明，用于整理页的部类切换提示。
  String get hint => switch (this) {
        PhotoCategory.precheck =>
          '与货品清单有关 —— 尽量对应到编码，按箱号分文件夹交付',
        PhotoCategory.supervision =>
          '装柜过程照片 —— 与清单无关，全部放进一个「监装」文件夹',
      };
}

/// OCR 处理状态（驱动"预处理进度条"）。
enum OcrState {
  pending('pending'),
  running('running'),
  done('done'),
  failed('failed'),

  /// 被跳过：用户关了 OCR 开关，或该张不需要识别
  skipped('skipped');

  const OcrState(this.code);
  final String code;

  static OcrState fromCode(String? c) =>
      OcrState.values.firstWhere((e) => e.code == c, orElse: () => OcrState.pending);
}

// ─────────────────────────────────────────────────────────────
// 拍摄组
// ─────────────────────────────────────────────────────────────

/// 组的建议状态。注意它描述的是**建议的质量**，不是归属。
enum GroupSuggestState {
  /// 有建议、待人工确认（默认目标状态）
  pending('pending'),

  /// 无建议或置信度过低 → 必须手动指派
  noSuggestion('no_suggestion'),

  /// 组内识别结果分歧较大 → 提醒人看一眼
  conflict('conflict'),

  /// 未运行 OCR（用户关闭了开关 / ML Kit 不可用）
  none('none');

  const GroupSuggestState(this.code);
  final String code;

  static GroupSuggestState fromCode(String? c) => GroupSuggestState.values
      .firstWhere((e) => e.code == c, orElse: () => GroupSuggestState.pending);

  String get label => switch (this) {
        GroupSuggestState.pending => '待确认',
        GroupSuggestState.noSuggestion => '无建议',
        GroupSuggestState.conflict => '识别冲突',
        GroupSuggestState.none => '未识别',
      };
}

/// 组的来源（决定整理页怎么展示）。
enum GroupOrigin {
  camera('camera'),

  /// 相册导入（按批次分组下与 camera 同规则：一批一组）
  album('album'),

  /// 用户手动合并/拆分产生
  manual('manual');

  const GroupOrigin(this.code);
  final String code;

  static GroupOrigin fromCode(String? c) =>
      GroupOrigin.values.firstWhere((e) => e.code == c, orElse: () => GroupOrigin.camera);
}

// ─────────────────────────────────────────────────────────────
// 归属决策
// ─────────────────────────────────────────────────────────────

/// 决策类型。
enum AssignTargetType {
  photo('photo'),
  group('group');

  const AssignTargetType(this.code);
  final String code;

  static AssignTargetType fromCode(String? c) => AssignTargetType.values
      .firstWhere((e) => e.code == c, orElse: () => AssignTargetType.photo);
}

/// 归属来源。用于统计 **OCR 建议采纳率**（§9.1 指标 3）。
enum AssignSource {
  /// 手动从候选里选
  manual('manual'),

  /// 采纳系统建议（单组）
  suggestionConfirmed('suggestion_confirmed'),

  /// 批量确认高置信
  bulkConfirm('bulk_confirm'),

  /// 分组变更（合并/拆分）后重算
  splitMerge('split_merge'),

  /// 从父级继承（拆分组时为组内照片补记录）
  carry('carry');

  const AssignSource(this.code);
  final String code;

  static AssignSource fromCode(String? c) => AssignSource.values
      .firstWhere((e) => e.code == c, orElse: () => AssignSource.manual);

  String get label => switch (this) {
        AssignSource.manual => '手动指派',
        AssignSource.suggestionConfirmed => '采纳建议',
        AssignSource.bulkConfirm => '批量确认',
        AssignSource.splitMerge => '分组调整',
        AssignSource.carry => '继承',
      };
}

// ─────────────────────────────────────────────────────────────
// 上传
// ─────────────────────────────────────────────────────────────

enum UploadState {
  queued('queued'),
  uploading('uploading'),
  done('done'),

  /// 已用尽重试次数，转人工
  failed('failed');

  const UploadState(this.code);
  final String code;

  static UploadState fromCode(String? c) =>
      UploadState.values.firstWhere((e) => e.code == c, orElse: () => UploadState.queued);
}

// ─────────────────────────────────────────────────────────────
// 清单导入
// ─────────────────────────────────────────────────────────────

/// 清单导入时映射到系统的字段。
enum ChecklistField {
  // ⚠️ 枚举值不能叫 `code` —— enum 常量是**静态**成员，与下面的实例字段
  // `code` 同名会触发 conflicting_static_and_instance，且报错信息指向构造
  // 函数、看起来像别的问题，极难定位。故枚举值用 itemCode，字段仍叫 code。
  itemCode('code', '货品编码', true),
  name('name', '货品名称', false),
  spec('spec', '规格/型号', false),
  qty('qty', '数量', false),
  unit('unit', '单位', false),
  requiredPhotos('required_photos', '要求张数', false),
  /// 所在包装箱（P4 诉求 1）。**非必填** —— 多数清单没有这一列，
  /// 没有它导入流程照常走完。
  container('container', '包装箱', false),
  remark('remark', '备注', false);

  // ⚠️ 第三个字段不能叫 `required`（Dart 关键字），故用 isRequired。
  const ChecklistField(this.code, this.label, this.isRequired);

  /// 存入 `column_mapping` 的字段名（稳定值，不要改）
  final String code;
  final String label;

  /// 该字段是否必填（目前只有「货品编码」必填）
  final bool isRequired;
}
