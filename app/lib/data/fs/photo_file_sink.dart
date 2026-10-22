import 'dart:io';
import 'dart:isolate';
import 'dart:typed_data';

import 'package:image/image.dart' as img;
import 'package:path/path.dart' as p;

import '../../core/constants.dart';
import '../../core/logger.dart';
import '../../core/perf_bridge.dart';
import 'project_paths.dart';

/// 一次落盘的结果。**这是主 isolate 能看到的全部信息** ——
/// 尺寸、字节数、缩略图路径都在这里，主线程不需要再读一次图。
class WriteResult {
  const WriteResult({
    required this.filePath,
    required this.thumbPath,
    required this.bytes,
    required this.width,
    required this.height,
  });

  final String filePath;
  final String? thumbPath;
  final int bytes;
  final int? width;
  final int? height;
}

/// 缩略图生成的入参（必须是可跨 isolate 传递的简单值）。
class ThumbSpec {
  const ThumbSpec({
    required this.srcPath,
    required this.dstPath,
    required this.longEdge,
  });

  final String srcPath;
  final String dstPath;
  final int longEdge;
}

/// 缩略图生成结果（isolate 内部用）。
class _ThumbResult {
  const _ThumbResult(this.width, this.height, {this.luma});
  final int width;
  final int height;
  final int? luma;
}

/// 缩略图生成的**对外**结果：尺寸 + 平均亮度。
///
/// [luma] 的用途只有一处 —— 判断「刚拍的这张光线够不够」（2026-10-10
/// 拍照体验对标）。它是**统计量**，不是画面：任何情况下都不许拿它去
/// 改原图一个像素（取证原始性）。
class ThumbOutcome {
  const ThumbOutcome({
    required this.width,
    required this.height,
    this.luma,
  });

  final int width;
  final int height;

  /// 平均亮度 0~255；null = 没量到（解码失败 / 原生老版本）。
  /// **没量到就当不知道，绝不填默认值**（纪律 17）。
  final int? luma;
}

/// 照片落盘 / 缩略图生成（设计方案 §8.1 性能目标）。
///
/// 三条设计约束：
///  1. **原图直写文件，不改名、不转码** —— §6.4 的"原始文件永不改名"。
///     相机已经给了 JPEG，我们不再二次编码（省 CPU、省电、无画质损失）。
///  2. **缩略图走独立 isolate，且降采样解码** ——
///     用 `decodeImage` 整图解码一张 4000×3000 的 JPEG 要 200~400ms 且
///     峰值内存 50MB+；做成 1600 张就是灾难（R1b）。
///     这里用 `JpegDecoder` 的 `getInfo()` 先读尺寸，再按目标比例
///     重设尺寸后解码，峰值内存压到几 MB。
///  3. **缩略图失败不算失败** —— 它只影响列表观感，不能影响照片入库。
class PhotoFileSink {
  const PhotoFileSink._();

  /// 把内存里的 JPEG 字节写成原始文件。
  ///
  /// 返回写入后的 [WriteResult]（缩略图路径已算好但**还没生成**，
  /// 生成由 [makeThumbnail] 单独完成 —— 这样"快门到可再次拍摄"的
  /// 400ms 预算里不包含缩略图）。
  static Future<WriteResult> writeRaw({
    required String projectId,
    required String sessionId,
    required DateTime takenAt,
    required int seq,
    required Uint8List bytes,
  }) async {
    final dir = await ProjectPaths.rawDir(projectId, sessionId);
    final path = p.join(dir.path, ProjectPaths.rawFileName(takenAt, seq));

    // ⚠️ 写入放**后台 isolate**（2026-10-09 拍照链路体检）：一张 4:3 原图
    // 4~8MB，`writeAsBytes + flush` 留在主 isolate 会把 UI 卡住几十到几百
    // 毫秒 —— 现场表现是"每按一下快门顿一下"，连拍时尤其明显。跨 isolate
    // 传 Uint8List 会拷贝一次（8MB 约几 ms），远比主线程同步写盘划算；
    // 这也是铁律「批量文件 IO 同步 + 后台 isolate」的落点。
    // flush: true —— 断电/杀进程后文件仍是完整可读的（指标 11）。
    final actual = await Isolate.run(() {
      final f = File(path);
      f.writeAsBytesSync(bytes, flush: true);
      return f.lengthSync();
    });

    return WriteResult(
      filePath: path,
      thumbPath: await ProjectPaths.thumbPath(projectId, _stem(path)),
      bytes: actual,
      width: null,
      height: null,
    );
  }

