package com.gtick.g_tick_picture.gallery

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.AudioManager
import android.media.MediaActionSound
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

/**
 * 「照片存入手机相册」的 MethodChannel 桥（P4 · 老板 2026-09-24 诉求）。
 *
 * ═══════════════════════════════════════════════════════════════
 * 职责边界：只做一件事 —— **把 App 私有目录里的一张已有照片，
 * 复制一份到系统相册**。不移动、不重命名、不删原件。
 *
 * 为什么是"复制一份"而不是"直接写到相册再从相册读"：
 *   1. App 私有副本是**交付源** —— 交付包、OCR、缩略图、重跑都依赖它。
 *      把原件交给 MediaStore，等于把命交给系统相册，删 APP / 清数据时
 *      业务数据会跟着丢，而那时交付还没做。
 *   2. 放款给用户靠相册副本 —— 他要的是"在相册里翻得到、能直接用微信发给同事"。
 *   所以两侧各一份，职责不同。
 *
 * ═══════════════════════════════════════════════════════════════
 * 幂等去重（老板 09-24 第三轮反馈：「手动操作会重复保存照片到相册」）：
 *   savePhoto 在写入前先查**同一相册目录下是否已有同名文件**——
 *   命中就跳过，返回 saved=false（不是错误）。去重做在原生写入点，
 *   「拍照自动存」和「概览页手动补存」两条路径就天然幂等：
 *   反复点补存，相册里不会多出第二份。
 *   同名判重是安全的：文件名带 5 位拍摄序号，不同照片必不同名。
 *
 * ═══════════════════════════════════════════════════════════════
 * savePhoto 返回契约：`Map{ "saved": Boolean, "uri": String }`
 *   · saved=true  —— 本次新写入，uri 是 MediaStore 的内容地址；
 *   · saved=false —— 相册里已有同名文件（幂等跳过），uri 是已有条目。
 *
 * 为什么不用第三方插件（`image_gallery_saver` / `gal` 等）：
 *   · 它们只实现 Android Q+ 的 MediaStore 路径，对 minSdk 26~28 要么
 *     退化得不对、要么照旧要 WRITE_EXTERNAL_STORAGE；
 *   · 本项目 minSdk = 26，两条路径都得写对，且失败原因要能回传 Dart。
 *
 * 线程模型：文件复制在 [Dispatchers.IO]，`result` 回到主线程 ——
 *   一张 5MB 的 JPEG 复制在真机上 100~400ms，主线程做会掉帧
 *   （连拍时连续触发，R1b）。
 */
class GalleryBridge(private val context: Context) : MethodChannel.MethodCallHandler {

    private val job = SupervisorJob()
    private val scope = CoroutineScope(job + Dispatchers.IO)

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            // 本机的写入条件 —— Dart 侧据此决定要不要先申请运行时权限。
            "status" -> postResult(result) {
                mapOf(
                    "needsPermission" to needsLegacyPermission(),
                    "granted" to hasWritePermission(),
                )
            }

            "savePhoto" -> {
                val path = call.argument<String>("path")
                val displayName = call.argument<String>("displayName")
                if (path.isNullOrEmpty() || displayName.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "path / displayName 必填", null)
                    return
                }
                val album = call.argument<String>("album")?.trim()?.takeIf { it.isNotEmpty() }
                    ?: ROOT_ALBUM
                val mime = call.argument<String>("mime")?.takeIf { it.isNotEmpty() } ?: "image/jpeg"
                val takenAtMs = call.argument<Number>("takenAtMs")?.toLong()

