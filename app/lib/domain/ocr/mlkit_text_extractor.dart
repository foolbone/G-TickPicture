import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';

import 'ocr_text_extractor.dart';

/// ML Kit 离线文本识别的适配实现（§5.3.2 第 1~2 步）。
///
/// · **用中文脚本**（2026-09-24 真机反馈修正）：早期版本用拉丁脚本，
///   理由是"编码是拉丁/数字，识别中文浪费算力"。但真机实测暴露了
///   两个问题：
///     1. build.gradle 里中文模型 artifact 就是按「M4 OCR 用中文识别」
///        的本意引入的（App 侧手动加 `text-recognition-chinese`），
///        Dart 侧却选拉丁 —— 两处自相矛盾，拉丁注释是后来偏离的。
///     2. 现场标签是**中文为主**的装箱单/标识卡，拉丁模型对整行中文
///        的版面切分远不如中文模型，连它本该认的数字也容易被切成
///        认不出的碎片 —— 真机表现是"一张都识别不出来"。
///   中文模型识别拉丁/数字没有问题（它是超集），token 里混进的中文
///   词对编码匹配无害（matcher 只认编码形状）。
/// · **直读原图**：ML Kit 在 native 层自行处理大图。设计方案的
///   「先缩到 1600px」属于提速优化，但 Dart 侧全图解码再缩放
///   （image 包）单张要 1~2s，比 ML Kit native 处理还慢 ——
///   R1b 的教训（绝不能整图解码）在这里同样适用，先直读，
///   真机压测后若识别耗时仍超标再上 isolate 缩图。
/// · token 粒度取 TextElement（词级）：编码是无空格连续串，
///   词级正好一个编码一个 token；行级会把两件货的编码粘在一行。
class MlKitTextExtractor implements OcrTextExtractor {
  MlKitTextExtractor({TextRecognizer? recognizer})
      : _ownedRecognizer = recognizer ??
            TextRecognizer(script: TextRecognitionScript.chinese);

  final TextRecognizer _ownedRecognizer;
  bool _closed = false;

  @override
  Future<List<OcrTokenResult>> extract(String filePath) async {
    if (_closed) return const [];
    try {
      // fromFilePath 是同步构造（内部读文件元数据）。
      final input = InputImage.fromFilePath(filePath);
      final result = await _ownedRecognizer.processImage(input);

      // 整图尺寸（归一化坐标用）。metadata 拿不到 → 尺寸记为 0，
      // 下方按「未知 → 正中心」处理（未知不打折，unknown 沉默原则）。
      final size = input.metadata?.size;
      final double imgW = (size != null && size.width > 0) ? size.width : 0;
      final double imgH = (size != null && size.height > 0) ? size.height : 0;

      final tokens = <OcrTokenResult>[];
      for (final block in result.blocks) {
        for (final line in block.lines) {
          for (final element in line.elements) {
            var cx = 0.5;
            var cy = 0.5;
            if (imgW > 0 && imgH > 0) {
              final box = element.boundingBox;
              cx = (box.center.dx / imgW).clamp(0.0, 1.0);
              cy = (box.center.dy / imgH).clamp(0.0, 1.0);
            }
            tokens.add(OcrTokenResult(
              text: element.text,
              // 0.13.x 的 confidence 可空 —— 拿不到给 1.0（未知不打折）。
              ocrConf: element.confidence ?? 1.0,
              normCx: cx,
              normCy: cy,
            ));
          }
        }
      }
      return tokens;
    } catch (_) {
      // 识别失败 ≠ 识别为空：抛给管道，由管道把该张标为 failed
      // 并继续下一张（§5.3.3 单张失败不终止流水线）。
      rethrow;
    }
  }

  /// 释放 ML Kit 资源（APP 生命周期结束时调用）。
  void close() {
    if (_closed) return;
    _closed = true;
    _ownedRecognizer.close();
  }
}
