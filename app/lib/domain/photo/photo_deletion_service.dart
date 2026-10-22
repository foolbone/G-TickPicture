import 'dart:io';

import 'package:drift/drift.dart';

import '../../core/logger.dart';
import '../../data/db/database.dart';
import '../../data/fs/project_paths.dart';
import '../model/enums.dart';

/// 删除照片 / 整组的核心服务（M7 · 老板诉求：删项目里的图片）。
///
/// 落在 domain 层，与 [AssignService] 同构：直接持有 [AppDatabase] 做事务、
/// 可 import `data/fs`（删磁盘文件）、**全程不写 itemId**（架构规则 3）。
///
/// ═══════════════════════════════════════════════════════════════
/// 设计原则（破坏性操作的两条铁律）：
///
///   1. **DB 删除走事务，原子完成** —— 要么整组连带一起删，要么不删。
///      这保证不会出现"照片行没了、但 assignments / ocr_tokens 还挂着"
///      这种半成品状态（否则 `IntegrityChecks` 会报孤儿数 > 0）。
///
///   2. **文件删除是"尽力而为"** —— 原图 / 缩略图 / OCR json 可能已被清过、
///      或导入后用户手动挪走，删不掉**绝不**阻断 DB 删除。
///      一次磁盘异常不该让照片永远卡在库里删不掉。
/// ═══════════════════════════════════════════════════════════════
///
/// 牵连处理（删照片时不留脏数据）：
///   · OCR token、一照多货附加关联、照片级归属记录 —— 一并删。
///   · 若被删的是组的封面，改派给组内剩余最早一张。
///   · 若删后组内空了，连组级归属记录一起删，整组移除（不留空壳）。
///   · 全程**不碰 itemId** —— 已指派组的剩余照片仍归原货，这是人做的决定，
///     删除服务无权改（也不会"因删一张就把整组归属抹掉"）。
class PhotoDeletionService {
  PhotoDeletionService(this._db);

  final AppDatabase _db;

  // ═══════════════════════════════════════════════════════════
  // 删单张照片
  // ═══════════════════════════════════════════════════════════

  /// 删除一张照片（含它在组内造成的封面/计数/空组连带）。
  ///
  /// [photoId] 不存在时静默返回（幂等，可重复调用）。
  Future<void> deletePhoto(String photoId) async {
    final List<String> paths = [];
    String? projectId;

    await _db.transaction(() async {
      final photo = await (_db.select(_db.photos)
            ..where((t) => t.id.equals(photoId)))
          .getSingleOrNull();
      if (photo == null) return; // 已删或从未存在 —— 幂等

      projectId = photo.projectId;
      final groupId = photo.groupId;

      // 收集文件（删除行前拿路径，删除后就查不到了）
      if (photo.filePath.isNotEmpty) paths.add(photo.filePath);
      if (photo.thumbPath != null) paths.add(photo.thumbPath!);

      // ① 连带清理：OCR token、一照多货附加关联、照片级归属记录
      //    —— 都是"这张照片消失后必须跟着消失"的从属数据，且都不碰 itemId
      await (_db.delete(_db.ocrTokens)
            ..where((t) => t.photoId.equals(photoId)))
          .go();
      await (_db.delete(_db.itemPhotoExtras)
            ..where((t) => t.photoId.equals(photoId)))
          .go();
      await (_db.delete(_db.assignments)
            ..where((t) =>
                t.targetType.equals(AssignTargetType.photo.code) &
                t.targetId.equals(photoId)))
          .go();

      // ② 维护所属组：封面改派 / 计数递减 / 删空则连组级归属一起删
      if (groupId != null) {
        final group = await (_db.select(_db.photoGroups)
              ..where((t) => t.id.equals(groupId)))
            .getSingleOrNull();
        if (group != null) {
          final remaining = await ((_db.select(_db.photos))
                ..where(
                    (t) => t.groupId.equals(groupId) & t.id.equals(photoId).not()))
              .get();
          remaining.sort((a, b) => a.takenAt.compareTo(b.takenAt));

          if (remaining.isEmpty) {
            // 整组空了：连组级归属记录一起删，移除空壳（不留孤儿）
            await (_db.delete(_db.assignments)
                  ..where((t) =>
                      t.targetType.equals(AssignTargetType.group.code) &
                      t.targetId.equals(groupId)))
                .go();
            await (_db.delete(_db.photoGroups)
                  ..where((t) => t.id.equals(groupId)))
                .go();
          } else {
            final needCover = group.coverPhotoId == photoId;
            await (_db.update(_db.photoGroups)
                  ..where((t) => t.id.equals(groupId)))
                .write(PhotoGroupsCompanion(
              photoCount: Value(remaining.length),
              // 被删的是封面 → 改派给剩余最早一张；否则别动 coverPhotoId
              coverPhotoId: needCover
                  ? Value(remaining.first.id)
                  : const Value.absent(),
            ));
          }
        }
      }

      // ②.5 批次张数同步递减（2026-10-10 v0.19.0）：photos.session_id
      //      非空外键，删除行前拿。photo_count 是 capture_sessions 的
      //      冗余计数，不递减的话「本次 128 张」在删一张后就虚高 1。
      //      拍后回看·重拍（刚入库就删）是主要调用场景；整理期删除
      //      已归属批次里的照片同样适用，口径一致。
      await _db.customStatement(
        'UPDATE capture_sessions SET photo_count = '
        'CASE WHEN photo_count > 0 THEN photo_count - 1 ELSE 0 END '
        'WHERE id = ?',
        [photo.sessionId],
      );

      // ③ 删照片行本身
      await (_db.delete(_db.photos)
            ..where((t) => t.id.equals(photoId)))
          .go();
    });

    // ④ 文件尽力而为删除（在事务外，失败不回滚已完成的 DB 删除）
    if (projectId != null) {
      await _deletePhotoFiles(projectId!, photoId, paths);
    }
    Log.i('PhotoDeletionService', '已删除照片 $photoId');
  }

