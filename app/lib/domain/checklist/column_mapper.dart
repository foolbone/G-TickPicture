import '../model/enums.dart';
import 'checklist_file_reader.dart';

/// 一份列映射方案。
class ColumnMapping {
  const ColumnMapping({required this.headerRow, required this.columns});

  const ColumnMapping.empty() : headerRow = 0, columns = const {};

  /// 表头所在行（0-based）
  final int headerRow;

  /// 系统字段 → 该字段在表格里的列下标
  final Map<ChecklistField, int> columns;

  bool get isValid => columns.containsKey(ChecklistField.itemCode);

  int? operator [](ChecklistField f) => columns[f];

  ColumnMapping withField(ChecklistField field, int? column) {
    final next = Map<ChecklistField, int>.from(columns);
    if (column == null) {
      next.remove(field);
    } else {
      // 一个列不能同时映射到两个字段
      next.removeWhere((_, v) => v == column);
      next[field] = column;
    }
    return ColumnMapping(headerRow: headerRow, columns: next);
  }

  ColumnMapping withHeaderRow(int row) =>
      ColumnMapping(headerRow: row, columns: columns);
}

/// 列映射推断。
///
/// 客户给的清单表头写法千奇百怪（"货号/料号/产品编号/SKU/item no."），
/// 但 90% 能靠关键词命中。命中不了的让人手动点一下 —— 这就是 §5.1 STEP 3 的价值。
class ColumnMapper {
  const ColumnMapper._();

  /// 每个系统字段的识别关键词。**顺序有意义**：更具体的放前面。
  static const Map<ChecklistField, List<String>> keywords = {
    ChecklistField.requiredPhotos: ['要求张数', '需要张数', '照片张数', '照片数', '张数'],
    ChecklistField.itemCode: [
      // 'modelnumber'/'modelno'：真实清单（PIDU9352234）的编码列就叫
      // Model Number，列内容是 103006010017BM 这类货品编码。放最前面 ——
      // 完整词精确命中得 100 分，能压住 spec 关键词 'model' 的 contains 50 分。
      // ⚠️ 不能只加 'model'（会和规格列抢，且 'model' 本身不含 'no'/'code'
      //    子串，靠通用词根本命中不了这列表头）。
      'modelnumber', 'modelno',
      '货品编码', '商品编码', '产品编码', '物料编码', '货物编码', '产品编号',
      '商品编号', '物料编号', '货号', '料号', '物料号', '编码', '编号',
      'sku', 'itemcode', 'itemno', 'item', 'code', 'no',
    ],
    ChecklistField.name: [
      '货品名称', '商品名称', '产品名称', '货物名称', '物料名称', '品名', '名称',
      '描述', 'description', 'productname', 'name',
    ],
    ChecklistField.spec: ['规格型号', '规格', '型号', '规格描述', 'spec', 'model', 'type'],
    ChecklistField.qty: ['数量', '件数', '总数量', 'qty', 'quantity', 'pcs', 'qty(pcs)'],
    ChecklistField.unit: ['单位', '计量单位', 'unit'],
    // 包装箱（P4 诉求 1）。**顺序有意义**：更具体的放前面 ——
    // `_score` 里 header == k 得 100 分，所以「包装箱号」这种精确词
    // 必须先于「箱」出现，否则短词会先命中。
    ChecklistField.container: [
      '包装箱号', '包装箱', '装箱号', '外箱号', '箱号', '箱型', '箱',
      '柜号', '容器号', '托盘号', '卡板号',
      'carton', 'cartonno', 'box', 'boxno', 'case', 'caseno',
      'container', 'pallet', 'ctn',
    ],
    ChecklistField.remark: ['备注', '说明', 'remark', 'remarks', 'note', 'comment'],
  };

  /// 从表格里挑出最可能的表头行，并建立列映射。
  static ColumnMapping autoDetect(SheetGrid grid, {int scanRows = 20}) {
    if (grid.rows.isEmpty) return const ColumnMapping.empty();

    var bestRow = 0;
    var bestScore = -1;

    final limit = grid.rows.length < scanRows ? grid.rows.length : scanRows;
    for (var r = 0; r < limit; r++) {
      final row = grid.rows[r];
      final matchedFields = <ChecklistField>{};
      for (final cell in row) {
        final h = _norm(cell);
        if (h.isEmpty) continue;
        for (final entry in keywords.entries) {
          if (entry.value.any((k) => _norm(k) == h || h.contains(_norm(k)))) {
            matchedFields.add(entry.key);
          }
        }
      }
      // 表头行至少命中 2 个不同字段才认（单命中可能是数据行里恰好含"编号"字样）
      final score = matchedFields.length;
      if (score > bestScore) {
        bestScore = score;
        bestRow = r;
      }
    }
    if (bestScore < 2) bestRow = 0;

    return forHeaderRow(grid, bestRow);
  }

