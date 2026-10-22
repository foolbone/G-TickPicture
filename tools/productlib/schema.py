# -*- coding: utf-8 -*-
"""
schema.py -- 产品库数据规范与库表定义

═══════════════════════════════════════════════════════════════════════
第 1 条：产品编码是唯一标识
═══════════════════════════════════════════════════════════════════════
产品清单由用户导入。**编码归一化后全局唯一**（跨批次、跨导入）。

为什么用「归一化编码」而不是原始编码做主键：
  实测同一批货在清单里存成文本 `1000000119`、在报关单里存成数字
  1000000119.0 —— 原始字面值不同，但**是同一件货**。归一化后一致。
  归一化规则与 APP 侧 `code_matcher.dart` 逐条对齐（见 libcore 说明）。

═══════════════════════════════════════════════════════════════════════
字段规范（写在代码里，而不是写在文档里 —— 文档会过时）
═══════════════════════════════════════════════════════════════════════
必填：
  code        产品编码。非空、长度 ≥4、必须含数字。

建议填（影响关联质量 —— 语义匹配要用）：
  name        品名。多模态描述与它做语义匹配，空了就少一路信号。
  spec        规格。同上。

选填：
  unit / brand / material / category / remark

系统字段（不由用户填）：
  photo_count / auto_count / manual_count / status / created_at / updated_at

═══════════════════════════════════════════════════════════════════════
照片分类字典（治理管道第①步的输出）
═══════════════════════════════════════════════════════════════════════
  packing_list  装箱单/唛头打印页 —— **高价值**：一张常含十几个编码
  label         物料标识卡 —— 可能有手写编码，OCR 常读不出，多模态能救
  product       产品外观特写 —— 无码，靠外观描述做语义匹配
  packaging     包装/木箱/托盘 —— 无码，弱信号
  scene         场景（车辆/集装箱外观/人物/空场）—— 无产品信息，跳过
  unknown       未分类（治理失败或降级模式下）—— 按有码处理
"""

# ── 产品字段规范 ────────────────────────────────────────────────────

PRODUCT_FIELDS = [
    # (字段名, 中文名, 是否必填, 说明)
    ('code', '产品编码', True, '唯一标识。非空、长度≥4、必须含数字'),
    ('name', '品名', False, '建议填 —— 语义匹配要用，空了少一路关联信号'),
    ('spec', '规格', False, '建议填 —— 同上'),
    ('unit', '单位', False, ''),
    ('brand', '品牌', False, ''),
    ('material', '材质', False, ''),
    ('category', '类别', False, ''),
    ('remark', '备注', False, ''),
]

REQUIRED_FIELDS = [f for f, _, req, _ in PRODUCT_FIELDS if req]

# ── 照片分类 ────────────────────────────────────────────────────────

# 照片分类字典（治理管道第①步的输出）
#
# 分类体系（2026-10-17 老板确认）：
#   photo_usage（用途大类）：监装 / 预检 / 其他
#   photo_kind（预检内部细分）：
#     label        = 0201 产品（有编码）—— 标识卡清晰或手写编码可读
#     product      = 0202 产品（无编码）—— 有产品本体但标识卡小/没有
#     packaging    = 0203 包装 —— 被包装覆盖，看不到具体产品
#     packing_list = 0204 清单 —— 白色纸质货品清单
#     unknown      = 0205 其他预检照片 —— 不属于以上四类的预检照
#   photo_usage='监装' 时 photo_kind='scene'，细分见 supervision_tag

# 编号 0201–0205 只决定**枚举顺序**（下拉按此序），UI 文案不带编号。
PHOTO_KINDS = {
    'label': '产品·有编码（标识卡/手写编码）',
    'product': '产品·无编码（产品本体特写）',
    'packaging': '包装（被包装覆盖或多款混放）',
    'packing_list': '清单（白色纸质货品清单）',
    'scene': '场景（监装照/车辆/集装箱，由 supervision_tag 细分）',
    'unknown': '其他预检照片',
}

# 哪些分类值得跑 OCR（有码可能性高）。
# 注意：packing_list 跑 OCR 只是提取「参考文字」，不用于关联（见 NO_LINK_KINDS）。
OCR_WORTHY_KINDS = ('packing_list', 'label', 'unknown')

# 哪些分类直接跳过（不浪费算力）
SKIP_KINDS = ('scene',)

