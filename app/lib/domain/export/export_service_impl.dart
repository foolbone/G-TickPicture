import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';

import 'package:archive/archive_io.dart';
import 'package:drift/drift.dart';
import 'package:path/path.dart' as p;
import 'package:uuid/uuid.dart';

import '../../core/constants.dart';
import '../../core/logger.dart';
import '../../core/perf_bridge.dart';
import '../../data/db/database.dart';
import '../../data/fs/project_paths.dart';
import '../model/delivery_plan.dart';
import '../model/delivery_readiness.dart';
import 'delivery_plan_builder.dart';
import 'export_service.dart';
import 'volume_planner.dart';

/// 打包导出服务的真实实现 —— M5，09-27 升级为「预检 / 监装」两大部分。
///
/// ── 交付结构（老板 09-27 拍板）─────────────────────────────────
///   ① 照片先分**预检 / 监装**两大部分（整理时人归的类）。
///   ② 监装与货品清单无关 → 全部进 `监装/` 一个文件夹，用原始文件名。
///   ③ 预检按**整理时人指定的箱号**分文件夹 → `预检/箱A/`；
///      对应上编码的用交付命名，没对应上的用原始文件名，同一个箱号目录里。
///   ④ 整份交付一个箱号都没指定 → 预检内部保持平铺（不造 `_未分箱/`）。
///
/// 包内布局：
/// ```
/// 集刻交付_<项目名>_<日期>/
/// ├── 预检/
/// │   ├── 箱A/
/// │   │   ├── 007_103010013345AMX_01.jpg   ← 对应上了：交付命名
/// │   │   └── P_20260927_101234.jpg        ← 没对应上：原始文件名
/// │   └── _未分箱/                          ← 没指定箱号的（若有箱号时）
/// ├── 监装/
/// │   └── P_20260927_110000.jpg            ← 与清单无关，一个文件夹
/// ├── _未使用/                              ← 勾选「含未使用」才有
/// └── manifest.json                         ← 机器可读的交付清单
/// ```
/// 同时打 ZIP 便于微信直发（2026-09-30 起：可选压缩画质 + 超 500MB
/// 自动分卷 —— 微信单文件 1GB 上限；每卷都独立可解压且含 manifest）。
///
/// 2026-09-30（老板）：包内不再产出 `_对照表.csv` 与 `_清单缺口.txt`，
/// 交付包只留照片 + manifest —— 报告员直接翻照片即可。
///
/// ── 三条硬约束（不要为了"快一点"破坏）───────────────────────
///   1. **原始文件永不改名**。包内照片是**副本**，源文件只读。
///      §6.4 的底线：现场照片是证据，任何重命名都是篡改风险。
///      （包内改名只发生在副本上，且只针对"对应上了"的照片。）
///   2. **交付不设检查**（老板 09-27）。归属完整性异常只 Log + 写
///      manifest，不拦截、不弹框；覆盖率从来不是闸门。
///   3. **进包的必须是 packagePhotos 全量**（已对应 + 预检未对应 + 监装）。
///      三堆分散在三个字段里，循环时漏一堆就等价于"少交付一批照片"。
class ExportServiceImpl implements ExportService {
  ExportServiceImpl(this._db);

  final AppDatabase _db;
  static const _uuid = Uuid();

