/// 照片缩略图条目 —— 列表/胶片条只需知道的两个字段。
///
/// 属于**领域模型**，不属于数据层。
/// 放在这里的原因：UI 层不得直接 import `lib/data/`（见 tools/check_architecture.ps1 规则 2），
/// 而 UI 需要具名引用这个类型，所以它必须住在 `domain/model/`。
///
/// 为什么不直接暴露 drift 的 `Photo` 行：
///  1. UI 拿不到整行就不会顺手去读 `itemId` —— 采集页**在类型上**看不到归属，
///     这不靠自觉，靠类型系统（§5.2 采集期零判断）。
///  2. 列表里只需要 id + 缩略图路径，暴露整行会鼓励 UI 去解码原图（R1b）。
///
/// 缩略图可能还没生成（[thumbPath] 为 null 或文件已丢），UI 必须能画出占位块。
library;

class PhotoThumb {
  const PhotoThumb({
    required this.id,
    required this.thumbPath,
  });

  final String id;

  /// 256px 缩略图的绝对路径。**null = 尚未生成**（异步补图还没跑完）。
  ///
  /// ⚠️ UI 只允许读这个文件，绝不允许读原图 ——
  /// 一天 1600 张的列表里解码原图会直接把内存打爆（R1b）。
  final String? thumbPath;

  @override
  String toString() => 'PhotoThumb($id, $thumbPath)';
}
