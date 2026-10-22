import 'dart:io';

import 'package:intl/intl.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

/// 本地文件布局（设计方案 §6.4）。
///
/// 选 App 私有外置目录的理由（§8.3）：**不需要任何存储权限**。
/// 采集期写文件、整理期读文件，全程零权限申请。
///
/// 目录结构：
/// ```
/// <files>/projects/{projectId}/
///   ├── raw/{sessionId}/20260922_085012_00001.jpg   原始文件，永不改名
///   ├── thumb/{photoId}.jpg                          256px 缩略图
///   ├── ocr/{photoId}.json                           OCR 原始结果缓存
///   ├── delivery/                                    交付包生成区（可整体清理）
///   └── project.json                                 项目元数据快照
/// ```
class ProjectPaths {
  const ProjectPaths._();

  static Directory? _cachedRoot;

  /// 根目录。Android 走外置私有目录（用户能用数据线拷出来备份），
  /// 其他平台走应用支持目录（桌面调试用）。
  static Future<Directory> filesRoot() async {
    if (_cachedRoot != null) return _cachedRoot!;

    Directory? dir;
    if (Platform.isAndroid || Platform.isIOS) {
      dir = await getExternalStorageDirectory();
    }
    dir ??= await getApplicationSupportDirectory();

    if (!await dir.exists()) await dir.create(recursive: true);
    _cachedRoot = dir;
    return dir;
  }

  /// 仅供测试注入。
  static void overrideRootForTest(Directory? dir) => _cachedRoot = dir;

  // ─────────────────────────────────────────────────────────

  static Future<Directory> projectDir(String projectId) =>
      _sub('projects/$projectId');

  static Future<Directory> rawDir(String projectId, String sessionId) =>
      _sub('projects/$projectId/raw/$sessionId');

  static Future<Directory> thumbDir(String projectId) =>
      _sub('projects/$projectId/thumb');

  static Future<Directory> ocrDir(String projectId) =>
      _sub('projects/$projectId/ocr');

  /// 交付包生成区。整目录可安全删除（§6.4 的"清理"入口）。
  static Future<Directory> deliveryDir(String projectId) =>
      _sub('projects/$projectId/delivery');

  static Future<File> manifestFile(String projectId) async => File(
        p.join((await projectDir(projectId)).path, 'project.json'),
      );

  static Future<File> ocrCacheFile(String projectId, String photoId) async =>
      File(p.join((await ocrDir(projectId)).path, '$photoId.json'));

  static Future<String> thumbPath(String projectId, String photoId) async =>
      p.join((await thumbDir(projectId)).path, '$photoId.jpg');

  /// 采集时的原始文件名：`yyyyMMdd_HHmmss_{5位序号}.jpg`
  ///
  /// 刻意**不含货品编码** —— 采集期根本不知道归属（这正是 v3.0 的核心）。
  /// 带编码的命名发生在交付阶段（生成副本时），见 `core/naming.dart`。
  static String rawFileName(DateTime takenAt, int seq) {
    final ts = DateFormat('yyyyMMdd_HHmmss').format(takenAt);
    return '${ts}_${seq.toString().padLeft(5, '0')}.jpg';
  }

  static Future<File> rawFile({
    required String projectId,
    required String sessionId,
    required DateTime takenAt,
    required int seq,
  }) async {
    final dir = await rawDir(projectId, sessionId);
    return File(p.join(dir.path, rawFileName(takenAt, seq)));
  }

  /// 相册导入的落点路径。
  ///
  /// 刻意与相机拍摄**同目录同命名规则** —— 相册照片也是"原始文件"，
  /// 享受同样的"永不改名"待遇（§6.4）。区别只在 session 的 source 标记，
  /// 那记在数据库里，不记在文件名里。
  ///
  /// 扩展名保留原样（png/heic 不强行转 jpg —— 转码是有损的，
  /// 而且会拖慢导入；交付阶段再按需处理）。
  static Future<String> importedFile({
    required String projectId,
    required String sessionId,
    required DateTime takenAt,
    required int seq,
    required String ext,
  }) async {
    final dir = await rawDir(projectId, sessionId);
    final ts = DateFormat('yyyyMMdd_HHmmss').format(takenAt);
    return p.join(dir.path, '${ts}_${seq.toString().padLeft(5, '0')}.$ext');
  }

  /// 确保项目的目录骨架存在。采集前调一次即可。
  static Future<void> ensureProject(String projectId) async {
    await projectDir(projectId);
    await thumbDir(projectId);
    await ocrDir(projectId);
    await deliveryDir(projectId);
  }

  /// 估算项目占用的空间（字节）。用于"清理"入口与存储预检。
  static Future<int> usageBytes(String projectId) async {
    final dir = await projectDir(projectId);
    if (!await dir.exists()) return 0;
    var sum = 0;
    await for (final e in dir.list(recursive: true, followLinks: false)) {
      if (e is File) {
        sum += await e.length();
      }
    }
    return sum;
  }

  /// 清理交付包生成区（最安全的一档清理：交付包已分享/已上传后可以删）。
  static Future<void> clearDeliveryArea(String projectId) async {
    final dir = await deliveryDir(projectId);
    if (await dir.exists()) {
      await dir.delete(recursive: true);
    }
  }

  static Future<Directory> _sub(String rel) async {
    final root = await filesRoot();
    final d = Directory(p.join(root.path, rel));
    if (!await d.exists()) await d.create(recursive: true);
    return d;
  }
}