# 哪些分类永远不关联产品（第 1 条延伸：物料清单 / 车辆 / 车牌无需关联产品编码）
#   · packing_list 含很多编码，但它是「参考文档」——把整页关联到某个单一产品是错的
#   · scene（车辆 / 集装箱 / 车牌 / 空场）本身无产品信息
# 这两类只做内容提取（OCR 文字 / 大模型描述）用于展示，绝不写 links。
# 2026-10-15 scene 并入：低置信兜底让 scene 也跑 OCR 存 token 了，必须同时
# 挡住自动关联，否则「分类错成 scene 的标识卡」读到的编码会被整页关联。
NO_LINK_KINDS = ('packing_list', 'scene')

# 🔴 哪些分类**能**关联产品（2026-10-17 老板规则，重要）：
#   「只有产品需要关联」——只有产品图片（0201 有编码 label / 0202 无编码
#   product）进入待关联队列与一切关联流程（自动关联/候选/新产品确认）。
#   包装、清单、其他预检、场景照一律不进。这是**白名单**口径，取代旧
#   「黑名单排除」思路 —— 未识别（photo_kind 为 NULL）的照片也不进，
#   治理识别为产品图、或人工改判后才进。
#   消费方：store._UNLINKED_SQL（待关联列表/徽章/树/箱号分组/工作台）、
#   store._cand_filter_sql（待确认候选）、pipeline 写关联的三处。
LINKABLE_KINDS = ('label', 'product')

# 照片用途分类（人工标注，用于筛选/统计，不影响治理）
PHOTO_USAGES = {
    '监装': '01 监装（货车/集装箱/装载过程，细分类见 supervision_tag）',
    '预检': '02 预检（产品/标签/包装/清单，细分类见 photo_kind）',
    '其他': '03 其他（不属于以上两类）',
}

# ── 监装照片的语义细分（2026-10-05 v3，装柜报告需要；2026-10-17 编号化）──
#
# 这个字段判的是「这张图在报告的哪个版位」（空柜/柜侧/封条/锁门/卡车头/
# 装柜过程），和 photo_kind 判的「这张图里有什么」是两个维度 —— 同一张空柜
# 照片在 photo_kind 眼里就是 scene。所以它**不能**从 photo_kind 推导。
#
# 🔴 2026-10-07 老板要求：细分由治理阶段的大模型识别，人工确认修改。
#   实现上**刻意不把 AI 结果直接写进 supervision_tag**，而是分两列：
#     · supervision_tag     = 人工确认过的值（报告只认这列）
#     · sup_tag_ai/_conf/_reason = 模型建议 + 置信度 + 理由（待确认）
#   理由：报告区块④的 4 张柜况代表图是从 supervision_tag 里挑的，一张
#   贴错标签的图会**直接印进交付给客户的正式报告**，比留空危害大得多。
#   「还没确认」≠「没问题」：AI 建议永不静默生效，必须有人点一下。
#   与 photo_usage 的分工：photo_usage 是粗粒度（预检/监装，管交付分组），
#   supervision_tag 是细粒度（监装内部的 7 种角色，只服务报告区块④⑦）。
#
# 编号 0101–0107 = 2026-10-17 老板分类表的监装段（01 监装）：
#   0101 空柜（柜内侧壁）/ 0102 柜侧（柜外两侧）/ 0103 封条（铅封及装门照）
#   0104 锁门（关门上锁）/ 0105 卡车头·车牌号 / 0106 装柜过程（柜内有货）
#   0107 其他监装照片
# ⚠️ 编号只用于**排序**（下拉/树按此顺序枚举），UI 文案不带编号（2026-10-17
#   老板原话：「前端页面显示不需要展示编号，编号只是为了显示顺序的」）。
# 🔴 value 只做展示文案；键（empty_container 等）是存储与报告口径，永不改 ——
#   改键等于全量数据迁移，报告区块④⑦查询跟着炸。
SUPERVISION_TAGS = {
    'empty_container': '空柜（柜内侧壁）',
    'container_side': '柜侧（柜体外部两侧）',
    'container_seal': '封条（铅封及装在柜门上）',
    'container_lock': '锁门（柜门关闭上锁）',
    'truck_head': '卡车头/车牌号',
    'loading_process': '装柜过程（柜内装载货物）',
    'other': '其他监装照片',
}

