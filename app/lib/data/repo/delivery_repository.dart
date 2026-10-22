/// 交付记录读取（2026-10-20 v0.24.8）。
///
/// 打包完成时 `ExportService.build` 一直有写 `deliveries` 表，但从来没有人
/// 读它 —— 交付页只展示「本次运行里刚打的那个包」，退出重进就什么都看不到
/// （老板 10-20：「已经交付打包，退出重进，看不到前面打的包」）。
///
/// 这里只做**读 + 还原**：
///  · 按项目取最近 N 条（新的在前）；
///  · 把数据库里的单卷路径还原成「实际还在手机上的卷列表」——多卷的卷号
///    从文件名 `_第NN卷-共MM卷.zip` 推出来（DB 只存第一卷，见
///    export_service_impl 落库注释）。
///
/// 不写、不删：交付记录是历史事实，不该被 UI 顺手改掉。
library;

import 'dart:convert';
import 'dart:io';

import 'package:drift/drift.dart';
import 'package:path/path.dart' as p;

import '../../domain/export/delivery_history.dart';
import '../db/database.dart';

class DeliveryRepository {
  DeliveryRepository(this._db);

  final AppDatabase _db;

  /// 本项目最近的交付记录（新的在前）。
  ///
  /// [limit] 默认 8 条 —— 现场关心的是"最近打的那几个包"，
  /// 翻历史交给文件管理器（包本身就在项目导出目录里）。
  Future<List<DeliveryHistoryItem>> recentByProject(
    String projectId, {
    int limit = 8,
  }) async {
    final rows = await (_db.select(_db.deliveries)
          ..where((d) => d.projectId.equals(projectId))
          ..orderBy([(d) => OrderingTerm.desc(d.createdAt)])
          ..limit(limit))
        .get();
    final out = <DeliveryHistoryItem>[];
    for (final r in rows) {
      out.add(await _toItem(r));
    }
    return out;
  }

  Future<DeliveryHistoryItem> _toItem(Delivery r) async {
    final zip = r.zipPath ?? '';
    final volumes = await _volumePaths(zip);
    var bytes = r.bytes ?? 0;
    if (bytes <= 0 && volumes.isNotEmpty) {
      // 老记录没存 bytes：用现存卷文件大小兜底（可能不全，只用于展示）
      var sum = 0;
      for (final v in volumes) {
        try {
          sum += await File(v).length();
        } catch (_) {}
      }
      bytes = sum;
    }
    return DeliveryHistoryItem(
      id: r.id,
      createdAt: DateTime.fromMillisecondsSinceEpoch(r.createdAt),
      zipPath: zip,
      folderPath: zip.isEmpty ? '' : p.dirname(zip),
      volumePaths: volumes,
      bytes: bytes,
      itemCount: r.itemCount ?? 0,
      photoCount: r.photoCount ?? 0,
      compressed: _compressedOf(r.optionsJson),
    );
  }

  /// 数据库里的单卷路径 → 实际存在的全部卷。
  ///
  /// 单卷：就是那个 zip。
  /// 多卷：文件名 `_第01卷-共03卷.zip` → 同目录按卷序拼回去，
  ///       只返回**真实存在**的文件（被清理掉的卷不能出现在分享列表里，
  ///       否则分享面板会拿到一个死路径）。
  Future<List<String>> _volumePaths(String zipPath) async {
    if (zipPath.isEmpty) return const [];
    final name = p.basename(zipPath);
    final m = RegExp(r'_第(\d+)卷-共(\d+)卷\.zip$').firstMatch(name);
    if (m == null) {
      return await File(zipPath).exists() ? <String>[zipPath] : const [];
    }
    final total = int.tryParse(m.group(2)!) ?? 0;
    if (total <= 0) return const [];
    final prefix = name.substring(0, m.start);
    final dir = p.dirname(zipPath);
    final out = <String>[];
    for (var i = 1; i <= total; i++) {
      final nn = i.toString().padLeft(2, '0');
      final mm = total.toString().padLeft(2, '0');
      final path = p.join(dir, '${prefix}_第$nn卷-共$mm卷.zip');
      if (await File(path).exists()) out.add(path);
    }
    return out;
  }

  /// 当时的选项里 compressPhotos 是否为 true（老记录没有该键 → 当时默认开）。
  bool _compressedOf(String optionsJson) {
    try {
      final m = jsonDecode(optionsJson);
      if (m is Map && m['compressPhotos'] is bool) {
        return m['compressPhotos'] as bool;
      }
    } catch (_) {}
    // 2026-10-20 之前默认压缩；解析失败按「当时可能压缩过」展示更保守
    return true;
  }
}