  // ═══════════════════════════════════════════════════════════
  // 删整组
  // ═══════════════════════════════════════════════════════════

  /// 删除一个组（含组内全部照片、它们的从属数据、组级归属记录、磁盘文件）。
  ///
  /// [groupId] 不存在时静默返回。
  Future<void> deleteGroup(String groupId) async {
    final List<({String id, String? filePath, String? thumbPath})> photoMeta = [];
    String? projectId;

    await _db.transaction(() async {
      final group = await (_db.select(_db.photoGroups)
            ..where((t) => t.id.equals(groupId)))
          .getSingleOrNull();
      if (group == null) return;

      projectId = group.projectId;
      final photos = await (_db.select(_db.photos)
            ..where((t) => t.groupId.equals(groupId)))
          .get();
      final ids = photos.map((p) => p.id).toList();

      for (final p in photos) {
        photoMeta.add((id: p.id, filePath: p.filePath, thumbPath: p.thumbPath));
      }

      // ① 组内照片的所有从属数据 + 照片行
      if (ids.isNotEmpty) {
        await (_db.delete(_db.ocrTokens)
              ..where((t) => t.photoId.isIn(ids)))
            .go();
        await (_db.delete(_db.itemPhotoExtras)
              ..where((t) => t.photoId.isIn(ids)))
            .go();
        await (_db.delete(_db.assignments)
              ..where((t) =>
                  t.targetType.equals(AssignTargetType.photo.code) &
                  t.targetId.isIn(ids)))
            .go();
        await (_db.delete(_db.photos)..where((t) => t.id.isIn(ids))).go();
      }

      // ② 组级归属记录 + 组行
      await (_db.delete(_db.assignments)
            ..where((t) =>
                t.targetType.equals(AssignTargetType.group.code) &
                t.targetId.equals(groupId)))
          .go();
      await (_db.delete(_db.photoGroups)
            ..where((t) => t.id.equals(groupId)))
          .go();
    });

    // ③ 文件尽力而为删除
    if (projectId != null) {
      for (final m in photoMeta) {
        final ps = <String>[
          if (m.filePath != null && m.filePath!.isNotEmpty) m.filePath!,
          if (m.thumbPath != null) m.thumbPath!,
        ];
        await _deletePhotoFiles(projectId!, m.id, ps);
      }
    }
    Log.i('PhotoDeletionService', '已删除整组 $groupId（${photoMeta.length} 张）');
  }

  // ─────────────────────────────────────────────────────────
  // 内部：尽力而为的文件删除
  // ─────────────────────────────────────────────────────────

  Future<void> _deletePhotoFiles(
    String projectId,
    String photoId,
    List<String> explicitPaths,
  ) async {
    for (final p in explicitPaths) {
      await _tryDelete(p);
    }
    // OCR 缓存 json（路径由 projectId + photoId 推导，不在照片行里）
    try {
      final f = await ProjectPaths.ocrCacheFile(projectId, photoId);
      if (await f.exists()) await f.delete();
    } catch (_) {
      // 尽力而为：读不到/删不掉都不影响主流程
    }
  }

  Future<void> _tryDelete(String? path) async {
    if (path == null || path.isEmpty) return;
    try {
      final f = File(path);
      if (await f.exists()) await f.delete();
    } catch (_) {
      // 尽力而为：文件可能已被清过或正被占用，删不掉不应阻断
    }
  }
}
