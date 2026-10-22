import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../app/theme.dart';
import '../../core/logger.dart';
import '../../domain/checklist/checklist_file_reader.dart';
import '../../domain/checklist/checklist_importer.dart';
import '../../domain/checklist/column_mapper.dart';
import '../../domain/model/checklist_row.dart';
import '../../domain/model/enums.dart';
import '../widgets/stage_progress.dart';
import 'checklist_photo_import_page.dart';

/// P3 · 清单导入向导（设计方案 §5.1）。
///
/// 五步：选文件 → 选工作表 → 列映射 → 校验 → 导入。
/// 之所以要这么多步而不是"一键导入"：客户给的 Excel 形状千奇百怪，
/// **必须允许看清并纠正**，否则导入错了要整项目重来。
class ChecklistImportPage extends ConsumerStatefulWidget {
  const ChecklistImportPage({super.key, required this.projectId});

  final String projectId;

  @override
  ConsumerState<ChecklistImportPage> createState() =>
      _ChecklistImportPageState();
}

class _ChecklistImportPageState extends ConsumerState<ChecklistImportPage> {
  static const _stepTitles = ['选文件', '选工作表', '列映射', '校验', '导入'];

  int _step = 0;
  bool _busy = false;
  String? _error;

  String? _filePath;
  String? _fileName;

  List<SheetGrid> _sheets = const [];
  int _sheetIndex = 0;

  ColumnMapping _mapping = const ColumnMapping.empty();
  ChecklistParseResult? _parsed;
  Set<String> _existingCodes = const {};

  int? _importedCount;
  int _skippedFromImport = 0;

  @override
  void initState() {
    super.initState();
    _loadExistingCodes();
  }

  /// 提前把项目里已有的编码取出来 —— 第 0 步要据此提示
  /// "再次导入会只追加新编码"，而不是等校验完才告诉用户。
  Future<void> _loadExistingCodes() async {
    try {
      final codes =
          await ref.read(itemRepositoryProvider).existingCodes(widget.projectId);
      if (mounted) setState(() => _existingCodes = codes);
    } catch (e) {
      Log.w('ChecklistImport', '读取已有编码失败：$e');
    }
  }

  // ───────────────────────────────────────────────────────────
  // 动作
  // ───────────────────────────────────────────────────────────