# 报告区块④的 4 个柜况槽位（顺序即报告里的呈现顺序）
CONTAINER_CONDITION_TAGS = ('empty_container', 'container_side',
                            'container_seal', 'container_lock')

# 报告区块⑦ Truck picture 收哪些
TRUCK_PICTURE_TAGS = ('truck_head', 'loading_process', 'other')

# 未分柜兜底柜的柜号（迁移用，UI 显示为「未分柜」）
UNCATEGORIZED_NO = '_UNCATEGORIZED'
UNCATEGORIZED_LABEL = '（未分柜）'      # 界面上唯一说法


# 手动上传的标准图在 standard_images.src_photo_id 里存的哨兵值。
# ⚠️ 这不是 photo_id，任何拿它去 join photos 的地方都会串（已在
# store.standard_for_photo 里按 origin='crop' 过滤）。
UPLOAD_SENTINEL = '_UPLOADED_'


def container_label(container_no, empty='（无柜号）'):
    """柜号 → 显示文案（**界面唯一口径**）。

    `_UNCATEGORIZED` 是迁移时给"柜号为空的老批次"落的兜底柜号，是**内部值**，
    漏到界面上像 bug（10-06 老板在产品库柜号下拉里看到 `_UNCATEGORIZED（524 件）`）。
    所有展示柜号的地方（产品库下拉 / 表格柜号列 / 柜页 / 报告页）都走这里，
    别再各写各的 if。

    ⚠️ 两个分支含义不同，别混：空 = 「（无柜号）」（连柜都没挂），
    内部兜底值 = 「（未分柜）」（挂着兜底柜，等归位）。
    """
    s = (container_no or '').strip()
    if not s:
        return empty
    if s == UNCATEGORIZED_NO:
        return UNCATEGORIZED_LABEL
    return s


# ── 数量列的解析口径（报告 TOTAL 行 / 页面汇总共用同一份）─────────
#
# 清单里同一个数量列出现过 `12` / `12.0` / "12 PCS" 三种写法，
# 落库存文本照抄（保真），求和时才转数字。转不出来的**返回 None**
# 而不是当 0 —— 当 0 会让 TOTAL 少算而不自知，比报错更坏。
import re as _re
_NUM_RE = _re.compile(r'-?\d+(?:\.\d+)?')


def to_number(text):
    """'12' / '12.0' / '12 PCS' / '1,200' → 12.0；解析不出返回 None。"""
    if text is None:
        return None
    s = str(text).replace(',', '').strip()
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def fmt_int(v):
    """浮点 → 整数文本（12.0 → '12'，12.5 → '12.5'）。"""
    if v is None:
        return ''
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(round(f))) if abs(f - round(f)) < 1e-6 else ('%g' % f)

# ── 关联来源 ────────────────────────────────────────────────────────

LINK_SOURCES = {
    'auto_ocr': 'OCR 精确/纠偏命中编码',
    'auto_vision': '多模态读取编码',
    'auto_semantic': '多模态描述与品名语义匹配（弱信号，仅提示）',
    'manual': '人工关联',
}

# 自动关联的置信度门槛：≥ 此值才自动建关联，否则留给人工
AUTO_LINK_THRESHOLD = 0.70

# 详情页/抽屉「显示用」预览图的长边（px）。原图动辄 3.8~21MB，直接显示会让
# 左右切换卡成幻灯片；1600 够 2x 看清细节，体积约 200~400KB。
# ⚠️ 改这个值会让已缓存的 view/ 全部失效（文件名含长边）—— 换了就清 view/。
VIEW_LONG_EDGE = 1600

# 「建议关联」候选的最低置信度（老板 10-02 要求）。
# 语义候选（SCORE_SEMANTIC=0.60）天生低于它 —— 它靠描述与品名的词面重合，
# 实测在真实库里给出的基本是噪声（products 的 spec/brand/unit 几乎全空，
# 匹配出来的是"看起来像"而非"就是它"）。所以：
#   · 语义候选整个不进建议列表（明确要求去掉）
#   · 编码类候选低于此分的也不进 —— 宁可让老板手输，也不给一堆错的让他挑
CAND_MIN_SCORE = 0.70

