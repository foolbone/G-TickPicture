import 'package:drift/drift.dart';
import 'package:path/path.dart' as p;

import '../../core/naming.dart';
import '../../data/db/database.dart';
import '../model/delivery_plan.dart';
import '../model/enums.dart';

/// 交付计划构建器 —— 从数据库算出 [DeliveryPlan]。
///
/// 单独抽出来的理由：这是**纯查询 + 纯计算**，没有任何文件 IO。
/// 因此它可以被单测直接拿来跑（喂一个内存库，断言命名与缺口），
/// 不需要真的建 ZIP、不需要碰磁盘。
///
/// ⚠️ 它**不写任何归属** —— 归属的唯一写入口是 `AssignService`。
///    这里只读。部类（预检/监装）与箱号是「人怎么整理」的结果，
///    由 OrganizeRepository 直接写，与归属正交，不经过 AssignService。
///
/// ── 包内布局（老板 2026-09-27 拍板）──────────────────────────
/// ```
/// 集刻交付_<项目名>_<日期>/
/// ├── 预检/                       ← 与货品清单有关的那一半
/// │   ├── 箱A/
/// │   │   ├── 007_103010013345AMX_01.jpg   ← 对应上了：交付命名
/// │   │   └── P_20260927_101234.jpg        ← 没对应上：原始文件名
/// │   └── _未分箱/                ← 没指定箱号的（也可能整体平铺）
/// ├── 监装/                       ← 与清单无关，一个文件夹，原始文件名
/// ├── _未使用/                    ← 勾选「含未使用」才有
/// └── manifest.json               ← 机器可读的交付清单
/// ```
class DeliveryPlanBuilder {
  DeliveryPlanBuilder(this._db);

  final AppDatabase _db;

