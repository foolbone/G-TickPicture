/// 导入入口的共用动作（M6.2 · 老板 2026-09-27 拍板）。
///
/// 采集的三个入口现在**并排在采集 Tab 上**（进入全屏相机 / 从相册导入 /
/// 微信聊天记录导入），全屏采集页只负责拍。所以导入逻辑从采集页里抽出来，
/// 成为任何页面都能调的一段动作 —— 采集 Tab 用它，将来别处也能用。
///
/// ⚠️ 这些函数**刻意留在 UI 层**，不放进 CaptureService：
/// 它们需要 BuildContext（拉系统选择器、弹提示），而服务层不持有 context
/// —— 「服务层禁弹窗」因此是结构保证，不是靠自觉（§5.2）。
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../app/providers.dart';
import '../../domain/model/native_gallery_photo.dart';
import 'gallery_picker_page.dart';

/// 相册权限。
///
/// Android 13+ 用 READ_MEDIA_IMAGES；8~12 用 READ_EXTERNAL_STORAGE。
/// permission_handler 会自动按版本挑对的权限名。
///
/// 最终以**原生状态**为准（2026-09-29 真机空态教训）：Android 14 的
/// 「仅允许选中的照片」部分授权下，permission_handler 可能报未授予，
/// 但原生按 VISUAL_USER_SELECTED 算已授权 —— MediaStore 实际执行的
/// 就是那个口径，让它说了算。
///
/// 按需申请：用户不点导入入口就永远不会触发（§8.3）。
Future<bool> requestGalleryPermission(WidgetRef ref) async {
  if (!Platform.isAndroid && !Platform.isIOS) return true;
  final photos = await Permission.photos.request();
  if (photos.isGranted) return true;
  // Android 12 及以下：Permission.photos 可能返回 restricted/denied 但
  // storage 是可授权的（因为 READ_MEDIA_IMAGES 在那个版本不存在）。
  if (Platform.isAndroid) {
    final s = await Permission.storage.request();
    if (s.isGranted) return true;
    // 部分授权（Android 14「选中的照片」）：原生口径兜底。
    final st = await ref.read(nativeGalleryServiceProvider).galleryStatus();
    if (st.granted) return true;
  }
  return false;
}

/// 执行一批导入（相册 / 微信共用的尾段）。
///
/// 走的是与相机拍照**完全不同**的入口：不碰相机、不碰预览，
/// 但落盘路径一致（EXIF 时间戳 / 连续 seq / 缩略图 / source=album 批次），
/// 所以导入的照片在整理页与拍出来的照片没有区别。
///
/// [takenAts] 与 [paths] 按下标对齐的拍摄时刻覆盖值（见
/// [CaptureService.importFromGallery]）—— 微信导入传 MediaStore 的
/// DATE_TAKEN，相册导入传按「文件名+大小」回查媒体库的时间（2026-09-29；
/// 不回查，没有 EXIF 的图落库全是导入时刻，时序分组永远「不可信」）。
///
/// 少于这个张数就不弹进度框（几张而已，弹框比等待更烦人）。
const int _progressDialogThreshold = 8;

