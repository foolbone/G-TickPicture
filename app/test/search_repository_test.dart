import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/data/repo/capture_repository.dart';
import 'package:g_tick_picture/data/repo/organize_repository.dart';
import 'package:g_tick_picture/data/repo/project_repository.dart';
import 'package:g_tick_picture/data/repo/search_repository.dart';
import 'package:g_tick_picture/domain/assign/assign_service.dart';
import 'package:g_tick_picture/domain/model/enums.dart';
import 'package:g_tick_picture/domain/model/photo_search_hit.dart';
import 'package:g_tick_picture/domain/search/code_norm.dart';

/// 按编码检索照片的契约测试（2026-10-15 v0.24.0）。
///
/// 钉的是**现场真实用法**，不是 SQL：
///  1. 输**后几位**要命中（唛头被挡住，只记得尾部流水号）；
///  2. 输**中间几位**要命中；
///  3. 全角 / 连字符 / 大小写差异不影响命中；
///  4. 来源要分得清：已确认归属 > 组建议 > OCR（后两者必须标出来）；
///  5. 检索**只读** —— 不写 itemId、不改组结构。
///
/// 用真实内存库（NativeDatabase.memory）：匹配逻辑跨 SQL 与 Dart 两侧，
/// mock 掉任何一侧都测不出真实行为（项目纪律：不写真实库之外的假象）。
void main() {
  late AppDatabase db;
  late ProjectRepository projects;
  late CaptureRepository capture;
  late OrganizeRepository organize;
  late AssignService assign;
  late PhotoSearchRepository search;
  late String projectId;

  setUp(() async {
    db = AppDatabase.forTesting(NativeDatabase.memory());
    projects = ProjectRepository(db);
    capture = CaptureRepository(db);
    organize = OrganizeRepository(db);
    assign = AssignService(db, deviceName: 'test-device');
    search = PhotoSearchRepository(db);
    projectId = await projects.create(name: '检索测试');
  });

  tearDown(() async {
    await db.close();
  });

  // ── 夹具 ────────────────────────────────────────────────

  DateTime t(int sec) => DateTime(2026, 10, 14, 9, 0, sec);

  Future<String> insertItem(String code) async {
    final id = 'item-$code';
    await db.into(db.items).insert(
          ItemsCompanion.insert(
            id: id,
            projectId: projectId,
            seq: 1,
            code: code,
            codeSafe: code.replaceAll('-', ''),
          ),
        );
    return id;
  }

  /// 拍 [n] 张 → 聚成一组。返回（photoIds, groupId）。
  Future<(List<String>, String?)> shoot(int n) async {
    final s = await capture.startSession(projectId);
    final photos = [
      for (var i = 0; i < n; i++)
        NewPhoto(
          sessionId: s,
          filePath: '/tmp/s$i.jpg',
          seq: i + 1,
          takenAt: t(i * 5),
          bytes: 1024,
        ),
    ];
    final ids = await capture.insertPhotos(projectId, photos);
    await capture.endSession(s);
    await organize.regroupPending(projectId);
    // 取**本批**那张照片所在的组（库里可能已经有别的组，不能 .single）
    final row = await (db.select(db.photos)
          ..where((p) => p.id.equals(ids.first)))
        .getSingle();
    return (ids, row.groupId);
  }

  Future<void> insertOcrToken(String photoId, String text) async {
    await db.into(db.ocrTokens).insert(
          OcrTokensCompanion.insert(
            id: 'ocr-$photoId-$text',
            photoId: photoId,
            rawText: text,
            confidence: 0.9,
            boxJson: '[]',
          ),
        );
  }

  Future<void> setSuggested(String groupId, String itemId) async {
    await (db.update(db.photoGroups)..where((g) => g.id.equals(groupId)))
        .write(PhotoGroupsCompanion(suggestedItemId: Value(itemId)));
  }

  // ── 命中场景 ────────────────────────────────────────────

  group('后几位 / 中间几位（现场第一、第二场景）', () {
    test('输后几位命中「已确认归属」的编码', () async {
      final item = await insertItem('ABC-123');
      final (ids, gid) = await shoot(2);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      final hits = await search.search(query: '123');
      expect(hits, hasLength(2));
      expect(hits.first.source, PhotoSearchSource.assigned);
      expect(hits.first.kind, CodeMatchKind.suffix);
      // 显示给人的是**原文**，不是规范化后的串
      expect(hits.first.matchedCode, 'ABC-123');
      expect(hits.map((h) => h.photoId).toSet(), ids.toSet());
    });

    test('输中间几位命中（包含）', () async {
      final item = await insertItem('ABC-123');
      final (_, gid) = await shoot(1);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      final hits = await search.search(query: 'BC12');
      expect(hits, hasLength(1));
      expect(hits.single.kind, CodeMatchKind.contains);
    });

    test('输前几位命中（前缀）', () async {
      final item = await insertItem('ABC-123');
      final (_, gid) = await shoot(1);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      final hits = await search.search(query: 'ABC');
      expect(hits, hasLength(1));
      expect(hits.single.kind, CodeMatchKind.prefix);
    });

    test('写法差异不影响命中：全角 / 连字符 / 大小写', () async {
      final item = await insertItem('ABC-123');
      final (_, gid) = await shoot(1);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      for (final q in ['abc-123', 'ＡＢＣ１２３', 'abc 123', 'ABC123']) {
        expect(await search.search(query: q), hasLength(1), reason: '输入 $q');
      }
    });

    test('不足 2 位不查（1 位会命中半个库）', () async {
      final item = await insertItem('ABC-123');
      final (_, gid) = await shoot(1);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      expect(await search.search(query: '1'), isEmpty);
      expect(await search.search(query: ''), isEmpty);
    });
  });

  group('来源分级', () {
    test('组建议（未确认）命中 → 标 suggested', () async {
      final item = await insertItem('XYZ-778');
      final (_, gid) = await shoot(1);
      await setSuggested(gid!, item);

      final hits = await search.search(query: '778');
      expect(hits, hasLength(1));
      expect(hits.single.source, PhotoSearchSource.suggested);
      expect(hits.single.source.badge, '建议');
    });

    test('OCR token 命中 → 标 ocr', () async {
      final (ids, _) = await shoot(1);
      await insertOcrToken(ids.first, 'KK-9021');

      final hits = await search.search(query: '9021');
      expect(hits, hasLength(1));
      expect(hits.single.source, PhotoSearchSource.ocr);
      expect(hits.single.source.badge, 'OCR');
    });

    test('「只看已确认」把建议与 OCR 都挡掉', () async {
      final item = await insertItem('XYZ-778');
      final (ids, gid) = await shoot(2);
      await setSuggested(gid!, item);
      await insertOcrToken(ids.last, 'KK-9021');

      // 不加过滤：建议 + OCR 都命中
      expect(await search.search(query: '778'), isNotEmpty);
      // 只看已确认：这两张都没确认过 → 空
      expect(
        await search.search(query: '778', confirmedOnly: true),
        isEmpty,
      );
      expect(
        await search.search(query: '9021', confirmedOnly: true),
        isEmpty,
      );
    });

    test('排序：已确认的排在 OCR 前面（同一个编码）', () async {
      final item = await insertItem('MM-500');
      final (idsA, gidA) = await shoot(1);
      await assign.confirmGroup(
        gidA!,
        itemId: item,
        source: AssignSource.manual,
      );
      // 另一张只有 OCR 命中同一个码
      final (idsB, _) = await shoot(1);
      await insertOcrToken(idsB.first, 'MM-500');

      final hits = await search.search(query: 'MM500');
      expect(hits, hasLength(2));
      expect(hits.first.photoId, idsA.first);
      expect(hits.first.source, PhotoSearchSource.assigned);
      expect(hits.last.source, PhotoSearchSource.ocr);
    });
  });

  group('范围：跨项目 / 限定项目', () {
    test('不限项目 → 两个项目的照片都出来；限定 → 只有本项目的', () async {
      final item = await insertItem('QQ-321');
      final (_, gid) = await shoot(1);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      // 第二个项目，同编码
      final p2 = await projects.create(name: '另一个项目');
      await db.into(db.items).insert(
            ItemsCompanion.insert(
              id: 'item2',
              projectId: p2,
              seq: 1,
              code: 'QQ-321',
              codeSafe: 'QQ321',
            ),
          );
      final s2 = await capture.startSession(p2);
      final ids2 = await capture.insertPhotos(p2, [
        NewPhoto(
          sessionId: s2,
          filePath: '/tmp/other.jpg',
          seq: 1,
          takenAt: t(60),
          bytes: 1024,
        ),
      ]);
      await capture.endSession(s2);
      await organize.regroupPending(p2);
      final g2 = await (db.select(db.photoGroups)
            ..where((g) => g.projectId.equals(p2)))
          .get();
      await assign.confirmGroup(
        g2.single.id,
        itemId: 'item2',
        source: AssignSource.manual,
      );

      final all = await search.search(query: '321');
      expect(all, hasLength(2));
      expect(all.map((h) => h.projectId).toSet(), {projectId, p2});

      final scoped = await search.search(query: '321', projectId: p2);
      expect(scoped, hasLength(1));
      expect(scoped.single.photoId, ids2.single);
      expect(scoped.single.projectName, '另一个项目');
    });
  });

  group('只读性（检索不得改数据）', () {
    test('搜完以后归属、组结构、照片行都没被改写', () async {
      final item = await insertItem('ABC-123');
      final (_, gid) = await shoot(2);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      final before = await (db.select(db.photos)).get();
      final groupsBefore = await (db.select(db.photoGroups)).get();

      await search.search(query: '123');
      await search.search(query: 'zzz');

      expect(await (db.select(db.photos)).get(), before);
      expect(await (db.select(db.photoGroups)).get(), groupsBefore);
    });
  });

  group('索引缓存与失效（v0.24.1）', () {
    test('搜过以后再拍新照片，新照片立刻能搜到（缓存不挡"刚拍的"）', () async {
      final item = await insertItem('ABC-123');
      final (ids1, gid1) = await shoot(1);
      await assign.confirmGroup(gid1!, itemId: item, source: AssignSource.manual);

      // 第一次搜索：建立索引缓存
      expect(await search.search(query: '123'), hasLength(1));

      // 再拍一批、再确认归属（写事务 → 索引版本 +1 → 缓存失效）
      final (ids2, gid2) = await shoot(1);
      await assign.confirmGroup(gid2!, itemId: item, source: AssignSource.manual);

      final hits = await search.search(query: '123');
      expect(hits, hasLength(2));
      expect(hits.map((h) => h.photoId).toSet(), {...ids1, ...ids2});
    });

    test('OCR 是后写入的，也要能立刻搜到', () async {
      final (ids, _) = await shoot(1);
      expect(await search.search(query: '777'), isEmpty);

      await insertOcrToken(ids.first, 'ZZ-777');

      expect(await search.search(query: '777'), hasLength(1));
    });

    test('改派（UPDATE photos.item_id）后新归属能搜到', () async {
      final itemA = await insertItem('AAA-100');
      final itemB = await insertItem('BBB-200');
      final (ids, gid) = await shoot(1);
      await assign.confirmGroup(gid!, itemId: itemA, source: AssignSource.manual);
      expect(await search.search(query: '100'), hasLength(1));
      expect(await search.search(query: '200'), isEmpty);

      // 改派到 B：UPDATE 触发器必须让索引失效
      await assign.confirmGroup(gid, itemId: itemB, source: AssignSource.manual);

      expect(await search.search(query: '200'), hasLength(1));
      expect(await search.search(query: '100'), isEmpty);
    });

    test('项目归档后，它的照片从搜索结果里消失', () async {
      final item = await insertItem('QQ-321');
      final (_, gid) = await shoot(1);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);
      expect(await search.search(query: '321'), hasLength(1));

      await projects.softDelete(projectId);

      expect(await search.search(query: '321'), isEmpty);
    });

    test('没数据变化时索引复用（版本号不变 → 不重建）', () async {
      final item = await insertItem('ABC-123');
      final (_, gid) = await shoot(2);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      // 两次搜索之间没有任何写入 → 索引版本号必须没变
      await search.search(query: '123');
      final v1 = await readSearchIndexVersion(db);
      await search.search(query: '12');
      final v2 = await readSearchIndexVersion(db);
      expect(v2, v1, reason: '无写事务时版本号不该动');
    });
  });

  group('边界', () {
    test('超长 OCR 文本不参与匹配（那是噪音不是编码）', () async {
      final (ids, _) = await shoot(1);
      await insertOcrToken(
        ids.first,
        '这是一段很长的说明文字里面恰好含有123四个数字但是它不是编码真的不是',
      );
      expect(await search.search(query: '123'), isEmpty);
    });

    test('结果限量（limit）生效', () async {
      final item = await insertItem('ABC-123');
      final (_, gid) = await shoot(5);
      await assign.confirmGroup(gid!, itemId: item, source: AssignSource.manual);

      expect(await search.search(query: '123', limit: 2), hasLength(2));
      expect(await search.search(query: '123'), hasLength(5));
    });

    test('没命中时返回空，不抛', () async {
      await insertItem('ABC-123');
      await shoot(1);
      expect(await search.search(query: 'zzz-99'), isEmpty);
    });
  });
}
