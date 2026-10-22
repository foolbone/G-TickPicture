package com.gtick.g_tick_picture.perf

import android.app.ActivityManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * 性能相关的原生能力（2026-09-29「全 App 性能排查」）。
 *
 * 两件事 Dart 侧做不好、原生做很便宜：
 *
 *  1. **设备分级** —— 内存级别 / 是否低内存机 / CPU 核数。Dart 拿不到这些，
 *     而它们直接决定「一次能并发生成几张缩略图」「网格一次加载多少格」。
 *     低配机上按高配的参数跑 = 卡顿 + OOM，这是本次优化要解决的核心。
 *
 *  2. **缩略图解码** —— Dart 侧 `image` 包只能**整图解码再缩放**：
 *     一张 4000x3000 的 JPEG 要 200~600ms、峰值内存 48MB+（ARGB8888）。
 *     BitmapFactory 的 `inSampleSize` 在解码阶段就降采样（硬件/内存友好），
 *     再配 RGB_565，峰值内存降到 1/8 左右，且是批量一次跨通道往返完成。
 *
 * 生命周期跟随 engine（见 MainActivity.cleanUpFlutterEngine）。
 */
class PerfBridge(private val context: Context) : MethodChannel.MethodCallHandler {

    private val scope = CoroutineScope(Dispatchers.Default + Job())
    private val mainHandler = Handler(Looper.getMainLooper())

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "deviceProfile" -> postResult(result) { deviceProfile() }

