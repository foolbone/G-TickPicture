// 诊断/验证探针：批量用 APP 真实的 ChecklistFileReader 读清单文件。
// 覆盖 xlsx / xls / csv 三条路径，输出前若干行做人工核对。
// ignore_for_file: avoid_print
// 运行（经 run_unsandboxed）：
//   dart run tool/probe_checklists.dart
import 'package:g_tick_picture/domain/checklist/checklist_file_reader.dart';

const _samples = <String, String>{
  'xlsx (标准)': r'D:\G-Tick\data\uploads\manifest_1_d3f924.xlsx',
  'xlsx (另一份)': r'D:\G-Tick\data\uploads\manifest_2_623eeb.xlsx',
  'csv': r'D:\G-Tick\data\uploads\manifest_3_6219fc.csv',
  'xls (BIFF8)': r'D:\G-Tick\data\uploads\manifest_4_004c0e.xls',
  'xlsx (同源对照)': r'C:\Users\Bone\Documents\manifest_4_004c0e.xlsx',
};

Future<void> main(List<String> args) async {
  final only = args.isNotEmpty ? args[0] : null;
  for (final e in _samples.entries) {
    if (only != null && !e.value.toLowerCase().endsWith(only.toLowerCase())) {
      continue;
    }
    print('=== ${e.key} ===');
    print('path: ${e.value}');
    try {
      final grids = await ChecklistFileReader.read(e.value);
      print('OK  sheets=${grids.length}');
      for (final g in grids) {
        print('  -- "${g.name}" ${g.rowCount} rows x ${g.maxColumns} cols');
      }
      final s = grids.first;
      print('  header: ${s.rows.first.join(" | ")}');
      if (s.rows.length > 1) {
        print('  row2  : ${s.rows[1].join(" | ")}');
      }
      print('  rowN  : ${s.rows.last.join(" | ")}');
    } catch (err) {
      print('FAILED: $err');
    }
    print('');
  }
}
