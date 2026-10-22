import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import '../../domain/model/checklist_row.dart';
import '../../domain/model/item_with_shot.dart';
import '../db/database.dart';

/// 货品仓储。
///
/// 这里最有价值的一条查询是 [watchGaps] —— 设计方案 §5.4 S5 的「清单缺口视图」。
/// 它回答的是 **"我是不是漏拍了哪件货"**，而且不依赖 OCR 是否成功。
/// v2.0 因为把归属绑在 OCR 上，压根没法回答这个问题。
class ItemRepository {
  ItemRepository(this._db);

  final AppDatabase _db;
  static const _uuid = Uuid();

  /// 批量导入。同项目内**已存在**的编码静默跳过 —— 因为那意味着
  /// 这个编码此前已导入过（连同它已有的照片归属），不能覆盖。
  ///
  /// ⚠️ 注意区分两件事（P4 诉求 1 之后）：
  ///   · **同一份清单内部**的编码重复（同一件货分散在多箱、被列成多行）
  ///     → 在 [ChecklistImporter] 阶段就**合并**掉了，不会走到这里；
  ///   · **与库里已有数据**的编码重复 → 才是这里的静默跳过。
  ///
  /// 返回实际写入的行数。
  Future<int> bulkInsert(
    String projectId,
    List<ChecklistRow> rows, {
    int startSeq = 0,
  }) async {
    if (rows.isEmpty) return 0;

    // 先取出已存在的编码，避免把已有行（连同照片归属）覆盖掉
    final existing = await existingCodes(projectId);
    final fresh = <ChecklistRow>[];
    for (final r in rows) {
      if (existing.contains(r.code)) continue;
      fresh.add(r);
    }
    if (fresh.isEmpty) return 0;

    var seq = startSeq;
    final companions = fresh
        .map(
          (r) => ItemsCompanion.insert(
            id: _uuid.v4(),
            projectId: projectId,
            seq: seq++,
            code: r.code,
            codeSafe: r.codeSafe,
            name: Value(r.name),
            spec: Value(r.spec),
            qty: Value(r.qty),
            unit: Value(r.unit),
            requiredPhotos: Value(r.requiredPhotos ?? 2),
            // P4 诉求 1：箱号汇总额（语义甲 —— 多行合并成一件货）
            containerSummary: Value(r.container),
            // 这件货在清单里占了几行（单行 = 1）
            sourceLineCount: Value(r.sourceLineCount),
            remark: Value(r.remark),
          ),
        )
        .toList();

    await _db.batch((b) {
      b.insertAll(_db.items, companions, mode: InsertMode.insertOrIgnore);
    });
    return companions.length;
  }

  Future<Set<String>> existingCodes(String projectId) async {
    final q = _db.selectOnly(_db.items)
      ..addColumns([_db.items.code])
      ..where(_db.items.projectId.equals(projectId) &
          _db.items.deletedAt.isNull());
    final rows = await q.get();
    return rows.map((r) => r.read(_db.items.code)!).toSet();
  }

