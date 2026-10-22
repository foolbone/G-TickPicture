package com.gtick.g_tick_picture.ppocr

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import ai.onnxruntime.TensorInfo
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.graphics.Rect
import java.io.File
import java.io.FileOutputStream
import java.nio.FloatBuffer
import java.util.Collections

/**
 * 基于 ONNX Runtime 的 PP-OCRv6 推理引擎（P4 诉求 4）。
 *
 * ═══════════════════════════════════════════════════════════════
 * 模型文件
 * ───────────────────────────────────────────────────────────────
 *   assets/ppocr/det.onnx   —— PP-OCRv6_small_det   （9.4 MB）
 *   assets/ppocr/rec.onnx   —— PP-OCRv6_small_rec   （20.2 MB）
 *   assets/ppocr/keys.txt   —— 识别字典（18708 行）
 *
 * **缺任何一个文件 → create() 返回 null → 自动回退 ML Kit。**
 *
 * ═══════════════════════════════════════════════════════════════
 * 前处理参数：**全部来自模型自带的 inference.yml，不靠记忆**
 * ───────────────────────────────────────────────────────────────
 * 早期版本里这几个值是凭印象写的，实测与官方配置**三处不符**
 * （归一化、通道序、二值化阈值），会直接把识别率打到 0。现在的取法：
 *
 *   det（来自 PP-OCRv6_small_det_infer/inference.yml）：
 *     DecodeImage:   img_mode: BGR          -> 通道序 B,G,R
 *     NormalizeImage: mean [0.485,0.456,0.406] / std [0.229,0.224,0.225] / scale 1/255
 *     DetResizeForTest: null                -> 官方默认 736 / limit_type=min
 *     DBPostProcess: thresh 0.2 / box_thresh 0.45 / unclip_ratio 1.4 / max_candidates 3000
 *
 *   rec（来自 PP-OCRv6_small_rec_infer/inference.yml）：
 *     DecodeImage:   img_mode: BGR
 *     RecResizeImg:  image_shape [3, 48, 320]
 *     归一化藏在 RecResizeImg 里（yml 里**没有** NormalizeImage 这一项）：
 *       (x/255 - 0.5) / 0.5        <- 与 det 的 ImageNet mean/std **不是**一套
 *     填充值 = np.zeros，即**归一化空间的 0.0**（= 原始像素 127.5 的中灰），
 *       不是黑边。黑边是 -1.0，会被模型当成"一整片墨迹"。
 *
 * ═══════════════════════════════════════════════════════════════
 * 两处**有意偏离**官方默认（都写清了理由，别当 bug 修掉）
 * ───────────────────────────────────────────────────────────────
 * 1. **det 的缩放：按总像素数缩到 ~70 万，而不是官方的「短边 736、只放大不缩小」。**
 *    官方 DetResizeForTest(limit_type=min) 的逻辑是：短边 < 736 才放大，
 *    否则 ratio=1.0 **不缩小**。也就是说 1600x1200 的照片会原尺寸喂进网络
 *    —— 1.9M 像素，手机上单次 det 就要几秒，1200 张照片跑不完（R1b / 指标②）。
 *    改成按面积归一后，横竖拍的计算量一致（约 0.7M 像素，与官方 736 短边
 *    在同样输入下的 0.72M 相当），精度损失可控。**要调就调 DET_TARGET_PIXELS。**
 *
 * 2. **不做方向分类（Cls）、不做透视矫正、不做真 NMS。**
 *    · 无 Cls 模型：**rec 侧做四方向兜底**（0° 置信度 < 0.85 才试
 *      180/90/270，取「长度×置信度」最高）。真实数据实证：倒贴的标识卡
 *      0° 全是乱码、180° 全对 —— det 对倒置文字无感，兜底必须在 rec。
 *      打印体 0° 就有 0.92+，几乎不付额外开销。
 *    · 无透视矫正：用轴对齐包围盒裁剪，对水平排版的标签足够。
 *      ⚠️ 代价：斜着贴的标签识别率下降。
 *    · 无真 NMS：改成「按面积降序 + IoU>0.5 丢弃」，框数量是几十级不是几千级。
 *
 * ═══════════════════════════════════════════════════════════════
 * 字典下标布局（**这一条错一个下标，输出就是整片乱码，且不报错**）
 * ───────────────────────────────────────────────────────────────
 *   下标 0         -> CTC blank（不发字符）
 *   下标 1..18708  -> keys.txt 的第 1..18708 行
 *   下标 18709     -> 半角空格（PaddleOCR 中文模型 use_space_char 追加）
 *   合计 18710     -> 必须等于 rec.onnx 输出张量的最后一维
 *
 * create() 会**拿 ONNX 输出维度反查**这个数量，对不上就直接返回 null
 * 回退 ML Kit —— 宁可不用，也不能输出一堆错字。
 *
 * ⚠️ keys.txt 的第 1748 条是 U+3000 全角空格「　」。读文件时**不能用 trim()**
 *    （Kotlin 的 trim 会剥掉 Unicode 空白，把这一条读成空串），
 *    只能用 trimEnd('\r','\n')。同理生成脚本里也不能用 Python 的 strip()。
 */
