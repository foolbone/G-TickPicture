package com.gtick.g_tick_picture.camera

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import androidx.core.content.FileProvider
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.RandomAccessFile
import java.util.UUID

/**
 * 系统相机桥 v2（2026-10-22，feat/system-camera-v2 全量重写）。
 *
 * ── 为什么重写 ─────────────────────────────────────────────
 * v0.24.12~16 的「返回即回 App + native→Dart 反向推送」架构在真机上
 * 连续翻车（推送线程断言、时序竞态、会话状态泄漏），10-22 真机验收
 * 「一张图都收不到」。本版回归**同步契约 + 拉模式**：
 *
 *   ① `launchSession` 在相机返回后**同步收一批**（有界快窗 ≤2s，只交
 *      完整照片）并随结果返回 —— 不再有反向推送，不再有 Dart 侧会话
 *      状态机，不存在「推送丢了/时序竞态」这一整类问题；
 *   ② 晚到/写了一半的照片由 **Dart 主动轮询** `collectLate` 拉取
 *      （拉模式没有竞态：谁调用谁拿到）；轮询节奏与收口判据全在
 *      Dart（可单测）；
 *   ③ 每场会话一个原生内存上下文（基线/起点/目录/已交付表），
 *      Dart 调 `endCollect` 或上下文超时后释放 —— 无全局可泄漏状态。
 *
 * 保留的已验证底座：单张降级路径（EXTRA_OUTPUT）、媒体库基线增量、
 * 文件系统目录扫描、JPEG 完整性（EOI）、目录取材三层、进程被杀恢复
 * （syscam_pending + recoverSession 全量口径）。
 *
 * 权限：拉起系统相机**不需要** CAMERA 权限；读媒体库需要
 * READ_MEDIA_IMAGES（Dart 侧确认，没有则退回单张模式）。
 *
 * 线程约定：MethodChannel 进出都在主线程；耗时的媒体库/文件系统扫描
 * 一律后台线程，`MethodChannel.Result` 的完成回主线程。
 */
