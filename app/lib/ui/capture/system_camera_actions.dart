/// 系统相机拍照的编排 v2（2026-10-22，feat/system-camera-v2 全量重写）。
///
/// 与 `import_actions.dart` 同款分工：拉起系统相机、把结果翻译成结局
/// 在 UI 层；临时路径在服务层、ingest 在服务层
/// （[CaptureService.captureFromFile]）。
///
/// ── v2 同步契约（为什么推倒重来）────────────────────────────
/// v0.24.12~16 的「返回即回 App + native→Dart 反向推送」在真机上连续
/// 翻车，10-22 验收「一张图都收不到」。本版：
///
///   ① [runSystemCameraSession] 全程**同步**：launchSession 带回首批
///      （原生收完才回，有界 ≤2s）→ 入库（进度实时回调）→ 轮询
///      collectLate 拉晚到照片（拉模式无竞态）→ 实测对账 → 收口。
///      一场拍照 = 一个函数调用 = 一个批次，没有全局会话状态机、
///      没有跨页面广播流、没有可泄漏的收尾依赖；
///   ② 结局与张数全部来自**入库实测**（账本口径），提示只说真话；
///   ③ 保留已验证底座：账本幂等、批次收口（endSession + 5 分钟
///      resumable）、进程被杀恢复、单张降级。
library;

import 'dart:async';
import 'dart:io';

// visibleForTesting 由 material.dart 转出（foundation 显式 import 是冗余）。
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show PlatformException;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/async_limiter.dart';
import '../../core/logger.dart';
import '../../domain/capture/camera_capture_service.dart';
import '../../domain/capture/camera_preferences.dart';
import '../../domain/capture/capture_service.dart';
import '../../domain/capture/system_camera_service.dart';
import 'import_actions.dart' show requestGalleryPermission;

/// 一次系统相机拍照的结局。
enum SystemShotOutcome {
  /// 拍了并入库（id 有效）。
  shot,

  /// 用户在系统相机里返回/取消 —— **静默收场**：不建批次、不计错、
  /// 不提示（用户反悔不是错误，弹提示才是打扰）。
  cancelled,

  /// 系统相机返回 OK 但没给原图（个别 ROM 不尊重 EXTRA_OUTPUT）。
  noImage,

  /// 原生判定「大概率拍了」（在相机里停留够久）但一张都没收到 ——
  /// **必须明说**并指补收路径（静默零会让用户以为照片进了 App，
  /// 10-22 真机反馈）。
  missed,

  /// 启动失败（没有相机 App / 重复启动 / 其他异常）。
  failed,
}

/// 进程级「已启动未回收」状态（方案 D7）。
///
/// App 在系统相机前台时被系统杀掉，Dart 侧调用链随之消失，但临时文件
/// 还在磁盘上。重进采集页时靠这里判断有没有一张「拍了没入库」的。
class SystemCameraLaunch {
  SystemCameraLaunch._();

  static String? pendingPath;
  static DateTime? launchedAt;

  static bool get hasPending => pendingPath != null;

  static void clear() {
    pendingPath = null;
    launchedAt = null;
  }
}

/// 当前相机模式。读失败按系统相机兜底（升级后的默认路径）。
Future<CameraCaptureMode> _resolveCaptureMode(WidgetRef ref) async {
  try {
    return await ref.read(cameraPreferencesProvider).captureMode();
  } catch (_) {
    return CameraCaptureMode.system;
  }
}

// ─────────────────────────────────────────────────────────────
// 会话入库（首批 + 晚到轮询共用）
// ─────────────────────────────────────────────────────────────

/// 一场拍照的入库账（v2）。
///
/// 生命周期 = 一次 [runSystemCameraSession] 调用（局部变量，无全局状态、
/// 无泄漏）。`ingested` 是「原图路径 → 照片 id」的真源：UI 的张数与
/// 少片对账只认它，绝不拿「收到几批」冒充「入库几张」。
class _SessionAccount {
  _SessionAccount(this.projectId, {this.groupId});

  final String projectId;

