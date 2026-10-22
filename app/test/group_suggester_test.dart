import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/search/code_matcher.dart';
import 'package:g_tick_picture/domain/suggest/group_suggester.dart';
import 'package:g_tick_picture/domain/suggest/suggest_thresholds.dart';

/// [GroupSuggester] 的纯函数测试 —— §5.3.2 第 4~6 步的合成算法。
///
/// 阈值语义钉死三条：
///  1. 置信度只用于排序与标冲突，任何阈值都不能让机器拿到归属；
///  2. conflict = 第二名平均分距胜者 < 0.15（建议照给，UI 提醒）；
///  3. no_suggestion = 胜者平均分 < 0.40（不给建议，必须手动）。
void main() {
  CodeMatcher matcherOf(Map<String, String> codeById) => CodeMatcher([
        for (final e in codeById.entries)
          CodeEntry(itemId: e.key, code: e.value),
      ]);

  SuggestToken tk(String text,
          {double conf = 1.0, double weight = 1.0}) =>
      SuggestToken(text: text, ocrConf: conf, positionWeight: weight);

  PhotoTokens photo(String id, List<SuggestToken> tokens) =>
      PhotoTokens(photoId: id, tokens: tokens);

  group('单张命中', () {
    test('exact 命中、中心位置 → pending，置信 = 0.98', () {
      final m = matcherOf({'item-a': 'BOX-001'});
      final s = GroupSuggester.suggest(
        photos: [photo('p1', [tk('BOX-001')])],
        matcher: m,
      );
      expect(s.itemId, 'item-a');
      expect(s.confidence, closeTo(0.98, 1e-9));
      expect(s.state, 'pending');
      expect(s.evidence, ['张1:exact(0.98)']);
    });

    test('OCR 置信度等比拉低得分', () {
      final m = matcherOf({'item-a': 'BOX-001'});
      final s = GroupSuggester.suggest(
        photos: [photo('p1', [tk('BOX-001', conf: 0.5)])],
        matcher: m,
      );
      expect(s.confidence, closeTo(0.49, 1e-9));
    });

    test('边缘位置打 0.85 折（经位置权重函数）', () {
      final w = SuggestWeights.positionWeight(cx: 0.0, cy: 0.5);
      expect(w, closeTo(0.85, 1e-9));
      final m = matcherOf({'item-a': 'BOX-001'});
      final s = GroupSuggester.suggest(
        photos: [photo('p1', [tk('BOX-001', weight: w)])],
        matcher: m,
      );
      expect(s.confidence, closeTo(0.98 * 0.85, 1e-9));
    });
  });

  group('组级投票', () {
    test('两张同货品 → 平均分口径（不是累加虚高）', () {
      final m = matcherOf({'item-a': 'BOX-001'});
      final s = GroupSuggester.suggest(
        photos: [
          photo('p1', [tk('BOX-001')]),
          photo('p2', [tk('BOX-001', conf: 0.5)]),
        ],
        matcher: m,
      );
      // (0.98 + 0.49) / 2 —— 如实反映「一张清楚一张糊」。
      expect(s.confidence, closeTo((0.98 + 0.49) / 2, 1e-9));
      expect(s.state, 'pending');
    });

    test('同一张里同货品两个 token 只算一票（取最高）', () {
      final m = matcherOf({'item-a': 'BOX-001'});
      final s = GroupSuggester.suggest(
        photos: [
          photo('p1', [tk('BOX-001'), tk('BOX-001', conf: 0.3)]),
        ],
        matcher: m,
      );
      // 若重复计票会虚高到 0.98 + 0.294 = 1.274 > 1。
      expect(s.confidence, closeTo(0.98, 1e-9));
    });

    test('组内识别出不同编码且差距 < 0.15 → conflict（建议照给胜者）', () {
      // 两张照片各 exact 命中不同货品（混拍/聚类错都会这样）——
      // 组级两票并列，差距 0 < 0.15 → conflict。
      final m = matcherOf({'item-a': 'BOX-001', 'item-b': 'BOX-002'});
      final s = GroupSuggester.suggest(
        photos: [
          photo('p1', [tk('BOX-001')]),
          photo('p2', [tk('BOX-002')]),
        ],
        matcher: m,
      );
      expect(s.itemId, isNotNull);
      expect(s.state, 'conflict');
      expect(s.confidence, closeTo(0.98, 1e-9));
      expect(s.candidates.map((c) => c.itemId),
          containsAll(['item-a', 'item-b']));
    });

    test('第二名距胜者 ≥ 0.15 → 不标冲突', () {
      // photo1 exact 0.98（item-a）；photo2 OCR 置信 0.3 → exact 0.294。
      // 差 0.686 ≥ 0.15 → pending，胜者 item-a。
      final m = matcherOf({'item-a': 'BOX-001', 'item-b': 'BOX-002'});
      final s = GroupSuggester.suggest(
        photos: [
          photo('p1', [tk('BOX-001')]),
          photo('p2', [tk('BOX-002', conf: 0.3)]),
        ],
        matcher: m,
      );
      expect(s.itemId, 'item-a');
      expect(s.state, 'pending');
    });

    test('胜者平均分 < 0.40 → no_suggestion，itemId 为空', () {
      // edit2 = 0.72，OCR 置信 0.5 → 0.36。
      final m = matcherOf({'item-a': 'BOX-001'});
      final s = GroupSuggester.suggest(
        photos: [
          photo('p1', [tk('BOX-013', conf: 0.5)]),
          photo('p2', [tk('BOX-013', conf: 0.5)]),
        ],
        matcher: m,
      );
      expect(s.itemId, isNull);
      expect(s.confidence, closeTo(0.36, 1e-9));
      expect(s.state, 'no_suggestion');
    });
  });

  group('边界', () {
    test('空照片列表 → no_suggestion，不抛错', () {
      final m = matcherOf({'item-a': 'BOX-001'});
      final s = GroupSuggester.suggest(photos: const [], matcher: m);
      expect(s.itemId, isNull);
      expect(s.state, 'no_suggestion');
    });

    test('所有 token 都匹配不上 → none（itemId 空）', () {
      final m = matcherOf({'item-a': 'BOX-001'});
      final s = GroupSuggester.suggest(
        photos: [photo('p1', [tk('ZZZ-999'), tk('随便什么中文')])],
        matcher: m,
      );
      expect(s.itemId, isNull);
      expect(s.state, 'no_suggestion');
    });

    test('候选最多 3 个，按分数降序', () {
      final m = matcherOf({
        'item-a': 'BOX-001',
        'item-b': 'BOX-002',
        'item-c': 'BOX-003',
        'item-d': 'BOX-004',
      });
      // 三张照片三个货品：0.98 / 0.98 / 0.294（conf 0.3）。
      final s = GroupSuggester.suggest(
        photos: [
          photo('p1', [tk('BOX-001')]),
          photo('p2', [tk('BOX-002')]),
          photo('p3', [tk('BOX-003', conf: 0.3)]),
        ],
        matcher: m,
      );
      expect(s.candidates.length, lessThanOrEqualTo(3));
      // 降序：0.98 在前。
      expect(s.candidates.first.score,
          greaterThanOrEqualTo(s.candidates.last.score));
    });
  });

  group('位置权重函数', () {
    test('正中心不打折', () {
      expect(SuggestWeights.positionWeight(cx: 0.5, cy: 0.5), 1.0);
    });

    test('中心区（偏移 ≤ 0.25）不打折', () {
      expect(SuggestWeights.positionWeight(cx: 0.25, cy: 0.5), 1.0);
      expect(SuggestWeights.positionWeight(cx: 0.5, cy: 0.28), 1.0);
    });

    test('边缘（偏移 ≥ 0.45）= 0.85', () {
      expect(SuggestWeights.positionWeight(cx: 0.0, cy: 0.5), closeTo(0.85, 1e-9));
      expect(SuggestWeights.positionWeight(cx: 0.95, cy: 0.95), closeTo(0.85, 1e-9));
    });

    test('中间线性插值', () {
      final w = SuggestWeights.positionWeight(cx: 0.35, cy: 0.5);
      // off = 0.15，t = (0.15-0.0)/... 不对：edgeStart=0.25 → off=0.15 < 0.25 → 1.0
      expect(w, 1.0);
      final w2 = SuggestWeights.positionWeight(cx: 0.5, cy: 0.83);
      // off = 0.33，t = (0.33-0.25)/0.20 = 0.4 → 1 - 0.4*0.15 = 0.94
      expect(w2, closeTo(0.94, 1e-9));
    });
  });
}
