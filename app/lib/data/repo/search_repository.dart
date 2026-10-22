import '../../domain/model/photo_search_hit.dart';
import '../../domain/search/code_norm.dart';
import '../db/database.dart';

/// 按产品编码检索历史照片（2026-10-15 v0.24.0，v0.24.1 加索引缓存）。
///
/// ═══════════════════════════════════════════════════════════════
/// **只读**。本仓库没有任何写方法 —— 检索不产生归属、不改部类、
/// 不动分组，归属写入口仍然只有 `AssignService` 一条。
/// ═══════════════════════════════════════════════════════════════
///
/// **为什么匹配在 Dart 侧做，而不是写进 SQL**：
///
/// 现场的输入是「编码的**后几位**或**中间几位**」（老板 2026-10-15
/// 反馈）。这两种在 SQLite 里只能写成 `LIKE '%x'` / `LIKE '%x%'` ——
/// B-tree 索引用不上，全表扫；而「全角→半角、去连字符」这种规范化
/// SQL 侧根本表达不了（没有 reverse，也没有可靠的全角转换）。
///
/// 所以这里反过来看数据规模：本机量级是几万照片 / 十万级 OCR token。
/// 一次窄表查询把「照片 → 候选码」拉进内存（只两个窄列，几 MB），
/// 然后在 Dart 侧用纯函数规范化 + `endsWith/contains` 判定：
///   · 比 SQL 全表扫更快（几万次字符串比较是毫秒级）；
///   · 归一只存在 `code_norm.dart` 一处，可单测；
///   · **零迁移、零回填** —— 不新增列、不改写入侧，也就不存在
///     「写入时忘了算索引列」这种隐患。
///
/// **缓存与失效**（v0.24.1）：上面那句"一次窄表查询"原本是**每次
/// 搜索都来一次**（照片 join ~100-300ms + OCR 全表 ~200-400ms），
/// 人连着翻几个编码就要每次都等一遍 loading。现在索引建一次就留着，
/// 后续搜索只付内存比对（<10ms）。
///
/// 失效判定用触发器版本表（`search_index_version`，database.dart 里
/// 建）：五张业务表上任何写事务都把版本号 +1，检索前读一次即可判断
/// 索引是否过期 —— "拍完新照片再回来搜"必然命中，而连着搜一串编码
/// 只付一次构建代价。
///
/// 为什么不用 `PRAGMA data_version`：它对**同一连接自己的提交**不
/// 递增（SQLite 文档原文），而 App 全程单连接（drift 单例）——
/// 用它等于缓存永不失效，那会比不缓存更糟。
class PhotoSearchRepository {
  /// 构造检索仓库（只依赖数据库，可测试）。
  PhotoSearchRepository(this._db);

  /// 数据库。
  final AppDatabase _db;

  /// 单次检索的结果上限。
  ///
  /// 短串（如输 `12`）可能命中几百张 —— 不封顶会让人等一次全量渲染，
  /// 而且超过这个数量人也不会再往下翻了。
  static const int defaultLimit = 200;

  /// OCR token 参与匹配的最大长度。
  ///
  /// OCR 偶尔会吐出一整行字（几十上百字符），那种长文本里"包含"
  /// 任何 2 位串都是必然 —— 那是噪音不是命中。真实编码不会超过这个
  /// 长度，超长的一律不参与。
  static const int maxOcrTokenLength = 32;

  // ── 索引缓存 ────────────────────────────────────────────

  /// 已构建的索引；null = 还没建过。
  _SearchIndex? _index;

  /// 建 [index] 时读到的索引版本号。
  ///
  /// -1 = 从未构建。与当前值不同就重建（见类注释）。
  int _indexVersion = -1;

  /// 读检索索引的当前版本号（triggers 保证任何写事务都会 +1）。
  Future<int> _readIndexVersion() => readSearchIndexVersion(_db);

