/// OCR 引擎选择（P4 诉求 4 / 设计方案 §5.3.2）。
///
/// 为什么要有「选引擎」这层：
///   两条技术路线的适用面不同，且**都有可能失败**（机型、so 缺失、
///   NDK ABI 不匹配）。把选择权做成显式枚举 + 可回退，而不是
///   编译期二选一，是为了让「引擎崩了」这件事在**运行期**可恢复 ——
///   现场几百张图不能被一个 native crash 拖死。
///
/// ⚠️ 与本文件无关的一条纪律：**引擎只产出 token，永远不产出归属。**
///    归属的写入口唯一（domain/assign/assign_service.dart），
///    由 `tools/check_architecture.ps1` 强制。
enum OcrEngine {
  /// Google ML Kit Text Recognition —— 基线，随 APK 分发，零额外体积。
  ///
  /// 优点：稳定、无 native 编译风险、中英文开箱可用。
  /// 缺点：识别率一般，对工业字符（数码管/点阵/喷码）尤其弱。
  mlkit('mlkit', '标准识别', '手机自带引擎，稳定可靠'),

  /// PaddleOCR PP-OCRv6 —— 精度更高，专门改善了工业字符场景。
  ///
  /// 优点：对货品编码这类"印刷体 + 点阵/喷码"识别率明显更高。
  /// 缺点：APK 体积增加约 20~30MB（模型 + ONNX Runtime），
  ///      首次引入 NDK 原生编译。
  ///
  /// ⚠️ 未就绪时**必须自动回退到 [mlkit]**，不能让整理流程卡住。
  ppOcrV6('ppocr_v6', '增强识别', '精度更高，对编码/标签更准');

  const OcrEngine(this.code, this.label, this.hint);

  /// 存入 `app_settings` 的稳定值，不要改。
  final String code;

  /// 设置面板上显示的名字（业务语言，不出现技术名词）。
  final String label;

  /// 一句话说明，帮用户判断该选哪个。
  final String hint;

  static OcrEngine fromCode(String? c) => OcrEngine.values.firstWhere(
        (e) => e.code == c,
        orElse: () => OcrEngine.mlkit,
      );
}
