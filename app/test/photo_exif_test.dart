/// [PhotoExif] 的规格说明（M2.1 / §5.3.1 规则 5 的输入质量）。
///
/// 核心主张：**EXIF 读不到绝不抛异常** —— 导入不能因为一张损坏的
/// 照片失败；时间解析不出来就退化用文件修改时间，那是调用方的事。

// 超时放宽到 2 分钟（库级注解 —— @Timeout 只能标 library/group/test，
// 挂在 main() 上是 invalid_annotation_target）：全量测试时导出压测
// （1000 张真打 ZIP）会把 CPU 吃满，本文件的用例被饿 30 秒就撞
// flutter_test 默认超时 —— 2026-10-01 发版门禁就是挂在这一点上。
@Timeout(Duration(minutes: 2))
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/fs/photo_exif.dart';
import 'package:image/image.dart' as img;

void main() {
  late Directory tmp;

  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('gt_exif_');
  });
  tearDown(() async {
    // 尽力而为的清理：Windows 上刚写完的文件可能仍被句柄/杀软索引
    // 短暂占用（errno 32），立即删必报 PathAccessException ——
    // 2026-10-01 发版 flaky 的根因。重试几轮，仍删不掉就放弃
    // （留在 systemTemp 由系统回收，不值得为它红一次门禁）。
    for (var i = 0; i < 5; i++) {
      try {
        if (!tmp.existsSync()) return;
        await tmp.delete(recursive: true);
        return;
      } on FileSystemException {
        await Future<void>.delayed(const Duration(milliseconds: 200));
      }
    }
  });

  /// 造一张带 EXIF 的 JPEG。
  Future<File> jpegWithExif(
    String name, {
    String? dateTimeOriginal,
    String? dateTime,
  }) async {
    final image = img.Image(width: 8, height: 8);
    if (dateTimeOriginal != null) {
      image.exif.exifIfd['DateTimeOriginal'] = dateTimeOriginal;
    }
    if (dateTime != null) {
      image.exif.imageIfd['DateTime'] = dateTime;
    }
    final bytes = img.encodeJpg(image, quality: 80);
    final f = File('${tmp.path}${Platform.pathSeparator}$name');
    await f.writeAsBytes(bytes, flush: true);
    return f;
  }

  group('读得出来', () {
    test('DateTimeOriginal 优先 —— 这是快门时刻', () async {
      final f = await jpegWithExif('a.jpg',
          dateTimeOriginal: '2026:09:23 10:30:00');
      expect(await PhotoExif.takenAt(f.path),
          DateTime(2026, 9, 23, 10, 30, 0));
    });

    test('只有 IFD0 的 DateTime 时作为次选', () async {
      final f = await jpegWithExif('b.jpg', dateTime: '2026:09:23 08:00:05');
      expect(await PhotoExif.takenAt(f.path), DateTime(2026, 9, 23, 8, 0, 5));
    });

    test('两者都有时 DateTimeOriginal 赢', () async {
      final f = await jpegWithExif('c.jpg',
          dateTimeOriginal: '2026:09:23 10:30:00',
          dateTime: '2026:09:23 08:00:05');
      expect(await PhotoExif.takenAt(f.path),
          DateTime(2026, 9, 23, 10, 30, 0));
    });

    test('容忍厂商的非标分隔符与时区尾巴', () async {
      for (final raw in const [
        '2026-09-23 10:30:00', // 常见安卓变体
        '2026/09/23 10:30:00', // 少数厂商
        '2026:09:23 10:30:00 ', // 尾随空格
      ]) {
        final f = await jpegWithExif('v_${raw.hashCode}.jpg',
            dateTimeOriginal: raw);
        expect(
          await PhotoExif.takenAt(f.path),
          DateTime(2026, 9, 23, 10, 30, 0),
          reason: '"$raw" 应该能解析',
        );
      }
    });
  });

  group('读不出来 → 一律 null（绝不抛）', () {
    test('没有 EXIF 的 JPEG', () async {
      final image = img.Image(width: 8, height: 8);
      final f = File('${tmp.path}${Platform.pathSeparator}plain.jpg');
      await f.writeAsBytes(img.encodeJpg(image));

      expect(await PhotoExif.takenAt(f.path), isNull);
    });

    test('PNG（decodeJpgExif 不认的格式）', () async {
      final image = img.Image(width: 8, height: 8);
      final f = File('${tmp.path}${Platform.pathSeparator}x.png');
      await f.writeAsBytes(img.encodePng(image));

      expect(await PhotoExif.takenAt(f.path), isNull);
    });

    test('文件不存在', () async {
      expect(
        await PhotoExif.takenAt(
            '${tmp.path}${Platform.pathSeparator}nope.jpg'),
        isNull,
      );
    });

    test('损坏的字节流', () async {
      final f = File('${tmp.path}${Platform.pathSeparator}bad.jpg');
      await f.writeAsBytes([0xFF, 0xD8, 0xFF, 0x00, 0x01, 0x02]);

      expect(await PhotoExif.takenAt(f.path), isNull);
    });
  });

  group('时间字符串的宽进严出', () {
    test('垃圾时刻（1970 时钟重置）不返回', () async {
      final f = await jpegWithExif('y1970.jpg',
          dateTimeOriginal: '1970:01:01 00:00:00');
      // 2000 以下的年份必是没电的相机时钟，用它聚类是噪声 → null
      expect(await PhotoExif.takenAt(f.path), isNull);
    });

    test('月/日越界不返回（DateTime 构造会静默进位，必须挡住）', () async {
      final f =
          await jpegWithExif('m13.jpg', dateTimeOriginal: '2026:13:40 25:61:61');
      expect(await PhotoExif.takenAt(f.path), isNull);
    });
  });
}
