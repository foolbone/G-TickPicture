/// 系统相机连拍会话（2026-10-15 v0.24.2）的数据解析。
///
/// 只测纯函数那一半 —— 原生桥（MediaStore 基线/增量查询）与通道往返
/// 要真机；这里钉住的是「脏数据绝不能炸整批收图」的解析契约。
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/capture/system_camera_service.dart';

void main() {
  group('SystemSessionShot.fromMap', () {
    test('正常项：path + dateTakenMs（毫秒）', () {
      final s = SystemSessionShot.fromMap({
        'path': '/storage/emulated/0/DCIM/Camera/IMG_001.jpg',
        'dateTakenMs': 1760000000000,
      });
      expect(s, isNotNull);
      expect(s!.path, '/storage/emulated/0/DCIM/Camera/IMG_001.jpg');
      expect(s.takenAt, DateTime.fromMillisecondsSinceEpoch(1760000000000));
    });

    test('DATE_TAKEN 为 null（个别图没有拍摄时刻）→ takenAt=null 不炸', () {
      final s = SystemSessionShot.fromMap({
        'path': '/storage/emulated/0/DCIM/Camera/IMG_002.jpg',
        'dateTakenMs': null,
      });
      expect(s, isNotNull);
      expect(s!.takenAt, isNull);
    });

    test('dateTakenMs 非 int / 非正数 → 一律当没有时刻处理', () {
      for (final bad in ['x', 0, -5, 1.5]) {
        final s = SystemSessionShot.fromMap({
          'path': '/a.jpg',
          'dateTakenMs': bad,
        });
        expect(s, isNotNull, reason: 'path 有效就不该丢弃，坏的是时刻');
        expect(s!.takenAt, isNull, reason: 'bad=$bad');
      }
    });

    test('path 缺失 / 为空 / 非 String → 整项丢弃（返回 null）', () {
      expect(SystemSessionShot.fromMap({'dateTakenMs': 1}), isNull);
      expect(SystemSessionShot.fromMap({'path': '', 'dateTakenMs': 1}), isNull);
      expect(
        SystemSessionShot.fromMap({'path': 123, 'dateTakenMs': 1}),
        isNull,
      );
    });

    test('非 Map 项 / null → 丢弃不炸（第二道防）', () {
      expect(SystemSessionShot.fromMap('junk'), isNull);
      expect(SystemSessionShot.fromMap(null), isNull);
      expect(SystemSessionShot.fromMap(42), isNull);
    });
  });
}
