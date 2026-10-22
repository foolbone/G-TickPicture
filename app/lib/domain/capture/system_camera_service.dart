import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

import '../../data/fs/project_paths.dart';

/// 系统相机拍照的平台通道 v2（2026-10-22，feat/system-camera-v2 重写）。
///
/// 与 `NativeGalleryService` 同款定位：`domain/capture` 里的薄通道封装 ——
/// 不持 context、不做决策。决策（ingest、轮询节奏、错误口径）都在
/// `ui/capture/system_camera_actions.dart`。
///
/// ── v2 同步契约（为什么推倒重来）────────────────────────────
/// v0.24.12~16 的「返回即回 App + native→Dart 反向推送」在真机上连续
/// 翻车（引擎线程断言吞推送、首批与注册的时序竞态、会话状态泄漏），
/// 10-22 真机验收「一张图都收不到」。本版：
///
///  · [launchSession] **同步**返回首批（原生收完才回，有界 ≤2s）——
///    没有反向推送，就没有「推送丢在哪一环」的问题；
///  · 晚到/写了一半的照片由 Dart 调 [collectLate] **主动拉取**（拉模式
///    无竞态），节奏与收口判据全在 Dart 侧（可单测）；
///  · [endCollect] 释放原生会话上下文。
///
/// 保留：单张降级 [launch]、进程被杀恢复 [recoverSession]（全量口径）、
/// 临时路径约定（与 FileProvider 声明同源）。
class SystemCameraService {
  SystemCameraService();

  static const MethodChannel _channel = MethodChannel('gtick/system_camera');

  /// 生成一张系统相机照片的临时落点（外部私有 files 的 gt_temp 下）。
  ///
  /// 在服务层而不是 UI 层：临时目录必须与项目目录**同根**
  /// （都是 [ProjectPaths.filesRoot]，即 getExternalFilesDir），
  /// ingest 时 rename 才是同一卷原子移动；目录约定是 data 层的事
  /// （FileProvider 的 res/xml/file_paths.xml 与这里必须一致），
  /// UI 层不该知道（架构 R2：UI 不直连数据层）。
  Future<String> newTempShotPath() async {
    final root = await ProjectPaths.filesRoot();
    final dir = Directory('${root.path}/gt_temp');
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return '${dir.path}/gt_shot_${DateTime.now().millisecondsSinceEpoch}.jpg';
  }

  /// 扫临时目录里 [since] 前后落盘的图片（v0.24.9 单张降级路径的补救）。
  ///
  /// 场景：单张往返（无读权限时的降级）期间进程被杀 —— EXTRA_OUTPUT
  /// 的文件留在 gt_temp/ 没人收。正常往返会把它 ingest 并移走，所以
  /// 这里能扫到的都是「拍了没入库」的。mtime 给 1 分钟容差。
  Future<List<SystemSessionShot>> recentTempShots(DateTime since) async {
    final root = await ProjectPaths.filesRoot();
    final dir = Directory('${root.path}/gt_temp');
    if (!dir.existsSync()) return const [];
    final out = <SystemSessionShot>[];
    for (final e in dir.listSync()) {
      if (e is! File) continue;
      if (!e.path.toLowerCase().endsWith('.jpg')) continue;
      try {
        if (e.lengthSync() <= 0) continue;
        final mtime = e.lastModifiedSync();
        if (mtime.isBefore(since.subtract(const Duration(minutes: 1)))) {
          continue;
        }
        out.add(SystemSessionShot(path: e.path, takenAt: mtime));
      } catch (_) {}
    }
    out.sort((a, b) => (a.takenAt ?? DateTime.fromMillisecondsSinceEpoch(0))
        .compareTo(b.takenAt ?? DateTime.fromMillisecondsSinceEpoch(0)));
    return out;
  }

  /// 拉起系统相机拍**一张**（单张降级路径用）。
  ///
  /// [tempPath] 临时文件**绝对路径**。返回 true = 用户拍了（RESULT_OK；
  /// 文件是否真落盘由调用方校验）。抛 [PlatformException]：
  /// `NO_CAMERA_APP` / `BAD_PATH` / `ALREADY_RUNNING`。
  Future<bool> launch(String tempPath) async {
    final res = await _channel.invokeMethod<Map<Object?, Object?>>(
      'launch',
      {'path': tempPath},
    );
    return res?['ok'] == true;
  }

  /// 连拍会话（v2 同步契约）。
  ///
  /// `INTENT_ACTION_STILL_IMAGE_CAMERA` 拉起系统相机普通模式，按返回回
  /// App；原生**同步收一批**（媒体库快查 + 文件系统一轮扫描，只交完整
  /// 照片，有界 ≤2s）随结果返回。返回
  /// `(首批照片, 诊断摘要, 会话 id, 大概率拍了)`：
  ///  · 首批**可能为空** —— 空不等于没拍：[likely]==true 时调用方应继续
  ///    [collectLate] 轮询（照片可能还在写盘/索引），最后仍空才报
  ///    「没收到照片」；likely==false 的空批 = 用户真没拍（静默收场）。
  ///  · [diag] 是收图诊断摘要，「关于」面板直接看，现场排障不抓 logcat。
  ///
  /// 抛 [PlatformException]：`NO_CAMERA_APP` / `ALREADY_RUNNING` /
  /// `MEDIA_QUERY_FAILED`（读不了媒体库 —— 调用方退回单张模式）。
  Future<(List<SystemSessionShot>, String diag, String sessionId, bool likely)>
      launchSession() async {
    final res = await _channel.invokeMethod<Map<Object?, Object?>>(
      'launchSession',
    );
    final raw = res?['shots'];
    final shots = <SystemSessionShot>[];
    if (raw is List) {
      for (final item in raw) {
        final s = SystemSessionShot.fromMap(item);
        if (s != null) shots.add(s);
      }
    }
    final diag = res?['diag'];
    final sid = res?['sessionId'];
    return (
      shots,
      diag is String ? diag : '',
      sid is String ? sid : '',
      res?['likely'] == true,
    );
  }

