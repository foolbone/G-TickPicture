import 'dart:async';
import 'dart:io';

import 'package:drift/drift.dart' show QueryRow, Variable;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/app_info.dart';
import '../core/logger.dart';
import '../data/db/database.dart';
import '../data/db/integrity_checks.dart';
import '../data/fs/project_paths.dart';
import '../data/fs/storage_service.dart';
import '../data/repo/capture_repository.dart';
import '../data/repo/delivery_repository.dart';
import '../data/repo/item_repository.dart';
import '../data/repo/organize_repository.dart';
import '../data/repo/project_repository.dart';
import '../data/repo/search_repository.dart';
import '../domain/assign/assign_service.dart';
import '../domain/capture/camera_capture_service.dart';
import '../domain/capture/camera_preferences.dart';
import '../domain/capture/capture_service.dart';
import '../domain/capture/gallery_meta_service.dart';
import '../domain/capture/gallery_service.dart';
import '../domain/capture/native_gallery_service.dart';
import '../domain/capture/system_camera_service.dart';
import '../domain/export/delivery_history.dart';
import '../domain/export/delivery_plan_builder.dart';
import '../domain/export/export_service.dart';
import '../domain/export/export_service_impl.dart';
import '../domain/model/assigned_group.dart';
import '../domain/model/bulk_confirm_candidate.dart';
import '../domain/model/delivery_plan.dart';
import '../domain/model/delivery_readiness.dart';
import '../domain/model/duplicate_photos.dart';
import '../domain/model/item_with_shot.dart';
import '../domain/model/open_group.dart';
import '../domain/model/photo_search_hit.dart';
import '../domain/model/photo_thumb.dart';
import '../domain/model/project_summary.dart';
import '../domain/ocr/mlkit_text_extractor.dart';
import '../domain/ocr/ocr_engine.dart';
import '../domain/ocr/ocr_engine_factory.dart';
import '../domain/photo/photo_deletion_service.dart';
import '../domain/search/recent_searches.dart';
import '../domain/suggest/suggest_pipeline.dart';

// ═══════════════════════════════════════════════════════════════
// 数据库
// ═══════════════════════════════════════════════════════════════

/// 唯一的数据库实例。
///
/// 测试时用 `ProviderScope(overrides: [appDatabaseProvider.overrideWithValue(...)])`
/// 注入内存库，不要在这里加分支。
final appDatabaseProvider = Provider<AppDatabase>((ref) {
  final db = AppDatabase();
  ref.onDispose(db.close);
  return db;
});

// ═══════════════════════════════════════════════════════════════
// 仓储
// ═══════════════════════════════════════════════════════════════

final projectRepositoryProvider = Provider<ProjectRepository>(
  (ref) => ProjectRepository(ref.watch(appDatabaseProvider)),
);

final itemRepositoryProvider = Provider<ItemRepository>(
  (ref) => ItemRepository(ref.watch(appDatabaseProvider)),
);

/// 采集仓储。**它只增不改归属** —— 写 itemId 的唯一入口仍是 AssignService。
final captureRepositoryProvider = Provider<CaptureRepository>(
  (ref) => CaptureRepository(ref.watch(appDatabaseProvider)),
);

/// 整理仓储（M3）：分组建议层的数据引擎。
/// 同样碰不到 itemId —— 只负责把照片聚成组、改组结构。
final organizeRepositoryProvider = Provider<OrganizeRepository>(
  (ref) => OrganizeRepository(ref.watch(appDatabaseProvider)),
);

final integrityChecksProvider = Provider<IntegrityChecks>(
  (ref) => IntegrityChecks(ref.watch(appDatabaseProvider)),
);

/// 照片检索仓库（2026-10-15 v0.24.0「按编码搜历史照片」）。
///
/// **只读**：它没有任何写路径，归属写入口仍然只有 AssignService。
final photoSearchRepositoryProvider = Provider<PhotoSearchRepository>(
  (ref) => PhotoSearchRepository(ref.watch(appDatabaseProvider)),
);

/// 最近搜过的编码（本地 10 条）。
final recentSearchesProvider = Provider<RecentSearches>(
  (ref) => RecentSearches(),
);

