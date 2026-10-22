import 'dart:async';

/// 串行任务队列：后进先出地**排队**执行，某一环抛错不会掐断链。
///
/// ── 为什么需要它（2026-10-09 拍照链路体检）──────────────────────
/// 拍照天然是"一条流水"：相机取帧 → 写文件 → 入库 → 异步副作用。
/// 直觉写法是 `await` 到底再拍下一张，但那样**主 isolate 会被磁盘卡住**，
/// 连拍时后续张还会因为"上一张还在忙"被静默丢弃。
///
/// 所以采集服务改成：`await` 只到取帧（真正必须等的相机动作），
/// 后面所有落盘/入库都 `add()` 到这里，串行执行：
///   · 串行 = 文件名里的 seq 与入库顺序严格一致（并发会乱序）；
///   · 错误隔离 = 某张写失败不该让后面的张一起不写；
///   · [drain] = 退出采集前等队列排空，否则最后几张还在队列里就被
///     endSession 关掉了批次（进度丢图）。
class SerialQueue {
  Future<void> _tail = Future<void>.value();
  var _pending = 0;

  /// 尚未完成的任务数（含正在执行的）。UI 用它提示"正在保存…"。
  int get pending => _pending;

  /// 排一个任务。[task] 抛出的错交给 [onError]，**不会**中断后续任务。
  void add(Future<void> Function() task, {void Function(Object, StackTrace)? onError}) {
    _pending++;
    _tail = _tail.then((_) async {
      try {
        await task();
      } catch (e, st) {
        try {
          onError?.call(e, st);
        } catch (_) {
          // onError 自己抛错也不能影响队列继续跑
        }
      }
    }).whenComplete(() => _pending--);
  }

  /// 等队列排空。连续调用会一直等到当前最后一环结束。
  Future<void> drain() => _tail;
}