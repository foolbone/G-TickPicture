import 'package:drift/drift.dart';

/// 全部表定义 —— 对应设计方案 §6.2。
///
/// 两条必须在代码里守住的约定：
///   1. 状态字段一律用 `text()` 存枚举的 `code`，不用 drift TypeConverter。
///   2. `Photos.itemId` / `PhotoGroups.itemId` 是「人的领地」，
///      只允许 `AssignService` 写入。改这里的结构前请先看 §6.1。

// ─────────────────────────────────────────────────────────────
// 1. 项目
// ─────────────────────────────────────────────────────────────

class Projects extends Table {
  TextColumn get id => text()();
  TextColumn get name => text()();
  TextColumn get client => text().nullable()();
  IntColumn get createdAt => integer()();

  /// ProjectStatus.code
  TextColumn get status =>
      text().withDefault(const Constant('collecting'))();

  /// 清单来源文件名，便于回溯
  TextColumn get checklistFile => text().nullable()();

  /// 项目级设置（JSON）：每品张数、画质、是否启用 OCR 等
  TextColumn get settingsJson => text().nullable()();

  IntColumn get deletedAt => integer().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// ─────────────────────────────────────────────────────────────
// 2. 货品（来自清单）
// ─────────────────────────────────────────────────────────────

class Items extends Table {
  TextColumn get id => text()();
  TextColumn get projectId => text().references(Projects, #id)();

  /// 清单行序。决定交付目录的 3 位序号，也是缺口视图的排序依据。
  IntColumn get seq => integer()();

  /// 原始编码 —— **永不改写**，用于匹配与显示
  TextColumn get code => text()();

  /// 文件名安全版本 —— 仅用于交付目录/文件命名
  TextColumn get codeSafe => text()();

  TextColumn get name => text().nullable()();
  TextColumn get spec => text().nullable()();
  RealColumn get qty => real().nullable()();
  TextColumn get unit => text().nullable()();

  /// 每品要求张数，用于"张数未达标"提醒
  IntColumn get requiredPhotos => integer().withDefault(const Constant(2))();

  /// 所在包装箱（P4 诉求 1，语义甲）。
  ///
  /// 客户清单里同一件货可能分散在多个箱子里，被列成多行
  /// （如「BOX-0012 / 3 件 / 箱 A」「BOX-0012 / 5 件 / 箱 B」）。
  /// 业务上这是**同一件货**，所以导入时合并为一条记录：
  ///   · [qty] 累加（3 + 5 = 8）
  ///   · 各行的箱号在此**汇总成列表**，用 `、` 连接
  ///
  /// 存文本而不是关联表：箱号只用于**显示**，
  /// 没有任何按箱查询的需求（预检是"按货品"作业，不是"按箱"）。
  /// 为它建一张表只会增加连接与迁移成本。
  ///
  /// null / 空串 = 清单没提供箱号信息（多数清单如此），
  /// 界面必须能优雅地什么都不显示。
  TextColumn get containerSummary => text().nullable()();

  /// 该货品在清单里占了几行（P4 诉求 1）。
  ///
  /// 用于两件事：
  ///   1. 导入校验报告里说明"编码 X 由 3 行合并而来"，让人能回原表核对；
  ///   2. manifest 里体现"这件货分布在几个箱"。
  /// 默认 1 = 清单里正常的单行货品。
  IntColumn get sourceLineCount => integer().withDefault(const Constant(1))();

  /// ItemState.code: normal / not_found / extra
  TextColumn get state => text().withDefault(const Constant('normal'))();

  /// 缺口原因（压在垛底 / 已被提走 / 客户取消 / 其他）。
  /// 措辞纪律：界面一律说「缺口」，不说「现场未见」（§原则 13）。
  TextColumn get notFoundReason => text().nullable()();

  TextColumn get remark => text().nullable()();
  IntColumn get deletedAt => integer().nullable()();

  @override
  Set<Column> get primaryKey => {id};

  /// 同一项目内编码唯一（阻止重复导入）
  @override
  List<Set<Column>> get uniqueKeys => [
        {projectId, code},
      ];
}

// ─────────────────────────────────────────────────────────────
// 3. 采集批次（一次"开拍 → 结束"）
// ─────────────────────────────────────────────────────────────

class CaptureSessions extends Table {
  TextColumn get id => text()();
  TextColumn get projectId => text().references(Projects, #id)();

  /// CaptureSource.code: camera / album
  TextColumn get source => text().withDefault(const Constant('camera'))();

  IntColumn get startedAt => integer()();
  IntColumn get endedAt => integer().nullable()();
  IntColumn get photoCount => integer().withDefault(const Constant(0))();
  TextColumn get note => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// ─────────────────────────────────────────────────────────────
// 4. 拍摄组（按批次分组的结果，可人工修正）
// ─────────────────────────────────────────────────────────────

class PhotoGroups extends Table {
  TextColumn get id => text()();
  TextColumn get projectId => text().references(Projects, #id)();
  TextColumn get sessionId => text().references(CaptureSessions, #id)();

  IntColumn get seq => integer()();
  TextColumn get coverPhotoId => text().nullable()();
  IntColumn get photoCount => integer().withDefault(const Constant(0))();

  /// GroupOrigin.code: camera / album / manual
  TextColumn get origin => text().withDefault(const Constant('camera'))();

  /// PhotoCategory.code: precheck / supervision（老板 2026-09-27 拍板）。
  ///
  /// 部类由**人在整理阶段**指定（采集时不问）。默认 precheck ——
  /// 老数据与"还没归类的照片"都按预检处理，保证交付不丢照片。
  ///
  /// ⚠️ 不是归属：这里改类别不影响 `itemId`，因此不走 AssignService。
  TextColumn get category => text().withDefault(const Constant('precheck'))();

  /// 用户指定的箱号（老板 2026-09-27 拍板）。
  ///
  /// ★ 与 `Items.containerSummary` 的区别：
  ///   · 那个是**清单里写的**箱号信息（多数清单没有，且一货多箱时是汇总文本）；
  ///   · 这个是**整理时由人输入/选择**的箱号，是交付分文件夹的**唯一依据**。
  ///
  /// 「分组时由用户指定箱号，不依赖货品清单」—— 所以打包只看这一列。
  /// null / 空 = 还没指定箱号 → 交付时进 `_未分箱/`。
  TextColumn get carton => text().nullable()();

  // ── OCR 建议：机器产出，**不等于归属** ────────────────────
  TextColumn get suggestedItemId => text().nullable()();
  RealColumn get suggestionConf => real().nullable()();

  /// 候选列表 + 命中证据（JSON），供 UI 排序"改派"候选与复盘
  TextColumn get suggestionJson => text().nullable()();

  /// GroupSuggestState.code: pending / no_suggestion / conflict / none
  TextColumn get suggestState =>
      text().withDefault(const Constant('pending'))();

  // ── 人的决定 ──────────────────────────────────────────────
  /// ★ 只由 AssignService 写
  TextColumn get itemId => text().nullable()();
  IntColumn get confirmedAt => integer().nullable()();

  IntColumn get createdAt => integer()();

  @override
  Set<Column> get primaryKey => {id};
}

// ─────────────────────────────────────────────────────────────
// 5. 照片
// ─────────────────────────────────────────────────────────────

/// 查重是「按 content_hash 分组数 > 1」，没索引就是全表扫（上千张照片
/// 的项目每次进页面都全扫一遍 = 卡）。
///
/// 用注解而不是 `get indexes` 覆写 —— drift 2.31 的表类上没有这个覆写点，
/// 写了会报 `override_on_non_overriding_member`。
@TableIndex(name: 'photos_content_hash', columns: {#contentHash})
class Photos extends Table {
  TextColumn get id => text()();
  TextColumn get projectId => text().references(Projects, #id)();
  TextColumn get sessionId => text().references(CaptureSessions, #id)();
  TextColumn get groupId => text().nullable()();

  /// 原始文件路径 —— **永不改名**（§6.4）
  TextColumn get filePath => text()();
  TextColumn get thumbPath => text().nullable()();

  IntColumn get width => integer().nullable()();
  IntColumn get height => integer().nullable()();
  IntColumn get bytes => integer().nullable()();

  /// EXIF 优先，缺失时退化用写入时间
  IntColumn get takenAt => integer()();

  /// 项目内全局序号
  IntColumn get seq => integer()();

  /// ★ 只由 AssignService 写
  TextColumn get itemId => text().nullable()();

  /// PhotoState.code: unassigned / confirmed / unused
  TextColumn get state => text().withDefault(const Constant('unassigned'))();

  /// PhotoCategory.code: precheck / supervision。
  ///
  /// 冗余一份在照片上的理由：打包与统计都按照片走（监装照片可能
  /// 根本不进组），每次 join 组再回退会话会让查询写得很绕，且游离
  /// 照片（groupId 为空）无处可 join。
  ///
  /// **一致性由写入口保证**：整理页切换组类别时，同一个事务里把
  /// 组内照片的 category 一起刷掉（见 OrganizeRepository）。
  TextColumn get category => text().withDefault(const Constant('precheck'))();

  /// OcrState.code: pending / running / done / failed / skipped
  TextColumn get ocrState => text().withDefault(const Constant('pending'))();

  /// 画质标记：blur / exposure / reasonable（P2 才用）
  TextColumn get sharpnessFlag => text().nullable()();

  /// ★ 内容指纹（2026-10-04 老板「同一组内、不同组间的照片不能重复」）。
  ///
  /// 形态是「文件大小 + 前 64KB 的摘要」拼成的短串，**不是全文件哈希** ——
  /// 1200 张 × 2.4MB 全读一遍是 2.9GB IO，现场等不起；而同一张图无论
  /// 从相册选几次、经几次微信转发，**文件字节完全不变**，读头 64KB
  /// 就足以认出来。真正的重复一张不漏，可见的编辑/重压（同一场景两张
  /// 略不同的图）不会被误判 —— 宁可漏报也不错报。
  ///
  /// **NULL = 还没算过**（不是"没有重复"）。老照片在 v4 迁移后一律 NULL，
  /// 由 backfillHashes 分批补算；补算前照片页不显示重复提示。
  TextColumn get contentHash => text().nullable()();

  IntColumn get createdAt => integer()();

  @override
  Set<Column> get primaryKey => {id};
}

// ─────────────────────────────────────────────────────────────
// 6. OCR 原始 token（与归属完全隔离）
// ─────────────────────────────────────────────────────────────

class OcrTokens extends Table {
  TextColumn get id => text()();
  TextColumn get photoId => text().references(Photos, #id)();

  /// OCR 识别出的原始文本。
  ///
  /// ⚠️ Dart 侧字段名**不能**叫 `text` —— `Table` 基类有 `text()` 方法，
  /// 同名 getter 会把它遮蔽掉，导致本类其余 `text()` 调用全部报
  /// "invocation_of_non_function_expression"，且 drift 生成器直接失败。
  /// 所以用 `named('text')` 保留 SQL 列名不变，只改 Dart 侧标识符。
  TextColumn get rawText => text().named('text')();

  RealColumn get confidence => real()();

  /// 归一化坐标（JSON），用于位置权重
  TextColumn get boxJson => text()();
  IntColumn get page => integer().withDefault(const Constant(0))();

  @override
  Set<Column> get primaryKey => {id};
}

// ─────────────────────────────────────────────────────────────
// 7. 归属决策记录 —— 可追溯的核心（§6.2）
// ─────────────────────────────────────────────────────────────

class Assignments extends Table {
  TextColumn get id => text()();
  TextColumn get projectId => text().references(Projects, #id)();

  /// AssignTargetType.code: photo / group
  TextColumn get targetType => text()();
  TextColumn get targetId => text()();
  TextColumn get itemId => text()();

  /// AssignSource.code
  TextColumn get source => text()();

  /// 当时的机器建议是什么 —— 用于统计"建议采纳率"
  TextColumn get suggestedItemId => text().nullable()();
  RealColumn get suggestionConf => real().nullable()();

  /// ★ 非空。这是"人做决定"原则的落点。
  IntColumn get confirmedAt => integer()();

  /// 免登录下的最小身份标识（设备昵称）
  TextColumn get confirmedBy => text()();

  /// 撤销时间。**撤销是打标记，不是删除** —— 留痕。
  IntColumn get revokedAt => integer().nullable()();

  TextColumn get note => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// ─────────────────────────────────────────────────────────────
// 8. 交付包
// ─────────────────────────────────────────────────────────────

class Deliveries extends Table {
  TextColumn get id => text()();
  TextColumn get projectId => text().references(Projects, #id)();
  IntColumn get createdAt => integer()();

  /// includeRaw / includeManifest / includeUnused / groupByCarton
  TextColumn get optionsJson => text()();

  TextColumn get zipPath => text().nullable()();
  TextColumn get pdfPath => text().nullable()();
  IntColumn get bytes => integer().nullable()();
  IntColumn get itemCount => integer().nullable()();
  IntColumn get photoCount => integer().nullable()();
  TextColumn get sha256 => text().nullable()();
  IntColumn get sharedAt => integer().nullable()();
  TextColumn get webdavPath => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// ─────────────────────────────────────────────────────────────
// 9. WebDAV 上传队列
// ─────────────────────────────────────────────────────────────

class UploadTasks extends Table {
  TextColumn get id => text()();
  TextColumn get deliveryId => text().references(Deliveries, #id)();
  TextColumn get localPath => text()();
  TextColumn get remotePath => text()();
  IntColumn get bytes => integer()();
  IntColumn get uploadedBytes => integer().withDefault(const Constant(0))();

  /// UploadState.code
  TextColumn get state => text().withDefault(const Constant('queued'))();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  IntColumn get nextRetryAt => integer().nullable()();
  TextColumn get lastError => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// ─────────────────────────────────────────────────────────────
// 10. 一照多货：照片与货品的附加关联（P2）
//
// 设计方案 §2.2 决策："主归属 + 附加关联"。主归属走 Photos.itemId，
// 附加关系落在这张表。M1 只建表不用。
// ─────────────────────────────────────────────────────────────

class ItemPhotoExtras extends Table {
  TextColumn get id => text()();
  TextColumn get photoId => text().references(Photos, #id)();
  TextColumn get itemId => text().references(Items, #id)();

  /// 关联角色：co_visible（同框可见） / damaged（破损处） …
  TextColumn get role => text().withDefault(const Constant('co_visible'))();
  IntColumn get createdAt => integer()();

  @override
  Set<Column> get primaryKey => {id};

  @override
  List<Set<Column>> get uniqueKeys => [
        {photoId, itemId},
      ];
}

// ─────────────────────────────────────────────────────────────
// 11. 应用设置（键值对。WebDAV 凭据不在这 —— 那走 secure_storage）
// ─────────────────────────────────────────────────────────────

class AppSettings extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();
  IntColumn get updatedAt => integer()();

  @override
  Set<Column> get primaryKey => {key};
}