/// 一次检索的参数。
///
/// 用 record 而不是新 class：record 自带值相等，正好可以直接当
/// `.family` 的键（去抖后的每次输入变化自动重新查）。
typedef PhotoSearchArgs = ({
  String query,
  String? projectId,
  bool confirmedOnly,
});

/// 按编码检索照片。
///
/// `autoDispose` —— 人搜完就走，结果不必常驻内存；下次进来重新查一次
/// 也就几百毫秒，而常驻会让「刚拍完的照片」搜不到（数据变了）。
final photoSearchProvider = FutureProvider.autoDispose
    .family<List<PhotoSearchHit>, PhotoSearchArgs>((ref, args) async {
  final q = args.query.trim();
  // 空串与 1 个字都不查（1 位会命中半个库）—— 由纯函数的常量守着底线，
  // 这里再挡一层空串，省掉一次无意义的全表 join。
  if (q.isEmpty) return const <PhotoSearchHit>[];
  return ref.watch(photoSearchRepositoryProvider).search(
        query: q,
        projectId: args.projectId,
        confirmedOnly: args.confirmedOnly,
      );
});

/// 「照片存入手机相册」服务（P4 · 老板诉求）。
///
/// 无状态（除开关偏好外），单例即可；采集服务与概览页共用同一实例，
/// 让 `ensurePermission` 的探测结果只走一次通道。
final galleryServiceProvider = Provider<GalleryService>(
  (ref) => GalleryService(),
);

/// 媒体库元数据回查（相册导入找回真实拍摄时刻，2026-09-29）。
///
/// 纯无状态（通道薄封装），单例即可。
final galleryMetaServiceProvider = Provider<GalleryMetaService>(
  (ref) => const GalleryMetaService(),
);

/// 「相册选择器」原生服务（2026-09-29「优化从相册选择照片」）。
///
/// 纯无状态（通道薄封装），单例即可。选择器页用它分页读 MediaStore、
/// 取缩略图、把选中原图复制进临时目录。
final nativeGalleryServiceProvider = Provider<NativeGalleryService>(
  (ref) => const NativeGalleryService(),
);

/// 相机偏好（09-26 老板诉求：画幅 / 闪光 / 网格线）。
///
/// 无状态外壳（缓存在实例内），单例即可 —— 采集页读网格开关，
/// CameraCaptureService 读/写画幅与闪光，同一实例保证读写一致。
final cameraPreferencesProvider = Provider<CameraPreferences>(
  (ref) => CameraPreferences(),
);

/// 系统相机拍照通道（2026-10-14 v0.22.0）。单例。
///
/// v0.24.11：构造时注册 native→Dart 的 handler（渐进式收图的晚到照片
/// 推送），所以不能再是 `const` 常量构造 —— provider 里普通构造即可。
final systemCameraServiceProvider = Provider<SystemCameraService>(
  (ref) => SystemCameraService(),
);

/// App 版本号（「关于」面板用，2026-10-14 v0.23.0）。
///
/// 读 pubspec（见 [AppInfo.version]），读不到回落「版本未知」——
/// 展示信息缺失不该让面板报错。autoDispose：面板关掉就不用留着。
final appVersionProvider = FutureProvider.autoDispose<String>(
  (ref) => AppInfo.version(),
);

/// 最近一次系统相机连拍会话的收图诊断（v0.24.6，「关于」面板展示）。
///
/// 「拍 3 张只存 1 张」返工过两版（0.24.4 判据错、0.24.5 猜窗口），
/// 每次都缺「到底收了几张、每轮几张、等了多久」这些数字，只能靠现象
/// 反推。原生侧现在把这些数字回传存进偏好，这里读出来给用户看 ——
/// 现场复测后截图这一行就够定位。
final sessionDiagProvider = FutureProvider.autoDispose<String>(
  (ref) => ref.watch(cameraPreferencesProvider).sessionDiag(),
);

/// 相机采集服务。
///
/// ⚠️ 用 `autoDispose` 是**刻意的**：离开采集页就必须释放相机，
/// 否则从后台回来时相机仍被别人占着（§8.2）。
final captureServiceProvider = Provider.autoDispose<CaptureService>((ref) {
  final s = CameraCaptureService(
    ref.watch(captureRepositoryProvider),
    gallery: ref.watch(galleryServiceProvider),
    prefs: ref.watch(cameraPreferencesProvider),
  );
  ref.onDispose(s.dispose);
  return s;
});

