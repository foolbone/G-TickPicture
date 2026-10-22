/// 一条历史交付包（2026-10-20 v0.24.8）。
///
/// 为什么需要这个模型：打包完成时 `ExportService` 早就写进了 `deliveries`
/// 表，但交付页只把最后一份结果放在 State 里 —— 退出重进就「看不到前面
/// 打的包」了（老板 10-20 反馈）。补上读口之后，**drift 的 Delivery 行
/// 不直接外泄到 UI**（架构 R2：UI 层禁 import data/），在这里转成纯数据。
library;

class DeliveryHistoryItem {
  const DeliveryHistoryItem({
    required this.id,
    required this.createdAt,
    required this.zipPath,
    required this.folderPath,
    required this.volumePaths,
    required this.bytes,
    required this.itemCount,
    required this.photoCount,
    required this.compressed,
  });

  final String id;

  /// 打包时刻（本地时间）。
  final DateTime createdAt;

  /// 数据库里记的第一卷路径（多卷时是卷 1）。
  final String zipPath;

  /// 包所在的目录（分享文案与「找不到文件」提示用）。
  final String folderPath;

  /// 实际还在手机上的卷文件（按卷序）。空 = 文件已被清理/删除。
  ///
  /// 多卷的卷号从文件名还原（`xxx_第01卷-共03卷.zip`），因为数据库只
  /// 存了第一卷 —— 这样「历史交付包」也能逐卷重新发送。
  final List<String> volumePaths;

  final int bytes;
  final int itemCount;
  final int photoCount;

  /// 当时是否勾了「压缩画质」（从 optionsJson 还原，展示用）。
  final bool compressed;

  /// 文件不在了（被系统清理 / 手动删了）。
  bool get missing => volumePaths.isEmpty;

  /// 当时分了多卷。
  bool get isSplit => volumePaths.length > 1;
}