  /// 组内补拍目标组（非空 = 收完挂回这个组）。
  final String? groupId;

  /// 这场会话在 DB 里的 capture_session id（首批 startSession 后填）。
  String? captureSessionId;

  /// 原图路径 → 照片 id（唯一路径去重）。
  final Map<String, String> ingested = {};

  /// 入库失败的唯一原图路径（复制失败 / 磁盘满 / DB 写失败）。
  final Set<String> failed = {};
}

/// 把一批照片 ingest 进项目（首批与晚到轮询共用）。
///
///  · 前置 [CaptureService.startSession]（命中 open / resumable 批次，
///    「一批一组」的根基）；批次 id 记进 [account]。
///  · 并发上限 3（大图复制是主要耗时）；ids 按 shots 顺序回填。
///  · `changed=true` 的项走修复（重拷覆盖 + 重算派生），不重复插行。
///  · 单张失败不断链：记进 [account.failed]，收尾对账说真话。
///  · 组内补拍：收完统一挂目标组。
Future<List<String>> _ingestShots({
  required WidgetRef ref,
  required CaptureService svc,
  required _SessionAccount account,
  required List<SystemSessionShot> shots,
  void Function(int ingested, int total)? onIngested,
}) async {
  if (shots.isEmpty) return const [];
  await svc.startSession(account.projectId);
  account.captureSessionId ??= svc.activeSessionId;
  final ids = List<String?>.filled(shots.length, null);
  var done = 0;
  final gate = AsyncLimiter(3);
  final pending = <Future<void>>[];
  for (var i = 0; i < shots.length; i++) {
    // ⚠️ 每轮先把下标与照片取成局部量再进闭包 —— 并发任务体在 await
    // 之后才写 ids，循环变量绝不能被闭包共享（顺序错了对账就错）。
    final idx = i;
    final s = shots[i];
    pending.add(gate.run(() async {
      try {
        var known = account.ingested[s.path];
        if (s.changed && known == null) {
          // 内存登记丢了（恢复路径），账本还记着 —— 仍走修复。
          try {
            known = await ref
                .read(captureRepositoryProvider)
                .systemShotPhotoId(
                  projectId: account.projectId,
                  sourcePath: s.path,
                );
            if (known != null) account.ingested[s.path] = known;
          } catch (e) {
            Log.w('Capture', 'ledger lookup failed: ${s.path} :: $e');
          }
        }
        if (s.changed && known != null) {
          // 修复：交回后文件大小变了 —— 重拷覆盖 + 重算派生。
          // recopyPhoto 在 CameraCaptureService 上（CaptureService
          // 接口没有它）；实现不是该类型时跳过修复（测试桩场景）。
          try {
            if (svc is CameraCaptureService) {
              await svc.recopyPhoto(account.projectId, known, s.path);
              account.failed.remove(s.path);
              Log.i('Capture', 'shot repaired: $known <- ${s.path}');
            }
            ids[idx] = known;
          } catch (e) {
            account.failed.add(s.path);
            Log.w('Capture', 'shot repair failed: ${s.path} :: $e');
          }
        } else if (known != null) {
          // 已入库（同路径重复交付）—— 复用，不重复插行。
          ids[idx] = known;
        } else {
          final id = await svc.captureFromFile(
            account.projectId,
            s.path,
            takenAtOverride: s.takenAt,
            move: false,
            galleryMirror: false,
          );
          if (id.isNotEmpty) {
            ids[idx] = id;
            account.ingested[s.path] = id;
            account.failed.remove(s.path);
          } else {
            // 失败（复制/磁盘/DB）—— 记账，收尾对账说真话。
            account.failed.add(s.path);
          }
        }
      } catch (e) {
        account.failed.add(s.path);
        Log.w('Capture', 'shot ingest failed: ${s.path} :: $e');
      } finally {
        done++;
        onIngested?.call(done, shots.length);
      }
    }));
  }
  await Future.wait(pending);
  final out = ids.whereType<String>().toList();
  if (account.groupId != null && out.isNotEmpty) {
    try {
      await ref
          .read(organizeRepositoryProvider)
          .attachPhotosToGroup(account.projectId, account.groupId!, out);
    } catch (e) {
      // 组被整理流程调整掉时照片仍在（按批次成组），只记日志。
      Log.w('Capture', 'attach shots to group failed :: $e');
    }
  }
  return out;
}

