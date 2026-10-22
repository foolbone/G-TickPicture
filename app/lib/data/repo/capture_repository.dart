import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import '../../core/constants.dart';
import '../../domain/model/duplicate_photos.dart';
import '../../domain/model/enums.dart';
import '../../domain/model/gallery_photo.dart';
import '../../domain/model/photo_thumb.dart';
import '../db/database.dart';

/// 采集期要落库的数据。
///
/// 刻意做成一个**不含任何归属字段**的结构 —— 从类型上就写不出 itemId。
/// 这是 §6.1 物理隔离在 M2 的体现：采集代码不可能"顺手"写归属。
class NewPhoto {
  const NewPhoto({
    required this.sessionId,
    required this.filePath,
    required this.seq,
    required this.takenAt,
    this.thumbPath,
    this.width,
    this.height,
    this.bytes,
  });

  final String sessionId;
  final String filePath;
  final int seq;
  final DateTime takenAt;
  final String? thumbPath;
  final int? width;
  final int? height;
  final int? bytes;
}

/// 一次收图认领的结果（2026-10-21 系统相机账本）。
///
/// [photoId] 非空 = 这张原图**已经入库**（重收/晚到重叠），调用方直接
/// 复用，不要再复制、再插行。
class SystemShotClaim {
  const SystemShotClaim({
    this.photoId,
    this.alreadyStored = false,
    this.inFlight = false,
  });

  final String? photoId;
  final bool alreadyStored;

  /// true = 另一路正在收同一张（账本 state=ingesting 且很新）。
  /// 调用方应跳过这一张，避免两路同时复制/插行。
  final bool inFlight;

  bool get reused => photoId != null;
}

/// 采集仓储。
///
/// ⚠️ 本类**只增不改归属**。它绝不触碰 `photos.item_id` ——
/// 那个字段的写入口只有 `AssignService`（见 §7.4 与架构约束 3）。
class CaptureRepository {
  CaptureRepository(this._db);

  final AppDatabase _db;
  static const _uuid = Uuid();

  // ─────────────────────────────────────────────────────────
  // 采集批次
  // ─────────────────────────────────────────────────────────

  /// 开（或续接）一个批次。
  ///
  /// 【2026-09-27 分组 BUG 修复 → 2026-09-29 扩展到相册】**同来源**
  /// 批次带续接语义：
  ///  ① 有未结束的同来源批次（APP 被杀导致）→ 续用它；
  ///  ② 否则，上一个同来源批次在 [AppConst.sessionResumeWindow]（5 分钟）
  ///     内结束 → 复活续用。两个来源各有现场节奏：
  ///     · 相机：「拍一件 → 退出对照清单 → 20 秒后再进拍下一件」；
  ///     · 相册：「导一批 → 想起漏了几张 → 过一两分钟再导一批」。
  ///     分组按批次进行（组表 sessionId 外键，一批一组）——
  ///     切批意味着两段照片**永远**不在一组。
  ///  ③ 来源隔离：album 只续 album、camera 只续 camera ——
  ///     两个来源各有现场节奏（见上），混续会把不相关的一批
  ///     并进同一组。
  Future<String> startSession(
    String projectId, {
    CaptureSource source = CaptureSource.camera,
    String? note,
  }) async {
    final existing = await findOpenSession(projectId, source: source);
    if (existing != null) return existing;

    final resumable = await findResumableSession(
      projectId,
      source: source,
      window: AppConst.sessionResumeWindow,
    );
    if (resumable != null) {
      await reopenSession(resumable.id);
      return resumable.id;
    }

    final id = _uuid.v4();
    await _db.into(_db.captureSessions).insert(
          CaptureSessionsCompanion.insert(
            id: id,
            projectId: projectId,
            source: Value(source.code),
            startedAt: DateTime.now().millisecondsSinceEpoch,
            note: Value(note),
          ),
        );
    return id;
  }

  /// 结束批次。**幂等** —— 重复调用不会把 endedAt 改来改去。
  Future<void> endSession(String sessionId) async {
    await (_db.update(_db.captureSessions)
          ..where((t) => t.id.equals(sessionId) & t.endedAt.isNull()))
        .write(
      CaptureSessionsCompanion(endedAt: Value(DateTime.now().millisecondsSinceEpoch)),
    );
  }