  Future<void> _pickFile() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final res = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ChecklistFileReader.supportedExtensions,
        withData: false,
      );
      if (!mounted) return;
      if (res == null || res.files.isEmpty) return; // 用户取消

      final f = res.files.single;
      final path = f.path;
      if (path == null) {
        setState(() => _error = '无法读取该文件路径，请换一个位置再试');
        return;
      }

      final sheets = await ChecklistFileReader.read(path);
      if (!mounted) return;
      if (sheets.isEmpty) {
        setState(() => _error = '文件里没有可读的数据表');
        return;
      }

      _filePath = path;
      _fileName = f.name;
      _sheets = sheets;
      _sheetIndex = 0;
      _mapping = ColumnMapper.autoDetect(sheets.first);

      setState(() => _step = 1);
    } catch (e, st) {
      Log.e('ChecklistImport', '读取清单失败', e, st);
      if (mounted) setState(() => _error = '读取失败：$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _chooseSheet(int i) {
    setState(() {
      _sheetIndex = i;
      _mapping = ColumnMapper.autoDetect(_sheets[i]);
      _step = 2;
    });
  }

  void _setHeaderRow(int row) {
    final g = _sheets[_sheetIndex];
    setState(() {
      // 必须整份重算列映射 —— 只改 headerRow 会让映射停留在原来那一行
      _mapping = ColumnMapper.forHeaderRow(g, row);
    });
  }

  Future<void> _runValidation() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final repo = ref.read(itemRepositoryProvider);
      _existingCodes = await repo.existingCodes(widget.projectId);

      final grid = _sheets[_sheetIndex];
      final result = ChecklistImporter.parse(
        grid: grid,
        mapping: _mapping,
        existingCodes: _existingCodes,
      );
      if (!mounted) return;
      setState(() {
        _parsed = result;
        _step = 3;
      });
    } catch (e, st) {
      Log.e('ChecklistImport', '校验失败', e, st);
      if (mounted) setState(() => _error = '校验失败：$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _doImport() async {
    final parsed = _parsed;
    if (parsed == null || !parsed.canProceed) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final repo = ref.read(itemRepositoryProvider);
      final startSeq = await repo.nextSeq(widget.projectId);
      final n = await repo.bulkInsert(
        widget.projectId,
        parsed.rows,
        startSeq: startSeq,
      );
      if (!mounted) return;
      setState(() {
        _importedCount = n;
        _skippedFromImport = parsed.rows.length - n;
        _step = 4;
      });
    } catch (e, st) {
      Log.e('ChecklistImport', '导入失败', e, st);
      if (mounted) setState(() => _error = '导入失败：$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ───────────────────────────────────────────────────────────
  // Build
  // ───────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final canBack = _step > 0 && _step < 4 && !_busy;

    return Scaffold(
      appBar: AppBar(
        title: const Text('导入货品清单'),
        leading: BackButton(
          onPressed: () {
            if (canBack) {
              setState(() => _step -= 1);
            } else {
              Navigator.of(context).maybePop();
            }
          },
        ),
      ),
      body: Column(
        children: [
          _StepIndicator(current: _step, titles: _stepTitles),
          if (_error != null)
            Container(
              width: double.infinity,
              color: AppTheme.redBg,
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
              child: Row(
                children: [
                  const Icon(Icons.error_outline, size: 17, color: AppTheme.red),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      _error!,
                      style: const TextStyle(fontSize: 12.5, color: AppTheme.red),
                    ),
                  ),
                ],
              ),
            ),
          Expanded(child: _buildStep()),
          _buildBottomBar(),
        ],
      ),
    );
  }

  Widget _buildStep() {
    if (_busy && _step <= 1) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: 14),
            Text('正在读取…', style: TextStyle(fontSize: 13, color: AppTheme.textMuted)),
          ],
        ),
      );
    }
    return switch (_step) {
      0 => _buildPickFile(),
      1 => _buildPickSheet(),
      2 => _buildColumnMapping(),
      3 => _buildValidation(),
      _ => _buildDone(),
    };
  }

  // ── Step 0 ──────────────────────────────────────────────

  Widget _buildPickFile() {
    final hasExisting = _existingCodes.isNotEmpty;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        StageEmptyState(
          icon: Icons.upload_file,
          title: '选择货品清单文件',
          hint: '支持 Excel 表格与 CSV：.xlsx、.xls（含 97-2003 老格式）、.csv。\n'
              '微信里收到的文件，先「用其他应用打开」保存到手机，再来这里选。',
          actionLabel: '选择文件',
          onAction: _busy ? null : _pickFile,
        ),
        const SizedBox(height: 4),
        // ── 拍照识别入口（老板 09-26 拍板）——纸质清单/图片清单走这里 ──
        OutlinedButton.icon(
          onPressed: _busy
              ? null
              : () => Navigator.of(context).push<String>(
                    MaterialPageRoute(
                      builder: (_) => ChecklistPhotoImportPage(
                          projectId: widget.projectId),
                    ),
                  ),
          style: OutlinedButton.styleFrom(
            foregroundColor: AppTheme.navy,
            side: const BorderSide(color: AppTheme.line),
            minimumSize: const Size(0, 48),
          ),
          icon: const Icon(Icons.document_scanner_outlined, size: 19),
          label: const Text('拍照 / 相册识别清单（没有 Excel 时用）'),
        ),
        if (hasExisting)
          const Padding(
            padding: EdgeInsets.only(top: 4),
            child: _HintCard(
              text: '本项目已有货品。再次导入会**只追加新编码**，'
                  '已存在的编码会被跳过 —— 它们已有的照片归属不受影响。',
            ),
          ),
      ],
    );
  }

  // ── Step 1 ──────────────────────────────────────────────

  Widget _buildPickSheet() {
    return ListView(
      padding: const EdgeInsets.all(14),
      children: [
        _FileChip(name: _fileName ?? '', path: _filePath ?? ''),
        const SizedBox(height: 12),
        const Text(
          '选择工作表',
          style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: AppTheme.navy),
        ),
        const SizedBox(height: 8),
        ...List.generate(_sheets.length, (i) {
          final s = _sheets[i];
          return Card(
            margin: const EdgeInsets.only(bottom: 8),
            child: ListTile(
              onTap: () => _chooseSheet(i),
              leading: const Icon(Icons.table_chart_outlined, color: AppTheme.navy),
              title: Text(s.name),
              subtitle: Text(
                '${s.rowCount} 行 · ${s.maxColumns} 列'
                '${s.rowCount > 0 ? '  ·  首行：${_snip(s.rows.first)}' : ''}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
              trailing: const Icon(Icons.chevron_right),
            ),
          );
        }),
      ],
    );
  }

  String _snip(List<String?> row) {
    final t = row.where((c) => (c ?? '').trim().isNotEmpty).take(3).join(' | ');
    return t.isEmpty ? '(空)' : t;
  }

  // ── Step 2 ──────────────────────────────────────────────

  Widget _buildColumnMapping() {
    final grid = _sheets[_sheetIndex];
    final headerLabels = (grid.rows.length > _mapping.headerRow)
        ? grid.rows[_mapping.headerRow]
        : <String?>[];
    final maxCols = grid.maxColumns;

    // 表头行候选：前 10 行
    final headerCandidates = List.generate(
      grid.rows.length < 10 ? grid.rows.length : 10,
      (i) => i,
    );

    return ListView(
      padding: const EdgeInsets.all(14),
      children: [
        _FileChip(name: '${_fileName ?? ''} › ${grid.name}', path: ''),

        const SizedBox(height: 12),
        Row(
          children: [
            const Text(
              '表头在第',
              style: TextStyle(fontSize: 13.5, color: AppTheme.textMain),
            ),
            const SizedBox(width: 8),
            DropdownButton<int>(
              value: _mapping.headerRow,
              underline: const SizedBox.shrink(),
              items: headerCandidates
                  .map((i) => DropdownMenuItem(
                        value: i,
                        child: Text('第 ${i + 1} 行'),
                      ))
                  .toList(),
              onChanged: (v) => v == null ? null : _setHeaderRow(v),
            ),
            const Spacer(),
            Text(
              '系统识别到 ${_mapping.columns.length} 个字段',
              style: const TextStyle(fontSize: 12, color: AppTheme.textMuted),
            ),
          ],
        ),

        const SizedBox(height: 10),

        // ── 列映射表 ──
        Card(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ...ChecklistField.values.map((f) {
                  final col = _mapping[f];
                  return Padding(
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 84,
                          child: Row(
                            children: [
                              Text(
                                f.label,
                                style: TextStyle(
                                  fontSize: 12.5,
                                  fontWeight: FontWeight.w600,
                                  color: f.isRequired ? AppTheme.accent : AppTheme.textMain,
                                ),
                              ),
                              if (f.isRequired)
                                const Text(
                                  '*',
                                  style: TextStyle(fontSize: 12, color: AppTheme.accent),
                                ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          // 用受控的 DropdownButton 而不是 DropdownButtonFormField：
                          // FormField 只在首次 build 取值，改表头行后不会刷新显示，
                          // 会出现"表头变了、下拉还显示旧列"的错位。
                          child: Container(
                            height: 38,
                            padding: const EdgeInsets.symmetric(horizontal: 8),
                            decoration: BoxDecoration(
                              border: Border.all(color: AppTheme.line),
                              borderRadius: BorderRadius.circular(5),
                            ),
                            child: DropdownButton<int?>(
                              value: col,
                              isExpanded: true,
                              isDense: true,
                              underline: const SizedBox.shrink(),
                              style: const TextStyle(
                                fontSize: 12.5,
                                color: AppTheme.textMain,
                              ),
                              items: [
                                const DropdownMenuItem<int?>(
                                  value: null,
                                  child: Text(
                                    '（不映射）',
                                    style: TextStyle(fontSize: 12.5),
                                  ),
                                ),
                                ...List.generate(
                                  maxCols,
                                  (c) => DropdownMenuItem<int?>(
                                    value: c,
                                    child: Text(
                                      _colLabel(headerLabels, c),
                                      style: const TextStyle(fontSize: 12.5),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                ),
                              ],
                              onChanged: (v) => setState(() {
                                _mapping = _mapping.withField(f, v);
                              }),
                            ),
                          ),
                        ),
                      ],
                    ),
                  );
                }),
              ],
            ),
          ),
        ),

        if (!_mapping.isValid)
          const Padding(
            padding: EdgeInsets.only(top: 10),
            child: _HintCard(
              text: '「货品编码」是必填的 —— 它是照片与货品建立对应关系的唯一依据。',
              danger: true,
            ),
          ),

        const SizedBox(height: 14),
        const Text(
          '数据预览（前 5 行）',
          style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: AppTheme.navy),
        ),
        const SizedBox(height: 7),
        _PreviewTable(
          grid: grid,
          headerRow: _mapping.headerRow,
          mapping: _mapping,
        ),
      ],
    );
  }

  String _colLabel(List<String?> headers, int c) {
    final h = (c < headers.length ? headers[c] : null)?.trim() ?? '';
    final letter = String.fromCharCode(65 + (c % 26));
    return h.isEmpty ? '第 $letter 列（无表头）' : '$h（$letter 列）';
  }

  // ── Step 3 ──────────────────────────────────────────────

  Widget _buildValidation() {
    final r = _parsed;
    if (r == null) return const SizedBox.shrink();

    final errors = r.issues.where((i) => i.level == IssueLevel.error).toList();
    final warns = r.issues.where((i) => i.level == IssueLevel.warning).toList();
    final infos = r.issues.where((i) => i.level == IssueLevel.info).toList();

    return ListView(
      padding: const EdgeInsets.all(14),
      children: [
        Card(
          color: r.canProceed ? AppTheme.greenBg : AppTheme.redBg,
          child: Padding(
            padding: const EdgeInsets.all(13),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  r.canProceed ? '校验通过，可以导入' : '校验未通过',
                  style: TextStyle(
                    fontSize: 14.5,
                    fontWeight: FontWeight.w700,
                    color: r.canProceed ? AppTheme.green : AppTheme.red,
                  ),
                ),
                const SizedBox(height: 7),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    StageBadge(
                      text: '将导入 ${r.rows.length} 件',
                      color: AppTheme.green,
                      icon: Icons.check,
                    ),
                    if (r.skippedRows > 0)
                      StageBadge(
                        text: '跳过 ${r.skippedRows} 行',
                        color: warns.isEmpty ? AppTheme.textMuted : AppTheme.amber,
                      ),
                    if (errors.isNotEmpty)
                      StageBadge(text: '错误 ${errors.length}', color: AppTheme.red),
                    if (warns.isNotEmpty)
                      StageBadge(text: '警告 ${warns.length}', color: AppTheme.amber),
                    if (infos.isNotEmpty)
                      StageBadge(text: '提示 ${infos.length}', color: AppTheme.blue),
                  ],
                ),
                const SizedBox(height: 9),
                Text(
                  '源表数据行 ${r.totalSourceRows} · 表头在第 ${r.headerRow + 1} 行',
                  style: const TextStyle(fontSize: 12, color: AppTheme.textMuted),
                ),
              ],
            ),
          ),
        ),

        if (r.issues.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 12),
            child: _HintCard(text: '没有发现任何问题。'),
          ),

        if (errors.isNotEmpty) ...[
          const SizedBox(height: 14),
          _IssueGroup(title: '错误（这些行不会被导入）', issues: errors, color: AppTheme.red),
        ],
        if (warns.isNotEmpty) ...[
          const SizedBox(height: 14),
          _IssueGroup(title: '警告（已处理，但你需要知道）', issues: warns, color: AppTheme.amber),
        ],
        if (infos.isNotEmpty) ...[
          const SizedBox(height: 14),
          _IssueGroup(title: '提示', issues: infos, color: AppTheme.blue),
        ],
      ],
    );
  }

  // ── Step 4 ──────────────────────────────────────────────

  Widget _buildDone() {
    final n = _importedCount ?? 0;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const SizedBox(height: 24),
        const Icon(Icons.check_circle, size: 56, color: AppTheme.green),
        const SizedBox(height: 14),
        Text(
          '已导入 $n 件货品',
          textAlign: TextAlign.center,
          style: const TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: AppTheme.navy,
          ),
        ),
        if (_skippedFromImport > 0) ...[
          const SizedBox(height: 8),
          Text(
            '另有 $_skippedFromImport 件因编码重复被跳过',
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 12.5, color: AppTheme.textMuted),
          ),
        ],
        const SizedBox(height: 22),
        const _HintCard(
          text: '下一步：回到「采集」，打开相机开始拍照。\n\n'
              '现场只需按快门，不用选货品、不用输入任何内容。',
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: () => Navigator.of(context).maybePop(),
          style: FilledButton.styleFrom(backgroundColor: AppTheme.accent),
          child: const Text('返回工作台'),
        ),
      ],
    );
  }

  // ── 底部操作栏 ──────────────────────────────────────────

  Widget _buildBottomBar() {
    // (按钮文案, 点击回调)；文案为 null 表示这一步不需要底部按钮
    // —— 第 1 步「选工作表」由列表项点击驱动，第 4 步已完成。
    final (String? label, VoidCallback? onTap) = switch (_step) {
      0 => ('选择文件', _busy ? null : _pickFile),
      2 => ('校验并预览', (_busy || !_mapping.isValid) ? null : _runValidation),
      3 => (
          '确认导入 ${_parsed?.rows.length ?? 0} 件',
          (_busy || !(_parsed?.canProceed ?? false)) ? null : _doImport,
        ),
      _ => (null, null),
    };

    if (label == null) return const SizedBox.shrink();

    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
        decoration: const BoxDecoration(
          color: AppTheme.card,
          border: Border(top: BorderSide(color: AppTheme.line)),
        ),
        child: SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: onTap,
            style: FilledButton.styleFrom(
              backgroundColor: AppTheme.accent,
              minimumSize: const Size(0, 50),
            ),
            child: _busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : Text(label),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 子组件
// ═══════════════════════════════════════════════════════════════

class _StepIndicator extends StatelessWidget {
  const _StepIndicator({required this.current, required this.titles});

  final int current;
  final List<String> titles;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppTheme.card,
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 11),
      child: Row(
        children: List.generate(titles.length * 2 - 1, (i) {
          if (i.isOdd) {
            return Expanded(
              child: Container(
                height: 2,
                margin: const EdgeInsets.symmetric(horizontal: 3),
                color: (i ~/ 2) < current ? AppTheme.accent : AppTheme.line,
              ),
            );
          }
          final idx = i ~/ 2;
          final done = idx < current;
          final active = idx == current;
          final c = done
              ? AppTheme.green
              : (active ? AppTheme.accent : AppTheme.textMuted);
          return Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 21,
                height: 21,
                decoration: BoxDecoration(
                  color: done
                      ? AppTheme.greenBg
                      : (active ? AppTheme.accent.withValues(alpha: 0.12) : AppTheme.bg),
                  shape: BoxShape.circle,
                  border: Border.all(color: c, width: active ? 1.6 : 1),
                ),
                child: Center(
                  child: done
                      ? const Icon(Icons.check, size: 12, color: AppTheme.green)
                      : Text(
                          '${idx + 1}',
                          style: TextStyle(
                            fontSize: 10.5,
                            fontWeight: FontWeight.w700,
                            color: c,
                          ),
                        ),
                ),
              ),
              const SizedBox(height: 3),
              Text(
                titles[idx],
                style: TextStyle(
                  fontSize: 9.5,
                  fontWeight: active ? FontWeight.w700 : FontWeight.w400,
                  color: c,
                ),
              ),
            ],
          );
        }),
      ),
    );
  }
}

