import 'package:flutter/material.dart';

import '../../../app/theme.dart';

/// 快门键（§4.3 P4）。
///
/// ── 交互契约 ────────────────────────────────────────────────
///  · 单击     → 拍一张
///  · 长按     → 连拍（每 400ms 一张，最多 20 张），松手即停
///  · 右滑     → 切换前后摄（"上滑"在单手横持时不好使）
///
/// ── 尺寸理由 ────────────────────────────────────────────────
/// 外径 84 / 内径 66 —— 远超 48dp 的最小点击尺寸（§1.3）。
/// 戴棉线手套时手指触控面积会明显变大，按压中心也更容易偏，
/// 所以这里宁可做大，不做小。
///
/// ── 视觉反馈的克制 ──────────────────────────────────────────
/// 按下时只做一次很短的收缩（sc 0.94）+ 内圈变浅。
/// **不做"拍照成功"的绿光/对勾** —— 那种反馈会让人下意识去看屏幕，
/// 而现场的正确动作是"拍完就走"。张数在顶部跳，那就是全部反馈。
class ShutterButton extends StatefulWidget {
  const ShutterButton({
    super.key,
    required this.onTap,
    required this.onLongPressStart,
    required this.onLongPressEnd,
    required this.onSwitchCamera,
    this.onPressDown,
    this.enabled = true,
    this.busy = false,
  });

  final VoidCallback onTap;
  final VoidCallback onLongPressStart;
  final VoidCallback onLongPressEnd;
  final VoidCallback onSwitchCamera;

  /// **按下瞬间**的回调（手指落下、还没抬起）—— 采集页用它预对焦。
  ///
  /// 为什么要有它：对焦是拍照里唯一必须"等"的动作，而按下→抬起这段
  /// 时间本来就是白等的。把它交给采集页去跑 AF，抬手时焦已经合上，
  /// 快门就快了。单击和长按都会触发（长按的第一下也是按下去）。
  final VoidCallback? onPressDown;

  final bool enabled;

  /// 正在写盘（连拍时的常态）。只用于轻微视觉提示，不禁用点击。
  final bool busy;

  @override
  State<ShutterButton> createState() => _ShutterButtonState();
}

class _ShutterButtonState extends State<ShutterButton> {
  var _pressed = false;
  var _bursting = false;

  static const double _outer = 84;
  static const double _inner = 66;

