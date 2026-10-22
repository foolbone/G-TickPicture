import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../app/router.dart';
import '../../app/theme.dart';
import '../../domain/model/open_group.dart';
import '../../domain/model/photo_search_hit.dart';
import '../../domain/search/code_norm.dart';
import '../organize/photo_viewer_page.dart';

/// 按产品编码搜历史照片（2026-10-15 v0.24.0）。
///
/// 现场的真实提问是「上次那批 XXX 编码的照片在哪」—— 而人记得住的
/// 往往**不是完整编码**：唛头被挡住时只剩**后几位**，或者只认得**中间
/// 那一段**。所以本页不吃「前缀搜索」那一套，输入 2 位以上就按
/// 精确 / 后缀 / 前缀 / 包含 四级同时找（见 `code_norm.dart`）。
///
/// 两个入口共用这一页：
///   · 主页顶栏搜索图标 → 跨项目搜（`projectId` 为 null）；
///   · 项目工作台 ⋯ 菜单「搜索本项目照片」→ 只搜当前项目。
class PhotoSearchPage extends ConsumerStatefulWidget {
  /// 构造；[projectId] 为空表示跨项目全局搜。
  const PhotoSearchPage({super.key, this.projectId});

  /// 限定项目；null = 全部项目。
  final String? projectId;

  @override
  ConsumerState<PhotoSearchPage> createState() => _PhotoSearchPageState();
}

class _PhotoSearchPageState extends ConsumerState<PhotoSearchPage> {
  final TextEditingController _ctrl = TextEditingController();

  /// 输入去抖：人还在敲的时候不查（一次 join + 匹配几百毫秒，
  /// 每敲一个字符查一次会把界面敲卡）。
  Timer? _debounce;
  String _query = '';
  bool _confirmedOnly = false;
  List<String> _recent = const <String>[];

  /// 去抖时长。
  static const Duration _debounceDelay = Duration(milliseconds: 300);

  @override
  void initState() {
    super.initState();
    _loadRecent();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _loadRecent() async {
    final list = await ref.read(recentSearchesProvider).load();
    if (!mounted) return;
    setState(() => _recent = list);
  }

  void _onChanged(String v) {
    _debounce?.cancel();
    _debounce = Timer(_debounceDelay, () async {
      final q = v.trim();
      if (!mounted) return;
      setState(() => _query = q);
      // 只记"够长"的输入 —— 1 位字符记进历史只会污染列表。
      if (q.length >= kMinCodeQueryLength) {
        await ref.read(recentSearchesProvider).push(q);
        if (!mounted) return;
        await _loadRecent();
      }
    });
  }

  void _submitFromChip(String code) {
    _ctrl.text = code;
    _ctrl.selection = TextSelection.collapsed(offset: code.length);
    _debounce?.cancel();
    setState(() => _query = code.trim());
  }

  Future<void> _clearRecent() async {
    await ref.read(recentSearchesProvider).clear();
    if (!mounted) return;
    setState(() => _recent = const <String>[]);
  }

  @override
  Widget build(BuildContext context) {
    final scoped = widget.projectId != null;
    final tooShort = _query.length < kMinCodeQueryLength;
    final args = (
      query: _query,
      projectId: widget.projectId,
      confirmedOnly: _confirmedOnly,
    );
    final async = ref.watch(photoSearchProvider(args));

    return Scaffold(
      appBar: AppBar(
        title: Text(scoped ? '搜索本项目照片' : '搜索照片'),
      ),
      body: Column(
        children: [
          _SearchField(
            controller: _ctrl,
            onChanged: _onChanged,
            onClear: () {
              _ctrl.clear();
              _debounce?.cancel();
              setState(() => _query = '');
            },
            confirmedOnly: _confirmedOnly,
            onToggleConfirmed: (v) => setState(() => _confirmedOnly = v),
          ),
          Expanded(
            child: _query.isEmpty
                ? _IdlePane(
                    recent: _recent,
                    onPick: _submitFromChip,
                    onClearRecent: _clearRecent,
                  )
                : tooShort
                    ? const _HintPane(
                        icon: Icons.keyboard_outlined,
                        title: '再多输一位',
                        subtitle: '至少 2 位才搜 —— 1 位会命中半个库，'
                            '那样的结果没有意义。',
                      )
                    : _ResultPane(
                        async: async,
                        query: _query,
                        projectId: widget.projectId,
                        onOpen: _openViewer,
                        onLocate: _locateInProject,
                      ),
          ),
        ],
      ),
    );
  }

  /// 打开大图。同组的照片一起进查看器 —— 人要找的是"那批"，不是那一张。
  void _openViewer(List<PhotoSearchHit> hits, int index) {
    if (index < 0 || index >= hits.length) return;
    final hit = hits[index];
    final batch = hit.groupId == null
        ? <PhotoSearchHit>[hit]
        : hits
            .where((h) => h.projectId == hit.projectId && h.groupId == hit.groupId)
            .toList();
    final at = batch.indexWhere((h) => h.photoId == hit.photoId);
    final group = OpenGroup(
      groupId: hit.groupId ?? hit.photoId,
      seq: hit.groupSeq ?? 0,
      takenAtMs: hit.takenAtMs,
      photos: [
        for (final h in batch)
          GroupPhotoThumb(
            id: h.photoId,
            takenAtMs: h.takenAtMs,
            thumbPath: h.thumbPath,
            originalPath: h.filePath,
          ),
      ],
    );
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => PhotoViewerPage(
          projectId: hit.projectId,
          group: group,
          initialIndex: at < 0 ? 0 : at,
          groupLabel: '搜索「$_query」· ${hit.projectName}',
        ),
      ),
    );
  }

  /// 跳到照片所在项目的照片页。
  ///
  /// ⚠️ 用 push 不能用 go（2026-10-20）：go 会把搜索页从栈里替换掉，
  /// 项目页按返回就直接退出 App。push 后返回能回到搜索结果，继续看别的。
  void _locateInProject(PhotoSearchHit hit) {
    context.push('${AppRoutes.project}/${hit.projectId}?tab=0');
  }
}