/// 返回成功导入的照片 id（长度 = 张数）。
Future<List<String>> importPaths(
  BuildContext context,
  WidgetRef ref,
  String projectId,
  List<String> paths, {
  required String note,
  List<DateTime?>? takenAts,
  String? intoGroupId,
  String? groupLabel,
}) async {
  final messenger = ScaffoldMessenger.of(context);
  final svc = ref.read(captureServiceProvider);

  // 进度框（2026-09-29 性能排查）：耗时不变，但"系统还在动"这件事必须
  // 看得见 —— 现场选上百张时那几十秒，没有进度就是"点了没反应"。
  final progress = ValueNotifier<int>(0);
  BuildContext? dialogCtx;
  final showDialog_ = paths.length >= _progressDialogThreshold;
  if (showDialog_) {
    unawaited(showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        dialogCtx = ctx;
        return _ImportProgressDialog(
          total: paths.length,
          progress: progress,
          title: '正在导入',
        );
      },
    ));
  }

  final ids = await svc.importFromGallery(
    projectId,
    paths,
    note: note,
    takenAts: takenAts,
    onProgress: (done, _) => progress.value = done,
  );
  final n = ids.length;

  final dc = dialogCtx;
  if (dc != null && dc.mounted) Navigator.of(dc).pop();
  progress.dispose();

  // 组内补照（2026-09-30）：导入完成立刻挂进目标组。
  // 挂组走 OrganizeRepository（分组是整理期的地盘）；移动语义会顺带
  // 收回被自动分组抢走的照片，晚几毫秒调也不出错。
  if (ids.isNotEmpty && intoGroupId != null) {
    try {
      await ref
          .read(organizeRepositoryProvider)
          .attachPhotosToGroup(projectId, intoGroupId, ids);
      ref.invalidate(openGroupsProvider(projectId));
    } catch (e) {
      if (!context.mounted) return ids;
      // 提示必须说清「照片没丢」+ 下一步（2026-10-08）：原来直接把
      // Bad state 抛给老板，看不出照片去了哪。
      messenger.showSnackBar(SnackBar(
        content: Text(
          '已导入 $n 张，但目标组在导入期间被自动整理调整了，照片没有丢'
          ' —— 它们已按批次自动成组，如需并回，请在照片页长按组卡片拖拽合并。',
        ),
        duration: const Duration(seconds: 5),
      ));
      return ids;
    }
  }

  // 计数与"最近拍摄"都是流，写库后本会自动推新值；
  // 但 invalidate 一次能确保"我点了导入"这个动作有确定的反馈，
  // 也覆盖「导入的图时间戳很旧、排不进最近 5 张」的情况。
  ref.invalidate(projectPhotoCountProvider(projectId));
  ref.invalidate(latestThumbsProvider(projectId));

  // 查重报告要重算（2026-10-04）：导入是最容易产生重复的入口
  // （同一张图被选了两次）。不刷新的话用户导完看不到橙色横幅，
  // 要等下次进页面才发现 —— 那就等于没提示。
  ref.invalidate(duplicateReportProvider(projectId));

  // 主动补齐刚导入照片的缩略图（2026-09-30「从相册导入后组内缩略图
  // 显示不出来」根因修复）：
  // 整理页 initState 的 backfill 在 IndexedStack 下进项目时就跑完了，
  // 用户点「从相册导入」完成后再也不会触发；新导入的照片 thumbPath 还是
  // null，UI 显示空图标 —— 用户看到的就是"缩略图显示不出来"。
  // 这里**后台**补一轮（不阻塞 SnackBar 反馈），完成后 invalidate 整理页
  // 三个流，让组内缩略图立刻可见。
  // 用 unawaited 而非 await：①不让用户在 progress dialog 关闭后等几秒
  // 看到 SnackBar；②这里不在测试场景（测试调 svc.importFromGallery 不
  // 调本函数），无 path_provider channel race 风险（见 camera_capture_
  // service.dart importFromGallery 内的说明）。
  // try/catch 兜底：widget dispose 后 ref.invalidate 会抛 StateError，
  // 吞掉即可（缩略图只影响观感）。
  if (n > 0) {
    unawaited(() async {
      try {
        final filled = await svc.backfillThumbnails(projectId);
        if (filled > 0) {
          ref.invalidate(openGroupsProvider(projectId));
          ref.invalidate(assignedGroupsProvider(projectId));
          ref.invalidate(supervisionPhotosProvider(projectId));
        }
      } catch (_) {/* 缩略图不影响导入计数，静默 */}
    }());
  }

  if (!context.mounted) return ids;
  messenger.showSnackBar(
    SnackBar(
      content: Text(
        n > 0
            ? (intoGroupId != null
                ? '已把 $n 张照片加入${groupLabel ?? '所选组'}。'
                : '已导入 $n 张，它们会在「照片」页出现。')
            : '没有导入成功 —— 可能这些图片已被删除或无法读取。',
      ),
      duration: const Duration(seconds: 3),
    ),
  );
  return ids;
}