// ═══════════════════════════════════════════════════════════════
// 领域服务
// ═══════════════════════════════════════════════════════════════

// 注：ChecklistFileReader / ChecklistImporter / ColumnMapper
// 都是纯静态工具类（私有构造 + 全静态方法），不需要 Provider ——
// 它们没有状态、没有依赖，直接静态调用即可。

/// 设备昵称 —— 免登录下的最小身份标识，写入 `assignments.confirmed_by`。
///
/// 老板拍板的前提是免登录（需求 8），所以这里**不做账号体系**。
/// 但归属决策记录里必须留下某种可区分来源的标识，
/// 否则多人共用一台设备时无法复盘。见设计方案 §6.2。
final deviceNameProvider = FutureProvider<String>((ref) async {
  try {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString('device_name');
    if (saved != null && saved.trim().isNotEmpty) return saved;
    final name = Platform.localHostname;
    await prefs.setString('device_name', name);
    return name;
  } catch (_) {
    return 'unknown-device';
  }
});

final assignServiceProvider = Provider<AssignService>((ref) {
  final name = ref.watch(deviceNameProvider).valueOrNull ?? 'unknown-device';
  return AssignService(ref.watch(appDatabaseProvider), deviceName: name);
});

/// 照片删除服务（M7 · 老板诉求：删项目里的图片）。
///
/// 删单张 / 删整组：事务内级联清理从属数据，磁盘文件尽力而为删。
/// 与 [AssignService] 同构 —— 直接持库、可碰 data/fs、**不写 itemId**。
final photoDeletionServiceProvider = Provider<PhotoDeletionService>(
  (ref) => PhotoDeletionService(ref.watch(appDatabaseProvider)),
);

/// OCR 建议管道（M4 / §5.3.2）。
///
/// 与 [AssignService] 对偶：管道只写建议字段
/// （suggested_item_id / ocr_tokens / ocr_state），**永远不写归属**。
/// 归属仍然只能走 assignServiceProvider 进 AssignService。
///
/// ═══════════════════════════════════════════════════════════════
/// P4 诉求 4：提取器不再是写死的 ML Kit，而是按用户偏好装配。
///
/// ⚠️ 这里**必须先返回一个可用的管道**，再异步换引擎 ——
///    `OcrEngineFactory.build` 要探测原生侧（一次 channel 往返），
///    如果 `await` 它再返回管道，Providers 的构建就会变成异步的，
///    而 `suggestPipelineProvider` 被 UI 同步 watch。
///
///    所以策略是：
///      ① 同步构造一个「先用 ML Kit」的管道（立刻可用，绝不空转）；
///      ② 异步读偏好 + 探测 → 需要换就用 [SuggestPipeline.swapExtractor]。
///
///    换引擎只动一个字段引用，没有竞态：管道每次取图都是
///    `await _extractor.extract(...)`，读到的是换之前还是之后的实例
///    都无所谓 —— 两者契约完全相同（成功给 token，失败抛异常）。
/// ═══════════════════════════════════════════════════════════════
final suggestPipelineProvider = Provider<SuggestPipeline>((ref) {
  final pipeline = SuggestPipeline(
    db: ref.watch(appDatabaseProvider),
    extractor: MlKitTextExtractor(),
  );

  // 异步装配用户选的引擎（失败则保持 ML Kit）。
  // publishEffective 把探测结果写进 effectiveOcrEngineProvider：
  // provider 销毁后装配才完成是正常时序，所以这里必须自己兜异常。
  unawaited(_applyPreferredEngine(pipeline, (e) {
    try {
      ref.read(effectiveOcrEngineProvider.notifier).state = e;
    } catch (_) {/* provider 已销毁，无处可写 */}
  }));

  return pipeline;
});

/// 实际生效的 OCR 引擎（P4 诉求 4）。
///
/// UI 用它显示状态 —— 显示的必须是**真正在用的**那个，
/// 而不是用户选的那个：用户选了增强识别但原生侧不可用时，
/// 显示"增强识别"就是在撒谎。
final effectiveOcrEngineProvider = StateProvider<OcrEngine>(
  (ref) => OcrEngine.mlkit,
);

