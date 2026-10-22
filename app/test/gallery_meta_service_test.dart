import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/capture/gallery_meta_service.dart';

/// [GalleryMetaService] 的通道契约测试。
///
/// 原生侧（GalleryBridge.queryDateTakenByNames）无法在单测里跑，
/// 这里 mock `gtick/gallery` 通道，锁定 Dart 侧的三条纪律：
///  1. 毫秒 → DateTime、0 → null 的映射不变形；
///  2. 结果比请求短时按下标安全退化（不抛 RangeError）；
///  3. 原生任何异常 → 整批 null（时间查不到只影响分组质量，
///     绝不能让导入失败 —— 与 PhotoExif 同一条纪律）。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('gtick/gallery');
  const service = GalleryMetaService();

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('毫秒映射为时刻、0 映射为 null；请求参数带原始文件名与大小', () async {
    Object? receivedArgs;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      expect(call.method, 'queryDateTakenByNames');
      receivedArgs = call.arguments;
      return <Object?>[1790000000000, 0, 1790000005000];
    });

    final items = <({String name, int sizeBytes})>[
      (name: 'IMG_20260923_151701.jpg', sizeBytes: 3145728),
      (name: 'mmexport1758900000000.jpg', sizeBytes: 1048576),
      (name: 'IMG_20260923_151707.jpg', sizeBytes: 2097152),
    ];

    final result = await service.dateTakenByNames(items);

    // 请求参数：与选择结果同序，逐张带 name + size
    final list = receivedArgs! as Map<Object?, Object?>;
    final sent = list['items']! as List<Object?>;
    expect(sent, hasLength(3));
    expect(sent[0], {'name': 'IMG_20260923_151701.jpg', 'size': 3145728});
    expect(sent[2], {'name': 'IMG_20260923_151707.jpg', 'size': 2097152});

    // 结果：与请求按下标对齐；0 = 媒体库没记时间 → null
    expect(result, hasLength(3));
    expect(result[0], DateTime.fromMillisecondsSinceEpoch(1790000000000));
    expect(result[1], isNull);
    expect(result[2], DateTime.fromMillisecondsSinceEpoch(1790000005000));
  });

  test('空请求直接返回空，不碰通道', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      fail('空请求不应该触发原生调用');
    });
    expect(await service.dateTakenByNames(const []), isEmpty);
  });

  test('结果比请求短：缺的下标安全退化为 null（不抛 RangeError）', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      return <Object?>[1790000000000]; // 只回了 1 个，请求 3 个
    });

    final result = await service.dateTakenByNames(const [
      (name: 'a.jpg', sizeBytes: 1),
      (name: 'b.jpg', sizeBytes: 2),
      (name: 'c.jpg', sizeBytes: 3),
    ]);

    expect(result, hasLength(3));
    expect(result[0], DateTime.fromMillisecondsSinceEpoch(1790000000000));
    expect(result[1], isNull);
    expect(result[2], isNull);
  });

  test('原生报错：整批 null（与请求等长），绝不把异常抛给导入流程', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      throw PlatformException(code: 'QUERY_ERROR', message: '查询失败');
    });

    final result = await service.dateTakenByNames(const [
      (name: 'a.jpg', sizeBytes: 1),
      (name: 'b.jpg', sizeBytes: 2),
    ]);

    expect(result, hasLength(2));
    expect(result, everyElement(isNull));
  });
}
