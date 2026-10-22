import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/ui/capture/gallery_picker_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 相册选择器「位置记忆」回归测试（2026-09-29）。
///
/// 现场真实动作：滚到相册深处挑一批 → 退出 → 过会儿再进 → 期望接着上次
/// 的位置往下挑。这条链路跨「滚动时记录 / 退出落盘 / 重新加载 / 异步翻页 /
/// 滚动跳转」五个环节，任一环节断了都表现为「回到顶部」，肉眼只看得到结果
/// —— 所以钉成测试：
///   · 保存侧：退出后 prefs 里必须是离开时顶部那张照片的 id（不是第一张）；
///   · 恢复侧：再次进入要滚回同一行（按行首对齐，不是像素级还原）。
///
/// 两条退出路径各测一遍：系统返回（dispose 兜底）和左上角关闭（主动保存）。
const _total = 300;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('gtick/gallery');
  final navKey = GlobalKey<NavigatorState>();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      switch (call.method) {
        case 'galleryStatus':
          return {'sdkInt': 34, 'granted': true, 'fullAccess': true};
        case 'queryGalleryBuckets':
          return [
            {'bucket': 'Camera', 'count': _total},
          ];
        case 'queryGalleryImages':
          final a = call.arguments as Map<dynamic, dynamic>;
          final limit = (a['limit'] as num?)?.toInt() ?? 120;
          final offset = (a['offset'] as num?)?.toInt() ?? 0;
          // id 与排序下标一致（id=i+1），便于从 id 反推「第几张」
          final out = <Map<String, Object?>>[];
          for (var i = offset; i < offset + limit && i < _total; i++) {
            out.add({
              'id': i + 1,
              'displayName': 'p_$i.jpg',
              'dateTakenMs': 1700000000000 - i * 60000,
              'sizeBytes': 1024,
              'mimeType': 'image/jpeg',
              'bucket': 'Camera',
            });
          }
          return out;
        case 'galleryThumb':
          return null; // 缩略图与定位无关
        case 'readGalleryImages':
          final ids = (call.arguments as Map)['ids'] as List<dynamic>;
          return [
            for (final e in ids)
              {
                'id': e,
                'tempPath': '/tmp/$e.jpg',
                'displayName': '$e.jpg',
                'sizeBytes': 10,
                'dateTakenMs': 1700000000000,
              },
          ];
        default:
          return null;
      }
    });
  });

  testWidgets('系统返回退出：再次进入回到上次位置', (tester) async {
    await tester.pumpWidget(ProviderScope(child: _Host(navKey: navKey)));
    final offset0 = await _enter(tester);
    expect(offset0, 0.0, reason: '首次进入应停在顶部');

    final left = await _scrollToMiddle(tester);

    navKey.currentState!.pop();
    await tester.pumpAndSettle();

    // 保存侧：必须是离开时顶部那张（不是第一张 —— 那是 offset 读成 0 的症状）
    final prefs = await SharedPreferences.getInstance();
    final savedId = prefs.getInt('gallery.last_viewed_id');
    expect(savedId, isNotNull, reason: '退出时必须把顶部照片 id 存下来');
    expect(prefs.getInt('gallery.last_viewed_ms'), isNotNull);
    expect(savedId, greaterThan(1),
        reason: '存成第一张说明退出时没读到滚动位置');

    final restored = await _enter(tester, awaitRestore: true);
    _expectSameRow(left, restored);
  });

  testWidgets('左上角关闭退出：再次进入回到上次位置', (tester) async {
    await tester.pumpWidget(ProviderScope(child: _Host(navKey: navKey)));
    await _enter(tester);

    final left = await _scrollToMiddle(tester);

    await tester.tap(find.byIcon(Icons.close));
    await tester.pumpAndSettle();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getInt('gallery.last_viewed_id'), greaterThan(1),
        reason: '主动退出路径也应记住位置');

    final restored = await _enter(tester, awaitRestore: true);
    _expectSameRow(left, restored);
  });

  testWidgets('选照片后导入退出：再次进入回到上次位置', (tester) async {
    await tester.pumpWidget(ProviderScope(child: _Host(navKey: navKey)));
    await _enter(tester);
    final left = await _scrollToMiddle(tester);

    // 选当前可见的第一张（缩略图 mock 返回 null，格子是占位图标）
    await tester.tap(find.byIcon(Icons.image).first);
    await tester.pump();
    await tester.tap(find.text('导入 1 张'));
    await tester.pumpAndSettle();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getInt('gallery.last_viewed_id'), greaterThan(1),
        reason: '导入退出这条路径最容易漏存位置（用户主诉场景）');

    final restored = await _enter(tester, awaitRestore: true);
    _expectSameRow(left, restored);
  });
}