/// 广播实际生效引擎的小回调。
///
/// 用回调而不是让装配函数直接拿 `ref`：provider 销毁后再碰 ref 会抛，
/// 回调在 provider 体内构造，可以把 `ref.read` 包在自己的 try/catch 里。
void _publishEffectiveEngine(
  OcrEngine e,
  void Function(OcrEngine) write,
) =>
    write(e);

Future<void> _applyPreferredEngine(
  SuggestPipeline pipeline,
  void Function(OcrEngine) publishEffective,
) async {
  try {
    final preferred = await pipeline.preferredEngine;
    if (preferred == OcrEngine.mlkit) {
      // 默认引擎本来就装配好了 —— 但**探测结果还是要广播**：
      // 设置面板的"增强识别不可用"提示依赖它（旧版在这里直接 return，
      // 导致面板里 effective 永远是初始值）。
      _publishEffectiveEngine(OcrEngine.mlkit, publishEffective);
      return;
    }
    final built = await OcrEngineFactory.build(preferred: preferred);
    pipeline.swapExtractor(built.extractor);
    _publishEffectiveEngine(built.effective, publishEffective);
  } catch (_) {
    // 装配失败保持默认 —— 建议功能降级但流程可用（§5.3.3）。
  }
}

// ═══════════════════════════════════════════════════════════════
// 视图数据流
// ═══════════════════════════════════════════════════════════════

final projectListProvider = StreamProvider<List<ProjectSummary>>(
  (ref) => ref.watch(projectRepositoryProvider).watchAll(),
);

/// 回收站：已软删的项目流（列表页底部"已删除"区消费）。
///
/// 软删只打标记、DB 与磁盘都留着，所以这里项目可一键恢复，
/// 或二次确认后 [ProjectRepository.purge] 彻底清盘。
final deletedProjectsProvider = StreamProvider<List<ProjectSummary>>(
  (ref) => ref.watch(projectRepositoryProvider).watchDeleted(),
);

final projectSummaryProvider = StreamProvider.family<ProjectSummary?, String>(
  (ref, projectId) => ref.watch(projectRepositoryProvider).watchOne(projectId),
);

/// 清单缺口（§5.4 S5）—— 唯一能可靠回答"漏拍了哪件"的数据源。
final gapItemsProvider = StreamProvider.family<List<ItemWithShot>, String>(
  (ref, projectId) => ref.watch(itemRepositoryProvider).watchGaps(projectId),
);

final allItemsProvider = StreamProvider.family<List<ItemWithShot>, String>(
  (ref, projectId) => ref.watch(itemRepositoryProvider).watchByProject(projectId),
);

