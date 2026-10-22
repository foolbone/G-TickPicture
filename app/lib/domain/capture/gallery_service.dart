import 'dart:io';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/constants.dart';
import '../../core/logger.dart';
import '../model/gallery_photo.dart';

/// 「照片存入手机相册」的服务（P4 · 老板 2026-09-24 诉求）。
///
/// ═══════════════════════════════════════════════════════════════
/// 为什么要往相册里写
///   现场预检员的真实动线里有一小段是 app 管不到的：他要把照片**发给别人**
///   （同事、客户、微信群），而在微信里选图最顺手的入口是系统相册。
///   App 私有目录里的原图他翻不到 —— 于是就会出现「用手机相机再拍一遍」
///   这种荒唐动作。抄一份到相册，是让 App 融进他已有的习惯。
///
/// ═══════════════════════════════════════════════════════════════
/// 五条纪律（改这个类之前先读）
///
///  1. **复制，不移动**。App 私有副本是交付源 —— 交付包、OCR、缩略图、
///     重跑全都依赖它。原件绝不能交给 MediaStore 托管。
///  2. **失败一律静默**。这是锦上添花的能力，不是主路径 ——
///     写不进相册，照片照样在 App 里能看、能整理、能导出。
///     所以本文件里没有一个 throw 逃出去，全部返回结果对象 / reason。
///     （§8.2「查不到 ≠ 不足」的同款纪律：做不到就别打扰正在拍照的人。）
///  3. **默认开**。老板提的是硬需求。开关留着是为了「存储紧张的人」，
///     不是为了让默认值变成关。
///  4. **主路径一步不少**：无论开关开不开，采集期的主路径
///     （快门 → 落盘 → 入库）完全相同，相册写入排在 `_shoot` 之后异步补。
///  5. **幂等去重做在原生写入点**。同一相册目录下同名文件已在 →
///     原生跳过并返回 saved=false —— **跳过不是失败**。这样「拍照自动存」
///     和「概览页手动补存」无论谁先谁后、重复多少次，相册里都只有一份
///     （老板 09-24 反馈：手动补存会重复保存照片）。
///  6. **只有 App 内拍的照片才进相册**（老板 09-29 拍板）。相册 / 微信
///     导入的照片本来就在手机里，再抄一份进 `集刻-采集/<项目>` 就是相册
///     里的重复件。所以「概览页补存」的输入必须是**相机来源**的照片
///     （`CaptureRepository.capturedPhotos`），不是项目下的全部照片。
class GalleryService {
  GalleryService({
    SharedPreferences? prefs,
    bool? platformIsAndroidForTest,
  })  : _prefsOverride = prefs,
        _platformIsAndroidForTest = platformIsAndroidForTest;

  static const MethodChannel _channel = MethodChannel('gtick/gallery');

  static const _kEnabled = 'capture.save_to_gallery';

  final SharedPreferences? _prefsOverride;
  SharedPreferences? _prefsCache;

  Future<SharedPreferences> get _prefs async =>
      _prefsCache ??= _prefsOverride ?? await SharedPreferences.getInstance();

  /// 平台注入点：桌面单测里 `Platform.isAndroid` 恒为 false，
  /// 会提前静默降级 —— 单测传 true 才能走到 mock 通道。
  /// null（生产）= 用真实平台判断。
  final bool? _platformIsAndroidForTest;

  bool get _isAndroid => _platformIsAndroidForTest ?? Platform.isAndroid;

  /// 本进程中已经确认过的写入条件。null = 还没问过原生侧。
  ///
  /// 缓存它的理由：连拍时每张都要存相册，不能每张都来回一次通道问权限。
  bool? _granted;
  String? _lastError;

  /// 最近一次失败的原文。UI 可以展示 —— 但**不弹窗**。
  String? get lastError => _lastError;

  // ─────────────────────────────────────────────────────────
  // 开关
  // ─────────────────────────────────────────────────────────

