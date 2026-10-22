// v0.19.0（2026-10-10）缩略图亮度（luma）单测。
//
// 桌面测试环境没有原生通道 → makeThumbnails 必然走 isolate 回退路径
// （_viaIsolate → _generate → _avgLuma），正好把 429 中断时补上的
// Dart 侧算亮度代码完整覆盖到。原生路径的口径一致性由 PerfBridge.kt
// 注释 + 真机复测兜底（同一 Rec.601 公式）。
//
// 断言口径：纯黑图 luma ≈ 0（JPEG 压缩伪影给 <20 的余量），
// 纯白图 luma ≈ 255（同理 >235），且 白 > 黑 —— 防止有人把公式
// 写反或忘了归一。
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/fs/photo_file_sink.dart';
import 'package:image/image.dart' as img;
import 'package:path/path.dart' as p;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory temp;

  setUp(() async {
    temp = await Directory.systemTemp.createTemp('gtick_luma_test');
  });

  tearDown(() async {
    try {
      if (await temp.exists()) await temp.delete(recursive: true);
    } catch (_) {/* 临时目录删不掉不影响结论 */}
  });

  Future<String> makeJpg(String name, img.Image image) async {
    final path = p.join(temp.path, name);
    await File(path).writeAsBytes(img.encodeJpg(image, quality: 78));
    return path;
  }

  test('纯黑图：luma 接近 0（非 null —— 没量到才是 null）', () async {
    final src = await makeJpg(
      'black.jpg',
      img.Image(width: 64, height: 48)..clear(img.ColorRgb8(0, 0, 0)),
    );
    final dst = p.join(temp.path, 'black_thumb.jpg');

    final r = await PhotoFileSink.makeThumbnail(srcPath: src, dstPath: dst);

    expect(r, isNotNull, reason: '缩略图生成本身必须成功');
    expect(r!.luma, isNotNull, reason: 'isolate 回退路径必须量出亮度');
    expect(r.luma!, lessThan(20));
  });

  test('纯白图：luma 接近 255，且 白 > 黑（公式没写反）', () async {
    final src = await makeJpg(
      'white.jpg',
      img.Image(width: 64, height: 48)..clear(img.ColorRgb8(255, 255, 255)),
    );
    final dst = p.join(temp.path, 'white_thumb.jpg');

    final white = await PhotoFileSink.makeThumbnail(srcPath: src, dstPath: dst);
    final black = await PhotoFileSink.makeThumbnail(
      srcPath: await makeJpg(
        'black2.jpg',
        img.Image(width: 64, height: 48)..clear(img.ColorRgb8(0, 0, 0)),
      ),
      dstPath: p.join(temp.path, 'black2_thumb.jpg'),
    );

    expect(white, isNotNull);
    expect(white!.luma, greaterThan(235));
    expect(black, isNotNull);
    expect(white.luma!, greaterThan(black!.luma ?? -1));
  });

  test('原图一个字节都不许动（取证原始性：luma 只读不改）', () async {
    final srcPath = await makeJpg(
      'orig.jpg',
      img.Image(width: 64, height: 48)..clear(img.ColorRgb8(120, 120, 120)),
    );
    final before = await File(srcPath).readAsBytes();
    final dst = p.join(temp.path, 'orig_thumb.jpg');

    await PhotoFileSink.makeThumbnail(srcPath: srcPath, dstPath: dst);

    final after = await File(srcPath).readAsBytes();
    expect(after.length, before.length);
    // 逐字节比对 —— 亮度统计绝不允许碰原图（任何"顺手优化"都不行）
    for (var i = 0; i < before.length; i++) {
      if (before[i] != after[i]) {
        fail('原图被修改 @byte $i —— luma 统计污染了取证原件');
      }
    }
  });
}