class _FileChip extends StatelessWidget {
  const _FileChip({required this.name, required this.path});

  final String name;
  final String path;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppTheme.blueBg,
        borderRadius: BorderRadius.circular(7),
      ),
      child: Row(
        children: [
          const Icon(Icons.description_outlined, size: 16, color: AppTheme.blue),
          const SizedBox(width: 7),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.navy,
                  ),
                ),
                if (path.isNotEmpty)
                  Text(
                    path,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 10.5, color: AppTheme.textMuted),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PreviewTable extends StatelessWidget {
  const _PreviewTable({
    required this.grid,
    required this.headerRow,
    required this.mapping,
  });

  final SheetGrid grid;
  final int headerRow;
  final ColumnMapping mapping;

  @override
  Widget build(BuildContext context) {
    final headers = headerRow < grid.rows.length
        ? grid.rows[headerRow]
        : <String?>[];
    final start = headerRow + 1;
    final rows = grid.rows.skip(start).take(5).toList();
    if (rows.isEmpty) {
      return const _HintCard(text: '表头下方没有数据行。');
    }

    // 只展示映射到的列，避免宽表横向溢出
    final cols = (mapping.columns.values.toSet().toList()..sort());
    if (cols.isEmpty) {
      return const _HintCard(text: '还没有建立任何列映射。');
    }

    return Card(
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          headingRowHeight: 34,
          dataRowMinHeight: 30,
          dataRowMaxHeight: 34,
          columnSpacing: 14,
          horizontalMargin: 10,
          columns: cols.map((c) {
            final h = (c < headers.length ? headers[c] : null)?.trim() ?? '';
            return DataColumn(
              label: Text(
                h.isEmpty ? '第${String.fromCharCode(65 + (c % 26))}列' : h,
                style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700),
              ),
            );
          }).toList(),
          rows: rows.map((r) {
            return DataRow(
              cells: cols.map((c) {
                final v = c < r.length ? (r[c] ?? '') : '';
                return DataCell(
                  Text(
                    v,
                    style: const TextStyle(fontSize: 11.5),
                  ),
                );
              }).toList(),
            );
          }).toList(),
        ),
      ),
    );
  }
}

