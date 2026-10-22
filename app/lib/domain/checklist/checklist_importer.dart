import '../../core/constants.dart';
import '../../core/naming.dart';
import '../model/checklist_row.dart';
import '../model/enums.dart';
import 'checklist_file_reader.dart';
import 'column_mapper.dart';

/// 清单解析与校验（纯逻辑，不碰文件系统、不碰数据库）。
///
/// 校验规则严格对齐设计方案 §5.1 的「导入校验规则（硬性）」。
/// 之所以要做成纯函数：这几条规则是整个导入流程里最容易出错的地方，
/// 必须能脱离 Excel 包、脱离 APP 单独跑测试。
class ChecklistImporter {
  const ChecklistImporter._();

  /// [sameCodeMultiRow]：同一份清单里编码重复时怎么办（P4 诉求 1）。
  ///
  ///   · `true`（**默认，语义甲**）—— 视为同一件货分散在多箱，**合并**为一条：
  ///     数量累加、箱号收集。
  ///   · `false` —— 旧行为：保留首次、其余跳过。
  ///
  /// 之所以给开关而不是一刀切：客户清单的写法不统一。真有客户把
  /// 同一个编码当两件不同的货列（同编码不同规格），合并会把两件并成一件。
  /// 这个开关是留给那种情况的逃生口，不作为默认。
  static ChecklistParseResult parse({
    required SheetGrid grid,
    required ColumnMapping mapping,
    int defaultRequiredPhotos = 2,
    Set<String> existingCodes = const <String>{},
    bool sameCodeMultiRow = true,
  }) {
    final issues = <ValidationIssue>[];
    final rows = <ChecklistRow>[];

    final headerIdx = mapping.headerRow;
    final headerLabels = (headerIdx >= 0 && headerIdx < grid.rows.length)
        ? grid.rows[headerIdx].map((c) => (c ?? '').trim()).toList()
        : <String>[];

    /// 编码 → 已合并进 [rows] 的那一行（P4 诉求 1，语义甲）。
    ///
    /// 语义甲：同一件货可能分散在多个箱子里，被清单列成多行。
    /// 业务上这是**一件货**，所以这里做的是**合并**而不是跳过 ——
    /// 跳过会让数量少算，进而让人以为少了货。
    final merged = <String, _MergedRow>{};

    final dataStart = headerIdx + 1;
    final dataRows = grid.rows.skip(dataStart).toList();

    if (!mapping.isValid) {
      issues.add(const ValidationIssue(
        level: IssueLevel.error,
        row: 0,
        message: '尚未指定「货品编码」所在列，无法导入',
        field: '货品编码',
      ));
    }

    if (dataRows.length > AppConst.checklistWarnRows) {
      issues.add(ValidationIssue(
        level: IssueLevel.warning,
        row: 0,
        message: '清单有 ${dataRows.length} 行，明显大于常规规模（> ${AppConst.checklistWarnRows} 行）。'
            '请确认没有选错文件或选错工作表。',
      ));
    }

    final codeCol = mapping[ChecklistField.itemCode];
    final nameCol = mapping[ChecklistField.name];
    final specCol = mapping[ChecklistField.spec];
    final qtyCol = mapping[ChecklistField.qty];
    final unitCol = mapping[ChecklistField.unit];
    final reqCol = mapping[ChecklistField.requiredPhotos];
    final containerCol = mapping[ChecklistField.container];
    final remarkCol = mapping[ChecklistField.remark];

    // 箱号向下填充的携带值（见循环内注释：合并单元格视觉 → 稀疏填写）
    String? containerCarry;

    for (var i = 0; i < dataRows.length; i++) {
      final raw = dataRows[i];
      final excelRow = dataStart + i + 1; // 1-based，供用户回原表核对

      String cell(int? col) {
        if (col == null || col >= raw.length) return '';
        return (raw[col] ?? '').trim();
      }

      final rawCode = cell(codeCol);

      // ── 规则 1：编码为空 → 丢弃该行 ──────────────────────
      // 客户清单末尾常有"合计""小计"行，或表头下方有空行。
      if (rawCode.isEmpty) {
        final rowHasAnyData = raw.any((c) => (c ?? '').trim().isNotEmpty);
        if (rowHasAnyData) {
          issues.add(ValidationIssue(
            level: IssueLevel.error,
            row: excelRow,
            message: '货品编码为空，该行已跳过',
            field: '货品编码',
          ));
        }
        continue;
      }

      // ── 规则 4：全角 / 前后空格 → 归一化 ──────────────────
      final code = toHalfWidth(rawCode).trim();
      if (code != rawCode) {
        issues.add(ValidationIssue(
          level: IssueLevel.info,
          row: excelRow,
          message: '编码「$rawCode」含全角字符或多余空格，已规范为「$code」',
          field: '货品编码',
        ));
      }

      final containerRaw = cell(containerCol);
      // ── 箱号向下填充（2026-09-24 真实清单 PIDU9352234 实证补上的）────
      //
      // 客户用 Excel 合并单元格表达「这 5 行都是 BOX-M10」：箱号只在
      // 同箱**首行**有值，其余行留空。逐行读的话 80 件货里只有 20 件
      // 带箱号。这里做向下填充：读到非空就更新，读到空沿用上一个。
      //
      // ⚠️ 只在编码非空（该行真的会被导入）时才更新 carry —— 备注行
      //    （真实清单第 91 行整行只有 "NOTE.:1、..."，编码为空）不能把
      //    自己灌进后续行的箱号。跳过的行也不该改变箱号语义。
      if (containerRaw.isNotEmpty) containerCarry = containerRaw;
      final container = containerCarry;

      final qtyHere = _parseQty(cell(qtyCol));

      // ── 规则 2（P4 语义甲改写）：编码重复 → **合并**，不是跳过 ──
      //
      // 改写原因：清单按箱子排列时，同一件货会被列成多行
      //（「BOX-0012 / 3 件 / 箱 A」「BOX-0012 / 5 件 / 箱 B」）。
      // 原实现"保留首次、其余跳过"会让这件货只算 3 件 —— 数据是错的。
      // 现在累加数量、收集箱号，并把这件事**明确告诉用户**。
      final already = merged[code];
      if (already != null) {
        if (!sameCodeMultiRow) {
          // 旧行为（由调用方显式要求）：保留首次，其余跳过
          issues.add(ValidationIssue(
            level: IssueLevel.warning,
            row: excelRow,
            message: '编码「$code」与第 ${already.firstRow} 行重复，本行已跳过',
            field: '货品编码',
          ));
          continue;
        }
        already.merge(container: container, qty: qtyHere);
        issues.add(ValidationIssue(
          level: IssueLevel.info,
          row: excelRow,
          message: container == null
              ? '编码「$code」与第 ${already.firstRow} 行重复，已合并为一件货'
              : '编码「$code」与第 ${already.firstRow} 行重复（本次：$container），'
                  '已合并为一件货并累加数量',
          field: '货品编码',
        ));
        continue;
      }
      if (existingCodes.contains(code)) {
        issues.add(ValidationIssue(
          level: IssueLevel.warning,
          row: excelRow,
          message: '编码「$code」在本项目中已存在，本行已跳过（不会影响它已有的照片归属）',
          field: '货品编码',
        ));
        continue;
      }

      // ── 规则 3：文件名不安全字符 → 自动替换 ───────────────
      final codeSafe = safeFileName(code);
      if (codeSafe != code) {
        issues.add(ValidationIssue(
          level: IssueLevel.warning,
          row: excelRow,
          message: '编码「$code」含文件名不可用字符，打包时将写作「$codeSafe」（原始编码仍保留）',
          field: '货品编码',
        ));
      }

      final name = cell(nameCol);

      // 数值字段也要过全角转换 —— 客户表里全角数字很常见，
      // 不转的话 double.tryParse('１００') 会直接失败。
      final qtyRaw = toHalfWidth(cell(qtyCol));
      final reqRaw = toHalfWidth(cell(reqCol));

      final qty = qtyHere;
      if (qtyRaw.isNotEmpty && qty == null) {
        issues.add(ValidationIssue(
          level: IssueLevel.info,
          row: excelRow,
          message: '数量「$qtyRaw」无法解析为数字，已留空',
          field: '数量',
        ));
      }

      int? requiredPhotos = int.tryParse(reqRaw.replaceAll(RegExp(r'[^0-9]'), ''));
      if (requiredPhotos != null && requiredPhotos <= 0) requiredPhotos = null;
      requiredPhotos ??= defaultRequiredPhotos;

      final row = ChecklistRow(
        sourceRow: excelRow,
        code: code,
        codeSafe: codeSafe,
        name: name.isEmpty ? null : name,
        spec: _nullable(cell(specCol)),
        qty: qty,
        unit: _nullable(cell(unitCol)),
        requiredPhotos: requiredPhotos,
        container: container,
        remark: _nullable(cell(remarkCol)),
      );
      rows.add(row);
      merged[code] = _MergedRow(row: row, rowIndex: rows.length - 1);
    }

    // ── 合并结果回写（P4 诉求 1）─────────────────────────────
    // ChecklistRow 是不可变值对象，所以累加完成后统一重建一次。
    // 只有真的发生过合并的行才重建 —— 绝大多数行原样不动。
    for (final entry in merged.values) {
      if (!entry.didMerge) continue;
      rows[entry.rowIndex] = entry.rebuild();
    }

    if (rows.isEmpty && dataRows.isNotEmpty) {
      issues.add(const ValidationIssue(
        level: IssueLevel.error,
        row: 0,
        message: '没有解析出任何有效货品，请检查「货品编码」列是否选对',
      ));
    }

    return ChecklistParseResult(
      rows: rows,
      issues: issues,
      totalSourceRows: dataRows.length,
      headerRow: headerIdx,
      headerLabels: headerLabels,
      previewRows: dataRows.take(5).toList(),
    );
  }

