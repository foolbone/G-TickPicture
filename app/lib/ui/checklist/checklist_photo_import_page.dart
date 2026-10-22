import 'dart:io';

import 'package:camera/camera.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';

import '../../app/providers.dart';
import '../../app/theme.dart';
import '../../core/logger.dart';
import '../../core/naming.dart';
import '../../domain/checklist/column_mapper.dart' show toHalfWidth;
import '../../domain/checklist/ocr_checklist_parser.dart';
import '../../domain/model/checklist_row.dart';
import '../../domain/ocr/mlkit_text_extractor.dart';
import '../widgets/stage_progress.dart';

/// 拍照 / 相册选图识别导入货品清单（老板 2026-09-26 拍板）。
///
/// 流程：选图（相册多选或现场拍）→ 离线 OCR → 行重组 → 编码/品名提取
/// → **人工预览确认（可勾选、可编辑）** → 走 [ItemRepository.bulkInsert] 落库。
///
/// 为什么中间必须有人工确认页：手机拍纸质清单的倾斜/反光/字迹
/// 都可能让识别出错，识别结果是"建议"，不是数据（§3 原则 7）。
/// 每一行的编码、品名都可直接改，改完才进库。
class ChecklistPhotoImportPage extends ConsumerStatefulWidget {
  const ChecklistPhotoImportPage({super.key, required this.projectId});

  final String projectId;

  @override
  ConsumerState<ChecklistPhotoImportPage> createState() =>
      _ChecklistPhotoImportPageState();
}

