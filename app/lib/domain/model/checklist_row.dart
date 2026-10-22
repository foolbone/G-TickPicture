/// 从清单里解析出来的一行货品。
///
/// 注意 [code] 与 [codeSafe] 的分工（设计方案 §5.1）：
///   · [code]     —— 原始编码，入库保留，用于匹配与显示
///   · [codeSafe] —— 文件名安全版本，只用于交付目录/文件命名
/// 两者都要留。丢掉原始值的话，报告员看到的名字就和客户清单对不上了。
class ChecklistRow {
  const ChecklistRow({
    required this.sourceRow,
    required this.code,
    required this.codeSafe,
    this.name,
    this.spec,
    this.qty,
    this.unit,
    this.requiredPhotos,
    this.container,
    this.sourceLineCount = 1,
    this.remark,
  });

  /// 原表行号（1-based，含表头偏移已在解析时处理）。
  /// 校验报错时要指回 Excel 的哪一行，用户才找得到。
  final int sourceRow;

  final String code;
  final String codeSafe;
  final String? name;
  final String? spec;
  final double? qty;
  final String? unit;
  final int? requiredPhotos;

  /// 该行标注的所在包装箱（P4 诉求 1）。多数清单没有这一列 → null。
  ///
  /// 当同一件货分散在多箱时，合并后的记录里这里是**汇总列表**
  /// （形如 `箱A、箱B`），由 [ChecklistImporter] 用 `、` 连接。
  final String? container;

  /// 这件货在清单里占了几行（P4 诉求 1）。
  ///
  /// 单行货品 = 1；同编码多行被合并后 = 实际行数。
  /// 用于导入报告说明"编码 X 由 3 行合并而来"，让人能回原表核对。
  final int sourceLineCount;

  final String? remark;
}

/// 校验问题的严重级别。
enum IssueLevel {
  /// 该行被丢弃，必须让用户看到
  error,

  /// 该行保留但已被系统改写，需要用户知晓
  warning,

  /// 仅提示
  info;

  String get label => switch (this) {
        IssueLevel.error => '错误',
        IssueLevel.warning => '警告',
        IssueLevel.info => '提示',
      };
}

/// 一条校验问题。
class ValidationIssue {
  const ValidationIssue({
    required this.level,
    required this.row,
    required this.message,
    this.field,
  });

  final IssueLevel level;
  final int row;
  final String message;
  final String? field;

  @override
  String toString() => '[${level.label}] 第 $row 行：$message';
}

/// 导入结果。UI 的"校验报告"页就是渲染这个对象。
class ChecklistParseResult {
  const ChecklistParseResult({
    required this.rows,
    required this.issues,
    required this.totalSourceRows,
    required this.headerRow,
    required this.headerLabels,
    required this.previewRows,
  });

  /// 通过校验、可以入库的行
  final List<ChecklistRow> rows;

  final List<ValidationIssue> issues;

  /// 原表数据行总数（不含表头）
  final int totalSourceRows;

  /// 表头所在行（0-based，用于展示"表头在第 N 行"）
  final int headerRow;

  /// 推断出的表头文字，用于列映射向导的回显
  final List<String> headerLabels;

  /// 前若干行原始数据，供"预览"步骤展示
  final List<List<String?>> previewRows;

  int get errorCount => issues.where((e) => e.level == IssueLevel.error).length;
  int get warningCount => issues.where((e) => e.level == IssueLevel.warning).length;
  int get skippedRows => totalSourceRows - rows.length;

  bool get hasBlockingError => rows.isEmpty || errorCount > 0;

  /// 能否进入下一步（导入）。有 error 时要求用户先确认。
  bool get canProceed => rows.isNotEmpty;
}
