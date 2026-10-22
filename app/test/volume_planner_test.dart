import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/export/volume_planner.dart';

/// 分卷规划（老板 2026-09-30 拍板：微信单文件 1GB 上限 → 500MB 分卷）。
///
/// 纯函数测试 —— 打包端到端行为在 export_service_test.dart 里测。
void main() {
  group('planVolumes', () {
    test('空列表 → 不产生卷', () {
      expect(planVolumes(const [], 100), isEmpty);
    });

    test('总量不超限 → 单卷且保序', () {
      final v = planVolumes(const [10, 20, 30], 100);
      expect(v.length, 1);
      expect(v.single, [0, 1, 2]);
    });

    test('恰好压线 → 不切（sum + size > limit 才切）', () {
      final v = planVolumes(const [50, 50], 100);
      expect(v.length, 1, reason: '50+50 == 100，等于上限不超，应同卷');
    });

    test('超限 → 按顺序贪心切卷', () {
      final v = planVolumes(const [40, 40, 40], 100);
      expect(v.length, 2);
      expect(v[0], [0, 1]); // 80
      expect(v[1], [2]); // 40：80+40=120 > 100 → 新卷
    });

    test('单文件超限 → 独占一卷，后续照常装填', () {
      final v = planVolumes(const [10, 500, 10], 100);
      expect(v.length, 3);
      expect(v[0], [0]);
      expect(v[1], [1], reason: '超限文件独占一卷，不能卡死规划');
      expect(v[2], [2]);
    });

    test('连续多个超限文件 → 各自独占一卷', () {
      final v = planVolumes(const [999, 999, 999], 100);
      expect(v.length, 3);
      for (final vol in v) {
        expect(vol.length, 1);
      }
    });

    test('所有下标不重不漏且各卷升序', () {
      final sizes = [for (var i = 0; i < 100; i++) i * 7 + 1];
      final v = planVolumes(sizes, 300);
      final all = [for (final vol in v) ...vol]..sort();
      expect(all, [for (var i = 0; i < 100; i++) i]);
      for (final vol in v) {
        expect(vol, orderedEquals(vol.toList()..sort()));
      }
    });

    test('limit 必须 > 0', () {
      expect(() => planVolumes(const [1], 0), throwsA(isA<AssertionError>()));
    });
  });
}
