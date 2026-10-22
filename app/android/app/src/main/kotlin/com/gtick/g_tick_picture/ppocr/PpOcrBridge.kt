package com.gtick.g_tick_picture.ppocr

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Rect
import android.util.Log
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.io.File

/**
 * PP-OCRv6 的 MethodChannel 桥（P4 诉求 4）。
 *
 * 职责边界：
 *   · **只做**「给一张图 → 给一串文本 + 坐标」。
 *   · **不做**编码匹配、不做分组、不做归属 —— 那些全在 Dart 侧
 *     （domain/suggest/ 与 domain/assign/）。原生侧不持有任何业务判断。
 *
 * ═══════════════════════════════════════════════════════════════
 * 线程模型（必须清楚，否则会 ANR）：
 *   OCR 单张在 CPU 上是 100~600ms 量级的重活。
 *   所有推理都在 [Dispatchers.Default] 上跑，
 *   MethodChannel 的 result 回调再切回主线程返回。
 *   **绝不**在 platform thread（主线程）上做推理。
 */
class PpOcrBridge(private val context: Context) : MethodChannel.MethodCallHandler {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var engine: PpOcrEngine? = null
    private var initFailed = false

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "isReady" -> {
                if (initFailed) {
                    // 带原因回传（P4 · 真机反馈：UI 上"不可用"必须给下文）。
                    postResult(result) {
                        mapOf(
                            "ready" to false,
                            "reason" to (OnnxPpOcrEngine.lastCreateError
                                ?: "引擎初始化失败（未记录原因）"),
                        )
                    }
                    return
                }
                scope.launch {
                    val e = ensureEngine()
                    val ready = e != null
                    if (!ready) Log.e(TAG, "isReady: engine unavailable: ${OnnxPpOcrEngine.lastCreateError}")
                    postResult(result) {
                        mapOf(
                            "ready" to ready,
                            "reason" to if (ready) null else OnnxPpOcrEngine.lastCreateError,
                        )
                    }
                }
            }

            "recognize" -> {
                val path = call.argument<String>("path")
                if (path.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "path is required", null)
                    return
                }
                scope.launch {
                    val e = ensureEngine()
                    if (e == null) {
                        postError(result, "ENGINE_UNAVAILABLE",
                            "PP-OCRv6 engine is not available on this device")
                        return@launch
                    }
                    val tokens = try {
                        recognizeFile(e, path)
                    } catch (t: Throwable) {
                        Log.e(TAG, "recognize failed: $path", t)
                        postError(result, "OCR_FAILED", t.message ?: t.toString())
                        return@launch
                    }
                    postResult(result) { tokens }
                }
            }

            "dispose" -> {
                scope.launch {
                    try { engine?.close() } catch (_: Throwable) { }
                    engine = null
                    postResult(result) { null }
                }
            }

            else -> result.notImplemented()
        }
    }

    fun shutdown() {
        try { engine?.close() } catch (_: Throwable) { }
        engine = null
    }

    // ───────────────────────────────────────────────────────────

    /**
     * 懒加载 + **失败记牢**。
     *
     * [initFailed] 这面旗很重要：模型文件缺失时，每次调用都重试一遍
     * 初始化会白等几百毫秒 × 几百张照片。失败一次就永久降级，
     * Dart 侧会据此回退到 ML Kit。
     *
     * ⚠️ 失败时**必须留日志**：真机反馈（2026-09-24）"增强识别不可用"
     * 没有任何下文，排查只能靠 logcat。原因原文同时记在
     * [OnnxPpOcrEngine.lastCreateError]，随 isReady 回传给 Dart 显示。
     */
    private fun ensureEngine(): PpOcrEngine? {
        engine?.let { return it }
        if (initFailed) return null
        return try {
            val created = PpOcrEngine.create(context)
            if (created == null) {
                initFailed = true
                Log.e(TAG, "PP-OCRv6 create() returned null: ${OnnxPpOcrEngine.lastCreateError}")
                null
            } else {
                engine = created
                Log.i(TAG, "PP-OCRv6 engine ready")
                created
            }
        } catch (t: Throwable) {
            initFailed = true
            OnnxPpOcrEngine.lastCreateError = "create() 异常：${t.message ?: t.javaClass.simpleName}"
            Log.e(TAG, "PP-OCRv6 create() threw", t)
            null
        }
    }

    /**
     * 读图 + 推理。
     *
     * ⚠️ **必须先降采样再解码**，绝不能整图解码后缩放（R1b 铁律）。
     * 现场照片是 1200 万像素（4000×3000），整图解码一次要 36MB
     * ARGB_8888 —— 连拍时 OS 会直接把进程杀掉。
     * 这里用 `inJustDecodeBounds` 先读头部拿尺寸，算出采样率，
     * 再第二次解码（inSampleSize 是 2 的幂，解码器内部跳过像素）。
     *
     * 为什么采样到 [LONG_EDGE]：编码识别只需要看清字符，1600px
     * 对印刷体足够；再大只是线性增加时间，不提高识别率。
     */
    private fun recognizeFile(e: PpOcrEngine, path: String): List<Map<String, Any?>> {
        val f = File(path)
        if (!f.exists()) throw IllegalStateException("file not found: $path")

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(path, bounds)
        val w = bounds.outWidth
        val h = bounds.outHeight
        if (w <= 0 || h <= 0) throw IllegalStateException("cannot decode image: $path")

        val opts = BitmapFactory.Options().apply {
            inSampleSize = sampleSizeFor(w, h, LONG_EDGE)
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val bitmap = BitmapFactory.decodeFile(path, opts)
            ?: throw IllegalStateException("decode returned null: $path")

        try {
            val boxes = e.recognize(bitmap)
            val bw = bitmap.width.toFloat()
            val bh = bitmap.height.toFloat()

            // Dart 侧要的是「归一化中心点」，不是像素框 ——
            // 归一化后与原图分辨率无关，位置权重的阈值才不用跟着图变。
            return boxes.map { b ->
                val r: Rect = b.box
                mapOf(
                    "text" to b.text,
                    "confidence" to b.confidence.toDouble(),
                    "cx" to (((r.left + r.right) / 2f) / bw).coerceIn(0f, 1f).toDouble(),
                    "cy" to (((r.top + r.bottom) / 2f) / bh).coerceIn(0f, 1f).toDouble(),
                )
            }
        } finally {
            // 一定要回收 —— 一次推理一张，几百张下来
            // 不回收就是几百 MB 的 native 内存泄漏（R1b：内存不增长）。
            bitmap.recycle()
        }
    }

    private fun sampleSizeFor(w: Int, h: Int, target: Int): Int {
        var sample = 1
        var longEdge = maxOf(w, h)
        while (longEdge / 2 >= target) {
            longEdge /= 2
            sample *= 2
        }
        return sample
    }

    private fun postResult(result: MethodChannel.Result, block: () -> Any?) {
        mainHandler.post { result.success(block()) }
    }

    private fun postError(result: MethodChannel.Result, code: String, msg: String) {
        mainHandler.post { result.error(code, msg, null) }
    }

    private companion object {
        const val TAG = "PpOcrV6"
        const val LONG_EDGE = 1600
        val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
    }
}