  @override
  Future<ExportPrecheck> precheck(
    String projectId,
    ExportOptions options,
  ) async {
    final plan = await DeliveryPlanBuilder(_db)
        .build(projectId, groupByCarton: options.groupByCarton);
    final est = _estimate(plan, options);

    // 老板 2026-09-27 拍板：「交付时，去掉原来的检查，直接按分组打包」。
    // 所以这里列出的都只是**告知**，没有任何一条会阻止打包。
    final warnings = <String>[];
    if (plan.gapCount > 0) {
      warnings.add('有 ${plan.gapCount} 件货品没有照片（缺口不会阻止交付）');
    }
    if (plan.unmatchedPhotos.isNotEmpty) {
      warnings.add(
        '有 ${plan.unmatchedPhotos.length} 张预检照片没对应上编码，'
        '会按原始文件名跟着箱号一起交付',
      );
    }
    if (plan.underShot.isNotEmpty) {
      warnings.add('有 ${plan.underShot.length} 件货品的照片张数没达到要求');
    }
    if (est.shouldPreferWebdav) {
      warnings.add('交付包较大，建议改走网盘发送');
    }
    // 微信单文件 1GB 上限（老板 09-30）：关了分卷又超限时必须提前说，
    // 别让人打完 3GB 的包才发现微信发不出去。
    if (!options.splitVolumes && est.totalBytes > 1024 * 1024 * 1024) {
      warnings.add('单包超过微信 1GB 上限，微信发不出去 —— '
          '建议打开「自动分卷」或改走网盘');
    }

    return ExportPrecheck(
      readiness: DeliveryReadiness(
        orphanPhotoAssignments: plan.orphanCount,
        orphanGroupAssignments: 0, // 已在 builder 里合并计数，见 orphanCount 口径
        itemTotal: plan.itemTotal,
        itemGap: plan.gapCount,
        // 09-27 起「未对应」不再等于「不进包」——它们照样交付，
        // 只是用原始文件名。所以这个数现在是**知情项**，不是拦截项。
        photoUnassigned: plan.unmatchedPhotos.length,
        photoConfirmed: plan.photoCount,
        photoUnused: plan.unusedPhotos.length,
      ),
      estimatedBytes: est.totalBytes,
      freeBytes: await _freeBytes(projectId),
      warnings: warnings,
    );
  }

  @override
  Future<ExportEstimate> estimate(
    String projectId,
    ExportOptions options,
  ) async {
    final plan = await DeliveryPlanBuilder(_db)
        .build(projectId, groupByCarton: options.groupByCarton);
    return _estimate(plan, options);
  }

  ExportEstimate _estimate(DeliveryPlan plan, ExportOptions options) {
    // 进包的是三堆：已对应 + 预检未对应 + 监装（见 plan.packagePhotos）。
    // 少算一堆 → 体积估算偏小 → 打包中途才发现空间不够，那是最糟的顺序。
    var rawBytes = 0;
    for (final ph in plan.packagePhotos) {
      rawBytes += _fileSizeOr(ph.sourcePath, AppConst.estimatedPhotoBytes);
    }
    if (options.includeUnused) {
      for (final ph in plan.unusedPhotos) {
        rawBytes += _fileSizeOr(ph.sourcePath, AppConst.estimatedPhotoBytes);
      }
    }

    // 压缩开 → 按长边 2560/q85 的经验系数估（0.45，宁大勿小）；
    // 原图直出的部分会高估 —— 空间检查宁可保守。
    final payloadBytes =
        options.compressPhotos ? (rawBytes * 0.45).round() : rawBytes;

    // JPEG 已压缩，再压几乎无收益；留 0.5% + 64KB 给文本文件与 ZIP 目录项
    const overheadFloor = 64 * 1024;
    final overhead = (payloadBytes * 0.005).round() + overheadFloor;

    return ExportEstimate(
      rawBytes: rawBytes,
      totalBytes: payloadBytes + overhead,
      photoCount: plan.photoCount,
      itemCount: plan.itemTotal,
    );
  }

