/// 交付分卷规划 —— 老板 2026-09-30 拍板（微信单文件 1GB 上限）。
///
/// 纯函数、零 IO：输入按交付顺序排列的文件字节数与单卷上限，
/// 输出每卷包含的**下标**列表。规则：
///
/// 1. **贪心装填**：按顺序往当前卷里放，放不下（累计会超限）就开新卷。
///    保序 —— 第 1 卷永远是交付顺序里最靠前的照片，报告员按卷号顺序
///    解压就是完整流程。
/// 2. **绝不拆文件**：一张照片要么整个进某卷，要么整个进下一卷。
/// 3. **单文件超限独占一卷**：比如关掉压缩时的 20MB 原图不会卡死
///    规划器 —— 它自己占一卷，哪怕这一卷超了上限（物理上没法再小，
///    让打包继续，别让一张大图毁掉整次交付）。
library;

/// 按累计字节贪心分卷。
///
/// [byteSizes] 与交付顺序一一对应；[limit] 为单卷字节上限（必须 > 0）。
/// 返回值本身有序：`result[0]` 是第 1 卷，内含的是**下标**（升序）。
List<List<int>> planVolumes(List<int> byteSizes, int limit) {
  assert(limit > 0, 'volume limit must be positive');
  final volumes = <List<int>>[];
  var current = <int>[];
  var sum = 0;

  for (var i = 0; i < byteSizes.length; i++) {
    final size = byteSizes[i];
    // 只有当前卷非空时才考虑切卷：让「单文件超限」独占一卷而不是空卷。
    if (current.isNotEmpty && sum + size > limit) {
      volumes.add(current);
      current = <int>[];
      sum = 0;
    }
    current.add(i);
    sum += size;
  }
  if (current.isNotEmpty) volumes.add(current);
  return volumes;
}
