import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/logger.dart';
import '../ui/capture/system_camera_actions.dart';
import 'providers.dart';
import 'router.dart';
import 'theme.dart';

/// App 根组件。
///
/// 兼职「进程被杀恢复」（v0.24.9）：拍照期间 App 在系统相机的后台，
/// 低内存设备会杀掉进程 —— 重启后 go_router 回到 initialLocation
/// （列表页）、收图上下文全丢，老板 10-20 看到的就是「回到项目列表页、
/// 照片没入库」。首帧之后做两件事把现场找回来：
///  ① 把用户送回最后在用的项目页（半小时内有效）；
///  ② 有挂起的拍照会话就把收图补跑一遍（原生侧持久化了收图三要素，
///     Dart 侧持久化了项目归属），照片自动进项目。
class GtickApp extends ConsumerStatefulWidget {
  const GtickApp({super.key});

  /// 全局 SnackBar 通道（v0.24.11）：进程被杀恢复补收照片时，人已经在
  /// 项目页了，页面级 ScaffoldMessenger 不好找 —— 用根上的这把 key，
  /// 任何地方都能把「照片补回来了」送到用户眼前。
  static final GlobalKey<ScaffoldMessengerState> scaffoldMessengerKey =
      GlobalKey<ScaffoldMessengerState>();

  @override
  ConsumerState<GtickApp> createState() => _GtickAppState();
}

class _GtickAppState extends ConsumerState<GtickApp> {
  @override
  void initState() {
    super.initState();
    // 项目页路由变化都记下来 —— 只记项目页：恢复只针对「拍到一半被杀」
    // 的场景，别的页面回列表即可。
    appRouter.routerDelegate.addListener(_rememberLocation);
    // 首帧后再恢复：prefs / 原生通道都要 binding 就绪，也不挡冷启动。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _recoverAfterRestart();
    });
  }

  @override
  void dispose() {
    appRouter.routerDelegate.removeListener(_rememberLocation);
    super.dispose();
  }

  void _rememberLocation() {
    final uri = appRouter.routeInformationProvider.value.uri.toString();
    final prefs = ref.read(cameraPreferencesProvider);
    if (uri.startsWith('${AppRoutes.project}/')) {
      prefs.saveLastLocation(uri);
    } else if (uri == AppRoutes.projects) {
      // 主动回到列表 = 离开项目 —— 不再恢复进旧项目。
      prefs.clearLastLocation();
    }
  }

  Future<void> _recoverAfterRestart() async {
    // ── ① 导航恢复 ──
    // 只在确实停在 initialLocation（列表页）时才跳：正常启动也在列表页，
    // 但「半小时内用过某项目」就是被杀重启的特征。
    try {
      final prefs = ref.read(cameraPreferencesProvider);
      final last = await prefs.lastLocation();
      if (last != null && mounted) {
        final (loc, at) = last;
        final fresh =
            DateTime.now().difference(at) < const Duration(minutes: 30);
        final onRoot = appRouter.routeInformationProvider.value.uri
                .toString() ==
            AppRoutes.projects;
        if (fresh && onRoot) {
          appRouter.go(loc);
        }
      }
    } catch (e) {
      Log.w('App', 'location restore failed :: $e');
    }

    // ── ② 待收照片恢复 ──
    // 「读后即清」：恢复动作本身只发生一次（再次被杀会留下新的标记）。
    // 超过 15 分钟的旧标记丢弃 —— 那些照片用户多半已从相册导入过，
    // 自动补收反而有重复风险。
    try {
      final prefs = ref.read(cameraPreferencesProvider);
      final pending = await prefs.takePendingSession();
      if (pending == null) return;
      final age = DateTime.now().difference(pending.launchedAt);
      if (age > const Duration(minutes: 15)) {
        Log.w('App', 'stale pending session dropped (age=$age)');
        return;
      }
      final recovered = await recoverPendingCameraSession(
        ref,
        pending.projectId,
        pending.launchedAt,
      );
      // v0.24.11：恢复必须**可见** —— 用户刚经历「拍照后 App 没了」，
      // 沉默地补收会让人以为照片丢了。导航已先跳回项目页，这里补一句。
      if (recovered > 0) {
        GtickApp.scaffoldMessengerKey.currentState?.showSnackBar(
          SnackBar(
            content: Text('已补收 $recovered 张拍照期间的照片'),
            duration: const Duration(seconds: 3),
          ),
        );
      }
    } catch (e) {
      Log.w('App', 'pending session recovery failed :: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: '预检拍照',
      debugShowCheckedModeBanner: false,
      scaffoldMessengerKey: GtickApp.scaffoldMessengerKey,
      theme: AppTheme.light(),
      routerConfig: appRouter,

      // 中文界面。清单导入会用到日期/文件选择器，本地化必须给上。
      locale: const Locale('zh', 'CN'),
      supportedLocales: const [
        Locale('zh', 'CN'),
        Locale('en', 'US'),
      ],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],

      // 锁定文字缩放上限：现场设备可能被设成超大字体，
      // 而采集页的按钮尺寸是按固定 dp 算的，放大后容易挤压错位（§1.3）。
      builder: (context, child) {
        final mq = MediaQuery.of(context);
        return MediaQuery(
          data: mq.copyWith(
            textScaler: TextScaler.linear(
              mq.textScaler.scale(1.0).clamp(0.9, 1.15),
            ),
          ),
          child: child ?? const SizedBox.shrink(),
        );
      },
    );
  }
}