  /// 找一个未结束的批次（"回来自动续接同一 session"）。
  ///
  /// [source] 给定时只找该来源的 —— 两个来源的续接互不可见（来源隔离）。
  Future<String?> findOpenSession(
    String projectId, {
    CaptureSource? source,
  }) async {
    final row = await (_db.select(_db.captureSessions)
          ..where((t) =>
              t.projectId.equals(projectId) &
              (source == null
                  ? t.endedAt.isNull()
                  : t.source.equals(source.code) & t.endedAt.isNull()))
          ..orderBy([(t) => OrderingTerm.desc(t.startedAt)])
          ..limit(1))
        .getSingleOrNull();
    return row?.id;
  }

  /// 找一个「刚结束不久、可以续接」的同来源批次（分组 BUG 修复链）。
  ///
  /// 场景（两来源各有节奏，见 [startSession]）：相机是「拍一件 → 退出
  /// 对照清单 → 20 秒后再进拍下一件」（2026-09-27）；相册是「导一批 →
  /// 想起漏了几张 → 过一两分钟再导一批」（2026-09-29）。退出/导完时
  /// 批次已结束，[findOpenSession] 找不到 → 新开批次 → 两段照片分属
  /// 两个批次。而分组**按批次进行**（组表有 sessionId 外键），
  /// 跨批次的照片永远不能同组。
  ///
  /// 本方法回找：同项目、**指定来源**、在 [window] 内结束的最近一个
  /// 批次。命中后调用 [reopenSession] 复活它，两段照片就还在同一个
  /// 批次里。来源隔离由 [source] 过滤保证：album 只续 album、
  /// camera 只续 camera。
  Future<CaptureSession?> findResumableSession(
    String projectId, {
    required CaptureSource source,
    required Duration window,
  }) async {
    final earliest = DateTime.now().millisecondsSinceEpoch - window.inMilliseconds;
    final row = await (_db.select(_db.captureSessions)
          ..where((t) =>
              t.projectId.equals(projectId) &
              t.source.equals(source.code) &
              t.endedAt.isNotNull() &
              t.endedAt.isBiggerOrEqualValue(earliest))
          ..orderBy([(t) => OrderingTerm.desc(t.endedAt)])
          ..limit(1))
        .getSingleOrNull();
    return row;
  }

  /// 复活一个已结束的批次（endedAt 置 NULL），让后续照片继续落进它。
  ///
  /// 幂等：对未结束的批次调用是无害的 no-op（where 条件挡住）。
  /// photoCount 列保留原值 —— 服务层的会话计数从 [getSession] 续读。
  Future<void> reopenSession(String sessionId) async {
    await (_db.update(_db.captureSessions)
          ..where((t) => t.id.equals(sessionId) & t.endedAt.isNotNull()))
        .write(const CaptureSessionsCompanion(endedAt: Value(null)));
  }

  Future<CaptureSession?> getSession(String sessionId) =>
      (_db.select(_db.captureSessions)..where((t) => t.id.equals(sessionId)))
          .getSingleOrNull();

  /// 结束项目下当前未结束的**相机**批次，返回被结束的 id（没有则 null）。
  ///
  /// 系统相机直拍的收尾用（2026-10-21）：一批一组的前提是"批次会结束"。
  /// 旧实现只在采集页 `_onFinish` 里结束，而系统直拍主入口根本不进采集页，
  /// 于是首个 open 批次会被无限复用 —— 整个项目永远只有一组。
  ///
  /// 结束之后 5 分钟内再拍，[startSession] 会走 `findResumableSession`
  /// 把同一批次复活，所以"拍一段、停下来看清单、再拍"仍是同一组。
  ///
  /// 只结束 camera 来源：album 批次由导入路径自己结束。
  Future<String?> endOpenCameraSession(String projectId) async {
    final id = await findOpenSession(projectId, source: CaptureSource.camera);
    if (id == null) return null;
    await endSession(id);
    return id;
  }