  /// 按**指定的表头行**重新建立列映射。
  ///
  /// 用户手动改"表头在第 N 行"时必须走这条 ——
  /// 只改 headerRow 而沿用旧 columns 的话，列映射会停留在原来那一行，
  /// 出现"表头变了但映射没变"的错位。
  static ColumnMapping forHeaderRow(SheetGrid grid, int row) {
    if (row < 0 || row >= grid.rows.length) return const ColumnMapping.empty();
    return ColumnMapping(
      headerRow: row,
      columns: _matchColumns(grid.rows[row]),
    );
  }

  static Map<ChecklistField, int> _matchColumns(List<String?> header) {
    // 收集所有 (字段, 列, 得分)
    final cands = <_Cand>[];
    for (var c = 0; c < header.length; c++) {
      final h = _norm(header[c]);
      if (h.isEmpty) continue;
      for (final entry in keywords.entries) {
        final s = _score(h, entry.value);
        if (s > 0) cands.add(_Cand(entry.key, c, s));
      }
    }
    // 高分优先分配；一个字段、一个列各只能用一次
    cands.sort((a, b) => b.score.compareTo(a.score));
    final usedFields = <ChecklistField>{};
    final usedCols = <int>{};
    final out = <ChecklistField, int>{};
    for (final cd in cands) {
      if (usedFields.contains(cd.field) || usedCols.contains(cd.col)) continue;
      out[cd.field] = cd.col;
      usedFields.add(cd.field);
      usedCols.add(cd.col);
    }
    return out;
  }

  static int _score(String header, List<String> kws) {
    var best = 0;
    for (final kw in kws) {
      final k = _norm(kw);
      if (k.isEmpty) continue;
      final s = switch (true) {
        _ when header == k => 100,
        _ when header.endsWith(k) => 80,
        _ when header.startsWith(k) => 70,
        _ when header.contains(k) => 50,
        _ => 0,
      };
      if (s > best) best = s;
    }
    return best;
  }

  /// 归一化：去空白/标点、全角转半角、转小写。用于表头比对。
  ///
  /// ⚠️ 2026-09-23 修：原来用 `RegExp(r'[\s\-_/\\.,:;()（）\[\]【】、。：]')`
  /// **逐字符**过滤。Dart 的 `\s` 匹配 Unicode 空白，而 `\u00A0`（NBSP）
  /// 与 `\u3000`（全角空格）都在其中 —— 单独取出来匹配没问题，
  /// 但它们属于**多字节**，用单字符正则逐个 rune 过滤是对的……
  /// 真正的问题是 `\s` 还会吃掉 `\u200B` 之类零宽字符没人注意。
  /// 这里改成先 `trim` + 全角转半角，再统一剥标点，语义更直白。
  static String _norm(String? raw) {
    if (raw == null) return '';
    // 先全角转半角（NBSP 也顺手换成普通空格），再逐字符剥掉分隔符。
    final flat = toHalfWidth(raw.trim())
        .replaceAll('\u00A0', ' ')
        .replaceAll('\u3000', ' ');
    final sb = StringBuffer();
    for (final rune in flat.toLowerCase().runes) {
      final c = String.fromCharCode(rune);
      if (RegExp(r'[\s\-_/\\.,:;()（）\[\]【】、。：]').hasMatch(c)) continue;
      sb.write(c);
    }
    return sb.toString();
  }
}

class _Cand {
  _Cand(this.field, this.col, this.score);
  final ChecklistField field;
  final int col;
  final int score;
}

/// 全角 → 半角。清单里混入全角字符是常态，早归一化早省事。
String toHalfWidth(String s) {
  final sb = StringBuffer();
  for (final rune in s.runes) {
    if (rune == 0x3000) {
      sb.write(' ');
    } else if (rune >= 0xFF01 && rune <= 0xFF5E) {
      sb.writeCharCode(rune - 0xFEE0);
    } else {
      sb.writeCharCode(rune);
    }
  }
  return sb.toString();
}
