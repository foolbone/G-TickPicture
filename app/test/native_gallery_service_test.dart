import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/capture/native_gallery_service.dart';

/// 原生侧（GalleryBridge 的 queryGalleryImages / galleryThumb / readGalleryImages）
/// 无法在单测里跑，这里用 mock MethodChannel 验证 Dart 侧的「解析层」：
/// 通道返回的 Map 能不能正确翻成域模型，特别是 dateTakenMs=0 → null 的退化。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('gtick/gallery');

  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      switch (call.method) {
        case 'queryGalleryImages':
          return [
            {
              'id': 1,
              'displayName': 'a.jpg',
              'dateTakenMs': 1700000000000,
              'sizeBytes': 100,
              'mimeType': 'image/jpeg',
              'bucket': 'Camera',
            },
            {
              'id': 2,
              'displayName': 'b.png',
              'dateTakenMs': 0,
              'sizeBytes': 200,
              'mimeType': 'image/png',
              'bucket': 'WeiXin',
            },
          ];
        case 'queryGalleryBuckets':
          return [
            {'bucket': 'Camera', 'count': 5},
            {'bucket': 'WeiXin', 'count': 3},
          ];
        case 'galleryThumb':
          return Uint8List.fromList([1, 2, 3]);
        case 'galleryStatus':
          return {'sdkInt': 34, 'granted': true, 'fullAccess': false};
        case 'readGalleryImages':
          final ids = (call.arguments as Map)['ids'] as List;
          return ids
              .map((e) => {
                    'id': e,
                    'tempPath': '/tmp/$e.jpg',
                    'displayName': '$e.jpg',
                    'sizeBytes': 10,
                    'dateTakenMs': 1700000000000,
                  })
              .toList();
        default:
          return null;
      }
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('queryImages 解析 + dateTakenMs=0 退化 null', () async {
    final list = await const NativeGalleryService().queryImages();
    expect(list.length, 2);
    expect(list[0].id, 1);
    expect(list[0].dateTaken,
        DateTime.fromMillisecondsSinceEpoch(1700000000000));
    expect(list[1].dateTaken, isNull);
    expect(list[1].mimeType, 'image/png');
    expect(list[0].bucket, 'Camera');
  });

  test('queryBuckets 解析', () async {
    final list = await const NativeGalleryService().queryBuckets();
    expect(list.length, 2);
    expect(list[0].name, 'Camera');
    expect(list[0].count, 5);
    expect(list[1].name, 'WeiXin');
  });

  test('thumbnail 透传字节', () async {
    final bytes = await const NativeGalleryService().thumbnail(1);
    expect(bytes, isNotNull);
    expect(bytes!.length, 3);
  });

  test('readImages 解析并带真实拍摄时刻', () async {
    final res = await const NativeGalleryService().readImages([7, 8]);
    expect(res.length, 2);
    expect(res[0].tempPath, '/tmp/7.jpg');
    expect(res[0].dateTaken,
        DateTime.fromMillisecondsSinceEpoch(1700000000000));
  });

  test('galleryStatus 解析 + partial 判定（Android 14 部分授权）', () async {
    final st = await const NativeGalleryService().galleryStatus();
    expect(st.sdkInt, 34);
    expect(st.granted, isTrue);
    expect(st.fullAccess, isFalse);
    expect(st.partial, isTrue);
  });
}
