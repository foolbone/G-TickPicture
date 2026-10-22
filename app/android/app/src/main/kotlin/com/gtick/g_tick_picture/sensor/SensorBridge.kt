package com.gtick.g_tick_picture.sensor

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlin.math.sqrt

/**
 * 手抖检测（2026-10-10「拍照体验对标系统相机」）。
 *
 * 为什么是加速度计而不是"读快门曝光时间"：本项目用的 camera 插件
 * 不暴露 ISO / 曝光时长 / OIS 状态，拿不到就拿不到，**不猜**（纪律 17）。
 * 但"按下快门那一刻手是不是在抖"这件事，加速度计是能真实测出来的。
 *
 * 为什么不引三方包（sensors_plus 之类）：本项目现场机是几百到一千块的
 * 安卓机，多一个插件就多一份版本求解与 Gradle 兼容风险；而这里只需要
 * 一个加速度计 + 一个滑动窗口，三十行 Kotlin 就够，且与已有三个桥
 * （ppocr / gallery / perf）同一套工程做法、同一套生命周期。
 *
 * 指标定义 —— **jerk RMS**（加速度模值相邻变化的均方根，单位 m/s²）：
 *   · 用"模值的变化"而不是"模值本身"，是因为**匀速移动手机**（转身去拍
 *     下一件货、把镜头从箱顶移到唛头）模值也偏离 1g，但那不是抖，
 *     不该报。抖的本质是**高频来回**。
 *   · 静止手持：0.1~0.4；明显手抖：1.5~4；边走边拍：5 以上。
 * 具体分级阈值放在 Dart 侧 [ShakeLevel]，好测、好调，不用重新打 APK。
 *
 * 生命周期：只在采集页可见时 start，离开立刻 stop —— 加速度计常开是
 * 实打实的耗电，现场一开就是一天（R1b 续航指标）。
 */
class SensorBridge(private val context: Context) :
    MethodChannel.MethodCallHandler, SensorEventListener {

    private val manager =
        context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager

    // ── 环形缓冲：只留最近 WINDOW_NS 的样本 ──────────────────────
    // 采样率 SENSOR_DELAY_GAME ≈ 50Hz → 1s 约 50 条，容量 128 足够。
    private companion object {
        const val CAP = 128
        const val WINDOW_NS = 1_000_000_000L // 1s
        const val MIN_SAMPLES = 6
    }

    private val lock = Any()
    private val ts = LongArray(CAP)
    private val mag = FloatArray(CAP)
    private var head = 0
    private var count = 0
    private var listening = false

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "start" -> result.success(start())
            "stop" -> {
                stop()
                result.success(null)
            }

            "jerk" -> result.success(jerk())
            else -> result.notImplemented()
        }
    }

    /** 开始采样。返回 false = 这台机器没有加速度计（调用方据此永久放弃）。 */
    private fun start(): Boolean {
        val sm = manager ?: return false
        val acc = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) ?: return false
        synchronized(lock) {
            if (listening) return true
            // 注册失败（极少数机器限制）就当没有 —— 手抖提示是锦上添花，
            // 绝不能因为它让采集页打不开。
            listening = sm.registerListener(this, acc, SensorManager.SENSOR_DELAY_GAME)
            if (!listening) return false
            head = 0
            count = 0
        }
        return true
    }

    private fun stop() {
        val sm = manager ?: return
        synchronized(lock) {
            if (!listening) return
            try {
                sm.unregisterListener(this)
            } catch (_: Throwable) {
            }
            listening = false
            head = 0
            count = 0
        }
    }

    /**
     * 最近窗口内的 jerk RMS（m/s²）。样本不足（刚 start / 机器没传感器）
     * 返回 null —— **没有数据 ≠ 不抖**，调用方拿到 null 必须闭嘴。
     */
    private fun jerk(): Double? {
        synchronized(lock) {
            if (count < MIN_SAMPLES) return null

            // 按时间从旧到新取出窗口内样本
            val n = count
            val listTs = LongArray(n)
            val listMag = FloatArray(n)
            for (i in 0 until n) {
                val idx = (head - n + i + CAP * 2) % CAP
                listTs[i] = ts[idx]
                listMag[i] = mag[idx]
            }
            val newest = listTs[n - 1]
            var sumSq = 0.0
            var used = 0
            for (i in 1 until n) {
                // event.timestamp 与这里比较的是同一单调时钟（纳秒）
                if (newest - listTs[i] > WINDOW_NS) continue
                val d = (listMag[i] - listMag[i - 1]).toDouble()
                sumSq += d * d
                used++
            }
            if (used < MIN_SAMPLES - 1) return null
            return sqrt(sumSq / used)
        }
    }

    // ── SensorEventListener ────────────────────────────────────

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ACCELEROMETER) return
        val x = event.values.getOrNull(0) ?: return
        val y = event.values.getOrNull(1) ?: return
        val z = event.values.getOrNull(2) ?: return
        val m = sqrt((x * x + y * y + z * z).toDouble()).toFloat()
        synchronized(lock) {
            ts[head] = event.timestamp
            mag[head] = m
            head = (head + 1) % CAP
            if (count < CAP) count++
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // 精度变化不影响 jerk 的统计口径，忽略。
    }

    fun shutdown() {
        stop()
    }
}