  @override
  Future<DeliveryResult> build({
    required String projectId,
    required ExportOptions options,
    void Function(double ratio, String stage)? onProgress,
    bool Function()? isCancelled,
  }) async {
    void tick0(double r, String s) => onProgress?.call(r, s);

    // 单调钳制：压缩段（0.05+0.55*i/n）与复制/ZIP 段的比例是**分段计算**
    // 的浮点数，段间交界可能出现 1e-16 级的回退（0.6000000000000001 → 0.6）。
    // 进度条对用户必须单调不减，在源头统一钳制。
    var lastRatio = 0.0;
    void tick(double r, String s) {
      final v = r < lastRatio ? lastRatio : r;
      lastRatio = v;
      tick0(v, s);
    }

    bool cancelled() => isCancelled?.call() ?? false;

    tick(0.0, '正在统计照片');

    final plan = await DeliveryPlanBuilder(_db)
        .build(projectId, groupByCarton: options.groupByCarton);

    // ── 归属完整性（老板 09-26 + 09-27 两次拍板：交付不设任何检查）──
    // orphan > 0 意味着归属数据被绕开 AssignService 改过（正常操作造不出来）。
    // 行为：只 Log + 写进 manifest，不提示、不拦截、不弹确认。
    // 现场要的是"点了就出包"，异常只写进 manifest 备查。
    if (!plan.canDeliver) {
      Log.w('Export',
          '归属完整性异常 orphanCount=${plan.orphanCount}，按拍板继续打包（留痕）');
    }

    if (cancelled()) throw const ExportCancelled();

    // ── 输出目录：复用 ProjectPaths 的 delivery 区（§6.4）──
    final stamp = _stamp(DateTime.now());
    final folderName = '集刻交付_${_safe(plan.projectName)}_$stamp';
    final base = await ProjectPaths.deliveryDir(projectId);
    final outRoot = Directory(p.join(base.path, folderName));
    if (await outRoot.exists()) {
      await outRoot.delete(recursive: true);
    }
    await outRoot.create(recursive: true);

    // ── 汇总「要复制哪些文件」（src → dst 绝对路径）──
    //
    // ⚠️ 性能（2026-09-30 第三轮定位，最终结论）：**这里也一个 await 都不能有**。
    //    每个 async 文件操作在事件循环粗糙的环境要 ~100-184ms（详见 `_copyFile`），
    //    1000 张照片光 `await src.exists()` 就要 100+ 秒 —— 它跑在**主 isolate**
    //    上，比后台 isolate 里的复制更致命（直接把 UI 拖死）。
    //    所以一律 `existsSync()`；真正的重 IO 在 [_packEntry] 里同步完成。
    final looseCount = options.includeUnused ? plan.unusedPhotos.length : 0;

    final files = <List<String>>[];
    for (final ph in plan.packagePhotos) {
      final src = File(ph.sourcePath);
      if (!src.existsSync()) continue;
      files.add([src.path, p.join(outRoot.path, ph.fileName)]);
    }
    if (options.includeUnused && looseCount > 0) {
      final looseDir = p.join(outRoot.path, '_未使用');
      for (final ph in plan.unusedPhotos) {
        final src = File(ph.sourcePath);
        if (!src.existsSync()) continue;
        files.add([src.path, p.join(looseDir, p.basename(ph.fileName))]);
      }
    }

    // ── 压缩阶段（老板 09-30 拍板，适配微信 1GB 单文件上限）──
    //
    // 为什么压缩在**主 isolate**、复制/ZIP 在后台 isolate：
    //   压缩走平台通道（原生 BitmapFactory），Dart 侧只是 await 通道回复
    //   —— 重活在原生线程（Dispatchers.Default），主 isolate 不阻塞；
    //   且按 8 张/块分块，1000 张只有 ~125 次 await，即使按「每 await
    //   ~100ms」的最坏环境也就十几秒。原生侧**串行**压缩（一张 12MP
    //   ARGB 位图 48MB，并发会顶爆低配机内存）。
    //
    // 失败口径：通道不可用 / 返回异常 → 全部按「未压缩」处理，交由
    // [_packEntry] 回退复制原图 —— **压缩只是优化，绝不能让它丢照片**。
    // 目标目录在压缩前建好 —— 压缩产物直接写进包内目录（预检/监装/…），
    // 不建的话原生/替身写 dst 时目录还不存在。目录数 ≈ 箱号数 + 2，
    // 同步创建的开销可忽略（与照片数无关）。[_packEntry] 里的创建保留，
    // 幂等，纯防御。
    final outDirs = <String>{for (final f in files) p.dirname(f[1])};
    for (final dir in outDirs) {
      Directory(dir).createSync(recursive: true);
    }

    final compressFlags = List<bool>.filled(files.length, false);
    if (options.compressPhotos && files.isNotEmpty) {
      const chunk = 8;
      final n = files.length;
      tick(0.05, '正在压缩照片 0 / $n');
      for (var start = 0; start < n; start += chunk) {
        if (cancelled()) throw const ExportCancelled();
        final end = start + chunk < n ? start + chunk : n;
        final jobs = [
          for (var i = start; i < end; i++)
            CompressJob(srcPath: files[i][0], dstPath: files[i][1]),
        ];
        final results = await PerfBridge.compressPhotos(jobs);
        for (var k = 0; k < results.length; k++) {
          final r = results[k];
          // ok && !skipped → 压缩产物已由原生写到 dst；
          // skipped（原图够小）/失败 → 保持 false，打包时复制原图。
          compressFlags[start + k] = r.ok && !r.skipped;
        }
        tick(0.05 + 0.55 * end / n, '正在压缩照片 $end / $n');
      }
    }

    // ── 重 IO（复制 + manifest + 分卷 ZIP）放到**后台 isolate** ──
    //
    // 为什么不留在主 isolate：这三步是纯粹的磁盘读写（1000+ 次文件创建 /
    // 读取 / 写入），在低端机或「文件操作昂贵」的环境下累计可达数十秒。
    // 放到后台 isolate 后：① UI 线程全程不阻塞 —— 进度照跳、取消可点，
    // 不会出现「点了打包 App 就假死」；② 重 IO 的临时缓冲不进 UI 堆。
    // 见 [_packEntry]。
    tick(options.compressPhotos ? 0.60 : 0.05, '正在打包 0 / ${files.length}');
    final zipBase = outRoot.path; // 单卷 → '<base>.zip'；多卷 → '<base>_第NN卷-共MM卷.zip'
    final manifestJson =
        const JsonEncoder.withIndent('  ').convert(_manifestOf(plan, options));

    final List<DeliveryVolume> volumes;
    try {
      volumes = await _packIo(
        outRoot: outRoot.path,
        zipBase: zipBase,
        manifestPath: p.join(outRoot.path, 'manifest.json'),
        manifestJson: manifestJson,
        files: files,
        compressFlags: compressFlags,
        compressAttempted: options.compressPhotos,
        volumeLimit:
            options.splitVolumes ? options.volumeLimitBytes : 0, // 0 = 不分卷
        onProgress: tick,
        isCancelled: cancelled,
      );
    } on ExportCancelled {
      // 取消留下的是不完整的卷（可能不止一个），删掉免得用户误发出去。
      // ⚠️ 被 kill 的 isolate 可能还没来得及释放文件句柄（Windows 上会
      // 删不掉）——删不掉就算了，绝不能因此把「已取消」变成别的异常。
      try {
        final parent = Directory(p.dirname(zipBase));
        final baseName = p.basename(zipBase);
        for (final e in parent.listSync()) {
          if (e is File &&
              e.path.endsWith('.zip') &&
              p.basename(e.path).startsWith(baseName)) {
            e.deleteSync();
          }
        }
      } catch (_) {/* 忽略：句柄未释放时删不掉 */}
      rethrow;
    }

    final totalBytes =
        volumes.fold<int>(0, (sum, v) => sum + v.bytes);

    // ── 完整性自检：包内照片数必须与计划一致 ──
    // 少一张都意味着"计划里有、包内没有"，那是数据交付事故。
    // 判定口径：`files` 是**逐张经过 `existsSync()` 过滤后**的复制清单，
    // 而 `_packEntry` 里每张都落盘（压缩产物或复制，失败即抛）——
    // 所以「复制清单长度」就等价于「包里实际照片数」，无需再遍历目录。
    if (files.length < plan.photoCount) {
      throw StateError(
        '打包中断：计划 ${plan.photoCount} 张，可读取的源文件只有 ${files.length} 张。'
        '请检查存储空间后重试。',
      );
    }

    tick(1.0, '完成');

    // ── 落库（交付记录）──
    final deliveryId = _uuid.v4();
    await _db.into(_db.deliveries).insert(
          DeliveriesCompanion.insert(
            id: deliveryId,
            projectId: projectId,
            createdAt: DateTime.now().millisecondsSinceEpoch,
            optionsJson: jsonEncode(options.toJson()),
            // DB 两个字段不迁移：zipPath 存第一卷（多卷时是卷 1），
            // bytes 存全部卷的总和。
            zipPath: Value(volumes.first.path),
            bytes: Value(totalBytes),
            itemCount: Value(plan.itemTotal),
            photoCount: Value(plan.photoCount),
          ),
        );

    return DeliveryResult(
      deliveryId: deliveryId,
      zipPath: volumes.first.path,
      folderPath: outRoot.path,
      bytes: totalBytes,
      itemCount: plan.itemTotal,
      photoCount: plan.photoCount,
      volumes: volumes,
    );
  }