// ─────────────────────────────────────────────────────────────
// 单张降级路径（无相册读权限 / 会话启动失败时兜底）
// ─────────────────────────────────────────────────────────────

/// 启动系统相机拍一张，拍完收进当前采集批次。
Future<(SystemShotOutcome, String)> _launchAndIngest(
  WidgetRef ref,
  String projectId,
  CaptureService svc,
) async {
  final tempPath =
      await ref.read(systemCameraServiceProvider).newTempShotPath();
  SystemCameraLaunch.pendingPath = tempPath;
  SystemCameraLaunch.launchedAt = DateTime.now();

  final sw = Stopwatch()..start();
  try {
    final ok = await ref.read(systemCameraServiceProvider).launch(tempPath);
    if (!ok) return (SystemShotOutcome.cancelled, '');

    // 系统相机回来了。先看文件真落下来了没有 —— 个别 ROM 返回 OK 但不
    // 写 EXTRA_OUTPUT（那种 ROM 的 data 里只有缩略图，这里不用它）。
    final f = File(tempPath);
    if (!f.existsSync() || f.lengthSync() == 0) {
      Log.w('Capture', 'system camera returned no image: $tempPath');
      try {
        await ref
            .read(cameraPreferencesProvider)
            .saveSessionDiag('单张直拍：相机确认后没有落盘（兼容层写不进'
                'App 目录的典型表现）· 建议改用普通 Android 手机拍');
      } catch (_) {}
      return (SystemShotOutcome.noImage, '');
    }

    final id = await svc.captureFromFile(projectId, tempPath);
    if (id.isEmpty) return (SystemShotOutcome.failed, '');
    return (SystemShotOutcome.shot, id);
  } on PlatformException catch (e) {
    Log.w('Capture', 'system camera launch failed: ${e.code} / ${e.message}');
    return (SystemShotOutcome.failed, '');
  } catch (e) {
    Log.e('Capture', 'system camera shot failed', e);
    return (SystemShotOutcome.failed, '');
  } finally {
    SystemCameraLaunch.clear();
    Log.d('Capture', 'system camera roundtrip: ${sw.elapsedMilliseconds}ms');
  }
}

/// 方案 D7 的补救：App 在系统相机前台时被杀 → 重进采集页，磁盘上可能有
/// 一张「拍了但没入库」的照片。有就补收，没有就静默清理。
Future<String> recoverPendingSystemShot({
  required String projectId,
  required CaptureService svc,
}) async {
  final path = SystemCameraLaunch.pendingPath;
  SystemCameraLaunch.clear();
  if (path == null) return '';
  final f = File(path);
  if (!f.existsSync() || f.lengthSync() == 0) return '';
  Log.i('Capture', 'recovering pending system shot: $path');
  return svc.captureFromFile(projectId, path);
}

/// 单张往返包一层列表返回（降级路径共用）。
Future<(SystemShotOutcome, List<String>, int)> _singleShotAsList(
  WidgetRef ref,
  String projectId,
  CaptureService svc,
) async {
  final (outcome, id) = await _launchAndIngest(ref, projectId, svc);
  final ids = id.isEmpty ? const <String>[] : <String>[id];
  return (outcome, ids, ids.length);
}

// ─────────────────────────────────────────────────────────────
// 主入口：连拍会话 v2（同步首批 + 拉模式晚到）
// ─────────────────────────────────────────────────────────────

