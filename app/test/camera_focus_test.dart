import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:g_tick_picture/domain/capture/camera_capture_service.dart';
import 'package:g_tick_picture/ui/capture/widgets/shutter_button.dart';

/// 对焦（2026-10-09 老板诉求「拍照时需要能够快速对焦，适应现场快速拍照」）。
///
/// 现场快拍里，对焦是唯一必须"等"的动作。做法是把它提前到"手指按下→
/// 抬起"这段白等的时间里跑完（半按对焦），抬手时焦距已合上。
///
/// 服务里真正调相机的那几行没法在单测里验（要真镜头），所以这里测的是
/// **可验的两块**：①对焦点/节流的纯规则；②快门键是否真的在按下瞬间
/// 就把这个动作发出去了 —— 少这一环，服务写得再对也没人调用它。
void main() {
  group('预对焦规则', () {
    test('没点过对焦点 → 用画面中心', () {
      expect(
        CameraCaptureService.focusTargetFor(null),
        const Offset(0.5, 0.5),
      );
    });

    test('点过对焦点 → 复用它（那是用户刚指定的位置）', () {
      expect(
        CameraCaptureService.focusTargetFor(const Offset(0.2, 0.8)),
        const Offset(0.2, 0.8),
      );
    });

    test('首次按下一定触发', () {
      final now = DateTime(2026, 10, 9, 12, 0, 0);
      expect(CameraCaptureService.shouldPrepareFocus(null, now), isTrue);
    });

    test('节流窗口内不重复触发（连拍/手抖时 AF 反复重启只会更慢）', () {
      final now = DateTime(2026, 10, 9, 12, 0, 0);
      final last = now.subtract(CameraCaptureService.prepareFocusThrottle ~/ 2);
      expect(CameraCaptureService.shouldPrepareFocus(last, now), isFalse);
    });

    test('过了节流窗口就再触发一次', () {
      final now = DateTime(2026, 10, 9, 12, 0, 0);
      final last = now.subtract(CameraCaptureService.prepareFocusThrottle * 2);
      expect(CameraCaptureService.shouldPrepareFocus(last, now), isTrue);
    });
  });

  group('快门按下瞬间', () {
    Future<void> pumpShutter(
      WidgetTester tester, {
      required void Function() onPressDown,
      void Function()? onTap,
    }) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: ShutterButton(
                onTap: onTap ?? () {},
                onLongPressStart: () {},
                onLongPressEnd: () {},
                onSwitchCamera: () {},
                onPressDown: onPressDown,
              ),
            ),
          ),
        ),
      );
    }

    testWidgets('单击：手指落下就发预对焦，抬起才拍照', (tester) async {
      var prepared = 0;
      var shot = 0;
      await pumpShutter(tester,
          onPressDown: () => prepared++, onTap: () => shot++);

      final center = tester.getCenter(find.byType(ShutterButton));
      final gesture = await tester.startGesture(center);
      await tester.pump();

      // 按下（还没抬）：预对焦已经跑了，照片还没拍
      expect(prepared, 1, reason: '按下瞬间必须先开始对焦，抬手才有得拍');
      expect(shot, 0);

      await gesture.up();
      await tester.pump();
      expect(shot, 1);
    });

    testWidgets('长按连拍：第一下也要先对焦', (tester) async {
      var prepared = 0;
      await pumpShutter(tester, onPressDown: () => prepared++);

      final center = tester.getCenter(find.byType(ShutterButton));
      final gesture = await tester.startGesture(center);
      await tester.pump(const Duration(milliseconds: 600)); // 越过长按阈值
      await tester.pump();

      expect(prepared, greaterThanOrEqualTo(1));

      await gesture.up();
      await tester.pumpAndSettle();
    });

    testWidgets('禁用态：按下去不触发预对焦', (tester) async {
      var prepared = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Center(
              child: ShutterButton(
                enabled: false,
                onTap: () {},
                onLongPressStart: () {},
                onLongPressEnd: () {},
                onSwitchCamera: () {},
                onPressDown: () => prepared++,
              ),
            ),
          ),
        ),
      );

      final center = tester.getCenter(find.byType(ShutterButton));
      final gesture = await tester.startGesture(center);
      await tester.pump();
      expect(prepared, 0);
      await gesture.up();
      await tester.pumpAndSettle();
    });
  });
}