  // ───────────────────────────────────────────────────────────
  // 内部
  // ───────────────────────────────────────────────────────────

  Map<String, Object?> _manifestOf(DeliveryPlan plan, ExportOptions options) =>
      {
        'generator': '集刻-采集',
        // 2 = 09-27 起包内先分「预检 / 监装」两大部分，预检再按箱号分
        'formatVersion': 2,
        'layout': 'by-part',
        // 预检内部：指定过箱号 → by-carton；一个箱号都没指定 → flat
        'precheckLayout': (options.groupByCarton && plan.hasCartonData)
            ? 'by-carton'
            : 'flat',
        'parts': {
          'precheck': plan.precheckPhotoCount,
          'supervision': plan.supervisionPhotos.length,
        },
        'summary': plan.toSummaryJson(),
        'options': options.toJson(),
        'items': [
          for (final it in plan.items)
            {
              'seq': it.seq,
              'code': it.code,
              'name': it.name,
              'spec': it.spec,
              // 交付目录用的箱号 = 整理时**人指定**的那个
              'carton': it.carton,
              // 清单里写的箱号汇总（可能没有），仅作清单信息保留
              'containerSummary': it.containerSummary,
              'state': it.state,
              'requiredPhotos': it.requiredPhotos,
              'photoCount': it.photos.length,
              'isGap': it.isGap,
              'photos': [
                for (final ph in it.photos)
                  {
                    'fileName': ph.fileName,
                    'takenAt': ph.takenAt,
                    'index': ph.indexInItem,
                  },
              ],
            },
        ],
        // 预检里没对上编码的照片：跟着箱号走、用原始文件名
        'unmatched': [
          for (final ph in plan.unmatchedPhotos)
            {
              'fileName': ph.fileName,
              'originalName': ph.originalName,
              'carton': ph.carton,
              'takenAt': ph.takenAt,
            },
        ],
        // 监装：一个文件夹，与清单无关
        'supervision': [
          for (final ph in plan.supervisionPhotos)
            {
              'fileName': ph.fileName,
              'originalName': ph.originalName,
              'takenAt': ph.takenAt,
            },
        ],
      };