  /// 构建计划。
  ///
  /// [groupByCarton] 为 true（默认）时，整理时**指定过箱号**的照片进
  /// `预检/{箱号}/`；一张都没指定箱号时自动保持平铺（否则会为"没指定"
  /// 造出一个装着全部照片的 `_未分箱/`，结构反而更乱）。
  ///
  /// 未对应上编码的预检照片**照样进包**，跟着自己的箱号走、用原始文件名
  /// —— 老板 09-27 拍板：「能对应则对应，不能对应不影响后面交付」
  /// 「没有对应的就用原始文件名」。只有被显式标记「本张不用」的照片
  /// 才进 `_未使用/`。
  ///
  /// 计划先行、选项进构建器的原因：manifest 是计划的直接投影 ——
  /// 命名在计划里定了，它就不可能再与包内目录不一致。
  Future<DeliveryPlan> build(
    String projectId, {
    bool groupByCarton = true,
  }) async {
    final projRow = await (_db.select(_db.projects)
          ..where((t) => t.id.equals(projectId)))
        .getSingleOrNull();
    if (projRow == null) {
      throw StateError('项目不存在：$projectId');
    }

    // ── 1. 货品（含清单外）按 seq 升序 ──
    final itemRows = await (_db.select(_db.items)
          ..where((t) =>
              t.projectId.equals(projectId) & t.deletedAt.isNull())
          ..orderBy([(t) => OrderingTerm.asc(t.seq)]))
        .get();

    // ── 2. 组 → 用户指定箱号 ──
    //
    // 分箱只认**整理时人手输入**的 carton（老板 09-27 拍板：
    // 「分组时，由用户输入或指定箱号，不依赖货品清单」）。
    // 清单里的 containerSummary 仍随货品走，但只是清单信息。
    final groupRows = await (_db.select(_db.photoGroups)
          ..where((t) => t.projectId.equals(projectId)))
        .get();
    final cartonOf = <String, String?>{
      for (final g in groupRows)
        g.id: ((g.carton ?? '').trim().isEmpty) ? null : g.carton!.trim(),
    };

    String? cartonOfPhoto(Photo ph) =>
        (ph.groupId == null) ? null : cartonOf[ph.groupId];

    // ── 3. 全部照片，按拍摄时间升序 ──
    final allPhotos = await (_db.select(_db.photos)
          ..where((t) => t.projectId.equals(projectId))
          ..orderBy([
            (t) => OrderingTerm.asc(t.takenAt),
            (t) => OrderingTerm.asc(t.seq),
          ]))
        .get();

    // ⚠️ 「确认了」还得「确认到一件货品表里还存在的货」才算正片。
    // 归属指向已删除/不存在的货品时，按**没对上**处理 —— 走原始文件名进包。
    // 直接丢掉是最坏的选择：交付少了一张照片，而没有任何人知道。
    final itemIdSet = <String>{for (final it in itemRows) it.id};
    bool isConfirmed(Photo ph) =>
        ph.itemId != null &&
        ph.state == PhotoState.confirmed.code &&
        itemIdSet.contains(ph.itemId);
    bool isSupervision(Photo ph) =>
        ph.category == PhotoCategory.supervision.code;

    // 四堆**互斥且穷尽** —— 每张照片恰好落进一堆，不重不漏。
    // 顺序即优先级：先剔「不用」，再剔「监装」，剩预检按确认与否分。
    final supervision = <Photo>[];
    final unmatched = <Photo>[];
    final unused = <Photo>[];
    final confirmed = <Photo>[];

    for (final ph in allPhotos) {
      if (ph.state == PhotoState.unused.code) {
        unused.add(ph);
      } else if (isSupervision(ph)) {
        supervision.add(ph);
      } else if (isConfirmed(ph)) {
        confirmed.add(ph);
      } else {
        unmatched.add(ph);
      }
    }

    // ── 4. 是否启用箱号目录 ──
    final useCartonDirs = groupByCarton &&
        [...confirmed, ...unmatched]
            .any((ph) => (cartonOfPhoto(ph) ?? '').isNotEmpty);

    /// 预检部分的目录前缀：`预检/` 或 `预检/{箱号}/`
    String precheckDir(String? carton) {
      if (!useCartonDirs) return deliveryPrecheckDir;
      final dir = userCartonDir(carton) ?? '_未分箱';
      return '$deliveryPrecheckDir/$dir';
    }

    // 包内不允许重名 —— 原始文件名可能撞车（微信导入/相册导入同名很常见）。
    // 撞了就在主干后加 `_2` `_3`，而不是静默覆盖导致少一张照片。
    final usedPaths = <String>{};
    String alloc(String desired) {
      if (usedPaths.add(desired)) return desired;
      final stem = p.withoutExtension(desired);
      final ext = p.extension(desired);
      for (var i = 2; i < 9999; i++) {
        final cand = '${stem}_$i$ext';
        if (usedPaths.add(cand)) return cand;
      }
      return desired;
    }

    // ── 5. 逐货品命名（已对应的预检照片）──
    final byItem = <String, List<Photo>>{};
    for (final ph in confirmed) {
      byItem.putIfAbsent(ph.itemId!, () => <Photo>[]).add(ph);
    }

    final items = <DeliveryItem>[];
    for (final it in itemRows) {
      final raw = byItem[it.id] ?? const <Photo>[];
      if (raw.isEmpty) {
        items.add(
          DeliveryItem(
            itemId: it.id,
            seq: it.seq,
            code: it.code,
            codeSafe: it.codeSafe,
            name: it.name,
            spec: it.spec,
            containerSummary: it.containerSummary,
            state: it.state,
            requiredPhotos: it.requiredPhotos,
            photos: const <DeliveryPhoto>[],
          ),
        );
        continue;
      }
      // 一件货的照片通常同箱；万一分散在多组，取第一个有箱号的组。
      String? itemCarton;
      for (final ph in raw) {
        final c = cartonOfPhoto(ph);
        if (c != null && c.isNotEmpty) {
          itemCarton = c;
          break;
        }
      }
      final dir = precheckDir(itemCarton);
      final photos = <DeliveryPhoto>[];
      for (var i = 0; i < raw.length; i++) {
        final ph = raw[i];
        final index = i + 1; // 该品第几张，1 起
        final base = flatDeliveryName(
          itemSeq: it.seq,
          codeSafe: it.codeSafe,
          index: index,
        );
        photos.add(
          DeliveryPhoto(
            photoId: ph.id,
            sourcePath: ph.filePath,
            takenAt: ph.takenAt,
            photoSeq: ph.seq,
            itemSeq: it.seq,
            codeSafe: it.codeSafe,
            indexInItem: index,
            fileName: alloc('$dir/$base'),
            itemCode: it.code,
            itemName: it.name,
            category: PhotoCategory.fromCode(ph.category),
            carton: itemCarton,
            originalName: p.basename(ph.filePath),
          ),
        );
      }
      items.add(
        DeliveryItem(
          itemId: it.id,
          seq: it.seq,
          code: it.code,
          codeSafe: it.codeSafe,
          name: it.name,
          spec: it.spec,
          containerSummary: it.containerSummary,
          state: it.state,
          requiredPhotos: it.requiredPhotos,
          photos: photos,
          carton: itemCarton,
        ),
      );
    }

    // ── 6. 预检里没对应上编码的照片 —— 照样进包，用原始文件名 ──
    final unmatchedPhotos = <DeliveryPhoto>[];
    for (final ph in unmatched) {
      final carton = cartonOfPhoto(ph);
      unmatchedPhotos.add(
        DeliveryPhoto(
          photoId: ph.id,
          sourcePath: ph.filePath,
          takenAt: ph.takenAt,
          photoSeq: ph.seq,
          itemSeq: 0,
          codeSafe: '',
          indexInItem: 0,
          fileName: alloc('${precheckDir(carton)}/${p.basename(ph.filePath)}'),
          itemCode: '',
          itemName: null,
          category: PhotoCategory.precheck,
          carton: carton,
          originalName: p.basename(ph.filePath),
        ),
      );
    }

    // ── 7. 监装照片 —— 一个文件夹，原始文件名 ──
    final supervisionPhotos = <DeliveryPhoto>[];
    for (final ph in supervision) {
      supervisionPhotos.add(
        DeliveryPhoto(
          photoId: ph.id,
          sourcePath: ph.filePath,
          takenAt: ph.takenAt,
          photoSeq: ph.seq,
          itemSeq: 0,
          codeSafe: '',
          indexInItem: 0,
          fileName: alloc('$deliverySupervisionDir/${p.basename(ph.filePath)}'),
          itemCode: '',
          itemName: null,
          category: PhotoCategory.supervision,
          // 监装与箱号无关（老板：与清单无关，放一个文件夹即可）
          carton: null,
          originalName: p.basename(ph.filePath),
        ),
      );
    }

    // ── 8. 标记「本张不用」的照片 —— 固定 `_未使用/` ──
    final unusedPhotos = <DeliveryPhoto>[];
    for (final ph in unused) {
      unusedPhotos.add(
        DeliveryPhoto(
          photoId: ph.id,
          sourcePath: ph.filePath,
          takenAt: ph.takenAt,
          photoSeq: ph.seq,
          itemSeq: 0,
          codeSafe: '_未使用',
          indexInItem: unusedPhotos.length + 1,
          fileName: alloc('_未使用/${'${ph.seq}'.padLeft(4, '0')}.jpg'),
          itemCode: '',
          itemName: null,
          category: PhotoCategory.fromCode(ph.category),
          carton: cartonOfPhoto(ph),
          originalName: p.basename(ph.filePath),
        ),
      );
    }

    // ── 9. 归属完整性（§6.3 不变式）：有归属但无确认记录 ──
    final orphanCount = await _countOrphans(projectId);

    return DeliveryPlan(
      projectId: projectId,
      projectName: projRow.name,
      client: projRow.client,
      generatedAt: DateTime.now().millisecondsSinceEpoch,
      items: items,
      unusedPhotos: unusedPhotos,
      supervisionPhotos: supervisionPhotos,
      unmatchedPhotos: unmatchedPhotos,
      orphanCount: orphanCount,
    );
  }

