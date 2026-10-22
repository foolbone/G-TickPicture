/// 交付记录读取（2026-10-20 v0.24.8）。
///
/// 钉住老板反馈「已经交付打包，退出重进看不到前面打的包」的修复：
/// 打包时 deliveries 表一直在写，本次补的是**读口**。这里锁三件事：
///  ① 按项目取、新的在前、limit 生效；
///  ② 单卷/多卷路径都能还原成「实际还在手机上的文件」——
///     多卷的卷号是从文件名 `_第NN卷-共MM卷.zip` 推的（DB 只存第一卷）；
///  ③ 交付默认**不压缩画质**（2026-10-20 老板拍板）。
@Timeout(Duration(minutes: 2))
library;

import 'dart:convert';
import 'dart:io';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/delivery_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/export/export_service.dart';
import 'package:path/path.dart' as p;

void main() {
  late AppDatabase db;
  late DeliveryRepository repo;
  late String projectId;
  late Directory tmp;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    repo = DeliveryRepository(db);
    projectId = await ProjectRepository(db).create(name: '交付记录测试');
    tmp = await Directory.systemTemp.createTemp('gt_delivery_hist_');
  });

  tearDown(() async {
    await db.close();
    try {
      if (await tmp.exists()) await tmp.delete(recursive: true);
    } catch (_) {}
  });

  Future<String> makeZip(String name) async {
    final f = File(p.join(tmp.path, name));
    await f.writeAsBytes([1, 2, 3, 4]);
    return f.path;
  }

  Future<void> insertDelivery({
    required String id,
    required int createdAt,
    String? zipPath,
    int? bytes,
    bool compress = false,
    int photoCount = 3,
  }) async {
    await db.into(db.deliveries).insert(
          DeliveriesCompanion.insert(
            id: id,
            projectId: projectId,
            createdAt: createdAt,
            optionsJson: jsonEncode({'compressPhotos': compress}),
            zipPath: Value(zipPath),
            bytes: Value(bytes),
            itemCount: const Value(1),
            photoCount: Value(photoCount),
          ),
        );
  }

  test('按项目取最近交付：新的在前，limit 生效', () async {
    await insertDelivery(id: 'a', createdAt: 1000, zipPath: await makeZip('a.zip'));
    await insertDelivery(id: 'b', createdAt: 3000, zipPath: await makeZip('b.zip'));
    await insertDelivery(id: 'c', createdAt: 2000, zipPath: await makeZip('c.zip'));

    final all = await repo.recentByProject(projectId);
    expect(all.map((e) => e.id).toList(), ['b', 'c', 'a'],
        reason: 'createdAt 降序 —— 最近打的包排最前');

    final two = await repo.recentByProject(projectId, limit: 2);
    expect(two.map((e) => e.id).toList(), ['b', 'c']);
  });

  test('其他项目的交付不会混进来', () async {
    final other = await ProjectRepository(db).create(name: '另一个项目');
    await db.into(db.deliveries).insert(
          DeliveriesCompanion.insert(
            id: 'other',
            projectId: other,
            createdAt: 5000,
            optionsJson: jsonEncode({'compressPhotos': false}),
          ),
        );
    await insertDelivery(id: 'mine', createdAt: 1000, zipPath: await makeZip('m.zip'));

    final mine = await repo.recentByProject(projectId);
    expect(mine.map((e) => e.id).toList(), ['mine']);
  });

  test('单卷：路径还在 → 可分享；文件没了 → missing', () async {
    final zip = await makeZip('one.zip');
    await insertDelivery(id: 'one', createdAt: 1000, zipPath: zip);

    final items = await repo.recentByProject(projectId);
    expect(items.single.volumePaths, [zip]);
    expect(items.single.missing, isFalse);
    expect(items.single.isSplit, isFalse);

    await File(zip).delete();
    final after = await repo.recentByProject(projectId);
    expect(after.single.missing, isTrue,
        reason: '文件被清理后不能给分享面板一个死路径');
  });

  test('多卷：从文件名还原全部卷，缺哪卷就少哪卷', () async {
    // 真实命名：{zipBase}_第NN卷-共MM卷.zip（见 export_service_impl）
    final v1 = await makeZip('包_第01卷-共03卷.zip');
    final v2 = await makeZip('包_第02卷-共03卷.zip');
    final v3 = await makeZip('包_第03卷-共03卷.zip');
    await insertDelivery(id: 'multi', createdAt: 1000, zipPath: v1);

    final items = await repo.recentByProject(projectId);
    expect(items.single.volumePaths, [v1, v2, v3]);
    expect(items.single.isSplit, isTrue);

    // 卷 2 被清理 → 只剩两卷，且顺序不乱
    await File(v2).delete();
    final after = await repo.recentByProject(projectId);
    expect(after.single.volumePaths, [v1, v3]);
  });

  test('压缩标记从 optionsJson 还原（老记录缺键 → 按当时默认开处理）', () async {
    await insertDelivery(
        id: 'raw', createdAt: 1000, zipPath: await makeZip('r.zip'), compress: false);
    await insertDelivery(
        id: 'cmp', createdAt: 2000, zipPath: await makeZip('c.zip'), compress: true);
    // 老记录：optionsJson 里没有 compressPhotos 键
    await db.into(db.deliveries).insert(
          DeliveriesCompanion.insert(
            id: 'legacy',
            projectId: projectId,
            createdAt: 3000,
            optionsJson: '{}',
          ),
        );

    final items = await repo.recentByProject(projectId);
    final byId = {for (final e in items) e.id: e};
    expect(byId['raw']!.compressed, isFalse);
    expect(byId['cmp']!.compressed, isTrue);
    expect(byId['legacy']!.compressed, isTrue,
        reason: '2026-10-20 之前默认压缩，缺键按「可能压过」展示');
  });

  test('交付默认不压缩画质（2026-10-20 老板拍板）', () {
    const o = ExportOptions();
    expect(o.compressPhotos, isFalse,
        reason: '默认交付原图；要发微信才手动打开压缩');
    // 其余默认值保持不变（别在改一个开关时顺手动了别的）
    expect(o.includeRaw, isTrue);
    expect(o.includeManifest, isTrue);
    expect(o.groupByCarton, isTrue);
    expect(o.splitVolumes, isTrue);
  });
}
