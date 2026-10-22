import 'dart:async';

/// 并发闸门 —— 限制同时跑的重活数量（2026-09-29 全 App 性能排查）。
///
/// 为什么需要：导入 100 张照片时，旧代码对每一张都 `unawaited(_enrich(...))`，
/// 等于同时发起 100 个缩略图任务。在 Dart 侧每个任务都要 `Isolate.run`
/// 整图解码一张 4000×3000 的 JPEG（峰值 ~48MB 像素缓冲）—— 低配机上
/// 就是内存触顶 + GC 抖动 + 界面卡死，用户看到的现象正是"选多了就变慢"。
///
/// 闸门只放行 [max] 个，其余排队。排队**不丢任务**（防并发不丢动作，
/// 见工程铁律 6）。
class AsyncLimiter {
  AsyncLimiter(this.max);

  /// 同时运行的上限。可在运行期调整（设备画像拿到后回写）。
  int max;

  var _running = 0;
  final _waiting = <Completer<void>>[];

  /// 当前排队 + 运行中的任务数（诊断用）。
  int get pending => _waiting.length + _running;

  Future<T> run<T>(Future<T> Function() body) async {
    if (_running >= max && max > 0) {
      final c = Completer<void>();
      _waiting.add(c);
      await c.future;
    }
    _running++;
    try {
      return await body();
    } finally {
      _running--;
      _release();
    }
  }

  void _release() {
    if (_waiting.isEmpty) return;
    final c = _waiting.removeAt(0);
    if (!c.isCompleted) c.complete();
  }
}