  /// 取索引（必要时重建）。
  Future<_SearchIndex> _loadIndex() async {
    final version = await _readIndexVersion();
    final cached = _index;
    if (cached != null && version == _indexVersion) return cached;
    final fresh = await _buildIndex();
    _index = fresh;
    _indexVersion = version;
    return fresh;
  }

  /// 建索引：一次 join 拿「照片 → 归属码 / 建议码」，一次窄表拿 OCR。
  ///
  /// 与项目/确认过滤无关（都是查询参数），所以索引是**全局一份**，
  /// 跨项目与项目内两种搜索共用同一次构建。
  Future<_SearchIndex> _buildIndex() async {
    final rows = await _db
        .customSelect(
          'SELECT p.id AS pid, p.project_id AS pj, p.group_id AS gid, '
          'p.taken_at AS taken, p.thumb_path AS thumb, p.file_path AS fpath, '
          'i.code AS assigned_code, si.code AS suggested_code, '
          'g.seq AS gseq, pr.name AS pname '
          'FROM photos p '
          'JOIN projects pr ON pr.id = p.project_id '
          'LEFT JOIN items i ON i.id = p.item_id '
          'LEFT JOIN photo_groups g ON g.id = p.group_id '
          'LEFT JOIN items si ON si.id = g.suggested_item_id '
          // 已归档项目不进检索结果（回收站里的东西不该被搜出来）。
          'WHERE pr.deleted_at IS NULL',
          readsFrom: {
            _db.photos,
            _db.projects,
            _db.items,
            _db.photoGroups,
          },
        )
        .get();

    final candidates = <_PhotoCandidate>[
      for (final r in rows)
        _PhotoCandidate(
          photoId: r.read<String>('pid'),
          projectId: r.read<String>('pj'),
          projectName: r.read<String>('pname'),
          filePath: r.read<String>('fpath'),
          takenAtMs: r.read<int>('taken'),
          groupId: r.read<String?>('gid'),
          groupSeq: r.read<int?>('gseq'),
          thumbPath: r.read<String?>('thumb'),
          assignedCode: r.read<String?>('assigned_code'),
          suggestedCode: r.read<String?>('suggested_code'),
        ),
    ];

    // OCR token → photoId（窄表，只两列）
    final ocrByPhoto = <String, List<String>>{};
    final tokens = await _db
        .customSelect(
          'SELECT t.photo_id AS pid, t.text AS txt '
          'FROM ocr_tokens t '
          'JOIN photos p ON p.id = t.photo_id '
          'JOIN projects pr ON pr.id = p.project_id '
          'WHERE pr.deleted_at IS NULL',
          readsFrom: {_db.ocrTokens, _db.photos, _db.projects},
        )
        .get();
    for (final t in tokens) {
      final pid = t.read<String>('pid');
      final txt = t.read<String>('txt');
      if (txt.length > maxOcrTokenLength) continue;
      ocrByPhoto.putIfAbsent(pid, () => []).add(txt);
    }

    return _SearchIndex(candidates: candidates, ocrByPhoto: ocrByPhoto);
  }

