// v0.19.0 拍照体验（2026-10-10）纯函数单测：
//   ① shakeLevelOf —— jerk RMS 分级（手抖提示的唯一判定入口）
//   ② CameraCaptureService.nextAutoEv —— 暗光自动曝光补偿的目标档计算
//
// 两者都是静态纯函数，不起相机、不开传感器 —— 分级阈值与状态机一旦
// 写错，现场表现是「该提示不提示 / 自动曝光过冲」，只能靠这里钉死。
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/core/constants.dart';
import 'package:g_tick_picture/core/sensor_bridge.dart';
import 'package:g_tick_picture/domain/capture/camera_capture_service.dart';

void main() {
  group('shakeLevelOf（手抖分级）', () {
    test('没量到（null）→ unknown —— 没数据必须闭嘴，绝不当成"不抖"', () {
      expect(shakeLevelOf(null), ShakeLevel.unknown);
    });

    test('静止手持（0.1~0.4 实测区间）→ none，不提示', () {
      expect(shakeLevelOf(0.0), ShakeLevel.none);
      expect(shakeLevelOf(0.2), ShakeLevel.none);
      expect(shakeLevelOf(0.4), ShakeLevel.none);
    });

    test('轻度抖动（mild 阈值起）→ mild，只记录不提示（判定交给 UI）', () {
      expect(shakeLevelOf(AppConst.shakeMildJerk), ShakeLevel.mild);
      expect(shakeLevelOf(1.5), ShakeLevel.mild);
    });

    test('明显手抖（heavy 阈值起）→ heavy，UI 提示「稳一下再按」', () {
      expect(shakeLevelOf(AppConst.shakeHeavyJerk), ShakeLevel.heavy);
      expect(shakeLevelOf(3.0), ShakeLevel.heavy);
      expect(shakeLevelOf(9.9), ShakeLevel.heavy);
    });

    test('边界值归属：恰好等于阈值算进对应档（>= 语义）', () {
      // mild 与 heavy 的分界：2.5 归 heavy，1.0 归 mild
      expect(shakeLevelOf(2.4999), ShakeLevel.mild);
      expect(shakeLevelOf(0.9999), ShakeLevel.none);
    });
  });

  group('nextAutoEv（暗光自动曝光补偿）', () {
    // 常用参数组合：设备支持（step 0.5 / 上限 3.0），产品上限 1.5 由
    // 调用方取 min 后传入 —— 这里模拟调用方算好的值。
    double ev({
      double current = 0,
      int? luma,
      double step = 0.5,
      double maxBoost = 1.5,
    }) =>
        CameraCaptureService.nextAutoEv(
          current: current,
          luma: luma,
          step: step,
          maxBoost: maxBoost,
          darkBelow: AppConst.lowLightLuma,
          brightAbove: AppConst.autoEvBrightLuma,
        );

    test('亮度没量到（null）→ 不动 —— 不知道 ≠ 要补偿（纪律 17）', () {
      expect(ev(luma: null, current: 0), 0);
      expect(ev(luma: null, current: 1.0), 1.0);
    });

    test('设备不支持（step=0 或 maxBoost=0）→ 恒不动（能力闸门）', () {
      expect(ev(luma: 10, step: 0), 0);
      expect(ev(luma: 10, maxBoost: 0), 0);
      // 已有残留档时也不动（反正下发会被 clamp 成 0）
      expect(ev(luma: 10, step: 0, current: 1.0), 1.0);
    });

    test('暗（< 64）→ 加一档 0.5', () {
      expect(ev(luma: 0), 0.5);
      expect(ev(luma: 63), 0.5);
    });

    test('连续暗 → 爬到产品上限 1.5 封顶，不过冲', () {
      expect(ev(luma: 20, current: 0.5), 1.0);
      expect(ev(luma: 20, current: 1.0), 1.5);
      expect(ev(luma: 20, current: 1.5), 1.5);
    });

    test('设备上限比产品上限低 → 钳到设备上限', () {
      expect(ev(luma: 20, current: 1.0, maxBoost: 1.2), 1.2);
    });

    test('亮（> 110）且有残留 → 退一档，最小到 0（不欠冲为负）', () {
      expect(ev(luma: 200, current: 1.5), 1.0);
      expect(ev(luma: 200, current: 0.5), 0);
      expect(ev(luma: 200, current: 0), 0);
    });

    test('中间带（64~110）→ 不动（防阈值附近抖动）', () {
      expect(ev(luma: 64), 0);
      expect(ev(luma: 90), 0);
      expect(ev(luma: 110), 0);
      expect(ev(luma: 90, current: 1.0), 1.0);
    });

    test('步长尊重硬件能力：step=1.0（粗步长机型）按 1.0 走', () {
      expect(ev(luma: 20, step: 1.0), 1.0);
    });
  });
}