# 各来源的基础分（再乘 token/模型置信度）
SCORE_OCR_EXACT = 0.98
SCORE_OCR_PREFIX = 0.86
SCORE_OCR_EDIT1 = 0.88
SCORE_OCR_EDIT2 = 0.72
SCORE_VISION_CODE = 0.90
SCORE_SEMANTIC = 0.60   # 低于 AUTO_LINK_THRESHOLD → 只提示，不自动关联

# ── DDL ─────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 产品主表（编码归一化后唯一）
CREATE TABLE IF NOT EXISTS products (
    code_norm       TEXT PRIMARY KEY,
    code            TEXT NOT NULL,
    name            TEXT,
    spec            TEXT,
    unit            TEXT,
    brand           TEXT,
    material        TEXT,
    category        TEXT,
    remark          TEXT,
    -- 统计（由 links 重算，不手工维护）
    photo_count     INTEGER DEFAULT 0,
    auto_count      INTEGER DEFAULT 0,
    manual_count    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'active',
    -- 审核状态：confirmed=人工确认进入标准库。
    -- 清单导入（权威初始数据）默认 confirmed；照片识别的新编码须经人工确认才 confirmed。
    review_state    TEXT DEFAULT 'confirmed',
    source_batch    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);

-- 柜（一等实体，2026-10-05 v3）
--
-- 为什么把柜从 batches 的一个可空文本列提成独立表：
--   一个柜有**清单批次 + 照片批次多个**，柜级字段（封条号 / 到离柜时间 /
--   Inspector / Location / REMARKS）放批次上就得回答"写哪个批次"——
--   多份就必然漂移。柜是一等实体，批次挂柜。
--
-- 流程闸门：导入 API（清单 / 照片目录 / 自动探测 / 上传）强制 container_id，
-- 缺失一律 400「请先选择柜」。老数据里 container_no 为空的批次挂
-- _UNCATEGORIZED 兜底柜（UI 显示「未分柜」），补柜号后可改挂。
--
-- 柜况 4 图（空柜/柜侧/封条/锁门）**不存这里**：它们是照片，
-- 语义由 photos.supervision_tag 表达，每类取一张代表图即可 ——
-- 再建槽位表等于给同一件事造第二个真相源。
CREATE TABLE IF NOT EXISTS containers (
    id            TEXT PRIMARY KEY,
    container_no  TEXT NOT NULL UNIQUE,   -- 柜号（ISO 6346，如 EMCU9914616）
    seal_no       TEXT,                   -- 封条号（报告区块④）
    arrival_at    TEXT,                   -- 到柜时间
    departure_at  TEXT,                   -- 离柜时间
    inspector     TEXT,                   -- Inspector（报告区块②）
    location      TEXT,                   -- Inspection Location（报告区块②）
    product_name  TEXT,                   -- Product Name（报告区块②）
    client_name   TEXT,                   -- Client Name（报告区块②）
    remark        TEXT,                   -- REMARKS（报告区块③）
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- 导入批次：清单导入 / 照片上传 共用
CREATE TABLE IF NOT EXISTS batches (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,          -- checklist / photos
    name        TEXT,
    container_no TEXT,                  -- 柜号（批次号），照片与清单共用同一柜号关联
    note        TEXT,
    item_count  INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    -- 2026-10-05 v3：柜是一等实体，批次挂柜。
    -- container_no 降级为**冗余只读列**（读兼容老代码），唯一真相源是 containers。
    -- 导入 API 强制传 container_id —— 无柜不导。
    container_id TEXT REFERENCES containers(id)
);

-- ⚠️ idx_batches_ctn **不在这里建**：它依赖 container_id 列，而
-- CREATE TABLE IF NOT EXISTS 对老库不生效（老库 batches 没这列），
-- 建索引会报 `no such column: container_id` 把整个库锁死。
-- 索引统一在 store._migrate 里「先补列、后建索引」。

-- 采集图片库
CREATE TABLE IF NOT EXISTS photos (
    id            TEXT PRIMARY KEY,
    file          TEXT NOT NULL UNIQUE,
    path          TEXT NOT NULL,
    batch_id      TEXT,
    taken_at      TEXT,
    time_src      TEXT,
    bytes         INTEGER,
    md5           TEXT,
    width         INTEGER,
    height        INTEGER,
    is_dup        INTEGER DEFAULT 0,
    dup_of        TEXT,
    group_idx     INTEGER,
    -- 治理结果
    govern_state  TEXT DEFAULT 'pending',  -- pending/running/done/failed/skipped
    govern_error  TEXT,
    photo_kind    TEXT,
    kind_conf     REAL,
    vision_desc   TEXT,
    vision_codes  TEXT,                    -- JSON array
    vision_meta   TEXT,                    -- JSON object: 标签提取的结构化产品信息 {name,spec,brand,material,unit,category}
    vision_model  TEXT,
    govern_at     TEXT,
    created_at    TEXT NOT NULL,
    -- 人工标注时点了「跳过」的照片（不适用的场景照/重复的/认不出的）。
    -- 跳过是人工决策，必须持久：否则每次刷新它都会回到待认领队列里。
    manual_skip   INTEGER DEFAULT 0,
    skip_at       TEXT,
    skip_by       TEXT,
    -- 照片用途分类：监装 / 预检 / NULL（未分类）。
    -- 监装=集装箱监装现场拍的（装箱过程/封条/箱号），预检=仓库货品预检拍的（产品/标签）。
    -- 用于筛选和统计，不影响治理逻辑。
    photo_usage   TEXT,
    -- 箱号：标准采集格式 {柜号}/预检/{箱号}/照片.jpg 中自动提取的箱号
    carton_no     TEXT,
    -- 一次导入内的顺序号（2026-10-11）：同一 batch 内从 0 开始。
    -- 微信转来的图没有 EXIF、taken_at 是接收时间（35% 同秒），靠时间排序
    -- 等于靠运气；文件名里的序号（微信图片_..._<序号>_<批> / IMG_日期_时间 /
    -- 相册末段）才是稳定的发送/拍摄顺序。见 store.product_panorama_candidates。
    import_seq    INTEGER,
    -- 监装照片的语义细分（2026-10-05 v3，装柜报告需要）。
    -- 只有 photo_usage='监装' 时有意义；NULL = 未细分（报告里按 other 处理）。
    -- 柜况 4 图 = tag 的 4 个取值（empty/container_side/container_seal/container_lock）
    -- 各自取一张代表图；Truck picture 区块取 truck_head/loading_process/other。
    -- ⚠️ 刻意**不在治理阶段改任何像素**（方向/缩放/裁剪都是报告生成的事），
    --    人工修图走 standard_images（标准资产），原图永远只读。
    supervision_tag TEXT,
    -- AI 建议的监装细分（2026-10-07）：治理阶段多模态模型给的**建议**，
    -- 三列一组：有建议就有 conf 和 reason，不允许只写 tag 不写置信度
    -- （「算过了但不知道多准」和「没算过」必须能区分开）。
    -- ⚠️ 这三列**不是** supervision_tag 的默认值，报告永远只认人工确认值。
    sup_tag_ai        TEXT,   -- 模型建议的 tag（枚举外一律丢弃）
    sup_tag_ai_conf   REAL,   -- 0~1 置信度
    sup_tag_ai_reason TEXT,   -- 一句话依据，给人判断可不可信
    -- 人工是否已就这张照片的细分做过表态：1=确认过（哪怕是改成别的值），
    -- 0=还没表态。防止「重新治理」把人工已经确认过的标签冲掉。
    sup_tag_confirmed INTEGER DEFAULT 0,
    -- 无效照片（2026-10-12 老板需求）：拍糊/误拍/与作业无关的照片，人工批量标记。
    -- 标记后默认从照片列表、待确认关联、监装选图等**工作队列**里排除
    -- （「仅看无效」筛选可单独查看/撤销）。永不删文件 —— 取证原件只读。
    is_invalid    INTEGER DEFAULT 0,
    invalid_at    TEXT,
    invalid_by    TEXT,
    -- 本次忽略（2026-10-18 老板需求）：新产品确认时「本次忽略」按照片标记 ——
    -- 忽略后退出待关联/候选/新产品确认等一切关联队列（「已忽略」选项卡可
    -- 查看与恢复）。与 is_invalid 的区别：无效 = 照片本身坏；忽略 = 照片
    -- 没问题但本次不关联（新产品先不入库，数据保留，后续柜可能复用）。
    photo_ignored INTEGER DEFAULT 0,
    ignored_at    TEXT,
    ignored_by    TEXT,
    -- 相似重复检测指纹（2026-10-15 需求3）：dHash 64-bit 的 16 位 hex。
    -- 导入时算（JPEG draft 快速降采样 ~10ms/张），存量库由 dups 端点按需补算。
    -- NULL = 还没算过（不算失败也算没算，补算时重试）。
    phash         TEXT
);

CREATE INDEX IF NOT EXISTS idx_photos_state ON photos(govern_state);
CREATE INDEX IF NOT EXISTS idx_photos_kind ON photos(photo_kind);
CREATE INDEX IF NOT EXISTS idx_photos_batch ON photos(batch_id);
-- 2026-10-09 性能：照片列表 ORDER BY taken_at（routes/photos.py:220）此前无索引可用，
--   执行计划是「SCAN photos + USE TEMP B-TREE FOR ORDER BY」——每次全表扫描再排序，
--   而且会随照片数线性劣化。
--   实测（2738 张真实库）：末页 OFFSET 2600 由 17.1ms → 0.5ms（32.9x），
--   首页 0.9ms → 0.4ms。**建这条索引本身只耗时 8ms**，且 taken_at 无 NULL 值。
--   taken_at 是建表原始列（存量库都有），故可直接在这里建、不必走 _migrate 先补列。
CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken_at);
-- ⚠️ idx_photos_suptag 同理：老库 photos 没有 supervision_tag 列，
-- 索引在 store._migrate 里建（先补列后建索引）。

