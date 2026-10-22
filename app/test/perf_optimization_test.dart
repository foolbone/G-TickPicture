import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/core/async_limiter.dart';
import 'package:g_tick_picture/core/device_tier.dart';
import 'package:g_tick_picture/data/fs/photo_file_sink.dart';

/// 2026-09-29 全 App 性能排查引入的三件东西，各自钉一个测试：
///   ① AsyncLimiter  —— 并发真的被压住了、且一个任务都不会丢
///   ② DeviceTier    —— 设备画像能正确分档（低配必须降级）
///   ③ 缩略图走原生  —— 原生可用时不该再整图解码
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const perfChannel = MethodChannel('gtick/perf');

  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(perfChannel, null);
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(perfChannel, null);
  });

  group('AsyncLimiter', () {
    test('并发不超过上限', () async {
      final limiter = AsyncLimiter(2);
      var running = 0;
      var peak = 0;
      final tasks = <Future<void>>[];
      for (var i = 0; i < 12; i++) {
        tasks.add(limiter.run(() async {
          running++;
          if (running > peak) peak = running;
          await Future<void>.delayed(const Duration(milliseconds: 5));
          running--;
        }));
      }
      await Future.wait(tasks);
      expect(peak, 2, reason: '闸门上限 2，任何时刻都不该有第 3 个在跑');
      expect(running, 0);
    });

    test('排队不丢任务（防并发不丢动作）', () async {
      final limiter = AsyncLimiter(1);
      final done = <int>[];
      final tasks = <Future<void>>[];
      for (var i = 0; i < 30; i++) {
        final n = i;
        tasks.add(limiter.run(() async {
          await Future<void>.delayed(const Duration(milliseconds: 1));
          done.add(n);
        }));
      }
      await Future.wait(tasks);
      expect(done.length, 30);
      expect(done.toSet().length, 30, reason: '每一个任务都必须跑到');
    });

    test('max 可在运行期调小（设备画像回来后降级）', () async {
      final limiter = AsyncLimiter(4);
      expect(limiter.pending, 0);
      limiter.max = 1;
      var peak = 0;
      var running = 0;
      final tasks = <Future<void>>[];
      for (var i = 0; i < 6; i++) {
        tasks.add(limiter.run(() async {
          running++;
          if (running > peak) peak = running;
          await Future<void>.delayed(const Duration(milliseconds: 2));
          running--;
        }));
      }
      await Future.wait(tasks);
      expect(peak, 1);
    });
  });

  group('DeviceTier 分档', () {
    Future<void> mockProfile(Map<String, Object?> p) async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(
              perfChannel, (call) async => call.method == 'deviceProfile' ? p : null);
    }

    test('2GB 低内存机判为 low（缩略图并发 1）', () async {
      await mockProfile({
        'totalMemMB': 2048,
        'memoryClassMB': 96,
        'lowRam': false,
        'cpuCores': 4,
        'sdkInt': 30,
      });
      await DeviceTier.init();
      expect(DeviceTier.current.klass, DeviceClass.low);
      expect(DeviceTier.current.thumbConcurrency, 1);
      expect(DeviceTier.current.galleryPageSize, lessThan(90));
    });

    test('系统标记 lowRam 一律 low', () async {
      await mockProfile({
        'totalMemMB': 8192,
        'memoryClassMB': 512,
        'lowRam': true,
        'cpuCores': 8,
        'sdkInt': 33,
      });
      await DeviceTier.init();
      expect(DeviceTier.current.klass, DeviceClass.low);
    });

    test('8GB 机判为 high', () async {
      await mockProfile({
        'totalMemMB': 8192,
        'memoryClassMB': 512,
        'lowRam': false,
        'cpuCores': 8,
        'sdkInt': 34,
      });
      await DeviceTier.init();
      expect(DeviceTier.current.klass, DeviceClass.high);
      expect(DeviceTier.current.thumbConcurrency, 3);
    });

    test('拿不到画像（桌面/通道异常）退回 mid，不冒险也不拖慢', () async {
      await mockProfile({
        'totalMemMB': 0,
        'memoryClassMB': 0,
        'lowRam': false,
        'cpuCores': 2,
        'sdkInt': 0,
      });
      await DeviceTier.init();
      expect(DeviceTier.current.klass, DeviceClass.mid);
    });
  });

  group('缩略图优先走原生', () {
    test('原生可用时不再整图解码（源文件不存在也能出结果）', () async {
      var nativeCalls = 0;
      final tmp = await Directory.systemTemp.createTemp('gtick_perf_thumb');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final outPath = '${tmp.path}/out.jpg';
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(perfChannel, (call) async {
        if (call.method != 'makeThumbs') return null;
        nativeCalls++;
        // 模拟原生实现：把缩略图真的写到 dstPath（非 0 字节），
        // 这样 验货（stat 非空）才会放行，返回的尺寸才是可信的。
        File(outPath).writeAsBytesSync([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10]);
        final jobs = (call.arguments as Map)['jobs'] as List;
        return [
          for (final _ in jobs) {'ok': true, 'w': 240, 'h': 180},
        ];
      });

      final size = await PhotoFileSink.makeThumbnail(
        srcPath: '${tmp.path}/does_not_exist.jpg',
        dstPath: outPath,
        longEdge: 256,
      );

      expect(nativeCalls, 1, reason: '必须走一次原生批量通道');
      expect(size, isNotNull);
      // v0.19.0 起返回 ThumbOutcome（带 luma），不再是 (int,int) record
      expect(size!.width, 240);
      expect(size.height, 180);
      // mock 原生没回 luma → null（没量到 ≠ 0，纪律 17）
      expect(size.luma, isNull);
    });

    test('原生失败时回退 isolate 且不抛', () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(
              perfChannel, (call) async => throw PlatformException(code: 'X'));

      final tmp = await Directory.systemTemp.createTemp('gtick_perf_fb');
      addTearDown(() => tmp.deleteSync(recursive: true));

      // 源文件不存在 —— 回退路径也只能返回 null，绝不能抛
      final size = await PhotoFileSink.makeThumbnail(
        srcPath: '${tmp.path}/nope.jpg',
        dstPath: '${tmp.path}/out.jpg',
      );
      expect(size, isNull);
    });
  });
}