class _ChecklistPhotoImportPageState
    extends ConsumerState<ChecklistPhotoImportPage> {
  /// 0 选图 · 1 识别中 · 2 预览确认 · 3 完成
  int _stage = 0;
  bool _busy = false;
  String? _error;

  final _photos = <String>[];

  /// 识别失败的图（下标从 1 起，给人看）。
  final _failedPhotos = <int>[];

  OcrChecklistParseResult? _parsed;
  final _picked = <int>{};
  final _codeCtrls = <TextEditingController>[];
  final _nameCtrls = <TextEditingController>[];

  int? _importedCount;

  @override
  void dispose() {
    for (final c in _codeCtrls) {
      c.dispose();
    }
    for (final c in _nameCtrls) {
      c.dispose();
    }
    super.dispose();
  }

  // ───────────────────────────────────────────────────────────
  // 选图 / 拍照
  // ───────────────────────────────────────────────────────────

  Future<void> _pickImages() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final res = await FilePicker.platform.pickFiles(
        type: FileType.image,
        allowMultiple: true,
        withData: false,
      );
      if (!mounted) return;
      if (res == null) return; // 用户取消
      final paths = res.files
          .map((f) => f.path)
          .whereType<String>()
          .toList(growable: false);
      if (paths.isEmpty) {
        setState(() => _error = '没有读到可用的图片，请换几张再试');
        return;
      }
      setState(() {
        _photos.addAll(paths);
        _stage = 1;
      });
      await _recognize();
    } catch (e, st) {
      Log.e('ChecklistPhoto', '选图失败', e, st);
      if (mounted) setState(() => _error = '选图失败：$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _shoot() async {
    final path = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => const ChecklistCameraPage()),
    );
    if (path == null || !mounted) return;
    setState(() {
      _photos.add(path);
      _stage = 1;
    });
    await _recognize();
  }

  // ───────────────────────────────────────────────────────────
  // 识别
  // ───────────────────────────────────────────────────────────

  Future<void> _recognize() async {
    setState(() {
      _busy = true;
      _error = null;
      _failedPhotos.clear();
    });
    try {
      // 清单照片是"印刷体大字"，ML Kit 离线识别足够；
      // 不借用整理页的引擎偏好 —— 那是照片建议的设置，两回事。
      final extractor = MlKitTextExtractor();
      final lines = <String>[];
      for (var i = 0; i < _photos.length; i++) {
        setState(() => _recognizingIndex = i);
        try {
          final tokens = await extractor.extract(_photos[i]);
          lines.addAll(OcrChecklistParser.assembleLines(tokens));
        } catch (e) {
          Log.w('ChecklistPhoto', '第 ${i + 1} 张识别失败：$e');
          _failedPhotos.add(i + 1);
        }
      }

      final codes =
          await ref.read(itemRepositoryProvider).existingCodes(widget.projectId);
      final result = OcrChecklistParser.parse(
        lines: lines,
        existingCodes: codes,
      );
      if (!mounted) return;

      // 预览编辑控件与 rows 对齐；默认全部勾选
      for (final c in _codeCtrls) {
        c.dispose();
      }
      for (final c in _nameCtrls) {
        c.dispose();
      }
      _codeCtrls.clear();
      _nameCtrls.clear();
      for (final r in result.rows) {
        _codeCtrls.add(TextEditingController(text: r.code));
        _nameCtrls.add(TextEditingController(text: r.name ?? ''));
      }
      _picked
        ..clear()
        ..addAll(List.generate(result.rows.length, (i) => i));

      setState(() {
        _parsed = result;
        _stage = 2;
      });
    } catch (e, st) {
      Log.e('ChecklistPhoto', '识别失败', e, st);
      if (mounted) setState(() => _error = '识别失败：$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  int _recognizingIndex = 0;

  // ───────────────────────────────────────────────────────────
  // 导入
  // ───────────────────────────────────────────────────────────

  Future<void> _doImport() async {
    final parsed = _parsed;
    if (parsed == null || _picked.isEmpty) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      // 用编辑后的编码/品名重建行 —— 人工改过的以人为准
      final rows = <ChecklistRow>[];
      for (final i in _picked) {
        final src = parsed.rows[i];
        final code = toHalfWidth(_codeCtrls[i].text).trim();
        if (code.isEmpty) continue; // 用户清空了编码 = 放弃这一行
        final name = _nameCtrls[i].text.trim();
        rows.add(ChecklistRow(
          sourceRow: src.sourceRow,
          code: code,
          codeSafe: safeFileName(code),
          name: name.isEmpty ? null : name,
          requiredPhotos: src.requiredPhotos,
          container: src.container,
          sourceLineCount: src.sourceLineCount,
        ));
      }
      if (rows.isEmpty) {
        setState(() => _error = '没有可导入的行（编码都为空）');
        return;
      }

      final repo = ref.read(itemRepositoryProvider);
      final startSeq = await repo.nextSeq(widget.projectId);
      final n = await repo.bulkInsert(widget.projectId, rows, startSeq: startSeq);
      if (!mounted) return;
      setState(() {
        _importedCount = n;
        _stage = 3;
      });
    } catch (e, st) {
      Log.e('ChecklistPhoto', '导入失败', e, st);
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
    return Scaffold(
      appBar: AppBar(
        title: const Text('拍照识别清单'),
        leading: BackButton(
          onPressed: () {
            if (_stage == 2 && !_busy) {
              // 回到选图重来（识别结果丢掉，照片保留可重拍）
              setState(() {
                _stage = 0;
                _parsed = null;
              });
            } else {
              Navigator.of(context).maybePop();
            }
          },
        ),
      ),
      body: Column(
        children: [
          if (_error != null)
            Container(
              width: double.infinity,
              color: AppTheme.redBg,
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
              child: Row(
                children: [
                  const Icon(Icons.error_outline,
                      size: 17, color: AppTheme.red),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      _error!,
                      style: const TextStyle(
                          fontSize: 12.5, color: AppTheme.red),
                    ),
                  ),
                ],
              ),
            ),
          Expanded(child: _buildBody()),
          _buildBottomBar(),
        ],
      ),
    );
  }

  Widget _buildBody() {
    return switch (_stage) {
      0 => _buildPick(),
      1 => _buildRecognizing(),
      2 => _buildPreview(),
      _ => _buildDone(),
    };
  }

  // ── Stage 0：选图 / 拍照 ──────────────────────────────────

  Widget _buildPick() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const StageEmptyState(
          icon: Icons.document_scanner_outlined,
          title: '拍下清单，或从相册选图',
          hint: '适合手里只有纸质清单、Excel 表或微信图片的场景。\n\n'
              '· 一页拍一张，字尽量占满画面、避免反光\n'
              '· 可以连续选多张，识别完后逐行确认再导入\n'
              '· 认不出的行会在预览里标出来，不会悄悄进库',
        ),
        const SizedBox(height: 6),
        FilledButton.icon(
          onPressed: _busy ? null : _shoot,
          style: FilledButton.styleFrom(
            backgroundColor: AppTheme.accent,
            minimumSize: const Size(0, 50),
          ),
          icon: const Icon(Icons.photo_camera_outlined),
          label: const Text('拍照'),
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: _busy ? null : _pickImages,
          style: OutlinedButton.styleFrom(
            foregroundColor: AppTheme.navy,
            side: const BorderSide(color: AppTheme.line),
            minimumSize: const Size(0, 50),
          ),
          icon: const Icon(Icons.photo_library_outlined),
          label: const Text('从相册选择'),
        ),
      ],
    );
  }

  // ── Stage 1：识别中 ──────────────────────────────────────

  Widget _buildRecognizing() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 14),
          Text(
            '正在识别第 ${_recognizingIndex + 1} / ${_photos.length} 张…',
            style:
                const TextStyle(fontSize: 13, color: AppTheme.textMuted),
          ),
          const SizedBox(height: 6),
          const Text(
            '识别在手机本地完成，不联网、不上传',
            style: TextStyle(fontSize: 11.5, color: AppTheme.textMuted),
          ),
        ],
      ),
    );
  }

  // ── Stage 2：预览确认 ────────────────────────────────────

  Widget _buildPreview() {
    final parsed = _parsed!;
    final warns =
        parsed.issues.where((i) => i.level == IssueLevel.warning).toList();
    final infos =
        parsed.issues.where((i) => i.level == IssueLevel.info).toList();

    return ListView(
      padding: const EdgeInsets.all(14),
      children: [
        Card(
          color: parsed.rows.isNotEmpty ? AppTheme.greenBg : AppTheme.amberBg,
          child: Padding(
            padding: const EdgeInsets.all(13),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  parsed.rows.isNotEmpty
                      ? '认出 ${parsed.rows.length} 件货品 —— 请逐行确认'
                      : '没有认出货品编码',
                  style: TextStyle(
                    fontSize: 14.5,
                    fontWeight: FontWeight.w700,
                    color: parsed.rows.isNotEmpty
                        ? AppTheme.green
                        : AppTheme.amber,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  '共 ${parsed.totalLines} 行文字 · 编码和品名都可以直接改，'
                  '改完点下面「导入」',
                  style: const TextStyle(
                      fontSize: 12, color: AppTheme.textMuted),
                ),
              ],
            ),
          ),
        ),
        if (_failedPhotos.isNotEmpty) ...[
          const SizedBox(height: 10),
          _HintCard(
            danger: true,
            text: '第 ${_failedPhotos.join('、')} 张识别失败'
                '（可能太暗或对不上焦）—— 已跳过，可返回重拍。',
          ),
        ],
        if (warns.isNotEmpty) ...[
          const SizedBox(height: 10),
          _IssueGroup(title: '没认出的行', issues: warns, color: AppTheme.amber),
        ],
        if (infos.isNotEmpty) ...[
          const SizedBox(height: 10),
          _IssueGroup(title: '提示', issues: infos, color: AppTheme.blue),
        ],
        const SizedBox(height: 10),
        Row(
          children: [
            Text(
              '候选 ${_picked.length}/${parsed.rows.length} 件',
              style: const TextStyle(
                fontSize: 13.5,
                fontWeight: FontWeight.w700,
                color: AppTheme.navy,
              ),
            ),
            const Spacer(),
            TextButton(
              onPressed: () => setState(() {
                if (_picked.length == parsed.rows.length) {
                  _picked.clear();
                } else {
                  _picked
                    ..clear()
                    ..addAll(List.generate(parsed.rows.length, (i) => i));
                }
              }),
              child: Text(
                _picked.length == parsed.rows.length ? '全不选' : '全选',
                style: const TextStyle(fontSize: 12.5),
              ),
            ),
          ],
        ),
        ...List.generate(parsed.rows.length, _buildRowCard),
      ],
    );
  }

  Widget _buildRowCard(int i) {
    final r = _parsed!.rows[i];
    final checked = _picked.contains(i);

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      color: checked ? null : AppTheme.bg,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 10, 10),
        child: Column(
          children: [
            Row(
              children: [
                Checkbox(
                  value: checked,
                  onChanged: (v) => setState(() {
                    v == true ? _picked.add(i) : _picked.remove(i);
                  }),
                ),
                Text(
                  '第 ${r.sourceRow} 行'
                  '${r.sourceLineCount > 1 ? '（合并 ${r.sourceLineCount} 行）' : ''}',
                  style: const TextStyle(
                      fontSize: 11.5, color: AppTheme.textMuted),
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.only(left: 10),
              child: Row(
                children: [
                  const SizedBox(
                    width: 42,
                    child: Text('编码',
                        style: TextStyle(
                            fontSize: 12, color: AppTheme.textMuted)),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _codeCtrls[i],
                      style: const TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w700,
                          fontFamily: 'monospace'),
                      decoration: const InputDecoration(
                        isDense: true,
                        border: OutlineInputBorder(),
                        contentPadding: EdgeInsets.symmetric(
                            horizontal: 8, vertical: 8),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 6),
            Padding(
              padding: const EdgeInsets.only(left: 10),
              child: Row(
                children: [
                  const SizedBox(
                    width: 42,
                    child: Text('品名',
                        style: TextStyle(
                            fontSize: 12, color: AppTheme.textMuted)),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _nameCtrls[i],
                      style: const TextStyle(fontSize: 13),
                      decoration: const InputDecoration(
                        isDense: true,
                        border: OutlineInputBorder(),
                        hintText: '（可留空，事后补）',
                        hintStyle: TextStyle(fontSize: 12),
                        contentPadding: EdgeInsets.symmetric(
                            horizontal: 8, vertical: 8),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── Stage 3：完成 ────────────────────────────────────────

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
        const SizedBox(height: 22),
        const _HintCard(
          text: '货品已进入清单缺口视图 —— 到「照片」页开拍即可，'
              '点那里的「缺口 N 件」就能看到漏了哪件。',
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: () => Navigator.of(context).maybePop(),
          style: FilledButton.styleFrom(backgroundColor: AppTheme.accent),
          child: const Text('完成'),
        ),
      ],
    );
  }

  // ── 底部操作栏 ──────────────────────────────────────────

  Widget _buildBottomBar() {
    final (String? label, VoidCallback? onTap) = switch (_stage) {
      2 => (
          '导入 ${_picked.length} 件',
          (_busy || _picked.isEmpty) ? null : _doImport,
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
                        strokeWidth: 2, color: Colors.white),
                  )
                : Text(label),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 轻量拍照页：拍一张 → 返回路径。与采集相机完全独立
//（清单照片不是货品照片，绝不进采集库 / 相册镜像）。
// ═══════════════════════════════════════════════════════════════

class ChecklistCameraPage extends StatefulWidget {
  const ChecklistCameraPage({super.key});

  @override
  State<ChecklistCameraPage> createState() => _ChecklistCameraPageState();
}

class _ChecklistCameraPageState extends State<ChecklistCameraPage> {
  CameraController? _controller;
  String? _error;
  bool _shooting = false;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final status = await Permission.camera.request();
    if (!status.isGranted) {
      if (mounted) {
        setState(
            () => _error = '没有相机权限 —— 请到系统设置里允许，或改用「从相册选择」');
      }
      return;
    }
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        if (mounted) setState(() => _error = '这台设备没有可用相机');
        return;
      }
      final back = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
      final ctrl = CameraController(
        back,
        ResolutionPreset.high,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.jpeg,
      );
      await ctrl.initialize();
      if (!mounted) {
        await ctrl.dispose();
        return;
      }
      setState(() => _controller = ctrl);
    } catch (e) {
      Log.e('ChecklistCamera', '相机初始化失败', e);
      if (mounted) setState(() => _error = '相机初始化失败：$e');
    }
  }

  Future<void> _shoot() async {
    final ctrl = _controller;
    if (ctrl == null || !ctrl.value.isInitialized || _shooting) return;
    setState(() => _shooting = true);
    try {
      final dir = await getTemporaryDirectory();
      final sub = Directory('${dir.path}/checklist_ocr');
      if (!sub.existsSync()) sub.createSync(recursive: true);
      final file =
          File('${sub.path}/${DateTime.now().millisecondsSinceEpoch}.jpg');
      final shot = await ctrl.takePicture();
      await shot.saveTo(file.path);
      if (!mounted) return;
      Navigator.of(context).pop(file.path);
    } catch (e) {
      Log.e('ChecklistCamera', '拍照失败', e);
      if (mounted) {
        setState(() => _shooting = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('拍照失败，请再试一次：$e')),
        );
      }
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ctrl = _controller;
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: const Text('拍清单'),
      ),
      body: _error != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  _error!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.white70, fontSize: 13.5),
                ),
              ),
            )
          : ctrl == null || !ctrl.value.isInitialized
              ? const Center(
                  child: CircularProgressIndicator(color: Colors.white),
                )
              : Stack(
                  alignment: Alignment.bottomCenter,
                  children: [
                    Positioned.fill(child: CameraPreview(ctrl)),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 28),
                      child: GestureDetector(
                        onTap: _shooting ? null : _shoot,
                        child: Container(
                          width: 72,
                          height: 72,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: Colors.white.withValues(alpha: 0.9),
                            border: Border.all(color: Colors.white, width: 4),
                          ),
                          child: _shooting
                              ? const Padding(
                                  padding: EdgeInsets.all(22),
                                  child: CircularProgressIndicator(
                                      strokeWidth: 2),
                                )
                              : const Icon(Icons.photo_camera_outlined,
                                  size: 30, color: Colors.black87),
                        ),
                      ),
                    ),
                  ],
                ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// 子组件（样式与 checklist_import_page 保持同款）
// ═══════════════════════════════════════════════════════════════

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
    const maxShow = 30;
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
                            style:
                                const TextStyle(fontSize: 12.5, height: 1.6),
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
                      style: const TextStyle(
                          fontSize: 11.5, color: AppTheme.textMuted),
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
