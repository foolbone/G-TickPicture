import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../app/theme.dart';
import '../../domain/model/open_group.dart';
import '../widgets/zoomable_image.dart';

/// P4 · 诉求 2：整理页的照片全屏查看。
///
/// 为什么单独一页而不是在卡片里放大：
///   列表 / 胶片条里的每一格只能读 **256px 缩略图** —— 一天上千张，
///   在列表里解码原图会把内存和 UI 线程一起拖死（R1b 的教训，见
///   `GroupPhotoThumb.originalPath` 的注释）。但"想看清编码上的小字"
///   是真实需求，缩略图的确不够。两者不冲突，只差一个**隔离开的场景**：
///   全屏、一次只看一张，这时解码原图完全可接受。
///
/// 交互（对齐系统相册的习惯，现场人员不用学）：
///   · 双指缩放 / 拖动平移（InteractiveViewer，双击复位）
///   · 左右滑动看组内上一张 / 下一张（PageView）
///   · 底部小字告诉人"这是第几张 / 共几张、哪个组、几点拍的"
///
/// 返回时把当前索引带回去，让列表滚动到人最后看的那一张 ——
/// 看完第 7 张退出来发现列表回到第 1 张是很恼人的。
///
/// M7 新增：右上角可删除**当前这一张**。删除走 [photoDeletionServiceProvider]，
/// 删完 invalidate 整理页各流并退回列表（列表会自动反映出少了一张）。
class PhotoViewerPage extends ConsumerStatefulWidget {
  const PhotoViewerPage({
    super.key,
    required this.projectId,
    required this.group,
    required this.initialIndex,
    this.groupLabel,
  });

  /// 所属项目 id（删除需要它来定位磁盘上的原图 / 缩略图 / OCR 缓存）。
  final String projectId;

  /// 要展示的组（含组内全部照片）。
  final OpenGroup group;

  /// 打开时先看第几张（0-based）。
  final int initialIndex;

  /// 页脚组标签的覆盖值（2026-09-30：监装照片墙复用本页）。
  ///
  /// 默认 null = 显示「第 {seq} 组」；监装墙没有"组"的概念，
  /// 传「监装照片」进来，页脚就显示「监装照片 · 拍摄于 hh:mm:ss」。
  final String? groupLabel;

  @override
  ConsumerState<PhotoViewerPage> createState() => _PhotoViewerPageState();
}

class _PhotoViewerPageState extends ConsumerState<PhotoViewerPage> {
  late final PageController _controller;
  late int _index;

  @override
  void initState() {
    super.initState();
    final n = widget.group.photos.length;
    _index = n == 0 ? 0 : widget.initialIndex.clamp(0, n - 1);
    _controller = PageController(initialPage: _index);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  static String hhmm(int ms) {
    final t = DateTime.fromMillisecondsSinceEpoch(ms);
    return '${t.hour.toString().padLeft(2, '0')}:'
        '${t.minute.toString().padLeft(2, '0')}:'
        '${t.second.toString().padLeft(2, '0')}';
  }

  Future<void> _deleteCurrent() async {
    final photos = widget.group.photos;
    if (photos.isEmpty) return;
    final current = photos[_index];

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除这张照片？'),
        content: const Text(
          '照片与它的缩略图、OCR 缓存会从本项目中删除。\n'
          '若它是一组的最后一张，该组也会被移除。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('取消'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppTheme.red),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    await ref
        .read(photoDeletionServiceProvider)
        .deletePhoto(current.id);

    if (!mounted) return;
    // 照片页的各流（组列表 / 监装墙）靠 drift watch 自动刷新，
    // 这里显式 invalidate 一次确保立刻重算，然后退回列表。
    ref.invalidate(openGroupsProvider(widget.projectId));
    ref.invalidate(assignedGroupsProvider(widget.projectId));
    ref.invalidate(supervisionPhotosProvider(widget.projectId));
    Navigator.of(context).pop(_index);
  }

  @override
  Widget build(BuildContext context) {
    final photos = widget.group.photos;
    final total = photos.length;
    final current = total == 0 ? null : photos[_index];

    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        elevation: 0,
        title: Text(
          total == 0 ? '照片' : '第 ${_index + 1} / $total 张',
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        ),
        leading: IconButton(
          icon: const Icon(Icons.close),
          tooltip: '关闭',
          // 把最后停留的索引带回去（列表据此滚动定位）
          onPressed: () => Navigator.of(context).pop(_index),
        ),
        actions: [
          if (total > 0)
            IconButton(
              icon: const Icon(Icons.delete_outline),
              tooltip: '删除这张',
              color: AppTheme.red,
              onPressed: _deleteCurrent,
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: total == 0
                ? const Center(
                    child: Text(
                      '这一组里没有照片',
                      style: TextStyle(color: Colors.white70, fontSize: 14),
                    ),
                  )
                : PageView.builder(
                    controller: _controller,
                    itemCount: total,
                    onPageChanged: (i) => setState(() => _index = i),
                    itemBuilder: (_, i) => _FullPhoto(
                      // key 带上路径：换页时是新 widget，缩放状态不会串到下一张
                      key: ValueKey(photos[i].id),
                      photo: photos[i],
                    ),
                  ),
          ),
          SafeArea(
            top: false,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
              color: Colors.black,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${widget.groupLabel ?? '第 ${widget.group.seq} 组'}'
                    '${current == null ? '' : ' · 拍摄于 ${hhmm(current.takenAtMs)}'}',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    total > 1
                        ? '左右滑动看同组其他照片 · 双指放大看细节 · 双击复位'
                        : '双指放大看细节 · 双击复位',
                    style: const TextStyle(
                      color: Colors.white60,
                      fontSize: 11.5,
                      height: 1.4,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 单张原图的展示（缩放 + 平移 + 双击复位）。
///
/// 手势与复位动画已抽到公用组件 [ZoomableImage]（2026-09-30，
/// 相册选择器大图预览共用同一套交互）；这里只负责选路径与降级。
class _FullPhoto extends StatelessWidget {
  const _FullPhoto({super.key, required this.photo});

  final GroupPhotoThumb photo;

  @override
  Widget build(BuildContext context) {
    // 原图路径缺失时退到缩略图 —— 宁可看到小图，也不要一个空白框
    final path = photo.originalPath ?? photo.thumbPath;
    if (path == null) {
      return const Center(
        child: Icon(Icons.image_outlined, size: 42, color: Colors.white24),
      );
    }

    // 全屏单张，可以要高清：不做 cacheWidth 降采样。
    // ZoomableImage 里的 gaplessPlayback 保证翻页时先显示上一帧再换新图，
    // 否则白闪一下（现场光线差，白闪很刺眼）。
    return ZoomableImage(path: path);
  }
}