            // 批量缩略图：一次通道往返处理 N 张，省掉 N 次跨平台调用开销。
            // 入参 jobs: [{src, dst, px, quality}]，出参 [{ok, w, h}]（按下标对齐）。
            "makeThumbs" -> {
                val jobs = call.argument<List<Map<String, Any?>>>("jobs")
                if (jobs.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "jobs 必填", null)
                    return
                }
                scope.launch {
                    try {
                        val out = makeThumbs(jobs)
                        postResult(result) { out }
                    } catch (t: Throwable) {
                        android.util.Log.e(TAG, "makeThumbs failed", t)
                        postError(result, "THUMB_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 批量压缩交付照片（2026-09-30 微信 1GB 限制）。
            // 入参 jobs: [{src, dst, px, quality}]，出参 [{ok, skipped, w, h, bytes}]。
            // 与 makeThumbs 的三点区别：ARGB_8888（交付画质，不用 565）、
            // 原图已小于目标长边时返回 skipped=true（原图直出，零画质损失）、
            // 回传 bytes（Dart 分卷要用，省一次 stat）。
            "compressPhotos" -> {
                val jobs = call.argument<List<Map<String, Any?>>>("jobs")
                if (jobs.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "jobs 必填", null)
                    return
                }
                scope.launch {
                    try {
                        val out = compressPhotos(jobs)
                        postResult(result) { out }
                    } catch (t: Throwable) {
                        android.util.Log.e(TAG, "compressPhotos failed", t)
                        postError(result, "COMPRESS_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 批量内容指纹（2026-10-04「照片不能重复」查重）。
            // 入参 paths: [String]，出参 hashes: [String|null]（按下标对齐，
            // null = 文件读不到）。**只读头 64KB**，见 hashFiles 的注释。
            "hashFiles" -> {
                val paths = call.argument<List<String>>("paths")
                if (paths.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "paths 必填", null)
                    return
                }
                scope.launch {
                    try {
                        val out = hashFiles(paths)
                        postResult(result) { out }
                    } catch (t: Throwable) {
                        android.util.Log.e(TAG, "hashFiles failed", t)
                        postError(result, "HASH_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            else -> result.notImplemented()
        }
    }

    fun shutdown() {
        try {
            scope.coroutineContext[Job]?.cancel()
        } catch (_: Throwable) {
        }
    }

    // ───────────────────────────────────────────────────────────

    private fun deviceProfile(): Map<String, Any?> {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
        val mi = ActivityManager.MemoryInfo()
        val totalMemMB = try {
            if (am != null) {
                am.getMemoryInfo(mi)
                mi.totalMem / (1024L * 1024L)
            } else {
                0L
            }
        } catch (_: Throwable) {
            0L
        }
        val memoryClassMB = try {
            am?.memoryClass ?: 0
        } catch (_: Throwable) {
            0
        }
        val lowRam = try {
            // isLowRamDevice 需要 API 19+，minSdk 26 起一律可用；仍留兜底。
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT) am?.isLowRamDevice == true else false
        } catch (_: Throwable) {
            false
        }
        return mapOf(
            "totalMemMB" to totalMemMB,
            "memoryClassMB" to memoryClassMB,
            "lowRam" to lowRam,
            "cpuCores" to Runtime.getRuntime().availableProcessors(),
            "sdkInt" to Build.VERSION.SDK_INT,
        )
    }

    /**
     * 批量生成缩略图。**串行**执行 —— 并发解码 N 张大图会让低配机内存峰值
     * 直接翻倍，省下的那点时间远不如一次 OOM 重启的代价。
     */
    private fun makeThumbs(jobs: List<Map<String, Any?>>): List<Map<String, Any?>> {
        val out = ArrayList<Map<String, Any?>>(jobs.size)
        for (j in jobs) {
            val src = j["src"] as? String
            val dst = j["dst"] as? String
            val px = (j["px"] as? Number)?.toInt() ?: 256
            val quality = (j["quality"] as? Number)?.toInt() ?: 78
            if (src == null || dst == null) {
                out.add(mapOf("ok" to false, "w" to 0, "h" to 0))
                continue
            }
            out.add(makeThumb(src, dst, px.coerceAtLeast(16), quality.coerceIn(30, 95)))
        }
        return out
    }

    private fun makeThumb(src: String, dst: String, px: Int, quality: Int): Map<String, Any?> {
        var bmp: Bitmap? = null
        var scaled: Bitmap? = null
        try {
            // ① 只读头部拿尺寸（不分配像素缓冲）
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(src, bounds)
            val ow = bounds.outWidth
            val oh = bounds.outHeight
            if (ow <= 0 || oh <= 0) return fail()

            // ② inSampleSize 只接受 2 的幂：取「仍不小于目标长边」的最大幂，
            //    这样解码出的图略大于目标，再精确缩放，画质与内存都合适。
            val longEdge = max(ow, oh)
            var sample = 1
            while (longEdge / (sample * 2) >= px) sample *= 2

            val opts = BitmapFactory.Options().apply {
                inSampleSize = sample
                // RGB_565：缩略图不需要 alpha，像素缓冲直接减半
                inPreferredConfig = Bitmap.Config.RGB_565
            }
            bmp = BitmapFactory.decodeFile(src, opts) ?: return fail()

            val bw = bmp.width
            val bh = bmp.height
            val bLong = max(bw, bh).toFloat()
            val scale = if (bLong > px.toFloat()) px.toFloat() / bLong else 1.0f

            val tw = if (scale < 1.0f) (bw * scale).roundToInt().coerceAtLeast(1) else bw
            val th = if (scale < 1.0f) (bh * scale).roundToInt().coerceAtLeast(1) else bh

            scaled = if (scale < 1.0f) Bitmap.createScaledBitmap(bmp, tw, th, true) else bmp

            val dir = File(dst).parentFile
            if (dir != null && !dir.exists() && !dir.mkdirs()) return fail()

            FileOutputStream(dst).use { out ->
                scaled.compress(Bitmap.CompressFormat.JPEG, quality, out)
                out.flush()
            }
            // 平均亮度顺手算（2026-10-10「弱光提示」）：此刻像素已在内存里，
            // 遍历一遍是微秒级；若放到 Dart 侧就得**再解码一次**整图，
            // 那才是真贵。luma 只用于提示"光线够不够"，不参与任何画面修改
            // —— 取证原图一个像素都不许动。
            return mapOf("ok" to true, "w" to tw, "h" to th, "luma" to avgLuma(scaled))
        } catch (t: Throwable) {
            android.util.Log.w(TAG, "makeThumb failed: $src :: ${t.message}")
            return fail()
        } finally {
            try {
                if (scaled != null && scaled !== bmp) scaled.recycle()
            } catch (_: Throwable) {
            }
            try {
                bmp?.recycle()
            } catch (_: Throwable) {
            }
        }
    }

    /**
     * 平均亮度（0~255，Rec.601 luma）。
     *
     * 只给**缩略图**用：调用点保证位图长边 ≤ px（默认 256），
     * 一次 getPixels 最多几万像素。上界保护是为了防止将来有人拿它
     * 去量整图 —— 那样一次就分配几十 MB，属于不该发生的事。
     *
     * 采样：像素总数超过上限时按步长跳采（亮度是统计量，跳采不影响结论）。
     * 失败返回 null —— 亮度查不到就**不提示**，绝不猜一个数（纪律 17）。
     */
    private fun avgLuma(bmp: Bitmap): Int? {
        return try {
            val w = bmp.width
            val h = bmp.height
            if (w <= 0 || h <= 0) return null
            val total = w * h
            val maxPx = 120_000
            val step = if (total > maxPx) (total + maxPx - 1) / maxPx else 1
            val buf = IntArray(total)
            bmp.getPixels(buf, 0, w, 0, 0, w, h)
            var sum = 0L
            var n = 0
            var i = 0
            while (i < total) {
                val c = buf[i]
                val r = (c shr 16) and 0xFF
                val g = (c shr 8) and 0xFF
                val b = c and 0xFF
                sum += (r * 299 + g * 587 + b * 114) / 1000
                n++
                i += step
            }
            if (n == 0) null else (sum / n).toInt()
        } catch (t: Throwable) {
            android.util.Log.w(TAG, "avgLuma failed :: ${t.message}")
            null
        }
    }

    private fun fail(): Map<String, Any?> =
        mapOf("ok" to false, "w" to 0, "h" to 0, "luma" to null)

    /**
     * 批量压缩交付照片。**串行**执行 —— 一张 12MP 的 ARGB_8888 位图 48MB，
     * 并发解码会让低配机内存峰值翻倍，交付不是抢时间的场景，稳比快重要。
     */
    private fun compressPhotos(jobs: List<Map<String, Any?>>): List<Map<String, Any?>> {
        val out = ArrayList<Map<String, Any?>>(jobs.size)
        for (j in jobs) {
            val src = j["src"] as? String
            val dst = j["dst"] as? String
            val px = (j["px"] as? Number)?.toInt() ?: 2560
            val quality = (j["quality"] as? Number)?.toInt() ?: 85
            if (src == null || dst == null) {
                out.add(fail())
                continue
            }
            out.add(compressPhoto(src, dst, px.coerceAtLeast(640), quality.coerceIn(50, 95)))
        }
        return out
    }

    private fun compressPhoto(src: String, dst: String, maxEdge: Int, quality: Int): Map<String, Any?> {
        var bmp: Bitmap? = null
        var scaled: Bitmap? = null
        try {
            // ① 只读头部拿尺寸（不分配像素缓冲）
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(src, bounds)
            val ow = bounds.outWidth
            val oh = bounds.outHeight
            if (ow <= 0 || oh <= 0) return fail()

            // ② 原图长边已不超目标 → 不动它，原图直出（零画质损失）。
            //    Dart 侧见 skipped=true 会走复制原图路径。
            val longEdge = max(ow, oh)
            if (longEdge <= maxEdge) {
                return mapOf(
                    "ok" to true, "skipped" to true,
                    "w" to ow, "h" to oh, "bytes" to File(src).length(),
                )
            }

            // ③ inSampleSize 解码阶段降采样：取「仍不小于目标长边」的最大幂，
            //    解码出的图略大于目标，再精确缩放。
            var sample = 1
            while (longEdge / (sample * 2) >= maxEdge) sample *= 2

            val opts = BitmapFactory.Options().apply {
                inSampleSize = sample
                // 交付照片用 ARGB_8888：RGB_565 是 16 位色，标签/箱号
                // 这类文字边缘可能出现色带 —— 画质优先。
                inPreferredConfig = Bitmap.Config.ARGB_8888
            }
            bmp = BitmapFactory.decodeFile(src, opts) ?: return fail()

            val bw = bmp.width
            val bh = bmp.height
            val bLong = max(bw, bh).toFloat()
            val scale = if (bLong > maxEdge.toFloat()) maxEdge.toFloat() / bLong else 1.0f

            val tw = if (scale < 1.0f) (bw * scale).roundToInt().coerceAtLeast(1) else bw
            val th = if (scale < 1.0f) (bh * scale).roundToInt().coerceAtLeast(1) else bh

            scaled = if (scale < 1.0f) Bitmap.createScaledBitmap(bmp, tw, th, true) else bmp

            val dir = File(dst).parentFile
            if (dir != null && !dir.exists() && !dir.mkdirs()) return fail()

            FileOutputStream(dst).use { out ->
                scaled.compress(Bitmap.CompressFormat.JPEG, quality, out)
                out.flush()
            }
            return mapOf(
                "ok" to true, "skipped" to false,
                "w" to tw, "h" to th, "bytes" to File(dst).length(),
            )
        } catch (t: Throwable) {
            android.util.Log.w(TAG, "compressPhoto failed: $src :: ${t.message}")
            return fail()
        } finally {
            try {
                if (scaled != null && scaled !== bmp) scaled.recycle()
            } catch (_: Throwable) {
            }
            try {
                bmp?.recycle()
            } catch (_: Throwable) {
            }
        }
    }

    /**
     * 批量算内容指纹，用于「同一张照片是否重复」查重。
     *
     * **只读文件头 64KB，不读全文件**：一个项目上千张、每张 2~5MB，
     * 全读一遍是数 GB 的 IO，现场等不起（这是本方法存在的理由）。
     * 同一张图无论从相册选几次、经几次微信转发，**文件字节完全不变**，
     * 头 64KB 足以把它认出来。
     *
     * 指纹 = `size:摘要前16位`。带上 size 是因为纯摘要理论上可能撞，
     * 而两张大小相同、头 64KB 摘要也相同的图在现实中基本不存在 ——
     * 宁可漏报不错报。
     *
     * 串行执行（与 [makeThumbs] 同理）：这里 IO 密集但极轻，
     * 并发只会让低配机的随机 IO 更乱。
     */
    private fun hashFiles(paths: List<String>): List<String?> {
        val out = ArrayList<String?>(paths.size)
        for (p in paths) {
            out.add(hashFile(p))
        }
        return out
    }

    private fun hashFile(path: String): String? {
        return try {
            val f = File(path)
            if (!f.exists() || !f.isFile) return null
            val len = f.length()
            if (len <= 0L) return null
            FileInputStream(f).use { input ->
                val buf = ByteArray(HEAD_BYTES)
                var read = 0
                while (read < buf.size) {
                    val n = input.read(buf, read, buf.size - read)
                    if (n <= 0) break
                    read += n
                }
                if (read <= 0) return null
                val md = MessageDigest.getInstance("SHA-256")
                md.update(buf, 0, read)
                "$len:" + md.digest().take(8).joinToString("") { "%02x".format(it) }
            }
        } catch (_: Throwable) {
            // 读不到就是 null（Dart 侧当成"还没算过"，下轮补算时再试）
            null
        }
    }

    private fun postResult(result: MethodChannel.Result, block: () -> Any?) {
        mainHandler.post { result.success(block()) }
    }

    private fun postError(result: MethodChannel.Result, code: String, msg: String) {
        mainHandler.post { result.error(code, msg, null) }
    }

    private companion object {
        const val TAG = "PerfBridge"

        /** 指纹只读文件头这么多字节 —— 够认同一张图，又不至于读成 IO 灾难。 */
        const val HEAD_BYTES = 64 * 1024
    }
}
