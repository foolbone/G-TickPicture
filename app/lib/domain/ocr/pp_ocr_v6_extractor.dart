import 'package:flutter/services.dart';

import 'ocr_text_extractor.dart';

/// PP-OCRv6 的 Flutter 侧适配器（P4 诉求 4）。
///
/// ═══════════════════════════════════════════════════════════════
/// 架构选择：**Platform Channel 桥接官方 Android SDK**，
/// 而不是「Dart 侧跑 ONNX Runtime」。
///
/// 理由（三条，按重要性排序）：
///   1. **复用官方前处理**。PP-OCR 的检测/识别是两阶段：DB 检测出文本框
///      （含多边形后处理 / 非极大值抑制）→ CRNN 逐框识别。这些步骤在
///      C++ / Kotlin 侧，Dart 重写一遍等于重造轮子，且极易出错。
///   2. **模型直接进 APK 的 assets**，由 Kotlin 侧喂给推理引擎 ——
///      完全不碰 Flutter 的 asset 解压路径，也没有「模型文件被
///      AAPT 压缩导致加载失败」这类经典坑。
///   3. **一处失败只是一处**。原生侧崩了会抛 PlatformException 回来，
///      管道照常把该张标 failed，其余功能零影响（§5.3.3 单张失败不终止）。
///
/// ═══════════════════════════════════════════════════════════════
/// 契约（与 [OcrTextExtractor] 完全一致）：
///   · 成功 → 返回 token 列表（可能为空 = 图里没文字）
///   · 失败 → **抛异常**（管道会把该张标 failed 并继续下一张）
///
/// 这两种情况语义不同，绝不能把失败也返回空列表 —— 那会让
/// 「识别不出来」和「没有文字」在数据上无法区分。
class PpOcrV6Extractor implements OcrTextExtractor {
  PpOcrV6Extractor({MethodChannel? channel})
      : _channel = channel ?? const MethodChannel(_channelName);

  static const String _channelName = 'gtick/ppocr';

  final MethodChannel _channel;

  /// 最近一次「不可用」的具体原因（P4 · 真机反馈）。
  ///
  /// ═════════════════════════════════════════════════════════════
  /// 为什么做成 static：引擎装配走 `OcrEngineFactory.build`，每次
  /// 换引擎都新建一个本类实例 —— 探测结果如果在实例上，设置面板
  /// 读不到（它面对的是管道里换进去的另一个实例）。失败原因天然是
  /// 「本进程最近一次探测」的语义，static 恰如其分。
  ///
  /// null = 没探测过，或探测结果为可用。
  /// ═════════════════════════════════════════════════════════════
  static String? lastUnavailableReason;

  /// 原生侧是否已就绪（模型加载成功）。
  ///
  /// 懒探测 + 缓存：第一次调用才问原生侧，之后直接用缓存值 ——
  /// 每张照片都问一次会白白多几百次 channel 往返。
  bool? _readyCache;

  @override
  Future<List<OcrTokenResult>> extract(String filePath) async {
    final raw = await _channel.invokeMethod<List<Object?>>(
      'recognize',
      <String, Object?>{'path': filePath},
    );
    if (raw == null) return const [];

    final tokens = <OcrTokenResult>[];
    for (final item in raw) {
      if (item is! Map) continue;
      final text = item['text'];
      if (text is! String || text.isEmpty) continue;
      tokens.add(OcrTokenResult(
        text: text,
        // 原生侧拿不到置信度时给 1.0（未知不打折，unknown 沉默原则）。
        ocrConf: (item['confidence'] as num?)?.toDouble() ?? 1.0,
        normCx: (item['cx'] as num?)?.toDouble() ?? 0.5,
        normCy: (item['cy'] as num?)?.toDouble() ?? 0.5,
      ));
    }
    return tokens;
  }

  /// 原生引擎是否可用。
  ///
  /// 任何异常都视为**不可用**（而不是往上抛）—— 调用它的人要做的
  /// 决策是"能不能用 PP-OCRv6"，一个探测失败不该让整个流程崩。
  ///
  /// 原因会记进 [lastUnavailableReason]，设置面板原样展示 ——
  /// 真机排查（2026-09-24）的最大障碍就是"不可用"三个字没有下文，
  /// 模型缺失 / so 架构不匹配 / 字典校验失败在 UI 上长一个样。
  Future<bool> isAvailable() async {
    final cached = _readyCache;
    if (cached != null) return cached;
    try {
      final raw = await _channel.invokeMethod<Object?>('isReady');
      // 新契约：Map{ready, reason}。兼容旧契约（裸 bool）。
      if (raw is Map) {
        final ok = raw['ready'] == true;
        final reason = raw['reason'];
        lastUnavailableReason =
            ok ? null : (reason is String && reason.isNotEmpty ? reason : '原生引擎初始化失败（原因未回传）');
        return _readyCache = ok;
      }
      final ok = raw == true;
      lastUnavailableReason = ok ? null : '原生引擎不可用';
      return _readyCache = ok;
    } catch (e) {
      lastUnavailableReason = '通道调用失败：$e';
      return _readyCache = false;
    }
  }

  /// 释放原生侧资源（APP 生命周期结束时调用）。
  Future<void> close() async {
    _readyCache = null;
    try {
      await _channel.invokeMethod<void>('dispose');
    } catch (_) {
      // 释放失败无副作用 —— 进程退出会回收。
    }
  }
}

/// 降级实现：永远返回空列表，**不抛异常**。
///
/// 用途：用户选了 PP-OCRv6 但原生侧不可用，且我们**不希望**每次都
/// 走一遍失败的 channel 调用。返回空列表 = 「图里没有文字」，
/// 组建议会退化成 no_suggestion —— 人仍然能手动指派，
/// 全流程可用（§5.3.3「OCR 可整体关闭」的同一套降级语义）。
class NoopOcrTextExtractor implements OcrTextExtractor {
  const NoopOcrTextExtractor();

  @override
  Future<List<OcrTokenResult>> extract(String filePath) async => const [];
}
