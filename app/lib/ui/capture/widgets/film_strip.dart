import 'dart:io';

import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// 胶片条（§4.3 P4）。
///
/// ── 它存在的唯一理由 ────────────────────────────────────────
/// 回答"我刚才拍进去了没有"。
///
/// ── 它必须不显示什么 ────────────────────────────────────────
///  · 不显示归属 / 货品名 / 编码 —— 采集期根本没有那些信息
///  · 不显示识别状态 —— 那是整理阶段的事
///  · 不做"已归档"之类的文字 —— 那会让人以为这里能整理
///
/// ── 性能约束（R1b）─────────────────────────────────────────
/// 只用**已经生成好的 256px 缩略图**。缩略图还没生成时显示灰块，
/// **绝不在采集期解码原图** —— 那是掉帧和发热的头号来源。
class FilmStrip extends StatelessWidget {
  const FilmStrip({
    super.key,
    required this.items,
    this.count = 5,
    this.size = 54,
  });

  /// 最近的照片（按时间倒序，最新在前）。每项是 (photoId, thumbPath)。
  final List<FilmFrame> items;
  final int count;
  final double size;

  @override
  Widget build(BuildContext context) {
    final show = items.take(count).toList();

    return SizedBox(
      height: size,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < show.length; i++) ...[
            _Frame(item: show[i], size: size, latest: i == 0),
            if (i != show.length - 1) const SizedBox(width: 6),
          ],
        ],
      ),
    );
  }
}

/// 胶片条的一格。
class FilmFrame {
  const FilmFrame({required this.photoId, this.thumbPath});

  final String photoId;
  final String? thumbPath;
}

class _Frame extends StatelessWidget {
  const _Frame({required this.item, required this.size, required this.latest});

  final FilmFrame item;
  final double size;
  final bool latest;

  @override
  Widget build(BuildContext context) {
    final path = item.thumbPath;
    // ⚠️ 性能（09-29 排查）：原来这里 build 里跑 `existsSync()` ——
    // 同步文件 IO 在每一帧重建时都会执行（胶片条随张数流频繁重建）。
    // 文件在不在，交给 Image 的 errorBuilder 兜底即可，省掉同步 IO。
    final hasThumb = path != null;

    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.42),
        borderRadius: BorderRadius.circular(5),
        border: Border.all(
          // 最新一格高亮：让人不用数就知道"刚拍的进去了"
          color: latest
              ? AppTheme.accent
              : Colors.white.withValues(alpha: 0.22),
          width: latest ? 1.8 : 1,
        ),
      ),
      clipBehavior: Clip.antiAlias,
      child: hasThumb
          ? Image.file(
              File(path),
              fit: BoxFit.cover,
              gaplessPlayback: true,
              filterQuality: FilterQuality.low,
              // 胶片条是小格：按 2 倍尺寸解码（09-29 性能排查）
              cacheWidth: (size * 2).round(),
              errorBuilder: (_, __, ___) => const _ThumbPlaceholder(),
            )
          : const _ThumbPlaceholder(),
    );
  }
}

class _ThumbPlaceholder extends StatelessWidget {
  const _ThumbPlaceholder();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Icon(
        Icons.photo_outlined,
        size: 17,
        color: Colors.white.withValues(alpha: 0.3),
      ),
    );
  }
}
