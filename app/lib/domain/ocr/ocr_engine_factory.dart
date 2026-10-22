import 'mlkit_text_extractor.dart';
import 'ocr_engine.dart';
import 'ocr_text_extractor.dart';
import 'pp_ocr_v6_extractor.dart';

/// 引擎装配 + **自动回退**（P4 诉求 4）。
///
/// ═══════════════════════════════════════════════════════════════
/// 为什么需要一个工厂而不是在 provider 里 `switch` 一下：
///
/// PP-OCRv6 的可用性是**运行期才知道的** —— 模型文件缺失、so 架构不匹配、
/// ONNX Runtime 初始化失败，这些都不是编译期能判定的。而整理流程
/// 不能因为引擎选错就卡住：几百张照片等着识别，人还在现场等着收工。
///
/// 所以回退策略是**三档**，每档都保证流程可用：
///
///   ① 用户选 PP-OCRv6 且原生侧就绪 → 用它（精度最好）
///   ② 用户选 PP-OCRv6 但原生侧没准备好 → **退回 ML Kit**（记一条提示）
///   ③ 用户关掉了 OCR / ML Kit 也不行 → `NoopOcrTextExtractor`
///      （全部返回空 → 建议退化成 no_suggestion → 人手动指派，
///       这正是 §5.3.3「OCR 可整体关闭」的同一套语义）
///
/// ⚠️ 回退是**静默**的（不弹窗、不打断）—— 采集期禁弹窗是架构约束，
///    整理期的原则同样是"不因为辅助功能失败而挡住主路径"。
///    唯一的反馈是整理页头部的引擎标签（写着实际在用哪个）。
/// ═══════════════════════════════════════════════════════════════
class OcrEngineFactory {
  const OcrEngineFactory._();

  /// 按用户选择装配提取器。
  ///
  /// 返回的 tuple 里第二个元素是**实际生效的引擎** —— 它可能与
  /// [preferred] 不同（回退发生了）。UI 用它来显示真实状态，
  /// 而不是显示用户选的那个（那会撒谎）。
  static Future<({OcrTextExtractor extractor, OcrEngine effective})> build({
    required OcrEngine preferred,
    MlKitTextExtractor? mlkit,
    PpOcrV6Extractor? ppocr,
  }) async {
    switch (preferred) {
      case OcrEngine.mlkit:
        return (
          extractor: mlkit ?? MlKitTextExtractor(),
          effective: OcrEngine.mlkit,
        );

      case OcrEngine.ppOcrV6:
        final p = ppocr ?? PpOcrV6Extractor();
        if (await p.isAvailable()) {
          return (extractor: p, effective: OcrEngine.ppOcrV6);
        }
        // 原生侧没准备好 → 静默回退，流程照常
        return (
          extractor: mlkit ?? MlKitTextExtractor(),
          effective: OcrEngine.mlkit,
        );
    }
  }
}