-- OCR token（原始识别结果，与关联结论分离）
CREATE TABLE IF NOT EXISTS ocr_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id   TEXT NOT NULL,
    raw_text   TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tokens_photo ON ocr_tokens(photo_id);

-- 产品 ↔ 照片 关联
CREATE TABLE IF NOT EXISTS links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code_norm   TEXT NOT NULL,
    photo_id    TEXT NOT NULL,
    source      TEXT NOT NULL,        -- auto_ocr/auto_vision/auto_semantic/manual
    confidence  REAL,
    evidence    TEXT,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    UNIQUE(code_norm, photo_id)
);

CREATE INDEX IF NOT EXISTS idx_links_code ON links(code_norm);
CREATE INDEX IF NOT EXISTS idx_links_photo ON links(photo_id);
CREATE INDEX IF NOT EXISTS idx_links_source ON links(source);

-- 导入/治理的运行日志（便于回溯"这批是怎么算出来的"）
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,        -- import_checklist / import_photos / govern / link
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    total       INTEGER DEFAULT 0,
    done        INTEGER DEFAULT 0,
    ok          INTEGER DEFAULT 0,
    failed      INTEGER DEFAULT 0,
    message     TEXT
);

-- 「发现新产品」中被人工忽略的候选编码（不再重复出现在发现列表里）
CREATE TABLE IF NOT EXISTS discover_ignore (
    code_norm   TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
);

