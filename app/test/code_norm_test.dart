import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/search/code_norm.dart';

/// 编码规范化与四级匹配的契约测试（2026-10-15 v0.24.0）。
///
/// 钉的是**现场的输入习惯**，不是字符串函数的实现细节：
///   · 人写的编码五花八门（连字符、空格、全角、大小写）；
///   · 人记得住的往往**不是完整编码** —— 是后几位、或中间几位
///     （老板 2026-10-15 反馈：「更多的是用编码后几位，或中间几位」）。
///
/// 这两条一旦被"顺手优化"掉，搜索就变成摆设，所以全部钉死。
void main() {
  group('normalizeCode', () {
    test('连字符 / 空格 / 大小写 / 全角 全部归一', () {
      expect(normalizeCode('ABC-123'), 'ABC123');
      expect(normalizeCode('abc 123'), 'ABC123');
      expect(normalizeCode('ＡＢＣ－１２３'), 'ABC123');
      expect(normalizeCode(' abc_123 '), 'ABC123');
      expect(normalizeCode('ABC.123'), 'ABC123');
    });

    test('中文顿号与斜杠同样视为排版（现场唛头常这么印）', () {
      expect(normalizeCode('ABC、123'), 'ABC123');
      expect(normalizeCode('ABC/123'), 'ABC123');
    });

    test('空串与全是分隔符 → 空串', () {
      expect(normalizeCode(''), '');
      expect(normalizeCode('---'), '');
    });
  });

  group('matchKind', () {
    test('精确', () {
      expect(matchKind('ABC123', 'ABC123'), CodeMatchKind.exact);
      // 输入侧的写法差异不影响判定（规范化在前，匹配在后）
      expect(matchKind('ABC123', normalizeCode('abc-123')),
          CodeMatchKind.exact);
    });

    test('后几位（后缀）—— 现场第一场景', () {
      expect(matchKind('ABC123', '123'), CodeMatchKind.suffix);
      expect(matchKind('ABC123', 'C123'), CodeMatchKind.suffix);
    });

    test('中间几位（包含）—— 现场第二场景', () {
      expect(matchKind('ABC123', 'BC12'), CodeMatchKind.contains);
      expect(matchKind('ABC123', 'C1'), CodeMatchKind.contains);
    });

    test('前几位（前缀）', () {
      expect(matchKind('ABC123', 'ABC'), CodeMatchKind.prefix);
    });

    test('没命中', () {
      expect(matchKind('ABC123', '99'), CodeMatchKind.none);
      expect(matchKind('ABC123', 'ABCD'), CodeMatchKind.none);
    });

    test('空查询一律不命中（空串能被任何串包含，那不是搜索）', () {
      expect(matchKind('ABC123', ''), CodeMatchKind.none);
    });

    test('首尾都能匹配时按后缀算 —— 尾部流水号是主要记忆点', () {
      // 'A1A' 的 'A' 既在前也在后；后几位优先（现场反馈）
      expect(matchKind('A1A', 'A'), CodeMatchKind.suffix);
    });

    test('排序权重：精确 > 后缀 > 前缀 > 包含', () {
      expect(
        CodeMatchKind.exact.weight,
        greaterThan(CodeMatchKind.suffix.weight),
      );
      expect(
        CodeMatchKind.suffix.weight,
        greaterThan(CodeMatchKind.prefix.weight),
      );
      expect(
        CodeMatchKind.prefix.weight,
        greaterThan(CodeMatchKind.contains.weight),
      );
      expect(CodeMatchKind.none.weight, 0);
      expect(CodeMatchKind.none.matched, isFalse);
    });
  });

  group('highlightRangeInRaw', () {
    test('定位到**原文**下标（跳过被规范化丢掉的连字符）', () {
      final r = highlightRangeInRaw('ABC-123', '123');
      expect(r, isNotNull);
      expect(r!.start, 4);
      expect(r.end, 7);
      expect('ABC-123'.substring(r.start, r.end), '123');
    });

    test('全角输入也能在半角原文里定位', () {
      final r = highlightRangeInRaw('ABC-123', '１２３');
      expect(r, isNotNull);
      expect('ABC-123'.substring(r!.start, r.end), '123');
    });

    test('命中中间几位同样能定位', () {
      // 原文里 'BC' 与 '1' 之间隔着被丢掉的 '-'，所以区间含 '-'
      final r = highlightRangeInRaw('ABC-123', 'bc1');
      expect(r, isNotNull);
      expect('ABC-123'.substring(r!.start, r.end), 'BC-1');
    });

    test('没命中返回 null（UI 正常显示，不高亮）', () {
      expect(highlightRangeInRaw('ABC-123', 'zz'), isNull);
      expect(highlightRangeInRaw('ABC-123', ''), isNull);
    });
  });

  group('kMinCodeQueryLength', () {
    test('最小 2 位 —— 1 位会命中半个库', () {
      expect(kMinCodeQueryLength, 2);
    });
  });
}
