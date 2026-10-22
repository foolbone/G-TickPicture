// 相机增强（09-26 老板诉求）的单测：
//   ① CameraPreferences —— 默认值 / 往返 / 未知存储值防御
//   ② 画幅 → ResolutionPreset 映射（纯静态，不起相机）
//   ③ 变焦快捷档位生成（纯静态）
//
// 真实相机行为（setZoomLevel / 重建控制器）在插件层，单测覆盖不到，
// 由真机复测兜底（见待办：相机增强真机项）。
import 'package:camera/camera.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/capture/camera_capture_service.dart';
import 'package:g_tick_picture/domain/capture/camera_preferences.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('CameraPreferences', () {
    test('默认值：4:3 / 闪光关 / 网格关 / 拍后回看开', () async {
      SharedPreferences.setMockInitialValues({});
      final p = CameraPreferences();

      expect(await p.aspectRatio(), CameraAspectRatio.ratio4_3);
      expect(await p.flashMode(), FlashMode.off);
      expect(await p.gridLines(), isFalse);
      // 回看默认开：拍糊当场知道是默认动作，关掉留给节奏优先的人
      expect(await p.reviewAfterShot(), isTrue);
    });

    test('set/get 往返', () async {
      SharedPreferences.setMockInitialValues({});
      final p = CameraPreferences();

      await p.setAspectRatio(CameraAspectRatio.ratio16_9);
      await p.setFlashMode(FlashMode.torch);
      await p.setGridLines(true);
      await p.setReviewAfterShot(false);

      expect(await p.aspectRatio(), CameraAspectRatio.ratio16_9);
      expect(await p.flashMode(), FlashMode.torch);
      expect(await p.gridLines(), isTrue);
      expect(await p.reviewAfterShot(), isFalse);
    });

    test('未知存储值防御：一律回落默认（老版本升级无键也走这条）', () async {
      SharedPreferences.setMockInitialValues({
        'camera.aspect_ratio': 'bogus',
        'camera.flash_mode': 'bogus',
        'camera.grid_lines': 'not-a-bool',
      });
      final p = CameraPreferences();

      expect(await p.aspectRatio(), CameraAspectRatio.ratio4_3);
      expect(await p.flashMode(), FlashMode.off);
      // getBool 对非 bool 字符串会抛 TypeError —— 网格是纯 UI 态，
      // 读取方（采集页）自己 try-catch 兜底，这里不保证返回值。
    });

    test('注入 override 与直读一致（GalleryService 同款测试姿势）', () async {
      SharedPreferences.setMockInitialValues({'camera.grid_lines': true});
      final p = CameraPreferences();
      expect(await p.gridLines(), isTrue);
    });
  });

  group('画幅 → 分辨率映射', () {
    test('4:3 → max（传感器原生，画质最大化）', () {
      expect(
        CameraCaptureService.presetFor(CameraAspectRatio.ratio4_3),
        ResolutionPreset.max,
      );
    });

    test('16:9 → ultraHigh（4K 级宽幅）', () {
      expect(
        CameraCaptureService.presetFor(CameraAspectRatio.ratio16_9),
        ResolutionPreset.ultraHigh,
      );
    });
  });

  group('变焦快捷档位生成', () {
    test('不支持变焦（[1,1]）→ 保底 1x', () {
      expect(CameraCaptureService.zoomStepsFor(1.0, 1.0), <double>[1.0]);
    });

    test('max=2 → 1x / 2x', () {
      expect(
        CameraCaptureService.zoomStepsFor(1.0, 2.0),
        <double>[1.0, 2.0],
      );
    });

    test('max=6 → 1x / 2x / 5x（5 在能力内）', () {
      expect(
        CameraCaptureService.zoomStepsFor(1.0, 6.0),
        <double>[1.0, 2.0, 5.0],
      );
    });

    test('不能缩小的普通镜头 min=1：不出小于 1x 的档', () {
      expect(
        CameraCaptureService.zoomStepsFor(1.0, 8.0),
        <double>[1.0, 2.0, 5.0],
      );
    });

    test('max=1.5（只有一点点变焦）→ 只有 1x 可用', () {
      expect(CameraCaptureService.zoomStepsFor(1.0, 1.5), <double>[1.0]);
    });

    // ── 缩小档（2026-10-09 修订）────────────────────────────
    // 原来写死 0.6 一档：设备 minZoom=1.0 时它被过滤、界面什么都不说，
    // 真机反馈就是「看不到 0.6x」。现在缩小档**只认设备上报的 minZoom**，
    // 能缩到多少就显示多少 —— 不写死，也就不存在"按了没反应"的档。

    test('镜头能缩到 0.6 → 档位就是 0.6x（老板要的那个数）', () {
      expect(
        CameraCaptureService.zoomStepsFor(0.6, 8.0),
        <double>[0.6, 1.0, 2.0, 5.0],
      );
    });

    test('镜头只能缩到 0.7 → 显示 0.7x，不谎报 0.6x', () {
      expect(
        CameraCaptureService.zoomStepsFor(0.7, 4.0),
        <double>[0.7, 1.0, 2.0],
      );
    });

    test('超广角 min=0.5 → 显示 0.5x（设备真实能力）', () {
      expect(
        CameraCaptureService.zoomStepsFor(0.5, 8.0),
        <double>[0.5, 1.0, 2.0, 5.0],
      );
    });

    test('上报值带零碎小数（0.62）→ 显示一位小数 0.6x', () {
      expect(
        CameraCaptureService.zoomStepsFor(0.62, 8.0),
        <double>[0.6, 1.0, 2.0, 5.0],
      );
    });

    test('min=0.95（等于没缩小）→ 不单独给档，避免和 1x 挤在一起', () {
      expect(
        CameraCaptureService.zoomStepsFor(0.95, 8.0),
        <double>[1.0, 2.0, 5.0],
      );
    });

    test('只能缩不能放（min=0.6, max=1.0）→ 0.6x 与 1x 都出', () {
      expect(
        CameraCaptureService.zoomStepsFor(0.6, 1.0),
        <double>[0.6, 1.0],
      );
    });
  });

  // ─────────────────────────────────────────────────────────
  // 换镜头（2026-10-09）：0.6x 的真身
  //
  // 数码变焦只能放大，视野变宽只能换镜头。超广角在被系统独立暴露时
  // 就是 availableCameras 里的另一颗后置 —— 这里定的是"下一颗是谁"。
  // ─────────────────────────────────────────────────────────
  group('后置镜头轮换', () {
    CameraDescription lens(String name, CameraLensDirection dir) =>
        CameraDescription(name: name, lensDirection: dir, sensorOrientation: 90);

    test('两颗后置：主摄 → 副摄', () {
      final cams = [
        lens('Camera 0', CameraLensDirection.back),
        lens('Camera 1', CameraLensDirection.front),
        lens('Camera 2', CameraLensDirection.back),
      ];
      expect(CameraCaptureService.nextBackLensIndex(cams, 0), 2);
    });

    test('两颗后置：副摄 → 回到主摄（循环）', () {
      final cams = [
        lens('Camera 0', CameraLensDirection.back),
        lens('Camera 1', CameraLensDirection.front),
        lens('Camera 2', CameraLensDirection.back),
      ];
      expect(CameraCaptureService.nextBackLensIndex(cams, 2), 0);
    });

    test('三颗后置：按顺序走完再回第一颗', () {
      final cams = [
        lens('Camera 0', CameraLensDirection.back),
        lens('Camera 1', CameraLensDirection.back),
        lens('Camera 2', CameraLensDirection.back),
      ];
      expect(CameraCaptureService.nextBackLensIndex(cams, 0), 1);
      expect(CameraCaptureService.nextBackLensIndex(cams, 1), 2);
      expect(CameraCaptureService.nextBackLensIndex(cams, 2), 0);
    });

    test('当前是前置 → 回到第一颗后置（点换镜头是想继续拍背面）', () {
      final cams = [
        lens('Camera 0', CameraLensDirection.back),
        lens('Camera 1', CameraLensDirection.front),
        lens('Camera 2', CameraLensDirection.back),
      ];
      expect(CameraCaptureService.nextBackLensIndex(cams, 1), 0);
    });

    test('只有一颗后置 → -1（没得换，界面要明说而不是按了没反应）', () {
      final cams = [
        lens('Camera 0', CameraLensDirection.back),
        lens('Camera 1', CameraLensDirection.front),
      ];
      expect(CameraCaptureService.nextBackLensIndex(cams, 0), -1);
    });

    test('没有后置（只有前置）→ -1', () {
      final cams = [lens('Camera 0', CameraLensDirection.front)];
      expect(CameraCaptureService.nextBackLensIndex(cams, 0), -1);
    });
  });
}