  /// 检索照片。
  ///
  /// [query] 是人的原始输入（可以带空格/连字符/全角）；[projectId]
  /// 为空 = 跨项目搜全部，非空 = 只搜这一个项目；[confirmedOnly]
  /// 为 true 时只认**已确认归属**的编码（排除建议与 OCR 的推测命中）。
  ///
  /// 输入不足 [kMinCodeQueryLength] 位直接返回空 —— 1 个字符的包含
  /// 匹配会命中半个库，那种"结果"没有意义。
  Future<List<PhotoSearchHit>> search({
    required String query,
    String? projectId,
    bool confirmedOnly = false,
    int limit = defaultLimit,
  }) async {
    final q = normalizeCode(query);
    if (q.length < kMinCodeQueryLength) return const <PhotoSearchHit>[];

    final index = await _loadIndex();

    // ── 逐个候选打分，每张照片只留最好的一条命中 ──────────────
    final hits = <PhotoSearchHit>[];
    for (final c in index.candidates) {
      if (projectId != null && c.projectId != projectId) continue;
      final best = _bestCandidate(
        q: q,
        assigned: c.assignedCode,
        suggested: c.suggestedCode,
        ocrTexts: index.ocrByPhoto[c.photoId],
        confirmedOnly: confirmedOnly,
      );
      if (best == null) continue;
      hits.add(
        PhotoSearchHit(
          photoId: c.photoId,
          projectId: c.projectId,
          projectName: c.projectName,
          filePath: c.filePath,
          takenAtMs: c.takenAtMs,
          matchedCode: best.code,
          source: best.source,
          kind: best.kind,
          groupId: c.groupId,
          groupSeq: c.groupSeq,
          thumbPath: c.thumbPath,
        ),
      );
    }

    // 排序：来源可信度 + 命中方式 → 同分按拍摄时间倒序（新的在前）。
    hits.sort((a, b) {
      final c = b.score.compareTo(a.score);
      return c != 0 ? c : b.takenAtMs.compareTo(a.takenAtMs);
    });
    return hits.length <= limit ? hits : hits.sublist(0, limit);
  }

  /// 在一张照片的全部候选码里挑**最好的一条命中**；都没命中返回 null。
  ({String code, PhotoSearchSource source, CodeMatchKind kind})? _bestCandidate({
    required String q,
    required String? assigned,
    required String? suggested,
    required List<String>? ocrTexts,
    required bool confirmedOnly,
  }) {
    String? bestCode;
    var bestSource = PhotoSearchSource.ocr;
    var bestKind = CodeMatchKind.none;

    void consider(String? raw, PhotoSearchSource source) {
      if (raw == null || raw.isEmpty) return;
      final kind = matchKind(normalizeCode(raw), q);
      if (!kind.matched) return;
      // 先比来源可信度，再比命中方式 —— 「已确认的后缀命中」胜过
      // 「OCR 的精确命中」，因为后者可能是识别错了。
      final better = source.weight > bestSource.weight ||
          (source.weight == bestSource.weight && kind.weight > bestKind.weight);
      if (better) {
        bestCode = raw;
        bestSource = source;
        bestKind = kind;
      }
    }

    consider(assigned, PhotoSearchSource.assigned);
    if (!confirmedOnly) {
      consider(suggested, PhotoSearchSource.suggested);
      for (final t in ocrTexts ?? const <String>[]) {
        consider(t, PhotoSearchSource.ocr);
      }
    }
    if (bestCode == null) return null;
    return (code: bestCode!, source: bestSource, kind: bestKind);
  }
}

/// 内存检索索引（[PhotoSearchRepository] 内部缓存）。
///
/// 全局一份：与项目限定、确认过滤都无关，两者都是查询参数。
class _SearchIndex {
  const _SearchIndex({required this.candidates, required this.ocrByPhoto});

  /// 每张照片一条候选（含归属码 / 建议码与展示所需字段）。
  final List<_PhotoCandidate> candidates;

  /// photoId → 该照片的 OCR 识别文本（已滤掉超长噪音）。
  final Map<String, List<String>> ocrByPhoto;
}

/// 一条照片候选（索引里的一行）。
class _PhotoCandidate {
  const _PhotoCandidate({
    required this.photoId,
    required this.projectId,
    required this.projectName,
    required this.filePath,
    required this.takenAtMs,
    this.groupId,
    this.groupSeq,
    this.thumbPath,
    this.assignedCode,
    this.suggestedCode,
  });

  final String photoId;
  final String projectId;
  final String projectName;
  final String filePath;
  final int takenAtMs;
  final String? groupId;
  final int? groupSeq;
  final String? thumbPath;
  final String? assignedCode;
  final String? suggestedCode;
}
