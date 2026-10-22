package com.gtick.g_tick_picture.ppocr

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Rect

/** 一次识别的产出：文本 + 置信度 + 像素框（归一化在 Kotlin 侧做完）。 */
data class OcrBox(val text: String, val confidence: Float, val box: Rect)

/**
 * PP-OCRv6 推理引擎的**抽象**（P4 诉求 4）。
 *
 * ═══════════════════════════════════════════════════════════════
 * 为什么是接口而不是直接写死一个实现：
 *
 * PP-OCRv6 的端侧部署有两条路，选哪条取决于**模型文件的形式**：
 *
 *   A. **官方 Android Demo 的 SDK 那条路**（`deploy/ppocr-android`）：
 *      基于 ONNX Runtime 1.21.1，Det/Rec/Cls 三个 .onnx，
 *      SDK 与 Demo 分离、可打成 AAR。
 *      → 用 [OnnxPpOcrEngine] 实现。
 *
 *   B. **Paddle-Lite 的 `.nb` 模型**：官方也提供 opt 工具把
 *      Paddle 模型转成 Paddle-Lite 格式，端侧用 PaddlePredictor。
 *      → 需要另写实现（本项目未采用，理由见下）。
 *
 * 本项目选 A。理由：
 *   · ONNX Runtime 1.21.1 的 **minSdk 是 26**，与本工程 minSdk 26 一致；
 *   · 依赖面更窄（就一个 `onnxruntime-android` aar），
 *     不需要引入 Paddle-Lite 的整套 Maven 依赖；
 *   · 官方 Demo 已经把这套跑通了，包括前处理与后处理。
 *
 * ⚠️ 无论哪条路，**模型文件与 so 都不会随 Flutter 的 pub 依赖自动进来**。
 *    必须由 `tools/fetch_ppocr_model.ps1` 下载后放进
 *    `android/app/src/main/assets/ppocr/`，
 *    否则 [PpOcrEngine.create] 返回 null，Dart 侧自动回退 ML Kit。
 * ═══════════════════════════════════════════════════════════════
 */
interface PpOcrEngine {

    /** 对**已降采样**的位图做「检测 + 识别」，返回按从上到下、从左到右排好的框。 */
    fun recognize(bitmap: Bitmap): List<OcrBox>

    /** 释放 native 资源。可重复调用。 */
    fun close()

    companion object {
        /**
         * 建引擎。**任何失败都返回 null**（模型缺失、so 架构不匹配、
         * ONNX Runtime 初始化失败……），由调用方降级 ——
         * 这里不抛异常，是为了让"能不能用"是一个可判定的事实，
         * 而不是散落在各处的 try/catch。
         */
        fun create(context: Context): PpOcrEngine? = try {
            OnnxPpOcrEngine.create(context)
        } catch (t: Throwable) {
            // create 内部已逐步记因（OnnxPpOcrEngine.lastCreateError），
            // 这里兜的是"内部分发都失败"的最外层异常 —— 也要留痕。
            OnnxPpOcrEngine.lastCreateError =
                "引擎创建异常：${t.message ?: t.javaClass.simpleName}"
            android.util.Log.e("PpOcrV6", "create() threw", t)
            null
        }
    }
}