/// 恢复是按「上次顶部那张照片」对齐到行首，不是像素级还原：落点等于或略
/// 早于离开位置，偏差不超过一行。
void _expectSameRow(double left, double restored) {
  expect(restored, lessThanOrEqualTo(left + 0.5));
  expect(left - restored, lessThan(300.0),
      reason: '再次进入应回到上次离开的位置（离开 $left，实际 $restored）');
}

/// 滚到中段：先滚到底把数据翻够（模拟用户往深处翻），再回到半程位置。
Future<double> _scrollToMiddle(WidgetTester tester) async {
  var c = _controller(tester)!;
  for (var i = 0; i < 6; i++) {
    c.jumpTo(c.position.maxScrollExtent);
    await tester.pump(const Duration(milliseconds: 16));
    await tester.pump(const Duration(milliseconds: 16));
  }
  await _offsetOfTop(tester, afterFrames: 40);
  c = _controller(tester)!;
  c.jumpTo(c.position.maxScrollExtent * 0.5);
  await _offsetOfTop(tester, afterFrames: 40);
  return _controller(tester)!.offset;
}

/// 进入选择器（点首页按钮 → 等路由动画 → 等加载/恢复流程跑完）。
Future<double> _enter(WidgetTester tester, {bool awaitRestore = false}) async {
  await tester.tap(find.text('打开相册'));
  await tester.pumpAndSettle();
  return _offsetOfTop(tester, afterFrames: 400, waitSnackBar: awaitRestore);
}

/// 推进若干帧，返回网格当前滚动偏移。
///
/// [waitSnackBar]=true 时等到「恢复流程的 SnackBar」出现再收尾（成功/失败
/// 都会弹）。只看 offset 是否稳定会误判 —— 恢复前 offset 恒为 0，一直"稳定"。
Future<double> _offsetOfTop(WidgetTester tester,
    {int afterFrames = 1, bool waitSnackBar = false}) async {
  var last = -1.0;
  var stable = 0;
  for (var i = 0; i < afterFrames; i++) {
    await tester.pump(const Duration(milliseconds: 16));
    final c = _controller(tester);
    if (c == null) continue;
    final v = c.offset;
    if (waitSnackBar) {
      final done = find
          .byType(SnackBar)
          .evaluate()
          .any((e) => (((e.widget as SnackBar).content as Text?)?.data ?? '')
              .contains('上次浏览'));
      if (done) {
        for (var k = 0; k < 8; k++) {
          await tester.pump(const Duration(milliseconds: 16));
        }
        return _controller(tester)?.offset ?? 0;
      }
      continue;
    }
    if ((v - last).abs() < 0.5) {
      stable++;
      if (stable >= 5) break;
    } else {
      stable = 0;
    }
    last = v;
  }
  if (waitSnackBar) {
    throw TestFailure('恢复流程未在 $afterFrames 帧内结束（无 SnackBar）');
  }
  return last < 0 ? 0 : last;
}

ScrollController? _controller(WidgetTester tester) {
  final f = find.byType(GridView);
  if (f.evaluate().isEmpty) return null;
  final c = tester.widget<GridView>(f).controller;
  return (c != null && c.hasClients) ? c : null;
}

class _Host extends StatelessWidget {
  const _Host({required this.navKey});

  final GlobalKey<NavigatorState> navKey;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navKey,
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: ElevatedButton(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => const GalleryPickerPage(projectId: 'p1'),
              )),
              child: const Text('打开相册'),
            ),
          ),
        ),
      ),
    );
  }
}
