// 重复照片的领域模型（2026-10-04「照片不能重复」）。
//
// 判定口径是**字节级完全一致**（见 PerfBridge.hashFiles 的算法注释）
// —— 同一张图无论从相册选几次、经几次微信转发，文件字节不变，所以
// 「同一张图出现两次」在这个口径下一张不漏；而连拍两张略不同的照片
// 不会被误判（宁可漏报不错报：现场误删一张真照片，比多留一张重复的
// 代价大得多）。

/// 一组重复照片：**同一内容指纹的多张**。
///
/// 跨组重复时 [photoIds] 会横跨多个组；同组内重复时它们同属一组。
class DuplicateSet {
  const DuplicateSet({
    required this.hash,
    required this.photoIds,
    required this.earliestPhotoId,
  });

  /// 内容指纹（相同即重复）。
  final String hash;

  /// 参与重复的全部照片 id（>= 2）。
  final List<String> photoIds;

  /// 建议保留的那张 —— **最早拍的**（seq 最小）。
  ///
  /// 为什么保留最早：重复多半是"同一张图选了两次"，第一张才是用户
  /// 真正按下快门的那次，后面的都是重复选择。
  final String earliestPhotoId;

  int get duplicateCount => photoIds.length;

  /// 要删的冗余张数（总数 - 保留 1 张）。
  int get redundantCount => photoIds.length - 1;

  List<String> get redundantIds =>
      photoIds.where((id) => id != earliestPhotoId).toList(growable: false);
}

/// 查重结果汇总。
class DuplicateReport {  const DuplicateReport({
    required this.sets,
    required this.hashedCount,
    required this.pendingCount,
  });

  const DuplicateReport.empty()
      : sets = const [],
        hashedCount = 0,
        pendingCount = 0;

  /// 每组重复一份。
  ///
  /// 用具体子类而不是 [DuplicateSet]：UI 要显示原图（thumbPaths）与
  /// 跨组与否（crossesGroups），这两个只在子类的扩展视图里。
  final List<DuplicateSetWithGroups> sets;

  /// 已算出指纹的照片数（分母，用于「还差几张没算」）。
  final int hashedCount;

  /// 还没算指纹的照片数。>0 时提示「正在核查」，此时不显示重复结论 ——
  /// 没算完就报「无重复」是骗人。
  final int pendingCount;

  /// 冗余照片总张数（要删掉的数量）。
  int get redundantTotal =>
      sets.fold(0, (sum, s) => sum + s.redundantCount);

  /// 涉及的重复组数（跨组重复会占多个组）。
  int get affectedGroupCount {
    final g = <String>{};
    for (final s in sets) {
      g.addAll(s.groupIds.where((id) => id.isNotEmpty));
    }
    return g.length;
  }

  /// 其中跨组重复的组数（2026-10-05：顶部提示要能说清「几组是跨组的」——
  /// 跨组比同组严重，它意味着分组本身出了问题）。
  int get crossGroupCount => sets.where((s) => s.crossesGroups).length;

  /// 同组内重复的组数。
  int get withinGroupCount => sets.length - crossGroupCount;

  /// 还没进组的重复张数（游离照片重复）—— 用户看到「未分组」要有心理准备。
  int get floatingDuplicateCount => sets.fold(
        0,
        (sum, s) => sum + s.photos.where((p) => p.isFloating).length,
      );

  /// 正在补算指纹（还没算完）。
  bool get isScanning => pendingCount > 0;

  /// 有已确认的重复。
  bool get hasDuplicate => sets.isNotEmpty;
}

/// 重复组里的**一张**照片（2026-10-05 加：跨组重复要能逐张选，
/// 光有 photoIds 说不出「这张属于哪个组」，用户就没法判断该删哪张）。
///
/// 不可变值对象，按 [DuplicateSetWithGroups.photos] 的下标与之一一对应。
class DuplicatePhoto {
  const DuplicatePhoto({
    required this.id,
    required this.groupId,
    required this.groupSeq,
    required this.seq,
    required this.thumbPath,
  });

  final String id;

  /// 所属组 id（空串 = 游离照片，还没进任何组）。
  final String groupId;

  /// 所属组在项目里的次序（**展示口径**：UI 一律说「第 N 组」）。
  /// null = 游离照片，或所属组已被删掉。
  final int? groupSeq;

  /// 照片在项目里的序号（用于同组内说「第几张」）。
  final int seq;

  /// 缩略图路径（null = 还没生成）。
  final String? thumbPath;

  bool get isFloating => groupId.isEmpty;

  /// 归属的展示名。**必须写清「未分组」而不是留白** ——
  /// 提示含糊是这次要修的核心问题（用户看不出该动哪张）。
  String get groupLabel => groupSeq == null ? '未分组' : '第 $groupSeq 组';
}

/// [DuplicateSet] 的补充视图：带组归属与缩略图路径。
/// 仓储层查出来时一并附带 —— UI 靠 [DuplicatePhoto.thumbPath] 显示原图，
/// 不按 photoId 反推路径（缩略图是异步生成的，可能压根不存在）。
class DuplicateSetWithGroups extends DuplicateSet {
  const DuplicateSetWithGroups({
    required super.hash,
    required super.photoIds,
    required super.earliestPhotoId,
    required this.photos,
    required this.groupIds,
    required this.thumbPaths,
  });

  /// 逐张明细（2026-10-05 新增）。[photoIds] / [groupIds] / [thumbPaths]
  /// 都从它派生 —— 保留旧字段是为了不推翻既有调用点。
  final List<DuplicatePhoto> photos;

  /// 涉及的组 id（空串 = 游离照片，还没进任何组）。
  final List<String> groupIds;

  /// 与 [photoIds] 顺序对齐：缩略图路径（null = 还没生成）。
  final List<String?> thumbPaths;

  /// 某张的缩略图路径（越界返回 null）。
  String? thumbAt(int index) =>
      index >= 0 && index < thumbPaths.length ? thumbPaths[index] : null;

  /// 某张的明细（越界返回 null）。
  DuplicatePhoto? photoAt(int index) =>
      index >= 0 && index < photos.length ? photos[index] : null;

  /// 是否跨组重复（同组内重复 = false）。
  bool get crossesGroups {
    final g = groupIds.where((id) => id.isNotEmpty).toSet();
    return g.length > 1;
  }

  /// 跨组时，把涉及的组按次序列成「第 2 组 ↔ 第 5 组」这种说法。
  ///
  /// 超过 [limit] 个就写「…等 N 个组」—— 现场可能有同一张图散在七八个组里，
  /// 全列出来会把卡片撑爆，而用户要判断的也只是"到底跨了几组"。
  String groupSummary({int limit = 3}) {
    final seqs = <int>{
      for (final p in photos)
        if (p.groupSeq != null) p.groupSeq!,
    }.toList()
      ..sort();
    if (seqs.isEmpty) return '都还没进组';
    if (seqs.length == 1) return '都在第 ${seqs.first} 组';
    final head = seqs.take(limit).map((s) => '第 $s 组').join(' ↔ ');
    return seqs.length > limit ? '$head 等 ${seqs.length} 个组' : head;
  }

  /// 同一组里重复时，这组重复全在第几组（null = 游离）。
  int? get soleGroupSeq {
    final seqs = <int>{
      for (final p in photos)
        if (p.groupSeq != null) p.groupSeq!,
    };
    return seqs.length == 1 ? seqs.first : null;
  }
}
