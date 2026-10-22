/// 产品编码的**规范化**与**子串匹配分级**（2026-10-15 v0.24.0）。
///
/// 现场的真实检索动作不是「输完整编码」，而是：
///   · 只记得**后几位**（唛头被挡住，尾部流水号最常被记住）；
///   · 只记得**中间几位**（首尾都看不清）；
///   · 写得五花八门：`ABC-123` / `abc 123` / `ＡＢＣ－１２３`。
///
/// 所以这里做两件事，且**只在这里做**（查询侧 SQL 不参与 —— SQLite 表达
/// 不了全角转换，也用不上后缀/中间匹配的索引）：
///   1. 把所有写法归一到同一个串，让 `ABC-123` ≡ `abc123`；
///   2. 把「命中方式」分成四级，供结果排序与 UI 标注。
///
/// 纯函数、无依赖、不碰数据库 —— 可以直接单测（test/code_norm_test.dart）。
library;

/// 编码的命中方式。**顺序即排序权重**（大 = 更相关）。
enum CodeMatchKind {
  /// 完全相等（去掉分隔符后逐字符相同）。
  exact,

  /// 后缀：`ABC123` 输 `123`。
  ///
  /// 现场最常见 —— 记忆锚在编码尾部的流水号上，所以权重高于前缀。
  suffix,

  /// 前缀：`ABC123` 输 `ABC`。
  prefix,

  /// 包含（中间几位）：`ABC123` 输 `BC12`。
  contains,

  /// 没命中。
  none,
}

/// [CodeMatchKind] 的排序权重（大 = 更相关）。
extension CodeMatchKindWeight on CodeMatchKind {
  /// 权重值：exact 4 / suffix 3 / prefix 2 / contains 1 / none 0。
  int get weight => switch (this) {
        CodeMatchKind.exact => 4,
        CodeMatchKind.suffix => 3,
        CodeMatchKind.prefix => 2,
        CodeMatchKind.contains => 1,
        CodeMatchKind.none => 0,
      };

  /// 是否算命中。
  bool get matched => this != CodeMatchKind.none;
}

/// 发起一次检索的**最小输入长度**。
///
/// 1 个字符的包含匹配会命中半个库（`1` 在成千上万个编码里都出现），
/// 结果没有意义，反而让人以为「搜出来一堆垃圾」。UI 在不足 2 位时
/// 直接不发起查询并给出提示。
const int kMinCodeQueryLength = 2;

/// 规范化后的串，以及它每个字符在**原文**里的下标。
///
/// 保留下标是为了 UI 能把命中的那几位在**原文**上标出来 ——
/// 显示给用户的是 `ABC-123`（原文），匹配发生在 `ABC123`（规范化后），
/// 没有这层映射就只能高亮"大概位置"，或干脆显示规范化后的串（更难认）。
class NormalizedCode {
  /// 构造一条规范化结果。
  const NormalizedCode(this.norm, this.originIndex);

  /// 规范化后的文本（全角已转半角、分隔符已去掉、字母已大写）。
  final String norm;

  /// `originIndex[i]` = `norm[i]` 在原文中的下标。
  final List<int> originIndex;

  /// 是否为空串。
  bool get isEmpty => norm.isEmpty;
}

/// 归一化规则中**被丢弃**的字符（视为「只是排版」，不参与比对）。
///
/// 只丢这些：空白、各类连字符与分隔标点。其余字符保留 —— 编码里可能
/// 出现 `/` 之外的业务符号，宁可多留也别把有效字符吃掉。
bool _isSeparator(int unit) {
  // 各类空白（含全角空格 0x3000）
  if (unit == 0x20 || unit == 0x09 || unit == 0x0A || unit == 0x0D) return true;
  if (unit == 0x0B || unit == 0x0C || unit == 0x3000) return true;
  return switch (unit) {
    // - – — _ . / \ : 、, ，; ；· # ( ) [ ] { } | ' "
    0x2D || 0x2013 || 0x2014 || 0x5F || 0x2E || 0x2F || 0x5C || 0x3A ||
    0x3001 || 0x2C || 0xFF0C || 0x3B || 0xFF1B || 0xB7 || 0x23 || 0x28 ||
    0x29 || 0x5B || 0x5D || 0x7B || 0x7D || 0x7C || 0x27 || 0x22 =>
      true,
    _ => false,
  };
}

/// 把 [raw] 规范化：全角→半角、丢分隔符、转大写。
///
/// `ABC-123` / `abc 123` / `ＡＢＣ－１２３` 全部 → `ABC123`。
String normalizeCode(String raw) => _normalize(raw).norm;

/// 同 [normalizeCode]，但连「每个字符在原文里的下标」一起返回
/// （供 [highlightRangeInRaw] 做原文高亮）。
NormalizedCode _normalize(String raw) {
  final sb = StringBuffer();
  final map = <int>[];
  for (var i = 0; i < raw.length; i++) {
    var unit = raw.codeUnitAt(i);
    // 全角 ！-～ → 半角 !-~
    if (unit >= 0xFF01 && unit <= 0xFF5E) unit -= 0xFEE0;
    if (_isSeparator(unit)) continue;
    // 小写 → 大写（只处理 ASCII 段，其余原样）
    if (unit >= 0x61 && unit <= 0x7A) unit -= 0x20;
    sb.writeCharCode(unit);
    map.add(i);
  }
  return NormalizedCode(sb.toString(), map);
}

/// 判定 [normCode]（已规范化）与查询串 [normQuery]（已规范化）的命中方式。
///
/// 判定顺序：**精确 → 后缀 → 前缀 → 包含**。后缀排在前面，是因为
/// 「只记得后几位」是现场第一场景（老板 2026-10-15 反馈）。
///
/// 空查询串一律 [CodeMatchKind.none] —— 空串能被任何串"包含"，
/// 那会退化成「列出全部照片」，不是搜索。
CodeMatchKind matchKind(String normCode, String normQuery) {
  if (normQuery.isEmpty || normCode.isEmpty) return CodeMatchKind.none;
  if (normCode == normQuery) return CodeMatchKind.exact;
  if (normCode.endsWith(normQuery)) return CodeMatchKind.suffix;
  if (normCode.startsWith(normQuery)) return CodeMatchKind.prefix;
  if (normCode.contains(normQuery)) return CodeMatchKind.contains;
  return CodeMatchKind.none;
}

/// 在**原文** [raw] 里定位查询串 [rawQuery] 命中片段的下标区间。
///
/// 返回 `[start, end)`（end  exclusive）；找不到返回 null
/// （此时 UI 正常显示不高亮，而不是报错）。
///
/// 例：`highlightRangeInRaw('ABC-123', '123')` → `(4, 7)`。
({int start, int end})? highlightRangeInRaw(String raw, String rawQuery) {
  final n = _normalize(raw);
  final q = normalizeCode(rawQuery);
  if (q.isEmpty || n.norm.isEmpty) return null;
  final at = n.norm.indexOf(q);
  if (at < 0) return null;
  final start = n.originIndex[at];
  final last = n.originIndex[at + q.length - 1];
  return (start: start, end: last + 1);
}