class _IssueGroup extends StatelessWidget {
  const _IssueGroup({
    required this.title,
    required this.issues,
    required this.color,
  });

  final String title;
  final List<ValidationIssue> issues;
  final Color color;

  @override
  Widget build(BuildContext context) {
    const maxShow = 40;
    final shown = issues.take(maxShow).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              title,
              style: TextStyle(
                fontSize: 13.5,
                fontWeight: FontWeight.w700,
                color: color,
              ),
            ),
            const SizedBox(width: 6),
            StageBadge(text: '${issues.length}', color: color),
          ],
        ),
        const SizedBox(height: 7),
        Card(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Column(
              children: [
                ...shown.map(
                  (i) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 52,
                          child: Text(
                            i.row > 0 ? '第${i.row}行' : '—',
                            style: const TextStyle(
                              fontSize: 11.5,
                              fontFamily: 'monospace',
                              color: AppTheme.textMuted,
                            ),
                          ),
                        ),
                        Expanded(
                          child: Text(
                            i.message,
                            style: const TextStyle(fontSize: 12.5, height: 1.6),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                if (issues.length > maxShow)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Text(
                      '还有 ${issues.length - maxShow} 条未显示',
                      style: const TextStyle(fontSize: 11.5, color: AppTheme.textMuted),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _HintCard extends StatelessWidget {
  const _HintCard({required this.text, this.danger = false});

  final String text;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final c = danger ? AppTheme.amber : AppTheme.blue;
    final bg = danger ? AppTheme.amberBg : AppTheme.blueBg;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: c.withValues(alpha: 0.25)),
      ),
      child: Text(
        text,
        style: TextStyle(fontSize: 12.5, color: c, height: 1.7),
      ),
    );
  }
}