  /// 在**后台 isolate** 里完成「照片落盘 + manifest + 分卷 ZIP」。
  ///
  /// 只传纯数据（绝对路径 / JSON 字符串 / bool 列表），isolate 里只做
  /// `dart:io`，不碰 db、不碰 path_provider —— 所以不需要任何 isolate 初始化。
  ///
  /// 进度：复制映射到 `[复制起点..0.90]`（压缩开 → 0.60 起，关 → 0.05 起）、
  /// 打包映射到 `[0.90..1.0]`；取消：kill isolate（半成品卷由调用方删除）。
  ///
  /// [volumeLimit] 为 0 表示不分卷（单卷 ZIP，哪怕超过微信上限 —— 关掉
  /// 「自动分卷」走网盘的场景）。
  ///
  /// [compressAttempted] = 是否跑过压缩阶段（开关开了就算，与实际有没有
  /// 压成无关）：它决定复制阶段的进度起点（0.60 或 0.05）—— **进度条必须
  /// 单调**，压缩阶段把比例推到 0.60 之后，复制就不能再从 0.05 开始。
  Future<List<DeliveryVolume>> _packIo({
    required String outRoot,
    required String zipBase,
    required String manifestPath,
    required String manifestJson,
    required List<List<String>> files,
    required List<bool> compressFlags,
    required bool compressAttempted,
    required int volumeLimit,
    required void Function(double ratio, String stage) onProgress,
    required bool Function() isCancelled,
  }) async {
    final copyFrom = compressAttempted ? 0.60 : 0.05;

    final rp = ReceivePort();
    final completer = Completer<List<DeliveryVolume>>();
    Isolate? iso;
    late final StreamSubscription<dynamic> sub;

    void finish(Object? error, List<DeliveryVolume>? value) {
      if (completer.isCompleted) return;
      sub.cancel();
      rp.close();
      if (error != null) {
        completer.completeError(error);
      } else {
        completer.complete(value!);
      }
    }

    sub = rp.listen((dynamic msg) {
      if (completer.isCompleted) return;
      if (isCancelled()) {
        iso?.kill(priority: Isolate.immediate);
        finish(const ExportCancelled(), null);
        return;
      }
      final m = msg as List<dynamic>;
      switch (m[0] as String) {
        case 'copy':
          // 复制占 [copyFrom .. 0.90]（压缩开时通常没有或只有极少量回退复制）
          final i = m[1] as int;
          final n = m[2] as int;
          onProgress(
            n == 0 ? copyFrom : copyFrom + (0.90 - copyFrom) * i / n,
            '正在整理照片 $i / $n',
          );
          break;
        case 'zip':
          // 打包占 [0.90 .. 1.00]（跨全部卷累计）
          final i = m[1] as int;
          final n = m[2] as int;
          onProgress(
            n == 0 ? 1.0 : 0.90 + 0.10 * i / n,
            '正在打包 $i / $n',
          );
          break;
        case 'done':
          final raw = m[1] as List<dynamic>;
          finish(
            null,
            [
              for (final row in raw)
                DeliveryVolume(
                  path: (row as List<dynamic>)[0] as String,
                  bytes: (row[1] as num).toInt(),
                ),
            ],
          );
          break;
        case 'error':
          finish(StateError('打包失败：${m[1]}'), null);
          break;
      }
    });

    iso = await Isolate.spawn(
      _packEntry,
      _PackReq(
        send: rp.sendPort,
        outRoot: outRoot,
        zipBase: zipBase,
        manifestPath: manifestPath,
        manifestJson: manifestJson,
        files: files,
        compressFlags: compressFlags,
        volumeLimit: volumeLimit,
      ),
    );

    try {
      return await completer.future;
    } finally {
      // 无论成功 / 失败 / 取消，都不让 isolate 滞留
      iso.kill(priority: Isolate.beforeNextEvent);
    }
  }