  /// 读取已有文件的尺寸（不落盘，只解码头部）。
  ///
  /// ⚠️ 这是**低优先级**动作：只在整理阶段做（采集期禁止读图，见 §5.2）。
  static Future<(int, int)?> readSize(String filePath) async {
    try {
      // startDecode 是同步的 —— 它只读到足够解析出尺寸就返回。
      final info = img.JpegDecoder().startDecode(
        await File(filePath).readAsBytes(),
      );
      if (info == null) return null;
      return (info.width, info.height);
    } catch (e) {
      Log.w('PhotoFileSink', 'readSize failed: $filePath :: $e');
      return null;
    }
  }

  /// 生成缩略图。**失败返回 null，绝不抛**（缩略图不是关键路径）。
  ///
  /// [srcPath] 原图；[dstPath] 目标 .jpg；[longEdge] 长边像素。
  ///
  /// 路线（2026-09-29 全 App 性能排查）：
  ///   ① **优先走原生** —— BitmapFactory 的 `inSampleSize` 在解码阶段就
  ///      降采样（配 RGB_565，像素缓冲 1/8），且不需要把整份字节搬进 Dart
  ///      堆。实测一张 12MP 的图：原生 ~40ms / Dart isolate ~300ms + 几十 MB。
  ///   ② **原生失败才回退 isolate** —— HEIC / 通道异常 / 桌面调试环境。
  ///      缩略图只影响列表观感，两条路都失败就返回 null，绝不拖住入库。
  static Future<ThumbOutcome?> makeThumbnail({
    required String srcPath,
    required String dstPath,
    int longEdge = AppConst.thumbLongEdge,
  }) async {
    final r = await makeThumbnails([
      ThumbSpec(srcPath: srcPath, dstPath: dstPath, longEdge: longEdge),
    ]);
    return r.isEmpty ? null : r.first;
  }

  /// 批量生成。**一次原生通道往返处理整批**（原生内部串行解码 ——
  /// 并发解码 N 张大图会让低配机内存峰值直接翻倍）。
  ///
  /// 返回与 [jobs] 等长、按下标对齐的结果；`null` = 该张失败。
  ///
  /// ⚠️ **原生报成功也要验货**（2026-09-29 真机"整理页缩略图全空"的第一层
  /// 防线）：`ok=true` 只代表原生没抛异常，不代表文件真的落盘了。`compress`
  /// 返回 false、目录创建失败等情况下都会出现"报成功但没文件" —— 一旦把这
  /// 种路径写进库，列表就会拿着一个永远打不开的路径去显示，看起来就是
  /// "缩略图全都显示不出来"。所以这里必须 `stat` 一次确认非空。
  static Future<List<ThumbOutcome?>> makeThumbnails(List<ThumbSpec> jobs) async {
    if (jobs.isEmpty) return const [];

    final out = List<ThumbOutcome?>.filled(jobs.length, null);
    final retry = <int>[];

    try {
      final native = await PerfBridge.makeThumbs([
        for (final j in jobs)
          ThumbJob(
            srcPath: j.srcPath,
            dstPath: j.dstPath,
            longEdge: j.longEdge,
            quality: AppConst.thumbQuality,
          ),
      ]);
      if (native.length == jobs.length) {
        for (var i = 0; i < jobs.length; i++) {
          final r = native[i];
          if (r.ok && r.width > 0 && r.height > 0 && _nonEmpty(jobs[i].dstPath)) {
            out[i] = ThumbOutcome(width: r.width, height: r.height, luma: r.luma);
          } else {
            retry.add(i);
          }
        }
      } else {
        retry.addAll(List.generate(jobs.length, (i) => i));
      }
    } catch (e) {
      // 通道异常不算异常 —— 全部回退 isolate 即可
      Log.d('PhotoFileSink', 'native thumbs unavailable: $e');
      retry
        ..clear()
        ..addAll(List.generate(jobs.length, (i) => i));
    }

    for (final i in retry) {
      out[i] = await _viaIsolate(jobs[i]);
    }
    return out;
  }

  /// 目标文件存在且非空（验货用；不在 build 路径上，同步 stat 是可接受的）。
  static bool _nonEmpty(String path) {
    try {
      return File(path).statSync().size > 0;
    } catch (_) {
      return false;
    }
  }