  /// 是否「拍照同时存入手机相册」。**默认 true** —— 这是老板的硬需求。
  Future<bool> get isEnabled async => (await _prefs).getBool(_kEnabled) ?? true;

  Future<void> setEnabled(bool value) async {
    await (await _prefs).setBool(_kEnabled, value);
  }

  // ─────────────────────────────────────────────────────────
  // 写入
  // ─────────────────────────────────────────────────────────

  /// 把 [srcPath] 复制一份到相册的 `{AppConst.galleryRootAlbum}/{album}`。
  ///
  /// 返回三档结果：saved=新写入 / skipped=已在相册里（幂等跳过，不算失败）/
  /// failed=真失败（原因在 [lastError]）。**不抛、不弹窗**（纪律 2）。
  Future<GallerySaveResult> save({
    required String srcPath,
    required String album,
    String? displayName,
    DateTime? takenAt,
  }) {
    return saveAll(
      [
        GalleryPhoto(
          srcPath: srcPath,
          displayName: displayName ?? p.basename(srcPath),
          takenAt: takenAt,
        ),
      ],
      album: album,
    );
  }

  /// 批量补存（把项目里已有的照片抄进相册）。
  ///
  /// 逐张**串行**而不是并发：MediaStore 的 insert + write 在系统侧是
  /// 全局有序的，几百个并发 insert 会让部分 ROM 的媒体扫描掉队，
  /// 结果是「照片存进去了、相册里看不到」且没有任何报错。
  /// 串行 + 计数是唯一能向用户说清「存了多少、跳了多少、剩多少」的做法。
  Future<GallerySaveResult> saveAll(
    List<GalleryPhoto> photos, {
    required String album,
  }) async {
    if (photos.isEmpty) {
      return const GallerySaveResult(saved: 0, failed: 0);
    }
    if (!_isAndroid) {
      // 非 Android 未接原生实现 —— 静默降级（纪律 2）。
      return const GallerySaveResult(
        saved: 0,
        failed: 0,
        reason: '仅 Android 支持存入相册',
      );
    }

    if (!await ensurePermission()) {
      return GallerySaveResult(
        saved: 0,
        failed: photos.length,
        reason: _lastError ?? '未获得相册写入权限',
      );
    }

    final folder = safeFolderName(album);
    var saved = 0;
    var skipped = 0;
    var failed = 0;
    String? reason;

    for (final photo in photos) {
      try {
        final res = await _channel.invokeMethod<Object?>('savePhoto', {
          'path': photo.srcPath,
          'album': folder,
          'displayName': photo.displayName,
          'mime': _mimeOf(photo.displayName),
          if (photo.takenAt != null)
            'takenAtMs': photo.takenAt!.millisecondsSinceEpoch,
        });
        // 原生契约：Map{saved: bool, uri: String}。saved=false 不是失败 ——
        // 那是「同名文件已在相册里」的幂等跳过（纪律 5）。
        // 只有 PlatformException 算失败。
        if (_savedFlagOf(res)) {
          saved++;
        } else {
          skipped++;
        }
      } on PlatformException catch (e) {
        failed++;
        reason = '${e.code}：${e.message ?? ''}'.trim();
        Log.w('Gallery', 'save failed: ${photo.srcPath} :: $reason');
      } catch (e) {
        failed++;
        reason = '$e';
        Log.w('Gallery', 'save failed: ${photo.srcPath} :: $e');
      }
    }

    if (failed > 0) _lastError = reason;
    return GallerySaveResult(
      saved: saved,
      skipped: skipped,
      failed: failed,
      reason: reason,
    );
  }

  /// 解析原生 savePhoto 的返回：
  ///  · 新契约 `Map{saved, uri}` —— saved==true 即本次新写入，false=跳过；
  ///  · 防御旧契约（直接回 uri 字符串）→ 视为已写入。
  static bool _savedFlagOf(Object? res) {
    if (res is Map) return res['saved'] == true;
    return res != null;
  }