/// 拍照入口的统一编排。
///
/// 系统相机模式下不经过 App 内相机页：点入口 → 补收单张残留 →
/// 拉起系统相机 → 按返回 → **同步收首批 → 入库（进度实时回调）→
/// 轮询拉晚到 → 实测对账 → 收口**。会话不可用（无读权限 / 原生不支持）
/// 自动退回单张往返。
///
/// 返回 `(结局, 入库照片 id 列表, 原生看到张数)`：
///  · `shot`：拍了；ids = 实际入库的全部照片。`shotCount > ids.length`
///    说明有少片（复制失败等），UI 必须明说；
///  · `missed`：原生判定大概率拍了但一张都没收到 —— UI 必须提示；
///  · `cancelled`：一张没拍（原生空窗等完也没见新图）—— 静默；
///  · `noImage` / `failed`：单张路径的两种失败。
Future<(SystemShotOutcome, List<String>, int)> runSystemCameraSession({
  required WidgetRef ref,
  required String projectId,
  CaptureService? svc,
  void Function(int ingested, int total)? onProgress,
  String? intoGroupId,
}) async {
  CameraCaptureService? owned;
  if (svc == null) {
    owned = CameraCaptureService(
      ref.read(captureRepositoryProvider),
      gallery: ref.read(galleryServiceProvider),
      prefs: ref.read(cameraPreferencesProvider),
    );
    svc = owned;
  }
  final account = _SessionAccount(projectId, groupId: intoGroupId);
  final seenPaths = <String>{};
  var likely = false;
  var sessionId = '';
  try {
    // 会话收图的前提是能读媒体库。没有就退回单张（单张走 EXTRA_OUTPUT
    // 文件直收，不需要读权限，永远可用）。
    var canRead = false;
    try {
      canRead = await requestGalleryPermission(ref);
    } catch (_) {}
    if (!canRead) {
      Log.w('Capture', 'session fallback: no gallery read permission');
      return _singleShotAsList(ref, projectId, svc);
    }

    try {
      // ⚠️ 挂起标记先写：被杀发生在等的窗口里 —— 写晚了就等于没写。
      try {
        await ref.read(cameraPreferencesProvider).savePendingSession(projectId);
      } catch (_) {}
      final (shots, diag, sid, likelyFlag) =
          await ref.read(systemCameraServiceProvider).launchSession();
      sessionId = sid;
      likely = likelyFlag;
      if (diag.isNotEmpty) {
        try {
          await ref.read(cameraPreferencesProvider).saveSessionDiag(diag);
        } catch (_) {}
      }
      seenPaths.addAll(shots.map((s) => s.path));

      // 入库 id 按交付顺序累积（去重保序）；返回给 UI 的就是它。
      final storedOrder = <String>[];

      // 首批入库（onProgress 实时 —— 卡片/HUD 的「已 N 张」是真进度）。
      final firstIds = await _ingestShots(
        ref: ref,
        svc: svc,
        account: account,
        shots: shots,
        onIngested: onProgress,
      );
      Log.i('Capture', 'first batch stored ${firstIds.length}/${shots.length}');
      storedOrder.addAll(firstIds);

      // ── 晚到照片：拉模式轮询（v2）──────────────────────────
      // 空首批 + likely = 照片可能还在写盘/索引，继续轮询；连续空轮且
      // 过了最短时长才收口。节奏与判据全在 Dart（可单测）。
      // 大概率没拍（空首批且 likely=false）时不轮询 —— 原生空窗已等过，
      // 快进快出。
      if (sessionId.isNotEmpty && (shots.isNotEmpty || likely)) {
        final sw = Stopwatch()..start();
        var emptyStreak = 0;
        while (true) {
          await Future<void>.delayed(const Duration(milliseconds: 700));
          final r =
              await ref.read(systemCameraServiceProvider).collectLate(sessionId);
          final fresh =
              r.shots.where((s) => !seenPaths.contains(s.path)).toList();
          seenPaths.addAll(r.shots.map((s) => s.path));
          if (fresh.isEmpty && r.shots.isEmpty) {
            emptyStreak++;
          } else {
            emptyStreak = 0;
            final batchIds = await _ingestShots(
              ref: ref,
              svc: svc,
              account: account,
              shots: r.shots,
              onIngested: onProgress,
            );
            for (final id in batchIds) {
              if (!storedOrder.contains(id)) storedOrder.add(id);
            }
          }
          if (r.done) break;
          // 收口：连续 3 个空轮且至少 5s（给相机写盘留时间），或 30s 上限。
          if (emptyStreak >= 3 && sw.elapsed >= const Duration(seconds: 5)) {
            break;
          }
          if (sw.elapsed >= const Duration(seconds: 30)) break;
        }
        unawaited(ref.read(systemCameraServiceProvider).endCollect(sessionId));
      }

      // ── 结局（全部来自入库实测）────────────────────────────
      // storedOrder：按交付顺序去重的入库 id（来源是每批的返回值，
      // 顺序 = shots 顺序 —— 不能用 account.ingested.values，那是
      // 完成顺序，并发下与 shots 顺序不一致）。
      final storedIds = storedOrder;
      if (storedIds.isEmpty) {
        if (likely) {
          // 大概率拍了但一张没收到 —— 必须明说（静默零 10-22 真机反馈）。
          return (SystemShotOutcome.missed, const <String>[], seenPaths.length);
        }
        // 真没拍：静默收场，不建批次（空批次会在续接窗里被续上，添乱）。
        return (SystemShotOutcome.cancelled, const <String>[], 0);
      }
      return (
        SystemShotOutcome.shot,
        storedIds,
        seenPaths.length,
      );
    } on PlatformException catch (e) {
      // 会话拉不起来（NO_CAMERA_APP / MEDIA_QUERY_FAILED / 双启）——
      // 退回单张往返，别让升级把人拍个精光。
      Log.w('Capture', 'session launch failed, fallback to single: '
          '${e.code} / ${e.message}');
      return _singleShotAsList(ref, projectId, svc);
    }
  } catch (e) {
    Log.e('Capture', 'system camera session failed', e);
    return (SystemShotOutcome.failed, const <String>[], 0);
  } finally {
    if (owned != null) {
      try {
        // 一次性会话服务不等派生（缩略图/指纹），万一半路中断由
        // backfillThumbnails / backfillHashes 在整理页兜底。
        await owned.dispose(awaitDerived: false);
      } catch (_) {}
    }
    // 收口：本场批次结束（下一拍 5 分钟内 resumable 复活，分组语义不变）；
    // 挂起标记消费（一场拍照 = 一次完整的「拍 → 收 → 入库」闭环）。
    final sid = account.captureSessionId;
    if (sid != null) {
      try {
        await ref.read(captureRepositoryProvider).endSession(sid);
        Log.i('Capture', 'camera session ended: $sid ($projectId)');
      } catch (e) {
        Log.w('Capture', 'end camera session failed :: $e');
      }
    }
    try {
      await ref.read(cameraPreferencesProvider).clearPendingSession();
    } catch (_) {}
  }
}