  /// 数量解析：全角转半角 + 剔除非数字字符。
  /// 解析不出来返回 null（**不返回 0** —— 0 和"没有数量列"是两回事）。
  static double? _parseQty(String raw) {
    final s = toHalfWidth(raw).replaceAll(RegExp(r'[^0-9.\-]'), '');
    if (s.isEmpty) return null;
    final v = double.tryParse(s);
    // 负数不是数量。客户表里 `-` 常被当作"此格空着"，能解析成 -1 反而更危险。
    if (v == null || v < 0) return null;
    return v;
  }

  static String? _nullable(String s) => s.trim().isEmpty ? null : s.trim();
}

/// 合并过程中的累加器（P4 诉求 1，语义甲）。
///
/// 为什么单独一个类而不是就地改 [ChecklistRow]：
/// `ChecklistRow` 是**不可变值对象**，导入校验是纯函数 ——
/// 就地改会让"合并"这件事散落在循环里，难以断言与测试。
/// 这里显式收集"哪些行被合并了、合并成什么"，最后一次性回写。
class _MergedRow {
  _MergedRow({required this.row, required this.rowIndex})
      : firstRow = row.sourceRow,
        _qty = row.qty,
        // 首行就没有数量 → 这件货的数量从一开始就不可信，
        // 后面再怎么累加都是在错的基础上加（P4 语义甲的边界条件）。
        _qtyKnown = row.qty != null;