  /// 删除一张照片在相册里的**镜像**（2026-10-10 v0.19.0「拍后回看·重拍」）。
  ///
  /// 与 [save] 严格对偶：按 `相册/{album}/{basename(srcPath)}` 定位，
  /// 原生只删本 App 自己插入的条目。返回是否真的删掉了。
  ///
  /// **不抛、不弹窗**（纪律 2）：删不到（本来就没存进去 / 已被手动清 /
  /// ROM 拒绝）就返回 false，绝不能让"重拍"这个主动作被镜像删除卡住
  /// —— 相册多一张废图是可接受的代价。
  Future<bool> deleteMirror({
    required String srcPath,
    required String album,
  }) async {
    if (!_isAndroid) return false;
    try {
      final res = await _channel.invokeMethod<Object?>('deletePhoto', {
        'album': safeFolderName(album),
        'displayName': p.basename(srcPath),
      });
      return res is Map && res['deleted'] == true;
    } catch (e) {
      Log.w('Gallery', 'delete mirror failed: $srcPath :: $e');
      return false;
    }
  }

  /// 确认当前能否写入相册。需要权限且尚未授权时，申请一次。
  ///
  /// Android 10+ 不需要任何权限（分区存储下 App 插自己的图是免权操作），
  /// 只有 8/9 才要 [Permission.storage]。所以这里是**询问在前、申请在后**：
  /// 不让新机型承担一次毫无意义的权限提问。
  Future<bool> ensurePermission() async {
    if (_granted != null) return _granted!;

    try {
      final status = await _channel.invokeMapMethod<String, dynamic>('status');
      final needs = status?['needsPermission'] == true;
      final granted = status?['granted'] == true;
      if (!needs || granted) {
        _granted = true;
        return true;
      }
    } on PlatformException catch (e) {
      // 通道不可用（原生没挂 / 非 Android）→ 静默降级
      _lastError = '相册桥不可用：${e.code}';
      Log.w('Gallery', 'status probe failed: ${e.code}');
      _granted = false;
      return false;
    }

    // Android 8/9：申请写存储权限。只问一次 —— 拒绝了就不再打扰，
    // 照片留在 App 里照样可用、可导出。
    try {
      final result = await Permission.storage.request();
      // ⚠️ 先落局部变量再判：实例字段（bool?）不参与空安全提升，
      //    直接 `if (!_granted)` 是编译错误。
      final granted = result.isGranted;
      _granted = granted;
      if (!granted) {
        _lastError = '未允许存储空间权限，暂时无法存入相册';
      }
    } catch (e) {
      _granted = false;
      _lastError = '权限申请失败：$e';
    }
    return _granted!;
  }

  // ─────────────────────────────────────────────────────────
  // 工具
  // ─────────────────────────────────────────────────────────

  /// 相册文件夹名 —— 项目名里可能带 `\ / : * ? " < > |`，
  /// 这些字符在 FAT32 / MediaStore 上都是非法的。
  ///
  /// 清理后再截 40 字：相册目录名过长时部分 ROM 的媒体扫描会
  /// 直接忽略整个目录（照片存进去了但相册看不到）。
  static String safeFolderName(String name) {
    var s = name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_').trim();
    // 首尾的点是隐藏文件语义（Linux），相册会看不见
    s = s.replaceAll(RegExp(r'^\.+'), '').trim();
    if (s.isEmpty) return AppConst.galleryRootAlbum;
    if (s.length > 40) s = s.substring(0, 40).trim();
    return s;
  }

  /// 相册里最终的路径（UI 文案用）。
  static String displayPath(String album) =>
      '相册 / ${AppConst.galleryRootAlbum} / ${safeFolderName(album)}';

  static String _mimeOf(String fileName) {
    final ext = p.extension(fileName).toLowerCase();
    switch (ext) {
      case '.png':
        return 'image/png';
      case '.webp':
        return 'image/webp';
      case '.heic':
        return 'image/heic';
      case '.heif':
        return 'image/heif';
      default:
        return 'image/jpeg';
    }
  }
}