  /// 剩余空间。
  ///
  /// Dart 没有跨平台 statvfs。用一个 4MB 写探针判"能不能写"，
  /// 与采集期的 `storage_service` **同一口径**（§8.2：查不到就沉默）。
  /// 能写 → 返回 -1 表示"未知但不拦人"；写失败 → 0。
  Future<int> _freeBytes(String projectId) async {
    try {
      final dir = await ProjectPaths.deliveryDir(projectId);
      final probe = File(
        p.join(dir.path, '.probe_${DateTime.now().microsecondsSinceEpoch}'),
      );
      await probe.writeAsBytes(Uint8List(AppConst.storageProbeBytes), flush: true);
      await probe.delete();
      return -1;
    } catch (_) {
      return 0;
    }
  }

  int _fileSizeOr(String path, int fallback) {
    try {
      final f = File(path);
      return f.existsSync() ? f.lengthSync() : fallback;
    } catch (_) {
      return fallback;
    }
  }
}

/// 打包被用户取消。调用方应当**静默忽略**（不是错误）。
class ExportCancelled implements Exception {
  const ExportCancelled();
  @override
  String toString() => '打包已取消';
}

String _stamp(DateTime d) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${d.year}${two(d.month)}${two(d.day)}_'
      '${two(d.hour)}${two(d.minute)}';
}

/// 目录名安全化。中文保留（Android / ZIP 都支持 UTF-8 名）。
String _safe(String raw) {
  var s = raw.trim().replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
  s = s.replaceAll(RegExp(r'[ .]+$'), '');
  return s.isEmpty ? '未命名' : s;
}