// ─────────────────────────────────────────────────────────────
// 拍照入口（照片页 / 组内补拍）
// ─────────────────────────────────────────────────────────────

/// 拍照入口的统一编排：补收单张残留 → 连拍会话。
///
/// 返回 `(null, [], 0)` = 内置相机模式，调用方 push 全屏采集页。
Future<(SystemShotOutcome?, List<String>, int)> openSystemCameraDirect({
  required WidgetRef ref,
  required String projectId,
  void Function(int ingested, int total)? onProgress,
  String? intoGroupId,
}) async {
  final mode = await _resolveCaptureMode(ref);
  if (mode == CameraCaptureMode.builtin) {
    return (null, const <String>[], 0);
  }

  // 进程被杀的待收照片：先收（一次性服务），再开新的快门。
  try {
    final recoverSvc = CameraCaptureService(
      ref.read(captureRepositoryProvider),
      gallery: ref.read(galleryServiceProvider),
      prefs: ref.read(cameraPreferencesProvider),
    );
    String recovered = '';
    try {
      recovered = await recoverPendingSystemShot(
        projectId: projectId,
        svc: recoverSvc,
      );
    } finally {
      try {
        await recoverSvc.dispose();
      } catch (_) {}
    }
    if (recovered.isNotEmpty) {
      Log.i('Capture', 'entry recovered pending shot: $recovered');
    }
  } catch (e) {
    Log.w('Capture', 'recover at entry failed :: $e');
  }

  return runSystemCameraSession(
    ref: ref,
    projectId: projectId,
    onProgress: onProgress,
    intoGroupId: intoGroupId,
  );
}