  /// 首次出现的那一行（不可变，作为重建的基底）。
  final ChecklistRow row;

  /// 它在 [rows] 里的下标（回写用）。
  final int rowIndex;

  /// 首次出现的原表行号（提示语里"与第 N 行重复"用的就是它）。
  final int firstRow;

  /// 累加中的数量。[_qtyKnown] 为 false 时它无意义。
  double? _qty;

  /// 数量是否还能信。**任一行缺数量 → 整件货的数量就不该给出**
  ///（宁可留空让人回原表查，也不要给一个少算的数）。
  bool _qtyKnown;

  final List<String> _containers = [];
  int _lineCount = 1;
  bool _didMerge = false;

  /// 首行自带的箱号。合并时**先种进来**，这样"首行箱A + 第二行箱A"
  /// 也能正确去重成一个（不做这一步就会拼出「箱A、箱A」）。
  List<String> get _allContainers {
    final out = <String>[
      if (row.container != null && row.container!.isNotEmpty) row.container!,
    ];
    for (final c in _containers) {
      if (!out.contains(c)) out.add(c);
    }
    return out;
  }

  bool get didMerge => _didMerge;
  int get lineCount => _lineCount;

  /// 把一行的箱号与数量并进来。
  void merge({required String? container, required double? qty}) {
    _didMerge = true;
    _lineCount++;

    if (container != null && container.isNotEmpty) _containers.add(container);

    if (qty == null) {
      _qtyKnown = false;
      _qty = null;
    } else if (_qtyKnown) {
      _qty = (_qty ?? 0) + qty;
    }
    // _qtyKnown 已为 false 时什么都不做 —— 总数已不可信
  }

  ChecklistRow rebuild() {
    final containers = _allContainers;
    return ChecklistRow(
      sourceRow: row.sourceRow,
      code: row.code,
      codeSafe: row.codeSafe,
      name: row.name,
      spec: row.spec,
      qty: _qtyKnown ? _qty : null,
      unit: row.unit,
      requiredPhotos: row.requiredPhotos,
      container: containers.isEmpty ? null : containers.join('、'),
      sourceLineCount: _lineCount,
      remark: row.remark,
    );
  }
}