/// 复制一个文件 —— **同步**，且**绝不要 await**（2026-09-30 第三轮定位）。
///
/// ── 为什么是 sync + 不能用 async ───────────────────────────────
/// 实测（bench4 + 测试内插桩）：
///   · `File.copySync` 在**任何**环境都 ~2ms/文件（无事件循环参与）。
///   · `await File.copy` / `await encoder.addFile` 在事件循环精细时 ~2ms，
///     但在**事件循环粗糙**的环境（`flutter test`/`flutter_tester`，
///     以及主 isolate 被占满时）每个 await 往返要 **~100-184ms** ——
///     1000 张照片 = 184 秒，真机上就是「打包卡死」，且**每个版本都中招**
///     （v0.10.0 的 File.copy、v0.10.1 的 addStream 都是一 await 一文件）。
///
/// 机制：慢的不是字节吞吐（`openRead` 纯读只要 1.1ms/文件），而是
/// **「发起异步 IO → 等事件循环回投完成事件」这一趟往返**。同步 API 直接
/// 在调用线程完成系统调用，**完全不经过事件循环**，因此对事件循环抖动免疫。
///
/// 结论：整条打包链路（复制 / manifest / ZIP）一律用 `*Sync`，
/// 彻底消灭「每文件一次 await」。**写这个文件时不要再引入任何 await。**
/// ──────────────────────────────────────────────────────────────
void _copyFile(File src, String dstPath) {
  src.copySync(dstPath);
}

/// 后台 isolate 的打包请求（只含可发送的纯数据）。
class _PackReq {
  const _PackReq({
    required this.send,
    required this.outRoot,
    required this.zipBase,
    required this.manifestPath,
    required this.manifestJson,
    required this.files,
    required this.compressFlags,
    required this.volumeLimit,
  });

  final SendPort send;
  final String outRoot;

  /// 卷名基底（不含扩展名）。单卷 → `<zipBase>.zip`；
  /// 多卷 → `<zipBase>_第NN卷-共MM卷.zip`。
  final String zipBase;
  final String manifestPath;
  final String manifestJson;

  /// 每项 `[源绝对路径, 目标绝对路径]`。
  final List<List<String>> files;

  /// 与 [files] 对齐：true = 压缩产物已写到 dst（跳过复制）；
  /// false = 需要复制原图（含压缩失败 / 原图直出的回退）。
  final List<bool> compressFlags;

  /// 单卷字节上限；0 = 不分卷。
  final int volumeLimit;
}