/// 进程被杀后的连拍会话恢复（v0.24.9）。
///
/// 原生按持久化三要素把收图全量再跑一遍，Dart 走同一条 ingest 链；
/// 已入库的按 DB 账本过滤（恢复重收不重复）。
///
/// 返回本次补收入库的张数（0 = 没有可收的）—— app.dart 据此给用户
/// 「照片补回来了」的可见反馈。
Future<int> recoverPendingCameraSession(
  WidgetRef ref,
  String projectId,
  DateTime launchedAt,
) async {
  var recovered = 0;
  try {
    final recovery = await ref.read(systemCameraServiceProvider).recoverSession();
    if (recovery.diag.isNotEmpty) {
      try {
        await ref.read(cameraPreferencesProvider).saveSessionDiag(recovery.diag);
      } catch (_) {}
    }
    var shots = recovery.shots;
    if (shots.isEmpty && !recovery.hasContext) {
      shots = await ref
          .read(systemCameraServiceProvider)
          .recentTempShots(launchedAt);
    }
    if (!recovery.hasContext && shots.isEmpty) return 0;
    // 已入库过滤走 DB 账本（恢复重收不重复）。
    if (shots.isNotEmpty) {
      final done = await ref
          .read(captureRepositoryProvider)
          .storedSystemPaths(projectId);
      if (done.isNotEmpty) {
        final before = shots.length;
        shots = shots.where((s) => !done.contains(s.path)).toList();
        Log.i('Capture', 'recovery filter: $before -> ${shots.length} '
            '(${before - shots.length} already ingested)');
      }
    }
    final svc = CameraCaptureService(
      ref.read(captureRepositoryProvider),
      gallery: ref.read(galleryServiceProvider),
      prefs: ref.read(cameraPreferencesProvider),
    );
    try {
      final account = _SessionAccount(projectId);
      // 首批入库（可能为空 —— 照片可能还没被媒体库索引完）。
      if (shots.isNotEmpty) {
        final ids = await _ingestShots(
          ref: ref,
          svc: svc,
          account: account,
          shots: shots,
        );
        recovered = ids.length;
        if (ids.isNotEmpty) {
          Log.i('Capture', 'recovered ${ids.length}/${shots.length} shot(s) '
              'after process death into $projectId');
        }
      }
      // ── 晚到轮询（v0.24.19）────────────────────────────
      // 恢复只是一次快照：媒体库可能还有没索引完的照片（真机实拍 7 张
      // 恢复只收到 5 张，另 2 张晚索引/晚提交）。原生已按恢复结果注册
      // collectLate 上下文 —— 这里继续拉，口径与正常会话一致。
      final sid = recovery.sessionId;
      if (sid.isNotEmpty) {
        final seen = shots.map((s) => s.path).toSet();
        final sw = Stopwatch()..start();
        var emptyStreak = 0;
        while (true) {
          await Future<void>.delayed(const Duration(milliseconds: 700));
          final r =
              await ref.read(systemCameraServiceProvider).collectLate(sid);
          final fresh =
              r.shots.where((s) => !seen.contains(s.path)).toList();
          seen.addAll(r.shots.map((s) => s.path));
          if (fresh.isEmpty && r.shots.isEmpty) {
            emptyStreak++;
          } else {
            emptyStreak = 0;
            final before = account.ingested.length;
            await _ingestShots(
              ref: ref,
              svc: svc,
              account: account,
              shots: r.shots,
            );
            // 只有真新入库的才计补收张数（修复 changed 不算）。
            recovered += account.ingested.length - before;
          }
          if (r.done) break;
          if (emptyStreak >= 3 && sw.elapsed >= const Duration(seconds: 5)) {
            break;
          }
          if (sw.elapsed >= const Duration(seconds: 30)) break;
        }
        unawaited(ref.read(systemCameraServiceProvider).endCollect(sid));
        if (account.ingested.length > recovered) {
          Log.i('Capture', 'recovery late poll: total '
              '${account.ingested.length} ingested for $projectId');
        }
      }
      // 恢复 = 一次完整收尾：结束这次补收打开的批次。
      try {
        await svc.endSession();
      } catch (e) {
        Log.w('Capture', 'end recovered session failed :: $e');
      }
    } finally {
      try {
        await svc.dispose(awaitDerived: false);
      } catch (_) {}
    }
  } catch (e) {
    Log.w('Capture', 'pending session recovery failed :: $e');
  }
  return recovered;
}

