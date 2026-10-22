import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../app/theme.dart';
import '../../domain/model/duplicate_photos.dart';

/// 重复照片面板（2026-10-04「照片不能重复」；2026-10-05 改为逐张选）。
///
/// **说清三件事，缺一件用户就没法判断**：
///  1. **哪些重复了** —— 左右并排出原图，一眼看出是同一张；
///  2. **重复在哪** —— 每张缩略图下方写明「第 N 组」/「未分组」，
///     顶部再写跨组涉及哪几个组。**含糊的提示等于没提示**：
///     只说「出现在 2 个组」，用户不知道该动哪张；
///  3. **删哪张由人定** —— 每张可点选（勾 = 删），跨组重复**默认不预勾**，
///     必须用户自己决定「删哪个组的哪张」。
///
/// **为什么不预勾冗余**（与 10-04 的变化）：跨组重复意味着分组本身出了问题，
/// 哪张该留取决于业务 —— 也许 A 组属于某个货品、B 组属于另一个，
/// 机器按"最早"来判 retain 只是猜测。**猜错了删掉的是有用的那张。**
/// 同组内重复仍给「一键删冗余」（同组内早/晚差异没有业务含义），
/// 但也允许逐张改。
void showDuplicateSheet(
  BuildContext context,
  WidgetRef ref, {
  required String projectId,
  required List<DuplicateSetWithGroups> sets,
}) {
  showModalBottomSheet<void>(
    context: context,
    // 内容可能很长（几十组重复），给一个可滚的高度而不是半屏。
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => _DuplicateSheet(projectId: projectId, sets: sets),
  );
}

class _DuplicateSheet extends ConsumerStatefulWidget {
  const _DuplicateSheet({required this.projectId, required this.sets});

  final String projectId;
  final List<DuplicateSetWithGroups> sets;

  @override
  ConsumerState<_DuplicateSheet> createState() => _DuplicateSheetState();
}

class _DuplicateSheetState extends ConsumerState<_DuplicateSheet> {
  /// 已被处理掉的重复组 hash（本次会话内不再显示）。
  final _resolved = <String>{};

  /// 正在删的 hash（防连点）。
  final _busy = <String>{};

  /// 用户勾选要删的照片（跨 hash 累积）。
  ///
  /// 为什么放 State 而不是塞回 widget.sets：勾选是**临时的用户决定**，
  /// 服务端的报告不该被本地交互污染；删完 invalidate 会拿新报告。
  final _picked = <String, bool>{};

