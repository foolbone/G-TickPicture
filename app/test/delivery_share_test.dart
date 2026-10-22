import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/export/delivery_share.dart';
import 'package:g_tick_picture/domain/export/export_service.dart';

/// 交付包分享策略（2026-10-01）。
///
/// 真机现象：**分卷后分享面板里没有微信**。
/// 根因不是卷的问题，是个数的问题 —— share_plus 在 Android 上
/// 按文件数分流 Intent：
///   1 个  → ACTION_SEND
///   ≥2 个 → ACTION_SEND_MULTIPLE      ← 微信没有注册这个 action
///
/// 所以本文件只钉一件事：**逐卷发送时每次只能传 1 个文件**。
/// 哪天有人图省事改回"一次全发"，微信就会再次从面板里消失。
void main() {
  DeliveryResult result({int volumes = 3}) => DeliveryResult(
        deliveryId: 'd1',
        zipPath: '/out/交付包_第01卷-共03卷.zip',
        folderPath: '/out/folder',
        bytes: 900 * 1024 * 1024,
        itemCount: 12,
        photoCount: 300,
        volumes: [
          for (var i = 1; i <= volumes; i++)
            DeliveryVolume(
              path: '/out/交付包_第0$i卷-共0$volumes卷.zip',
              bytes: 300 * 1024 * 1024,
            ),
        ],
      );

  test('逐卷发送：每卷都单独发，且每次只传 1 个文件', () async {
    final calls = <List<String>>[];
    final sharer = DeliverySharer((paths, {required subject, required text}) async {
      calls.add(paths);
    });

    final r = result(volumes: 3);
    for (final v in r.volumes) {
      await sharer.shareVolume(r, v);
    }

    // 发了 3 次…
    expect(calls.length, 3);
    // …每一次都只有 1 个文件 —— 这是微信能出现的唯一条件
    for (final call in calls) {
      expect(call.length, 1);
    }
    // 三卷互不重复、顺序不串
    expect(
      calls.map((c) => c.single).toSet().length,
      3,
      reason: '每一卷都要被单独发出去，不能重复也不能漏',
    );
  });

  test('一次全发：传全部卷（这条路径不含微信）', () async {
    final calls = <List<String>>[];
    final sharer = DeliverySharer((paths, {required subject, required text}) async {
      calls.add(paths);
    });

    await sharer.shareAll(result(volumes: 3));

    expect(calls.length, 1);
    expect(calls.single.length, 3);
  });

  test('单卷包：两种走法都只发 1 个文件，行为一致', () async {
    final calls = <List<String>>[];
    final sharer = DeliverySharer((paths, {required subject, required text}) async {
      calls.add(paths);
    });

    final single = result(volumes: 1);
    await sharer.shareVolume(single, single.volumes.first);
    await sharer.shareAll(single);

    expect(calls, [
      ['/out/交付包_第01卷-共01卷.zip'],
      ['/out/交付包_第01卷-共01卷.zip'],
    ]);
    expect(single.isSplit, isFalse);
  });

  test('旧记录兼容：volumes 为空时退回 zipPath', () async {
    final calls = <List<String>>[];
    final sharer = DeliverySharer((paths, {required subject, required text}) async {
      calls.add(paths);
    });

    const legacy = DeliveryResult(
      deliveryId: 'old',
      zipPath: '/out/legacy.zip',
      folderPath: '/out/folder',
      bytes: 1024,
      itemCount: 1,
      photoCount: 2,
    );

    await sharer.shareAll(legacy);

    expect(calls.single, ['/out/legacy.zip']);
  });
}
