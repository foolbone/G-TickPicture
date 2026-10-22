import 'package:flutter/material.dart';

/// 取景框 overlay（§4.3 P4）。
///
/// ── 它为什么存在 ──────────────────────────────────────────────
/// 采集页有一半的用户是**戴手套、单手、手机挂腕带**的（§1.3）。
/// 取景框不是"装饰" —— 它承担两个实际功能：
///  ① 告诉人"唛头要落在这个范围里"，减少拍歪；
///  ② 给一个视觉锚点，让"抬手就拍"这个动作不需要思考。
///
/// ── 它刻意不是什么 ────────────────────────────────────────────
///  · 不是 OCR 预览框（不做实时识别，§5.2 采集期禁止逐帧分析）
///  · 不是质检提示（不判模糊、不判曝光 —— 那是拍照之后的事）
///  · 不带任何红/绿状态色（状态色会让人以为"要等它变绿"）
///
/// ── 网格线（09-26 老板诉求）──────────────────────────────────
/// [grid] 打开时画**全屏**三分线（九宫格）。默认关 —— 「不干扰」
/// 原则下网格是可选项不是默认项；它是构图辅助，不承载任何状态。
class FrameOverlay extends StatelessWidget {
  const FrameOverlay({
    super.key,
    this.hint = '对准货品唛头，连续拍摄',
    this.subHint = '不需要选货品 · 不需要输入',
    this.visible = true,
    this.grid = false,
  });

  final String hint;
  final String subHint;

  /// 连拍时可临时收起，减少干扰。
  final bool visible;

  /// 九宫格构图线。默认关。
  final bool grid;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: AnimatedOpacity(
        opacity: visible ? 1 : 0,
        duration: const Duration(milliseconds: 180),
        child: CustomPaint(
          painter: _FramePainter(showGrid: grid),
          child: Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 28),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const SizedBox(height: 8),
                  Text(
                    hint,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      shadows: [
                        Shadow(blurRadius: 8, color: Color(0xCC000000)),
                      ],
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    subHint,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: Color(0xCCFFFFFF),
                      fontSize: 12.5,
                      shadows: [
                        Shadow(blurRadius: 8, color: Color(0xCC000000)),
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
  }
}

class _FramePainter extends CustomPainter {
  _FramePainter({required this.showGrid});

  final bool showGrid;

  /// 框在屏幕上的相对尺寸。宽度占 78%、高度占 42% ——
  /// 依据：标签 / 唛头通常是横向的长方形，且手持时自然会对准屏幕中部。
  static const double _wRatio = 0.78;
  static const double _hRatio = 0.42;

  @override
  void paint(Canvas canvas, Size size) {
    // ── 三分线：全屏九宫格，先画（垫在四角下层）──────────────
    // 存在感压到 0.16 透明度 —— 辅助线一旦抢戏就变成了干扰。
    if (showGrid) {
      final grid = Paint()
        ..color = Colors.white.withValues(alpha: 0.16)
        ..strokeWidth = 1;
      final dx = size.width / 3;
      final dy = size.height / 3;
      for (var i = 1; i <= 2; i++) {
        canvas.drawLine(Offset(dx * i, 0), Offset(dx * i, size.height), grid);
        canvas.drawLine(Offset(0, dy * i), Offset(size.width, dy * i), grid);
      }
    }

    final rect = Rect.fromCenter(
      center: Offset(size.width / 2, size.height / 2 - size.height * 0.06),
      width: size.width * _wRatio,
      height: size.height * _hRatio,
    );

    // ── 四个角标：比整框细线更"轻"，不会压住画面 ──
    final corner = Paint()
      ..color = Colors.white.withValues(alpha: 0.92)
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;

    final arm = rect.width * 0.11;

    void drawCorner(Offset origin, double dx, double dy) {
      canvas.drawLine(origin, origin.translate(arm * dx, 0), corner);
      canvas.drawLine(origin, origin.translate(0, arm * dy), corner);
    }

    drawCorner(rect.topLeft, 1, 1);
    drawCorner(rect.topRight, -1, 1);
    drawCorner(rect.bottomLeft, 1, -1);
    drawCorner(rect.bottomRight, -1, -1);

    // ── 中间的十字准星（对焦参考，极低存在感）──
    final cross = Paint()
      ..color = Colors.white.withValues(alpha: 0.30)
      ..strokeWidth = 1;
    canvas.drawLine(
      rect.centerLeft.translate(rect.width * 0.45, 0),
      rect.centerRight.translate(-rect.width * 0.45, 0),
      cross,
    );
    canvas.drawLine(
      rect.topCenter.translate(0, rect.height * 0.38),
      rect.bottomCenter.translate(0, -rect.height * 0.38),
      cross,
    );
  }

  @override
  bool shouldRepaint(covariant _FramePainter oldDelegate) =>
      oldDelegate.showGrid != showGrid;
}

/// 触摸取景框时的对焦指示方块（§5.2「点击取景框任意处 = 对焦/测光」）。
///
/// 一次性动画：出现 → 缩一下 → 淡出。不驻留，
/// 因为采集页不该有任何"还在进行中"的视觉残留。
class FocusReticle extends StatefulWidget {
  const FocusReticle({
    super.key,
    required this.offset,
    this.side = 76,
    this.locked = false,
  });

  /// 预览归一化坐标（0~1）。
  final Offset offset;
  final double side;

  /// 已合焦。黄框（对焦中）→ 白框（对上了）。
  ///
  /// 现场快速拍时需要一个"可以拍了"的确认信号；没有它，点完屏幕只能
  /// 靠画面自己变清楚来判断，暗处/低对比（外包装、木箱、唛头）那一下
  /// 很难看出来。
  final bool locked;

  @override
  State<FocusReticle> createState() => _FocusReticleState();
}

class _FocusReticleState extends State<FocusReticle>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 760),
  )..forward();

  @override
  void initState() {
    super.initState();
    _c.addStatusListener((s) {
      if (s == AnimationStatus.completed && mounted) {
        setState(() {});
      }
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_c.isCompleted) return const SizedBox.shrink();

    return IgnorePointer(
      child: LayoutBuilder(
        builder: (context, c) {
          final t = _c.value;
          // 前 25% 缩入，后 75% 淡出
          final scale = t < 0.25 ? 1.18 - t * 0.72 : 1.0;
          final opacity =
              t < 0.25 ? 1.0 : (1 - (t - 0.25) / 0.75).clamp(0.0, 1.0);

          return Stack(
            children: [
              Positioned(
                left: widget.offset.dx * c.maxWidth - widget.side / 2,
                top: widget.offset.dy * c.maxHeight - widget.side / 2,
                child: Opacity(
                  opacity: opacity,
                  child: Transform.scale(
                    scale: scale,
                    child: Container(
                      width: widget.side,
                      height: widget.side,
                      decoration: BoxDecoration(
                        border: Border.all(
                          color: widget.locked
                              ? Colors.white
                              : const Color(0xFFFFD24D),
                          width: widget.locked ? 2.2 : 1.6,
                        ),
                        borderRadius: BorderRadius.circular(3),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