  @override
  Widget build(BuildContext context) {
    final dim = !widget.enabled;

    // ── 为什么预对焦走 Listener 而不是 GestureDetector ────────────
    // 本按钮同时认单击/长按/横滑三种手势，它们要进**手势竞技场**分胜负：
    // 手指落下那一刻胜负未定，`onTapDown` 会被压到竞技场结束才回调 ——
    // 而竞技场要等抬手或移动才结束，于是"按下就对焦"变成了"抬手才对焦"，
    // 正好把想抢的那点时间原样浪费掉。
    //
    // Listener 拿的是**原始 pointer 事件**，不进竞技场，落下即时回调。
    // 它不消费事件，下面的 GestureDetector 照旧判定单击/长按/横滑。
    return Listener(
      onPointerDown: dim ? null : (_) => widget.onPressDown?.call(),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: dim ? null : (_) => setState(() => _pressed = true),
        onTapUp: dim
            ? null
            : (_) {
                setState(() => _pressed = false);
                widget.onTap();
              },
        onTapCancel: () => setState(() => _pressed = false),
        onLongPressStart: dim
            ? null
            : (_) {
                setState(() {
                  _pressed = true;
                  _bursting = true;
                });
                widget.onLongPressStart();
              },
        onLongPressEnd: dim
            ? null
            : (_) {
                setState(() {
                  _pressed = false;
                  _bursting = false;
                });
                widget.onLongPressEnd();
              },
        // 横向拖动手势用于切镜头。用 onHorizontalDragEnd 而不是
        // onVerticalDrag，因为手腕挂绳时手指更容易横向抹。
        onHorizontalDragEnd: dim
            ? null
            : (d) {
                final v = d.primaryVelocity ?? 0;
                if (v.abs() > 220) widget.onSwitchCamera();
              },
        child: SizedBox(
          width: _outer + 28,
          height: _outer + 28,
          child: Stack(
            alignment: Alignment.center,
            children: [
              // 外环
              AnimatedContainer(
                duration: const Duration(milliseconds: 90),
                width: _outer,
                height: _outer,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: dim
                        ? Colors.white.withValues(alpha: 0.25)
                        : Colors.white.withValues(alpha: 0.95),
                    width: 4,
                  ),
                ),
              ),
              // 内芯
              AnimatedScale(
                duration: const Duration(milliseconds: 90),
                scale: _pressed ? 0.9 : 1.0,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 120),
                  width: _inner,
                  height: _inner,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: dim
                        ? Colors.white.withValues(alpha: 0.18)
                        : _bursting
                            ? AppTheme.accent
                            : Colors.white,
                  ),
                  child: _bursting
                      ? const Icon(Icons.stop_rounded,
                          color: Colors.white, size: 26)
                      : null,
                ),
              ),
              // 写盘中的极轻提示：只有一圈细弧，不遮挡也不闪烁
              if (widget.busy && !dim)
                SizedBox(
                  width: _outer + 14,
                  height: _outer + 14,
                  child: CircularProgressIndicator(
                    strokeWidth: 1.6,
                    color: Colors.white.withValues(alpha: 0.5),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 相机页的圆形小钮（相册导入 / 微信导入等）。
///
/// M5.1 醒目化（老板 09-26 拍板：相册导入入口要更明显）：
///  · [emphasized] 强调态 —— 主题色实底 + 更亮描边 + 更大图标，
///    在"底部一片黑玻璃"里唯一带颜色的钮，视线第一落点；
///  · [showLabel] 在圆钮下方渲染**可见文字** —— 以前 label 只进
///    Semantics，屏幕上看不到"从相册导入"五个字，新用户不知道
///    那颗钮是干嘛的。
/// 其余小钮（闪光 / 曝光）保持低调默认态，不与主动作抢权重。
class RoundIconButton extends StatelessWidget {
  const RoundIconButton({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
    this.enabled = true,
    this.size = 52,
    this.emphasized = false,
    this.showLabel = false,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool enabled;

  /// 圆钮直径。强调态建议 62（快门 84 与普通钮 52 之间的层级）。
  final double size;

  /// 强调态：主题色实底。一页至多一颗，多了就不"强调"了。
  final bool emphasized;

  /// 圆钮下方是否渲染可见文字标签。
  final bool showLabel;

  @override
  Widget build(BuildContext context) {
    final circle = InkWell(
      onTap: enabled ? onTap : null,
      customBorder: const CircleBorder(),
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: emphasized
              ? AppTheme.accent.withValues(alpha: enabled ? 0.92 : 0.28)
              : Colors.black.withValues(alpha: 0.34),
          border: Border.all(
            color: Colors.white
                .withValues(alpha: enabled ? (emphasized ? 0.85 : 0.32) : 0.12),
            width: emphasized ? 1.6 : 1,
          ),
        ),
        child: Icon(
          icon,
          size: emphasized ? 27 : 23,
          color: Colors.white.withValues(alpha: enabled ? 0.98 : 0.35),
        ),
      ),
    );

    if (!showLabel) {
      return Semantics(button: true, label: label, child: circle);
    }

    return Semantics(
      button: true,
      label: label,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          circle,
          const SizedBox(height: 5),
          Text(
            label,
            style: TextStyle(
              fontSize: 10.5,
              height: 1.1,
              fontWeight: emphasized ? FontWeight.w700 : FontWeight.w500,
              color: Colors.white.withValues(alpha: enabled ? 0.92 : 0.35),
              shadows: const [
                Shadow(color: Colors.black54, blurRadius: 4),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 「结束采集」—— 长按 1 秒（§4.3 P4：防误触，但不要二次确认弹窗）。
///
/// 为什么不做确认弹窗：现场戴手套单手操作，弹窗要"瞄准按钮再点"，
/// 反而更烦。长按是一个**不需要阅读**的防误触手段。
class HoldToFinishButton extends StatefulWidget {
  const HoldToFinishButton({
    super.key,
    required this.onFinish,
    this.holdDuration = const Duration(seconds: 1),
  });

  final VoidCallback onFinish;
  final Duration holdDuration;

  @override
  State<HoldToFinishButton> createState() => _HoldToFinishButtonState();
}

class _HoldToFinishButtonState extends State<HoldToFinishButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: widget.holdDuration,
  );

  @override
  void initState() {
    super.initState();
    _c.addStatusListener((s) {
      if (s == AnimationStatus.completed) {
        _c.reset();
        widget.onFinish();
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
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTapDown: (_) => _c.forward(),
      onTapUp: (_) => _c.reverse(),
      onTapCancel: () => _c.reverse(),
      onLongPressEnd: (_) => _c.reverse(),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(19),
          color: Colors.black.withValues(alpha: 0.34),
          border: Border.all(color: Colors.white.withValues(alpha: 0.3)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              '结束采集',
              style: TextStyle(
                color: Colors.white,
                fontSize: 12.5,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(width: 6),
            // 环形进度：手指按住时填满，填满即触发
            AnimatedBuilder(
              animation: _c,
              builder: (context, _) => SizedBox(
                width: 13,
                height: 13,
                child: CircularProgressIndicator(
                  value: _c.value,
                  strokeWidth: 1.8,
                  backgroundColor: Colors.white.withValues(alpha: 0.22),
                  color: Colors.white,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