  /// 项目下全部批次（整理页按批次推进时用）。
  Stream<List<CaptureSession>> watchSessions(String projectId) =>
      (_db.select(_db.captureSessions)
            ..where((t) => t.projectId.equals(projectId))
            ..orderBy([(t) => OrderingTerm.asc(t.startedAt)]))
          .watch();

  // ─────────────────────────────────────────────────────────
  // 照片
  // ─────────────────────────────────────────────────────────

  /// 项目内下一个全局序号。采集必须单调递增，否则文件名会撞。
  Future<int> nextSeq(String projectId) async {
    final row = await _db.customSelect(
      'SELECT COALESCE(MAX(seq), 0) AS m FROM photos WHERE project_id = ?',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photos},
    ).getSingle();
    return row.read<int>('m') + 1;
  }

  /// 批量插入照片。**一次事务、一次 flush** ——
  /// 连拍时每张都单独开事务会让 SQLite 成为瓶颈（§8.1 要求 ≥10 张/5s）。
  Future<List<String>> insertPhotos(
    String projectId,
    List<NewPhoto> photos,
  ) async {
    if (photos.isEmpty) return const [];

    final ids = <String>[];
    await _db.transaction(() async {
      for (final p in photos) {
        final id = _uuid.v4();
        ids.add(id);
        await _db.into(_db.photos).insert(
              PhotosCompanion.insert(
                id: id,
                projectId: projectId,
                sessionId: p.sessionId,
                filePath: p.filePath,
                seq: p.seq,
                takenAt: p.takenAt.millisecondsSinceEpoch,
                thumbPath: Value(p.thumbPath),
                width: Value(p.width),
                height: Value(p.height),
                bytes: Value(p.bytes),
                createdAt: DateTime.now().millisecondsSinceEpoch,
              ),
            );
      }
      // 批次张数同步累加，列表页据此显示"本次 128 张"
      await _bumpSessionCount(photos.first.sessionId, photos.length);
    });
    return ids;
  }

  Future<void> _bumpSessionCount(String sessionId, int delta) async {
    await _db.customUpdate(
      'UPDATE capture_sessions SET photo_count = photo_count + ? WHERE id = ?',
      variables: [Variable.withInt(delta), Variable.withString(sessionId)],
      updates: {_db.captureSessions},
    );
  }

  /// 回填尺寸与缩略图路径（缩略图是异步生成的，晚于入库）。
  ///
  /// ⚠️ 只更新**传了值**的列。**不碰 item_id / state** —— 本类没有那个权限。
  ///
  /// 为什么 null 表示"不更新"而不是"清空"（2026-10-21 修复）：
  /// 缩略图回填只关心 thumbPath/width/height，`bytes` 不传；
  /// 修复路径（recopyPhoto）只关心 bytes，thumbPath/width/height 不传。
  /// 旧实现统一 `Value(x)`，未传的列会被写成 NULL —— 缩略图回填把
  /// `photos.bytes` 抹掉、修复又把 `thumbPath/width/height` 抹掉，
  /// 都是静默的数据损坏。当前 3 个调用点都不需要"清空某列"；
  /// 将来真要清空，再显式加 clear 参数，不要回到 Value(null)。
  Future<void> patchMediaInfo(
    String photoId, {
    int? width,
    int? height,
    String? thumbPath,
    int? bytes,
  }) async {
    await (_db.update(_db.photos)..where((t) => t.id.equals(photoId))).write(
      PhotosCompanion(
        width: Value.absentIfNull(width),
        height: Value.absentIfNull(height),
        thumbPath: Value.absentIfNull(thumbPath),
        bytes: Value.absentIfNull(bytes),
      ),
    );
  }

  /// 认领一张系统相机原图（幂等）。
  ///
  /// 账本 `system_capture_shots` 的 `(project_id, source_path)` 唯一：
  ///  · 首次 → 插一行 state=ingesting，返回空 claim；
  ///  · 已 stored 且照片行还在 → 返回 photoId（调用方复用）；
  ///  · 之前失败/进行中 → 重置为 ingesting 再试。
  ///
  /// 为什么不用 `photos.source_key`：加列要重跑 drift codegen；账本是
  /// raw SQL 表，不动 generated 代码，且能记失败原因。
  Future<SystemShotClaim> claimSystemShot({
    required String projectId,
    required String sessionId,
    required String sourcePath,
    int? sourceSize,
    int? sourceMtime,
    int? takenAtMs,
  }) async {
    final now = DateTime.now().millisecondsSinceEpoch;
    return _db.transaction(() async {
      await _db.customInsert(
        'INSERT OR IGNORE INTO system_capture_shots '
        '(id, session_id, project_id, source_path, source_size, '
        'source_mtime, taken_at, state, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        variables: [
          Variable.withString(_uuid.v4()),
          Variable.withString(sessionId),
          Variable.withString(projectId),
          Variable.withString(sourcePath),
          Variable<int>(sourceSize),
          Variable<int>(sourceMtime),
          Variable<int>(takenAtMs),
          const Variable<String>('seen'),
          Variable.withInt(now),
        ],
      );
      final row = await _db.customSelect(
        'SELECT state, photo_id, updated_at FROM system_capture_shots '
        'WHERE project_id = ? AND source_path = ?',
        variables: [
          Variable.withString(projectId),
          Variable.withString(sourcePath),
        ],
      ).getSingle();
      final state = row.read<String>('state');
      final photoId = row.read<String?>('photo_id');
      if (state == 'stored' && photoId != null) {
        final photo = await getPhoto(photoId);
        if (photo != null) {
          return SystemShotClaim(photoId: photoId, alreadyStored: true);
        }
        // 照片行被删了 —— 账本失效，重新收。
      }
      // 另一路正在收（例如旧场晚到与新场首批同时到）：不要抢，
      // 让它把照片存下来；120s 是很宽松的在途窗口（复制 8MB 远小于它）。
      final updatedAt = row.read<int?>('updated_at') ?? 0;
      if (state == 'ingesting' && now - updatedAt < 120000) {
        return const SystemShotClaim(inFlight: true);
      }
      await _db.customUpdate(
        'UPDATE system_capture_shots SET session_id = ?, source_size = ?, '
        'source_mtime = ?, taken_at = ?, state = ?, photo_id = NULL, '
        'error = NULL, updated_at = ? '
        'WHERE project_id = ? AND source_path = ?',
        variables: [
          Variable.withString(sessionId),
          Variable<int>(sourceSize),
          Variable<int>(sourceMtime),
          Variable<int>(takenAtMs),
          const Variable<String>('ingesting'),
          Variable.withInt(now),
          Variable.withString(projectId),
          Variable.withString(sourcePath),
        ],
      );
      return const SystemShotClaim();
    });
  }

  /// 标记账本里的这张原图已入库。
  Future<void> markSystemShotStored({
    required String projectId,
    required String sourcePath,
    required String photoId,
  }) async {
    await _db.customUpdate(
      'UPDATE system_capture_shots SET state = ?, photo_id = ?, error = NULL, '
      'updated_at = ? WHERE project_id = ? AND source_path = ?',
      variables: [
        const Variable<String>('stored'),
        Variable.withString(photoId),
        Variable.withInt(DateTime.now().millisecondsSinceEpoch),
        Variable.withString(projectId),
        Variable.withString(sourcePath),
      ],
    );
  }

  /// 标记账本里的这张原图入库失败（保留原因，恢复/重试时可见）。
  Future<void> markSystemShotFailed({
    required String projectId,
    required String sourcePath,
    required String error,
  }) async {
    await _db.customUpdate(
      'UPDATE system_capture_shots SET state = ?, error = ?, updated_at = ? '
      'WHERE project_id = ? AND source_path = ?',
      variables: [
        const Variable<String>('failed'),
        Variable.withString(error),
        Variable.withInt(DateTime.now().millisecondsSinceEpoch),
        Variable.withString(projectId),
        Variable.withString(sourcePath),
      ],
    );
  }

  /// 项目内已经入库过的原图路径（恢复时过滤用）。
  Future<Set<String>> storedSystemPaths(String projectId) async {
    final rows = await _db.customSelect(
      'SELECT s.source_path AS source_path FROM system_capture_shots s '
      'JOIN photos p ON p.id = s.photo_id '
      "WHERE s.project_id = ? AND s.state = 'stored'",
      variables: [Variable.withString(projectId)],
    ).get();
    return {
      for (final r in rows) r.read<String>('source_path'),
    };
  }

  /// 账本里这张原图对应的照片 id（null = 没入库/已删除）。
  ///
  /// 用于「进程重启后 sweep 仍推 changed=true」的修复：内存登记丢了，
  /// 但账本还记着 photo_id，仍然能重拷覆盖而不是再插一行。
  Future<String?> systemShotPhotoId({
    required String projectId,
    required String sourcePath,
  }) async {
    final row = await _db.customSelect(
      'SELECT photo_id FROM system_capture_shots '
      "WHERE project_id = ? AND source_path = ? AND state = 'stored'",
      variables: [
        Variable.withString(projectId),
        Variable.withString(sourcePath),
      ],
    ).getSingleOrNull();
    return row?.read<String?>('photo_id');
  }

  /// 项目照片总数。
  Stream<int> watchPhotoCount(String projectId) => _db.customSelect(
        'SELECT COUNT(*) AS c FROM photos WHERE project_id = ?',
        variables: [Variable.withString(projectId)],
        readsFrom: {_db.photos},
      ).watchSingle().map((r) => r.read<int>('c'));

  /// 按 id 取单张（回填后核对、测试断言用）。
  ///
  /// 返回整行是刻意的：它住在 data 层，**UI 拿不到它**（架构规则 2），
  /// 所以暴露完整行不会让界面顺手去读 itemId。
  Future<Photo?> getPhoto(String photoId) =>
      (_db.select(_db.photos)..where((t) => t.id.equals(photoId)))
          .getSingleOrNull();

  /// 待整理的照片（还没有归属的）。整理页的输入。
  Stream<List<Photo>> watchPendingPhotos(String projectId) =>
      (_db.select(_db.photos)
            ..where((t) =>
                t.projectId.equals(projectId) & t.itemId.isNull() & t.state.equals('unassigned'))
            ..orderBy([(t) => OrderingTerm.asc(t.takenAt)]))
          .watch();

  /// 最近 N 张（采集页胶片条）。倒序取，调用方自行反转。
  Stream<List<Photo>> watchLatestPhotos(String projectId, {int limit = 5}) =>
      (_db.select(_db.photos)
            ..where((t) => t.projectId.equals(projectId))
            ..orderBy([(t) => OrderingTerm.desc(t.takenAt)])
            ..limit(limit))
          .watch();

  /// 最近 N 张的**缩略图视图**（M2 胶片条 / 概览页"最近拍摄"）。
  ///
  /// 与 [watchLatestPhotos] 的区别是返回类型：这里只投影出
  /// `id + thumbPath`，UI **在类型上**拿不到 itemId / ocr 字段 ——
  /// 采集与概览阶段不需要看到归属（§5.2），这是靠类型约束而不是靠纪律。
  Stream<List<PhotoThumb>> watchLatestThumbs(String projectId, {int limit = 5}) =>
      (_db.select(_db.photos)
            ..where((t) => t.projectId.equals(projectId))
            ..orderBy([(t) => OrderingTerm.desc(t.takenAt)])
            ..limit(limit))
          .watch()
          .map(
            (rows) => rows
                .map((r) => PhotoThumb(id: r.id, thumbPath: r.thumbPath))
                .toList(growable: false),
          );

  /// 一次取一小批，供落盘后的媒体信息回填补齐（采集期用，避免全表扫）。
  Future<List<Photo>> photosMissingThumb(String projectId, {int limit = 20}) =>
      (_db.select(_db.photos)
            ..where((t) => t.projectId.equals(projectId) & t.thumbPath.isNull())
            ..orderBy([(t) => OrderingTerm.asc(t.seq)])
            ..limit(limit))
          .get();

  // ─────────────────────────────────────────────────────────
  // 采集期的"只读"依赖检查
  // ─────────────────────────────────────────────────────────

  /// 项目是否已导入清单。没清单也能拍（先拍后导入是允许的），
  /// 但采集页要据此决定是否显示"还没导入清单"的轻微提示。
  Future<bool> hasChecklist(String projectId) async {
    final row = await _db.customSelect(
      'SELECT COUNT(*) AS c FROM items WHERE project_id = ? AND deleted_at IS NULL',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.items},
    ).getSingle();
    return row.read<int>('c') > 0;
  }

  /// 项目下已落盘照片占用的总字节数（存储预检用）。
  Future<int> totalPhotoBytes(String projectId) async {
    final row = await _db.customSelect(
      'SELECT COALESCE(SUM(bytes), 0) AS s FROM photos WHERE project_id = ?',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photos},
    ).getSingle();
    return row.read<int>('s');
  }

  /// 项目名（相册文件夹要用）。
  ///
  /// 取不到时返回传入的 id —— 相册目录名叫什么都比"写不进去"强。
  Future<String> projectName(String projectId) async {
    final row = await (_db.select(_db.projects)
          ..where((t) => t.id.equals(projectId)))
        .getSingleOrNull();
    return row?.name ?? projectId;
  }

  /// 项目下 **App 内拍的** 照片（路径 + 时刻 + 文件名），按拍摄顺序 ——
  /// 「把已有照片补存到相册」的输入。
  ///
  /// ⚠️ **只收相机来源**（session.source = camera）：
  /// 相册 / 微信导入的照片本来就在手机里，再抄一份进
  /// `相册/集刻-采集/<项目>` 就变成相册里的重复件 ——
  /// 老板 2026-09-29 拍板：**只有 App 里拍的才需要存相册**。
  ///
  /// ⚠️ 只投影出这几列：调用方（GalleryService）只需要这三样，
  /// 拿到整行 Photo 会让"顺手读一下 itemId"变成可能（规则 2 的变形）。
  Future<List<GalleryPhoto>> capturedPhotos(String projectId) async {
    final rows = await (_db.select(_db.photos).join([
      innerJoin(
        _db.captureSessions,
        _db.captureSessions.id.equalsExp(_db.photos.sessionId),
      ),
    ])
          ..where(_db.photos.projectId.equals(projectId) &
              _db.captureSessions.source.equals(CaptureSource.camera.code))
          ..orderBy([OrderingTerm.asc(_db.photos.seq)]))
        .get();
    return rows.map((row) {
      final ph = row.readTable(_db.photos);
      return GalleryPhoto(
        srcPath: ph.filePath,
        displayName: _nameOf(ph.filePath),
        // 表里 takenAt 是 int 毫秒（跨时区安全），GalleryPhoto 要 DateTime。
        takenAt: DateTime.fromMillisecondsSinceEpoch(ph.takenAt),
      );
    }).toList();
  }

  /// [capturedPhotos] 的张数（相册卡据此决定要不要显示「补存」入口）。
  ///
  /// 故意复用列表查询而不是另写一条 COUNT —— 两条 SQL 各有一份筛选条件，
  /// 迟早会漂移（改了列表忘了改计数，按钮数与实存数就对不上）。
  Future<int> capturedPhotoCount(String projectId) async =>
      (await capturedPhotos(projectId)).length;

  static String _nameOf(String path) {
    final i = path.lastIndexOf('/');
    final name = i < 0 ? path : path.substring(i + 1);
    return name.isEmpty ? '$path.jpg' : name;
  }

  // ─────────────────────────────────────────────────────────
  // 重复照片查重（2026-10-04）
  // ─────────────────────────────────────────────────────────

  /// 回填一张照片的内容指纹。
  Future<void> patchContentHash(String photoId, String hash) async {
    await (_db.update(_db.photos)..where((t) => t.id.equals(photoId))).write(
      PhotosCompanion(contentHash: Value(hash)),
    );
  }

  /// 一次取一小批还没算指纹的照片，供后台补算（抄 photosMissingThumb
  /// 的形状：分批 + 索引走 seq，避免全表扫）。
  Future<List<Photo>> photosMissingHash(String projectId, {int limit = 20}) =>
      (_db.select(_db.photos)
            ..where((t) => t.projectId.equals(projectId) &
                t.contentHash.isNull())
            ..orderBy([(t) => OrderingTerm.asc(t.seq)])
            ..limit(limit))
          .get();

  /// 指纹覆盖率：已算 / 未算。用于「正在核查 N 张」的提示。
  Future<({int hashed, int pending})> hashCoverage(String projectId) async {
    final row = await _db.customSelect(
      'SELECT COUNT(*) AS total, '
      'SUM(CASE WHEN content_hash IS NULL THEN 1 ELSE 0 END) AS pending '
      'FROM photos WHERE project_id = ?',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photos},
    ).getSingle();
    final total = row.read<int>('total');
    final pending = row.read<int?>('pending') ?? 0;
    return (hashed: total - pending, pending: pending);
  }

  /// 查项目内的重复照片。
  ///
  /// 一条 SQL 搞定（`GROUP BY content_hash HAVING COUNT(*) > 1`），
  /// 不把上千张照片全捞到内存里再分组 —— 项目动辄 1200 张，
  /// 全捞 = 1200 个对象 + 一次全表传输。
  ///
  /// 判重只认**非 NULL** 的指纹：NULL 是"还没算过"，把它当同一组
  /// 会把"没算过"的所有照片误报成彼此重复。
  Future<List<DuplicateSetWithGroups>> findDuplicates(String projectId) async {
    // ① 哪些指纹重复了
    final dupHashes = await _db.customSelect(
      'SELECT content_hash AS h FROM photos '
      'WHERE project_id = ? AND content_hash IS NOT NULL '
      'GROUP BY content_hash HAVING COUNT(*) > 1',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photos},
    ).get();
    if (dupHashes.isEmpty) return const [];

    final hashes = [for (final r in dupHashes) r.read<String>('h')];

    // ② 这些指纹下的照片（含组归属 + seq 供"保留最早" + 缩略图路径）
    //
    // ⚠️ **必须 LEFT JOIN photo_groups 拿 gseq**（2026-10-05）：
    // UI 的展示口径是「第 N 组」（与 organize_page 的组卡片一致），
    // 只查 group_id 的话 UI 拿不到次序，提示只能写「出现在 2 个组」——
    // 用户看不出该动哪张photo，跨组逐张选就无从谈起。
    // 用 LEFT 而非 INNER：游离照片（group_id 为 NULL）也必须查出来。
    final rows = await _db.customSelect(
      'SELECT p.id, p.content_hash AS h, COALESCE(p.group_id, \'\') AS g, '
      'p.seq, p.thumb_path AS t, g.seq AS gseq '
      'FROM photos p LEFT JOIN photo_groups g ON p.group_id = g.id '
      'WHERE p.project_id = ? AND p.content_hash IS NOT NULL '
      'ORDER BY p.seq ASC',
      variables: [Variable.withString(projectId)],
      readsFrom: {_db.photos, _db.photoGroups},
    ).get();

    final wanted = hashes.toSet();
    final byHash =
        <String, List<({String id, String group, int seq, String? thumb, int? gseq})>>{};
    for (final r in rows) {
      final h = r.read<String>('h');
      if (!wanted.contains(h)) continue;
      (byHash[h] ??= []).add((
        id: r.read<String>('id'),
        group: r.read<String>('g'),
        seq: r.read<int>('seq'),
        thumb: r.read<String?>('t'),
        gseq: r.read<int?>('gseq'),
      ));
    }

    return [
      for (final entry in byHash.entries)
        () {
          final items = entry.value; // 已按 seq ASC 排好
          return DuplicateSetWithGroups(
            hash: entry.key,
            photoIds: [for (final it in items) it.id],
            // rows 已 ORDER BY seq ASC，first 就是最早那张
            earliestPhotoId: items.first.id,
            groupIds: [for (final it in items) it.group],
            thumbPaths: [for (final it in items) it.thumb],
            photos: [
              for (final it in items)
                DuplicatePhoto(
                  id: it.id,
                  groupId: it.group,
                  groupSeq: it.gseq,
                  seq: it.seq,
                  thumbPath: it.thumb,
                ),
            ],
          );
        }(),
    ];
  }
}
