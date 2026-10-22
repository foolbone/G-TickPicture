/// 清单里的一条编码。
class CodeEntry {
  const CodeEntry({required this.itemId, required this.code});

  final String itemId;
  final String code;
}

/// 一次匹配的结果。
class MatchCandidate {
  const MatchCandidate({
    required this.itemId,
    required this.score,
    required this.mode,
    this.matchedToken,
  });

  final String itemId;

  /// 0.0~1.0。已含 token 自身置信度；位置/字号权重在合成阶段再乘。
  final double score;

  /// exact / prefix / edit1 / edit2
  final String mode;

  /// 命中的原始 token 文本，用于在 UI 上展示"依据"
  final String? matchedToken;

  MatchCandidate scaled(double factor) => MatchCandidate(
        itemId: itemId,
        score: (score * factor).clamp(0.0, 1.0),
        mode: mode,
        matchedToken: matchedToken,
      );

  @override
  String toString() => 'Match($itemId, ${score.toStringAsFixed(2)}, $mode)';
}

/// 编码归一化与匹配（设计方案 §7.2）。
///
/// ═══════════════════════════════════════════════════════════════
/// 设计要点：**索引用基础归一化，形近纠偏只作为"匹配变体"**。
///
/// 最初的想法是把形近纠偏（O→0、I→1）也做进 normalize 里，
/// 但那样做有两个问题：
///   ① 索引会被改写 —— 合法的 `BOX001` 可能变成 `B0X001`，
///      不同编码归一化后还可能撞车，索引里悄悄少掉一条
///   ② 无法区分"OCR 认错了"和"编码本来就是这样"
///
/// 现在的做法：词典索引只做无损归一化（大小写/全角/分隔符）；
/// 匹配时，若 token 含可疑形近字符，**额外生成一个纠偏变体**一起试。
/// 因为**未经纠偏的变体永远先试**，合法编码不会被误伤 ——
/// 纠偏只在"原样匹配不上"时才发挥作用。
/// ═══════════════════════════════════════════════════════════════
///
/// 这个类**只产出建议**。它的返回值永远不会被直接写进 `item_id` ——
/// 那条路只能由 `AssignService` 走，且必须有人确认。
///
/// 纯函数、无 IO、无数据库依赖，可完整单测。
class CodeMatcher {
  CodeMatcher(List<CodeEntry> entries)
      : _index = {
          for (final e in entries) normalize(e.code): e,
        },
        _all = entries;

  /// 归一化编码 → 条目（若多条编码归一化后相同，保留清单里第一条）
  final Map<String, CodeEntry> _index;
  final List<CodeEntry> _all;

  bool get isEmpty => _all.isEmpty;

  // ═══════════════════════════════════════════════════════════
  // 归一化
  // ═══════════════════════════════════════════════════════════

  /// 基础归一化：全角→半角 → 大写 → 去空白与分隔符差异。
  ///
  /// **无损、可逆意图**：不改变任何字符的字母/数字身份，
  /// 只是把"同一条编码的不同写法"折叠成同一个 key。
  /// 所以 `ABC-1024`、`ABC_1024`、`ＡＢＣ－１０２４` 会归一化成同一个。
  ///
  /// 注意顺序：**必须先做全角转换，再删分隔符**。
  /// 反过来的话，全角的 `－` 会躲过删除、转换后残留成 `-`。
  static String normalize(String raw) {
    var s = toHalfWidth(raw.trim()).toUpperCase();
    // ⚠️ 半角 `.` 必须显式列出 —— 字符类里 `.` 虽是字面量，但早期版本只写了
    // 全角 `．`，导致 `ABC.1024` 归一化后仍是 `ABC.1024`，与 `ABC1024` 对不上。
    s = s.replaceAll(RegExp(r'[\s\-_·．。,，、/\\.]'), '');
    return s;
  }

  /// 形近纠偏的替换表。
  ///
  /// 刻意**只保留印刷体标签上最高频的混淆对**：O↔0、I↔1、L↔1、S↔5。
  /// 没有把 D→0、B→8、Z→2、G→6 这类收进来 ——
  /// 它们的混淆概率低得多，而一旦误替换，会把本来正确的 token
  /// 推进另一个编码的编辑距离内，制造假阳性建议。
  ///
  /// ⚠️ 这张表必须按**真实标签样本实测的混淆矩阵**来定（设计方案 Q1）。
  /// 拿到 20~30 张真实照片跑完 POC 后替换它，而不是靠直觉加行。
  static const Map<String, String> confusables = {
    'O': '0',
    'I': '1',
    'L': '1',
    'S': '5',
  };

  /// 生成匹配用的变体列表。第一个永远是"原样的基础归一化结果"。
  ///
  /// 只有含可疑形近字符时才返回第二个变体 ——
  /// 纯数字或纯无关字母的 token 不产生额外开销。
  static List<String> variants(String raw) {
    final basic = normalize(raw);
    final fixed = _applyConfusables(basic);
    return fixed == basic ? <String>[basic] : <String>[basic, fixed];
  }

  /// 只在「至少含一个数字、且长度 ≥2 的连续段」里替换形近字符。
  ///
  /// 这里刻意**不做"数字占多数"的严格判定**（早先试过，会把
  /// `GHI33OO` 这类段判为非数字段而漏掉纠偏）。
  /// 因为纠偏结果只作为"备选变体"，原样变体永远先试，
  /// 所以放宽条件是安全的 —— 代价只是多算一次查表。
  static String _applyConfusables(String s) {
    final buf = StringBuffer();
    final segRe = RegExp('[0-9${confusables.keys.join()}]+');
    var i = 0;
    while (i < s.length) {
      final m = segRe.matchAsPrefix(s, i);
      if (m != null && m.group(0)!.length >= 2) {
        final seg = m.group(0)!;
        final hasDigit = seg.split('').any((c) => '0123456789'.contains(c));
        if (hasDigit) {
          // 段内同时有字母和数字时，优先按"数字误认成字母"处理
          buf.write(seg.split('').map((c) => confusables[c] ?? c).join());
        } else {
          buf.write(seg);
        }
        i += seg.length;
      } else {
        buf.write(s[i]);
        i++;
      }
    }
    return buf.toString();
  }