  /// 轮询拉取晚到/写完的照片（v2，拉模式）。
  ///
  /// 每次调用做一轮「文件系统扫描 + 媒体库补时刻」，与会话的已交付表做
  /// 差集：新路径 → `changed=false`；大小变了 → `changed=true`（调用方
  /// 走修复）。**无推送、无竞态**：谁调用谁拿到。
  ///
  /// `done` = 原生侧上下文已释放（超时/不存在）—— 调用方收到后应停止
  /// 轮询；正常收口判据（连续空轮 + 最短时长）在调用方。
  Future<({List<SystemSessionShot> shots, bool done})> collectLate(
    String sessionId,
  ) async {
    final res = await _channel.invokeMethod<Map<Object?, Object?>>(
      'collectLate',
      {'sessionId': sessionId},
    );
    final raw = res?['shots'];
    final shots = <SystemSessionShot>[];
    if (raw is List) {
      for (final item in raw) {
        final s = SystemSessionShot.fromMap(item);
        if (s != null) shots.add(s);
      }
    }
    return (shots: shots, done: res?['done'] == true);
  }

  /// 轮询结束，释放原生会话上下文（幂等：上下文不存在也无害）。
  Future<void> endCollect(String sessionId) async {
    try {
      await _channel.invokeMethod<void>('endCollect', {'sessionId': sessionId});
    } catch (_) {
      // 释放失败无碍：上下文有 120s 超时自清。
    }
  }

  /// 恢复被中断的连拍会话（v0.24.9，保留）。
  ///
  /// 场景：拍照期间 App 进程被系统杀掉 —— 重启后内存里的收图上下文全
  /// 丢。原生按持久化三要素把收图**全量口径**再跑一遍（带完整稳定窗口
  /// —— 恢复发生在启动期，没人等首批）。
  ///
  /// `hasContext == false` = 没有可恢复的会话（正常收完过 / 从没拍过）。
  Future<SessionRecovery> recoverSession() async {
    final res = await _channel.invokeMethod<Map<Object?, Object?>>(
      'recoverSession',
    );
    if (res == null) {
      return const SessionRecovery(shots: [], hasContext: false);
    }
    final raw = res['shots'];
    final shots = <SystemSessionShot>[];
    if (raw is List) {
      for (final item in raw) {
        final s = SystemSessionShot.fromMap(item);
        if (s != null) shots.add(s);
      }
    }
    final diag = res['diag'];
    final sid = res['sessionId'];
    return SessionRecovery(
      shots: shots,
      hasContext: true,
      diag: diag is String ? diag : '',
      sessionId: sid is String ? sid : '',
    );
  }
}

/// 收回的一张新图。
///
/// 纯数据载体：[path] 是原图**绝对路径**（DCIM 等，归相册管），ingest 侧
/// 只复制、绝不移动/改名（「原始文件永不改名」的边界在项目目录内；会话
/// 原图的主人是系统相册，动它等于偷用户的底片）。
class SystemSessionShot {
  const SystemSessionShot({
    required this.path,
    this.takenAt,
    this.changed = false,
  });

  /// 原图绝对路径。
  final String path;

  /// MediaStore DATE_TAKEN（真快门时刻）。个别图没有 → null。
  final DateTime? takenAt;

  /// true = 这张**已交回并入库**，但本轮发现大小变了（交早了/相机补写）
  /// —— 调用方走修复（重拷覆盖 + 重算派生），而不是再插一行。
  final bool changed;

  /// 原生回传项解析。path 缺失/为空的项静默丢弃（原生侧已过滤，
  /// 这里是第二道防：坏项扔掉，不能让一张脏数据炸掉整批收图）。
  static SystemSessionShot? fromMap(Object? raw) {
    if (raw is! Map) return null;
    final p = raw['path'];
    if (p is! String || p.isEmpty) return null;
    final ms = raw['dateTakenMs'];
    return SystemSessionShot(
      path: p,
      takenAt: ms is int && ms > 0
          ? DateTime.fromMillisecondsSinceEpoch(ms)
          : null,
      changed: raw['changed'] == true,
    );
  }
}

/// 一次被中断的连拍会话的恢复结果（v0.24.9）。
class SessionRecovery {
  const SessionRecovery({
    required this.shots,
    required this.hasContext,
    this.diag = '',
    this.sessionId = '',
  });

  /// 恢复收到的图（可能为空 —— 原生收图窗口跑完没找到新文件）。
  final List<SystemSessionShot> shots;

  /// 是否存在被中断的会话上下文。false = 没有可恢复的（正常完成过）。
  final bool hasContext;

  /// 收图诊断摘要（「关于」面板展示用）。
  final String diag;

  /// 被杀会话的 id。空串 = 旧版本没有该字段。
  final String sessionId;
}