  /// 统计归属完整性违规。期望恒为 0。>0 意味着包里有「无据可查的归属」。
  ///
  /// 检测四类损坏（每一类都意味着 `photos.itemId` 不再是可信证据）：
  ///   ① 照片有 itemId，但 state 不是 confirmed（缺确认标记）
  ///   ② 照片有 itemId，却没有未吊销的 assignment 记录（无决策凭据）
  ///   ③ **照片的 itemId 与 assignment 记录的 itemId 不一致**
  ///      —— 这是最隐蔽的一类：有凭据、状态也对，但凭据说的归属
  ///      和实际归属不是同一件货。绕过 AssignService 直接改库会这样。
  ///   ④ 组同理（③ 也适用于组）
  Future<int> _countOrphans(String projectId) async {
    final row = await _db.customSelect(
      r'''
      SELECT
        (SELECT COUNT(*) FROM photos p
          WHERE p.project_id = ?
            AND p.item_id IS NOT NULL
            AND p.state <> 'confirmed') AS photo_unconfirmed,
        (SELECT COUNT(*) FROM photos p
          WHERE p.project_id = ?
            AND p.item_id IS NOT NULL
            AND NOT EXISTS (
              SELECT 1 FROM assignments a
              WHERE a.project_id = p.project_id
                AND a.target_type = 'photo'
                AND a.target_id   = p.id
                AND a.revoked_at IS NULL
            )) AS photo_orphan,
        (SELECT COUNT(*) FROM photos p
          WHERE p.project_id = ?
            AND p.item_id IS NOT NULL
            AND NOT EXISTS (
              SELECT 1 FROM assignments a
              WHERE a.project_id = p.project_id
                AND a.target_type = 'photo'
                AND a.target_id   = p.id
                AND a.revoked_at IS NULL
                AND a.item_id     = p.item_id
            )) AS photo_mismatch,
        (SELECT COUNT(*) FROM photo_groups g
          WHERE g.project_id = ?
            AND g.item_id IS NOT NULL
            AND g.confirmed_at IS NULL) AS group_unconfirmed,
        (SELECT COUNT(*) FROM photo_groups g
          WHERE g.project_id = ?
            AND g.item_id IS NOT NULL
            AND NOT EXISTS (
              SELECT 1 FROM assignments a
              WHERE a.project_id = g.project_id
                AND a.target_type = 'group'
                AND a.target_id   = g.id
                AND a.revoked_at IS NULL
            )) AS group_orphan,
        (SELECT COUNT(*) FROM photo_groups g
          WHERE g.project_id = ?
            AND g.item_id IS NOT NULL
            AND NOT EXISTS (
              SELECT 1 FROM assignments a
              WHERE a.project_id = g.project_id
                AND a.target_type = 'group'
                AND a.target_id   = g.id
                AND a.revoked_at IS NULL
                AND a.item_id     = g.item_id
            )) AS group_mismatch
      ''',
      variables: [
        Variable.withString(projectId),
        Variable.withString(projectId),
        Variable.withString(projectId),
        Variable.withString(projectId),
        Variable.withString(projectId),
        Variable.withString(projectId),
      ],
      readsFrom: {_db.photos, _db.photoGroups, _db.assignments},
    ).getSingle();

    // 取 max 而非求和：同一张照片可能同时命中多类（例如既无凭据又状态错），
    // 相加会把"1 张坏照片"报成"2 处异常"，数字会骗人。
    // 这里按"受影响的照片/组数"计数，才是可解释的口径。
    return [
      row.read<int>('photo_unconfirmed'),
      row.read<int>('photo_orphan'),
      row.read<int>('photo_mismatch'),
      row.read<int>('group_unconfirmed'),
      row.read<int>('group_orphan'),
      row.read<int>('group_mismatch'),
    ].fold<int>(0, (a, b) => a > b ? a : b);
  }
}