/// 后台 isolate 入口：照片落盘 → 写 manifest → 规划分卷 → 逐卷打 ZIP。
///
/// 只做 `dart:io`，不碰 db / path_provider / 平台通道 —— 因此不需要
/// `BackgroundIsolateBinaryMessenger` 之类的初始化。
///
/// ⚠️ **本函数刻意保持「零 await」**（见 `_copyFile` 的长注释）：
///    每个 await 往返在事件循环粗糙的环境要 ~100-184ms，1000 张就是 184s。
///    复制用 `copySync`、manifest 用 `writeAsStringSync`、ZIP 用同步
///    `ZipEncoder.addFile` —— 全同步，系统调用在调用线程直接完成。
///    代价：这个后台 isolate 的线程会被占满（这正是我们想要的：
///    主 isolate / UI 线程完全不受影响）。取消粒度 = 一个文件（~2ms）。
///
/// 消息协议：`['copy'|'zip', 已完成, 总数]` /
/// `['done', [[卷路径, 字节], ...]]` / `['error', message]`。
void _packEntry(_PackReq req) {
  final send = req.send;
  try {
    // 目标目录一次性建好（避免逐张 create 的重复 stat）
    final dirs = <String>{for (final f in req.files) p.dirname(f[1])};
    for (final dir in dirs) {
      Directory(dir).createSync(recursive: true);
    }

    final n = req.files.length;
    // 进度节流：最多回 ~100 条/阶段，避免 UI 端被上千次 setState 淹没
    final step = n <= 100 ? 1 : n ~/ 100;

    // ── 照片落盘 ──
    // 压缩产物原生已写好；这里只负责复制原图（含「压缩失败/原图直出」
    // 的回退）。保险起见：标记已压缩但 dst 缺失/为空的也回退复制 ——
    // 宁可多复制一张，绝不能让包里少一张。
    for (var i = 0; i < n; i++) {
      final f = req.files[i];
      final dst = File(f[1]);
      var ok = false;
      if (req.compressFlags[i]) {
        ok = dst.existsSync() && dst.lengthSync() > 0;
      }
      if (!ok) {
        _copyFile(File(f[0]), f[1]);
      }
      if ((i + 1) % step == 0 || i + 1 == n) send.send(['copy', i + 1, n]);
    }

    // manifest.json（机器可读的交付清单）—— 同步写
    final manifestFile = File(req.manifestPath)
      ..writeAsStringSync(req.manifestJson);
    final manifestBytes = manifestFile.lengthSync();

    // ── 分卷规划（纯函数，见 volume_planner.dart）──
    final sizes = [for (final f in req.files) File(f[1]).lengthSync()];
    final List<List<int>> volumeIndexes;
    if (req.volumeLimit > 0) {
      // 每卷还要装 manifest + 每文件的 ZIP 目录项开销（~512B/文件冗余）
      final budget = req.volumeLimit - manifestBytes - 16 * 1024;
      volumeIndexes = planVolumes(
        [for (final s in sizes) s + 512],
        budget > 0 ? budget : req.volumeLimit,
      );
    } else {
      volumeIndexes = [
        [for (var i = 0; i < n; i++) i],
      ];
    }
    // 零照片的交付也出包（空 zip + manifest），不能让 volumes.first 崩
    if (volumeIndexes.isEmpty) volumeIndexes.add(<int>[]);
    final volTotal = volumeIndexes.length;

    // ── 逐卷打包（同步 STORED 直存）──
    //
    // 用 `ZipEncoder` 而不是 `ZipFileEncoder`：后者的 `addFile` 是 async
    // （内部 `await fileStream.close()`），一文件一 await —— 正是慢源。
    // `ZipEncoder.addFile` 是同步的，配合 `InputFileStream`/`ArchiveFile.stream`
    // 逐文件读→写，内存与照片总量无关（现场 2-4MB 照片安全）。
    //
    // 每卷都完整包含 manifest.json：微信分卷发送后，报告员解压任何一卷
    // 都能看到「这份交付是什么」。
    final volumes = <List<Object?>>[]; // [path, bytes]
    var zipped = 0;
    for (var v = 0; v < volTotal; v++) {
      final indexes = volumeIndexes[v];
      final nn = (v + 1).toString().padLeft(2, '0');
      final mm = volTotal.toString().padLeft(2, '0');
      final zipPath = volTotal == 1
          ? '${req.zipBase}.zip'
          : '${req.zipBase}_第$nn卷-共$mm卷.zip';

      final output = OutputFileStream(zipPath);
      final encoder = ZipEncoder();
      encoder.startEncode(output, level: ZipFileEncoder.STORE);
      try {
        // ① manifest.json 打头
        final mStat = manifestFile.statSync();
        final mInput = InputFileStream(req.manifestPath);
        try {
          encoder.addFile(
            ArchiveFile.stream('manifest.json', mInput.length, mInput)
              ..compress = false
              ..lastModTime = mStat.modified.millisecondsSinceEpoch ~/ 1000
              ..mode = mStat.mode,
          );
        } finally {
          mInput.closeSync();
        }

        // ② 本卷的照片，ZIP 内用 `/` 分隔符（ZIP 规范要求，不是 `\`）
        for (final i in indexes) {
          final f = req.files[i];
          final rel = p.relative(f[1], from: req.outRoot).replaceAll(r'\', '/');
          final stat = File(f[1]).statSync();
          final input = InputFileStream(f[1]);
          try {
            encoder.addFile(
              ArchiveFile.stream(rel, input.length, input)
                ..compress = false // STORE：不压缩
                ..lastModTime = stat.modified.millisecondsSinceEpoch ~/ 1000
                ..mode = stat.mode,
            );
          } finally {
            input.closeSync();
          }
          zipped++;
          if (zipped % step == 0 || zipped == n) {
            send.send(['zip', zipped, n]);
          }
        }
      } finally {
        encoder.endEncode();
        output.closeSync();
      }
      volumes.add([zipPath, File(zipPath).lengthSync()]);
    }

    send.send(['done', volumes]);
  } catch (e) {
    send.send(['error', '$e']);
  }
}
