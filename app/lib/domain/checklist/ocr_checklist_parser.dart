import '../../core/naming.dart';
import '../model/checklist_row.dart';
import '../ocr/ocr_text_extractor.dart';
// toHalfWidth 是本目录 column_mapper.dart 的顶层函数（ChecklistImporter 同款）
import 'column_mapper.dart';

/// OCR 清单识别（老板 2026-09-26 拍板的「货品清单拍照上传识别」）：
/// 把清单照片的 OCR token 重组为行、再从行里提取「编码（必）+ 品名」。
///
/// 纯逻辑：不碰文件系统、不碰数据库、不依赖具体 OCR 引擎 ——
/// 输入是 [OcrTokenResult]（词级 token，带归一化中心坐标）或行文本，
/// 输出是候选 [ChecklistRow] 与人能看懂的 issues。
///
/// ⚠️ 识别必然不完美（手机拍纸质清单的倾斜、反光、手写体都常见），
/// 所以**人工预览确认是流程的一部分**（§3 原则 7：机器给建议、人做决定）。
/// 这里产出的只是「待确认的候选」，不是最终数据。
class OcrChecklistParser {
  const OcrChecklistParser._();

  // ─────────────────────────────────────────────────────────
  // 行重组：token → 行文本
  // ─────────────────────────────────────────────────────────

  /// 把一张照片的 token 重组为可读行。
  ///
  /// 依据：同一物理行上的 token，纵坐标（normCy）接近、横坐标递增。
  /// [yTolerance] 是"同一行"的纵坐标容差（归一化 0~1）。
  /// 默认 0.014 ≈ 全图高度的 1.4% —— 清单打印件的行高通常 2%~4%，
  /// 行内 token 的波动更小：1.4% 足以容同行的轻微倾斜，又不会把
  /// 相邻两行粘在一起。行基准 y 用**滑动平均**，抗长行两端轻微上扬。
  ///
  /// 返回的行文本按从上到下、行内从左到右排列，token 之间补空格。
  static List<String> assembleLines(
    List<OcrTokenResult> tokens, {
    double yTolerance = 0.014,
  }) {
    if (tokens.isEmpty) return const [];
    final sorted = [...tokens]..sort((a, b) => a.normCy.compareTo(b.normCy));

    final lines = <List<OcrTokenResult>>[];
    var current = <OcrTokenResult>[];
    var currentY = sorted.first.normCy;

    for (final t in sorted) {
      if (current.isEmpty || (t.normCy - currentY).abs() <= yTolerance) {
        current.add(t);
        currentY =
            (currentY * (current.length - 1) + t.normCy) / current.length;
      } else {
        lines.add(current);
        current = [t];
        currentY = t.normCy;
      }
    }
    if (current.isNotEmpty) lines.add(current);

    return [
      for (final line in lines)
        ((line..sort((a, b) => a.normCx.compareTo(b.normCx)))
              .map((t) => t.text.trim())
              .where((s) => s.isNotEmpty)
              .toList())
            .join(' '),
    ].where((s) => s.isNotEmpty).toList(growable: false);
  }

  // ─────────────────────────────────────────────────────────
  // 行 → 候选货品
  // ─────────────────────────────────────────────────────────

  /// 表头关键词：一行命中 ≥ 2 个就当表头整行跳过。
  /// 命中 1 个不定表头（正文里也可能出现"数量 3 件"这种词）。
  static const _headerKeywords = [
    '编码', '品名', '名称', '数量', '单位', '箱号', '规格', '备注', '序号',
  ];

  /// 编码 token 的形态判断（[_findCodeIdx] 的规则说明）：
  ///  · **字母数字混合**最可信（BOX-001 / BX0012 / A100-3）；
  ///  · 纯数字 ≥ 3 位是备选（货号 10023）—— 但序号列 001 也是这个形态，
  ///    所以只在找不到混合 token 时才用；
  ///  · 纯中文不是编码；纯字母单词也不是（多为英文表头/备注词）。
  static final RegExp _codePattern =
      RegExp(r'^[A-Za-z0-9][A-Za-z0-9\-_/\.]{1,30}$');

  /// 在一行里找编码 token 的下标。找不到返回 null。
  static int? _findCodeIdx(List<String> tokens) {
    int? numeric;
    for (var j = 0; j < tokens.length; j++) {
      final s = toHalfWidth(tokens[j]).trim();
      if (!_codePattern.hasMatch(s)) continue;
      final hasDigit = s.contains(RegExp(r'[0-9]'));
      final hasAlpha = s.contains(RegExp(r'[A-Za-z]'));
      if (hasDigit && hasAlpha) return j; // 混合形态：直接认
      if (hasDigit && s.length >= 3) numeric ??= j; // 纯数字：备选
    }
    return numeric;
  }