/// 整理页待办流（M3 / §5.4）：未归属的组 + 组内缩略图。
///
/// 确认归属的组自动从流里消失（「只看剩下的」）。
///
/// ═══════════════════════════════════════════════════════════════
/// P4 · 诉求 3 修复：新拍的照片必须**立刻**出现在整理页。
///
/// 原实现是「进页先调一次 regroupPending，再 watchOpenGroups」，两个问题：
///   1. `regroupPending` 只在 `OrganizePage.initState` 里 `Future.microtask`
///      跑一次。而 `OrganizePage` 挂在 `IndexedStack` 里 —— 进工作台那一刻
///      就 initState 完了，之后用户去采集页拍几百张再回来，
///      State 并没有重建 → 那一轮分组**永远不会再跑**。
///   2. `watchOpenGroups` 查的是 `photo_groups` 表。刚拍的照片
///      `group_id` 是 NULL，**根本不在那张表里** —— 所以这不是"刷新慢"，
///      是"查不到"。
///
/// 现在改成**数据驱动**：
///   · 先 `await regroupPending`（补上历史积压），
///   · 再 `yield* watchOpenGroups`（正常流），
///   · 同时把「未入组照片数」这条信号流并进来 —— 只要它 > 0，
///     说明又有新照片没入组，立刻补一轮。
///
/// 因为 `regroupPending` 加了重入锁，这里多次触发是安全的。
/// ═══════════════════════════════════════════════════════════════
final openGroupsProvider = StreamProvider.family<List<OpenGroup>, String>(
  (ref, projectId) {
    final repo = ref.watch(organizeRepositoryProvider);

    late final StreamController<List<OpenGroup>> out;
    StreamSubscription<List<OpenGroup>>? groupSub;
    StreamSubscription<int>? pendingSub;
    out = StreamController<List<OpenGroup>>(
      onListen: () async {
        // ① 补上进入本页之前的积压（幂等 + 重入安全）
        await _regroupQuietly(repo, projectId);
        if (out.isClosed) return;

        // ② 正常待办流：一直订阅，值直接转发给 out
        groupSub = repo.watchOpenGroups(projectId).listen(
              out.add,
              onError: out.addError,
            );

        // ③ 新照片信号：未入组数 > 0 就补一轮分组。
        //    补组会写 photo_groups，订阅中的 watchOpenGroups 会自动推新值，
        //    所以这里**不需要**再手动重订阅。
        //    用 `skip(1)` 是因为 watchPendingPhotoCount 会先推一个当前值 ——
        //    我们只关心"从 0 变成正数"这种**变化**。
        pendingSub = repo.watchPendingPhotoCount(projectId).listen((count) {
          if (count > 0) _regroupQuietly(repo, projectId);
        });
      },
      onCancel: () async {
        await pendingSub?.cancel();
        await groupSub?.cancel();
        pendingSub = null;
        groupSub = null;
      },
    );

    ref.onDispose(() {
      pendingSub?.cancel();
      groupSub?.cancel();
      out.close();
    });

    return out.stream;
  },
);

/// 跑一轮重组，**吞掉异常**。
///
/// 分组是"建议层"的预处理：失败不该打断浏览 —— 照片还在（数据无损），
/// 用户切一次 Tab 或下拉刷新就会再试。这与原 `initState` 里的
/// `try/catch(_) {}` 语义一致。
Future<void> _regroupQuietly(OrganizeRepository repo, String projectId) async {
  try {
    await repo.regroupPending(projectId);
  } catch (_) {
    // 建议层失败不影响浏览
  }
}

/// 已有归属的货品 id 集合（§5.4「一货一组」的 UI 前置拦截）。
///
/// 指派面板用它把已占用的货品置灰 —— 把重复指派挡在入口，
/// 而不是等 AssignService 抛错再提示。
final assignedItemIdsProvider = StreamProvider.family<Set<String>, String>(
  (ref, projectId) =>
      ref.watch(organizeRepositoryProvider).watchAssignedItemIds(projectId),
);

/// 已指派组流（P4 · 真机反馈修复）：整理页「已指派」页签的数据源。
///
/// 与 [openGroupsProvider] 并行的第二条流 —— 待办流回答"还剩什么没干"，
/// 本流回答"已经干了什么、干得对不对"。撤销/改派走 AssignService，
/// 组表一变两条流各自自动刷新。
final assignedGroupsProvider = StreamProvider.family<List<AssignedGroup>, String>(
  (ref, projectId) =>
      ref.watch(organizeRepositoryProvider).watchAssignedGroups(projectId),
);

/// 监装照片墙（老板 2026-09-27 拍板：照片分预检 / 监装两大部分）。
///
/// 监装照片与货品清单无关，所以这里给的是**照片**而不是组 ——
/// 它们不需要对应编码、不需要分组，只是躺在一个文件夹里等着打包。
final supervisionPhotosProvider =
    StreamProvider.family<List<GroupPhotoThumb>, String>(
  (ref, projectId) => ref
      .watch(organizeRepositoryProvider)
      .watchSupervisionPhotos(projectId),
);

/// 本项目已经用过的箱号（给「指定箱号」面板做快捷选择）。
///
/// 不是流而是 Future：箱号只在打开面板的那一刻需要，
/// 没必要为它挂一条常驻监听（箱号变化频率极低）。
final cartonsProvider = FutureProvider.family<List<String>, String>(
  (ref, projectId) =>
      ref.watch(organizeRepositoryProvider).listCartons(projectId),
);

