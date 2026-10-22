import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/search/code_matcher.dart';

/// 编码归一化与匹配的测试。
///
/// 这组用例的重点是**"不要误伤合法编码"**。
/// 形近纠偏最容易犯的错误就是把合法的字母词改坏（BOX → B0X）——
/// 一旦发生，匹配率整体下降，而且极难定位原因。
void main() {
  const entries = [
    CodeEntry(itemId: 'i1', code: 'ABC-1024'),
    CodeEntry(itemId: 'i2', code: 'DEF-2001'),
    CodeEntry(itemId: 'i3', code: 'GHI3300'),
    CodeEntry(itemId: 'i4', code: 'BOX-001'),
    CodeEntry(itemId: 'i5', code: 'SIL-2200'),
  ];

  group('normalize —— 基础归一化必须是无损的', () {
    test('大小写差异被抹平', () {
      expect(CodeMatcher.normalize('abc-1024'), CodeMatcher.normalize('ABC-1024'));
    });

    test('分隔符差异被抹平（连字符 / 下划线 / 空格 / 点）', () {
      final base = CodeMatcher.normalize('ABC-1024');
      expect(CodeMatcher.normalize('ABC_1024'), base);
      expect(CodeMatcher.normalize('ABC 1024'), base);
      expect(CodeMatcher.normalize('ABC.1024'), base);
      expect(CodeMatcher.normalize('ABC·1024'), base);
    });

    test('全角转半角', () {
      expect(CodeMatcher.normalize('ＡＢＣ－１０２４'), 'ABC1024');
    });

    test('前后空格被去掉', () {
      expect(CodeMatcher.normalize('  ABC-1024  '), 'ABC1024');
    });

    test('纯字母编码原样保留，不被纠偏（关键回归）', () {
      expect(CodeMatcher.normalize('BOX-001'), 'BOX001');
      expect(CodeMatcher.normalize('SIL-2200'), 'SIL2200');
    });
  });

  group('variants —— 形近纠偏只作为备选变体', () {
    test('原样变体永远排在第一位', () {
      expect(CodeMatcher.variants('ABC-1O24').first, 'ABC1O24');
    });

    test('含可疑形近字符时，额外给出纠偏变体', () {
      expect(CodeMatcher.variants('ABC-1O24'), contains('ABC1024'));
    });

    test('不含可疑字符时不产生额外变体（零额外开销）', () {
      expect(CodeMatcher.variants('ABC-1024').length, 1);
      expect(CodeMatcher.variants('XYZ-9999').length, 1);
    });

    test('整段是字母时不纠偏（避免制造假阳性）', () {
      expect(CodeMatcher.variants('BOX-001').length, 1);
    });
  });

  group('best —— 三级匹配策略', () {
    final m = CodeMatcher(entries);

    test('完全相等 → exact', () {
      final c = m.best('ABC-1024', 1.0)!;
      expect(c.itemId, 'i1');
      expect(c.mode, 'exact');
      expect(c.score, greaterThan(0.9));
    });

    test('OCR 把 0 认成 O → 经纠偏变体仍能 exact 命中', () {
      final c = m.best('ABC-1O24', 1.0)!;
      expect(c.itemId, 'i1');
      expect(c.mode, 'exact');
    });

    test('OCR 把 0/1 认成 O/I → 仍能命中', () {
      final c = m.best('DEF-2OOI', 1.0)!;
      expect(c.itemId, 'i2');
      expect(c.mode, 'exact');
    });

    test('混在字幕里的大段文本 → prefix（清单编码是子串）', () {
      final c = m.best('LOT ABC-1024 QTY', 1.0)!;
      expect(c.itemId, 'i1');
      expect(c.mode, 'prefix');
    });

    test('一个字符错 → edit1', () {
      final c = m.best('ABC-1025', 1.0)!;
      expect(c.itemId, 'i1');
      expect(c.mode, 'edit1');
    });

    test('两个字符错 → edit2，分数明显更低', () {
      final c = m.best('ABC-1030', 1.0)!;
      expect(c.mode, 'edit2');
      expect(c.score, lessThan(0.8));
    });

    test('差得太多 → 不硬凑，返回 null', () {
      expect(m.best('XYZ-9999', 1.0), isNull);
    });

    test('太短的 token 是噪声，不参与匹配', () {
      expect(m.best('AB', 1.0), isNull);
      expect(m.best('A1', 1.0), isNull);
    });

    test('token 自身置信度会等比拉低总分', () {
      final hi = m.best('ABC-1024', 0.95)!;
      final lo = m.best('ABC-1024', 0.40)!;
      expect(lo.score, lessThan(hi.score));
      expect(lo.score / hi.score, closeTo(0.40 / 0.95, 0.01));
    });

    test('只有高置信 exact 才可能突破 0.90（"一键确认"的天然护栏）', () {
      final best = m.best('ABC-1024', 0.95)!;
      expect(best.score, greaterThan(0.90));

      // edit1 再怎么高，也够不到 0.90
      final e1 = m.best('ABC-1025', 1.0)!;
      expect(e1.score, lessThan(0.90));
    });

    test('空字典不崩，返回 null', () {
      expect(CodeMatcher(const []).best('ABC-1024', 1.0), isNull);
    });
  });

  group('search —— 改派面板的候选检索', () {
    final m = CodeMatcher(entries);

    test('前缀命中排在包含命中之前', () {
      expect(m.search('DE').first.itemId, 'i2');
    });

    test('输入带分隔符也能搜到（先归一化再比）', () {
      final r = m.search('abc 102');
      expect(r.map((e) => e.itemId), contains('i1'));
    });

    test('空关键词返回字典前若干个', () {
      expect(m.search('').length, entries.length);
    });

    test('limit 生效', () {
      expect(m.search('', limit: 2).length, 2);
    });
  });

  group('levenshtein', () {
    test('相同字符串 → 0', () => expect(levenshtein('abc', 'abc'), 0));
    test('一次替换 → 1', () => expect(levenshtein('abc', 'abd'), 1));
    test('一次插入 → 1', () => expect(levenshtein('abc', 'abxc'), 1));
    test('一次删除 → 1', () => expect(levenshtein('abc', 'ac'), 1));
    test('超出 cap 时提前返回 cap+1', () {
      expect(levenshtein('abcdef', 'xyzuvw', cap: 2), 3);
    });
    test('长度差大于 cap 时立即返回（不做无谓计算）', () {
      expect(levenshtein('a', 'abcdefgh', cap: 2), 3);
    });
  });
}