  /// 把行文本列表解析成候选货品。
  ///
  /// [existingCodes]：项目里已有的编码 —— 命中的行跳过（与
  /// [ChecklistImporter.parse] 的同款规则：不影响已有照片归属）。
  /// 同一次识别内部的重复编码 → 合并为一件（语义甲，sourceLineCount 计数）。
  static OcrChecklistParseResult parse({
    required List<String> lines,
    Set<String> existingCodes = const {},
    int startRow = 1,
    int defaultRequiredPhotos = 2,
  }) {
    final issues = <ValidationIssue>[];
    final rows = <ChecklistRow>[];
    final mergedIndex = <String, int>{}; // code → rows 下标

    for (var i = 0; i < lines.length; i++) {
      final rawLine = lines[i].trim();
      if (rawLine.isEmpty) continue;
      final lineNo = startRow + i;
      final tokens = rawLine.split(RegExp(r'\s+'));

      // ── 表头行：整行跳过 ──
      final hits = _headerKeywords.where(rawLine.contains).length;
      if (hits >= 2) {
        issues.add(ValidationIssue(
          level: IssueLevel.info,
          row: lineNo,
          message: '「${_snip(rawLine)}」看起来是表头，已跳过',
        ));
        continue;
      }

      // ── 找编码 ──
      final codeIdx = _findCodeIdx(tokens);
      if (codeIdx == null) {
        issues.add(ValidationIssue(
          level: IssueLevel.warning,
          row: lineNo,
          message: '「${_snip(rawLine)}」没认出编码，已跳过 —— 可在预览里手动补录或改用 Excel 导入',
        ));
        continue;
      }

      final code = toHalfWidth(tokens[codeIdx]).trim();

      // ── 品名：行内其余 token 拼接（顺序保持）──
      //  · 独立数字 token（序号/数量）不进品名；
      //  · 其他 token（含箱号字样）保留 —— 宁可品名多些杂质也不吞字，
      //    预览页随时可改。
      final nameTokens = <String>[];
      for (var j = 0; j < tokens.length; j++) {
        if (j == codeIdx) continue;
        final t = tokens[j];
        if (t.isEmpty) continue;
        if (RegExp(r'^[0-9]+$').hasMatch(toHalfWidth(t))) continue;
        nameTokens.add(t);
      }
      final name = nameTokens.join(' ').trim();

      // ── 同一次识别内的重复编码 → 合并 ──
      final at = mergedIndex[code];
      if (at != null) {
        final old = rows[at];
        rows[at] = ChecklistRow(
          sourceRow: old.sourceRow,
          code: old.code,
          codeSafe: old.codeSafe,
          name: old.name ?? (name.isEmpty ? null : name),
          spec: old.spec,
          qty: old.qty,
          unit: old.unit,
          requiredPhotos: old.requiredPhotos,
          container: old.container,
          sourceLineCount: old.sourceLineCount + 1,
          remark: old.remark,
        );
        issues.add(ValidationIssue(
          level: IssueLevel.info,
          row: lineNo,
          message: '编码「$code」重复出现，已合并为一件货',
        ));
        continue;
      }

      // ── 与库里已有编码冲突 → 跳过 ──
      if (existingCodes.contains(code)) {
        issues.add(ValidationIssue(
          level: IssueLevel.warning,
          row: lineNo,
          message: '编码「$code」在本项目中已存在，已跳过（不会影响它已有的照片归属）',
        ));
        continue;
      }

      rows.add(ChecklistRow(
        sourceRow: lineNo,
        code: code,
        codeSafe: safeFileName(code),
        name: name.isEmpty ? null : name,
        requiredPhotos: defaultRequiredPhotos,
      ));
      mergedIndex[code] = rows.length - 1;
    }

    return OcrChecklistParseResult(
      rows: rows,
      issues: issues,
      totalLines: lines.length,
    );
  }

  static String _snip(String s) => s.length <= 16 ? s : '${s.substring(0, 16)}…';
}

/// OCR 清单识别结果（预览确认页的数据源）。
class OcrChecklistParseResult {
  const OcrChecklistParseResult({
    required this.rows,
    required this.issues,
    required this.totalLines,
  });

  /// 候选货品（**未经人工确认** —— 导入前必须过预览页）。
  final List<ChecklistRow> rows;

  final List<ValidationIssue> issues;

  /// 参与识别的总行数（含被跳过的）。
  final int totalLines;
}