  /// Dart isolate 回退路径（原生不可用 / 该张失败）。
  static Future<ThumbOutcome?> _viaIsolate(ThumbSpec job) async {
    try {
      final r = await Isolate.run(() => _generate(job));
      // 0×0 = 解码失败（`_generate` 的失败返回值）。返回 null 而不是把
      // 0 写进库 —— 否则列表会拿一个"存在但为空"的缩略图路径去显示。
      if (r.width <= 0 || r.height <= 0) return null;
      return ThumbOutcome(width: r.width, height: r.height, luma: r.luma);
    } catch (e) {
      Log.w('PhotoFileSink', 'thumbnail failed: ${job.srcPath} :: $e');
      return null;
    }
  }

  /// isolate 内的实际生成逻辑。
  ///
  /// 关键点：**先 getInfo 拿尺寸，再按比例指定目标尺寸解码**，
  /// 而不是先整图解码再缩放。
  static _ThumbResult _generate(ThumbSpec job) {
    final src = File(job.srcPath);
    if (!src.existsSync()) return const _ThumbResult(0, 0);

    final bytes = src.readAsBytesSync();

    // ① 只解析头部，拿到原始尺寸（不分配像素缓冲）
    final probe = img.JpegDecoder().startDecode(bytes);
    if (probe == null) return const _ThumbResult(0, 0);
    final ow = probe.width;
    final oh = probe.height;
    if (ow <= 0 || oh <= 0) return const _ThumbResult(0, 0);

    // ② 算目标尺寸（长边 = longEdge，等比缩放，只缩不放）
    final longer = ow > oh ? ow : oh;
    final scale = longer > job.longEdge ? job.longEdge / longer : 1.0;
    final tw = (ow * scale).round().clamp(1, ow);
    final th = (oh * scale).round().clamp(1, oh);

    // ③ 回退路径才走这里：image 包**没有**解码期降采样（JpegDecoder 只能
    //    整图解码再 resize），所以这一步会真的开出全尺寸像素缓冲 ——
    //    正常路径已被原生 inSampleSize 接管（见 [makeThumbnail]），
    //    只有 HEIC / 通道不可用 / 桌面调试才会落到这儿。
    final decoded = img.JpegDecoder().decode(bytes);
    if (decoded == null) return const _ThumbResult(0, 0);

    final thumb = img.copyResize(
      decoded,
      width: tw,
      height: th,
      interpolation: img.Interpolation.average,
    );

    final dir = Directory(p.dirname(job.dstPath));
    if (!dir.existsSync()) dir.createSync(recursive: true);

    File(job.dstPath).writeAsBytesSync(
      img.encodeJpg(thumb, quality: AppConst.thumbQuality),
      flush: true,
    );

    // ④ 亮度顺手算（2026-10-10「弱光提示」）：与原生 avgLuma 同口径
    //    （Rec.601），此刻像素已在内存里，遍历一张 ≤256 长边的缩略图是
    //    毫秒级；若放到 Dart 主线程事后量，就得**再解码一次**整图。
    //    没量到（理论上不会）就返回 null —— 上层按"不知道"处理，不猜。
    return _ThumbResult(tw, th, luma: _avgLuma(thumb));
  }

  /// Dart 侧平均亮度（0~255，Rec.601）—— 原生 [PerfBridge] 同款口径。
  ///
  /// 只对**缩略图**用：调用点保证长边 ≤ thumbLongEdge（256），全图遍历
  /// 约几万像素。与原生一致：失败/空图返回 null，绝不猜一个数。
  static int? _avgLuma(img.Image thumb) {
    try {
      var sum = 0;
      var n = 0;
      for (final px in thumb) {
        sum += (px.r * 299 + px.g * 587 + px.b * 114) ~/ 1000;
        n++;
      }
      if (n == 0) return null;
      return sum ~/ n;
    } catch (e) {
      Log.w('PhotoFileSink', 'avgLuma failed: $e');
      return null;
    }
  }

  /// 缩略图缓存是否还在。
  static Future<bool> thumbnailExists(String projectId, String photoId) async {
    final f = File(await ProjectPaths.thumbPath(projectId, photoId));
    return f.exists();
  }

  /// 删除某项目的全部缩略图缓存（§6.4 的清理入口之一，可再生成）。
  static Future<int> clearThumbnails(String projectId) async {
    final dir = await ProjectPaths.thumbDir(projectId);
    if (!await dir.exists()) return 0;
    var n = 0;
    await for (final e in dir.list()) {
      if (e is File) {
        await e.delete();
        n++;
      }
    }
    return n;
  }

  static String _stem(String path) {
    final name = p.basename(path);
    final dot = name.lastIndexOf('.');
    return dot <= 0 ? name : name.substring(0, dot);
  }
}