-- 人工判定的「无关联」：老板查看候选照片后确认它**不属于这个产品**。
--
-- 为什么必须落库（10-05）：候选是**算出来的**（读码/同组），每次刷新都会
-- 重算 —— 只在前端隐藏的话，刷新一次它就回来了，等于没标记。
--
-- 为什么粒度是 (code_norm, photo_id) 而不是单 photo_id：
-- 一张照片可能同时是 A、B 两个产品的候选（它上面读出了两个码）。
-- 老板说「它不是 A 的」不能顺带把 B 的候选也一起抹掉 ——
-- 那样会替他做决定，而这个决定的范围他没授权。
--
-- 与 links 的关系：一对 (code_norm, photo_id) 要么被关联、要么被否决、
-- 要么待确认，三态互斥。人工关联时会自动清掉同对的否决记录
-- （老板改主意了就该能关联回来，不能让旧否决卡住他）。
CREATE TABLE IF NOT EXISTS cand_reject (
    code_norm   TEXT NOT NULL,
    photo_id    TEXT NOT NULL,
    -- 否决理由（可选）：'not_photo_of_product' 看得出是「这不是该产品的照片」，
    -- 'wrong_code_read' 是「读码读错了」。留空也允许，但有理由时
    -- 以后排查「为什么这批照片候选这么少」会轻松很多。
    reason      TEXT,
    created_at  TEXT NOT NULL,
    created_by  TEXT,
    PRIMARY KEY (code_norm, photo_id)
);

CREATE INDEX IF NOT EXISTS idx_candrej_photo ON cand_reject(photo_id);