  Future<int> nextSeq(String projectId) async {
    final row = await _db.customSelect(
      'SELECT COALESCE(MAX(seq), -1) AS m FROM items WHERE project_id = ?',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.items},
    ).getSingle();
    return row.read<int>('m') + 1;
  }

  /// 货品列表（含每件货已确认的照片数）。
  Stream<List<ItemWithShot>> watchByProject(String projectId) {
    return _db
        .customSelect(
          r'''
          SELECT i.*,
            (SELECT COUNT(*) FROM photos p
              WHERE p.item_id = i.id AND p.state = 'confirmed') AS shot_count
          FROM items i
          WHERE i.project_id = ? AND i.deleted_at IS NULL
          ORDER BY i.seq
          ''',
          variables: [Variable.withString(projectId)],
          readsFrom: {_db.items, _db.photos},
        )
        .watch()
        .map((rows) => rows.map(_mapItem).toList());
  }

  /// ★ 清单缺口：清单里有、但还没有任何已确认照片的货品（§7.5）。
  ///
  /// 这是全案唯一能可靠回答"漏拍了哪件"的地方。
  Stream<List<ItemWithShot>> watchGaps(String projectId) {
    return _db
        .customSelect(
          r'''
          SELECT i.*, 0 AS shot_count
          FROM items i
          WHERE i.project_id = ?
            AND i.deleted_at IS NULL
            AND i.state = 'normal'
            AND NOT EXISTS (
              SELECT 1 FROM photos p
              WHERE p.project_id = i.project_id
                AND p.item_id    = i.id
                AND p.state      = 'confirmed'
            )
          ORDER BY i.seq
          ''',
          variables: [Variable.withString(projectId)],
          readsFrom: {_db.items, _db.photos},
        )
        .watch()
        .map((rows) => rows.map(_mapItem).toList());
  }

  /// 张数未达标的货品（要求 2 张、实际只有 1 张）—— 次级提醒，不阻塞交付。
  Stream<List<ItemWithShot>> watchUnderShot(String projectId) {
    return _db
        .customSelect(
          r'''
          SELECT i.*, COUNT(p.id) AS shot_count
          FROM items i
          LEFT JOIN photos p ON p.item_id = i.id AND p.state = 'confirmed'
          WHERE i.project_id = ? AND i.deleted_at IS NULL
          GROUP BY i.id
          HAVING shot_count < i.required_photos
          ORDER BY i.seq
          ''',
          variables: [Variable.withString(projectId)],
          readsFrom: {_db.items, _db.photos},
        )
        .watch()
        .map((rows) => rows.map(_mapItem).toList());
  }

  /// 整理页指派面板的候选检索：前缀优先，其次包含。
  ///
  /// M1 用 SQL LIKE 实现（几千条清单足够快）；
  /// M4 若清单到万级，再换成常驻内存的 Trie（设计方案 §8.1 要求 ≤80ms）。
  Future<List<ItemWithShot>> search(
    String projectId,
    String keyword, {
    int limit = 30,
  }) async {
    final k = keyword.trim().toUpperCase();
    if (k.isEmpty) {
      // `.first` 返回的是 Future<List<...>>，必须先 await 再 .take()，
      // 否则 take 会作用在 Future 上（undefined_method）。
      return (await watchByProject(projectId).first).take(limit).toList();
    }
    final rows = await _db.customSelect(
      r'''
      SELECT i.*,
        (SELECT COUNT(*) FROM photos p
          WHERE p.item_id = i.id AND p.state = 'confirmed') AS shot_count
      FROM items i
      WHERE i.project_id = ? AND i.deleted_at IS NULL
        AND (UPPER(i.code) LIKE ? OR UPPER(COALESCE(i.name,'')) LIKE ?)
      ORDER BY
        CASE WHEN UPPER(i.code) LIKE ? THEN 0 ELSE 1 END,
        i.seq
      LIMIT ?
      ''',
      variables: [
        Variable.withString(projectId),
        Variable.withString('%$k%'),
        Variable.withString('%$k%'),
        Variable.withString('$k%'),
        Variable.withInt(limit),
      ],
      readsFrom: {_db.items, _db.photos},
    ).get();
    return rows.map(_mapItem).toList();
  }

  /// 标记为「缺口」（清单里有、却没有照片）。§5.4 S5。
  /// 注意措辞：不叫「现场未见」——那是替业务下判断（§原则 13）。
  Future<void> markNotFound(String itemId, String reason) async {
    await (_db.update(_db.items)..where((t) => t.id.equals(itemId))).write(
      ItemsCompanion(
        state: const Value('not_found'),
        notFoundReason: Value(reason),
      ),
    );
  }

  Future<void> clearNotFound(String itemId) async {
    await (_db.update(_db.items)..where((t) => t.id.equals(itemId))).write(
      const ItemsCompanion(
        state: Value('normal'),
        notFoundReason: Value(null),
      ),
    );
  }

  /// 创建"清单外"货品（§5.4 S4）。返回新货品 id，供立即指派使用。
  Future<String> createExtra({
    required String projectId,
    required String code,
    required String codeSafe,
    String? name,
  }) async {
    final id = _uuid.v4();
    final seq = await nextSeq(projectId);
    await _db.into(_db.items).insert(
          ItemsCompanion.insert(
            id: id,
            projectId: projectId,
            seq: seq,
            code: code,
            codeSafe: codeSafe,
            name: Value(name),
            state: const Value('extra'),
          ),
        );
    return id;
  }

  Future<void> softDelete(String itemId) async {
    await (_db.update(_db.items)..where((t) => t.id.equals(itemId))).write(
      ItemsCompanion(deletedAt: Value(DateTime.now().millisecondsSinceEpoch)),
    );
  }

  ItemWithShot _mapItem(QueryRow r) => ItemWithShot(
        id: r.read<String>('id'),
        seq: r.read<int>('seq'),
        code: r.read<String>('code'),
        codeSafe: r.read<String>('code_safe'),
        name: r.readNullable<String>('name'),
        spec: r.readNullable<String>('spec'),
        qty: r.readNullable<double>('qty'),
        unit: r.readNullable<String>('unit'),
        requiredPhotos: r.read<int>('required_photos'),
        state: r.read<String>('state'),
        notFoundReason: r.readNullable<String>('not_found_reason'),
        shotCount: r.readNullable<int>('shot_count') ?? 0,
        // P4 诉求 1：箱号汇总额（多箱同货时形如「箱A、箱B」）
        containerSummary: r.readNullable<String>('container_summary'),
        // 这件货由清单里的几行合并而来（单行 = 1）
        sourceLineCount: r.readNullable<int>('source_line_count') ?? 1,
      );
}

// ItemWithShot 已迁往 `domain/model/item_with_shot.dart` —— UI 需要
// 具名引用它，而 UI 不得 import data/（架构规则 2 的历史教训同
// DeliveryReadiness / PhotoThumb）。data 层照常 import domain，合法。
