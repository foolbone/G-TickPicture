import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/core/constants.dart';
import 'package:g_tick_picture/data/fs/storage_service.dart';

/// 存储预检的规格说明（§8.2）。
///
/// 这组用例最想守住的是一条**克制**：
/// **查不到空间 ≠ 空间不足。** 查不到时必须保持沉默，
/// 绝不能把"我没查到"渲染成"你要满了"去吓现场的人。
void main() {
  group('StorageAudit · 判定语义', () {
    StorageAudit make({
      required int free,
      required int required,
      bool unknown = false,
    }) =>
        StorageAudit(
          freeBytes: free,
          requiredBytes: required,
          unknown: unknown,
        );

    test('空间够 → enough', () {
      expect(make(free: 10_000, required: 5_000).enough, isTrue);
    });

    test('刚好等于所需 → 也算够（边界含等于）', () {
      expect(make(free: 5_000, required: 5_000).enough, isTrue);
    });

    test('空间不足 → not enough', () {
      expect(make(free: 1_000, required: 5_000).enough, isFalse);
    });

    test('查不到 + freeBytes = -1 → 仍然算够（不拦人）', () {
      final a = make(free: -1, required: 5_000, unknown: true);
      expect(a.unknown, isTrue);
      expect(a.enough, isTrue);
    });

    test('unknown 优先于数字 —— 即使 -1 < required 也不报不足', () {
      // 这是最容易写反的一条：如果实现成 pure 数值比较，
      // -1 >= 5000 为 false → 每次进采集页都弹"空间不足"，现场直接没法用。
      expect(make(free: -1, required: 999_999_999, unknown: true).enough, isTrue);
    });
  });

  group('StorageService.humanBytes', () {
    test('负数是"未知"，不是"-1 B"', () {
      expect(StorageService.humanBytes(-1), '未知');
    });

    test('0 字节', () {
      expect(StorageService.humanBytes(0), '0 B');
    });

    test('B / KB / MB / GB 换算', () {
      expect(StorageService.humanBytes(512), '512 B');
      expect(StorageService.humanBytes(2048), '2.0 KB');
      expect(StorageService.humanBytes(5 * 1024 * 1024), '5.0 MB');
      expect(StorageService.humanBytes(3 * 1024 * 1024 * 1024), '3.0 GB');
    });

    test('大于 100 的数值不带小数位（避免"1234.5 MB"这种噪声）', () {
      expect(StorageService.humanBytes(200 * 1024 * 1024), '200 MB');
    });
  });

  group('StorageService.audit · 估算口径', () {
    test('所需 = 单张估算 × 张数 × 余量倍数', () async {
      final tmp = await Directory.systemTemp.createTemp('gt_storage_');
      addTearDown(() async {
        if (tmp.existsSync()) await tmp.delete(recursive: true);
      });

      final a = await StorageService.audit(
        projectRootPath: tmp.path,
        expectedPhotos: 400,
        bytesPerPhoto: 1000,
      );
      final expected =
          (1000 * 400 * AppConst.captureFreeSpaceFactor).round();
      expect(a.requiredBytes, expected);
    });

    test('张数为 0（还没拍）时不按 0 算，避免一进页面就报"空间不足"', () async {
      final tmp = await Directory.systemTemp.createTemp('gt_storage_');
      addTearDown(() async {
        if (tmp.existsSync()) await tmp.delete(recursive: true);
      });

      final a = await StorageService.audit(
        projectRootPath: tmp.path,
        expectedPhotos: 0,
        bytesPerPhoto: 1000,
      );
      // 走默认试算张数（200），所以所需必然 > 0
      expect(a.requiredBytes, greaterThan(0));
    });

    test('真实可写目录 → enough 为 true（放行）、unknown（给不出精确数）、无残留探针', () async {
      final tmp = await Directory.systemTemp.createTemp('gt_storage_');
      addTearDown(() async {
        if (tmp.existsSync()) await tmp.delete(recursive: true);
      });

      final a = await StorageService.audit(
        projectRootPath: tmp.path,
        expectedPhotos: 400,
      );

      // 核心语义：探针能写 = 能拍。但"能拍"不等于"知道还剩多少 GB"——
      // 纯 Dart 拿不到精确余量，所以标 unknown（沉默），【绝不】给一个小数字：
      // 那会让 enough 误判为 false，把能拍的现场拦在门外（此 bug 被本组用例抓过）。
      expect(a.enough, isTrue, reason: '探针写成功了就必须放行');
      expect(a.unknown, isTrue, reason: '给不出精确余量时必须沉默，而不是编一个数');
      // 探针必须被清掉 —— 否则会有个 4MB 的垃圾文件跟着项目走
      final leftovers = tmp
          .listSync()
          .where((e) => e.path.endsWith('.space_probe'))
          .toList();
      expect(leftovers, isEmpty);
    });

    test('目录不存在时会自动创建（首次进采集页的常见情形）', () async {
      final base = await Directory.systemTemp.createTemp('gt_storage_');
      addTearDown(() async {
        if (base.existsSync()) await base.delete(recursive: true);
      });

      final nested = '${base.path}${Platform.pathSeparator}a'
          '${Platform.pathSeparator}b${Platform.pathSeparator}c';
      expect(Directory(nested).existsSync(), isFalse);

      await StorageService.audit(projectRootPath: nested, expectedPhotos: 10);
      expect(Directory(nested).existsSync(), isTrue);
    });
  });
}
