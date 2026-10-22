/// OCR 文本抽取的抽象接口 —— 建议管道只依赖这个接口。
///
/// 为什么隔一层：
///   1. **可测** —— flutter test 环境里 ML Kit 插件不可用，
///      管道测试用 [FakeOcrTextExtractor] 注入假结果即可全流程验证。
///   2. **可降级** —— ML Kit 初始化失败 / 机型不支持（§5.3.3）
///      时换一个永远返回空列表的实现，整条建议链路自动进入
///      「无建议模式」，其余功能零变化。
///   3. **可关闭** —— 用户在设置里关掉 OCR 时，编排器直接跳过抽取。
abstract interface class OcrTextExtractor {
  /// 对一张照片做离线文本识别。
  ///
  /// 返回识别出的 token 列表（词级）。识别失败应**返回空列表**并让
  /// 上层把 photos.ocr_state 置为 failed —— 抽取器自己不抛异常打断管道。
  /// [onTokenBox] 用于把归一化坐标交给调用方算位置权重；
  /// 拿不到坐标时回调 null（调用方按「未知不打折」处理）。
  Future<List<OcrTokenResult>> extract(String filePath);
}

/// 一次识别产出的一个 token。
class OcrTokenResult {
  const OcrTokenResult({
    required this.text,
    required this.ocrConf,
    required this.normCx,
    required this.normCy,
  });

  final String text;

  /// ML Kit 的识别置信度（0~1）。插件版本拿不到时给 1.0。
  final double ocrConf;

  /// token 中心点在整图中的归一化坐标（0~1），位置权重用。
  /// 拿不到时给 0.5 / 0.5（正中心 = 不打折）。
  final double normCx;
  final double normCy;
}

/// 测试 / 降级用的假实现：按构造参数返回固定结果。
class FakeOcrTextExtractor implements OcrTextExtractor {
  FakeOcrTextExtractor({this.results = const {}, this.failPaths = const {}});

  /// filePath → 该照片的 token 结果。
  final Map<String, List<OcrTokenResult>> results;

  /// 指定路径模拟识别失败 —— **抛异常**（与真实适配器契约一致：
  /// 失败抛出去，管道标 failed 并继续下一张；返回空列表只代表
  /// 「图里没有文字」，两者语义不同）。
  final Set<String> failPaths;

  @override
  Future<List<OcrTokenResult>> extract(String filePath) async {
    if (failPaths.contains(filePath)) {
      throw Exception('simulated OCR failure for $filePath');
    }
    return results[filePath] ?? const [];
  }
}