  @override
  Widget build(BuildContext context) {
    final remaining =
        widget.sets.where((s) => !_resolved.contains(s.hash)).toList();

    return DraggableScrollableSheet(
      initialChildSize: 0.75,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (context, scrollCtrl) => Container(
        decoration: const BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        ),
        child: Column(
          children: [
            // 抓手
            Container(
              width: 38,
              height: 4,
              margin: const EdgeInsets.only(top: 9, bottom: 11),
              decoration: BoxDecoration(
                color: AppTheme.line,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.copy_all_outlined,
                      size: 20, color: AppTheme.amber),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          remaining.isEmpty
                              ? '重复照片已处理完'
                              : '${remaining.length} 组照片重复',
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w800,
                            color: AppTheme.navy,
                          ),
                        ),
                        if (remaining.isNotEmpty)
                          Text(
                            _summaryLine(remaining),
                            style: const TextStyle(
                              fontSize: 12,
                              color: AppTheme.textMuted,
                              height: 1.4,
                            ),
                          ),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close, size: 20),
                    color: AppTheme.textMuted,
                    tooltip: '关闭',
                  ),
                ],
              ),
            ),
            if (remaining.isEmpty)
              const Expanded(
                child: Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.check_circle_outline,
                          size: 46, color: AppTheme.green),
                      SizedBox(height: 10),
                      Text(
                        '本项目的照片已无重复',
                        style: TextStyle(
                            fontSize: 14, color: AppTheme.textMuted),
                      ),
                    ],
                  ),
                ),
              )
            else
              Expanded(
                child: ListView.separated(
                  controller: scrollCtrl,
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  itemCount: remaining.length + 1,
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
                  itemBuilder: (_, i) {
                    // 最后一项是说明文字，不参与操作
                    if (i == remaining.length) {
                      return const Padding(
                        padding: EdgeInsets.only(top: 4),
                        child: Text(
                          '判定口径：文件内容完全一致才算重复。'
                          '连拍两张角度不同的照片不会被算成重复。\n'
                          '点缩略图选中要删的那张（再点取消）。',
                          style: TextStyle(
                            fontSize: 11.5,
                            color: AppTheme.textMuted,
                            height: 1.6,
                          ),
                        ),
                      );
                    }
                    final s = remaining[i];
                    return _DuplicateCard(
                      set: s,
                      busy: _busy.contains(s.hash),
                      picked: _picked,
                      onToggle: (id) => setState(
                          () => _picked[id] = !(_picked[id] ?? false)),
                      onDeletePicked: () => _deletePicked(s),
                    );
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// 顶部一句话说清"有多少、涉及几个组、其中几组是跨组的"。
  ///
  /// 为什么值得单独写这么一句：老板的原话是「要更具体明确」。
  /// 「发现 3 张重复照片」用户没法判断严重程度；
  /// 「3 组照片重复 · 涉及 5 个组 · 其中 2 组跨组」才看得出
  /// **分组本身出了问题**（跨组），而不只是多拍了几张。
  String _summaryLine(List<DuplicateSetWithGroups> remaining) {
    final redundant = remaining.fold(0, (s, e) => s + e.redundantCount);
    final groups = <String>{
      for (final s in remaining)
        ...s.groupIds.where((id) => id.isNotEmpty),
    };
    final cross = remaining.where((s) => s.crossesGroups).length;
    final floating =
        remaining.fold(0, (s, e) => s + e.photos.where((p) => p.isFloating).length);

    final buf = StringBuffer('要删 $redundant 张');
    if (groups.isNotEmpty) buf.write(' · 分布在 ${groups.length} 个组');
    if (cross > 0) buf.write(' · 其中 $cross 组是跨组重复');
    if (floating > 0) buf.write(' · $floating 张还没进组');
    return buf.toString();
  }

  /// 删掉这一组里**被勾选**的那些张。
  ///
  /// 逐张删而不是批量 SQL：删除要一起清文件、缩略图与从属数据，
  /// 走 [photoDeletionServiceProvider] 才有这些保证。
  Future<void> _deletePicked(DuplicateSetWithGroups s) async {
    final ids = s.photoIds.where((id) => _picked[id] ?? false).toList();
    if (ids.isEmpty) return; // 一个都没选 —— 什么都不做，不弹提示

    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy.add(s.hash));
    final svc = ref.read(photoDeletionServiceProvider);
    var ok = 0;
    var failed = 0;
    final firstError = <Object?>[];
    for (final id in ids) {
      try {
        await svc.deletePhoto(id);
        ok++;
      } catch (e) {
        // ⚠️ **不能空 catch**（2026-10-05 被它坑过一次）：删了 2 张只成 1 张，
        // UI 只弹「1 张失败」而看不出为什么，现场根本没法自查。
        // 记下第一条错，提示里带上原因。
        if (firstError.isEmpty) firstError.add(e);
        failed++;
      }
    }
    if (!mounted) return;

    setState(() {
      _busy.remove(s.hash);
      // 只有**这一组重复真的清干净了**（剩下的都不再重复）才叫处理完。
      // ⚠️ 2026-10-05 修：判据不能是「failed == 0」—— 用户只勾了一部分
      // 就删时 failed 也是 0，但剩下的仍然彼此重复，却被标成"已处理完"，
      // 顶部提示同时说「还剩 1 张重复待处理」，**两处自相矛盾**。
      // 正确判据：这次删完之后，这一组里还剩 >= 2 张（就是还在重复）。
      final left = s.photoIds.length - ok;
      if (failed == 0 && left < 2) _resolved.add(s.hash);
      for (final id in ids) {
        _picked.remove(id);
      }
    });
    ref.invalidate(duplicateReportProvider(widget.projectId));
    ref.invalidate(openGroupsProvider(widget.projectId));
    ref.invalidate(supervisionPhotosProvider(widget.projectId));
    ref.invalidate(projectPhotoCountProvider(widget.projectId));

    messenger.showSnackBar(
      SnackBar(
        content: Text(
          _resultMessage(
            ok: ok,
            failed: failed,
            totalBefore: s.photoIds.length,
            error: firstError.isEmpty ? null : firstError.first,
          ),
        ),
      ),
    );
  }

  /// 删除结果一句话。**必须说清"现在还剩几张重复"** ——
  /// 只说"删掉了 1 张"，用户不知道还有没有坑要处理。
  static String _resultMessage({
    required int ok,
    required int failed,
    required int totalBefore,
    Object? error,
  }) {
    final left = totalBefore - ok;
    final buf = StringBuffer('已删掉 $ok 张');
    if (failed > 0) {
      buf.write('，$failed 张失败');
      // 失败原因要能看到 —— 空 catch 时代现场根本没法自查。
      if (error != null) {
        final t = error.toString();
        buf.write('（${t.length > 40 ? '${t.substring(0, 40)}…' : t}）');
      }
    }
    if (left <= 1) {
      buf.write('，这一组已清干净');
    } else if (left == 2) {
      buf.write('，还剩 2 张重复待处理');
    } else {
      buf.write('，还剩 $left 张重复待处理');
    }
    return buf.toString();
  }
}

class _DuplicateCard extends StatelessWidget {
  const _DuplicateCard({
    required this.set,
    required this.busy,
    required this.picked,
    required this.onToggle,
    required this.onDeletePicked,
  });

  final DuplicateSetWithGroups set;

  /// 重复组 hash（作 busy 键）。
  String get hash => set.hash;

  final bool busy;

  /// 勾选状态表（photoId → 是否选中删除）。
  final Map<String, bool> picked;

  final ValueChanged<String> onToggle;
  final VoidCallback onDeletePicked;

  @override
  Widget build(BuildContext context) {
    final cross = set.crossesGroups;
    final pickedCount = set.photoIds.where((id) => picked[id] ?? false).length;

    return Card(
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(11),
        side: BorderSide(color: AppTheme.amber.withValues(alpha: 0.45)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(11),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ── 重复位置：写清"哪个组"，不只写"几个组" ──
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  cross ? Icons.compare_arrows : Icons.copy_all_outlined,
                  size: 15,
                  color: AppTheme.amber,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    cross
                        // 跨组：「跨组重复 · 第 2 组 ↔ 第 5 组」
                        ? '跨组重复 · ${set.groupSummary()}'
                        // 同组：「同组内重复 · 第 3 组」；全游离就直说
                        : set.soleGroupSeq == null
                            ? '同批内重复 · 都还没进组'
                            : '同组内重复 · 第 ${set.soleGroupSeq} 组',
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.navy,
                      height: 1.35,
                    ),
                  ),
                ),
              ],
            ),
            if (cross)
              Padding(
                padding: const EdgeInsets.only(top: 4, left: 21),
                child: Text(
                  '同一张照片出现在 ${set.groupIds.where((id) => id.isNotEmpty).length} '
                  '个组里 —— 分组可能出错了，请确认哪张该留',
                  style: TextStyle(
                    fontSize: 11.5,
                    color: AppTheme.textMuted.withValues(alpha: 0.95),
                    height: 1.35,
                  ),
                ),
              ),
            const SizedBox(height: 9),
            // ── 原图并排：每张标明归属，可点选 ──
            //
            // ⚠️ 高度必须与 [_Thumb] 的内容**严格一致**，否则 Column 溢出。
            // 算法：外层 padding 3+3 = 6，图 62，gap 3，两行小字各 14
            //      → 6 + 62 + 3 + 14 + 14 = 99，留 1px 余量取 100。
            //    **改缩略图尺寸或行数时这里必须同步改**（09-29 相册选择器
            //    栽过同款：行高公式与 GridView 不一致 → 静默 clamp）。
            SizedBox(
              height: 100,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: set.photoIds.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (_, i) {
                  final p = set.photoAt(i) ??
                      DuplicatePhoto(
                        id: set.photoIds[i],
                        groupId: i < set.groupIds.length ? set.groupIds[i] : '',
                        groupSeq: null,
                        seq: 0,
                        thumbPath: set.thumbAt(i),
                      );
                  return _Thumb(
                    photo: p,
                    // 最早的只作"默认建议"，不再强制 —— 跨组时
                    // 哪张该留是业务判断，机器猜不得。
                    isEarliest: p.id == set.earliestPhotoId,
                    picked: picked[p.id] ?? false,
                    onTap: busy ? null : () => onToggle(p.id),
                  );
                },
              ),
            ),
            const SizedBox(height: 9),
            SizedBox(
              width: double.infinity,
              height: 38,
              child: OutlinedButton.icon(
                onPressed: busy || pickedCount == 0 ? null : onDeletePicked,
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppTheme.red,
                  disabledForegroundColor: AppTheme.textMuted,
                  side: BorderSide(
                    color: pickedCount == 0
                        ? AppTheme.line
                        : AppTheme.red.withValues(alpha: 0.4),
                  ),
                ),
                icon: busy
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.delete_outline, size: 16),
                label: Text(
                  busy
                      ? '删除中…'
                      : pickedCount == 0
                          // 没选时按钮禁用过，**必须写清下一步该做什么** ——
                          // 禁用按钮不加解释是可用性反模式。
                          ? '请点缩略图选中要删的张'
                          : '删掉选中的 $pickedCount 张',
                  style: const TextStyle(fontSize: 12.5),
                ),
              ),
            ),
            if (pickedCount > 0 && pickedCount < set.photoIds.length)
              Padding(
                padding: const EdgeInsets.only(top: 5, left: 2),
                child: Text(
                  '会留下 ${set.photoIds.length - pickedCount} 张'
                  '（每组各留至少一张，别把整组删空）',
                  style: const TextStyle(
                      fontSize: 11, color: AppTheme.textMuted),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 单张缩略图：图 + 归属组 + 选中态。
class _Thumb extends StatelessWidget {
  const _Thumb({
    required this.photo,
    required this.isEarliest,
    required this.picked,
    required this.onTap,
  });

  final DuplicatePhoto photo;
  final bool isEarliest;
  final bool picked;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final thumb = photo.thumbPath;
    return SizedBox(
      width: 74,
      child: Material(
        // 选中态整块压暗 + 红边，比只改边框更容易在滑动时看清。
        color: picked ? AppTheme.red.withValues(alpha: 0.08) : Colors.transparent,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(3),
            child: Column(
              children: [
                SizedBox(
                  width: 62,
                  height: 62,
                  // ⚠️ 尺寸必须给死（2026-10-05 修）：Stack 默认按子节点
                  // 最大尺寸撑，而选中态的 `Border.all(width: 2)` 是
                  // **画在内容之外**的（62 + 2 + 2 = 66）→ Stack 变 66 高，
                  // 比外层 SizedBox 高 4px，Column 溢出 3~4px，
                  // widget 测试直接判 fail，真机上表现为文字被切掉。
                  child: Stack(
                    children: [
                      Positioned.fill(child: _thumbBody(thumb, picked)),
                      // 勾选标记：右上角对勾圆
                      if (picked)
                        const Positioned(
                          right: 0,
                          top: 0,
                          child: CircleAvatar(
                            radius: 9,
                            backgroundColor: AppTheme.red,
                            child: Icon(Icons.check,
                                size: 13, color: Colors.white),
                          ),
                        )
                      else if (isEarliest)
                        const Positioned(
                          right: 0,
                          top: 0,
                          child: CircleAvatar(
                            radius: 9,
                            backgroundColor: AppTheme.green,
                            child: Text('早',
                                style: TextStyle(
                                    fontSize: 9,
                                    color: Colors.white,
                                    fontWeight: FontWeight.w700)),
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 3),
                // 归属组 —— 「具体明确」的核心：每张都必须写清属于哪个组
                Text(
                  photo.groupLabel,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 10,
                    color: photo.isFloating
                        ? AppTheme.textMuted
                        : AppTheme.navy,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  picked ? '选中删除' : (isEarliest ? '最早' : '拍于 ${photo.seq}'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 9.5,
                    color: picked ? AppTheme.red : AppTheme.textMuted,
                    fontWeight:
                        picked || isEarliest ? FontWeight.w700 : FontWeight.w400,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// 缩略图本体（图 + 选中红框）。
  ///
  /// 抽出来是因为它被 [Positioned.fill] 约束在 62×62 里 ——
  /// 边框必须画在**内**侧，否则会把 Stack 撑大（见上方注释）。
  Widget _thumbBody(String? thumb, bool picked) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(7),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(7),
          border: picked ? Border.all(color: AppTheme.red, width: 2) : null,
        ),
        // 与组卡片同一套缩略图纪律（09-29 性能排查）：
        // build 里不做同步 existsSync，缺失交给 errorBuilder；
        // 74dp 格子按 132px 解码足够。
        child: thumb != null && thumb.isNotEmpty
            ? Image.file(
                File(thumb),
                fit: BoxFit.cover,
                filterQuality: FilterQuality.low,
                gaplessPlayback: true,
                cacheWidth: 132,
                errorBuilder: (_, __, ___) =>
                    const ColoredBox(color: AppTheme.bg),
              )
            : const ColoredBox(color: AppTheme.bg),
      ),
    );
  }
}

/// 照片页顶部的橙色重复提示横幅。
///
/// **显眼是刻意的**（老板 2026-10-04「显眼位置提示」）：橙色实底 +
/// 感叹号图标 + 直接写出「N 张重复」这个数字，不做成需要点开才发现的
/// 弱提示 —— 重复照片混进交付包是甲方的质量问题，现场必须第一眼看到。
///
/// 三种形态：
///  · [onScanning] —— 正在核查（**不是**"没问题"，是"还没查完"）；
///  · [duplicateCount] > 0 —— 发现重复，可点开处理；
///  · 其余 —— 收起来，不占任何空间。
class DuplicateBanner extends StatelessWidget {
  const DuplicateBanner({
    super.key,
    required this.loading,
    required this.duplicateCount,
    required this.onScanning,
    required this.onOpen,
    this.setCount = 0,
    this.crossGroupCount = 0,
  });

  final bool loading;

  /// 冗余张数（= 该删的数量）。
  final int duplicateCount;

  /// 重复的**组数**（几组照片彼此重复）。给了就把"几组"也说出来 ——
  /// 「3 组 / 9 张」比单说「9 张」更具体，用户一眼看出是 3 处问题。
  final int setCount;

  /// 其中跨组重复的组数（>0 时在横幅上点明 —— 分组本身出了问题，
  /// 严重程度和"同组内多拍了一张"不是一个量级）。
  final int crossGroupCount;

  /// 还在核查：显示剩余张数。
  final int onScanning;

  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    // 三个条件全不成立才收起来 —— 不占空间。
    //
    // ⚠️ [loading] 必须算作「还没结论」（2026-10-04 修）：首帧 provider
    // 在飞，此刻 duplicateCount 还是 0，若照直渲染就是橙色
    // 「发现 0 张重复照片」—— 还没查就宣布"没有"，比不提示更糟，
    // 而且用户会以为 App 已经查清了。
    final hasDup = duplicateCount > 0;
    final scanning = onScanning > 0;
    if (!loading && !hasDup && !scanning) {
      return const SizedBox.shrink();
    }

    // loading 且还没有任何结论 → 与"核查中"同一种形态（灰色 + 转圈）
    final pending = scanning || (!hasDup && loading);
    final text = scanning
        ? '正在核查照片重复…（还剩 $onScanning 张）'
        : hasDup
            ? _dupLine()
            : '正在核查照片重复…';

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      child: Material(
        color: pending
            ? AppTheme.line.withValues(alpha: 0.35)
            : AppTheme.amberBg,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: hasDup ? onOpen : null,
          child: Container(
            padding: const EdgeInsets.fromLTRB(11, 9, 9, 9),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: pending
                    ? AppTheme.line
                    : AppTheme.amber.withValues(alpha: 0.5),
              ),
            ),
            child: Row(
              children: [
                if (pending)
                  const SizedBox(
                    width: 15,
                    height: 15,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                else
                  const Icon(Icons.warning_amber_rounded,
                      size: 18, color: AppTheme.amber),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    text,
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight:
                          hasDup ? FontWeight.w700 : FontWeight.w500,
                      color:
                          pending ? AppTheme.textMuted : AppTheme.amber,
                    ),
                  ),
                ),
                if (hasDup) ...[
                  const Icon(Icons.chevron_right,
                      size: 18, color: AppTheme.amber),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// 横幅文案（2026-10-05 具体化）。
  ///
  /// 目标是让人**不用点开就知道这事有多严重**：
  ///   · 有组数 → 「3 组照片重复 · 要删 9 张」
  ///   · 有跨组 → 追加「其中 2 组跨组」，跨组意味着分组本身出错
  String _dupLine() {
    final buf = StringBuffer();
    if (setCount > 0) {
      buf.write('$setCount 组照片重复');
    } else {
      buf.write('发现 $duplicateCount 张重复照片');
    }
    buf.write(' · 要删 $duplicateCount 张');
    if (crossGroupCount > 0) {
      buf.write(' · $crossGroupCount 组跨组');
    }
    return buf.toString();
  }
}
