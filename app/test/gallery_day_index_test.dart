// v0.20.0（2026-10-12）日期过滤的时间归一化单测。
//
// 坑的出处（方案 v3 核对）：SQLite 归日是 UTC，国内差 8 小时——早上 8 点
// 前拍的照片会归到「前一天」。修复口径 = 本地天序号
// `(本地午夜 ms + 时区偏移) / 86400000`，Dart 与原生 Kotlin 两侧严格一致。
// 这里钉死 Dart 侧公式：任意时区下，[dayIndexOf] 必须等于
// 「该日 00:00 UTC」的标准天序号。
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/capture/native_gallery_service.dart';

void main() {
  group('dayIndexOf（本地天序号，Dart/Kotlin 归日同源）', () {
    test('任意日期的本地天序号 == 该日 UTC 午夜的标准天序号', () {
      for (final d in [
        DateTime(2026, 9, 24),
        DateTime(2026, 1, 1),
        DateTime(2026, 10, 12),
        DateTime(1970, 1, 2), // epoch 边界后一天
      ]) {
        final expected = DateTime.utc(d.year, d.month, d.day)
                .millisecondsSinceEpoch ~/
            Duration.millisecondsPerDay;
        expect(
          NativeGalleryService.dayIndexOf(d),
          expected,
          reason: '$d 归日漂移 —— Dart/Kotlin 两侧归日公式不一致会导致'
              '「选 A 天高亮 B 天」的错位',
        );
      }
    });

    test('相邻日期序号差 1（跨天连续性）', () {
      final a = NativeGalleryService.dayIndexOf(DateTime(2026, 9, 24));
      final b = NativeGalleryService.dayIndexOf(DateTime(2026, 9, 25));
      expect(b - a, 1);
    });

    test('天序号可逆：序号 + 偏移还原回本地当天 0 点附近（±1 天内）', () {
      // 与 _dayFromIndex 同公式：验证序号往返不跨天（时区偏移对称性）
      final d = DateTime(2026, 9, 24);
      final idx = NativeGalleryService.dayIndexOf(d);
      final restored = DateTime.fromMillisecondsSinceEpoch(
        idx * Duration.millisecondsPerDay -
            DateTime.now().timeZoneOffset.inMilliseconds,
      );
      expect(
        restored.difference(DateTime(d.year, d.month, d.day)).inHours.abs(),
        lessThan(24),
        reason: '往返应落在本地当天附近（谓词比较只依赖 dayIndexOf 一致性，'
            '此断言防公式被改坏后静默漂移）',
      );
    });
  });
}