/// 「从相册导入」。
///
/// 权限 → 进自建选择器（连选 / 时间定位 / 记忆位置 / 大图预览）→ 原生把
/// 选中原图复制进临时目录 → 带真实拍摄时刻导入 → 提示。全程在 UI 层，
/// 服务层不参与决策（服务层禁弹窗禁 context，见文件头）。
///
/// ⚠️ 导入路径**不写系统相册**：相册 / 微信导入的照片本来就在手机里，
/// 再抄进「集刻-采集/<项目>」就是重复件（老板 09-29 拍板 + 09-29 去重）。
/// 这里传的是原生直读的 DATE_TAKEN，时序分组也能正确归组。
/// [intoGroupId] 非空 = 组内补照模式：导入完成后照片直接挂进该组
/// （见 [importPaths]）。[groupLabel] 只用于提示文案（如「第 3 组」）。
Future<void> runGalleryImport(
  BuildContext context,
  WidgetRef ref,
  String projectId, {
  String? intoGroupId,
  String? groupLabel,
}) async {
  final ok = await requestGalleryPermission(ref);
  if (!ok) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('未授予相册访问权限，无法导入已有照片。'),
        duration: Duration(seconds: 3),
      ),
    );
    return;
  }

  if (!context.mounted) return;
  final picked = await Navigator.of(context).push<List<NativeGalleryReadResult>>(
    MaterialPageRoute(
      builder: (_) => GalleryPickerPage(projectId: projectId),
    ),
  );
  if (picked == null || picked.isEmpty) return;
  if (!context.mounted) return;

  await importPaths(
    context,
    ref,
    projectId,
    [for (final p in picked) p.tempPath],
    note: intoGroupId == null
        ? '相册导入 ${picked.length} 张'
        : '组内补照 ${picked.length} 张',
    takenAts: [for (final p in picked) p.dateTaken],
    intoGroupId: intoGroupId,
    groupLabel: groupLabel,
  );

  // 导入完成即清临时副本（已复制进项目私有目录，缓存不再需要）
  await ref.read(nativeGalleryServiceProvider).cleanupTemp();
}

/// 导入进度框。
///
/// 刻意做成**不可取消**：中途取消会让项目里留下半批照片（一批一组的语义
/// 下那就是一个残缺的组），与其事后收拾，不如让它跑完。
/// 张数不多时压根不弹（见 [_progressDialogThreshold]）。
class _ImportProgressDialog extends StatelessWidget {
  const _ImportProgressDialog({
    required this.total,
    required this.progress,
    required this.title,
  });

  final int total;
  final ValueNotifier<int> progress;
  final String title;

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: AlertDialog(
        title: Text(title),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ValueListenableBuilder<int>(
              valueListenable: progress,
              builder: (_, done, __) {
                final pct = total == 0 ? 0.0 : done / total;
                return Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    LinearProgressIndicator(value: pct),
                    const SizedBox(height: 10),
                    Text('$done / $total 张'),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

// 「从微信聊天记录导入」已整体下线（老板 2026-09-29 拍板）。
//
// 下线原因：安卓分区存储下，**只有**微信里"保存"过、已进公共媒体库的图才
// 读得到；聊天记录里的原图缓存系统层面不可见（本 App 不申请全盘权限）。
// 现场实际使用时基本读不到东西 —— 一个看起来能用、实际拿不到图的入口，
// 比没有这个入口更糟（用户会以为"导入失败"是 App 坏了）。
//
// 它带的 `takenAts` 覆盖能力（用 MediaStore DATE_TAKEN 当落库时间）被
// 相册导入继承下来了，不是白写 —— 见 [importPaths] 的注释。
