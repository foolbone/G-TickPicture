/// 项目汇总「待办角标」的口径回归（2026-10-15 老板反馈
/// 「项目里的多处照片统计数不一样」）。
///
/// 事故还原：预检流程里照片**入了组也还是 state='unassigned'**（归属
/// 确认才写 state），而底栏角标曾用 `groupPending + photoUnassigned` ——
/// 组内照片同时被「组待办」和「照片待办」数两遍，6 组 · 19 张的项目
/// 角标显示 25，看起来像统计对不上。
///
/// 修复后的口径：
///   角标 = groupPending（待确认组）+ photoOrphan（没进任何组的预检照片）
///   —— 同一张照片只可能出现在其中一边；监装照片无组语义，不计。
///   photoUnassigned（确认进度口径）继续服务 organizeDone / 交付就绪。
///
/// 真内存库实跑 [ProjectRepository.watchOne] 的聚合 SQL，钉死三件事：
/// 已入组不重复计、散照片计 orphan、监装照片两边都不计。
library;

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/organize_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/model/project_summary.dart';

void main() {
  late AppDatabase db;
  late ProjectRepository projects;
  late CaptureRepository capture;
  late OrganizeRepository organize;
  late String projectId;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    projects = ProjectRepository(db);
    capture = CaptureRepository(db);
    organize = OrganizeRepository(db);
    projectId = await projects.create(name: '角标口径');
  });

  tearDown(() async {
    await db.close();
  });

  // ── 夹具 ────────────────────────────────────────────────

  /// 拍 [n] 张入当前项目（不重跑分组）。[category] 改部类（默认预检）。
  Future<List<String>> shoot(int n, {PhotoCategory? category}) async {
    final s = await capture.startSession(projectId);
    final ids = await capture.insertPhotos(
      projectId,
      [
        for (var i = 0; i < n; i++)
          NewPhoto(
            sessionId: s,
            filePath: '/tmp/o${s}_$i.jpg',
            seq: i + 1,
            takenAt: DateTime(2026, 10, 15, 9, i),
            bytes: 1024,
          ),
      ],
    );
    await capture.endSession(s);
    if (category != null) {
      await (db.update(db.photos)..where((p) => p.id.isIn(ids)))
          .write(PhotosCompanion(category: Value(category.code)));
    }
    return ids;
  }

  Future<ProjectSummary> summary() async {
    final s = await projects.watchOne(projectId).first;
    return s!;
  }

  // ── 口径钉子 ────────────────────────────────────────────

  test('全入组：角标 = 组数，组内照片不再被数一遍（25 事故的钉子）', () async {
    // 3 张 → 一批一组；照片 state 停在 unassigned（归属确认才变）。
    await shoot(3);
    await organize.regroupPending(projectId);

    final s = await summary();
    expect(s.photoTotal, 3);
    expect(s.groupPending, 1);
    // 修复前：badge = 1 + 3 = 4（组内 3 张被数两遍）。
    expect(s.photoUnassigned, 3, reason: '确认进度口径不变');
    expect(s.photoOrphan, 0, reason: '已入组的照片不该出现在散照片里');
    expect(s.groupPending + s.photoOrphan, 1, reason: '角标 = 1 组待确认');
  });

  test('散照片与组待办各算各的，监装照片两边都不计', () async {
    await shoot(2);
    await organize.regroupPending(projectId); // 2 张进组
    await shoot(1); // 第 3 张散着（不跑分组）
    await shoot(1, category: PhotoCategory.supervision); // 监装，无组语义

    final s = await summary();
    expect(s.photoTotal, 4);
    expect(s.groupPending, 1);
    expect(s.photoOrphan, 1, reason: '只有那张散着的预检照片算 orphan');
    expect(s.photoOrphan + s.groupPending, 2, reason: '角标 = 1 组 + 1 散张');
    // 监装照片两边都不计：不是 orphan（无组语义），也不进 groupPending。
  });

  test('归属确认后角标清零', () async {
    await shoot(2);
    await organize.regroupPending(projectId);
    final groupRow = await (db.select(db.photoGroups)
          ..where((g) => g.projectId.equals(projectId)))
        .getSingle();
    final inGroup = await (db.select(db.photos)
          ..where((p) => p.groupId.equals(groupRow.id)))
        .get();
    expect(inGroup, isNotEmpty, reason: '组里应有照片');

    // 与 confirmGroup 同效的最小写法（本测试只关心汇总口径）：
    await (db.update(db.photos)
          ..where((p) => p.groupId.equals(groupRow.id)))
        .write(const PhotosCompanion(state: Value('confirmed')));
    await (db.update(db.photoGroups)..where((g) => g.id.equals(groupRow.id)))
        .write(const PhotoGroupsCompanion(itemId: Value('item-x')));

    final s = await summary();
    expect(s.groupPending, 0);
    expect(s.photoOrphan, 0);
    expect(s.groupPending + s.photoOrphan, 0, reason: '确认后无待办');
  });
}