class OnnxPpOcrEngine private constructor(
    private val env: OrtEnvironment,
    private val det: OrtSession,
    private val rec: OrtSession,
    private val keys: List<String>,
) : PpOcrEngine {

    @Volatile private var closed = false

    /**
     * 输入节点名。**从 session 元数据读**，不硬编码 —— 本模型实测是 `x`，
     * 但 PP-OCR 其它版本导出后叫 `image` / `inputs` 的都有；写死一个会导致
     * run() 抛 "invalid input name"，而报错不会告诉你正确的名字是什么。
     */
    private lateinit var detInputName: String
    private lateinit var recInputName: String

    override fun recognize(bitmap: Bitmap): List<OcrBox> {
        if (closed) return emptyList()

        val boxes = detect(bitmap)
        if (boxes.isEmpty()) return emptyList()

        val out = ArrayList<OcrBox>(boxes.size)
        for (b in boxes.take(MAX_REC_CROPS)) {
            val crop = cropAxial(bitmap, b)
            if (crop == null) continue
            try {
                out.add(recognizeCrop(crop, b))
            } finally {
                crop.recycle()
            }
        }
        // 阅读顺序：先上后下，同一行（纵向重叠）内再从左到右。
        return out.sortedWith(compareBy({ it.box.top }, { it.box.left }))
    }

    override fun close() {
        if (closed) return
        closed = true
        try { det.close() } catch (_: Throwable) { }
        try { rec.close() } catch (_: Throwable) { }
        // env 是进程级单例，**不要 close** —— 关了之后同进程再建引擎会炸。
    }

    // ───────────────────────────────────────────────────────────
    // 检测
    // ───────────────────────────────────────────────────────────

    private fun detect(bitmap: Bitmap): List<Rect> {
        val input = detInput(bitmap)
        val tensor = OnnxTensor.createTensor(env, FloatBuffer.wrap(input.data), input.shape)
        try {
            val result = det.run(Collections.singletonMap(detInputName, tensor))
            result.use { r ->
                // 输出签名（实测）：name='fetch_name_0'  shape=[N, 1, dH, dW]
                // 是 DB 的**概率图**，不是文本框坐标 —— 后处理必须自己做。
                // r[0].value 是 float[][][][]，编译期拿不到泛型，统一走反射。
                val prob = r[0].value
                val batch0 = java.lang.reflect.Array.get(prob, 0)
                // batch0 可能是 FloatArray（输出已 squeeze）也可能是 float[][]
                val map: Any = if (batch0 is FloatArray) batch0 else java.lang.reflect.Array.get(batch0, 0)
                val h = java.lang.reflect.Array.getLength(map)
                val first = java.lang.reflect.Array.get(map, 0)
                val w = java.lang.reflect.Array.getLength(first)

                // 摊平成一份 FloatArray：后面二值化要用阈值，打分要用原值，
                // 不能像早期版本那样只留 BooleanArray（那样就没法算 box_thresh 了）。
                val flat = FloatArray(h * w)
                for (y in 0 until h) {
                    val row = java.lang.reflect.Array.get(map, y) as FloatArray
                    System.arraycopy(row, 0, flat, y * w, w)
                }
                return boxesFromProbMap(flat, w, h, bitmap.width, bitmap.height)
            }
        } finally {
            tensor.close()
        }
    }

    /**
     * 概率图 → 文本框。对应官方 DBPostProcess，逐条对齐：
     *
     *   · `pred > thresh(0.2)` 二值化
     *   · `cv2.findContours`   -> 这里用**按行扫描连通区**的纯 Kotlin 版本
     *                             （上下相邻且 x 重叠就并成一个框）
     *   · `box_score_fast`     -> 框内**概率均值** < box_thresh(0.45) 丢弃
     *   · `unclip`             -> distance = area * unclip_ratio(1.4) / perimeter，四边外扩
     *   · 最后按 width/height 比例映射回原图坐标
     *
     * 复杂度 O(H*W)，0.7M 像素的图上几百万次比较，比引一个图像处理库更快且无额外依赖。
     */
    private fun boxesFromProbMap(
        prob: FloatArray,
        w: Int,
        h: Int,
        srcW: Int,
        srcH: Int,
    ): List<Rect> {
        // ① 每行取连续段 [y, x0, x1]
        val segs = ArrayList<IntArray>()
        for (y in 0 until h) {
            val row = y * w
            var x = 0
            while (x < w) {
                if (prob[row + x] <= BIN_THRESHOLD) { x++; continue }
                val start = x
                while (x < w && prob[row + x] > BIN_THRESHOLD) x++
                segs.add(intArrayOf(y, start, x - 1))
            }
        }

        // ② 上下相邻且 x 重叠 → 同一个框
        //
        // ⚠️ 三条 Kotlin 语法约束（都踩过）：
        //   1. 字段必须用 `var`：框会在逐行扫描中被**原地扩展**。用 val 会报
        //      "Val cannot be reassigned"，而报错行指向赋值处、真因在类型声明处。
        //   2. 这是**局部类**（声明在函数体内），**不能加 `private`** ——
        //      局部类没有类外可见性概念，加了报
        //      "Modifier 'private' is not applicable to 'local class'"。
        //   3. 用普通 class 而非 data class：`!==` 要比较引用同一性，
        //      data class 的 equals 语义在这里会造成误判。
        class Box(var x0: Int, var y0: Int, var x1: Int, var y1: Int)

        // 局部函数：能直接引用上面的局部类 Box，比反射取字段干净得多。
        // 对应官方 box_score_fast —— 取框内**概率**均值（不是二值图的均值）。
        fun boxScore(b: Box): Float {
            val x0 = b.x0.coerceIn(0, w - 1)
            val x1 = b.x1.coerceIn(0, w - 1)
            val y0 = b.y0.coerceIn(0, h - 1)
            val y1 = b.y1.coerceIn(0, h - 1)
            var sum = 0.0
            var n = 0
            for (y in y0..y1) {
                val row = y * w
                for (x in x0..x1) { sum += prob[row + x]; n++ }
            }
            return if (n == 0) 0f else (sum / n).toFloat()
        }

        val live = ArrayList<Box>()
        val done = ArrayList<Box>()
        for (s in segs) {
            val y = s[0]; val x0 = s[1]; val x1 = s[2]
            val overlap = live.firstOrNull { b ->
                val ox0 = maxOf(b.x0, x0); val ox1 = minOf(b.x1, x1)
                val ow = ox1 - ox0
                ow > 0 && ow * 2 >= minOf(b.x1 - b.x0, x1 - x0)
            }
            if (overlap == null) {
                live.add(Box(x0, y, x1, y))
            } else {
                overlap.x0 = minOf(overlap.x0, x0)
                overlap.x1 = maxOf(overlap.x1, x1)
                overlap.y1 = y
            }
            // 上一行留下的框若这一行没被续上，就收工。
            val it = live.iterator()
            while (it.hasNext()) {
                val b = it.next()
                if (b !== overlap && b.y1 < y - 1) { done.add(b); it.remove() }
            }
        }
        done.addAll(live)

        val sx = srcW.toFloat() / w
        val sy = srcH.toFloat() / h

        val raw = ArrayList<Rect>()
        for (b in done) {
            // ③ box_thresh：框内概率均值太低就丢（过滤碎点与误检）
            if (boxScore(b) < BOX_THRESHOLD) continue

            // ④ unclip：distance = area * ratio / perimeter，四边等量外扩
            val bw = b.x1 - b.x0 + 1
            val bh = b.y1 - b.y0 + 1
            val d = (bw.toFloat() * bh * UNCLIP_RATIO) / (2f * (bw + bh))

            val rw = (bw + 2 * d) * sx
            val rh = (bh + 2 * d) * sy
            if (rw < MIN_BOX_PX || rh < MIN_BOX_PX) continue
            // ⚠️ 早期版本这里写成 `rh / rw < MIN_ASPECT_INV`，**方向是反的**：
            //    正常文字行 rh/rw≈0.15，会被整批丢掉 —— 等于检测全废，
            //    而且不报错、只是"什么都检不到"，极难排查。
            //    改成只看 宽/高 一个比值，上下限都放宽（下限允许竖排中文）。
            val aspect = rw / rh
            if (aspect < MIN_ASPECT || aspect > MAX_ASPECT) continue

            raw.add(
                Rect(
                    ((b.x0 - d) * sx).toInt().coerceIn(0, srcW),
                    ((b.y0 - d) * sy).toInt().coerceIn(0, srcH),
                    ((b.x1 + 1 + d) * sx).toInt().coerceIn(0, srcW),
                    ((b.y1 + 1 + d) * sy).toInt().coerceIn(0, srcH),
                )
            )
        }

        // ⑤ 按面积降序 + IoU 去重（替代真 NMS 的轻量版），并封顶 max_candidates
        raw.sortByDescending { it.width().toLong() * it.height() }
        val kept = ArrayList<Rect>()
        for (r in raw) {
            if (kept.size >= MAX_CANDIDATES) break
            if (kept.none { iou(it, r) > NMS_IOU }) kept.add(r)
        }
        return kept
    }

    private fun iou(a: Rect, b: Rect): Float {
        val ix = maxOf(0, minOf(a.right, b.right) - maxOf(a.left, b.left))
        val iy = maxOf(0, minOf(a.bottom, b.bottom) - maxOf(a.top, b.top))
        val inter = ix.toFloat() * iy
        if (inter <= 0f) return 0f
        val union = a.width().toFloat() * a.height() + b.width().toFloat() * b.height() - inter
        return if (union <= 0f) 0f else inter / union
    }

    // ───────────────────────────────────────────────────────────
    // 识别
    // ───────────────────────────────────────────────────────────

    /**
     * 识别一个文本框。
     *
     * **四方向兜底**（真实数据逼出来的，不是锦上添花）：预检现场的标识卡
     * 经常**倒贴**（2026-09-24 真实照片 IMG_20250405_140307_BURST002 实测：
     * 0° 时 5 个框全是乱码「目/：」「台管」，置信度 0.48~0.80；旋转 180° 后
     * 「供应商：」「产品型号：」等表头全部 0.97~1.00）。det 对倒置文字
     * **完全无感**（照样出框），所以兜底必须做在 rec 这一级。
     *
     * 策略：0° 置信度够高（打印体实测 0.92+）直接返回，**不付四方向的钱**；
     * 只有低置信度才再试 180/90/270，取「长度×置信度」最高的结果。
     * 打印体照片几乎零开销，倒置标签能救回来。
     */
    private fun recognizeCrop(crop: Bitmap, orig: Rect): OcrBox {
        val first = recognizeOnce(crop)
        var bestText = first.first
        var bestConf = first.second
        if (bestConf < FOUR_DIR_CONF) {
            for (deg in intArrayOf(180, 90, 270)) {
                val rotated = rotateBitmap(crop, deg) ?: continue
                val r = try {
                    recognizeOnce(rotated)
                } finally {
                    rotated.recycle()
                }
                if (r.first.length * r.second > bestText.length * bestConf) {
                    bestText = r.first
                    bestConf = r.second
                }
            }
        }
        return OcrBox(bestText, bestConf, orig)
    }

    /** 跑一次 rec（不旋转）。返回 (text, conf)。 */
    private fun recognizeOnce(crop: Bitmap): Pair<String, Float> {
        val input = recInput(crop)
        val tensor = OnnxTensor.createTensor(env, FloatBuffer.wrap(input.data), input.shape)
        try {
            val result = rec.run(Collections.singletonMap(recInputName, tensor))
            result.use { r ->
                // 输出签名（实测）：name='fetch_name_0'  shape=[N, T, 18710]
                val batch0 = java.lang.reflect.Array.get(r[0].value, 0)
                val frames: Int = java.lang.reflect.Array.getLength(batch0)
                val sb = StringBuilder()
                var confSum = 0.0
                var confN = 0
                var prev = -1
                for (t in 0 until frames) {
                    val vec = java.lang.reflect.Array.get(batch0, t) as FloatArray
                    var best = 0
                    for (i in vec.indices) if (vec[i] > vec[best]) best = i
                    // CTC 贪心解码：blank(下标 0) 跳过；与上一个**已发出**的字符
                    // 相同也跳过（折叠重复帧）。
                    if (best != 0 && best != prev) {
                        // ⚠️ keys 的第 0 项就是 blank 占位，所以直接取 keys[best]，
                        //    **不是** keys[best-1]（早期版本这里是 off-by-one，
                        //    整体错位一位且漏掉字典最后一条，输出全是错的邻居字）。
                        if (best in keys.indices) sb.append(keys[best])
                        confSum += softmaxMax(vec); confN++
                    }
                    prev = best
                }
                val conf = if (confN == 0) 0.0f else (confSum / confN).toFloat()
                return Pair(sb.toString(), conf)
            }
        } finally {
            tensor.close()
        }
    }

    private fun rotateBitmap(src: Bitmap, deg: Int): Bitmap? = try {
        if (deg == 0) src else {
            val m = Matrix()
            m.postRotate(deg.toFloat())
            Bitmap.createBitmap(src, 0, 0, src.width, src.height, m, true)
        }
    } catch (_: Throwable) {
        null
    }

    /** 取最大类的 softmax 概率。用 x-max 平移避免 exp 溢出。 */
    private fun softmaxMax(v: FloatArray): Double {
        var m = v[0]
        for (x in v) if (x > m) m = x
        var sum = 0.0
        for (x in v) sum += Math.exp((x - m).toDouble())
        return 1.0 / sum
    }

    // ───────────────────────────────────────────────────────────
    // 张量构造（前处理）
    // ───────────────────────────────────────────────────────────

    private class Tensor(val data: FloatArray, val shape: LongArray)

    /**
     * 检测输入。
     *
     * 归一化：**BGR 通道序 + ImageNet mean/std 按通道位置施加**
     * （(x/255 - mean) / std，mean[0]=0.485 落在 **B** 通道 —— 这是 PaddleOCR
     * 的历史约定，训练与推理一致，照抄即可，不要"修正"成 RGB 序）。
     */
    private fun detInput(bitmap: Bitmap): Tensor {
        val (dw, dh) = detResize(bitmap.width, bitmap.height)
        val scaled = Bitmap.createScaledBitmap(bitmap, dw, dh, true)
        val px = IntArray(dw * dh)
        scaled.getPixels(px, 0, dw, 0, 0, dw, dh)
        if (scaled !== bitmap) scaled.recycle()

        val plane = dw * dh
        val buf = FloatArray(3 * plane)
        for (i in px.indices) {
            val c = px[i]
            val b = (c and 0xFF) / 255f
            val g = ((c shr 8) and 0xFF) / 255f
            val r = ((c shr 16) and 0xFF) / 255f
            buf[i] = (b - DET_MEAN[0]) / DET_STD[0]
            buf[plane + i] = (g - DET_MEAN[1]) / DET_STD[1]
            buf[2 * plane + i] = (r - DET_MEAN[2]) / DET_STD[2]
        }
        return Tensor(buf, longArrayOf(1, 3, dh.toLong(), dw.toLong()))
    }

    /**
     * 识别输入。
     *
     * · 高度固定 48、宽度按 48*w/h 算并封顶 320（来自 yml 的 image_shape [3,48,320]）。
     * · 归一化 `(x/255 - 0.5) / 0.5` —— **与 det 不是一套**，yml 里没有
     *   NormalizeImage 项，这一步藏在 RecResizeImg 内部。
     * · 右侧补的是**归一化空间的 0.0**（= 原始像素 127.5 的中灰），
     *   对应官方 `padding_im = np.zeros(...)`。**不是黑边**：黑边归一化后是 -1.0，
     *   会被模型当成一整片墨迹。
     */
    private fun recInput(crop: Bitmap): Tensor {
        val plane = REC_W * REC_H
        val buf = FloatArray(3 * plane)
        val shape = longArrayOf(1, 3, REC_H.toLong(), REC_W.toLong())
        val w = crop.width
        val h = crop.height
        if (w <= 0 || h <= 0) return Tensor(buf, shape)

        val ratio = w.toFloat() / h
        val targetW = Math.ceil(REC_H * ratio.toDouble()).toInt().coerceIn(1, REC_W)
        val scaled = Bitmap.createScaledBitmap(crop, targetW, REC_H, true)
        val px = IntArray(targetW * REC_H)
        scaled.getPixels(px, 0, targetW, 0, 0, targetW, REC_H)
        if (scaled !== crop) scaled.recycle()

        // 只写左侧 targetW 列，其余保持 0.0（中灰填充）
        for (y in 0 until REC_H) {
            val srcRow = y * targetW
            val dstRow = y * REC_W
            for (x in 0 until targetW) {
                val c = px[srcRow + x]
                val b = (c and 0xFF) / 255f
                val g = ((c shr 8) and 0xFF) / 255f
                val r = ((c shr 16) and 0xFF) / 255f
                buf[dstRow + x] = (b - 0.5f) / 0.5f
                buf[plane + dstRow + x] = (g - 0.5f) / 0.5f
                buf[2 * plane + dstRow + x] = (r - 0.5f) / 0.5f
            }
        }
        return Tensor(buf, shape)
    }

    /** 轴对齐裁剪（见类注释第 2 条：不做透视矫正）。带边界保护。 */
    private fun cropAxial(src: Bitmap, r: Rect): Bitmap? {
        val l = r.left.coerceIn(0, src.width - 1)
        val t = r.top.coerceIn(0, src.height - 1)
        val rr = r.right.coerceIn(l + 1, src.width)
        val b = r.bottom.coerceIn(t + 1, src.height)
        return try {
            Bitmap.createBitmap(src, l, t, rr - l, b - t)
        } catch (_: Throwable) {
            null
        }
    }

    /**
     * det 的缩放：**按总像素数归一**，而不是官方的「短边 736、只放大不缩小」。
     * 理由见类注释第 1 条。横竖拍的计算量因此一致。
     */
    private fun detResize(w: Int, h: Int): Pair<Int, Int> {
        val px = w.toLong() * h.toLong()
        val scale = if (px > DET_TARGET_PIXELS) {
            Math.sqrt(DET_TARGET_PIXELS.toDouble() / px.toDouble())
        } else {
            1.0
        }
        return round32((w * scale).toInt()) to round32((h * scale).toInt())
    }

    /** 下采样 32 倍，边长必须是 32 的整数倍，否则 ONNX 报 shape 不匹配。 */
    private fun round32(v: Int): Int = (Math.round(v / 32f) * 32).coerceAtLeast(32)

    companion object {
        // ── det ──
        private val DET_MEAN = floatArrayOf(0.485f, 0.456f, 0.406f)
        private val DET_STD = floatArrayOf(0.229f, 0.224f, 0.225f)
        private const val DET_TARGET_PIXELS = 700_000L  // 见类注释第 1 条
        private const val BIN_THRESHOLD = 0.2f          // DBPostProcess.thresh
        private const val BOX_THRESHOLD = 0.45f         // DBPostProcess.box_thresh
        private const val UNCLIP_RATIO = 1.4f           // DBPostProcess.unclip_ratio
        private const val MAX_CANDIDATES = 3000         // DBPostProcess.max_candidates

        // ── rec ──
        private const val REC_H = 48     // yml image_shape [3,48,320]
        private const val REC_W = 320

        // ── 识别框上限与四方向 ──
        // 真实数据实测：隔着塑料袋拍的装箱单，反光区会让 det 出 300+ 个
        // >box_thresh 的框（PC 上逐框 rec 要 16s，手机只会更久）。det 的
        // 框已按面积降序，只把前 40 个送 rec —— 文字行永远比反光块大。
        private const val MAX_REC_CROPS = 40
        // 0° 置信度低于此值才试 180/90/270（打印体实测 0.92+，不触发）。
        private const val FOUR_DIR_CONF = 0.85f

        // ── 通用过滤 ──
        private const val MIN_BOX_PX = 8f
        private const val MIN_ASPECT = 0.33f     // 宽/高下限（<0.33 即竖长条，多半是误检；放宽松以容纳竖排中文）
        private const val MAX_ASPECT = 40f       // 宽/高上限（过长的一条横带多半是误检）
        private const val NMS_IOU = 0.5f

        private const val TAG = "PpOcrV6"

        private const val DET_FILE = "ppocr/det.onnx"
        private const val REC_FILE = "ppocr/rec.onnx"
        private const val KEYS_FILE = "ppocr/keys.txt"

        /**
         * 最近一次 [create] 失败的原因（null = 没失败过 / 没探测过）。
         *
         * P4 · 真机反馈（2026-09-24）："增强识别不可用"没有下文，真机上
         * 模型缺失 / session 创建失败 / 字典校验失败在 UI 上长一个样，
         * 只能连 logcat 才能区分。现在每一步失败都把人话写进这里，
         * 随 isReady 回传 Dart 显示。
         *
         * setter 公开是有意的：[PpOcrEngine.create] 这个分发层的
         * 最外层兜底异常也要留痕（只此一处外部写入）。
         */
        @Volatile
        var lastCreateError: String? = null
        private fun fail(reason: String, t: Throwable? = null): PpOcrEngine? {
            lastCreateError = reason
            android.util.Log.e(TAG, "create failed: $reason", t)
            return null
        }

        fun create(context: Context): PpOcrEngine? {
            lastCreateError = null

            val detF = materialize(context, DET_FILE)
                ?: return fail("检测模型缺失或拷贝失败（${DET_FILE}）—— 请确认 APK 内 assets 已打包")
            val recF = materialize(context, REC_FILE)
                ?: return fail("识别模型缺失或拷贝失败（${REC_FILE}）")
            val keysTxt = readAssetText(context, KEYS_FILE)
                ?: return fail("识别字典缺失（${KEYS_FILE}）")

            val env = try {
                OrtEnvironment.getEnvironment()
            } catch (t: Throwable) {
                return fail("ONNX Runtime 环境创建失败（so 加载可能不兼容此设备）", t)
            }
            val opts = OrtSession.SessionOptions().apply {
                setIntraOpNumThreads(2)   // 手机 4~8 核，2 线程足够且不抢 UI
            }
            val det: OrtSession
            val rec: OrtSession
            try {
                det = env.createSession(detF.absolutePath, opts)
            } catch (t: Throwable) {
                return fail("检测模型加载失败（${detF.absolutePath}）", t)
            }
            try {
                rec = env.createSession(recF.absolutePath, opts)
            } catch (t: Throwable) {
                try { det.close() } catch (_: Throwable) { }
                return fail("识别模型加载失败（${recF.absolutePath}）", t)
            }

            // 字典：blank + keys.txt 全文 + 末尾空格。下标布局见类注释。
            val keys = ArrayList<String>()
            keys.add("")                       // 下标 0 = CTC blank
            for (line in keysTxt.split('\n')) {
                // ⚠️ 只能剥 CR/LF：第 1748 条是 U+3000 全角空格，
                //    用 trim() 会把它读成空串，后面所有下标整体前移。
                val s = line.trimEnd('\r', '\n')
                if (s.isEmpty()) continue
                keys.add(s)
            }
            keys.add(" ")                      // 末位 = 半角空格

            // 拿模型输出维度反查字典长度，对不上宁可回退也不能输出错字。
            val classCount = classCountOf(rec)
            if (classCount > 0 && keys.size != classCount) {
                try { det.close() } catch (_: Throwable) { }
                try { rec.close() } catch (_: Throwable) { }
                return fail("字典与模型不匹配：字典 ${keys.size} 条，模型输出 $classCount 类 —— 模型与 keys.txt 不是一套")
            }

            return OnnxPpOcrEngine(env, det, rec, keys).apply {
                detInputName = inputNameOf(det)
                recInputName = inputNameOf(rec)
            }
        }

        /** rec 输出最后一维 = 类别数（含 blank）。动态轴拿不到时返回 0（跳过校验）。 */
        private fun classCountOf(session: OrtSession): Int = try {
            val info = session.outputInfo.values.firstOrNull() as? TensorInfo
            val shape = info?.shape
            if (shape == null || shape.isEmpty()) 0 else shape[shape.size - 1].toInt()
        } catch (_: Throwable) {
            0
        }

        /**
         * ONNX Runtime 只能从**文件路径**建 session，不能直接吃 assets。
         * 所以首次调用时把 assets 拷到 filesDir 一次，之后复用。
         *
         * 版本判断用「文件长度一致」—— 换模型时长度几乎一定不同；
         * 真撞上同长度的情况，清一次 App 数据即可。
         *
         * ⚠️ 长度的取法（P4 加固）：优先 `openFd().length`（未压缩资产，
         *    准确值）；压缩资产 openFd 会抛，退回 `available()` 估算 ——
         *    该值在不同 ROM 上实现不一，所以**只当猜测**：对不上就重拷
         *    一遍并校验非零长度。旧版把 available() 当真值，遇到不一致
         *    的 ROM 会"每次重拷 31MB"或"误判文件完好"。本方法只在
         *    create() 时跑一次（引擎被桥缓存），重拷代价可忽略。
         */
        private fun materialize(context: Context, asset: String): File? = try {
            val name = asset.substringAfterLast('/')
            val out = File(context.filesDir, "ppocr_$name")
            val lenGuess = try {
                context.assets.openFd(asset).use { fd ->
                    if (fd.length > 0) fd.length else null
                }
            } catch (_: Throwable) {
                null // 压缩资产没有 fd —— 正常，走估算分支
            } ?: context.assets.open(asset).use { it.available().toLong() }

            if (out.exists() && out.length() == lenGuess && out.length() > 0) {
                out
            } else {
                context.assets.open(asset).use { am ->
                    FileOutputStream(out).use { fos -> am.copyTo(fos) }
                }
                if (out.length() == 0L) {
                    android.util.Log.e(TAG, "materialize: copied 0 bytes: $asset")
                    null
                } else {
                    android.util.Log.i(TAG, "materialize: ${out.name} -> ${out.length()} bytes")
                    out
                }
            }
        } catch (t: Throwable) {
            android.util.Log.e(TAG, "materialize failed: $asset", t)
            null
        }

        private fun readAssetText(context: Context, asset: String): String? = try {
            context.assets.open(asset).bufferedReader().use { it.readText() }
        } catch (_: Throwable) {
            null
        }

        /** 输入名从 session 元数据里读，**不硬编码**。 */
        private fun inputNameOf(session: OrtSession): String {
            val names = session.inputNames
            return names.firstOrNull() ?: "x"
        }
    }
}
