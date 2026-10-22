import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/core/serial_queue.dart';
import 'package:g_tick_picture/domain/capture/capture_service.dart';

/// 拍照流水线的地基（2026-10-09）。
///
/// 队列一旦不串行：文件名 seq 与入库顺序会漂；一旦会被错误掐断：
/// 一张写失败后面所有张都不写（现场表现为"连拍十几张最后只剩一张"）；
/// 一旦 drain 不准：退出采集时最后几张还在排队就被关批次了。
/// 这三条都会静默丢照片，所以逐条钉死。
void main() {
  test('按加入顺序执行，且同一时刻只有一个任务在跑', () async {
    final q = SerialQueue();
    final order = <int>[];
    var running = 0;
    var maxConcurrent = 0;

    for (var i = 0; i < 5; i++) {
      q.add(() async {
        running++;
        maxConcurrent = maxConcurrent > running ? maxConcurrent : running;
        await Future<void>.delayed(const Duration(milliseconds: 5));
        order.add(i);
        running--;
      });
    }

    await q.drain();
    expect(order, <int>[0, 1, 2, 3, 4], reason: 'seq 顺序必须与入队顺序一致');
    expect(maxConcurrent, 1, reason: '写盘/入库绝不能并发，否则 seq 会乱序');
    expect(q.pending, 0);
  });

  test('某个任务抛错：后面的任务照样跑完（一张写失败不能连坐）', () async {
    final q = SerialQueue();
    final done = <int>[];
    final errors = <Object>[];

    q.add(() async => done.add(1));
    q.add(
      () async => throw StateError('disk full'),
      onError: (e, _) => errors.add(e),
    );
    q.add(() async => done.add(3));

    await q.drain();
    expect(done, <int>[1, 3]);
    expect(errors.single, isStateError);
  });

  test('onError 自己抛错也不影响队列继续', () async {
    final q = SerialQueue();
    final done = <int>[];

    q.add(
      () async => throw StateError('boom'),
      onError: (_, __) => throw StateError('handler exploded'),
    );
    q.add(() async => done.add(2));

    await q.drain();
    expect(done, <int>[2]);
  });

  test('drain 等到最后一环（不等就是丢图）', () async {
    final q = SerialQueue();
    var finished = 0;

    q.add(() async {
      await Future<void>.delayed(const Duration(milliseconds: 20));
      finished++;
    });
    q.add(() async {
      await Future<void>.delayed(const Duration(milliseconds: 20));
      finished++;
    });

    await q.drain();
    expect(finished, 2, reason: '退出采集前 drain 必须等所有张落盘入库');
  });

  test('drain 后再加任务，再 drain 依然等到新的最后一环', () async {
    final q = SerialQueue();
    var finished = 0;
    q.add(() async => finished++);

    await q.drain();
    expect(finished, 1);

    q.add(() async => finished++);
    await q.drain();
    expect(finished, 2);
  });

  test('pending 在任务执行期间能反映"还在保存"', () async {
    final q = SerialQueue();
    expect(q.pending, 0);

    final gate = Completer<void>();
    q.add(() => gate.future);
    q.add(() async {});
    expect(q.pending, 2);

    gate.complete();
    await q.drain();
    expect(q.pending, 0);
  });

  group('失败提示口径（住在 domain，UI 与日志共用一份）', () {
    test('写盘失败：停采集 + 指名要查存储（不是"出错了"）', () {
      const e = CaptureError(CaptureErrorKind.write, 'no space');
      expect(e.hint, contains('已暂停拍摄'));
      expect(e.hint, contains('存储'));
    });

    test('单张没拍上：给出下一步动作', () {
      const e = CaptureError(CaptureErrorKind.shot, 'camera busy');
      expect(e.hint, contains('再按一次快门'));
    });

    test('连拍丢张：说清丢了多少张、能怎么补', () {
      const e = CaptureError(CaptureErrorKind.burstDropped, 'x', count: 3);
      expect(e.hint, contains('3 张'));
      expect(e.hint, contains('再连拍'));
    });

    test('丢张数缺失时不能出现"null 张"这种半个词', () {
      const e = CaptureError(CaptureErrorKind.burstDropped, 'x');
      expect(e.hint, isNot(contains('null')));
      expect(e.hint, contains('0 张'));
    });
  });
}