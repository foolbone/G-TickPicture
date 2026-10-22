import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/capture/gallery_service.dart';
import 'package:g_tick_picture/domain/model/gallery_photo.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// GalleryService 的单测 —— 重点覆盖「幂等去重」契约（P4-7）。
///
/// 桌面单测里 `Platform.isAndroid` 恒为 false，会提前静默降级，
/// 所以全部用 `platformIsAndroidForTest: true` 注入，走 mock 通道。
///
/// ⚠️ mock handler 会接到 **status 和 savePhoto 两种调用**：
/// 每个用例必须先分流 status（status 无参数，且 invokeMapMethod
/// 对返回类型有 Map 约束 —— 返回裸字符串会在解码处抛 TypeError，
/// 被 messenger 包成 code='error' 的 PlatformException）。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('gtick/gallery');
  final calls = <MethodCall>[];

  /// 每个用例自己设置的原生行为；null 时原生返回 null（不应发生）。
  Object? Function(MethodCall call)? handler;

  setUp(() {
    calls.clear();
    handler = null;
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return handler?.call(call);
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  GalleryService build() => GalleryService(platformIsAndroidForTest: true);

  GalleryPhoto ph(String name) =>
      GalleryPhoto(srcPath: '/private/$name', displayName: name);

  /// status 的正常应答：Android 10+ 免权限路径。
  Map<Object?, Object?> statusOk() => {'needsPermission': false, 'granted': true};

  /// MethodCall.arguments 是 dynamic —— 统一在这里收敛转型，
  /// 避免 avoid_dynamic_calls 噪声。
  Map<Object?, Object?> argsOf(MethodCall call) =>
      call.arguments as Map<Object?, Object?>;

  group('GalleryService', () {
    test('开关默认开（老板硬需求）', () async {
      expect(await build().isEnabled, isTrue);
    });

    test('saveAll 按 saved / skipped / failed 三档计数', () async {
      handler = (call) async {
        if (call.method == 'status') return statusOk();
        switch (argsOf(call)['displayName'] as String) {
          case 'a.jpg':
            return {'saved': true, 'uri': 'content://media/1'};
          case 'b.jpg':
            // 已在相册里 —— 幂等跳过，不是失败
            return {'saved': false, 'uri': 'content://media/2'};
          default:
            throw PlatformException(code: 'IO_ERROR', message: 'boom');
        }
      };
      final r = await build().saveAll(
        [ph('a.jpg'), ph('b.jpg'), ph('c.jpg')],
        album: 'P1',
      );
      expect(r.saved, 1);
      expect(r.skipped, 1);
      expect(r.failed, 1);
      expect(r.reason, contains('IO_ERROR'));
    });

    test('save：skipped 不算失败（幂等跳过语义）', () async {
      handler = (call) async {
        if (call.method == 'status') return statusOk();
        return {'saved': false, 'uri': 'content://media/9'};
      };
      final r = await build().save(srcPath: '/private/a.jpg', album: 'P1');
      expect(r.skipped, 1);
      expect(r.failed, 0);
      expect(r.isEmpty, isFalse);
    });

    test('防御旧契约：savePhoto 返回 uri 字符串视为已写入', () async {
      handler = (call) async {
        if (call.method == 'status') return statusOk();
        return 'content://media/legacy';
      };
      final r = await build().saveAll([ph('a.jpg')], album: 'P1');
      expect(r.saved, 1);
      expect(r.skipped, 0);
    });

    test('savePhoto 参数：album 走 safeFolderName，且逐张串行保序', () async {
      final order = <String>[];
      handler = (call) async {
        if (call.method == 'status') return statusOk();
        order.add(argsOf(call)['displayName'] as String);
        return {'saved': true, 'uri': 'content://media/x'};
      };
      await build().saveAll([ph('2.jpg'), ph('1.jpg')], album: '项目:A/B');
      expect(order, ['2.jpg', '1.jpg']);
      expect(argsOf(calls.firstWhere((c) => c.method == 'savePhoto'))['album'],
          '项目_A_B');
    });

    test('权限被拒 → 全部计失败、不触发 savePhoto', () async {
      handler = (call) async {
        if (call.method == 'status') {
          return {'needsPermission': true, 'granted': false};
        }
        fail('未获得权限时不应走到 savePhoto');
      };
      final r = await build().saveAll([ph('a.jpg')], album: 'P1');
      expect(r.saved, 0);
      expect(r.failed, 1);
      expect(r.reason, isNotNull);
    });

    test('非 Android 平台静默降级（不碰通道）', () async {
      final r = await GalleryService(platformIsAndroidForTest: false)
          .saveAll([ph('a.jpg')], album: 'P1');
      expect(r.isEmpty, isTrue);
      expect(r.reason, isNotNull);
      expect(calls, isEmpty);
    });
  });
}
