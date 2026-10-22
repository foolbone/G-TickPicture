import 'dart:io';

import 'package:flutter/material.dart';

/// 可双指缩放 / 平移 / 双击复位的单图查看组件（2026-09-30 抽公用）。
///
/// 之前这套交互只住在全屏查看页（`PhotoViewerPage._FullPhoto`）；
/// 相册选择器的大图预览同样需要「放大看细节」（老板 09-30 拍板），
/// 因此抽成公用组件，两处共用同一套手势与复位动画。
///
/// 用 [InteractiveViewer] 而不是自己算手势：系统相册级的
/// 边界回弹、双指焦点、惯性平移它都处理好了，自己写只会更差。
class ZoomableImage extends StatefulWidget {
  const ZoomableImage({
    super.key,
    required this.path,
    this.maxScale = 5.0,
    this.cacheWidth,
    this.filterQuality = FilterQuality.low,
    this.errorBuilder,
  });

  /// 图片文件路径。
  final String path;

  /// 最大放大倍数（min 固定 1.0 = 原始适配尺寸）。
  final double maxScale;

  /// 解码宽度上限（像素）。null = 按原图解码（全屏单张可接受）。
  ///
  /// 想让「放大后依然清晰」，这里的值必须大于屏幕物理宽度 ——
  /// 按 1 倍屏宽解码的图，放大 2 倍就开始糊（像素不够了）。
  final int? cacheWidth;

  /// 缩采样过滤质量。小图/静态看用默认 low；预览大图可传 medium。
  final FilterQuality filterQuality;

  /// 读不出文件时的展示；不传用默认的碎图提示（暗色系，适合黑底页）。
  final WidgetBuilder? errorBuilder;

  @override
  State<ZoomableImage> createState() => _ZoomableImageState();
}

class _ZoomableImageState extends State<ZoomableImage>
    with SingleTickerProviderStateMixin {
  final _transform = TransformationController();

  /// 双击复位用的动画。惰性建 —— 大多数照片不需要复位。
  AnimationController? _resetAnim;

  @override
  void dispose() {
    _resetAnim?.dispose();
    _transform.dispose();
    super.dispose();
  }

  void _reset() {
    // 双击复位：动画回原尺度，比瞬间跳回更容易理解发生了什么
    if (_transform.value == Matrix4.identity()) return;
    final anim = _resetAnim ??= AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 180),
    );
    final tween = Matrix4Tween(
      begin: _transform.value,
      end: Matrix4.identity(),
    ).animate(CurvedAnimation(parent: anim, curve: Curves.easeOut));
    void listener() => _transform.value = tween.value;
    tween
      ..removeListener(listener)
      ..addListener(listener);
    anim
      ..reset()
      ..forward().whenComplete(() => tween.removeListener(listener));
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onDoubleTap: _reset,
      child: InteractiveViewer(
        transformationController: _transform,
        minScale: 1.0,
        maxScale: widget.maxScale,
        // 只在真的放大后才允许平移超出边界（scale 1 时锁死，避免空拖）
        panEnabled: true,
        child: Center(
          child: Image.file(
            File(widget.path),
            fit: BoxFit.contain,
            cacheWidth: widget.cacheWidth,
            filterQuality: widget.filterQuality,
            // 重进 / 换源时先显示上一帧再换新图，避免白闪
            gaplessPlayback: true,
            errorBuilder: (_, __, ___) =>
                widget.errorBuilder != null
                    ? Builder(builder: widget.errorBuilder!)
                    : const _DefaultError(),
          ),
        ),
      ),
    );
  }
}

/// 默认错误占位（暗色系，给黑底的全屏查看页用）。
class _DefaultError extends StatelessWidget {
  const _DefaultError();

  @override
  Widget build(BuildContext context) {
    return const Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.broken_image_outlined, size: 40, color: Colors.white38),
        SizedBox(height: 8),
        Text(
          '这张照片读不出来',
          style: TextStyle(color: Colors.white60, fontSize: 13),
        ),
      ],
    );
  }
}