// ─────────────────────────────────────────────────────────────
// 搜索框
// ─────────────────────────────────────────────────────────────

class _SearchField extends StatelessWidget {
  const _SearchField({
    required this.controller,
    required this.onChanged,
    required this.onClear,
    required this.confirmedOnly,
    required this.onToggleConfirmed,
  });

  final TextEditingController controller;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;
  final bool confirmedOnly;
  final ValueChanged<bool> onToggleConfirmed;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppTheme.card,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: controller,
            autofocus: true,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              hintText: '输入产品编码（可只输后几位）',
              prefixIcon: const Icon(Icons.qr_code_2_outlined, size: 20),
              suffixIcon: IconButton(
                tooltip: '清空',
                icon: const Icon(Icons.close, size: 20),
                onPressed: onClear,
              ),
              isDense: true,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: const BorderSide(color: AppTheme.line),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: const BorderSide(color: AppTheme.line),
              ),
            ),
            onChanged: onChanged,
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              const Icon(Icons.info_outline,
                  size: 13, color: AppTheme.textMuted),
              const SizedBox(width: 4),
              const Expanded(
                child: Text(
                  '不分区大小写、忽略 - 与空格；输后几位 / 中间几位都能找到',
                  style: TextStyle(fontSize: 11.5, color: AppTheme.textMuted),
                ),
              ),
              SizedBox(
                height: 30,
                child: FilterChip(
                  label: const Text('只看已确认', style: TextStyle(fontSize: 11.5)),
                  selected: confirmedOnly,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  visualDensity: VisualDensity.compact,
                  onSelected: onToggleConfirmed,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────
// 空态：未输入 → 最近搜索
// ─────────────────────────────────────────────────────────────

class _IdlePane extends StatelessWidget {
  const _IdlePane({
    required this.recent,
    required this.onPick,
    required this.onClearRecent,
  });

  final List<String> recent;
  final ValueChanged<String> onPick;
  final Future<void> Function() onClearRecent;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (recent.isNotEmpty) ...[
          Row(
            children: [
              const Text('最近搜过',
                  style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.textMain)),
              const Spacer(),
              TextButton(
                onPressed: onClearRecent,
                child: const Text('清空', style: TextStyle(fontSize: 12)),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              for (final c in recent)
                ActionChip(
                  label: Text(c, style: const TextStyle(fontSize: 13)),
                  onPressed: () => onPick(c),
                ),
            ],
          ),
          const SizedBox(height: 20),
        ],
        const _HintPane(
          icon: Icons.search,
          title: '按产品编码找历史照片',
          subtitle: '输入清单上的编码即可，例如 ABC-123；\n'
              '只记得后几位（如 123）或中间几位也能搜。',
        ),
      ],
    );
  }
}