class SystemCameraBridge(
    private val activity: Activity,
    private val messenger: BinaryMessenger,
) {

    // ── 单张往返（v0.22.0，原样保留）──────────────────────────

    private var pendingResult: MethodChannel.Result? = null
    private var pendingPath: String? = null

    /** 会话模式（v0.24.2）的 MediaStore 基线：启动时已有的最大图片 _id。 */
    private var pendingBaseline = -1L

    /** 会话开始的墙钟时间（文件系统兜底的判据）。 */
    private var pendingSessionStartMs = 0L

    /** 会话开始时相机在用的目录集合（文件系统兜底）。 */
    private var pendingDirs: Set<String> = emptySet()

    /** 本场会话身份（collectLate / 恢复共用）。 */
    private var pendingSessionId: String = ""

    /** 是否正等系统相机回来（防双启）。 */
    val isPending: Boolean get() = pendingResult != null

    /**
     * 最近一次收图的诊断摘要。随结果回传 Dart 存本地，「关于」面板
     * 直接看 —— 现场排障不抓 logcat。
     */
    private var lastDiag: String = ""

    /**
     * 拉起系统相机拍**一张**（EXTRA_OUTPUT → FileProvider 临时文件）。
     */
    fun launch(path: String, result: MethodChannel.Result) {
        if (pendingResult != null) {
            result.error("ALREADY_RUNNING", "system camera is already running", null)
            return
        }
        val file = File(path)
        val uri: Uri = try {
            FileProvider.getUriForFile(
                activity,
                "${activity.packageName}.fileprovider",
                file,
            )
        } catch (e: IllegalArgumentException) {
            result.error("BAD_PATH", "temp file not under provider paths: $path", null)
            return
        }
        val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
            putExtra(MediaStore.EXTRA_OUTPUT, uri)
            addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        }
        pendingResult = result
        pendingPath = path
        try {
            activity.startActivityForResult(intent, REQUEST_CODE)
        } catch (e: ActivityNotFoundException) {
            pendingResult = null
            pendingPath = null
            result.error("NO_CAMERA_APP", "no app can handle camera intent", null)
        }
    }

    // ── 连拍会话 v2（同步首批 + 拉模式晚到）──────────────────

    /**
     * 一场会话的原生上下文：收图三要素 + 「已交付表」（路径 → 交付时
     * 大小）。`collectLate` 拿它做差集：新出现的路径当新照片，大小变了
     * 的当修复（changed=true）。
     */
    private class CollectCtx(
        val baseline: Long,
        val startMs: Long,
        val dirs: Set<String>,
        val delivered: LinkedHashMap<String, Long>,
        val createdAt: Long = System.currentTimeMillis(),
    ) {
        /**
         * EOI 未过的观察名单（路径 → 上次大小）。部分相机在 EOI 后追加
         * 私有数据段，EOI 校验永久失败 —— 不再一票否决，而是挂在这里
         * 观察：大小稳定（与上一轮一致）即视为写完，照常交付。交早了
         * 有 changed=true 修复重拷兑底（2026-10-22：恢复时 2 张被 EOI
         * 吞掉的真机事故）。
         */
        val suspects = HashMap<String, Long>()
    }

    /** 会话上下文表。上限 [MAX_CTXS]，超限丢最老的（Dart 侧 30s 就停轮询）。 */
    private val collectCtxs = LinkedHashMap<String, CollectCtx>()

    /** 连拍会话（v0.24.2 起；v2 同步契约）。
     *
     * `INTENT_ACTION_STILL_IMAGE_CAMERA` 拉起系统相机普通模式，想拍多少
     * 拍多少，按返回回 App。返回前**同步收一批**（媒体库快查 + 文件系统
     * 一轮扫描，只交完整照片，有界 ≤2s），随结果带回：
     *   · `shots`：首批照片（可能为空 —— 空不等于没拍，`likely` 说明）；
     *   · `likely`：原生判定「大概率拍了」（停留 ≥2.5s / 媒体库有新图），
     *     空首批 + likely=true 时 Dart 继续轮询 collectLate，最后仍空才
     *     报「没收到照片」；
     *   · `sessionId`：本场身份（collectLate / 恢复共用）；
     *   · `diag`：收图诊断摘要（「关于」面板展示）。
     */
    fun launchSession(result: MethodChannel.Result) {
        if (pendingResult != null) {
            result.error("ALREADY_RUNNING", "system camera is already running", null)
            return
        }
        // 准备工作全程后台线程（v0.24.10 教训：主线程扫媒体库会 ANR）。
        Thread {
            val baseline = queryMaxImageId()
            if (baseline < 0) {
                activity.runOnUiThread {
                    result.error("MEDIA_QUERY_FAILED", "cannot read MediaStore images", null)
                }
                return@Thread
            }
            val startMs = System.currentTimeMillis()
            val sessionId = UUID.randomUUID().toString()
            val dirs = collectCameraDirs()
            activity.runOnUiThread {
                // 竞态防御：后台准备期间用户又点了一次 —— 拒绝后者。
                if (pendingResult != null) {
                    result.error("ALREADY_RUNNING", "system camera is already running", null)
                    return@runOnUiThread
                }
                pendingResult = result
                pendingBaseline = baseline
                pendingSessionStartMs = startMs
                pendingDirs = dirs
                pendingSessionId = sessionId
                val intent = Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA)
                try {
                    activity.startActivityForResult(intent, REQUEST_SESSION_CODE)
                    // 收图三要素立即落盘（v0.24.9）：拍照期间进程被杀，
                    // 重启后 recoverSession 按这份上下文补收。
                    savePendingSession(baseline, startMs, dirs, sessionId)
                } catch (e: ActivityNotFoundException) {
                    pendingResult = null
                    pendingBaseline = -1L
                    pendingSessionId = ""
                    result.error("NO_CAMERA_APP", "no app can handle still image camera intent", null)
                }
            }
        }.start()
    }

    /**
     * 相机返回后的**首批同步收图**（v2）。
     *
     * 只做一轮「媒体库快查 + 文件系统单扫」，只交完整照片（EOI 校验），
     * 有界 ≤2s：空的且大概率拍了，再给 3×400ms 的短等（最后一张常在
     * 返回瞬间还在写）。**不做**完整稳定窗口 —— 那正是 v0.24.16 之前
     * 「返回后等 15s 才见照片」的根源；没赶上的照片由 collectLate 轮询
     * 补齐，EOI 校验保证不会收半成品。
     */
    private fun collectFirstBatch(
        baselineId: Long,
        startMs: Long,
        dirs: Set<String>,
    ): Pair<List<Map<String, Any?>>, Boolean> {
        val diag = mutableListOf<String>()
        var store = queryImagesAfter(baselineId)
        if (store.isEmpty()) {
            for (delayMs in EMPTY_POLL_MS) {
                if (!sleepOrGiveUp(delayMs)) break
                store = queryImagesAfter(baselineId)
                if (store.isNotEmpty()) break
            }
        }
        val dwellMs = System.currentTimeMillis() - startMs
        val likelyShot = store.isNotEmpty() || dwellMs >= SHOOT_DWELL_MS
        diag.add("停留 ${dwellMs}ms")

        var merged = collectOnce(baselineId, startMs, dirs, store, diag)
        if (merged.isEmpty() && likelyShot) {
            // 大概率拍了但一张都没扫到：短等三轮（最后一张写盘/索引中）。
            for (i in 0 until 3) {
                if (!sleepOrGiveUp(FS_POLL_MS)) break
                store = queryImagesAfter(baselineId)
                merged = collectOnce(baselineId, startMs, dirs, store, diag)
                if (merged.isNotEmpty()) break
            }
        }
        lastDiag = "首批 ${merged.size} 张；媒体库快照 ${store.size}；${diag.joinToString("；")}"
        Log.i(TAG, "session first batch: ${merged.size} shot(s), likely=$likelyShot")
        return Pair(merged, likelyShot)
    }

    /** 一轮收图：媒体库 + 文件系统合并，只交完整照片。 */
    private fun collectOnce(
        baselineId: Long,
        startMs: Long,
        dirs: Set<String>,
        storeShots: List<Map<String, Any?>>,
        diag: MutableList<String>,
    ): List<Map<String, Any?>> {
        val fsHits = scanCandidates(startMs, dirs).filter {
            it.size > 0L && isCompleteImage(File(it.path))
        }
        // 媒体库来源**不做 EOI 一票否决**（2026-10-22 真机事故）：
        // IS_PENDING=0（API 29+）本身就是系统给的「已写完」信号；且部分
        // 相机在 EOI 后追加私有数据段（三星 SEF 尾巴可跟几 KB），末 16
        // 字节找 EOI 会**永久性失败** —— 真机实拍 1 张被连续 4 轮否决，
        // 一张都收不到。交早了也有 changed=true 修复重拷兜底，宽容是安全的。
        var eoiSkipped = 0
        val usableStore = storeShots.filter { s ->
            val p = s["path"] as? String ?: return@filter false
            val size = (s["size"] as? Long) ?: -1L
            if (size <= 0L) return@filter false
            if (!isCompleteImage(File(p))) {
                // EOI 没过但媒体库已提交 —— 照收，诊断里记一笔。
                eoiSkipped++
            }
            true
        }
        if (eoiSkipped > 0) diag.add("含 $eoiSkipped 张 EOI 未过（按媒体库已提交口径收）")
        val fsShots = fsHits.map {
            mapOf("path" to it.path, "dateTakenMs" to it.mtime)
        }
        diag.add("媒体库 ${usableStore.size}/${storeShots.size}/fs ${fsShots.size}")
        return mergeShots(usableStore, fsShots)
    }

    /**
     * Dart 轮询拉取晚到照片（v2）。
     *
     * 每次调用做一轮「文件系统扫描 + 媒体库补时刻」，与已交付表做差集：
     * 新路径 → `changed=false`；大小变了 → `changed=true`（Dart 走修复，
     * 重拷覆盖）。**无推送、无竞态**：谁调用谁拿到。收口判据（连续空轮 +
     * 最短时长）在 Dart 侧；上下文超时（[CTX_MAX_AGE_MS]）或 Dart 调
     * `endCollect` 后释放。
     */
    fun collectLate(sessionId: String, result: MethodChannel.Result) {
        val ctx = synchronized(collectCtxs) { collectCtxs[sessionId] }
        if (ctx == null) {
            result.success(mapOf(
                "shots" to emptyList<Map<String, Any?>>(),
                "done" to true,
            ))
            return
        }
        Thread {
            try {
                // 媒体库增量也参与差集（2026-10-22 修复：v2 首版只看
                // fs 扫描 —— 相机写到没扫到的目录时晚到轮询永远收不到）。
                val storeRows = queryImagesAfter(ctx.baseline)
                val hits = scanCandidates(ctx.startMs, ctx.dirs).filter {
                    it.size > 0L && isCompleteImage(File(it.path))
                }
                val out = mutableListOf<Map<String, Any?>>()
                synchronized(ctx) {
                    for (s in storeRows) {
                        val p = s["path"] as? String ?: continue
                        val sz = s["size"] as? Long ?: -1L
                        if (sz <= 0L) continue
                        val prev = ctx.delivered[p]
                        if (prev == null) {
                            ctx.delivered[p] = sz
                            out.add(mapOf(
                                "path" to p,
                                "dateTakenMs" to s["dateTakenMs"],
                                "changed" to false,
                            ))
                        } else if (prev != sz) {
                            ctx.delivered[p] = sz
                            out.add(mapOf(
                                "path" to p,
                                "dateTakenMs" to s["dateTakenMs"],
                                "changed" to true,
                            ))
                        }
                    }
                    for (h in hits) {
                        val prev = ctx.delivered[h.path]
                        if (prev == null) {
                            if (isCompleteImage(File(h.path))) {
                                ctx.delivered[h.path] = h.size
                                out.add(mapOf(
                                    "path" to h.path,
                                    "dateTakenMs" to h.mtime,
                                    "changed" to false,
                                ))
                            } else {
                                // EOI 未过（相机尾巴）：挂观察，大小稳定
                                // （与上一轮一致）才交 —— 不再永久否决。
                                val last = ctx.suspects[h.path]
                                if (last != null && last == h.size) {
                                    ctx.delivered[h.path] = h.size
                                    ctx.suspects.remove(h.path)
                                    out.add(mapOf(
                                        "path" to h.path,
                                        "dateTakenMs" to h.mtime,
                                        "changed" to false,
                                    ))
                                } else {
                                    ctx.suspects[h.path] = h.size
                                }
                            }
                        } else if (prev != h.size) {
                            ctx.delivered[h.path] = h.size
                            out.add(mapOf(
                                "path" to h.path,
                                "dateTakenMs" to h.mtime,
                                "changed" to true,
                            ))
                            // 修复后 EOI 仍未过 → 继续观察（尾巴可能还在长）。
                            if (!isCompleteImage(File(h.path))) {
                                ctx.suspects[h.path] = h.size
                            } else {
                                ctx.suspects.remove(h.path)
                            }
                        }
                    }
                }
                val stale = System.currentTimeMillis() - ctx.createdAt > CTX_MAX_AGE_MS
                if (stale) {
                    synchronized(collectCtxs) { collectCtxs.remove(sessionId) }
                }
                activity.runOnUiThread {
                    result.success(mapOf("shots" to out, "done" to stale))
                }
            } catch (e: Exception) {
                Log.w(TAG, "collectLate failed: ${e.message}")
                activity.runOnUiThread {
                    result.success(mapOf(
                        "shots" to emptyList<Map<String, Any?>>(),
                        "done" to false,
                    ))
                }
            }
        }.start()
    }

    /** Dart 侧轮询结束，释放会话上下文。 */
    fun endCollect(sessionId: String, result: MethodChannel.Result) {
        synchronized(collectCtxs) { collectCtxs.remove(sessionId) }
        result.success(null)
    }

    // ── 会话上下文持久化（v0.24.9，原样保留）──────────────────
    //
    // 收图三要素（基线/起点/目录）+ sessionId 写进本 App 自己的
    // SharedPreferences（与 Dart 的 shared_preferences 不是同一份文件）。
    // 进程被杀重启后 recoverSession 按它补收。

    private fun savePendingSession(
        baseline: Long,
        startMs: Long,
        dirs: Set<String>,
        sessionId: String,
    ) {
        try {
            activity.getSharedPreferences(PENDING_SP, Context.MODE_PRIVATE)
                .edit()
                .putLong("baseline", baseline)
                .putLong("startMs", startMs)
                .putString("dirs", dirs.joinToString("\u0001"))
                .putString("sessionId", sessionId)
                .putLong("at", System.currentTimeMillis())
                .apply()
        } catch (e: Exception) {
            Log.w(TAG, "save pending session failed: ${e.message}")
        }
    }

    private fun clearPendingSession() {
        try {
            activity.getSharedPreferences(PENDING_SP, Context.MODE_PRIVATE)
                .edit().clear().apply()
        } catch (e: Exception) {
            Log.w(TAG, "clear pending session failed: ${e.message}")
        }
    }

    private class PendingSessionContext(
        val baseline: Long,
        val startMs: Long,
        val dirs: Set<String>,
        val sessionId: String,
    )

    private fun readPendingSession(): PendingSessionContext? {
        return try {
            val sp = activity.getSharedPreferences(PENDING_SP, Context.MODE_PRIVATE)
            val baseline = sp.getLong("baseline", -1L)
            if (baseline < 0L) return null
            PendingSessionContext(
                baseline = baseline,
                startMs = sp.getLong("startMs", 0L),
                dirs = (sp.getString("dirs", "") ?: "")
                    .split('\u0001')
                    .filter { it.isNotBlank() }
                    .toSet(),
                sessionId = sp.getString("sessionId", "")
                    ?.takeIf { it.isNotBlank() }
                    ?: UUID.randomUUID().toString(),
            )
        } catch (e: Exception) {
            null
        }
    }

    /**
     * 进程被杀后的会话恢复（v0.24.9，原样保留——全量口径一轮收完）。
     *
     * 读得到 pending = 上次会话没收完。恢复 = 用持久化三要素把收图
     * 原样再跑一遍（带完整稳定窗口 —— 恢复发生在启动期，没人等首批）。
     * 读不到 → success(null)。
     */
    fun recoverSession(result: MethodChannel.Result) {
        val ctx = readPendingSession() ?: run {
            result.success(null)
            return
        }
        clearPendingSession()
        Thread {
            try {
                val store = queryImagesAfter(ctx.baseline)
                val diag = mutableListOf<String>()
                val fsHits = collectByFilesystem(
                    sessionStartMs = ctx.startMs,
                    dirs = ctx.dirs,
                    hasStoreEvidence = store.isNotEmpty(),
                    stableRounds = FS_FULL_STABLE_ROUNDS,
                    diag = diag,
                )
                val usableStore = store.filter { s ->
                    val size = (s["size"] as? Long) ?: -1L
                    if (size > 0L) return@filter true
                    val p = s["path"] as? String
                    p != null && File(p).length() > 0L
                }
                val fsShots = fsHits.map {
                    mapOf("path" to it.path, "dateTakenMs" to it.mtime)
                }
                val merged = mergeShots(usableStore, fsShots)
                val diagText = "恢复：媒体库 ${usableStore.size}/${store.size} / " +
                    "文件系统 ${fsShots.size} → ${merged.size} 张；${diag.joinToString("；")}"
                lastDiag = diagText
                // 注册轮询上下文（v0.24.19）：恢复只是一次快照 —— MediaStore
                // 可能还有没索引完的照片（真机实拍 7 张恢复只收到 5 张，
                // 另 2 张晚索引）。挂上 ctx 让 Dart 用 collectLate 继续拉。
                val delivered = LinkedHashMap<String, Long>()
                for (s in merged) {
                    val p = s["path"] as? String ?: continue
                    val len = try {
                        File(p).length()
                    } catch (e: Exception) {
                        -1L
                    }
                    delivered[p] = if (len > 0L) len else -1L
                }
                synchronized(collectCtxs) {
                    collectCtxs[ctx.sessionId] =
                        CollectCtx(ctx.baseline, ctx.startMs, ctx.dirs, delivered)
                    while (collectCtxs.size > MAX_CTXS) {
                        val oldest = collectCtxs.keys.first()
                        collectCtxs.remove(oldest)
                    }
                }
                activity.runOnUiThread {
                    result.success(mapOf(
                        "shots" to merged,
                        "diag" to diagText,
                        "sweeping" to false,
                        "sessionId" to ctx.sessionId,
                    ))
                }
            } catch (e: Exception) {
                Log.e(TAG, "recover collect failed: ${e.message}")
                activity.runOnUiThread {
                    result.success(mapOf(
                        "shots" to emptyList<Map<String, Any?>>(),
                        "diag" to "恢复收图异常：${e.message}",
                        "sweeping" to false,
                        "sessionId" to ctx.sessionId,
                    ))
                }
            }
        }.start()
    }

    // ── 相机目录取材（v0.24.11，原样保留）────────────────────

    /**
     * 会话开始时相机在用的**父目录**集合。三层取材：
     * ① 相册总量 < [FULL_SCAN_BELOW] 才全表扫；
     * ② 大相册只取最近 [RECENT_DIRS_LIMIT] 张的父目录；
     * ③ 历史目录并集（跨会话持久化，上限 [MAX_PERSISTED_DIRS] 条）
     *    + 各存储卷的 DCIM/Pictures 兜底。
     */
    private fun collectCameraDirs(): Set<String> {
        val dirs = linkedSetOf<String>()
        val total = queryImageCount()
        val recentOnly = total >= FULL_SCAN_BELOW
        try {
            val uri = MediaStore.Images.Media.EXTERNAL_CONTENT_URI
            val cursor = if (recentOnly) {
                activity.contentResolver.query(
                    uri,
                    arrayOf(MediaStore.Images.Media.DATA),
                    null,
                    null,
                    "${MediaStore.Images.Media._ID} DESC LIMIT $RECENT_DIRS_LIMIT",
                )
            } else {
                activity.contentResolver.query(
                    uri,
                    arrayOf(MediaStore.Images.Media.DATA),
                    null,
                    null,
                    null,
                )
            }
            cursor?.use { cur ->
                val iPath = cur.getColumnIndex(MediaStore.Images.Media.DATA)
                if (iPath >= 0) {
                    while (cur.moveToNext()) {
                        val p = cur.getString(iPath) ?: continue
                        val parent = File(p).parent ?: continue
                        dirs.add(parent)
                    }
                }
            }
        } catch (e: Exception) {
            // 查不到就用公共目录兜底（下面的 DCIM/Pictures）
        }
        dirs.addAll(readPersistedDirs())
        @Suppress("DEPRECATION")
        try {
            dirs.add(
                Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_DCIM
                ).absolutePath
            )
            dirs.add(
                Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_PICTURES
                ).absolutePath
            )
        } catch (e: Exception) {
            // 拿不到就算了，MediaStore 结果仍照常返回
        }
        // 相机存储可能在 SD 卡等非主卷：用本 App 的 media 目录反推卷根。
        try {
            for (mediaDir in activity.getExternalMediaDirs()) {
                val volRoot = mediaDir?.parentFile?.parentFile?.parentFile ?: continue
                dirs.add(File(volRoot, Environment.DIRECTORY_DCIM).absolutePath)
                dirs.add(File(volRoot, Environment.DIRECTORY_PICTURES).absolutePath)
            }
        } catch (e: Exception) {
            // 个别 ROM 不给 media 目录 —— 主卷兜底仍在
        }
        savePersistedDirs(dirs)
        Log.i(
            TAG,
            "session camera dirs(${dirs.size}): total=$total recentOnly=$recentOnly"
        )
        return dirs
    }

    /** 媒体库图片总量（-1 = 查不到，按小相册处理：全表扫）。 */
    private fun queryImageCount(): Int {
        return try {
            activity.contentResolver.query(
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                arrayOf(MediaStore.Images.Media._ID),
                null,
                null,
                null,
            )?.use { cur -> cur.count } ?: -1
        } catch (e: Exception) {
            -1
        }
    }

    private fun readPersistedDirs(): Set<String> {
        return try {
            val sp = activity.getSharedPreferences(DIRS_SP, Context.MODE_PRIVATE)
            (sp.getString("union", "") ?: "")
                .split('\u0001')
                .filter { it.isNotBlank() }
                .toSet()
        } catch (e: Exception) {
            emptySet()
        }
    }

    private fun savePersistedDirs(dirs: Set<String>) {
        try {
            val sp = activity.getSharedPreferences(DIRS_SP, Context.MODE_PRIVATE)
            val old = sp.getString("union", "") ?: ""
            val merged = linkedSetOf<String>()
            merged.addAll(dirs)
            merged.addAll(old.split('\u0001').filter { it.isNotBlank() })
            val capped = merged.take(MAX_PERSISTED_DIRS)
            sp.edit().putString("union", capped.joinToString("\u0001")).apply()
        } catch (e: Exception) {
            Log.w(TAG, "save persisted dirs failed: ${e.message}")
        }
    }

    // ── 扫描与完整性判据（历代教训沉淀，原样保留）────────────

    /** 一次目录扫描的候选（**含 size=0**：完整性判据需要它）。 */
    private class FsHit(val path: String, val mtime: Long, val size: Long)

    /**
     * 扫一遍相机目录，返回会话期间创建/改动的图片候选。
     * 两层：目录本身 + 它的直接子目录。目录名不猜 —— 用会话开始时
     * 从媒体库收集到的真实目录集合。
     */
    private fun scanCandidates(
        sessionStartMs: Long,
        dirs: Set<String>,
    ): List<FsHit> {
        val found = mutableListOf<FsHit>()
        val seen = mutableSetOf<String>()
        for (dir in dirs) {
            // 历史目录并集可能把截图/微信/下载目录带进来 —— 不扫。
            if (isIgnoredName(File(dir).name)) continue
            val children = try {
                File(dir).listFiles()
            } catch (e: Exception) {
                null
            } ?: continue
            for (f in children) {
                if (isIgnoredName(f.name)) continue
                val files: Sequence<File> = if (f.isDirectory) {
                    try {
                        f.listFiles()?.asSequence() ?: emptySequence()
                    } catch (e: Exception) {
                        emptySequence()
                    }
                } else {
                    sequenceOf(f)
                }
                for (file in files) {
                    if (isIgnoredName(file.name)) continue
                    if (!_looksLikeImage(file.name)) continue
                    val size = try {
                        if (!file.isFile) continue
                        file.length()
                    } catch (e: Exception) {
                        continue
                    }
                    val mtime = try {
                        file.lastModified()
                    } catch (e: Exception) {
                        continue
                    }
                    // 2 秒容差：部分机型在「会话开始」前一瞬就建好空文件。
                    if (mtime < sessionStartMs - 2000L) continue
                    if (!seen.add(file.absolutePath)) continue
                    found.add(FsHit(file.absolutePath, mtime, size))
                }
            }
        }
        found.sortBy { it.mtime }
        return found
    }

    /// 隐藏文件/目录 + 已知非相机目录（截图/微信/下载/缩略图缓存）。
    private fun isIgnoredName(name: String): Boolean {
        if (name.startsWith(".")) return true
        val lower = name.lowercase()
        if (lower.startsWith("screenshot")) return true
        return lower in NON_CAMERA_DIR_NAMES
    }

    private fun _looksLikeImage(name: String): Boolean {
        val dot = name.lastIndexOf('.')
        if (dot <= 0 || dot == name.length - 1) return false
        return when (name.substring(dot + 1).lowercase()) {
            "jpg", "jpeg", "png", "heic", "heif", "webp" -> true
            else -> false
        }
    }

    /**
     * 文件是否已经写完：JPEG 必须以 EOI（FF D9）结尾。尾窗 512 字节
     * （2026-10-22 从 16 扩大）：部分相机 EOI 后补零对齐 / 追加小段
     * XMP，16 字节窗会误杀。更大的私有尾巴（SEF 等）由「媒体库来源
     * 免 EOI」口径兜住（见 [collectOnce]）。HEIC/PNG/WebP 没有统一
     * 尾标，返回 true。读失败一律 false —— 宁可这轮不收。
     */
    private fun isCompleteImage(f: File): Boolean {
        val name = f.name.lowercase()
        if (!name.endsWith(".jpg") && !name.endsWith(".jpeg")) return true
        return try {
            val len = f.length()
            if (len < 4L) return false
            RandomAccessFile(f, "r").use { raf ->
                val tailLen = minOf(512L, len).toInt()
                val tail = ByteArray(tailLen)
                raf.seek(len - tailLen)
                raf.readFully(tail)
                for (i in 0 until tailLen - 1) {
                    val b1 = tail[i].toInt() and 0xFF
                    val b2 = tail[i + 1].toInt() and 0xFF
                    if (b1 == 0xFF && b2 == 0xD9) return true
                }
                false
            }
        } catch (e: Throwable) {
            false
        }
    }

    /** 启动前的 MediaStore 图片 max(_id)。表空回 0；查询失败回 -1。 */
    private fun queryMaxImageId(): Long {
        return try {
            var max = -1L
            activity.contentResolver.query(
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                arrayOf(MediaStore.Images.Media._ID),
                null,
                null,
                "${MediaStore.Images.Media._ID} DESC",
            )?.use { cur -> if (cur.moveToFirst()) max = cur.getLong(0) }
            max
        } catch (e: Exception) {
            // 权限被运行时收回 / 媒体库异常
            -1L
        }
    }

    /** 基线之后的媒体库新图（_id 升序；is_pending 过滤，API 29+）。 */
    private fun queryImagesAfter(baselineId: Long): List<Map<String, Any?>> {
        val out = mutableListOf<Map<String, Any?>>()
        val selection = if (Build.VERSION.SDK_INT >= 29) {
            "${MediaStore.Images.Media._ID} > ? AND " +
                "${MediaStore.MediaColumns.IS_PENDING} = 0"
        } else {
            "${MediaStore.Images.Media._ID} > ?"
        }
        try {
            activity.contentResolver.query(
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                arrayOf(
                    MediaStore.Images.Media._ID,
                    MediaStore.Images.Media.DATA,
                    MediaStore.Images.Media.DATE_TAKEN,
                    MediaStore.Images.Media.SIZE,
                ),
                selection,
                arrayOf(baselineId.toString()),
                "${MediaStore.Images.Media._ID} ASC",
            )?.use { cur ->
                val iPath = cur.getColumnIndexOrThrow(MediaStore.Images.Media.DATA)
                val iDate = cur.getColumnIndexOrThrow(MediaStore.Images.Media.DATE_TAKEN)
                val iSize = cur.getColumnIndexOrThrow(MediaStore.Images.Media.SIZE)
                while (cur.moveToNext()) {
                    val path = cur.getString(iPath)
                    if (path.isNullOrEmpty()) continue
                    val dateMs = if (cur.isNull(iDate)) null else cur.getLong(iDate)
                    val size = if (cur.isNull(iSize)) -1L else cur.getLong(iSize)
                    out.add(mapOf(
                        "path" to path,
                        "dateTakenMs" to dateMs,
                        "size" to size,
                    ))
                }
            }
        } catch (e: Exception) {
            // 查询失败 = 收不到图，返回已收到的部分
        }
        return out
    }

    /**
     * 文件系统轮询到「写完」（**恢复路径专用**）：文件集合与各文件大小
     * 连续 [stableRounds] 轮不变才算写完。正常路径不再用它（首批同步
     * + collectLate 轮询替代），恢复发生在启动期，稳一点更划算。
     */
    private fun collectByFilesystem(
        sessionStartMs: Long,
        dirs: Set<String>,
        hasStoreEvidence: Boolean,
        stableRounds: Int,
        diag: MutableList<String>,
    ): List<FsHit> {
        if (sessionStartMs <= 0L || dirs.isEmpty()) return emptyList()
        val emptyWait =
            if (hasStoreEvidence) FS_EMPTY_WAIT_WHILE_SHOOTING_MS else FS_EMPTY_WAIT_MS
        var lastSig = ""
        var stable = 0
        var waited = 0L
        var rounds = 0
        var hits: List<FsHit> = emptyList()
        // 上一轮各文件的大小：EOI 未过的候选靠「与上一轮大小一致」
        // 判写完（相机尾巴让 EOI 永久失败，不能一票否决 —— 2026-10-22）。
        var prevSizes: Map<String, Long> = emptyMap()
        while (waited <= FS_MAX_WAIT_MS) {
            rounds++
            hits = scanCandidates(sessionStartMs, dirs)
            val sig = hits.joinToString("|") { "${it.path}#${it.size}" }
            if (hits.isEmpty()) {
                if (waited >= emptyWait) break
                stable = 0
            } else if (sig == lastSig) {
                if (++stable >= stableRounds) break
            } else {
                stable = 0
            }
            lastSig = sig
            if (!sleepOrGiveUp(FS_POLL_MS)) break
            waited += FS_POLL_MS
            prevSizes = hits.associate { it.path to it.size }
        }
        val done = hits.filter { h ->
            if (h.size <= 0L) return@filter false
            if (isCompleteImage(File(h.path))) return@filter true
            prevSizes[h.path] == h.size
        }
        diag.add("文件系统 ${done.size} 张 / 扫 $rounds 轮 / 等 ${waited}ms")
        Log.i(TAG, "fs collect: ${done.size} file(s), rounds=$rounds waited=${waited}ms")
        return done
    }

    /**
     * 媒体库与文件系统结果按绝对路径合并：优先媒体库的 DATE_TAKEN
     * （真快门时刻），缺失用 fs 项的 mtime；按拍摄时刻升序 —— ingest
     * 的 seq 按这个顺序分配，交付「按时间」排序才对得上。
     */
    private fun mergeShots(
        store: List<Map<String, Any?>>,
        fs: List<Map<String, Any?>>,
    ): List<Map<String, Any?>> {
        val byPath = LinkedHashMap<String, Map<String, Any?>>()
        for (s in store) {
            val p = s["path"] as? String ?: continue
            byPath[p] = s
        }
        for (f in fs) {
            val p = f["path"] as? String ?: continue
            val prev = byPath[p]
            if (prev == null) {
                byPath[p] = f
            } else {
                val prevDate = prev["dateTakenMs"] as? Long ?: 0L
                val fsDate = f["dateTakenMs"] as? Long ?: 0L
                if (prevDate <= 0L && fsDate > 0L) {
                    byPath[p] = mapOf("path" to p, "dateTakenMs" to fsDate)
                }
            }
        }
        return byPath.values.sortedBy { (it["dateTakenMs"] as? Long) ?: 0L }
    }

    /** 睡一觉再查；线程被中断（进程回收）时返回 false 让调用方收工。 */
    private fun sleepOrGiveUp(delayMs: Long): Boolean = try {
        Thread.sleep(delayMs)
        true
    } catch (e: InterruptedException) {
        false
    }

    /**
     * MainActivity.onActivityResult 转发。
     *
     * 单张路径：RESULT_OK 与否都交回 path，由 Dart 校验文件真落盘了没
     * （个别 ROM 返回 OK 却不写 EXTRA_OUTPUT）。
     * 会话路径（v2）：相机返回后**同步收首批**（后台线程、有界 ≤2s），
     * 收完才 result.success —— 首批随结果返回，没有反向推送。
     */
    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQUEST_CODE) {
            val result = pendingResult ?: return
            val path = pendingPath
            pendingResult = null
            pendingPath = null
            result.success(
                mapOf(
                    "ok" to (resultCode == Activity.RESULT_OK),
                    "path" to path,
                )
            )
            return
        }
        if (requestCode == REQUEST_SESSION_CODE) {
            // resultCode 刻意不看：普通模式拉起的相机 App 返回值不承载
            // 语义（通常 CANCELED），收多少张只由媒体库增量 + 文件系统说了算。
            //
            // ⚠️ pendingResult 必须在这里清掉（2026-10-22 真机事故）：
            // 单张分支清了，会话分支漏了 —— 第一场拍照回来后
            // pendingResult 永远挂着，之后所有 launchSession/launch
            // 全部 ALREADY_RUNNING，拍照按钮「永远进不去」。
            val result = pendingResult ?: return
            pendingResult = null
            val baseline = pendingBaseline
            // ⚠️ 先捕获成局部变量再清字段（v0.24.6 真踩过：后台线程回头
            // 读字段拿到空值，文件系统兜底直接失效）。
            val sessionStartMs = pendingSessionStartMs
            val dirs = pendingDirs
            val sessionId = pendingSessionId
            pendingBaseline = -1L
            pendingSessionStartMs = 0L
            pendingDirs = emptySet()
            pendingSessionId = ""
            Thread {
                try {
                    val (shots, likely) = collectFirstBatch(baseline, sessionStartMs, dirs)
                    // 会话上下文：晚到轮询（collectLate）用；已交付表先记首批。
                    val delivered = LinkedHashMap<String, Long>()
                    for (s in shots) {
                        val p = s["path"] as? String ?: continue
                        val len = try {
                            File(p).length()
                        } catch (e: Exception) {
                            -1L
                        }
                        delivered[p] = if (len > 0L) len else -1L
                    }
                    synchronized(collectCtxs) {
                        collectCtxs[sessionId] =
                            CollectCtx(baseline, sessionStartMs, dirs, delivered)
                        // 上限保护：超限丢最老的（正常情况下 Dart 30s 内
                        // 就 endCollect，到不了这个数）。
                        while (collectCtxs.size > MAX_CTXS) {
                            val oldest = collectCtxs.keys.first()
                            collectCtxs.remove(oldest)
                        }
                    }
                    activity.runOnUiThread {
                        result.success(mapOf(
                            "shots" to shots,
                            "diag" to lastDiag,
                            "sessionId" to sessionId,
                            "likely" to likely,
                        ))
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "first batch collect failed: ${e.message}")
                    lastDiag = "首批收图异常：${e.message}"
                    activity.runOnUiThread {
                        result.success(mapOf(
                            "shots" to emptyList<Map<String, Any?>>(),
                            "diag" to lastDiag,
                            "sessionId" to sessionId,
                            "likely" to true,
                        ))
                    }
                }
            }.start()
        }
    }

    private companion object {
        /// 取个高位值，避开 Flutter 插件注册表的 requestCode 区间。
        const val REQUEST_CODE = 0x5C01

        /// 连拍会话。
        const val REQUEST_SESSION_CODE = 0x5C02

        /// 收图三要素的持久化文件名（本 App 自己的 SP，与 Dart 侧
        /// shared_preferences 不是同一份文件）。
        private const val PENDING_SP = "syscam_pending"

        /// 相机目录历史并集的持久化文件名。
        private const val DIRS_SP = "syscam_dirs"

        private val TAG = "SystemCamera"

        /// 首查为空时的短确认窗口（ms）：区分「真没拍」与「索引还没来」。
        private val EMPTY_POLL_MS = longArrayOf(400L, 500L)

        /// 文件系统扫描/恢复稳定窗口的轮询间隔（ms）。
        private const val FS_POLL_MS = 400L

        /// 恢复路径（完整口径）的稳定轮数。
        private const val FS_FULL_STABLE_ROUNDS = 3

        /// 一个候选都没有、且媒体库也没有新图时的收场等待（ms）。
        private const val FS_EMPTY_WAIT_MS = 2000L

        /// 媒体库空但停留够久（大概率拍了）时的空窗口（ms）。
        private const val FS_EMPTY_WAIT_WHILE_SHOOTING_MS = 8000L

        /// 恢复路径稳定窗口总上限（ms）。
        private const val FS_MAX_WAIT_MS = 15000L

        /// 在相机里停留超过这么久 = 「大概率拍了」（ms）。
        private const val SHOOT_DWELL_MS = 2500L

        /// 相册总量少于此值才全表扫目录。
        private const val FULL_SCAN_BELOW = 500

        /// 大相册取最近多少张的父目录作为相机落点候选。
        private const val RECENT_DIRS_LIMIT = 300

        /// 目录历史并集上限（条）。
        private const val MAX_PERSISTED_DIRS = 64

        /// 同时存活的会话上下文上限（正常 1~2 场，兜底防泄漏）。
        private const val MAX_CTXS = 4

        /// 会话上下文最长存活（ms）—— 超时后 collectLate 报 done。
        private const val CTX_MAX_AGE_MS = 120_000L

        /// 非相机目录（小写）：历史目录并集可能把它们带进来，扫描时跳过。
        private val NON_CAMERA_DIR_NAMES = setOf(
            "screenshots", "weixin", "whatsapp", "telegram", "download",
            "thumbnails", ".thumbnails", "instagram", "messenger", "facebook",
            "snapchat", "line", "kakaotalk", "viber", "imo", "edited",
            "lightroom", "snapseed", "picsart", "collage",
        )
    }
}