  static String toHalfWidth(String s) {
    final sb = StringBuffer();
    for (final r in s.runes) {
      if (r == 0x3000) {
        sb.write(' ');
      } else if (r >= 0xFF01 && r <= 0xFF5E) {
        sb.writeCharCode(r - 0xFEE0);
      } else {
        sb.writeCharCode(r);
      }
    }
    return sb.toString();
  }

  // ═══════════════════════════════════════════════════════════
  // 匹配
  // ═══════════════════════════════════════════════════════════

  /// 对一段 OCR 文本求最佳命中。返回 null 表示没找到像样的候选。
  ///
  /// 三级策略（§7.2），每级都对所有变体分别尝试，取最高分：
  ///   ① 完全相等        → base 0.98
  ///   ② 清单编码是子串  → base 0.86
  ///   ③ 编辑距离 1 / 2  → base 0.88 / 0.72
  MatchCandidate? best(String tokenText, double tokenConf) {
    if (_all.isEmpty) return null;

    MatchCandidate? bestCand;
    for (final v in variants(tokenText)) {
      if (v.length < 3) continue; // 太短的 token 是噪声
      final c = _bestForVariant(v, tokenText, tokenConf);
      if (c != null && (bestCand == null || c.score > bestCand.score)) {
        bestCand = c;
      }
    }
    return bestCand;
  }

  MatchCandidate? _bestForVariant(
    String n,
    String tokenText,
    double tokenConf,
  ) {
    // ① 完全相等
    final hit = _index[n];
    if (hit != null) {
      return MatchCandidate(
        itemId: hit.itemId,
        score: (0.98 * tokenConf).clamp(0.0, 1.0),
        mode: 'exact',
        matchedToken: tokenText,
      );
    }

    // ② 清单编码是 token 的子串（照片上多识别出前后缀，如 "LOT ABC-1024 QTY"）
    for (final e in _index.entries) {
      if (e.key.length >= 4 && n.contains(e.key)) {
        return MatchCandidate(
          itemId: e.value.itemId,
          score: (0.86 * tokenConf).clamp(0.0, 1.0),
          mode: 'prefix',
          matchedToken: tokenText,
        );
      }
    }

    // ③ 编辑距离 ≤ 2（先用长度差预筛，避免对全表算 DP）
    MatchCandidate? bestCand;
    for (final e in _index.entries) {
      final lenDiff = (e.key.length - n.length).abs();
      if (lenDiff > 2) continue;
      final d = levenshtein(n, e.key, cap: 2);
      if (d == 0 || d > 2) continue;
      final base = d == 1 ? 0.88 : 0.72;
      final c = MatchCandidate(
        itemId: e.value.itemId,
        score: (base * tokenConf).clamp(0.0, 1.0),
        mode: 'edit$d',
        matchedToken: tokenText,
      );
      if (bestCand == null || c.score > bestCand.score) bestCand = c;
    }
    return bestCand;
  }

  /// 候选检索（供整理页"改派"面板使用）：前缀优先，其次包含。
  ///
  /// M1 直接用线性扫描（几千条足够快）；
  /// 若清单到万级，再换成常驻内存的 Trie（§8.1 要求 ≤80ms）。
  List<CodeEntry> search(String keyword, {int limit = 30}) {
    final k = normalize(keyword);
    if (k.isEmpty) return _all.take(limit).toList();

    final starts = <CodeEntry>[];
    final contains = <CodeEntry>[];
    for (final e in _all) {
      final n = normalize(e.code);
      if (n.startsWith(k)) {
        starts.add(e);
        if (starts.length >= limit) break;
      } else if (n.contains(k)) {
        contains.add(e);
      }
    }
    return <CodeEntry>[...starts, ...contains].take(limit).toList();
  }
}

/// 带提前退出的编辑距离。
///
/// [cap] 之外的距离一律返回 `cap + 1` —— 我们只关心"≤2"，
/// 没必要把整张 DP 表算完（清单几千条时这一步是热点）。
int levenshtein(String a, String b, {int cap = 2}) {
  if (a == b) return 0;
  if ((a.length - b.length).abs() > cap) return cap + 1;

  final la = a.length, lb = b.length;
  var prev = List<int>.generate(lb + 1, (i) => i);
  var cur = List<int>.filled(lb + 1, 0);

  for (var i = 1; i <= la; i++) {
    cur[0] = i;
    var rowMin = cur[0];
    for (var j = 1; j <= lb; j++) {
      final cost = a.codeUnitAt(i - 1) == b.codeUnitAt(j - 1) ? 0 : 1;
      var v = prev[j - 1] + cost;
      final del = prev[j] + 1;
      final ins = cur[j - 1] + 1;
      if (del < v) v = del;
      if (ins < v) v = ins;
      cur[j] = v;
      if (v < rowMin) rowMin = v;
    }
    if (rowMin > cap) return cap + 1; // 整行都超了，后面只会更大
    final tmp = prev;
    prev = cur;
    cur = tmp;
  }
  return prev[lb] > cap ? cap + 1 : prev[lb];
}
