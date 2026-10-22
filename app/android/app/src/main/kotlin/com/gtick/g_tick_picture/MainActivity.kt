package com.gtick.g_tick_picture

import android.content.Intent
import android.view.KeyEvent
import com.gtick.g_tick_picture.camera.SystemCameraBridge
import com.gtick.g_tick_picture.gallery.GalleryBridge
import com.gtick.g_tick_picture.perf.PerfBridge
import com.gtick.g_tick_picture.ppocr.PpOcrBridge
import com.gtick.g_tick_picture.sensor.SensorBridge
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

/**
 * 主 Activity。
 *
 * P4 诉求 4：挂上 PP-OCRv6 的 MethodChannel（`gtick/ppocr`）。
 *
 * ⚠️ 为什么在这里挂而不是写成一个 Flutter 插件：
 *   插件要单独一个 package + pubspec + 构建约定，为了一个通道
 *   不值当。引擎本身**不依赖 Flutter**（纯 Kotlin + ONNX Runtime），
 *   挂在 Activity 上反而更简单、更容易在原生侧单独调试。
 *
 * 生命周期：通道跟随 engine 生死，所以 close 挂 [cleanUpFlutterEngine]。
 * 不释放的话，ONNX session 持有的 native 内存会一直留在进程里 ——
 * 这正是 R1b「连续 8 小时内存不增长」要防的东西。
 */
class MainActivity : FlutterActivity() {

    private var ocrBridge: PpOcrBridge? = null
    private var galleryBridge: GalleryBridge? = null
    private var perfBridge: PerfBridge? = null
    private var sensorBridge: SensorBridge? = null

    // ── 系统相机拍照（2026-10-14 v0.22.0「拍照委托系统相机」）─────────
    // Dart 给临时文件路径 → 本桥拉起 ACTION_IMAGE_CAPTURE → 挂起
    // MethodChannel.Result → onActivityResult 回来再完成。
    private var systemCameraBridge: SystemCameraBridge? = null

    // ── 音量键快门（2026-10-12 v0.20.0，对标原生相机标配）─────────
    // Dart 侧采集页可见时 listen（volumeKeyActive=true）→ 音量上下键
    // 被拦截为快门事件（KeyEvent.keyCode 原样发给 Dart）；cancel /
    // 离开采集页 → 恢复系统音量调节。不 listen 时按键行为零改变。
    private var volumeKeyActive = false
    private var volumeKeySink: EventChannel.EventSink? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        val ocr = PpOcrBridge(applicationContext)
        ocrBridge = ocr
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, OCR_CHANNEL)
            .setMethodCallHandler(ocr)

        // 「拍照同时存入手机相册」—— 两个桥挂在同一个 engine 上，
        // 生命周期一致，一起在 cleanUpFlutterEngine 里收摊。
        val gallery = GalleryBridge(applicationContext)
        galleryBridge = gallery
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, GALLERY_CHANNEL)
            .setMethodCallHandler(gallery)

        // 性能：设备分级 + 原生缩略图解码（2026-09-29 全 App 性能排查）。
        val perf = PerfBridge(applicationContext)
        perfBridge = perf
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, PERF_CHANNEL)
            .setMethodCallHandler(perf)

        // 手抖检测（加速度计）。与上面三个桥同生命周期：
        // 不 stop 的话监听器会一直挂在进程里，一天下来是实打实的耗电。
        val sensor = SensorBridge(applicationContext)
        sensorBridge = sensor
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, SENSOR_CHANNEL)
            .setMethodCallHandler(sensor)

        // 音量键快门事件流（采集页 listen 时才拦截，见 onKeyDown）。
        EventChannel(flutterEngine.dartExecutor.binaryMessenger, KEYS_CHANNEL)
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(args: Any?, events: EventChannel.EventSink?) {
                    volumeKeyActive = true
                    volumeKeySink = events
                }

                override fun onCancel(args: Any?) {
                    volumeKeyActive = false
                    volumeKeySink = null
                }
            })

        // 系统相机拍照（v0.22.0）：launch(path) 拉起相机，结果经
        // onActivityResult 回到桥里，由它完成挂起的 MethodChannel 调用。
        // v2（2026-10-22）：同步契约 —— 首批随 launchSession 结果返回，
        // 晚到照片由 Dart 轮询 collectLate 拉取（无反向推送、无竞态）。
        val sysCam = SystemCameraBridge(this, flutterEngine.dartExecutor.binaryMessenger)
        systemCameraBridge = sysCam
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, SYSTEM_CAMERA_CHANNEL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "launch" -> {
                        val path = call.argument<String>("path")
                        if (path.isNullOrEmpty()) {
                            result.error("BAD_ARGS", "path is required", null)
                        } else {
                            sysCam.launch(path, result)
                        }
                    }
                    // 连拍会话（v0.24.2）：不带 EXTRA_OUTPUT，首批同步收
                    "launchSession" -> sysCam.launchSession(result)
                    // 晚到照片轮询（v2）：Dart 拉模式，一次一轮差集
                    "collectLate" -> {
                        val sid = call.argument<String>("sessionId")
                        if (sid.isNullOrEmpty()) {
                            result.error("BAD_ARGS", "sessionId is required", null)
                        } else {
                            sysCam.collectLate(sid, result)
                        }
                    }
                    // Dart 轮询结束，释放会话上下文
                    "endCollect" -> {
                        val sid = call.argument<String>("sessionId")
                        if (sid.isNullOrEmpty()) {
                            result.error("BAD_ARGS", "sessionId is required", null)
                        } else {
                            sysCam.endCollect(sid, result)
                        }
                    }
                    // 进程被杀后的会话恢复（v0.24.9）：用持久化的收图上下文
                    // 重跑一遍收图，照片照样进 App。
                    "recoverSession" -> sysCam.recoverSession(result)
                    else -> result.notImplemented()
                }
            }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        // 先给系统相机桥过一遍（它只认自己的 requestCode，其余原样放行）。
        systemCameraBridge?.onActivityResult(requestCode, resultCode, data)
        super.onActivityResult(requestCode, resultCode, data)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (volumeKeyActive && isVolumeKey(keyCode)) {
            volumeKeySink?.success(keyCode)
            return true // 吃掉：不调音量
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        // 按下时已拦，抬起也要拦 —— 否则抬起那下系统还是会调音量
        if (volumeKeyActive && isVolumeKey(keyCode)) return true
        return super.onKeyUp(keyCode, event)
    }

    private fun isVolumeKey(keyCode: Int): Boolean =
        keyCode == KeyEvent.KEYCODE_VOLUME_DOWN || keyCode == KeyEvent.KEYCODE_VOLUME_UP

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        ocrBridge?.shutdown()
        ocrBridge = null
        galleryBridge?.shutdown()
        galleryBridge = null
        perfBridge?.shutdown()
        perfBridge = null
        sensorBridge?.shutdown()
        sensorBridge = null
        systemCameraBridge = null
        volumeKeyActive = false
        volumeKeySink = null
        super.cleanUpFlutterEngine(flutterEngine)
    }

    private companion object {
        const val OCR_CHANNEL = "gtick/ppocr"
        const val GALLERY_CHANNEL = "gtick/gallery"
        const val PERF_CHANNEL = "gtick/perf"
        const val SENSOR_CHANNEL = "gtick/sensors"
        const val KEYS_CHANNEL = "gtick/keys"
        const val SYSTEM_CAMERA_CHANNEL = "gtick/system_camera"
    }
}