/// 照片的 OCR 状态计数（P4 · 真机反馈：失败必须可见可恢复）。
///
/// [projectId] 传项目 id = 本项目口径；传 **null = 全库口径**
/// （跨所有未软删的项目，与 photoSearchRepository 的可见范围同一口径）。
/// v0.24.2 起两处消费：
///   · 整理页 OCR 状态行 ——「这些照片识别过了没有」的正面回答；
///   · 搜索页空态 —— 区分「没识别」与「没命中」。
/// 只读 drift 流，照片状态一变自动推新。
final ocrPhotoStatsProvider = StreamProvider.autoDispose
    .family<OcrPhotoStats, String?>((ref, projectId) {
  final db = ref.watch(appDatabaseProvider);
  final Stream<List<QueryRow>> rows;
  if (projectId == null) {
    // 全局口径：join projects 排除软删项目（deleted_at 非空）。
    rows = db.customSelect(
      'SELECT p.ocr_state AS ocr_state, COUNT(*) AS c '
      'FROM photos p JOIN projects pr ON pr.id = p.project_id '
      'WHERE pr.deleted_at IS NULL GROUP BY p.ocr_state',
      readsFrom: {db.photos, db.projects},
    ).watch();
  } else {
    rows = db.customSelect(
      'SELECT ocr_state, COUNT(*) AS c FROM photos '
      'WHERE project_id = ? GROUP BY ocr_state',
      variables: [Variable.withString(projectId)],
      readsFrom: {db.photos},
    ).watch();
  }

  return rows.map((rs) {
    var pending = 0, done = 0, failed = 0;
    for (final r in rs) {
      switch (r.read<String>('ocr_state')) {
        case 'pending':
        case 'running':
          pending += r.read<int>('c');
        case 'done':
        case 'skipped':
          done += r.read<int>('c');
        case 'failed':
          failed += r.read<int>('c');
      }
    }
    return OcrPhotoStats(pending: pending, done: done, failed: failed);
  });
});

/// [ocrPhotoStatsProvider] 的投影。
class OcrPhotoStats {
  const OcrPhotoStats({
    required this.pending,
    required this.done,
    required this.failed,
  });

  /// 排队中 / 识别中。
  final int pending;

  /// 已完成（含被跳过的 —— 跳过是一种明确的"不识别"决定）。
  final int done;

  /// 识别失败。
  final int failed;

  int get total => pending + done + failed;
  bool get hasFailed => failed > 0;
}

/// 「一键确认高置信」预览（M4 / §5.4 S3）。
///
/// `autoDispose` 是刻意的：弹窗打开时现算、关闭即弃 ——
/// 预览必须是**当下**的状态，缓存一个过时的清单反而误导确认。
/// 批量确认完成后 UI 会 invalidate 一次（组确认后 itemId 落库，
/// 下一次预览自然变短）。
final bulkConfirmPreviewProvider =
    FutureProvider.autoDispose.family<List<BulkConfirmCandidate>, String>(
  (ref, projectId) =>
      ref.watch(assignServiceProvider).previewBulkConfirmDetailed(projectId),
);

/// OCR 建议开关状态（§5.3.3：整理页头部图标 + 设置面板）。
///
/// 切换后 UI 负责 invalidate（开关方法改的是 SharedPreferences +
/// suggest_state，drift 流会自动刷新，但这个 FutureProvider 不会）。
final ocrDisabledProvider = FutureProvider<bool>((ref) async =>
    ref.watch(suggestPipelineProvider).isDisabledByUser);

/// 交付就绪度（§6.3 的强制校验 + §5.5 的前置检查）。
final deliveryReadinessProvider =
    FutureProvider.family<DeliveryReadiness, String>(
  (ref, projectId) => ref.watch(integrityChecksProvider).readiness(projectId),
);

// ─────────────────────────────────────────────────────────────
// 交付打包（M5）
// ─────────────────────────────────────────────────────────────

final exportServiceProvider = Provider<ExportService>(
  (ref) => ExportServiceImpl(ref.watch(appDatabaseProvider)),
);

/// 交付记录读取（2026-10-20 v0.24.8，交付页「历史交付包」用）。
final deliveryRepositoryProvider = Provider<DeliveryRepository>(
  (ref) => DeliveryRepository(ref.watch(appDatabaseProvider)),
);