class _HintPane extends StatelessWidget {
  const _HintPane({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 40, horizontal: 24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 44, color: AppTheme.textMuted.withValues(alpha: .5)),
          const SizedBox(height: 12),
          Text(title,
              style: const TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.textMain)),
          const SizedBox(height: 6),
          Text(
            subtitle,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 12.5, color: AppTheme.textMuted),
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────
// 结果区
// ─────────────────────────────────────────────────────────────

class _ResultPane extends ConsumerWidget {
  const _ResultPane({
    required this.async,
    required this.query,
    required this.projectId,
    required this.onOpen,
    required this.onLocate,
  });

  final AsyncValue<List<PhotoSearchHit>> async;
  final String query;

  /// 搜索范围；null = 全部项目。空态提示要用它取对应的 OCR 覆盖统计。
  final String? projectId;

  final void Function(List<PhotoSearchHit> hits, int index) onOpen;
  final ValueChanged<PhotoSearchHit> onLocate;

  /// 是否限定当前项目。
  bool get scoped => projectId != null;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return async.when(
      loading: () => const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      ),
      error: (e, _) => _HintPane(
        icon: Icons.error_outline,
        title: '搜索出错了',
        subtitle: '$e',
      ),
      data: (hits) {
        if (hits.isEmpty) {
          // v0.24.2：零命中不再只说「没找到」—— 先分清是**没识别**
          // 还是**没命中**。OCR 从未跑过时（v0.24.1 及以前的现场），
          // 库里一条 token 都没有，说「换个关键词搜」是误导。
          final stats = ref.watch(ocrPhotoStatsProvider(projectId)).valueOrNull;
          final String subtitle;
          if (stats == null || stats.total == 0) {
            subtitle = '还没有可用于搜索的照片 —— 先拍照入库。';
          } else if (stats.hasFailed) {
            subtitle = '注意：${stats.failed} 张识别失败、'
                '${stats.pending} 张还没识别，可能因此搜不到。'
                '打开项目照片页可查看进度并重试。';
          } else if (stats.pending > 0) {
            subtitle = '还有 ${stats.pending} 张照片没识别'
                '（打开对应项目照片页会自动开始）。'
                '已识别的部分也没有匹配。';
          } else {
            subtitle = '试试编码的后几位，或换个项目搜（本页'
                '${scoped ? '只搜当前项目' : '搜全部项目'}）。';
          }
          return _HintPane(
            icon: Icons.search_off,
            title: '没找到「$query」',
            subtitle: subtitle,
          );
        }
        final projects = hits.map((h) => h.projectId).toSet().length;
        final allUnconfirmed =
            hits.every((h) => h.source != PhotoSearchSource.assigned);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 14, 6),
              child: Row(
                children: [
                  Text(
                    '命中 ${hits.length} 张 · 来自 $projects 个项目',
                    style: const TextStyle(
                        fontSize: 12.5, color: AppTheme.textMuted),
                  ),
                ],
              ),
            ),
            if (allUnconfirmed)
              Container(
                margin: const EdgeInsets.fromLTRB(14, 0, 14, 8),
                padding: const EdgeInsets.symmetric(
                    horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: AppTheme.amberBg,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.help_outline,
                        size: 15, color: AppTheme.amber),
                    SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        '这些命中都还没确认归属（来自建议或 OCR），'
                        '请到项目里核对。',
                        style:
                            TextStyle(fontSize: 11.5, color: AppTheme.amber),
                      ),
                    ),
                  ],
                ),
              ),
            Expanded(
              child: GridView.builder(
                padding: const EdgeInsets.fromLTRB(12, 0, 12, 16),
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 3,
                  crossAxisSpacing: 8,
                  mainAxisSpacing: 10,
                  childAspectRatio: 0.74,
                ),
                itemCount: hits.length,
                itemBuilder: (context, i) => _HitTile(
                  hit: hits[i],
                  query: query,
                  showProject: !scoped,
                  onTap: () => onOpen(hits, i),
                  onLocate: () => onLocate(hits[i]),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _HitTile extends StatelessWidget {
  const _HitTile({
    required this.hit,
    required this.query,
    required this.showProject,
    required this.onTap,
    required this.onLocate,
  });

  final PhotoSearchHit hit;
  final String query;
  final bool showProject;
  final VoidCallback onTap;
  final VoidCallback onLocate;

  @override
  Widget build(BuildContext context) {
    final thumb = hit.thumbPath;
    final badge = hit.source.badge;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Stack(
              children: [
                Positioned.fill(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(10),
                    child: Container(
                      color: AppTheme.line.withValues(alpha: .5),
                      child: thumb == null
                          ? const Center(
                              child: Icon(Icons.image_outlined,
                                  size: 26, color: AppTheme.textMuted),
                            )
                          : Image.file(
                              File(thumb),
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => const Center(
                                child: Icon(Icons.broken_image_outlined,
                                    size: 24, color: AppTheme.textMuted),
                              ),
                            ),
                    ),
                  ),
                ),
                if (badge != null)
                  Positioned(
                    left: 4,
                    top: 4,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 5, vertical: 1),
                      decoration: BoxDecoration(
                        color: Colors.black54,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        badge,
                        style: const TextStyle(
                            fontSize: 9.5, color: Colors.white),
                      ),
                    ),
                  ),
                Positioned(
                  right: 0,
                  bottom: 0,
                  child: SizedBox(
                    width: 30,
                    height: 30,
                    child: IconButton(
                      padding: EdgeInsets.zero,
                      tooltip: '在项目里打开',
                      icon: const Icon(Icons.open_in_new, size: 15),
                      color: Colors.white,
                      onPressed: onLocate,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 4),
          _CodeLine(code: hit.matchedCode, query: query),
          const SizedBox(height: 1),
          Text(
            showProject ? hit.projectName : _hhmm(hit.takenAtMs),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 10.5, color: AppTheme.textMuted),
          ),
        ],
      ),
    );
  }

  static String _hhmm(int ms) {
    final t = DateTime.fromMillisecondsSinceEpoch(ms);
    return '${t.year}-${t.month.toString().padLeft(2, '0')}-'
        '${t.day.toString().padLeft(2, '0')} '
        '${t.hour.toString().padLeft(2, '0')}:'
        '${t.minute.toString().padLeft(2, '0')}';
  }
}

/// 编码行：把**命中的那几位**标出来。
///
/// 后几位命中时尤其需要 —— `123` 同时命中 `ABC123` 与 `XYZ123`，
/// 不标出来人只能一张张点进去看。
class _CodeLine extends StatelessWidget {
  const _CodeLine({required this.code, required this.query});

  final String code;
  final String query;

  @override
  Widget build(BuildContext context) {
    final range = highlightRangeInRaw(code, query);
    const base = TextStyle(fontSize: 11.5, color: AppTheme.textMain);
    if (range == null) {
      return Text(
        code,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: base,
      );
    }
    return RichText(
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      text: TextSpan(
        style: base,
        children: [
          TextSpan(text: code.substring(0, range.start)),
          TextSpan(
            text: code.substring(range.start, range.end),
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              color: AppTheme.accent,
            ),
          ),
          TextSpan(text: code.substring(range.end)),
        ],
      ),
    );
  }
}