-- 产品 ↔ 清单批次 多对多关联：同一个产品编码可能出现在多个柜号的清单里。
-- products.source_batch 只记录首次导入来源，详细的"在哪些柜号出现过"存在这里。
CREATE TABLE IF NOT EXISTS product_batch (
    code_norm   TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (code_norm, batch_id)
);
CREATE INDEX IF NOT EXISTS idx_pb_batch ON product_batch(batch_id);
CREATE INDEX IF NOT EXISTS idx_pb_code ON product_batch(code_norm);

-- 标准图：照片经人工裁剪/编辑后形成的标准格式资产（场景 4 的"标准格式"载体）
-- 导出标准库时：该照片有标准图 → 用标准图；没有 → 回退原图。CSV 记录图源可追溯。
--
-- ⚠️ origin 区分来源（2026-10-06 老板要求「手动上传照片作为标准图」）：
--   'crop'   = 从库内照片裁剪/编辑而来，src_photo_id 指向真实照片
--   'upload' = 用户直接上传的文件，与库内照片无关
--   src_photo_id 对 upload 存哨兵值 UPLOAD_SENTINEL（表约束是 NOT NULL，
--   改约束要重建表，代价远大于收益；所有查询必须按 origin 过滤，
--   绝不能拿哨兵值去 join photos）。
CREATE TABLE IF NOT EXISTS standard_images (
    id            TEXT PRIMARY KEY,
    code_norm     TEXT NOT NULL,
    src_photo_id  TEXT NOT NULL,
    kind          TEXT NOT NULL,      -- 类别（决定导出文件名的类别标识）
    file          TEXT NOT NULL,      -- 绝对路径（productlib/data/standard/<编码>/<类别>[_n].jpg）
    width         INTEGER,
    height        INTEGER,
    created_at    TEXT NOT NULL,
    created_by    TEXT,
    origin        TEXT,               -- crop / upload；老行为 NULL，按 crop 解读
    orig_name     TEXT                -- 上传时的原始文件名（crop 为 NULL）
);

CREATE INDEX IF NOT EXISTS idx_std_code ON standard_images(code_norm);
CREATE INDEX IF NOT EXISTS idx_std_photo ON standard_images(src_photo_id);

-- ═══════════════════════════════════════════════════════════════════
-- 清单行快照（2026-10-05 v3，装柜报告的数据源）
--
-- 为什么必须单独存：products 是**归一化编码唯一**的合并视图
-- （同 code 多行 → 一条，qty 累加），而报告的 Packing list 要按
-- 清单**原行**出 —— 样例报告里 `216070000001` 是连着 3 行的 3 件货。
-- 合并模型给不出这个行数，报告的数量也就会和清单对不上。
--
-- 数量列存**文本照抄**（清单里有 `12` / `12.0` / "12 PCS" 三种写法，
-- 强转数字会丢信息）；TOTAL 行在报告生成时求和。
--
-- check_import 是**清单里客户预填的**核对结果 —— 照抄进报告（那是客户的
-- 数据，不是我们下的结论）；check_result 是人工核对结论，NULL = 未核对
-- （沿用 check_import）。两列都空 → 报告该格留空，绝不填 PASS。
CREATE TABLE IF NOT EXISTS checklist_rows (
    batch_id     TEXT NOT NULL,        -- 清单批次（batches.id, kind='checklist'）
    seq          INTEGER NOT NULL,     -- 清单内行序（同码多行各自占一 seq）
    code         TEXT NOT NULL,        -- 原始编码（照抄，不归一化）
    code_norm    TEXT NOT NULL,        -- 归一化编码（与 products/links 同一口径）
    name         TEXT,                 -- DESCRIPTION
    spec         TEXT,
    package_no   TEXT,                 -- Package Number（向下填充后的箱号）
    order_qty    TEXT,                 -- Order Qty（文本照抄）
    loading_qty  TEXT,                 -- Loading Qty（文本照抄）
    check_import TEXT,                 -- 清单预填的 Quantity Check result
    check_result TEXT,                 -- 人工核对结论；NULL = 沿用 check_import
    taken_at     TEXT,                 -- 核对时间（留痕）
    taken_by     TEXT,
    created_at   TEXT NOT NULL,        -- 导入时间
    PRIMARY KEY (batch_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_clrows_norm ON checklist_rows(code_norm);
CREATE INDEX IF NOT EXISTS idx_clrows_batch ON checklist_rows(batch_id);
"""