                scope.launch {
                    val src = File(path)
                    if (!src.exists()) {
                        postError(result, "NO_FILE", "照片文件不存在：$path")
                        return@launch
                    }
                    if (needsLegacyPermission() && !hasWritePermission()) {
                        // Android 8/9 写外置存储是危险权限 —— 没授权就
                        // 明确报 permission_denied，由 Dart 侧走运行时申请。
                        // 绝不在采集途中弹系统权限框打扰预检员。
                        postError(
                            result,
                            "PERMISSION_DENIED",
                            "未获得存储空间写入权限（Android ${Build.VERSION.SDK_INT}）",
                        )
                        return@launch
                    }
                    try {
                        // ── 幂等去重：已在相册里的同名文件直接跳过，不重复写入 ──
                        val existing = findExistingUri(album, displayName)
                        if (existing != null) {
                            Log.i(TAG, "already in gallery, skip: $album/$displayName")
                            postResult(result) {
                                mapOf("saved" to false, "uri" to existing)
                            }
                            return@launch
                        }
                        val uri = saveIntoGallery(src, album, displayName, mime, takenAtMs)
                        Log.i(TAG, "saved to gallery: $album/$displayName -> $uri")
                        postResult(result) { mapOf("saved" to true, "uri" to uri) }
                    } catch (t: Throwable) {
                        Log.e(TAG, "savePhoto failed: $path", t)
                        postError(result, "IO_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // ── 删除相册镜像（2026-10-10 v0.19.0「拍后回看·重拍」）──
            // 重拍 = 原图/缩略图/库行一起删（PhotoDeletionService），相册里
            // 那份镜像也要跟着走，否则相册会留下"拍废的那张"。只删
            // **本 App 自己插入**的条目（按 ROOT_ALBUM/album/displayName 定位，
            // 与 savePhoto 的写入路径严格对偶）—— 绝不按通配符删别人的图。
            // 尽力而为：删不到（已手动清过 / 查询被 ROM 拒）返回 deleted=false，
            // Dart 侧静默 —— 相册多一张旧图远小于让重拍卡住。
            "deletePhoto" -> {
                val displayName = call.argument<String>("displayName")
                if (displayName.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "displayName 必填", null)
                    return
                }
                val album = call.argument<String>("album")?.trim()?.takeIf { it.isNotEmpty() }
                    ?: ROOT_ALBUM
                scope.launch {
                    try {
                        val existing = findExistingUri(album, displayName)
                        if (existing == null) {
                            postResult(result) { mapOf("deleted" to false) }
                            return@launch
                        }
                        val deleted = if (existing.startsWith("content:")) {
                            // content:// 条目：delete 返回删除行数（>0 即成功）
                            context.contentResolver.delete(Uri.parse(existing), null, null) > 0
                        } else {
                            // Android 8/9 路径：findExistingByFile 返回 file:// uri，
                            // File.delete() 本身就返回 Boolean（别再拿去和 0 比较）
                            File(Uri.parse(existing).path ?: "").delete()
                        }
                        Log.i(TAG, "gallery mirror delete: $album/$displayName -> $deleted")
                        postResult(result) { mapOf("deleted" to deleted) }
                    } catch (t: Throwable) {
                        Log.e(TAG, "deletePhoto failed: $album/$displayName", t)
                        postError(result, "DELETE_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // ── 微信导入（M5.1 · 老板 09-27 拍板：采集时可从微信聊天记录导入）──
            // 只读**公共媒体库**里 owner=com.tencent.mm 的图片（微信里
            // 「保存」过的图 / 微信共享目录）。聊天记录的原图缓存在
            // Android/data 私有区，系统层面第三方不可见 —— 本 App 也
            // 不申请全文件访问权限（设计原则 9），边界要诚实。

            // 能力与授权状态：Dart 据此决定是否走运行时申请 / 引导兜底
            "wechatStatus" -> postResult(result) {
                val sdk = Build.VERSION.SDK_INT
                mapOf(
                    "supported" to (sdk >= Build.VERSION_CODES.Q),
                    "sdkInt" to sdk,
                    "granted" to hasMediaReadPermission(),
                )
            }

            // 微信贡献给公共媒体库的图片，时间倒序，限量（选择器不需要整库）
            "queryWeChatImages" -> {
                scope.launch {
                    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                        // OWNER_PACKAGE_NAME 列 Q 才有 —— 8/9 没有"按来源查"的能力
                        postError(result, "UNSUPPORTED", "需要 Android 10 及以上")
                        return@launch
                    }
                    try {
                        val list = queryWeChatImages()
                        postResult(result) { list }
                    } catch (t: Throwable) {
                        Log.e(TAG, "queryWeChatImages failed", t)
                        postError(result, "QUERY_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 网格缩略图：loadThumbnail 走系统缩略图缓存，绝不在 Dart 侧解码原图
            "wechatThumb" -> {
                val id = call.argument<Number>("id")?.toLong()
                val px = call.argument<Number>("sizePx")?.toInt() ?: 256
                if (id == null) {
                    result.error("BAD_ARGS", "id 必填", null)
                    return
                }
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
                    // loadThumbnail 是 API 29+ 方法 —— 低版本直接明确报错，
                    // 不能让它抛 NoSuchMethodError 把通道打挂
                    postError(result, "UNSUPPORTED", "需要 Android 10 及以上")
                    return
                }
                scope.launch {
                    try {
                        val bytes = loadThumbnailBytes(id, px)
                        postResult(result) { bytes }
                    } catch (t: Throwable) {
                        Log.e(TAG, "wechatThumb failed id=$id", t)
                        postError(result, "THUMB_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 把选中的微信图片流式复制到 cache 临时目录 —— 逐张容错，
            // 一张损坏图挡不住整批导入。临时路径交回 Dart，由它走
            // importFromGallery 主路径（EXIF 时间戳 / 连续 seq / 缩略图）。
            "readWeChatImages" -> {
                val ids = call.argument<List<Number>>("ids")
                if (ids.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "ids 必填", null)
                    return
                }
                scope.launch {
                    try {
                        val out = readWeChatImages(ids.map { it.toLong() })
                        postResult(result) { out }
                    } catch (t: Throwable) {
                        Log.e(TAG, "readWeChatImages failed", t)
                        postError(result, "READ_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 尽力而为：目录不存在 / 删除失败都不算错（cache 系统会兜底清）
            "cleanupWeChatTemp" -> postResult(result) {
                File(context.cacheDir, WECHAT_TEMP_DIR).deleteRecursively()
                true
            }

            // ── 相册导入找回真实拍摄时刻（2026-09-29「导入时间不对」修复）──
            // file_picker 只回传缓存副本路径（mtime = 复制那一刻），原始
            // 元数据全丢；没有 EXIF 的图（微信保存图 / 截图 / HEIC）落库
            // 时间便整批退化成导入时刻 → 时序聚类判定「不可信」→ 每张
            // 独立成组。file_picker 同时回传原始**文件名与字节数**，这对
            // 键在媒体库里几乎唯一 —— 拿它把 DATE_TAKEN 找回来。
            "queryDateTakenByNames" -> {
                val items = call.argument<List<*>>("items")
                if (items.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "items 必填", null)
                    return
                }
                scope.launch {
                    try {
                        val out = queryDateTakenByNames(items)
                        postResult(result) { out }
                    } catch (t: Throwable) {
                        Log.e(TAG, "queryDateTakenByNames failed", t)
                        postError(result, "QUERY_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // ── 相册选择器（2026-09-29「优化从相册选择照片」）：原生读 MediaStore，
            //    返回带真实拍摄时刻、分桶、缩略图的网格数据；Dart 侧自建网格
            //    UI，支持连选 / 时间定位 / 记忆位置，替代 file_picker 的简陋对话框。

            // 相册读取授权状态：Dart 据此决定进页面后怎么引导，别拿查询异常当权限探测。
            // granted 含 Android 14 的「仅允许选中的照片」（VISUAL_USER_SELECTED）——
            // 那种授权下 MediaStore 只回用户勾选过的行，UI 必须明说，不能装作没发生。
            "galleryStatus" -> postResult(result) {
                val sdk = Build.VERSION.SDK_INT
                mapOf(
                    "sdkInt" to sdk,
                    "granted" to hasMediaReadPermission(),
                    "fullAccess" to hasFullMediaReadPermission(),
                )
            }

            "queryGalleryImages" -> {
                val limit = (call.argument<Number>("limit")?.toInt() ?: 120).coerceAtLeast(1)
                val offset = (call.argument<Number>("offset")?.toInt() ?: 0).coerceAtLeast(0)
                val bucket = call.argument<String>("bucket")?.takeIf { it.isNotEmpty() }
                val ascending = call.argument<Boolean>("ascending") ?: false
                // 当天边界（毫秒），Dart 按本地时区算好传入；两者同时给才生效
                val dayStartMs = call.argument<Number>("dayStartMs")?.toLong()
                val dayEndMs = call.argument<Number>("dayEndMs")?.toLong()
                scope.launch {
                    try {
                        val list = queryGalleryImages(
                            limit, offset, bucket, ascending, dayStartMs, dayEndMs,
                        )
                        postResult(result) { list }
                    } catch (t: Throwable) {
                        Log.e(TAG, "queryGalleryImages failed", t)
                        postError(result, "QUERY_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 有照片的日期清单（2026-10-12 v0.20.0「按日期看照片」）：
            // 日期选择器据此把没有照片的日子置灰 —— 从源头消除
            // 「选了没反应」（目标日期没照片时的旧定位行为就是原地不动）。
            // 入参 tzOffsetMs = Dart 侧本地时区偏移；返回自 epoch 的本地
            // 天序号（倒序，上限 2000 天 = firstDate 的 5 年窗口）。
            "queryGalleryDays" -> {
                val tzOffsetMs = call.argument<Number>("tzOffsetMs")?.toLong() ?: 0L
                val bucket = call.argument<String>("bucket")?.takeIf { it.isNotEmpty() }
                scope.launch {
                    try {
                        val days = queryGalleryDays(tzOffsetMs, bucket)
                        postResult(result) { days }
                    } catch (t: Throwable) {
                        Log.e(TAG, "queryGalleryDays failed", t)
                        postError(result, "QUERY_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            "queryGalleryBuckets" -> {
                scope.launch {
                    try {
                        val list = queryGalleryBuckets()
                        postResult(result) { list }
                    } catch (t: Throwable) {
                        Log.e(TAG, "queryGalleryBuckets failed", t)
                        postError(result, "QUERY_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 网格缩略图：系统缩略图缓存（Q+），低版本回退到解码降采样（绝不传原图字节）。
            "galleryThumb" -> {
                val id = call.argument<Number>("id")?.toLong()
                val px = call.argument<Number>("sizePx")?.toInt() ?: 256
                if (id == null) {
                    result.error("BAD_ARGS", "id 必填", null)
                    return
                }
                scope.launch {
                    try {
                        val bytes = loadGalleryThumb(id, px)
                        postResult(result) { bytes }
                    } catch (t: Throwable) {
                        Log.e(TAG, "galleryThumb failed id=$id", t)
                        postError(result, "THUMB_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 把选中的相册图片流式复制到 cache 临时目录 —— 逐张容错。
            // 返回原生已知的真实拍摄时刻（DATE_TAKEN 优先），Dart 侧直接带进落库，
            // 不再需要「按文件名+大小回查」的 hack。
            "readGalleryImages" -> {
                val ids = call.argument<List<Number>>("ids")
                if (ids.isNullOrEmpty()) {
                    result.error("BAD_ARGS", "ids 必填", null)
                    return
                }
                scope.launch {
                    try {
                        val out = readGalleryImages(ids.map { it.toLong() })
                        postResult(result) { out }
                    } catch (t: Throwable) {
                        Log.e(TAG, "readGalleryImages failed", t)
                        postError(result, "READ_ERROR", t.message ?: t.javaClass.simpleName)
                    }
                }
            }

            // 尽力而为清理（临时目录在外部私有 files 下，系统不会自动清，
            // 所以这里必须真的删；导入已把文件 rename 走，剩下的都是残次品）。
            "cleanupGalleryTemp" -> postResult(result) {
                try {
                    galleryTempDir().deleteRecursively()
                } catch (t: Throwable) {
                    Log.w(TAG, "cleanup gallery temp failed", t)
                }
                true
            }

            // 系统快门音（2026-10-08）：照片落库后由 Dart 侧调用。
            // 体积小、同步返回，不进 IO 协程 —— MediaActionSound 内部自管线程。
            "playShutter" -> {
                playShutter()
                postResult(result) { true }
            }

            else -> result.notImplemented()
        }
    }

    /**
     * 播放系统快门音（2026-10-08 老板诉求：「拍照时需要有快门声音，
     * 提示用户拍照成功」）。
     *
     * 用 [MediaActionSound] 的 SHUTTER_CLICK —— 就是系统相机按快门那个
     * 声音，用户已经习惯把它理解成"拍上了"。Dart 侧在**照片成功落库**
     * 之后调用（不是快门按下就响）：响 = 真的存进去了，符合"提示成功"
     * 的本意。
     *
     * 实现细节：
     *  · [MediaActionSound] 内部自加载，首次 play 会有几十毫秒延迟，
     *    连拍第 2 张起就是零延迟 —— 可接受，不值得预加载整套。
     *  · 响了之后不 release（连接拍场景反复重建更贵），挂在桥的生死上。
     *  · 静音模式/媒体音量为 0 时系统不响 —— 这是用户自己的选择，
     *    不强行绕过（也不用 ToneGenerator 硬灌）。
     */
    private var shutterSound: MediaActionSound? = null

    private fun playShutter() {
        try {
            val s = shutterSound ?: MediaActionSound().also { shutterSound = it }
            s.play(MediaActionSound.SHUTTER_CLICK)
        } catch (t: Throwable) {
            // 声音只是提示，绝不因为播放失败让拍照报错
            Log.w(TAG, "play shutter sound failed", t)
        }
    }

    /**
     * 相比 OCR 的滑躺式关闭，这里打算走得干流：
     * 一次复制最多几百毫秒，[job.cancel] 不会损伤任何已写入的文件
     * （已经 insert 成功的都由 MediaStore 自己管生死）。
     */
    fun shutdown() {
        try {
            shutterSound?.release()
            shutterSound = null
        } catch (_: Throwable) {
        }
        try {
            job.cancel()
        } catch (_: Throwable) {
        }
    }

    // ───────────────────────────────────────────────────────────

    /**
     * 查「这个相册目录里是否已有同名文件」。有 → 返回它的 uri 字符串。
     *
     * Android 10+：查 MediaStore。分区存储下**无权限也能查到自己贡献的条目**，
     *   而这些相册副本全是本 App 写的 —— 查询范围恰好覆盖。
     *   relative_path 用**带尾斜杠 + 不带尾斜杠两种形态**都匹配：
     *   AOSP 会把插入的相对路径规范化成带 `/` 结尾，但各 ROM 表现不一，
     *   IN 两种形态一次查清，不赌规范化行为。
     *   过滤 `is_pending = 0` —— pending 是上一张写到一半的半成品，
     *   不算"已存在"，不挡本次重存。
     *
     * Android 8/9：直接看实体文件是否存在（DATA 指向的路径）。
     */
    private fun findExistingUri(album: String, displayName: String): String? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                findExistingUriQ(album, displayName)
            } catch (t: Throwable) {
                // ⚠️ 去重查询只是**优化**，绝不能变成保存失败的门槛（2026-10-08）：
                // 真机出现过 ROM 的 MediaProvider 拒绝 selection（Invalid token）。
                // 查询炸了就当"不存在"继续走插入 —— 最坏结果是多存一份副本，
                // 代价远小于「一整批照片补存失败」。顺手用实体路径兜一层：
                // 本 App 写的目录结构固定，File.exists 判得准。
                Log.w(TAG, "findExistingUri failed, fallback to file check", t)
                findExistingByFile(album, displayName)
            }
        } else {
            findExistingByFile(album, displayName)
        }
    }

    private fun findExistingByFile(album: String, displayName: String): String? {
        @Suppress("DEPRECATION")
        val f = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES),
            "$ROOT_ALBUM/$album/$displayName",
        )
        return if (f.exists()) Uri.fromFile(f).toString() else null
    }

    /** Android 10+ 的去重查询。列名必须用 MediaStore 的**真实列名**。 */
    private fun findExistingUriQ(album: String, displayName: String): String? {
        // ⚠️ 列名必须用 MediaStore 的**真实列名**（2026-10-08 真机报错修复）：
        //   MediaColumns.DISPLAY_NAME 的常量值是 "_display_name"（带下划线前缀），
        //   files 表里根本没有 "display_name" 这一列。旧版 MediaProvider 对
        //   selection 里的旧别名做过兼容映射所以能跑；新版媒体模块
        //   （Android 11+ 的 MediaProvider APK 随 Play 更新）直接走 SQL 分词器
        //   校验 → `IllegalArgumentException: Invalid token display_name`
        //   —— 表现为「补存到相册全部失败：IO_ERROR: Invalid token display_name」。
        //   写字面量是因为这些常量是 API 29+，避免 lint NewApi 误报；
        //   但字面量必须与常量**值**一致，不能想当然少写下划线。
        //   同类修正：`size` → `_size`（见 queryDateTakenByNames）。
        val selection =
            "(relative_path = ? OR relative_path = ?) AND _display_name = ? AND is_pending = 0"
        val args = arrayOf(
            "$ROOT_RELATIVE/$album/",
            "$ROOT_RELATIVE/$album",
            displayName,
        )
        return context.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            arrayOf(MediaStore.Images.Media._ID),
            selection,
            args,
            null,
        )?.use { c ->
            if (c.moveToFirst()) {
                ContentUris.withAppendedId(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                    c.getLong(0),
                ).toString()
            } else {
                null
            }
        }
    }

    /**
     * 实际写入（调用前已确认同名文件不存在）。
     *
     * Android 10+：[MediaStore.Images.Media.RELATIVE_PATH] + `IS_PENDING`。
     *   **不需要任何权限** —— 分区存储下 App 往公共媒体库插自己产出的图片
     *   是免权操作。先插 IS_PENDING=1 占位、写完再置 0，是为了不让相册
     *   扫到一个"写到一半"的文件（IS_PENDING=1 期间对其他 App 不可见）。
     *
     * Android 8/9：[MediaStore.Images.Media.DATA] 指向 Pictures 下的实体路径。
     *   `DATA` 在 Q+ 已废弃但在 P- 是唯一办法，且必须先 mkdirs。
     */
    @Suppress("DEPRECATION") // Q+ 走 RELATIVE_PATH 分支，这里只服务 8/9
    private fun saveIntoGallery(
        src: File,
        album: String,
        displayName: String,
        mime: String,
        takenAtMs: Long?,
    ): String {
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, displayName)
            put(MediaStore.Images.Media.MIME_TYPE, mime)
            // DATE_TAKEN 决定它在相册里的排序位置 —— 不填的话相册会按
            // 插入时间排，复制入库的顺序未必是拍摄顺序（回收 cores 时更乱）。
            if (takenAtMs != null) put(MediaStore.Images.Media.DATE_TAKEN, takenAtMs)

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.Images.Media.RELATIVE_PATH, "$ROOT_RELATIVE/$album")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            } else {
                val dir = File(
                    Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_PICTURES,
                    ),
                    "$ROOT_ALBUM/$album",
                )
                if (!dir.exists() && !dir.mkdirs()) {
                    throw IllegalStateException("无法创建相册目录：$dir")
                }
                put(MediaStore.Images.Media.DATA, File(dir, displayName).path)
            }
        }

        val resolver = context.contentResolver
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
            ?: throw IllegalStateException("MediaStore 插入失败（返回 null）")

        try {
            FileInputStream(src).use { input ->
                val out = resolver.openOutputStream(uri)
                    ?: throw IllegalStateException("无法打开相册输出流")
                out.use { input.copyTo(it, BUFFER_SIZE) }
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val published = ContentValues().apply {
                    put(MediaStore.Images.Media.IS_PENDING, 0)
                }
                resolver.update(uri, published, null, null)
            }
        } catch (t: Throwable) {
            // 写一半失败必须把半成品删掉 —— 否则相册里会留一张打不开的图，
            // 现场会以为是照片丢帧。
            try {
                resolver.delete(uri, null, null)
            } catch (_: Throwable) {
            }
            throw t
        }

        return uri.toString()
    }

    /// Android 10 以下写公共目录要危险权限。
    private fun needsLegacyPermission(): Boolean =
        Build.VERSION.SDK_INT <= Build.VERSION_CODES.P

    private fun hasWritePermission(): Boolean {
        if (!needsLegacyPermission()) return true
        return context.checkSelfPermission(
            android.Manifest.permission.WRITE_EXTERNAL_STORAGE,
        ) == PackageManager.PERMISSION_GRANTED
    }

    // ── 微信导入（M5.1）──────────────────────────────────────

    /**
     * 读**别人 App** 的媒体需要读权限（写才是 Q+ 免权的那个）。
     * 13+ 拆成细分权限；14 的「部分照片访问」（用户只勾了部分图）
     * 用 READ_MEDIA_VISUAL_USER_SELECTED 也算数 —— 查得到几张算几张。
     * 权限常量用字面量而非 VERSION_CODES.TIRAMISU，避免 compileSdk 差异。
     */
    private fun hasMediaReadPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= 33) {
            context.checkSelfPermission("android.permission.READ_MEDIA_IMAGES") ==
                PackageManager.PERMISSION_GRANTED ||
                context.checkSelfPermission(
                    "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
                ) == PackageManager.PERMISSION_GRANTED
        } else {
            context.checkSelfPermission(
                android.Manifest.permission.READ_EXTERNAL_STORAGE,
            ) == PackageManager.PERMISSION_GRANTED
        }
    }

    /**
     * **完整**读权限（不含 Android 14 的「仅选中的照片」部分授权）。
     * partial = granted 且非 full —— UI 要据这个差别提示用户去设置里放开。
     */
    private fun hasFullMediaReadPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= 33) {
            context.checkSelfPermission("android.permission.READ_MEDIA_IMAGES") ==
                PackageManager.PERMISSION_GRANTED
        } else {
            context.checkSelfPermission(
                android.Manifest.permission.READ_EXTERNAL_STORAGE,
            ) == PackageManager.PERMISSION_GRANTED
        }
    }

    /**
     * 微信（owner=com.tencent.mm）写进公共媒体库的图片，时间倒序，限量。
     *
     * 关键过滤：`owner_package_name = 'com.tencent.mm' AND is_pending = 0`。
     * is_pending=1 是别的 App 写到一半的半成品，列出来会打不开。
     */
    private fun queryWeChatImages(): List<Map<String, Any?>> {
        val projection = arrayOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.Images.Media.DATE_ADDED,
            MediaStore.Images.Media.SIZE,
            MediaStore.Images.Media.RELATIVE_PATH,
        )
        val selection = "owner_package_name = ? AND is_pending = 0"
        val args = arrayOf(WECHAT_PACKAGE)
        val sort = "${MediaStore.Images.Media.DATE_ADDED} DESC"
        val out = ArrayList<Map<String, Any?>>()
        context.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            projection, selection, args, sort,
        )?.use { c ->
            val idCol = c.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
            val nameCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DISPLAY_NAME)
            val takenCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_TAKEN)
            val addedCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_ADDED)
            val sizeCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.SIZE)
            val pathCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.RELATIVE_PATH)
            while (c.moveToNext() && out.size < WECHAT_QUERY_LIMIT) {
                val taken = c.getLong(takenCol)
                val added = c.getLong(addedCol) * 1000L
                out.add(
                    mapOf(
                        "id" to c.getLong(idCol),
                        "displayName" to (c.getString(nameCol) ?: ""),
                        // DATE_TAKEN 是毫秒；DATE_ADDED 是秒 —— 单位差异别搞混
                        "dateMs" to if (taken > 0) taken else added,
                        "sizeBytes" to c.getLong(sizeCol),
                        "relativePath" to (c.getString(pathCol) ?: ""),
                    ),
                )
            }
        }
        return out
    }

    /**
     * 按（display_name, size）回查图片的真实拍摄时刻（2026-09-29）。
     *
     * 返回与 [items] 按下标对齐的毫秒数；查不到为 0（Dart 侧转 null，
     * 退化走 EXIF → 文件时间的老路）。多行命中（同名同大小的重复副本）
     * 取最大的那个时刻 —— 重复副本的时间本来就应近似相等。
     *
     * 权限边界：读**别人 App** 的媒体行需要 READ_MEDIA_IMAGES（13+），
     * 相册导入在拉选择器之前已申请；没授权时查询只看得见自己的行，
     * 大概率查不到 → 静默退化，绝不报错阻塞导入。
     * 只查 Images 表 —— 从「文件管理器」等非媒体库入口选的图查不到，
     * 同样走退化路径（尽力而为，不追求全覆盖）。
     */
    private fun queryDateTakenByNames(items: List<*>): List<Long> {
        val out = ArrayList<Long>(items.size)
        for (element in items) {
            var best = 0L
            val item = element as? Map<*, *>
            val name = item?.get("name") as? String
            val size = (item?.get("size") as? Number)?.toLong()
            if (!name.isNullOrEmpty() && size != null && size > 0) {
                try {
                    context.contentResolver.query(
                        MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                        arrayOf(
                            MediaStore.Images.Media.DATE_TAKEN,
                            MediaStore.Images.Media.DATE_ADDED,
                        ),
                        "_display_name = ? AND _size = ? AND is_pending = 0",
                        arrayOf(name, "$size"),
                        null,
                    )?.use { c ->
                        val takenCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_TAKEN)
                        val addedCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_ADDED)
                        while (c.moveToNext()) {
                            // DATE_TAKEN 是毫秒；DATE_ADDED 是秒 —— 单位差异别搞混
                            val taken = c.getLong(takenCol)
                            val added = c.getLong(addedCol) * 1000L
                            val ms = if (taken > 0) taken else added
                            if (ms > best) best = ms
                        }
                    }
                } catch (t: Throwable) {
                    // 单条失败只影响这一张的时间，记日志继续
                    Log.w(TAG, "date lookup failed for $name", t)
                }
            }
            out.add(best)
        }
        return out
    }

    /** 系统缩略图（MediaProvider 自带缓存，不解码原图）。失败由调用方兜。 */
    private fun loadThumbnailBytes(id: Long, px: Int): ByteArray {
        val uri = ContentUris.withAppendedId(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id,
        )
        val bmp = context.contentResolver.loadThumbnail(
            uri, android.util.Size(px, px), null,
        )
        val bos = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 80, bos)
        bmp.recycle()
        return bos.toByteArray()
    }

    /** 逐张复制到 cache 临时目录；单张失败记 error 继续，不挡整批。 */
    private fun readWeChatImages(ids: List<Long>): List<Map<String, Any?>> {
        val dir = File(context.cacheDir, WECHAT_TEMP_DIR)
        if (!dir.exists() && !dir.mkdirs()) {
            throw IllegalStateException("无法创建临时目录")
        }
        val out = ArrayList<Map<String, Any?>>()
        for (id in ids) {
            try {
                val uri = ContentUris.withAppendedId(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id,
                )
                val name = queryDisplayName(id) ?: "wechat_$id.jpg"
                val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), "_")
                val dst = File(dir, "${id}_$safe")
                val input = context.contentResolver.openInputStream(uri)
                    ?: throw IllegalStateException("无法打开图片流 id=$id")
                input.use { ins ->
                    FileOutputStream(dst).use { outs -> ins.copyTo(outs, BUFFER_SIZE) }
                }
                out.add(mapOf("id" to id, "tempPath" to dst.absolutePath, "displayName" to name))
            } catch (t: Throwable) {
                Log.e(TAG, "read wechat image failed id=$id", t)
                out.add(mapOf("id" to id, "error" to (t.message ?: t.javaClass.simpleName)))
            }
        }
        return out
    }

    private fun queryDisplayName(id: Long): String? {
        return context.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            arrayOf(MediaStore.Images.Media.DISPLAY_NAME),
            "${MediaStore.Images.Media._ID} = ?",
            arrayOf("$id"),
            null,
        )?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    }

    /**
     * 相册选择器用的全库图片查询（2026-09-29）。
     *
     * 按 DATE_TAKEN 排序（缺失退化 DATE_ADDED*1000），分页（limit/offset）。
     * [bucket] 非空时按 `bucket_display_name` 过滤（顶部下拉「只看某相册」）。
     *
     * ⚠️ 版本分支（2026-09-29 真机空态排查的教训）：
     *   `is_pending` 和 `BUCKET_DISPLAY_NAME` 都是 **API 29+ 列** ——
     *   Android 8/9（minSdk 26~28）上照写会抛 "no such column"，
     *   选择器整个空掉。Q+ 才带这两列；8/9 用 DATA 路径推桶名、
     *   桶过滤用路径 LIKE 近似（8/9 本就是兼容路径，够用）。
     *
     * ⚠️⚠️ 排序列名教训（2026-09-29 真机 "Invalid token date_taken"）：
     *   `MediaStore.Images.Media.DATE_TAKEN` 的**底层列名是 `datetaken`**
     *   （无下划线！）—— 排序子句里裸写 "date_taken" 在 AOSP 是
     *   no such column，在魔改 MediaProvider 的 ROM 上直接 "Invalid token"。
     *   **SQL 片段里的列名一律用 SDK 常量拼，绝不手写**。个别 ROM 连
     *   COALESCE 都不认，所以排序从「COALESCE 修正列」逐级退化到裸列，
     *   总有一条能跑。
     */
    private fun queryGalleryImages(
        limit: Int,
        offset: Int,
        bucket: String?,
        ascending: Boolean,
        dayStartMs: Long?,
        dayEndMs: Long?,
    ): List<Map<String, Any?>> {
        val q = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
        val projection = mutableListOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.Images.Media.DATE_ADDED,
            MediaStore.Images.Media.SIZE,
            MediaStore.Images.Media.MIME_TYPE,
        )
        if (q) {
            projection += MediaStore.Images.Media.BUCKET_DISPLAY_NAME
        } else {
            @Suppress("DEPRECATION")
            projection += MediaStore.Images.Media.DATA
        }

        val sel: String?
        val selArgs: Array<String>?
        // 日期过滤（2026-10-12 v0.20.0 引入；2026-10-13 v0.21.1 重做）：
        // **绝不出现在 selection 里**。v0.20.0 曾把
        // `COALESCE(NULLIF(datetaken,0), date_added*1000) >= ? AND < ?` 拼进
        // selection，真机（Turbo 4）查询成功返回却 0 行（老板反馈
        // 「实际有照片却提示这一天没有照片」）—— 这台 ROM 的 MediaProvider
        // 对 selection 表达式/参数绑定的行为不可信，此前已连环证明：
        // sort 里的 LIMIT 被拒（09-29 Invalid token）、GROUP BY hack 被拒、
        // 列名严查。与 [queryGalleryDays]/[queryGalleryBuckets] 同一哲学：
        // **selection 只用裸列比较，过滤在内存做** —— 分页本就全量扫描，
        // 复杂度不变。口径不变：date_added 是**秒**要 ×1000；当天边界
        // [dayStartMs, dayEndMs) 由 Dart 按本地时区算好传下来。
        if (q) {
            sel = if (bucket != null) {
                "${MediaStore.Images.Media.BUCKET_DISPLAY_NAME} = ? AND is_pending = 0"
            } else {
                "is_pending = 0"
            }
            selArgs = if (bucket != null) arrayOf(bucket) else null
        } else {
            sel = if (bucket != null) "data LIKE ?" else null
            selArgs = if (bucket != null) arrayOf("%/$bucket/%") else null
        }

        val order = if (ascending) "ASC" else "DESC"
        // ⚠️⚠️⚠️ 第三击（2026-09-29 真机 "Invalid token LIMIT"）：这台 ROM 的
        // MediaProvider 解析器只认「列 + 方向」，排序子句里 **LIMIT/OFFSET 关键字
        // 都不放行**。所以排序子句不再带任何分页语法，分页改在 cursor 端做窗口：
        // 无 LIMIT 全量排序查询 + 跳过 offset 行、收满 limit 行即止（SQL OFFSET
        // 本来也是扫描到 offset 处才开始取，复杂度同级，真机几千张毫秒级）。
        // 排序列保留降级梯度：① 修正列 ② 裸 datetaken ③ 裸 date_added。
        val taken = MediaStore.Images.Media.DATE_TAKEN   // 底层列名 datetaken
        val added = MediaStore.Images.Media.DATE_ADDED   // 底层列名 date_added
        val sortLadder = listOf(
            "COALESCE($taken, $added * 1000) $order",   // ① 修正列：无拍摄时刻的退化到入库时刻
            "$taken $order",                            // ② 裸拍摄时刻列（个别 ROM 不认 COALESCE）
            "$added $order",                            // ③ 裸入库时刻列（最终兜底）
        )
        var lastError: Throwable? = null
        for (sort in sortLadder) {
            try {
                return queryGalleryImagesOnce(
                    projection.toTypedArray(), sel, selArgs, sort, q, limit, offset,
                    dayStartMs, dayEndMs,
                )
            } catch (t: Throwable) {
                Log.w(TAG, "gallery sort rejected, fallback next: $sort", t)
                lastError = t
            }
        }
        throw lastError ?: IllegalStateException("gallery query failed with no attempt")
    }

    private fun queryGalleryImagesOnce(
        projection: Array<String>,
        sel: String?,
        selArgs: Array<String>?,
        sort: String,
        q: Boolean,
        limit: Int,
        offset: Int,
        dayStartMs: Long?,
        dayEndMs: Long?,
    ): List<Map<String, Any?>> {
        val out = ArrayList<Map<String, Any?>>()
        // 计数器放 use 闭包外 —— 排障日志在闭包之后也要读它们。
        var skipped = 0
        var scanned = 0
        var firstTaken = -1L
        var firstAdded = -1L
        context.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            projection, sel, selArgs, sort,
        )?.use { c ->
            val idCol = c.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
            val nameCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DISPLAY_NAME)
            val takenCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_TAKEN)
            val addedCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_ADDED)
            val sizeCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.SIZE)
            val mimeCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.MIME_TYPE)
            val bucketCol = if (q) {
                c.getColumnIndexOrThrow(MediaStore.Images.Media.BUCKET_DISPLAY_NAME)
            } else {
                -1
            }
            val dataCol = if (q) {
                -1
            } else {
                @Suppress("DEPRECATION")
                c.getColumnIndexOrThrow(MediaStore.Images.Media.DATA)
            }
            // cursor 端窗口分页 + **内存日期过滤**：先按天筛（被筛掉的行不
            // 占 offset 配额 —— offset 语义是「过滤后集合内的第 offset 行」，
            // 与 Dart 侧按过滤结果分页的口径一致），再跳过 offset 行、
            // 收满 limit 行即止。归一化：datetaken>0 优先，否则 date_added×1000。
            while (c.moveToNext()) {
                val taken = c.getLong(takenCol)
                val added = c.getLong(addedCol) * 1000L
                if (scanned == 0) {
                    firstTaken = taken
                    firstAdded = added
                }
                scanned++
                if (dayStartMs != null && dayEndMs != null) {
                    val ms = if (taken > 0) taken else added
                    if (ms < dayStartMs || ms >= dayEndMs) continue
                }
                if (skipped < offset) {
                    skipped++
                    continue
                }
                val bucketName = if (q) {
                    c.getString(bucketCol) ?: ""
                } else {
                    File(c.getString(dataCol)).parentFile?.name ?: ""
                }
                out.add(
                    mapOf(
                        "id" to c.getLong(idCol),
                        "displayName" to (c.getString(nameCol) ?: ""),
                        "dateTakenMs" to if (taken > 0) taken else added,
                        "sizeBytes" to c.getLong(sizeCol),
                        "mimeType" to (c.getString(mimeCol) ?: "image/jpeg"),
                        "bucket" to bucketName,
                    ),
                )
                if (out.size >= limit) break
            }
        }
        // 排障锚点（2026-10-13）：日期过滤 0 行但扫描到数据时，把当天范围
        // 与首个样本的**原始**时间列值打进日志 —— 单位/口径异常一眼定位，
        // 不再靠猜（本次 v0.20.0 事故若有这行，logcat 一眼见分晓）。
        if (dayStartMs != null && dayEndMs != null && scanned > 0 && out.isEmpty()) {
            Log.w(
                TAG,
                "day filter empty: range=[$dayStartMs,$dayEndMs) scanned=$scanned " +
                    "sample(taken=$firstTaken,added=$firstAdded)",
            )
        }
        return out
    }

    /**
     * 有照片的日期清单（本地天序号，倒序）。
     *
     * **不用 SELECT DISTINCT**：ContentResolver 的 projection/sortOrder 会被
     * 拼进媒体库 SQL，新 MediaProvider 会校验列名合法性（2026-10-08
     * `_display_name` 同款事故面），表达式列随时可能被拒。改用内存归日
     * 去重 —— 只查两列时间，几千行毫秒级，与 [queryGalleryBuckets] 的
     * 内存计数同一哲学：宁可多拉一点，不做 ROM 兼容性赌博。
     *
     * 归日公式：`(归一化毫秒 + 本地时区偏移) / 86400000` 取整 —— 与 Dart
     * 侧 `dayIndexOf(DateTime)` 严格一致（见 native_gallery_service.dart）。
     */
    private fun queryGalleryDays(tzOffsetMs: Long, bucket: String?): List<Long> {
        val q = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
        val taken = MediaStore.Images.Media.DATE_TAKEN
        val added = MediaStore.Images.Media.DATE_ADDED
        val sel: String?
        val selArgs: Array<String>?
        if (q) {
            sel = if (bucket != null) {
                "${MediaStore.Images.Media.BUCKET_DISPLAY_NAME} = ? AND is_pending = 0"
            } else {
                "is_pending = 0"
            }
            selArgs = if (bucket != null) arrayOf(bucket) else null
        } else {
            sel = if (bucket != null) "data LIKE ?" else null
            selArgs = if (bucket != null) arrayOf("%/$bucket/%") else null
        }
        val projection = arrayOf(taken, added)
        val days = sortedSetOf<Long>(compareByDescending { it })
        context.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            projection, sel, selArgs, null,
        )?.use { c ->
            val takenCol = c.getColumnIndexOrThrow(taken)
            val addedCol = c.getColumnIndexOrThrow(added)
            while (c.moveToNext()) {
                val t = c.getLong(takenCol)
                val ms = if (t > 0) t else c.getLong(addedCol) * 1000L
                if (ms <= 0) continue
                days.add((ms + tzOffsetMs) / 86_400_000L)
            }
        }
        // 排障锚点（2026-10-14 v0.21.3）：日期清单与照片列表必须同口径
        // （同一个 bucket）。这行让 logcat 一眼确认清单当时按哪个相册算、
        // 算出多少天 —— 「日历说这天有/没有照片」的争议不再靠猜。
        Log.i(TAG, "gallery days: bucket=$bucket days=${days.size}")
        return days.take(2000)
    }

    /**
     * 相册分桶清单（顶部「只看某相册」下拉用）。
     *
     * **不用**「sortOrder 里塞 GROUP BY」的老 hack：ContentResolver 会把它拼成
     * `ORDER BY bucket GROUP BY bucket ...` —— 非法 SQL，AOSP 上靠 SQLite 的
     * 容错侥幸能跑，不少 ROM 直接抛 SQLiteException，选择器整个空掉
     * （2026-09-29 真机空态的头号嫌疑）。改成查询单列 + 内存计数：
     * 几千行也只有毫秒级，且所有版本行为一致。
     */
    private fun queryGalleryBuckets(): List<Map<String, Any?>> {
        val q = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
        val projection: Array<String> = if (q) {
            arrayOf(MediaStore.Images.Media.BUCKET_DISPLAY_NAME)
        } else {
            @Suppress("DEPRECATION")
            arrayOf(MediaStore.Images.Media.DATA)
        }
        val sel = if (q) "is_pending = 0" else null
        val counts = LinkedHashMap<String, Long>()
        context.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            projection, sel, null, null,
        )?.use { c ->
            while (c.moveToNext()) {
                val raw = c.getString(0) ?: continue
                val b = if (q) raw else File(raw).parentFile?.name ?: continue
                if (b.isEmpty()) continue
                counts[b] = (counts[b] ?: 0L) + 1L
            }
        }
        return counts.entries
            .sortedByDescending { it.value }
            .map { mapOf("bucket" to it.key, "count" to it.value) }
    }

    /** 网格缩略图字节：Q+ 走系统缩略图缓存；低版本回退到解码降采样。 */
    private fun loadGalleryThumb(id: Long, px: Int): ByteArray {
        val uri = ContentUris.withAppendedId(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id,
        )
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val bmp = context.contentResolver.loadThumbnail(
                uri, android.util.Size(px, px), null,
            )
            val bos = ByteArrayOutputStream()
            bmp.compress(Bitmap.CompressFormat.JPEG, 80, bos)
            bmp.recycle()
            bos.toByteArray()
        } else {
            loadThumbnailFallback(uri, px)
        }
    }

    /** [loadGalleryThumb] 的 API<29 回退：读原始流 + inSampleSize 降采样，绝不传原图字节。 */
    private fun loadThumbnailFallback(uri: Uri, px: Int): ByteArray {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        context.contentResolver.openInputStream(uri)?.use { st ->
            BitmapFactory.decodeStream(st, null, bounds)
        }
        val w = bounds.outWidth.coerceAtLeast(1)
        val h = bounds.outHeight.coerceAtLeast(1)
        val scale = maxOf(w, h).toFloat() / px.toFloat()
        val inSample = scale.toInt().coerceAtLeast(1)
        val opts = BitmapFactory.Options().apply { inSampleSize = inSample }
        val bmp = context.contentResolver.openInputStream(uri)?.use { st ->
            BitmapFactory.decodeStream(st, null, opts)
        } ?: throw IllegalStateException("无法解码图片 id=$uri")
        val bos = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 80, bos)
        bmp.recycle()
        return bos.toByteArray()
    }

    /**
     * 逐张复制到临时目录；单张失败记 error 继续，不挡整批。
     *
     * ⚠️ 性能（2026-09-29 全 App 性能排查）：旧实现**每张图发两次
     * MediaStore 查询**（一次取文件名、一次取拍摄时刻）。选 100 张 =
     * 200 次跨进程 query，真机上就是好几秒的纯等待，而它们完全可以在
     * 复制前用一条 `IN (...)` 批量取回（分批 400 条避开 SQL 参数上限）。
     *
     * 临时目录位置也改了：优先 **外部私有 files 目录**（与 Dart 侧
     * [ProjectPaths] 的 filesRoot 同根）。同根意味着 Dart 侧可以用
     * `rename` 把临时副本**移动**进项目目录 —— 省掉第二遍全量复制
     * （选 100 张 × 5MB = 500MB 的额外磁盘写，那是导入慢的大头）。
     */
    private fun readGalleryImages(ids: List<Long>): List<Map<String, Any?>> {
        val dir = galleryTempDir()
        val meta = queryMetaBatch(ids)
        val out = ArrayList<Map<String, Any?>>()
        for (id in ids) {
            try {
                val uri = ContentUris.withAppendedId(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id,
                )
                val m = meta[id]
                val name = m?.first ?: "gallery_$id.jpg"
                val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), "_")
                val dst = File(dir, "${id}_$safe")
                val input = context.contentResolver.openInputStream(uri)
                    ?: throw IllegalStateException("无法打开图片流 id=$id")
                input.use { ins ->
                    FileOutputStream(dst).use { outs -> ins.copyTo(outs, BUFFER_SIZE) }
                }
                out.add(
                    mapOf(
                        "id" to id,
                        "tempPath" to dst.absolutePath,
                        "displayName" to name,
                        "sizeBytes" to dst.length(),
                        "dateTakenMs" to (m?.second ?: 0L),
                    ),
                )
            } catch (t: Throwable) {
                Log.e(TAG, "read gallery image failed id=$id", t)
                out.add(mapOf("id" to id, "error" to (t.message ?: t.javaClass.simpleName)))
            }
        }
        return out
    }

    /** 临时副本目录：优先外部私有 files（与 Dart 项目目录同根 → 可 rename 移动）。 */
    private fun galleryTempDir(): File {
        val base = context.getExternalFilesDir(null) ?: context.cacheDir
        val dir = File(base, GALLERY_TEMP_DIR)
        if (!dir.exists() && !dir.mkdirs()) {
            throw IllegalStateException("无法创建临时目录")
        }
        return dir
    }

    /**
     * 一次性取回一批 id 的 (displayName, dateTakenMs)。
     *
     * 分批 400：SQLite 的 `IN` 参数上限是 999，留足余量；个别 ROM 的
     * MediaProvider 对超长 IN 也会退化，分批更稳。
     */
    private fun queryMetaBatch(ids: List<Long>): Map<Long, Pair<String?, Long>> {
        val out = HashMap<Long, Pair<String?, Long>>(ids.size * 2)
        val chunk = 400
        for (from in ids.indices step chunk) {
            val part = ids.subList(from, (from + chunk).coerceAtMost(ids.size))
            val placeholders = part.joinToString(",") { "?" }
            val args = part.map { it.toString() }.toTypedArray()
            try {
                context.contentResolver.query(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                    arrayOf(
                        MediaStore.Images.Media._ID,
                        MediaStore.Images.Media.DISPLAY_NAME,
                        MediaStore.Images.Media.DATE_TAKEN,
                        MediaStore.Images.Media.DATE_ADDED,
                    ),
                    "${MediaStore.Images.Media._ID} IN ($placeholders)",
                    args,
                    null,
                )?.use { c ->
                    val idCol = c.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
                    val nameCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DISPLAY_NAME)
                    val takenCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_TAKEN)
                    val addedCol = c.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_ADDED)
                    while (c.moveToNext()) {
                        val taken = c.getLong(takenCol)
                        val ms = if (taken > 0) taken else c.getLong(addedCol) * 1000L
                        out[c.getLong(idCol)] = Pair(c.getString(nameCol), ms)
                    }
                }
            } catch (t: Throwable) {
                // 批量查询失败不能挡住导入：退化到逐张查（慢，但能跑完）。
                Log.w(TAG, "meta batch query failed, fallback per-id", t)
                for (id in part) {
                    out[id] = Pair(queryDisplayName(id), queryDateTakenMs(id))
                }
            }
        }
        return out
    }

    /** 单张的真实拍摄时刻（DATE_TAKEN 优先，缺失退化 DATE_ADDED*1000）。 */
    private fun queryDateTakenMs(id: Long): Long {
        context.contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            arrayOf(
                MediaStore.Images.Media.DATE_TAKEN,
                MediaStore.Images.Media.DATE_ADDED,
            ),
            "${MediaStore.Images.Media._ID} = ?",
            arrayOf("$id"),
            null,
        )?.use { c ->
            if (c.moveToFirst()) {
                val taken = c.getLong(0)
                val added = c.getLong(1) * 1000L
                return if (taken > 0) taken else added
            }
        }
        return 0L
    }

    private fun postResult(result: MethodChannel.Result, block: () -> Any?) {
        mainHandler.post { result.success(block()) }
    }

    private fun postError(result: MethodChannel.Result, code: String, msg: String) {
        mainHandler.post { result.error(code, msg, null) }
    }

    private companion object {
        const val TAG = "GalleryBridge"
        const val BUFFER_SIZE = 128 * 1024
        const val ROOT_ALBUM = "集刻-采集"
        const val ROOT_RELATIVE = "Pictures/$ROOT_ALBUM"

        // 微信导入（M5.1）
        const val WECHAT_PACKAGE = "com.tencent.mm"
        const val WECHAT_TEMP_DIR = "wechat_import"
        const val WECHAT_QUERY_LIMIT = 500

        // 相册选择器（2026-09-29）临时副本目录
        const val GALLERY_TEMP_DIR = "gallery_import"

        val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
    }
}