/// 本项目最近的交付包（新的在前）。
///
/// 打包完成后要 invalidate 它 —— 否则刚打的包不会出现在历史里
/// （交付页只在 initState/手动刷新时读）。
final deliveryHistoryProvider = FutureProvider.autoDispose
    .family<List<DeliveryHistoryItem>, String>(
  (ref, projectId) =>
      ref.watch(deliveryRepositoryProvider).recentByProject(projectId),
);

/// 交付计划（文件名、缺口统计都在它里面算好）。
///
/// `autoDispose` + family：交付页打开时算一次，离开即弃。
/// 计划会遍历全部照片算文件名，不该被长期缓存（整理的每一次改动
/// 都会让它过期）。
final deliveryPlanProvider =
    FutureProvider.autoDispose.family<DeliveryPlan, String>(
  (ref, projectId) =>
      DeliveryPlanBuilder(ref.watch(appDatabaseProvider)).build(projectId),
);

// ═══════════════════════════════════════════════════════════════
// 采集相关（M2）
// ═══════════════════════════════════════════════════════════════

/// 采集前的存储空间预检（§8.2）。
///
/// 放在 FutureProvider 里而不是 Service 里，是因为它**只在进入采集页时算一次**，
/// 不是每张照片都算 —— 那会拖慢快门。
final storageAuditProvider =
    FutureProvider.family<StorageAudit, String>((ref, projectId) async {
  final summary = await ref.watch(projectSummaryProvider(projectId).future);
  final expected = (summary?.photoTotal ?? 0);
  final root = await ProjectPaths.filesRoot();
  return StorageService.audit(
    projectRootPath: root.path,
    expectedPhotos: expected,
  );
});

/// 采集页胶片条 / 概览页"最近拍摄"的数据源（最近 5 张）。
///
/// 返回 [PhotoThumb] 而不是 drift 的 `Photo` ——
/// 这样 UI 层不必 import `lib/data/`（架构规则 2），
/// 也无从看到 itemId（§5.2 采集期零判断，靠类型约束）。
final latestThumbsProvider = StreamProvider.family<List<PhotoThumb>, String>(
  (ref, projectId) =>
      ref.watch(captureRepositoryProvider).watchLatestThumbs(projectId, limit: 5),
);

/// 项目内照片总数（采集页顶部参考值）。
final projectPhotoCountProvider = StreamProvider.family<int, String>(
  (ref, projectId) =>
      ref.watch(captureRepositoryProvider).watchPhotoCount(projectId),
);


// ═══════════════════════════════════════════════════════════════
// 重复照片提示（2026-10-04 老板「同一组内、不同组间的照片不能重复」）
// ═══════════════════════════════════════════════════════════════

/// 项目内的重复照片报告：重复集 + 指纹补算进度。
///
/// **不是 StreamProvider** —— 指纹补算是分批推进的"一次性收敛"过程，
/// 中间态（已算 300 / 未算 900）对用户没有意义，UI 只需要最终结论
/// 与一个粗粒度的百分比。所以用 AsyncProvider，刷新靠显式 invalidate。
///
/// [DuplicateReport.isScanning] 为 true 时 UI 显示「正在核查 N 张」，
/// **不许显示「无重复」** —— 没算完就说没重复是骗人。
final duplicateReportProvider =
    FutureProvider.family<DuplicateReport, String>((ref, projectId) async {
  // ① 先把缺失的指纹补算完（分批，见 CaptureService.backfillHashes）。
  //    补算不出来（文件丢了）的会一直留在 pending 里 —— 那时
  //    isScanning 恒为 true，UI 会一直显示"正在核查"。
  //    这是刻意的：宁可一直核查，也不谎报无重复。
  try {
    await ref.read(captureServiceProvider).backfillHashes(projectId);
  } catch (e) {
    Log.w('Dup', 'backfill failed :: $e');
  }

  final repo = ref.watch(captureRepositoryProvider);
  final sets = await repo.findDuplicates(projectId);
  final cov = await repo.hashCoverage(projectId);
  return DuplicateReport(
    sets: sets,
    hashedCount: cov.hashed,
    pendingCount: cov.pending,
  );
});
