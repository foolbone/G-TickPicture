// 进程内 analyzer（不启动 analysis server）。
//
// 为什么需要：agent 沙箱隔离了 Windows 命名管道，`dart analyze` 的
// analysis_server 子进程会以 CreateFile failed 5 拒绝启动；本脚本在
// 当前进程里直接构造 AnalysisContextCollection，仍能做完整的类型检查。
//
// 用法（在 app/ 下）：
//   dart --packages=.dart_tool/package_config.json \
//     tool/_analyze_inprocess.dart lib/foo.dart test/bar_test.dart
//
// 输出：每条 ERROR/WARNING + 汇总；有 ERROR 时退出码 1。
import 'dart:io';

import 'package:analyzer/dart/analysis/analysis_context_collection.dart';
import 'package:analyzer/dart/analysis/results.dart';
import 'package:analyzer/diagnostic/diagnostic.dart';

Future<void> main(List<String> args) async {
  final targets = args
      .map((a) => File(a).absolute.path)
      .where((p) => p.endsWith('.dart'))
      .toList();
  if (targets.isEmpty) {
    stderr.writeln('usage: dart _analyze_inprocess.dart <files...>');
    exitCode = 2;
    return;
  }
  final collection = AnalysisContextCollection(
    includedPaths: targets.map((p) => File(p).parent.path).toSet().toList(),
  );
  var errors = 0;
  var warnings = 0;
  for (final path in targets) {
    final context = collection.contextFor(path);
    final result = await context.currentSession.getErrors(path);
    if (result is! ErrorsResult) continue;
    for (final e in result.errors) {
      if (e.severity == Severity.error) {
        errors++;
      } else if (e.severity == Severity.warning) {
        warnings++;
      } else {
        continue;
      }
      final loc = result.lineInfo.getLocation(e.offset);
      stdout.writeln(
        '${e.severity.name.toUpperCase()} $path:${loc.lineNumber}:'
        '${loc.columnNumber} ${e.message}',
      );
    }
  }
  await collection.dispose();
  stdout.writeln('ERRORS=$errors WARNINGS=$warnings');
  exitCode = errors == 0 ? 0 : 1;
}