// ─────────────────────────────────────────────────────────────
// 带进度卡的系统相机拍照（照片页 / 组内补拍入口）
// ─────────────────────────────────────────────────────────────

/// 进度卡的阶段文案（与采集页 HUD 同口径，两处不能各说各话）。
enum _ProgressPhase { opening, backHint, slowHint, ingesting }

/// 带进度卡的系统相机拍照（照片页 / 组内补拍入口）。
///
/// v2 同步契约下这张卡**重新有意义**了：相机返回 → 收首批（≤2s）→
/// 入库（进度实时）→ 晚到轮询 → 收口，全程卡都在，显示真实进度
/// 「已收图 N 张」；结束时结局确定，不存在「卡撤了照片还在路上」。
Future<(SystemShotOutcome?, List<String>, int)> runSystemCameraWithProgress({
  required BuildContext context,
  required WidgetRef ref,
  required String projectId,
  String? intoGroupId,
}) async {
  if (await _resolveCaptureMode(ref) == CameraCaptureMode.builtin) {
    return (null, const <String>[], 0);
  }
  if (!context.mounted) {
    return (SystemShotOutcome.cancelled, const <String>[], 0);
  }
  var ingested = 0;
  var total = 0;
  var phase = _ProgressPhase.opening;
  final state = ValueNotifier<(String, int, int)>(
    ('正在打开系统相机…', 0, 0),
  );

  void refresh() {
    if (ingested > 0) {
      state.value = ('正在收图… 已 $ingested 张', ingested, total);
    }
  }

  // 阶段文案定时器：2s 提示按返回、5s 明说相机保存偏慢。
  final tBack = Timer(const Duration(seconds: 2), () {
    if (ingested == 0 && phase == _ProgressPhase.opening) {
      phase = _ProgressPhase.backHint;
      state.value = ('拍完请按返回键 · 照片会自动收进 App', 0, 0);
    }
  });
  final tSlow = Timer(const Duration(seconds: 5), () {
    if (ingested == 0 &&
        (phase == _ProgressPhase.opening ||
            phase == _ProgressPhase.backHint)) {
      phase = _ProgressPhase.slowHint;
      state.value = ('正在收照片，请稍候…（相机保存有时偏慢）', 0, 0);
    }
  });

  showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => PopScope(
      canPop: false,
      child: Dialog(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 22, 20, 20),
          child: ValueListenableBuilder<(String, int, int)>(
            valueListenable: state,
            builder: (ctx, v, _) => Row(
              children: [
                const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2.4),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(v.$1, style: Theme.of(ctx).textTheme.titleSmall),
                      if (v.$3 > 0) ...[
                        const SizedBox(height: 4),
                        Text(
                          '已处理 ${v.$2} / ${v.$3} 张',
                          style: Theme.of(ctx).textTheme.bodySmall,
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );

  try {
    return await openSystemCameraDirect(
      ref: ref,
      projectId: projectId,
      intoGroupId: intoGroupId,
      onProgress: (i, t) {
        ingested = i;
        total = t;
        if (phase != _ProgressPhase.ingesting) {
          phase = _ProgressPhase.ingesting;
        }
        refresh();
      },
    );
  } finally {
    tBack.cancel();
    tSlow.cancel();
    state.dispose();
    // 撤卡。页面可能在等待期间被销毁（极端情况）—— 防御式 try。
    try {
      if (context.mounted) Navigator.of(context).pop();
    } catch (_) {}
  }
}
