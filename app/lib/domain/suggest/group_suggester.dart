import '../model/enums.dart';
import '../search/code_matcher.dart';
import 'suggest_service.dart';
import 'suggest_thresholds.dart';

/// 一行 OCR token 的建议合成输入。
///
/// [positionWeight] 由 token 的归一化坐标算出（1.0 中心 / 0.85 边缘），
/// 换算函数在 [SuggestWeights]，这里只收结果 —— 让 suggest() 保持纯函数。
class SuggestToken {
  const SuggestToken({
    required this.text,
    required this.ocrConf,
    required this.positionWeight,
  });

  /// ML Kit 识别出的原始文本。
  final String text;

  /// ML Kit 的识别置信度（0~1）。拿不到时给 1.0（未知不打折）。
  final double ocrConf;

  /// 位置权重（0.85~1.0）。
  final double positionWeight;
}

/// 一张照片的全部 token。
class PhotoTokens {
  const PhotoTokens({required this.photoId, required this.tokens});

  final String photoId;
  final List<SuggestToken> tokens;
}

/// 组级建议合成器（§5.3.2 第 4~6 步）—— **纯函数，不碰数据库、不碰 ML Kit**。
///
/// ═══════════════════════════════════════════════════════════════
/// 阈值语义（v3.0 的本质约定，写代码前再读一遍）：
///
///   **置信度只做两件事：排序、标冲突。任何阈值都不能让机器写入归属。**
///
///   · ≥0.90 且组内一致 → 只意味着「有资格进一键确认的可复核列表」，
///     点确认的仍然是人（AssignSource.bulkConfirm，留痕）。
///   · conflict / no_suggestion → 只是 UI 提示的优先级标签。
/// ═══════════════════════════════════════════════════════════════
///
/// 算法（对设计方案「组级建议 = 组内按得分加权投票」的量化实现）：
///
/// 1. **单 token 得分** = matcher.best(token) 的 score（内部已含
///    base 分档 × OCR 置信度）× 位置权重。
/// 2. **单张票**：一张照片对同一货品的多个命中只取**最高**的一个 ——
///    一张照片里同编码出现两次不该变成两票。
/// 3. **组级累计票** Σ（投票口径），**组级置信 = Σ / 张数**（平均口径）。
///    用平均而不是累计，是为了让「2 张组」和「1 张组」的置信度可比：
///    一张认出 0.95 + 一张拍糊 0.05 → 0.50，如实反映波动，而不是虚高成 1.0。
/// 4. **conflict**：第二名平均分与胜者平均分差 < [SuggestThresholds.conflictGap]
///    → 组标 conflict（建议照给，UI 提示人看一眼）。
/// 5. **no_suggestion**：胜者平均分 < [SuggestThresholds.minConfidence]
///    → 不给建议（必须手动指派）。
abstract final class GroupSuggester {
  /// 对一组照片合成组级建议。
  ///
  /// [photos] 为空 → no_suggestion（不抛错，空输入不崩是本管道的纪律）。
  static GroupSuggestion suggest({
    required List<PhotoTokens> photos,
    required CodeMatcher matcher,
  }) {
    if (photos.isEmpty) return const GroupSuggestion.none();

    // ── 1+2：逐 token 匹配，单张单货品只留最高分（并记下命中方式） ──
    final perPhotoBest = <Map<String, double>>[];
    final perPhotoMode = <Map<String, String>>[];

    for (final photo in photos) {
      final best = <String, double>{};
      final mode = <String, String>{};
      for (final token in photo.tokens) {
        final cand = matcher.best(token.text, token.ocrConf);
        if (cand == null) continue;
        final score = cand.score * token.positionWeight;
        final known = best[cand.itemId];
        if (known == null || score > known) {
          best[cand.itemId] = score;
          mode[cand.itemId] = cand.mode;
        }
      }
      perPhotoBest.add(best);
      perPhotoMode.add(mode);
    }

    // ── 3：组级累计 + 平均 ──
    final sum = <String, double>{};
    final count = <String, int>{};
    for (final best in perPhotoBest) {
      for (final e in best.entries) {
        sum[e.key] = (sum[e.key] ?? 0) + e.value;
        count[e.key] = (count[e.key] ?? 0) + 1;
      }
    }
    if (sum.isEmpty) return const GroupSuggestion.none();

    final mean = <String, double>{
      for (final e in sum.entries) e.key: e.value / count[e.key]!,
    };
    final ranked = mean.keys.toList()
      ..sort((a, b) => mean[b]!.compareTo(mean[a]!));

    final winner = ranked.first;
    final winnerMean = mean[winner]!;

    // ── 5：整体质量太差 → 不给建议 ──
    if (winnerMean < SuggestThresholds.minConfidence) {
      return GroupSuggestion(
        itemId: null,
        confidence: winnerMean,
        candidates: _topCandidates(ranked, mean),
        evidence: const [],
        state: GroupSuggestState.noSuggestion.code,
      );
    }

    // ── 4：第二名太接近 → 标冲突（建议照给） ──
    var state = GroupSuggestState.pending.code;
    if (ranked.length >= 2) {
      final secondMean = mean[ranked[1]]!;
      if (winnerMean - secondMean < SuggestThresholds.conflictGap) {
        state = GroupSuggestState.conflict.code;
      }
    }

    // ── 证据：胜者在各张上的得分与命中方式 ──
    final evidence = <String>[];
    for (var i = 0; i < photos.length; i++) {
      final score = perPhotoBest[i][winner];
      if (score == null) continue;
      final mode = perPhotoMode[i][winner] ?? 'match';
      evidence.add('张${i + 1}:$mode(${score.toStringAsFixed(2)})');
    }

    return GroupSuggestion(
      itemId: winner,
      confidence: winnerMean,
      candidates: _topCandidates(ranked, mean),
      evidence: evidence,
      state: state,
    );
  }

  /// 前 3 名候选（GroupSuggestion.candidates 的形状：itemId + score + mode）。
  static List<MatchCandidate> _topCandidates(
    List<String> ranked,
    Map<String, double> mean,
  ) {
    return ranked
        .take(3)
        .map((id) => MatchCandidate(
              itemId: id,
              score: mean[id]!,
              mode: 'group',
            ))
        .toList();
  }
}
