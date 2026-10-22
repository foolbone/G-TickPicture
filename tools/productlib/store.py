# -*- coding: utf-8 -*-
"""
store.py -- 产品库数据访问层

所有写操作集中在这里。理由与 APP 侧 `AssignService` 是唯一写归属入口
同一条原则：**关联（links）只能从这里写入**，且每条都记 source 与 created_by。
"""
import datetime
import functools
import io
import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime

# 上溯**两级**到 <仓库根>/tools —— build_library.py 就住在 tools/ 下。
# ⚠️ 必须是两级不是三级（仓库根）：build_library 不是包（tools/ 下没有
# __init__.py 也能 `import build_library`），而 routes/checks 里 import 的
# 是 `tools.productlib.*`（走仓库根）。两个层级都得在 sys.path 里。
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _p in (_REPO_ROOT, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import build_library as BL  # noqa: E402  复用已验证的归一化/匹配/清单解析

from . import paths, schema  # noqa: E402

# 路径走 paths.py（唯一真源）。DEFAULT_DB 支持 PL_DB 覆写（e2e 隔离 / 多项目）；
# connect() 显式传参仍优先 —— env 只是「没说的时候用哪个」。
DEFAULT_DB = paths.db_path()
DATA_DIR = paths.data_dir()
STANDARD_DIR = paths.standard_dir()      # 标准图资产目录

# ── 「未关联 / 关联候选」口径（2026-10-16 老板需求：监装照片不需要关联）──
# 监装照片（柜况/封条/箱号/车辆）本就不关联产品编码 —— 放进未关联队列只会
# 制造一个永远清不零的待办，还会把首页/徽章上的"待认领工作量"带偏。
# 🔴 同源铁律：这一份条件被下列各处共用，各写一份必然漂一位 ——
#    · photo_where_sql（未关联列表/左侧树/箱号分组/全选筛选）
#    · photo_groups（分组视图）
#    · photo_flag_counts ×2（五档徽章 / /api/photos/linkstate）
#    · _cand_filter_sql（待确认关联候选：列表角标/详情/③待办下拉）
#    · discovered_products（新产品确认）
#    · merge_suggestions（产品视角合并建议）
#    · stats（首页仪表盘 + 工作台总数）/ unlinked_photos（工作台列表）
#    注意：supervision_pending_of（③监装细分待办）是监装照片的**正当**
#    流程，与关联队列无关，不走这一条。
#
# 🔴 2026-10-17 老板规则（重要）：「只有产品需要关联」——只有产品图片
#   （label=0201 有编码 / product=0202 无编码）进入待关联。
#   白名单口径（schema.LINKABLE_KINDS）：包装/清单/其他预检/场景/未识别
#   一律不进。叠加 10-16 规则「监装不进关联队列」：usage='监装' 继续排除
#   —— 正常数据流监装照 kind=scene 不会撞白名单，但人工误改 kind 的脏
#   数据仍要被监装规则挡住（两条规则同时生效，宁可少进不误进）。
#   显示名「待关联」（原「未关联」）。
_UNLINKED_SQL = ("p.id NOT IN (SELECT photo_id FROM links) AND p.is_dup=0"
                 " AND IFNULL(p.photo_kind,'') IN (%s)"
                 % ','.join("'%s'" % k for k in schema.LINKABLE_KINDS)
                 + " AND IFNULL(p.photo_usage,'')<>'监装'"
                 # 本次忽略（2026-10-18）：忽略的照片退出待关联队列
                   " AND IFNULL(p.photo_ignored,0)=0")


def now_iso():
    return datetime.now().isoformat(timespec='seconds')


# 迁移只在每个库首次连接时执行一次，避免治理运行时每次请求都抢写锁。
# ⚠️ 必须按 **库路径** 记，不能用单个全局 bool —— 进程内先后连两个不同
#    库（测试的临时库 + 真实库，或将来多项目）时，第二个库会因开关已置
#    True 而跳过建表，报 `no such table: products`。
_schema_initialized = set()

def connect(db_path=None):
    db_path = db_path or DEFAULT_DB
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    # 柜作业段聚合要在 SQL 里判「这张照片的时间是不是快门时刻」，
    # 口径必须与 Python 侧 time_trustworthy 同源 —— App 采集命名也是
    # time_src='filename'，用 time_src 近似会把真时间误判成不可信。
    _register_time_fn(con)
    # WAL + 长超时：治理任务写库时，查询请求最多等 30 秒而不是 5 秒就 500
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA busy_timeout=30000')
    # 2026-10-09 性能：WAL 下 synchronous 该用 NORMAL。
    # 实测同一条 UPDATE+COMMIT：FULL 1.30ms/次 → NORMAL 0.04ms/次（37x）。
    # 原理：NORMAL 不在每次提交时 fsync WAL，只在**检查点**落盘，正常提交不必等磁盘。
    # 取舍：断电/硬崩溃可能丢掉最后极短窗口内的事务。本产品是本地单机工具、
    #   照片原件在别处、治理随时可重跑，这个代价可接受；若将来要保全量写入再改回。
    #   （注：别指望它提速治理——2738 张也才省约 3.5 秒，价值在降低写抖动。）
    con.execute('PRAGMA synchronous=NORMAL')
    key = os.path.abspath(db_path)
    if key not in _schema_initialized:
        con.executescript(schema.SCHEMA)
        _migrate(con)
        _schema_initialized.add(key)
    return con


def _has_col(con, table, col):
    """列是否已存在（PRAGMA 探测）。

    所有 ALTER TABLE 都必须先问一句 —— sqlite 的 ADD COLUMN 不幂等，
    「列已存在」会直接抛 duplicate column name 把整个流程打断。
    老库里可能已经手工加过列（不同版本的库跑过不同的迁移路径）。
    """
    return col in {r[1] for r in con.execute('PRAGMA table_info(%s)' % table)}


def _has_index(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                       (name,)).fetchone() is not None


def _backfill_import_seq(con):
    """给 import_seq 为空的历史照片补序号（幂等、只补空值）。

    🔴 补的顺序用 **rowid**（= 入库顺序 = 导入时按文件名遍历的顺序），
    而不是 taken_at —— 后者在微信来源里是接收时间，同秒一大片。
    SQL 里没法直接 UPDATE ... SELECT 带窗口函数，所以逐批次取 id 列表回写；
    照片量级几千、单次迁移几百个批次，秒级完成。
    """
    missing = con.execute(
        'SELECT COUNT(*) FROM photos WHERE import_seq IS NULL').fetchone()[0]
    if not missing:
        return 0
    done = 0
    for bid, in con.execute(
            'SELECT DISTINCT batch_id FROM photos '
            'WHERE import_seq IS NULL AND batch_id IS NOT NULL').fetchall():
        rows = con.execute(
            'SELECT id FROM photos WHERE batch_id=? AND import_seq IS NULL '
            'ORDER BY rowid', (bid,)).fetchall()
        for i, r in enumerate(rows):
            # 🔴 用**下标**取，不�� r['id']：_migrate 也被 upgrade.py 的裸连接
            #    调用，那条连接**没有** row_factory=sqlite3.Row，命名访问会抛
            #    "tuple indices must be integers"（打包版启动实测踩到：源码测试
            #    全绿是因为 store.connect 设了 row_factory）。
            con.execute('UPDATE photos SET import_seq=? WHERE id=?', (i, r[0]))
        done += len(rows)
    # 没有 batch 的零散照片（理论上不会有）也排一个序，免得永远是 NULL
    rows = con.execute(
        'SELECT id FROM photos WHERE import_seq IS NULL ORDER BY rowid').fetchall()
    base = con.execute('SELECT COALESCE(MAX(import_seq),-1) FROM photos').fetchone()[0]
    for i, r in enumerate(rows):
        con.execute('UPDATE photos SET import_seq=? WHERE id=?', (base + 1 + i, r[0]))
        done += 1
    if done:
        con.commit()
    return done


# ── 照片路径便携化（2026-10-18 老板问题 1：U盘/换机后照片找不到）──────────
# photos.path 曾存**绝对路径**（D:\集刻产品库\data\origin\...）—— 包拷到
# U盘/别的盘符/别的机器后前缀失效，所有照片 404。实际文件本体都在
# data 根之内（origin/{柜号}/...），所以修复 = 存相对路径 + 读时解析。
_DATA_SEG_RE = re.compile(r'^.*?[\\/]+data[\\/]+(.+)$', re.IGNORECASE)


def _data_root(con):
    """照片相对路径的基准根 = **库文件所在目录**（现场结构 data/productlib.db）。

    不能用全局 paths.data_dir()：测试/多库场景下库不在默认 data 根，
    相对路径各归各的库。按 db 文件路径缓存（同一库只查一次 PRAGMA）。
    """
    try:
        db_file = None
        for r in con.execute('PRAGMA database_list'):
            # database_list: (seq, name, file) —— main 库才有 file
            if r[1] == 'main' and r[2]:
                db_file = r[2]
                break
        key = os.path.abspath(db_file) if db_file else '__default__'
    except Exception:  # noqa: BLE001
        key = '__default__'
    cached = _DATA_ROOT_CACHE.get(key)
    if cached:
        return cached
    root = (os.path.dirname(os.path.abspath(db_file))
            if db_file else paths.data_dir())
    _DATA_ROOT_CACHE[key] = root
    return root


_DATA_ROOT_CACHE = {}


def photo_rel_path(path):
    """把任意形态的 path 归一为相对 data 根的路径（'origin/柜号/x.jpg'）。

    已是相对（不含盘符且不以 / 开头）→ 原样（正斜杠归一）；
    绝对路径里含 '/data/' 段 → 截取其后；
    其余（真正的外部绝对路径）→ 返回 None（调用方保留原值）。
    """
    p = str(path or '').replace('\\', '/')
    if re.match(r'^[A-Za-z]:', p) or p.startswith('/'):
        m = _DATA_SEG_RE.match(p)
        if m:
            return m.group(1)
        return None
    return p.lstrip('/') or None


def resolve_photo_path(con, pid, path):
    """把 photos.path 解析为当前机器上可用的绝对路径（便携化读侧）。

    三级解析，命中即返回：
      1. 原 path 存在（本机绝对路径仍然有效）→ 直接用；
      2. 相对路径或可截取 data 后缀的失效绝对路径 → 拼 data 根；
         命中后顺手把库里的 path **惰性回写**为相对形态（自愈迁移）；
      3. 都不行 → 返回原值（上层按文件不存在处理，如占位图）。
    """
    p = str(path or '')
    if p and os.path.isabs(p) and os.path.exists(p):
        return p
    rel = photo_rel_path(p)
    if not rel:
        return p
    full = os.path.join(_data_root(con), *rel.split('/'))
    if os.path.exists(full):
        if p != rel:
            try:
                con.execute('UPDATE photos SET path=? WHERE id=? AND path<>?',
                            (rel, pid, rel))
                con.commit()
            except Exception:  # noqa: BLE001 —— 自愈回写失败不影响读
                pass
        return full
    return p


def _migrate_photo_paths(con):
    """存量照片路径相对化（幂等，2026-10-18）。

    把 path 里带 'data\\' 段的绝对路径统一改写为相对 data 根的形态，
    包拷走/换盘符后照样能读。外部目录（不含 data 段）不动 —— 那类
    本来就不随包走，resolve 读不到时按缺图占位。
    """
    n = 0
    root = _data_root(con)
    for r in con.execute("SELECT id, path FROM photos WHERE path LIKE '%data%'"):
        rel = photo_rel_path(r['path'])
        if rel and rel != r['path'].replace('\\', '/'):
            full = os.path.join(root, *rel.split('/'))
            if os.path.exists(full):
                con.execute('UPDATE photos SET path=? WHERE id=?', (rel, r['id']))
                n += 1
    if n:
        con.commit()
    return n


def _migrate(con):
    """老库增量迁移。CREATE IF NOT EXISTS 对已存在的表不生效，列在这里补。

    ⚠️ 每一步都必须幂等（列探测 + 索引探测）：这个函数在每次 connect() 时
    跑（按库路径去重），老库里可能已经有部分列 —— 重复 ADD COLUMN 会抛
    duplicate column name，把整个产品库锁死。
    """
    cols = {r[1] for r in con.execute('PRAGMA table_info(products)')}
    if 'review_state' not in cols:
        # 存量产品来自清单导入/人工操作，视为已审核
        con.execute("ALTER TABLE products ADD COLUMN review_state TEXT"
                    " DEFAULT 'confirmed'")
        con.commit()

    pcols = {r[1] for r in con.execute('PRAGMA table_info(photos)')}
    if 'manual_skip' not in pcols:
        # 「跳过」是人工决策，老库补列后默认 0（未跳过）
        con.execute('ALTER TABLE photos ADD COLUMN manual_skip INTEGER DEFAULT 0')
        con.execute('ALTER TABLE photos ADD COLUMN skip_at TEXT')
        con.execute('ALTER TABLE photos ADD COLUMN skip_by TEXT')
        con.commit()
    if 'vision_meta' not in pcols:
        # 标签结构化提取：治理时从标识卡上读出的品名/规格/材质等
        con.execute('ALTER TABLE photos ADD COLUMN vision_meta TEXT')
        con.commit()
    if 'photo_usage' not in pcols:
        # 照片用途分类：监装 / 预检 / NULL
        con.execute('ALTER TABLE photos ADD COLUMN photo_usage TEXT')
        con.commit()
    # 🔴 这两个索引的建表 ALTER 原先和「加列」绑在同一段 `if` 里；后来列被
    #   并进 schema.SCHEMA（photos 表直接带这两列），`if 'photo_usage' not in
    #   pcols` 恒为 False → 索引永远不建。结果：新库、老库都缺 idx_photos_usage
    #   / idx_photos_carton，按用途/箱号筛选退化成全表扫描。改用 _has_index 保证
    #   存在（与下面的 idx_photos_suptag / idx_photos_supai 同模式）。
    if not _has_index(con, 'idx_photos_usage'):
        con.execute('CREATE INDEX IF NOT EXISTS idx_photos_usage ON photos(photo_usage)')
        con.commit()
    if 'carton_no' not in pcols:
        # 箱号：标准采集格式 {柜号}/预检/{箱号}/照片.jpg 中自动提取
        con.execute('ALTER TABLE photos ADD COLUMN carton_no TEXT')
        con.commit()
    if 'phash' not in pcols:
        # 相似重复检测指纹（2026-10-15 需求3）：dHash 64-bit hex。
        # 存量库不回填 —— dups 端点按需补算（一次一批），不挡 connect()。
        con.execute('ALTER TABLE photos ADD COLUMN phash TEXT')
        con.commit()
    if not _has_index(con, 'idx_photos_carton'):
        con.execute('CREATE INDEX IF NOT EXISTS idx_photos_carton ON photos(carton_no)')
        con.commit()
    if 'supervision_tag' not in pcols:        # 监装照片细分类（报告区块④⑦用，人工标注）
        con.execute('ALTER TABLE photos ADD COLUMN supervision_tag TEXT')
        con.commit()
    # ⚠️ 三列分开判断（不能一个 if 包三条 ALTER）：中途中断会留下
    # 「第一列已加、后两列没有」的半迁移态，合并判断会永远跳过它们。
    if 'photo_ignored' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN photo_ignored INTEGER DEFAULT 0')
        con.commit()
    if 'ignored_at' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN ignored_at TEXT')
        con.commit()
    if 'ignored_by' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN ignored_by TEXT')
        con.commit()
    # 照片路径便携化（2026-10-18）：存量绝对路径统一相对化（幂等）。
    # 放最后 —— 依赖上面所有列迁移先完成，且每次 connect 只跑一次。
    try:
        _migrate_photo_paths(con)
    except Exception:  # noqa: BLE001 —— 迁移失败不锁库，读侧 resolve 还能自愈
        pass
    if not _has_index(con, 'idx_photos_suptag'):
        con.execute('CREATE INDEX IF NOT EXISTS idx_photos_suptag ON photos(supervision_tag)')
        con.commit()
    # 监装细分的大模型建议（2026-10-07）：三列一组 + 一个已确认标记。
    # addColumn 一律幂等（_migrate 不在事务里，中断会留下「DDL 已落盘、
    # 版本号旧」的半迁移态；无脑重跑 ALTER 会直接砖化）。
    if 'sup_tag_ai' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN sup_tag_ai TEXT')
        con.commit()
    if 'sup_tag_ai_conf' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN sup_tag_ai_conf REAL')
        con.commit()
    if 'sup_tag_ai_reason' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN sup_tag_ai_reason TEXT')
        con.commit()
    if 'sup_tag_confirmed' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN sup_tag_confirmed INTEGER DEFAULT 0')
        con.commit()
    if not _has_index(con, 'idx_photos_supai'):
        con.execute('CREATE INDEX IF NOT EXISTS idx_photos_supai ON photos(sup_tag_ai)')
        con.commit()

    # ── is_invalid：无效照片（2026-10-12 老板需求，批量标记）──
    # 标记后默认从列表/待确认关联/监装选图等工作队列排除；「仅看无效」可查看撤销。
    # 永不删文件（取证原件只读），只是工作队列口径收窄。
    if 'is_invalid' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN is_invalid INTEGER DEFAULT 0')
        con.commit()
    if 'invalid_at' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN invalid_at TEXT')
        con.commit()
    if 'invalid_by' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN invalid_by TEXT')
        con.commit()

    # ── import_seq：一次导入内的**顺序号**（2026-10-11）──
    # 为什么要有它：微信转来的图没有 EXIF，taken_at 是**接收时间**（实测 35%
    # 与他人同秒、与真实拍摄差 2.7 天），按时间排序 = 按运气排序。而文件名里
    # 的序号（微信图片_<时间>_<序号>_<批> / IMG_日期_时间 / 相册末段序号）
    # 是稳定的发送/拍摄顺序 —— 把它落成列，才能在"标签近景"旁边找到
    # "可能的全景图"（见 product_panorama_candidates）。
    # 语义：**同一 batch 内**从 0 开始的导入序；跨批次无意义，比较时必须
    # 先按 batch_id 圈定。
    if 'import_seq' not in pcols:
        con.execute('ALTER TABLE photos ADD COLUMN import_seq INTEGER')
        con.commit()
    _backfill_import_seq(con)

    if not _has_col(con, 'standard_images', 'origin'):
        # 标准图来源（2026-10-06 手动上传标准图）：crop=库内照片裁剪 / upload=直接上传。
        # 老行为 NULL → 读取时按 crop 解读，不回填（回填要全表扫，没必要）。
        con.execute('ALTER TABLE standard_images ADD COLUMN origin TEXT')
        con.commit()
    if not _has_col(con, 'standard_images', 'orig_name'):
        con.execute('ALTER TABLE standard_images ADD COLUMN orig_name TEXT')
        con.commit()

    bcols = {r[1] for r in con.execute('PRAGMA table_info(batches)')}
    if 'container_no' not in bcols:
        # 柜号（批次号）：照片与清单共用同一柜号关联
        con.execute('ALTER TABLE batches ADD COLUMN container_no TEXT')
        con.execute('CREATE INDEX IF NOT EXISTS idx_batches_container ON batches(container_no)')
        con.commit()
    if 'container_id' not in bcols:
        # v3：批次挂柜。container_no 降级为冗余只读列。
        con.execute('ALTER TABLE batches ADD COLUMN container_id TEXT')
        con.commit()
    if not _has_index(con, 'idx_batches_ctn'):
        con.execute('CREATE INDEX IF NOT EXISTS idx_batches_ctn ON batches(container_id)')
        con.commit()
    if not _has_index(con, 'idx_batches_container'):
        con.execute('CREATE INDEX IF NOT EXISTS idx_batches_container ON batches(container_no)')
        con.commit()

    # product_batch 多对多表：老库从 products.source_batch 回填
    con.execute('''CREATE TABLE IF NOT EXISTS product_batch (
        code_norm TEXT NOT NULL, batch_id TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY (code_norm, batch_id))''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_pb_batch ON product_batch(batch_id)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_pb_code ON product_batch(code_norm)')
    # 回填：把已有 products.source_batch 迁到 product_batch（只迁有值的）
    con.execute('''INSERT OR IGNORE INTO product_batch(code_norm, batch_id, created_at)
                   SELECT code_norm, source_batch, created_at FROM products
                   WHERE source_batch IS NOT NULL AND source_batch != '' ''')
    con.commit()

    # 标准图落盘布局迁移：扁平 <sid>.jpg → <编码>/<类别>.jpg（幂等，失败不崩）
    _migrate_standard_layout(con)

    # v3：老批次归柜。把还挂在 container_no 上的批次按柜号建 containers 并回填。
    _migrate_containers(con)

    # 2026-10-10：历史清单导入的新产品漏记 product_batch（upsert_products 的
    # continue 在关联写入之前）→ 老库里「按柜号筛产品」大面积为 0。
    # 从 checklist_rows（清单原行快照，code_norm+batch_id 都在）幂等回填。
    _migrate_product_batch_backfill(con)


def _migrate_product_batch_backfill(con):
    """从 checklist_rows 回填 product_batch（历史导入的新产品漏关联修复）。

    幂等：INSERT OR IGNORE，主键 (code_norm,batch_id) 已存在就跳过。
    checklist_rows 是清单**原行**快照，code_norm+batch_id 天然成对 ——
    它就是「这个产品被这份清单带进过哪个柜」的权威证据。
    """
    con.execute('''INSERT OR IGNORE INTO product_batch(code_norm,batch_id,created_at)
                   SELECT DISTINCT cr.code_norm, cr.batch_id, cr.created_at
                   FROM checklist_rows cr
                   WHERE cr.code_norm IS NOT NULL AND TRIM(cr.code_norm) != ''
                     AND cr.batch_id IS NOT NULL''')
    con.commit()


def _migrate_containers(con):
    """把 batches.container_no 里的历史柜号落成 containers 行，回填 container_id。

    幂等：已建的柜不重复建；已回填的批次不重复回填（`container_id IS NULL` 判定）。
    柜号为空的批次挂 `_UNCATEGORIZED` 兜底柜 —— UI 显示「未分柜」，
    补柜号后可改挂（POST /api/containers/{id}/reassign）。
    """
    ts = now_iso()
    # 1. 按柜号建柜
    for r in con.execute(
            "SELECT DISTINCT container_no FROM batches"
            " WHERE container_no IS NOT NULL AND TRIM(container_no) != ''"
            " AND container_no NOT IN (SELECT container_no FROM containers)"):
        # 🔴 用下标 r[0]：_migrate 也被 upgrade.py 的**裸连接**调用，
        #    那条连接没有 row_factory（见 upgrade.upgrade 的注释）。
        con.execute('INSERT OR IGNORE INTO containers'
                    '(id, container_no, created_at, updated_at) VALUES (?,?,?,?)',
                    (uuid.uuid4().hex[:12], r[0], ts, ts))
    # 2. 兜底柜（没有柜号的批次）
    n_blank = con.execute(
        "SELECT COUNT(*) FROM batches"
        " WHERE container_no IS NULL OR TRIM(container_no) = ''").fetchone()[0]
    if n_blank:
        con.execute('INSERT OR IGNORE INTO containers'
                    '(id, container_no, remark, created_at, updated_at)'
                    ' VALUES (?,?,?,?,?)',
                    (uuid.uuid4().hex[:12], schema.UNCATEGORIZED_NO,
                     '迁移自「无柜号」的历史批次，补柜号后可改挂到正式柜。', ts, ts))
    con.commit()
    # 3. 回填 container_id（同步冗余 container_no —— 它现在是只读镜像）
    con.execute('''UPDATE batches SET container_id = (
                       SELECT c.id FROM containers c
                       WHERE c.container_no = batches.container_no)
                   WHERE (container_id IS NULL OR container_id = '')
                     AND container_no IS NOT NULL AND TRIM(container_no) != '' ''')
    con.execute('''UPDATE batches SET container_id = (
                       SELECT c.id FROM containers c
                       WHERE c.container_no = ?)
                   WHERE (container_id IS NULL OR container_id = '')
                     AND (container_no IS NULL OR TRIM(container_no) = '') ''',
                (schema.UNCATEGORIZED_NO,))
    con.commit()


def needs_migration(db_path=None):
    """当前代码要求的库结构，与磁盘上的库是否不一致（是否还有待迁移项）。

    用于「启动即无感升级」：只在**真需要**时才备份+迁移+核对，避免每次启动
    都复制一份 data\\ 备份（那会很快塞满磁盘）。返回 False 的几种情况：
      · 库文件不存在（connect() 会建全新库，谈不上迁移）
      · 库已具备当前代码要求的所有 表/列/索引

    🔴 与 store._migrate 添加的「表/列/索引」一一对应。_migrate 里**新增**
    ALTER 时，这里必须同步补上对应存在性检查，否则新版本发布后「是否需要
    升级」会误判为否 → 跳过备份 → 退化成 connect() 的静默无备份迁移
    （正是 2026-10-10 要修的坑）。tests/auto_upgrade.py 用「缺一列的旧库」
    卡住这个漂移：改 _migrate 加列忘了改这里，测试立刻红。
    """
    db_path = db_path or DEFAULT_DB
    if not os.path.isfile(db_path):
        return False
    con = sqlite3.connect(db_path, timeout=5)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ('products', 'containers', 'batches', 'photos', 'ocr_tokens',
                  'links', 'runs', 'discover_ignore', 'cand_reject',
                  'product_batch', 'standard_images', 'checklist_rows'):
            if t not in tables:
                return True
        def _cols(t):
            return {r[1] for r in con.execute('PRAGMA table_info(%s)' % t)}
        if 'review_state' not in _cols('products'):
            return True
        for c in ('manual_skip', 'skip_at', 'skip_by', 'vision_meta',
                  'photo_usage', 'carton_no', 'supervision_tag', 'sup_tag_ai',
                  'sup_tag_ai_conf', 'sup_tag_ai_reason', 'sup_tag_confirmed',
                  'import_seq', 'is_invalid', 'invalid_at', 'invalid_by'):
            if c not in _cols('photos'):
                return True
        for c in ('origin', 'orig_name'):
            if c not in _cols('standard_images'):
                return True
        for c in ('container_no', 'container_id'):
            if c not in _cols('batches'):
                return True
        idx = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        for i in ('idx_photos_usage', 'idx_photos_carton', 'idx_photos_suptag',
                  'idx_photos_supai', 'idx_batches_container', 'idx_batches_ctn',
                  'idx_pb_batch', 'idx_pb_code'):
            if i not in idx:
                return True
        return False
    finally:
        con.close()


_WECHAT_NAME_RE = re.compile(r'微信图片_(\d{14})_(\d+)_(\d+)')
# within_burst 的可选参数哨兵（None 是合法的目录键，不能拿它当"没传"）
_MISSING = object()
# App 采集命名（project_paths.rawFileName）：`20260927_151257_00896.jpg`
# 前两段是拍摄时刻（App 采集时写入，等于快门时间），末段是**会话内连拍序号**。
_APP_SEQ_RE = re.compile(r'^(\d{8})_(\d{6})_(\d+)\.')
# 相机原生命名 `IMG_20250405_083614.jpg` / `P_20260927_101234.jpg`
_CAM_NAME_RE = re.compile(r'^[A-Za-z]+_(\d{8})_(\d{6})\.')


def _row_get(r, key, default=None):
    """sqlite3.Row / dict 都能取（老代码两种都在传）。"""
    try:
        v = r[key]
    except (IndexError, KeyError, TypeError):
        return default
    return default if v is None else v


def photo_dir_key(row):
    """照片所属「文件夹」键 —— 「同一件货的照片在同一个文件夹里」。

    App 交付包的结构是 `预检/<箱号>/20260927_151257_00896.jpg`：
      · carton_no 已由导入时从目录名提取 → 优先用它（最干净）
      · 没箱号的（监装/平铺）→ 退回 path 的目录（path 一直存着完整层级）
      · import_standard_folder 只把 basename 写进 file，所以**绝不能只看 file**
        —— 那一列在 App 包里全是空的目录，用它等于所有照片都"同目录"。
    """
    cno = _row_get(row, 'carton_no')
    if cno not in (None, '', 'None'):
        return 'carton:%s' % cno
    for col in ('path', 'file'):
        v = _row_get(row, col, '')
        if v:
            d = os.path.dirname(str(v).replace('\\', '/'))
            if d:
                return 'dir:%s' % d
    return ''


@functools.lru_cache(maxsize=8192)
def photo_time_window(time_src=None, file_name=None):
    """「同一段连拍」的时间窗（秒）—— 老板口径：不是前后 5 分钟内的就不要推荐。

    三档，判据是**时间到底是不是拍摄时刻**，不是 time_src 这一列：
      · App 采集命名 / 相机原生命名 / EXIF → 时间就是快门时刻 → ±300s
      · 微信命名 `微信图片_20260915103314_...` → 时间戳是**转发/接收**时刻，
        一次转发几十张会挤在同一秒、与真实拍摄差好几天 → ±1800s
      · mtime（文件写入时刻）→ 最不可信 → ±1800s

    ⚠️ 2026-10-19 事故：之前只看 time_src，App 命名也是 'filename'，
       于是被当成"微信那种不可信时间"放宽到 30 分钟 —— 实测候选里 61%
       是 5 分钟以外的（59% 在 10 分钟以上），跨箱推荐占 36%。
    """
    base = os.path.basename(file_name or '')
    if _WECHAT_NAME_RE.match(base):
        return 1800
    if _APP_SEQ_RE.match(base) or _CAM_NAME_RE.match(base):
        return 300
    src = (time_src or '').lower()
    if src == 'exif':
        return 300
    if src == 'filename':
        # 认不出形态的文件名时间：宁宽勿杀，但不能按 5 分钟硬切（可能差很远）
        return 1800
    return 1800


def burst_gap_sec(a, b):
    """两张照片的拍摄时间差（秒）；任一没时间 → None（不参与过滤）。"""
    ta, tb = _row_get(a, 'taken_at'), _row_get(b, 'taken_at')
    if not ta or not tb:
        return None
    try:
        return abs((_dt(tb) - _dt(ta)).total_seconds())
    except Exception:  # noqa: BLE001
        return None


def within_burst(a, b, ka=_MISSING, kb=_MISSING):
    """两张照片是否可能是「同一段拍摄」—— 全景推荐的唯一入口（口径同源）。

    两条硬规则，都来自老板 2026-10-19 的原话：
      1. **同一个文件夹里**：App 交付包按箱号分目录，一件货的照片不会散在
         两个箱目录里。跨目录 = 必错，直接淘汰。
      2. **同一时间段内**：窗宽取两张照片各自的**较小值**（一方时间可信、
         一方不可信时按严的来）。

    ka/kb 是预先算好的 photo_dir_key（大循环里省掉重复算目录，逻辑不变）。
    返回 (bool, gap_sec, reason)：reason 是直接给人看的依据文案。
    """
    d_a = photo_dir_key(a) if ka is _MISSING else ka
    d_b = photo_dir_key(b) if kb is _MISSING else kb
    if d_a != d_b:
        return False, None, ''
    w = min(photo_time_window(_row_get(a, 'time_src'), _row_get(a, 'file')),
            photo_time_window(_row_get(b, 'time_src'), _row_get(b, 'file')))
    gap = burst_gap_sec(a, b)
    if gap is not None and gap > w:
        return False, gap, ''
    return True, gap, burst_reason(a, b, gap)


def time_trustworthy(time_src=None, file_name=None):
    """这张照片的 taken_at 是不是**拍摄时刻**（可信到能给人看秒差）。

    微信图的时间是接收时刻、mtime 是文件写入时刻 —— 一次转发几十张会挤在
    同一秒里，显示"相隔 1 秒"是**假证据**（真实拍摄可能差好几天）。
    只有 App 采集命名 / 相机原生命名 / EXIF 才允许把秒差摆到界面上。
    """
    return photo_time_window(time_src, file_name) <= 300


def _time_trusted_sql(time_src, file_name):
    """time_trustworthy 的 SQL 版（供作业段聚合调用）。
    出错一律当**不可信** —— 宁可少标「可信」，绝不能给假证据。"""
    try:
        return 1 if time_trustworthy(time_src, file_name) else 0
    except Exception:  # noqa: BLE001
        return 0


def _register_time_fn(con):
    """把时间可信度判定注册成 SQL 函数 pl_time_trusted（幂等）。
    裸连接（如升级探测）走到聚合查询时也能补注册。"""
    try:
        con.create_function('pl_time_trusted', 2, _time_trusted_sql,
                            deterministic=True)
    except Exception:  # noqa: BLE001
        pass
    return con


def burst_reason(a, b, gap):
    """给人看的依据：同箱 N · 相隔 X 秒 · 连拍序号相邻。

    ⚠️ 秒差只在**时间可信**时才写 —— 微信/mtime 的"相隔 1 秒"是假的，
    宁可少写一条依据，也不给老板一个看起来很确凿的错数字。
    """
    parts = []
    cno = _row_get(a, 'carton_no') or _row_get(b, 'carton_no')
    if cno not in (None, '', 'None'):
        parts.append('同箱 %s' % cno)
    if gap is not None and time_trustworthy(_row_get(a, 'time_src'),
                                            _row_get(a, 'file')) \
            and time_trustworthy(_row_get(b, 'time_src'), _row_get(b, 'file')):
        if gap < 60:
            parts.append('相隔 %d 秒' % int(round(gap)))
        else:
            parts.append('相隔 %d 分' % int(round(gap / 60.0)))
    sa, _ = file_seq(_row_get(a, 'file'))
    sb, _ = file_seq(_row_get(b, 'file'))
    if sa is not None and sb is not None and abs(sa - sb) <= 2:
        parts.append('连拍序号相邻')
    elif _row_get(a, 'group_idx') is not None \
            and _row_get(a, 'group_idx') == _row_get(b, 'group_idx'):
        parts.append('同一次连拍')
    return ' · '.join(parts)


def file_seq(file_name):
    """从文件名解析「序号」，认得三种来源（解析不出返回 None）。

    微信 `微信图片_20260915103314_22079_838.jpg` → (22079, '838')
      时间戳是**发送/接收**时刻，序号才是稳定的发送顺序（实测连续递增）。
    相机 `IMG_20250405_083614.jpg` → 数字段是时间不是序号，返回 None
      （相机的时间来自 EXIF，本来就可信，不需要靠序号）。
    相册 `20260915_204034_01066.jpg` → (1066, None) 末段是序号。

    只用于**排序加权**，不参与"是不是同一件货"的判定。
    """
    base = os.path.basename(file_name or '')
    m = _WECHAT_NAME_RE.match(base)
    if m:
        return int(m.group(2)), m.group(3)
    m2 = re.match(r'^(\d{8})_(\d{6})_(\d+)\.', base)
    if m2:
        return int(m2.group(3)), None
    return None, None


def _photo_seq_key(con_batch):
    """批次内照片的稳定顺序键：import_seq，NULL 时退回 rowid（= 入库序）。"""
    return sorted(con_batch, key=lambda r: (
        r['import_seq'] if r['import_seq'] is not None else 10 ** 9, r['rowid']))


def product_panorama_candidates(con, code_norm, k=3, anchor=None):
    """「可能的全景图」候选：由**已关联的标签近景**推出来的邻近照片。

    场景（2026-10-11 老板提出）：作业时对一件货拍两张 —— 怼标签拍的近景
    （OCR/多模态读得到编码，自动关联的就是它），退后拍的**产品全景**（图上
    没有编码，系统无从下手）。要帮老板把后者找出来确认。

    🔴 四条设计约束，都是实测换来的：
    1. **同一个文件夹里**（2026-10-19 老板口径）：App 交付包是
       `预检/<箱号>/xxx.jpg`，一件货的照片只在它那个箱目录里。跨目录 = 必错。
    2. **同一时间段内**：窗宽按**文件名形态**分档（见 photo_time_window）——
       App 采集命名里的 `yyyyMMdd_HHmmss` 就是快门时刻，可信 → ±5min；
       微信命名是转发时刻 → 只能放宽。
    3. **只给缺全景的产品**：已经有 product/packaging 类照片的产品不出声，
       不给老板推他已经有东西的提醒。
    4. **同组不许整组甩**：微信来源的组实测平均 22.9 张 —— 那不是建议，
       是负担。同组只作**排序加分**，候选一律收敛到 k。

    ⚠️ 2026-10-19 重写（老板反馈「推荐的图片不是很准」）：
    旧口径按 `import_seq`（= 文件系统扫描顺序）取 ±k 邻居 —— 而扫描顺序
    **跨箱号跳跃**（实测同一批里 seq0-3 是箱239 @15:12，seq4 起跳到箱240
    @11:23），于是推荐里 35.8% 跨箱、61.3% 相隔 5 分钟以上（59% 超 10 分钟）。
    现在改成「同目录 + 时间窗 + 连拍序号」三信号打分。

    绝不自动关联：全景只能证明"同一托盘/同一批发送"，证明不了"同一件货"。
    过滤口径复用 `_cand_filter_sql` + `rejected_pairs`（角标与列表同源）。

    [anchor] 当前打开抽屉的那张照片。给了就**先按它筛再截断** ——
    ⚠️ 顺序很关键：同一个编码常在多个箱号里都有已关联照，不传 anchor 时
    k 条名额会被别的箱号的候选占满，等路由层再按当前这张一过滤就全没了
    （实测 300 张样本里 76 张因此变成 0 条）。宁可多算，不能截错。
    """
    pr = con.execute('SELECT code_norm FROM products '
                     'WHERE code_norm=? OR code=?', (code_norm, code_norm)).fetchone()
    cn = pr['code_norm'] if pr else code_norm

    linked_rows = con.execute(
        'SELECT p.* FROM links l JOIN photos p ON p.id=l.photo_id '
        'WHERE l.code_norm=? AND IFNULL(p.is_dup,0)=0', (cn,)).fetchall()
    if not linked_rows:
        return []
    # ② 只对「缺全景」的产品出声
    has_pano = con.execute(
        "SELECT 1 FROM links l JOIN photos p ON p.id=l.photo_id "
        "WHERE l.code_norm=? AND IFNULL(p.is_dup,0)=0 "
        "AND p.photo_kind IN ('product','packaging') LIMIT 1", (cn,)).fetchone()
    if has_pano:
        return []

    linked_ids = {r['id'] for r in linked_rows}
    batch_ids = sorted({r['batch_id'] for r in linked_rows if r['batch_id']})
    if not batch_ids:
        return []

    # 每批的候选池：**按目录键建索引**（不是按 import_seq 排序）——
    # 扫描顺序会跨箱号跳跃，用它取邻居就是噪音来源；按目录直接命中同箱的那几十张，
    # 顺带把 O(批内张数) 的扫描降到 O(同目录张数)（真库 1617 张关联照 × 905 张
    # 批次，不建索引会跑到分钟级）。
    pools = {}
    _dir_keys = {}      # photo_id -> 目录键（只算一次）
    for bid in batch_ids:
        rows = con.execute(
            'SELECT p.* FROM photos p '
            'WHERE p.batch_id=? AND IFNULL(p.is_dup,0)=0 '
            'AND IFNULL(p.is_invalid,0)=0', (bid,)).fetchall()
        if not rows:
            continue
        by_dir = {}
        for x in rows:
            # ⚠️ 别用 k 当循环变量 —— 外层参数 k（返回条数上限）会被遮蔽，
            # 最后的 out[:k] 直接 TypeError（2026-10-19 踩）。
            dk = photo_dir_key(x)
            _dir_keys[x['id']] = dk
            by_dir.setdefault(dk, []).append(x)
        pools[bid] = by_dir
    if not pools:
        return []
    cand = {}   # photo_id -> 打分信息
    _anchor_key = photo_dir_key(anchor) if anchor is not None else None
    for r in linked_rows:
        by_dir = pools.get(r['batch_id'])
        if not by_dir:
            continue
        kr = photo_dir_key(r)
        seq_src, seq_batch = file_seq(r['file'])
        r_usage = _row_get(r, 'photo_usage')
        for p in by_dir.get(kr, ()):            # 只扫同目录的那几十张
            pid = p['id']
            if pid in linked_ids:
                continue
            ok, gap, reason = within_burst(r, p, kr, kr)
            if not ok:
                continue
            if anchor is not None and not within_burst(anchor, p, _anchor_key, kr)[0]:
                continue                        # 与**当前这张**不同箱/隔太久
            # 用途不同（预检 vs 监装）= 两件事，绝不互推
            p_usage = _row_get(p, 'photo_usage')
            if r_usage and p_usage and r_usage != p_usage:
                continue
            # 打分：时间越近越高；同一次连拍、连拍序号相邻各自加分
            if gap is None:
                score = 4                                  # 没时间：只靠目录
            elif gap <= 30:
                score = 12
            elif gap <= 120:
                score = 9
            elif gap <= 300:
                score = 6
            else:
                score = 3
            same_group = (_row_get(p, 'group_idx') is not None
                          and _row_get(r, 'group_idx') == _row_get(p, 'group_idx'))
            if same_group:
                score += 4                                 # 同组：确认度高
            cseq, cbatch = file_seq(_row_get(p, 'file'))
            if seq_src is not None and cseq is not None and \
                    (seq_batch is None or cbatch is None or seq_batch == cbatch):
                d = abs(cseq - seq_src)
                if d <= 2:
                    score += 3                             # App 会话内连拍序号相邻
                elif d <= 5:
                    score += 1
            # 秒差只在时间可信时给（微信接收时刻的"相隔 1 秒"是假证据）
            _trust = time_trustworthy(_row_get(r, 'time_src'), _row_get(r, 'file')) \
                and time_trustworthy(_row_get(p, 'time_src'), _row_get(p, 'file'))
            gap_txt = ('%d 秒' % int(round(gap))) if (gap is not None and _trust) else None
            old = cand.get(pid)
            if old and old['score'] >= score:
                continue
            cand[pid] = {
                'photo_id': pid, 'file': _row_get(p, 'file'),
                'path': _row_get(p, 'path'),
                'taken_at': _row_get(p, 'taken_at'),
                'photo_kind': _row_get(p, 'photo_kind'),
                'time_src': _row_get(p, 'time_src'),
                'thumb': '/thumb/%s' % pid, 'full': '/img/%s' % pid,
                'batch_id': _row_get(p, 'batch_id'),
                'group_idx': _row_get(p, 'group_idx'),
                'carton_no': _row_get(p, 'carton_no'),
                'same_group': same_group,
                'gap_txt': gap_txt, 'reason': reason, 'score': score,
                'used_by': con.execute('SELECT COUNT(DISTINCT code_norm) FROM links '
                                       'WHERE photo_id=?', (pid,)).fetchone()[0],
            }

    if not cand:
        return []
    # 过滤（三条）：
    #   · 只要产品/包装/未知类 —— **label 是另一件货的标签照**，把它当全景推给
    #     别的产品，等于把甲的货挪到乙名下（真库抽样里这类噪音占了多数）；
    #   · 装箱单/场景照绝不进（同一口径 _cand_filter_sql）；
    #   · 人工已标「无关联」的跳过。
    rej = rejected_pairs(con)
    out = [c for c in cand.values()
           if (c['photo_kind'] or 'unknown') in ('product', 'packaging', 'unknown')
           and c['photo_kind'] not in ('packing_list', 'scene')
           and (cn, c['photo_id']) not in rej]
    out.sort(key=lambda c: (-c['score'], c['taken_at'] or ''))
    return out[:k]


def _dt(s):
    import datetime
    return datetime.datetime.fromisoformat(str(s))


def assign_batch_container(con, batch_id, container_id):
    """把批次改挂到另一个柜（迁移产生的「未分柜」补柜号后用）。

    两边都写：container_id 是真相，container_no 是冗余镜像。
    """
    _container_row(con, container_id)
    cno = con.execute('SELECT container_no FROM containers WHERE id=?',
                      (container_id,)).fetchone()['container_no']
    b = con.execute('SELECT id FROM batches WHERE id=?', (batch_id,)).fetchone()
    if b is None:
        raise ContainerError('批次不存在：%s' % batch_id)
    con.execute('UPDATE batches SET container_id=?, container_no=? WHERE id=?',
                (container_id, cno, batch_id))
    con.commit()
    return {'batch_id': batch_id, 'container_id': container_id,
            'container_no': cno}


def container_batches(con, container_id):
    return [dict(r) for r in con.execute(
        'SELECT * FROM batches WHERE container_id=? ORDER BY created_at DESC',
        (container_id,))]


# ═══════════════════════════════════════════════════════════════════
# 柜（一等实体，v3）
# ═══════════════════════════════════════════════════════════════════

class ContainerError(Exception):
    """柜相关操作失败（柜号重复 / 柜不存在 / 柜号为空）。routes 层转 400。"""


def _container_row(con, cid):
    r = con.execute('SELECT * FROM containers WHERE id=?', (cid,)).fetchone()
    if r is None:
        raise ContainerError('柜不存在：%s' % cid)
    return r


def create_container(con, container_no, **fields):
    """建柜。柜号是唯一标识，重复直接报 ContainerError（不静默合并）。"""
    no = (container_no or '').strip()
    if not no:
        raise ContainerError('柜号不能为空')
    if con.execute('SELECT 1 FROM containers WHERE container_no=?', (no,)).fetchone():
        raise ContainerError('柜号已存在：%s' % no)
    ts = now_iso()
    cid = uuid.uuid4().hex[:12]
    allowed = ('seal_no', 'arrival_at', 'departure_at', 'inspector',
               'location', 'product_name', 'client_name', 'remark')
    vals = {k: (fields.get(k) or None) for k in allowed}
    con.execute('INSERT INTO containers(id, container_no, seal_no, arrival_at,'
                ' departure_at, inspector, location, product_name, client_name,'
                ' remark, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (cid, no, vals['seal_no'], vals['arrival_at'], vals['departure_at'],
                 vals['inspector'], vals['location'], vals['product_name'],
                 vals['client_name'], vals['remark'], ts, ts))
    con.commit()
    return dict(con.execute('SELECT * FROM containers WHERE id=?', (cid,)).fetchone())


# 建柜表单里「不常变」的那几个字段（2026-10-09 老板需求：记住上次输入）
# ⚠️ 刻意**不含**柜号 / 封条号 / 到离柜时间 —— 这三个每次必变，
#    自动带入就是替用户猜，猜错比空着危险得多。
DEFAULT_FIELDS = ('client_name', 'inspector', 'location', 'product_name')


def container_form_defaults(con, recent_limit=8):
    """建柜表单预填数据：{last:{...}, recent:{字段:[...]}, from_container:柜号}

    🔴 **刻意不新增表、不新增配置文件、不落 localStorage**：
      「上次输入」= 最近一次建柜那条记录的取值。containers 表里本来就有这些
      列，再单独存一份就出现两份真源，而且必然漂移（用户事后改了柜信息，
      默认值还停在旧值上）。跟着 data\\ 走还有个好处：换浏览器、清缓存、
      换机器都不丢。

    [last]   最近一次建柜的取值（某字段当时留空 → 这里就是空，不擅自拿更早的填）。
    [recent] 各字段**用过的**取值，去重、最近优先 —— 客户/地点往往在少数几个
             固定值之间切换，只记「上一次」不够用；给个下拉比手打快，也不打错字。
    [from_container] 值的来源柜号。前端必须**明示**出来：自动带入要让人知道
             这是从哪来的、且随时能改（机器不许替用户猜业务）。
    """
    last = {k: '' for k in DEFAULT_FIELDS}
    recent = {k: [] for k in DEFAULT_FIELDS}
    src_no = ''
    # 柜是两位数~三位数级别，全量扫最省心；真到几千柜再改成分组 SQL
    # ⚠️ 必须带 rowid 兜底：`created_at` 只精确到**秒**，同一秒内建两个柜时
    # 时间戳完全相同，只按 created_at 排序的结果是**不确定的** —— 实测就取到了
    # 更早建的那个柜当「上次输入」（2026-10-09）。rowid 单调递增，同秒内后
    # 插入的更大，正好是「更近的那次」。
    for r in con.execute(
            'SELECT container_no, client_name, inspector, location, product_name'
            ' FROM containers ORDER BY created_at DESC, rowid DESC'):
        if not src_no:
            src_no = r['container_no'] or ''
            for k in DEFAULT_FIELDS:
                last[k] = r[k] or ''
        for k in DEFAULT_FIELDS:
            v = (r[k] or '').strip()
            if v and v not in recent[k] and len(recent[k]) < recent_limit:
                recent[k].append(v)
    return {'last': last, 'recent': recent, 'from_container': src_no,
            'fields': list(DEFAULT_FIELDS)}


WORK_SEG_DETAIL_MAX = 60
"""柜详情最多回传多少个作业段。「历史图片」那种兜底柜段数上百，
全传会把抽屉撑到几千行；这里取最近 N 段并把总数一起给前端（详情页写明
「只显示最近 60 段，共 N 段」）。"""

WORK_SEG_WIDE_SEC = 12 * 3600
"""单段跨度超过 12h 就不是「一个人连着拍了 12 小时」，而是数据本身零散
（实测「历史图片」柜里有一段跨 5 年：分组的 45s 窗口对兜底数据失效）。
命中的段标 wide，前端不显示该段耗时 —— 免得把数据问题说成作业强度。

🔴 曾用「段数>30 或 跨度>7 天」当零散判据，被真实库打回：那会把
EMCU9914616（138 段、跨 3 天、净作业 2.8h、全部 EXIF 可信）这种最正常的
多次作业柜也判成零散，7 个柜里 7 个中招，功能等于废了。**段数多/跨度大
本身是正常业务形态，只有「宽段」才是数据异常。**"""


def container_work_segments(con, cid, max_segments=0):
    """柜的**作业段**（2026-10-20 老板需求：每柜的作业时长/起止/耗时）。

    🔴 绝对不能直接对全柜照片取 MIN/MAX(taken_at) 当「作业时长」，真实库实测：
       · EMCU9914616 首末跨 3 天 → 334.7 小时，实际是多次进厂作业；
       · 「历史图片」兜底柜 3197 张跨 18 天 → 44855 小时，毫无意义；
       · MRSU* 四个柜照片 100% 是文件 mtime → 那个 9.6 分钟是**文件拷贝耗时**。

    所以按项目现成的连拍分组真源 (batch_id, group_idx) 切段（切分规则见
    regroup_photos_by_time），每段独立给起止/跨度/张数/可信度。跨度一律用
    **秒数**返回，格式化交给前端 fmtGap（两端已有同一套实现）。

    可信度经 pl_time_trusted 与 time_trustworthy 同源判定 —— 段里只要有
    一张不可信，整段就是不可信（宁可保守，不可给假证据）。

    max_segments>0 时只回最近 N 段（详情页折叠用）。
    """
    _register_time_fn(con)
    rows = con.execute(
        'SELECT MIN(p.taken_at) AS t_from, MAX(p.taken_at) AS t_to,'
        ' COUNT(*) AS n, MIN(pl_time_trusted(p.time_src, p.file)) AS ok'
        ' FROM photos p JOIN batches b ON b.id = p.batch_id'
        ' WHERE b.container_id=? AND p.is_dup=0 AND p.taken_at IS NOT NULL'
        ' GROUP BY p.batch_id, p.group_idx'
        ' ORDER BY t_from, p.batch_id, p.group_idx', (cid,)).fetchall()
    out = []
    for r in rows:
        t1, t2 = r['t_from'], r['t_to']
        try:
            span = int((_dt(t2) - _dt(t1)).total_seconds())
        except Exception:  # noqa: BLE001
            span = None
        out.append({'from': t1, 'to': t2, 'span_sec': span,
                    'n': r['n'], 'trusted': bool(r['ok']),
                    'wide': bool(span and span > WORK_SEG_WIDE_SEC)})
    if max_segments and len(out) > max_segments:
        out = out[-max_segments:]
    return out


def _merged_span(segs):
    """作业段区间的**并集**总秒数（段与段之间允许重叠）。

    🔴 不能把各段跨度简单相加：多批次的照片时间会交错重叠（补传、
    「历史图片」兜底柜跨多年），实测 MIEU2012616 相加得 1025.7h，
    比它自己的全程跨度 256.6h 还长 —— 那是算法错，不是数据怪。
    并集之后恒有「净作业 ≤ 全程跨度」。
    """
    iv = []
    for s in segs:
        if s.get('span_sec') is None:
            return None
        iv.append((_dt(s['from']), _dt(s['to'])))
    iv.sort()
    total = 0.0
    cs = ce = None
    for a, b in iv:
        if ce is None or a > ce:
            if ce is not None:
                total += (ce - cs).total_seconds()
            cs, ce = a, b
        elif b > ce:
            ce = b
    if ce is not None:
        total += (ce - cs).total_seconds()
    return int(total)


def work_summary(segs):
    """作业段 → 柜级汇总。列表列与详情页共用这一份口径。

    两个时长必须分开给，含义不同：
      span_sec  全程跨度（首段开始 → 末段结束，**含中途停工**）—— 回答
                「这个柜的事跨了几天」，跨天柜才看得出问题；
      active_sec 净作业时长（各段跨度之和）—— 回答「实际干了多久」。
    只显示前者，跨 3 天的柜会报出「作业 334 小时」的假结论。
    """
    segs = [s for s in segs if s.get('from') and s.get('to')]
    if not segs:
        return None
    segs = sorted(segs, key=lambda s: (s['from'], s['to']))
    first, last = segs[0]['from'], max(s['to'] for s in segs)
    try:
        span = int((_dt(last) - _dt(first)).total_seconds())
    except Exception:  # noqa: BLE001
        span = None
    active = _merged_span(segs)
    return {'segments': len(segs),
            'photos': sum(s.get('n') or 0 for s in segs),
            'from': first, 'to': last,
            'span_sec': span, 'active_sec': active,
            'trusted': all(s.get('trusted') for s in segs),
            'untrusted': sum(0 if s.get('trusted') else 1 for s in segs),
            'wide': sum(1 for s in segs if s.get('wide')),
            # 零散数据：含宽段时算出来的净作业时长没有业务含义（历史图片
            # 兜底柜算出来是 44855 小时），前端据此只显示首末与段数。
            'scattered': any(s.get('wide') for s in segs)}


def list_containers(con, keyword='', date_from='', date_to=''):
    """柜列表。带照片/清单/报告生成的可选进度。

    逐个柜聚合而不是一条大 JOIN —— 柜数量是两位数级别，可读性优先
    （与 batches_stats 同一取舍）。
    [date_from/date_to]（2026-10-18 老板需求 3）：按**作业日期**筛选 ——
    柜内照片的拍摄日期（taken_at，预检/监装都算）。闭开区间：
    from <= 日期 <= to（to 传日期当天包含）。
    """
    sql = 'SELECT * FROM containers'
    args = []
    if keyword:
        sql += " WHERE container_no LIKE ? OR IFNULL(seal_no,'') LIKE ?"
        args += ['%%%s%%' % keyword, '%%%s%%' % keyword]
    sql += ' ORDER BY container_no'
    out = []
    for r in con.execute(sql, args):
        d = dict(r)
        d['is_uncategorized'] = (d['container_no'] == schema.UNCATEGORIZED_NO)
        cid = d['id']
        d['checklist_batches'] = con.execute(
            "SELECT COUNT(*) FROM batches WHERE container_id=? AND kind='checklist'",
            (cid,)).fetchone()[0]
        d['photo_batches'] = con.execute(
            "SELECT COUNT(*) FROM batches WHERE container_id=? AND kind='photos'",
            (cid,)).fetchone()[0]
        d['checklist_rows'] = con.execute(
            'SELECT COUNT(*) FROM checklist_rows cr JOIN batches b ON b.id=cr.batch_id'
            ' WHERE b.container_id=?', (cid,)).fetchone()[0]
        d['photos'] = con.execute(
            'SELECT COUNT(*) FROM photos p JOIN batches b ON b.id=p.batch_id'
            ' WHERE b.container_id=? AND p.is_dup=0', (cid,)).fetchone()[0]
        d['supervision'] = con.execute(
            "SELECT COUNT(*) FROM photos p JOIN batches b ON b.id=p.batch_id"
            " WHERE b.container_id=? AND p.is_dup=0 AND p.photo_usage='监装'",
            (cid,)).fetchone()[0]
        # 作业时长（2026-10-20）：作业段汇总，**不受日期筛选影响**；
        # 筛选直接复用同一份起止，避免两套口径漂移。
        d['work'] = work_summary(container_work_segments(con, cid))
        if date_from or date_to:
            # 作业日期筛选：ISO 文本直接按字典序比较（taken_at 前 10 位是日期）
            lo = (date_from or '') and (date_from.replace('/', '-')[:10])
            hi = (date_to or '') and (date_to.replace('/', '-')[:10] + 'Z')
            w = d['work'] or {}
            lo_d = (w.get('from') or '')[:10]
            hi_d = (w.get('to') or '')[:10]
            if not lo_d or (lo and lo_d < lo) or (hi and hi_d > hi):
                continue
            d['work_date'] = lo_d
        out.append(d)
    return out


def update_container(con, cid, **fields):
    """改柜元数据。空字符串视为「清空」→ 写 NULL（与项目撤销语义一致）。"""
    cur = _container_row(con, cid)
    allowed = ('seal_no', 'arrival_at', 'departure_at', 'inspector',
               'location', 'product_name', 'client_name', 'remark')
    sets, args = [], []
    for k in allowed:
        if k in fields:
            v = (fields.get(k) or '').strip()
            sets.append('%s=?' % k)
            args.append(v or None)
    if not sets:
        return dict(cur)
    sets.append('updated_at=?')
    args.append(now_iso())
    args.append(cid)
    con.execute('UPDATE containers SET %s WHERE id=?' % ','.join(sets), args)
    con.commit()
    return dict(con.execute('SELECT * FROM containers WHERE id=?', (cid,)).fetchone())


def container_detail(con, cid):
    """柜详情聚合面板：元数据 + 批次 + 行数 + 照片统计 + 柜况候选图。

    这是柜详情页与报告页的**同一份数据源** —— 页面上写的
    「93 行 · 12 行未核对」与报告生成器吃的是它，数字不会漂。
    """
    d = dict(_container_row(con, cid))
    d['is_uncategorized'] = (d['container_no'] == schema.UNCATEGORIZED_NO)

    d['batches'] = [dict(r) for r in con.execute(
        'SELECT * FROM batches WHERE container_id=? ORDER BY created_at DESC', (cid,))]
    for b in d['batches']:
        b['stats'] = con.execute(
            'SELECT COUNT(*) total, SUM(CASE WHEN is_dup=0 THEN 1 ELSE 0 END) uniq'
            ' FROM photos WHERE batch_id=?', (b['id'],)).fetchone()
        b['stats'] = dict(b['stats'])
        b['rows'] = con.execute(
            'SELECT COUNT(*) FROM checklist_rows WHERE batch_id=?', (b['id'],)).fetchone()[0]

    # 清单行：总数 / 未核对（check_result 与 check_import 都空）
    d['row_total'] = con.execute(
        'SELECT COUNT(*) FROM checklist_rows cr JOIN batches b ON b.id=cr.batch_id'
        ' WHERE b.container_id=?', (cid,)).fetchone()[0]
    d['row_unchecked'] = con.execute(
        "SELECT COUNT(*) FROM checklist_rows cr JOIN batches b ON b.id=cr.batch_id"
        " WHERE b.container_id=? AND IFNULL(cr.check_result,'')=''"
        " AND IFNULL(cr.check_import,'')=''", (cid,)).fetchone()[0]

    # 照片统计（按 usage × tag 拆，柜况图与 Truck picture 从这里选）
    d['photo_stats'] = {r['photo_usage'] or '未分类': r['c'] for r in con.execute(
        'SELECT p.photo_usage, COUNT(*) c FROM photos p'
        ' JOIN batches b ON b.id=p.batch_id'
        ' WHERE b.container_id=? AND p.is_dup=0 GROUP BY p.photo_usage', (cid,))}
    d['supervision_tags'] = {r['supervision_tag'] or '未标注': r['c'] for r in con.execute(
        'SELECT p.supervision_tag, COUNT(*) c FROM photos p'
        ' JOIN batches b ON b.id=p.batch_id'
        " WHERE b.container_id=? AND p.is_dup=0 AND p.photo_usage='监装'"
        ' GROUP BY p.supervision_tag', (cid,))}
    # 柜况候选：每个 tag 取该柜下最新一张（报告区块④的代表图默认取它）
    d['condition_photos'] = {}
    for tag in schema.CONTAINER_CONDITION_TAGS:
        row = con.execute(
            'SELECT p.id, p.file, p.path, p.taken_at FROM photos p'
            ' JOIN batches b ON b.id=p.batch_id'
            " WHERE b.container_id=? AND p.supervision_tag=? AND p.is_dup=0"
            ' ORDER BY p.taken_at DESC, p.created_at DESC LIMIT 1', (cid, tag)).fetchone()
        d['condition_photos'][tag] = dict(row) if row else None

    # 作业时长明细（2026-10-20）：柜列表给的是汇总，这里给逐段起止/跨度/
    # 张数/可信度 —— 跨天柜必须能看出「分几次来的」，否则一个 334 小时的
    # 跨度没人敢信。work 与列表同源（work_summary），两处数字不会漂。
    segs = container_work_segments(con, cid)
    d['work_segments_total'] = len(segs)
    d['work_segments'] = segs[-WORK_SEG_DETAIL_MAX:]
    d['work'] = work_summary(segs)
    return d


def supervision_photos_of(con, cid):
    """④选图的「监装照片」候选：本柜 photo_usage='监装' 的全部照片按 tag 分组。

    报告里监装照分两个去处（schema.SUPERVISION_TAGS 的分工）：
      kind='cond'  柜况 4 槽位（报告④）—— 每类**一张**代表图，默认取最新
      kind='truck' 卡车 3 类（报告⑦）—— 全部进报告，人工可增删
    组内最新在前（taken_at DESC），第一张即「自动」默认 —— 前端不用再猜。
    不筛选 supervision_tag IS NULL：NULL 按归 'other'（报告口径一致，
    见 loading_report_data 的 IFNULL(...,'other')）。
    """
    _container_row(con, cid)      # 柜不存在 → ContainerError（与其他端点一致）
    rows = con.execute(
        'SELECT p.id, p.taken_at, IFNULL(p.supervision_tag,\'other\') AS tag'
        ' FROM photos p JOIN batches b ON b.id=p.batch_id'
        " WHERE b.container_id=? AND p.photo_usage='监装' AND p.is_dup=0"
        ' AND IFNULL(p.is_invalid,0)=0'
        ' ORDER BY p.taken_at DESC, p.id DESC', (cid,)).fetchall()
    groups = []
    for tag in schema.CONTAINER_CONDITION_TAGS + schema.TRUCK_PICTURE_TAGS:
        groups.append({
            'tag': tag,
            'label': schema.SUPERVISION_TAGS.get(tag, tag),
            'kind': 'cond' if tag in schema.CONTAINER_CONDITION_TAGS else 'truck',
            'items': [{'photo_id': r['id'], 'taken_at': r['taken_at']}
                      for r in rows if r['tag'] == tag],
        })
    return {'groups': groups, 'total': len(rows)}


def supervision_pending_of(con, cid):
    """③治理的「监装照片 · 细分确认」待办清单（按柜）。

    两类都要确认（老板 10-11：治理里没有地方快速确认监装细分 →
    ④选图里没有像样的监装照片可选）：
      A. 用途已是监装、但细分还没人工确认（没标 或 AI 建议没表态）
      B. 用途还没分类、但模型已给出细分建议 —— AI 看出了监装特征，
         只是 photo_usage 还没人拍板；确认细分前得先把用途标成监装
         （set_supervision_tag 会拒绝非监装照打细分，枚举校验兜底）。

    🔴 与 schema.py 的分工一致：supervision_tag 只认人工确认的值
    （AI 建议永不静默生效），所以这里返回的是「待人工表态」的清单，
    不是缺 tagged 的全部监装照 —— 已确认过的不回来烦人。
    """
    _container_row(con, cid)
    rows = con.execute(
        'SELECT p.id, p.taken_at, p.photo_usage, p.supervision_tag,'
        '       p.sup_tag_ai, p.sup_tag_ai_conf, p.sup_tag_ai_reason,'
        '       IFNULL(p.sup_tag_confirmed,0) AS confirmed'
        ' FROM photos p JOIN batches b ON b.id=p.batch_id'
        ' WHERE b.container_id=? AND p.is_dup=0 AND IFNULL(p.is_invalid,0)=0 AND ('
        "   (p.photo_usage='监装' AND IFNULL(p.sup_tag_confirmed,0)=0)"
        "    OR (IFNULL(p.photo_usage,'')='' AND p.sup_tag_ai IN (%s)))"
        ' ORDER BY p.taken_at DESC, p.id DESC'
        % ','.join('?' * len(schema.SUPERVISION_TAGS)),
        [cid] + list(schema.SUPERVISION_TAGS)).fetchall()
    items = [{'photo_id': r['id'], 'taken_at': r['taken_at'],
              'usage': r['photo_usage'] or '',
              'tag': r['supervision_tag'] or '',
              'ai_tag': (r['sup_tag_ai'] or '')
                        if (r['sup_tag_ai'] or '') in schema.SUPERVISION_TAGS else '',
              'ai_conf': r['sup_tag_ai_conf'],
              'ai_reason': r['sup_tag_ai_reason'] or '',
              } for r in rows]
    # tag→中文名由后端下发，前端不抄第二份（抄两份必然漂移）。
    return {'items': items, 'total': len(items),
            'labels': dict(schema.SUPERVISION_TAGS)}


def container_picks_stats(con, cid):
    """④选图的柜级统计：编码维度 + 照片维度，一次算完。

    🔴 口径必须与 `report_lookup` 的 `found` **同源** —— 否则统计条上的
    「命中」和下面检索列表里的「命中 N」必然对不上（铁律 23：
    提醒数字与详情必须同源）。lookup 判 found 的条件是：
      编码在 products 里存在 **且** 有关联照片（副本不算）。
    所以这里 `with_photo` 走 links JOIN photos 且 is_dup=0，一条不多一条不少。

    照片维度只算**本柜导入的**照片（batches.container_id 限定，is_dup=0）：
      photo_total  本柜照片张数
      photo_linked 其中已关联到编码的（= 命中照片）
      std_photos   其中已做成标准图的（= 命中标准图，含裁剪/上传两类）
    标准图按 src_photo_id 反查；手动上传那类 src_photo_id 是哨兵值
    （UPLOAD_SENTINEL，不是真实照片 id），不会被误当成照片命中。
    """
    codes = [r['cn'] for r in con.execute(
        'SELECT DISTINCT cr.code_norm AS cn FROM checklist_rows cr'
        ' JOIN batches b ON b.id=cr.batch_id'
        " WHERE b.container_id=? AND IFNULL(cr.code_norm,'')<>''", (cid,)).fetchall()]
    total = len(codes)
    in_lib = 0
    with_photo = 0
    for i in range(0, total, 400):
        chunk = codes[i:i + 400]
        qs = ','.join('?' * len(chunk))
        in_lib += con.execute(
            'SELECT COUNT(*) FROM products WHERE code_norm IN (%s)' % qs,
            chunk).fetchone()[0]
        with_photo += con.execute(
            'SELECT COUNT(DISTINCT l.code_norm) FROM links l'
            ' JOIN photos p ON p.id=l.photo_id'
            ' WHERE l.code_norm IN (%s) AND IFNULL(p.is_dup,0)=0' % qs,
            chunk).fetchone()[0]

    ph = con.execute(
        'SELECT COUNT(*) AS t,'
        ' SUM(CASE WHEN l.photo_id IS NOT NULL THEN 1 ELSE 0 END) AS linked,'
        ' SUM(CASE WHEN s.photo_id IS NOT NULL THEN 1 ELSE 0 END) AS std'
        ' FROM photos p JOIN batches b ON b.id=p.batch_id'
        ' LEFT JOIN (SELECT DISTINCT photo_id FROM links) l ON l.photo_id=p.id'
        ' LEFT JOIN (SELECT DISTINCT src_photo_id AS photo_id FROM standard_images'
        "            WHERE IFNULL(src_photo_id,'')<>'') s ON s.photo_id=p.id"
        ' WHERE b.container_id=? AND IFNULL(p.is_dup,0)=0', (cid,)).fetchone()

    photo_total = ph['t'] or 0
    return {
        'codes_total': total,
        'in_lib': in_lib,
        'with_photo': with_photo,
        'missing': max(total - with_photo, 0),
        'hit_rate': (round(100.0 * with_photo / total, 1) if total else 0.0),
        'photo_total': photo_total,
        'photo_linked': ph['linked'] or 0,
        'std_photos': ph['std'] or 0,
    }


def container_progress(con, cid):
    """向导五步就绪度 —— 唯一数据源（复用具象聚合，零 schema 改动）。

    状态**全部派生自数据**（行数 / 治理数 / 报告文件数），不记账。
    返回 steps: 每步 {done, summary, sub, 数字字段}，以及 ready_pct。
    """
    import os
    from tools.productlib import paths as _paths

    d = container_detail(con, cid)
    cno = d['container_no']
    is_unc = d['is_uncategorized']

    # ① 建柜
    meta_fields = ['seal_no', 'inspector', 'client_name', 'location']
    meta_missing = [f for f in meta_fields if not (d.get(f) or '').strip()]
    c_done = not is_unc

    # ② 导入清单
    row_total = d['row_total']
    row_unchecked = d['row_unchecked']
    checklist_batches = sum(1 for b in d['batches'] if b['kind'] == 'checklist')
    cl_done = row_total > 0

    # ③ 导入照片
    photo_total = con.execute(
        'SELECT COUNT(*) FROM photos p JOIN batches b ON b.id=p.batch_id'
        " WHERE b.container_id=? AND p.is_dup=0", (cid,)).fetchone()[0]
    photo_batches = sum(1 for b in d['batches'] if b['kind'] == 'photos')
    precheck = d['photo_stats'].get('预检', 0)
    supervision = d['photo_stats'].get('监装', 0)
    ph_done = photo_total > 0

    # ④ 照片治理 + 新产品确认
    g = con.execute(
        'SELECT govern_state, COUNT(*) c FROM photos p'
        ' JOIN batches b ON b.id=p.batch_id'
        " WHERE b.container_id=? AND p.is_dup=0 GROUP BY govern_state", (cid,)).fetchall()
    g = {r['govern_state'] or 'pending': r['c'] for r in g}
    govern_total = sum(g.values())
    govern_done = g.get('done', 0) + g.get('skipped', 0)
    govern_pending = g.get('pending', 0)
    govern_failed = g.get('failed', 0)
    govern_linked = con.execute(
        'SELECT COUNT(DISTINCT l.photo_id) FROM links l'
        ' JOIN photos p ON p.id=l.photo_id'
        ' JOIN batches b ON b.id=p.batch_id WHERE b.container_id=?', (cid,)).fetchone()[0]
    review_pending = 0
    if not is_unc:
        codes = [r[0] for r in con.execute(
            'SELECT DISTINCT cr.code_norm FROM checklist_rows cr'
            ' JOIN batches b ON b.id=cr.batch_id WHERE b.container_id=?'
            " AND IFNULL(cr.code_norm,'')<>''", (cid,)).fetchall()]
        if codes:
            qs = ','.join('?' * len(codes))
            review_pending = con.execute(
                'SELECT COUNT(*) FROM products WHERE review_state<>?'
                ' AND code_norm IN (%s)' % qs, ['confirmed'] + codes).fetchone()[0]
    gov_done = (govern_total > 0 and govern_pending == 0 and govern_failed == 0)

    # ⑤ 生成报告（报告文件从文件名 CNTR#<柜号> 解析，零表）
    files = 0
    last_at = None
    if not is_unc:
        rdir = _paths.reports_dir()
        if os.path.isdir(rdir):
            import re as _re
            pat = _re.compile(r'CNTR#%s' % _re.escape(cno))
            for fn in os.listdir(rdir):
                if fn.lower().endswith('.docx') and pat.search(fn):
                    files += 1

    ready_pct = ((20 if c_done else 0) + (15 if cl_done else 0) +
                 (15 if ph_done else 0) + (25 if gov_done else 0) +
                 (25 if files > 0 else 0))

    steps = {
        'container': {
            'done': c_done,
            'summary': schema.container_label(cno) if not is_unc else '未建柜',
            'sub': ('封条 %s' % d.get('seal_no')) if d.get('seal_no') else '缺封条号',
            'meta_missing': meta_missing,
        },
        'checklist': {
            'done': cl_done, 'summary': '%d 行' % row_total,
            'sub': '未核对 %d' % row_unchecked,
            'row_total': row_total, 'row_unchecked': row_unchecked,
            'batches': checklist_batches,
        },
        'photos': {
            'done': ph_done, 'summary': '%d 张' % photo_total,
            'sub': '%d 批次 · 监装 %d' % (photo_batches, supervision),
            'total': photo_total, 'batches': photo_batches,
            'precheck': precheck, 'supervision': supervision,
        },
        'govern': {
            'done': gov_done, 'summary': '%d/%d 已治理' % (govern_done, govern_total),
            'sub': '待确认 %d · 失败 %d' % (govern_pending, govern_failed),
            'total': govern_total, 'done_cnt': govern_done,
            'pending': govern_pending, 'failed': govern_failed,
            'linked': govern_linked, 'review_pending': review_pending,
        },
        'report': {
            'done': files > 0,
            'summary': ('已生成 %d 份' % files) if files else '未生成',
            'files': files, 'last_at': last_at,
        },
        # ④选图是唯一的**客户端**步骤（后端不存采用状态），这里只下发柜级统计，
        # 口径与 report_lookup 同源。放进 progress 是为了让老板一进④就看见
        # 总数/缺口/占比，不必先点一次检索才知道要补多少。
        'picks': {
            'done': False,
            'stats': container_picks_stats(con, cid),
        },
    }
    return {'container_id': cid, 'container_no': cno, 'is_uncategorized': is_unc,
            'meta_missing': meta_missing, 'steps': steps, 'ready_pct': ready_pct}



# ═══════════════════════════════════════════════════════════════════
# 产品（第 1 条：编码唯一标识 + 清单导入校验）
# ═══════════════════════════════════════════════════════════════════

class ProductError(Exception):
    pass


def validate_product(row):
    """按 schema.PRODUCT_FIELDS 校验一行产品数据。

    返回 (clean_dict, errors)。errors 非空则该行不应入库。
    """
    clean = {}
    errors = []
    for fname, cname, required, _desc in schema.PRODUCT_FIELDS:
        v = BL._cell(row.get(fname))
        clean[fname] = v
        if required and not v:
            errors.append('%s不能为空' % cname)

    code = clean.get('code', '')
    if code:
        n = BL.normalize(code)
        if len(n) < 4:
            errors.append('编码太短（归一化后 %d 位，要求 ≥4）' % len(n))
        if not re.search(r'\d', n):
            errors.append('编码必须含数字（当前「%s」）' % code)
        clean['code_norm'] = n
    else:
        clean['code_norm'] = ''
    return clean, errors


def upsert_products(con, rows, batch_id=None, replace=False):
    """批量导入产品。

    返回 (added, updated, errors)。

    ⚠️ 同编码重复导入的行为必须明确：**默认合并（更新空字段），不是覆盖**。
    实测同一批货在清单与报关单里各出现一次，字段互补（清单有英文品名、
    报关单有中文描述）。覆盖会丢信息。

    [replace]=True 时才整体覆盖 —— 仅用于"这份清单是权威源"的场景。
    """
    added = updated = 0
    errors = []
    ts = now_iso()
    for i, raw in enumerate(rows, 1):
        clean, errs = validate_product(raw)
        if errs:
            errors.append({'line': i, 'code': raw.get('code', ''), 'errors': errs})
            continue
        cn = clean['code_norm']
        exist = con.execute('SELECT * FROM products WHERE code_norm=?', (cn,)).fetchone()
        if exist is None:
            con.execute(
                'INSERT INTO products(code_norm,code,name,spec,unit,brand,material,'
                'category,remark,review_state,source_batch,created_at,updated_at)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (cn, clean['code'], clean['name'], clean['spec'], clean['unit'],
                 clean['brand'], clean['material'], clean['category'], clean['remark'],
                 'confirmed', batch_id, ts, ts))
            added += 1
            # 🔴 新增产品**也必须**记 product_batch（2026-10-10 老板报「柜号下拉
            #    筛出 0 件」的根因之一）：此前 continue 跳到关联写入之前，清单
            #    导入的新产品从不过 product_batch → 首次导入的柜在
            #    _container_filter_sql 主路上永远查不到（没照片链接时整柜 0 件）。
            if batch_id:
                con.execute('INSERT OR IGNORE INTO product_batch(code_norm,batch_id,created_at)'
                            ' VALUES (?,?,?)', (cn, batch_id, ts))
            # ⚠️ 必须 continue —— 新增行没有旧值可 merge。
            #    漏了会掉进下面的 merge 分支读 exist[k] → TypeError。
            continue
        # 无论新增还是已存在，都记录产品↔批次关联（多对多，同一产品可在多个柜号出现）
        if batch_id:
            con.execute('INSERT OR IGNORE INTO product_batch(code_norm,batch_id,created_at)'
                        ' VALUES (?,?,?)', (cn, batch_id, ts))
        else:
            if replace:
                fields = {k: clean[k] for k in
                          ('code', 'name', 'spec', 'unit', 'brand',
                           'material', 'category', 'remark')}
            else:
                # 合并：新值非空才覆盖，空值保留旧的
                fields = {}
                for k in ('code', 'name', 'spec', 'unit', 'brand',
                          'material', 'category', 'remark'):
                    fields[k] = clean[k] if clean[k] else (exist[k] or '')
            sets = ','.join('%s=?' % k for k in fields)
            con.execute('UPDATE products SET %s,updated_at=? WHERE code_norm=?'
                        % sets, (*fields.values(), ts, cn))
            updated += 1
    con.commit()
    return added, updated, errors


def import_checklist_file(con, path, batch_name=None, replace=False,
                          container_id=None, container_no=None):
    """从 xls/xlsx 导入产品清单。

    复用 `build_library.parse_checklist`（已用真实清单验证过：表头自动定位、
    NOTE 行跳过、箱号向下填充、数字型编码去尾零），再做字段规范校验。

    ⚠️ 2026-10-05 v3：container_id **必填**（无柜不导，闸门在后端）。
    传了 container_no 但没给 container_id 时，按柜号找/建柜（兼容旧调用方，
    但推荐显式传 id —— 「先建柜」是流程的第一步，不该由导入函数代劳）。

    落两处：
      · products       —— 合并视图（归一化编码唯一），供关联/检索
      · checklist_rows —— **原行快照**，供装柜报告的 Packing list
    两者的行数不同是设计如此（90 行 → 53 个产品），报告要的是前者。
    """
    if not container_id:
        if container_no:
            c = con.execute('SELECT id FROM containers WHERE container_no=?',
                            (str(container_no).strip(),)).fetchone()
            container_id = c['id'] if c else create_container(
                con, container_no)['id']
        else:
            raise ContainerError('请先选择柜（container_id 必填）')
    _container_row(con, container_id)

    items, meta = BL.parse_checklist(path)
    merged = BL.merge_items(items)
    bid = uuid.uuid4().hex[:12]
    cno = con.execute('SELECT container_no FROM containers WHERE id=?',
                      (container_id,)).fetchone()['container_no']
    con.execute('INSERT INTO batches(id,kind,name,container_no,note,item_count,'
                'created_at,container_id) VALUES (?,?,?,?,?,?,?,?)',
                (bid, 'checklist', batch_name or os.path.basename(path),
                 cno, json.dumps(meta, ensure_ascii=False), len(merged),
                 now_iso(), container_id))
    rows = []
    for m in merged:
        rows.append({
            'code': m['code'],
            'name': m.get('name', ''),
            'spec': m.get('spec', ''),
            'unit': '',
            'brand': '',
            'material': '',
            'category': '',
            # 箱号信息不丢 —— 它是复盘"整箱有没有拍到"的关键维度
            'remark': ('箱号：%s' % m['container_summary']) if m.get('container_summary') else '',
        })
    added, updated, errors = upsert_products(con, rows, batch_id=bid, replace=replace)
    # 原行快照（报告用）。**同码多行各自一行** —— 报告里那是不同的件。
    n_snap = save_checklist_rows(con, bid, items)
    recalc_product_counts(con)
    return {
        'batch_id': bid,
        'container_id': container_id,
        'parsed': len(merged),
        'snap_rows': n_snap,
        'added': added,
        'updated': updated,
        'errors': errors,
        'meta': meta,
    }


def save_checklist_rows(con, batch_id, items):
    """把清单**原行**写进 checklist_rows（报告 Packing list 的数据源）。

    为什么原样落库而不是只留合并后的 products：
    真实清单里 `216070000001` 连着 3 行 = 3 件货，报告要出 3 行；
    而 products 是归一化编码唯一的合并视图（3 行 → 1 条，qty 累加）。
    只存合并结果，报告的总数量就会和清单对不上 —— 这类错在报告上很难看出来。

    数量列存文本（`12` / `12.0` / "12 PCS" 都照抄），求和放在报告生成时做。
    重复导入同柜清单 = 先删该批旧行再写（清单是权威快照，不叠加）。
    """
    con.execute('DELETE FROM checklist_rows WHERE batch_id=?', (batch_id,))
    ts = now_iso()
    n = 0
    for it in items:
        con.execute(
            'INSERT OR REPLACE INTO checklist_rows(batch_id,seq,code,code_norm,'
            'name,spec,package_no,order_qty,loading_qty,check_import,created_at'
            ') VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (batch_id, it['seq'], it['code'], it['code_norm'],
             it.get('name') or None, it.get('spec') or None,
             (it.get('package_no') or '').strip() or None,
             (it.get('order_qty') or '').strip() or None,
             (it.get('loading_qty') or '').strip() or None,
             (it.get('check_result') or '').strip() or None, ts))
        n += 1
    con.commit()
    return n


def set_row_check(con, batch_id, seq, result, loading_qty=None, by='user'):
    """人工核对：Loading Qty + Quantity Check result（报告 Packing list 那两列）。

    ⚠️ 绝不在这里自动写 PASS：机器能判的只有"有没有照片"，那是覆盖率
    不是数量核对结论。result 空 = 标回「未核对」，报告沿用清单预填的
    check_import —— 两列都空则报告该格留空。

    [loading_qty] 传 None 表示不动这一列（区分「不改」与「清空」）。
    """
    row = con.execute('SELECT * FROM checklist_rows WHERE batch_id=? AND seq=?',
                      (batch_id, int(seq))).fetchone()
    if row is None:
        raise ContainerError('清单行不存在：%s#%s' % (batch_id, seq))
    result = (result or '').strip() or None
    if loading_qty is None:
        con.execute('UPDATE checklist_rows SET check_result=?, taken_at=?, taken_by=?'
                    ' WHERE batch_id=? AND seq=?',
                    (result, now_iso(), by, batch_id, int(seq)))
    else:
        con.execute('UPDATE checklist_rows SET check_result=?, loading_qty=?,'
                    ' taken_at=?, taken_by=? WHERE batch_id=? AND seq=?',
                    (result, (str(loading_qty).strip() or None), now_iso(), by,
                     batch_id, int(seq)))
    con.commit()
    return dict(con.execute('SELECT * FROM checklist_rows WHERE batch_id=? AND seq=?',
                            (batch_id, int(seq))).fetchone())


def set_supervision_tag_bulk(con, photo_ids, tag, by='user'):
    """批量打标签的显式别名（与单张同一个实现，语义上更清楚）。"""
    return set_supervision_tag(con, photo_ids, tag, by=by)


def checklist_rows_of(con, batch_id):
    return [dict(r) for r in con.execute(
        'SELECT * FROM checklist_rows WHERE batch_id=? ORDER BY seq', (batch_id,))]


# ═══════════════════════════════════════════════════════════════════
# 照片（第 2 条：批量上传）
# ═══════════════════════════════════════════════════════════════════

_CARTON_FROM_PATH = ('预检', 'PRECIS', 'precheck')


def carton_from_relpath(path, root=''):
    """从相对路径里提取箱号 —— App 交付包是 `预检/{箱号}/照片.jpg`。

    为什么需要：App（零改动）把预检照片按**人指定的箱号**分文件夹，
    那是交付分目录的唯一依据。照片导进产品库时如果只认 `carton_map`
    人工映射，区块⑥的图注 `{编码}-{描述}-{箱号}` 会永远缺第三段。

    规则：路径里第一个形如 `预检/<目录>/` 的 `<目录>` 即箱号；
    找不到返回 None（**不猜** —— 猜错箱号比缺箱号更坏，它会写进报告）。
    目录名形如 `_未分箱` / `_未使用` 的按"没箱号"处理。
    """
    rel = os.path.relpath(path, root) if root else path
    parts = [p for p in rel.replace('\\', '/').split('/') if p]
    for i, p in enumerate(parts):
        if p in _CARTON_FROM_PATH and i + 1 < len(parts):
            cand = parts[i + 1].strip()
            if cand and not cand.startswith('_'):
                return cand
    return None


def _rel_under(path, root):
    """照片的库内标识：相对导入根的路径，统一用 `/` 分隔。

    存相对路径而不是 basename 的理由见 add_photos 里的注释（同名即丢照片）。
    出了根目录（`../x.jpg`）退化成 basename —— 那种路径本来就不该有。
    """
    try:
        rel = os.path.relpath(path, root) if root else path
    except ValueError:            # Windows: 跨盘符 relpath 会抛
        rel = os.path.basename(path)
    rel = rel.replace('\\', '/')
    if rel.startswith('../'):
        rel = os.path.basename(rel)
    return rel


def _dup_key_map(photos, root):
    """basename(dup_of) → 相对路径。

    `scan_photos` 的去重是按 basename 记 `dup_of` 的，而入库改用相对路径 ——
    不映射的话 dup_of 会指向一个库里不存在的 file（同批同名的另一张），
    「重复件」就变成了「指向空气的指针」。
    """
    out = {}
    for ph in photos:
        if ph.get('dup_of'):
            out.setdefault(ph['dup_of'], _rel_under(ph['path'], root))
    return out


def add_photos(con, folder, batch_name=None, storage_dir=None, container_id=None,
               carton_map=None, root=''):
    """把一个目录下的照片批量导入图片库。

    [storage_dir]：若指定，照片**复制**到该目录（产品库自持文件）；
                   为 None 则只记录原路径（原地引用，源目录不能被挪走）。

    默认原地引用 —— 复制 900MB 的照片进仓库不是好主意，且源文件
    本来就该被当作只读资产。只有"源目录是临时位置"时才用 storage_dir。

    ⚠️ 2026-10-05 v3：container_id **必填**（无柜不导）。
    [carton_map] 人工映射优先于路径自动提取（人工是最高优先级）。
    """
    if not container_id:
        raise ContainerError('请先选择柜（container_id 必填）')
    _container_row(con, container_id)

    photos, groups, stats = BL.scan_photos(folder, verbose=False)
    bid = uuid.uuid4().hex[:12]
    ts = now_iso()
    cno = con.execute('SELECT container_no FROM containers WHERE id=?',
                      (container_id,)).fetchone()['container_no']
    con.execute('INSERT INTO batches(id,kind,name,container_no,note,item_count,'
                'created_at,container_id) VALUES (?,?,?,?,?,?,?,?)',
                (bid, 'photos', batch_name or os.path.basename(folder),
                 cno, json.dumps(stats, ensure_ascii=False), len(photos), ts,
                 container_id))

    added = skipped = 0
    # ⚠️ 2026-10-05 修一个会**静默丢照片**的缺陷。
    #
    # 现象：App 交付包是 `预检/{箱号}/x.jpg` + `监装/x.jpg` 两棵目录树，
    # 而 photos.file 存的是 **basename** 且有 UNIQUE 约束 → 同名文件第二张
    # 直接 IntegrityError 被 `skipped += 1` 吞掉。App 相机文件名是秒级
    # 时间戳（`P_20260927_101234.jpg`），跨目录撞名概率很高，监装/预检同名更是
    # 常态。实测：4 张入库 2 张，报告里只说"跳过 2 张"，没人知道丢的是哪张。
    #
    # 改法：file 存**相对导入根的路径**（`预检/箱A/P_00.jpg`）。天然唯一、
    # 可追溯，展示时还多带箱号信息；读图一直走 `path`（绝对路径），不受影响。
    dup_map = _dup_key_map(photos, folder)
    for ph in photos:
        pid = uuid.uuid4().hex[:12]
        path = ph['path']
        _abs_for_hash = path          # 归一前的绝对路径（dhash 要真开文件）
        rel = _rel_under(ph['path'], folder)
        if storage_dir:
            os.makedirs(storage_dir, exist_ok=True)
            dst = os.path.join(storage_dir, os.path.basename(rel))
            if not os.path.exists(dst):
                import shutil
                shutil.copy2(ph['path'], dst)
            path = dst
        elif not os.path.abspath(folder).lower().startswith(
                os.path.abspath(_data_root(con)).lower() + os.sep):
            # 便携化（2026-10-18 老板问题 1）：源目录在 data 根**之外**时，
            # 把照片拷进 data/origin/{源目录名}/ 并存相对路径 —— 包拷到
            # U盘/别的机器照片跟着走，源目录之后清理也不影响。
            # 源目录已在 data 内（现场习惯：先放 data/origin/柜号/ 再导入）
            # 则不拷贝，直接存相对路径。
            import shutil as _sh
            _sub = os.path.basename(folder.rstrip('\\/')) or 'imported'
            _dst_dir = os.path.join(paths.data_dir(), 'origin', _sub)
            _dst = os.path.join(_dst_dir, *rel.split('/'))
            os.makedirs(os.path.dirname(_dst), exist_ok=True)
            if not os.path.exists(_dst):
                _sh.copy2(ph['path'], _dst)
            path = _dst
        # 统一归一：文件在库根之内 → path 存相对形态（便携）
        _relp = photo_rel_path(path)
        if _relp and os.path.exists(
                os.path.join(_data_root(con), *_relp.split('/'))):
            path = _relp
        try:
            carton = (carton_map or {}).get(ph['file'])
            if not carton:
                carton = carton_from_relpath(ph['path'], root or folder)
            dup_of = dup_map.get(ph['dup_of']) if ph['dup_of'] else None
            con.execute(
                'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,'
                'md5,is_dup,dup_of,group_idx,govern_state,created_at,carton_no,phash)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (pid, rel, path, bid, ph['taken_at'].isoformat(),
                 ph.get('time_src'), ph['bytes'], ph['md5'],
                 1 if dup_of else 0, dup_of, ph['group_idx'],
                 'pending', ts, carton, dhash_of(_abs_for_hash)))
            added += 1
        except sqlite3.IntegrityError:
            # file 唯一冲突 = 这张已经在库里了（同一批交付重复导入）
            skipped += 1
    # 修正批次 item_count 为实际导入数；若全部重复则删除空批次
    if added == 0:
        con.execute('DELETE FROM batches WHERE id=?', (bid,))
        con.commit()
        return {'batch_id': None, 'added': 0, 'skipped': skipped, 'stats': stats,
                'all_duplicate': True}
    con.execute('UPDATE batches SET item_count=? WHERE id=?', (added, bid))
    con.commit()
    return {'batch_id': bid, 'added': added, 'skipped': skipped, 'stats': stats}


def scan_standard_folder(root):
    """扫描标准采集文件夹格式：{任意目录}/预检/{箱号}/照片.jpg + {任意目录}/监装/照片.jpg
    返回 [(src_dir, carton_no, full_path, usage), ...]

    🔴 2026-10-06 老板定口径：**一切柜号以 web 端输入的柜号为准。**
    所以这里第一个返回值**不是柜号**，只是「照片来自哪个顶层目录」——
    仅用于批次命名/让人看懂来源，**绝不用于建柜或挂批次**。
    目录名可能叫柜号、也可能叫别的（App 交付目录、日期、随便什么），
    拿它当柜号就会出现「照片挂到 A 柜、清单在 B 柜」的错位。

    ⚠️ 监装目录**必须**一起扫 —— 监装照是装柜报告区块④⑦的原料，
    只扫预检的话报告永远缺柜况图/卡车图，而且没人会注意到
    （导入是成功的，只是少了照片 —— 静默丢数据比报错恶劣得多）。

    支持根目录直接是照片根，或根目录下有多个这样的子目录。
    优先读取 manifest.json 获取箱号元数据。
    """
    import os, json
    results = []
    root = os.path.abspath(root)

    IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')

    def _is_container_dir(d):
        return (os.path.isdir(os.path.join(d, '预检'))
                or os.path.isdir(os.path.join(d, '监装')))

    # 收集照片根：根目录本身可能就是，或根目录下有多个
    container_dirs = []
    if _is_container_dir(root):
        container_dirs.append((os.path.basename(root.rstrip(os.sep)) or '根目录', root))
    else:
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d) and _is_container_dir(d):
                container_dirs.append((name, d))

    for src_dir, cdir in container_dirs:
        # 尝试读取 manifest.json（在照片根或上级目录）
        manifest = None
        for mf in [os.path.join(cdir, 'manifest.json'), os.path.join(root, 'manifest.json')]:
            if os.path.isfile(mf):
                try:
                    with open(mf, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    break
                except Exception:
                    pass

        # 从 manifest 构建 fileName -> carton 映射
        carton_by_file = {}
        if manifest:
            for item in manifest.get('unmatched', []):
                fn = item.get('fileName', '')
                carton = item.get('carton')
                if fn and carton:
                    # fileName 格式：预检/箱号/文件名，取最后一段作为文件名
                    basename = os.path.basename(fn)
                    carton_by_file[basename] = carton

        # ① 预检：{柜}/预检/{箱号}/照片.jpg
        precheck_dir = os.path.join(cdir, '预检')
        if os.path.isdir(precheck_dir):
            for carton_name in sorted(os.listdir(precheck_dir)):
                carton_dir = os.path.join(precheck_dir, carton_name)
                if not os.path.isdir(carton_dir):
                    continue
                for fname in sorted(os.listdir(carton_dir)):
                    if not fname.lower().endswith(IMG_EXT):
                        continue
                    full = os.path.join(carton_dir, fname)
                    carton = carton_by_file.get(fname, carton_name)
                    results.append((src_dir, carton, full, '预检'))

        # ② 监装：{柜}/监装/照片.jpg（App 交付的是平铺目录，无箱号）
        supervise_dir = os.path.join(cdir, '监装')
        if os.path.isdir(supervise_dir):
            for fname in sorted(os.listdir(supervise_dir)):
                full = os.path.join(supervise_dir, fname)
                if not os.path.isfile(full) or not fname.lower().endswith(IMG_EXT):
                    continue
                results.append((src_dir, '', full, '监装'))

    return results


def _ensure_container(con, container_no, note=''):
    """按柜号找柜，没有就建。**仅供 CLI/脚本/迁移用**，Web 导入路径不走它。

    Web 端导入一律用 _require_container（柜必须先由人建）。
    保留这个函数是给命令行批处理和迁移脚本用的 —— 那两个场景没有界面。
    """
    no = (container_no or '').strip()
    if not no:
        raise ContainerError('请先选择柜（container_no 为空）')
    row = con.execute('SELECT id FROM containers WHERE container_no=?', (no,)).fetchone()
    if row:
        return row['id']
    return create_container(con, no, remark=note)['id']


def _require_container(con, container_no, root=''):
    """取柜 id；柜不存在则报错，**绝不自动建**（2026-10-06 老板指正）。

    「柜号是主线，必须先建柜才能进后续流程」—— 目录名带柜号也不例外。
    凭空的柜子没有封条号/到离柜时间/Inspector，等于制造一个残缺的数据源。
    """
    no = (container_no or '').strip()
    if not no:
        raise ContainerError('无法识别柜号：请先到「柜」页新建一个柜')
    row = con.execute('SELECT id FROM containers WHERE container_no=?', (no,)).fetchone()
    if row:
        return row['id']
    raise ContainerError(
        '目录名是柜号「%s」，但柜还不存在。\n'
        '请先到「柜」页新建这个柜（填上封条号、到离柜时间、检查员），'
        '再来导入照片 —— 柜是流程的第一步，照片要挂在它下面。%s'
        % (no, ('\n（识别自目录：%s）' % root) if root else ''))


def import_standard_folder(con, root, storage_dir=None, container_id=None):
    """按标准采集格式导入照片：{任意目录}/预检/{箱号}/照片.jpg + {任意目录}/监装/

    🔴 **柜号一律取 [container_id]（界面上选的柜）**，目录名只当"来源目录"
    用来命名批次。老板口径（2026-10-06）：一切柜号以 web 端输入的柜号为准。
    照片记录箱号与用途（预检/监装 —— 中文枚举，与 PHOTO_USAGES / 报告查询
    同一口径）。返回导入结果汇总。
    """
    import os
    items = scan_standard_folder(root)
    if not items:
        return {'added': 0, 'containers': [],
                'error': '未找到标准格式照片（期望 .../预检/{箱号}/ 与 .../监装/）'}

    # 🔴 v3.2（2026-10-06 老板定口径）：**一切柜号以 web 端输入的柜号为准。**
    #   src_dir 只是「照片来自哪个顶层目录」（可能叫柜号、也可能叫日期/
    #   App 交付目录/任意名字），仅用于批次命名和来源可追溯，
    #   **绝不用于建柜、也绝不用于挂批次**。
    #   之前拿目录名当柜号，会出现「照片挂到 A 柜、清单在 B 柜」的错位，
    #   而且目录名一旦与真实柜号不符，错误会静默传播到整份报告。
    #   分组只为「批次命名/去重判断」，最终都挂到 cid 这一个柜。
    by_src = {}
    for src_dir, carton, full_path, usage in items:
        by_src.setdefault(src_dir, []).append((carton, full_path, usage))

    total_added = 0
    total_skipped = 0
    container_results = []
    src_dir_names = sorted(by_src.keys())
    dir_note = ('（照片目录：%s）' % '、'.join(src_dir_names[:3])
                + (' 等 %d 个' % len(src_dir_names) if len(src_dir_names) > 3 else ''))

    for src_dir in src_dir_names:
        photo_items = by_src[src_dir]
        # 柜只认 container_id（界面上选的那个）—— 目录名不参与。
        cid = (container_id or '').strip() or None
        if not cid:
            raise ContainerError('请先在界面上选择柜 —— 照片要挂在柜下面，'
                                 '程序不认目录名当柜号')
        if not con.execute('SELECT 1 FROM containers WHERE id=?', (cid,)).fetchone():
            raise ContainerError('选择的柜不存在或已被删除，请在「柜」页重新选一个')
        row = con.execute('SELECT container_no FROM containers WHERE id=?',
                          (cid,)).fetchone()
        container_no = row['container_no']

        # 临时目录：把所有照片路径传给 add_photos
        # add_photos 接受 folder 参数，扫描目录下的照片。
        # 标准格式照片分散在不同箱号目录，需要用一个特殊方式处理。
        # 最简单：直接调用底层逻辑，逐个插入。
        # 但 add_photos 内部用 BL.scan_photos(folder) 扫描。
        # 我们改为：创建批次，然后直接插入照片记录。

        from datetime import datetime
        import hashlib
        from PIL import Image

        ts = datetime.now().isoformat(timespec='seconds')
        bid = 'ph_' + hashlib.md5((src_dir + container_no + ts).encode()).hexdigest()[:12]

        # ⚠️ 判重按**来源目录**（批次名带 src_dir），不能按柜号 ——
        #    现在多个来源目录都挂到同一个柜（柜号以界面选择为准），
        #    按柜号判重会把第二个目录整批当成"重复"吃掉，静默少导照片。
        existing = con.execute(
            'SELECT id, name FROM batches WHERE container_id=? AND kind=?'
            ' AND name=?',
            (cid, 'photos', f'标准采集-{src_dir}')).fetchone()
        if existing:
            # 该来源目录已导过，检查是否有照片
            cnt = con.execute('SELECT COUNT(*) FROM photos WHERE batch_id=?',
                              (existing['id'],)).fetchone()[0]
            if cnt > 0:
                container_results.append({
                    'container_no': container_no,
                    'src_dir': src_dir,
                    'added': 0, 'skipped': len(photo_items),
                    'batch_id': existing['id'],
                    'all_duplicate': True,
                    'note': '该照片目录已导入过（同名批次「%s」已有照片）' % existing['name']
                })
                total_skipped += len(photo_items)
                continue

        # 创建批次
        con.execute(
            'INSERT INTO batches(id,kind,name,container_no,item_count,created_at,'
            'container_id) VALUES (?,?,?,?,?,?,?)',
            (bid, 'photos', f'标准采集-{src_dir}', container_no,
             len(photo_items), ts, cid))

        added = 0
        skipped = 0
        for carton, full_path, usage in photo_items:
            try:
                with open(full_path, 'rb') as f:
                    data = f.read()
                md5 = hashlib.md5(data).hexdigest()
                # 检查重复（按 md5 + 路径）
                # ⚠️ 必须**加上路径**：两个来源目录里可能各有一张内容相同但
                #    路径不同的照片（同一柜的两批交付、或测试/重拍场景）。
                #    只按 md5 全库判重会把它们当同一张，于是第二个目录整批
                #    被"重复"吃掉 —— 照片数静默变少，用户看不出来（踩到过）。
                #    真正该跳过的只有「同一文件被重复导」：那必然是同一路径。
                dup = con.execute('SELECT id FROM photos WHERE md5=? AND path=?',
                                  (md5, full_path)).fetchone()
                if dup:
                    skipped += 1
                    continue
                # 读取图片尺寸 + EXIF 拍摄时间兜底
                try:
                    with Image.open(full_path) as img:
                        w, h = img.size
                except Exception:
                    w, h = None, None
                # 从文件名提取拍摄时间（格式：YYYYMMDD_HHMMSS_序号.jpg）
                taken_at = None
                basename = os.path.basename(full_path)
                parts = basename.replace('.jpg', '').replace('.jpeg', '').replace('.png', '').split('_')
                if len(parts) >= 2 and len(parts[0]) == 8 and len(parts[1]) == 6:
                    try:
                        taken_at = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}T{parts[1][:2]}:{parts[1][2:4]}:{parts[1][4:6]}"
                    except Exception:
                        pass
                if not taken_at:
                    # 文件名没有时间 → 读 EXIF DateTimeOriginal（用户手机拍的监装照
                    # 常常是原生命名，没有 App 的时间戳命名）
                    try:
                        with Image.open(full_path) as img:
                            ex = img.getexif()
                            dt = ex.get(36867) or ex.get(306)
                            if dt:
                                t = str(dt).strip().replace(' ', 'T', 1)
                                if len(t) >= 16:
                                    taken_at = t[:19]
                    except Exception:
                        pass
                pid = 'p_' + hashlib.md5((full_path + ts).encode()).hexdigest()[:16]
                # file 列有 UNIQUE 约束：预检/监装两个目录可能出现同名文件
                # （App 按时间序号命名通常不撞，但用户手动整理过的包会撞）。
                # 同名且同 md5 上面已经跳过；走到这里说明是**两张不同的照片**，
                # 用「用途_箱号_」前缀改名，绝不能静默吞掉监装照。
                stored_name = basename
                if con.execute('SELECT 1 FROM photos WHERE file=?', (stored_name,)).fetchone():
                    prefix = (carton or usage) + '_'
                    stored_name = prefix + basename
                    i = 2
                    while con.execute('SELECT 1 FROM photos WHERE file=?',
                                      (stored_name,)).fetchone():
                        stored_name = prefix + ('%d_' % i) + basename
                        i += 1
                con.execute(
                    'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,width,height,group_idx,govern_state,created_at,carton_no,photo_usage,import_seq)'
                    ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (pid, stored_name, full_path, bid, taken_at,
                     'exif' if (taken_at and not (len(parts) >= 2 and len(parts[0]) == 8)) else 'filename',
                     len(data), md5, w, h, None, 'pending', ts, carton or None,
                     usage if usage in schema.PHOTO_USAGES else None, added))
                added += 1
            except Exception as e:
                skipped += 1
                continue

        if added == 0:
            con.execute('DELETE FROM batches WHERE id=?', (bid,))
            con.commit()
            container_results.append({
                'container_no': container_no,
                'src_dir': src_dir,
                'added': 0, 'skipped': skipped,
                'batch_id': None, 'all_duplicate': True
            })
        else:
            con.execute('UPDATE batches SET item_count=? WHERE id=?', (added, bid))
            con.commit()
            # 🔴 group_idx 必须**真分组**，不能是插入序号。
            # 2026-10-19 事故：这里原来直接写 `added`（自增），于是每个 App
            # 交付包里每张照片自成一组（实测 1285 组全是 1 张）—— 抽屉里的
            # 「同组连拍」永远空、组视图也退化成单张，老板看得见的功能是死的。
            # 现在按「同目录（箱号）+ 拍摄时间间隔」聚类，与 regroup 同口径。
            try:
                regroup_photos_by_time(con, batch_id=bid, dry_run=False)
            except Exception as e:  # noqa: BLE001
                # 分组失败不能把已经导进去的照片弄丢 —— 但要留下痕迹，
                # 绝不静默（照片在、组没了，是全表 group_idx=NULL 的静默降级）。
                print('[WARN] 分组失败 batch=%s: %s' % (bid, e))
            container_results.append({
                'container_no': container_no,
                'src_dir': src_dir,
                'added': added, 'skipped': skipped,
                'batch_id': bid, 'all_duplicate': False
            })
        total_added += added
        total_skipped += skipped

    real_cno = None
    if container_results:
        real_cno = container_results[0]['container_no']
    # 目录名与所选柜号不一致时要**明说** —— 用户很可能以为导到同名柜了。
    mismatch = ([c['src_dir'] for c in container_results
                 if c.get('src_dir') and c['src_dir'] != real_cno])
    return {'added': total_added, 'skipped': total_skipped,
            'containers': container_results, 'total_found': len(items),
            'container_id': container_id, 'container_no': real_cno,
            'src_dirs': src_dir_names,
            'dir_note': dir_note,
            'dir_mismatch': mismatch}


def set_govern(con, photo_id, state, kind=None, kind_conf=None,
               desc=None, codes=None, model=None, error=None, meta=None, usage=None,
               sup_tag=None, sup_tag_conf=None, sup_tag_reason=None):
    """写治理结果。

    🔴 sup_tag* 三件套是监装细分的**建议**，不是定论 —— 只写 sup_tag_ai* 列，
    绝不碰 supervision_tag（报告只认那一列）。
    「重新治理」会让模型重新给建议，这本来就是想要的行为；人工确认过的
    值由 sup_tag_confirmed 标记保护，UI 上会显示「已确认」并保留人工的值。
    """
    con.execute(
        'UPDATE photos SET govern_state=?,photo_kind=?,kind_conf=?,vision_desc=?,'
        'vision_codes=?,vision_meta=?,vision_model=?,govern_error=?,govern_at=?,'
        'photo_usage=COALESCE(?, photo_usage),'
        'sup_tag_ai=?,sup_tag_ai_conf=?,sup_tag_ai_reason=? WHERE id=?',
        (state, kind, kind_conf, desc,
         json.dumps(codes, ensure_ascii=False) if codes else None,
         json.dumps(meta, ensure_ascii=False) if meta else None,
         model, error, now_iso(), usage,
         sup_tag, sup_tag_conf, sup_tag_reason, photo_id))


def add_tokens(con, photo_id, tokens):
    ts = now_iso()
    con.execute('DELETE FROM ocr_tokens WHERE photo_id=?', (photo_id,))
    for t in tokens:
        con.execute('INSERT INTO ocr_tokens(photo_id,raw_text,confidence,created_at)'
                    ' VALUES (?,?,?,?)',
                    (photo_id, t.get('t') or t.get('raw_text', ''),
                     t.get('c') or t.get('confidence', 0.0), ts))
    con.commit()


# ═══════════════════════════════════════════════════════════════════
# 关联（第 3、4 条：自动 + 手动）—— 唯一写入口
# ═══════════════════════════════════════════════════════════════════

def link(con, code_norm, photo_id, source, confidence=None,
         evidence=None, created_by='system'):
    """建立关联。**唯一的写入口**。

    手动关联必须传 created_by（人），自动关联记 'system'。
    这样将来能回答"这条对应关系是谁认定的"。

    兜底归一化：调用方传来的可能是原始字面值（如 CodeIndex.best 返回的
    原始 code、用户手输），这里统一 normalize —— links.code_norm 必须与
    products.code_norm 同一形态，否则 JOIN 落空、关联"消失"。
    """
    code_norm = BL.normalize(code_norm)
    ts = now_iso()
    con.execute(
        'INSERT OR REPLACE INTO links(code_norm,photo_id,source,confidence,'
        'evidence,created_at,created_by) VALUES (?,?,?,?,?,?,?)',
        (code_norm, photo_id, source, confidence, evidence, ts, created_by))
    # 人工关联 = 老板改主意了。清掉同对的「无关联」否决，否则旧否决会
    # 把这张照片继续挡在候选之外 —— 他明明刚亲手关联了它。
    # 只清人工这一路：自动关联绝不能走到这里（它自己就被否决挡着）。
    if created_by not in ('system', None):
        con.execute('DELETE FROM cand_reject WHERE code_norm=? AND photo_id=?',
                    (code_norm, photo_id))
    recalc_product_counts(con)
    return True


def unlink(con, code_norm, photo_id):
    cn = BL.normalize(code_norm)
    cur = con.execute('DELETE FROM links WHERE code_norm=? AND photo_id=?',
                      (cn, photo_id))
    # 同时清掉同对的「无关联」否决（10-05）。
    # 理由：老板先否过 → 又亲手关联了 → 现在又解除，这串动作说明他已经
    # 改了主意。留着否决的话，解除后这张照片**不回候选**（它被否决挡着），
    # 于是「关联 → 解除」这个最常见的操作变成了不可逆的单向门。
    con.execute('DELETE FROM cand_reject WHERE code_norm=? AND photo_id=?',
                (cn, photo_id))
    con.commit()
    recalc_product_counts(con)
    return cur.rowcount


def clear_auto_links(con, batch_id=None, pending_only=False):
    """删除自动关联（auto_ocr / auto_vision），保留人工关联。

    [batch_id]：只清该照片批次的自动关联。按批次重新治理时**必须**传 ——
    否则会把其它批次的 auto links 也清掉，而那些照片不在本次重算范围，
    关联丢了就没人补回来。人工关联是老板点的，任何情况都不碰。
    [pending_only]=True（2026-10-18「跳过已关联」配套）：只清**当前 pending**
    照片的自动关联 —— 重新治理选择跳过已关联照片时，被跳过照片的
    自动关联必须保留（它们不在重跑集合里，清了没人补回来）。
    必须在 reset UPDATE **之后**调用：此时 pending 集合恰为「本次要重跑的」。
    """
    extra = ''
    args = []
    if batch_id:
        extra += ' AND batch_id=?'
        args.append(batch_id)
    if pending_only:
        extra += " AND govern_state='pending'"
    if pending_only or batch_id:
        cur = con.execute(
            "DELETE FROM links WHERE source LIKE 'auto_%' AND photo_id IN"
            ' (SELECT id FROM photos WHERE is_dup=0' + extra + ')', args)
    else:
        cur = con.execute("DELETE FROM links WHERE source LIKE 'auto_%'")
    con.commit()
    recalc_product_counts(con)
    return cur.rowcount


def recalc_product_counts(con):
    """重算每个产品的图片数。

    ⚠️ 口径与 verify_library.py 的 A4 一脉相承：
       photo_count = 全部关联（含人工）
       auto_count  = 自动关联数
       manual_count= 人工关联数
    全部由 links 现算，不手工维护 —— 手工维护的计数一定会漂移。
    """
    con.execute('UPDATE products SET photo_count=0,auto_count=0,manual_count=0')
    for r in con.execute('SELECT code_norm,source,COUNT(*) n FROM links GROUP BY code_norm,source'):
        if r['source'] == 'manual':
            col = 'manual_count'
        else:
            col = 'auto_count'
        con.execute('UPDATE products SET %s=%s+? WHERE code_norm=?' % (col, col),
                    (r['n'], r['code_norm']))
    con.execute('UPDATE products SET photo_count=auto_count+manual_count')
    con.commit()


# ═══════════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════════

def _cand_filter_sql(alias=''):
    """候选照片的通用过滤条件：**只有产品图**能当候选（2026-10-17 老板规则）。

    列表的「N 待关」计数与详情的候选区**必须共用这一条**。口径不一致的
    表现很坑人：表格写着「1 待关」，点开详情却一张都没有。

    白名单口径（与 _UNLINKED_SQL 同源）：只有 label=0201（有编码）/
    product=0202（无编码）进候选。曾经是黑名单（排除装箱单/场景照，
    NULL 放行）—— 那会让「其他预检/未识别」的照片也带着读出的编码来
    扰人工；老板规则是「只有产品需要关联」，直接收成白名单，未识别的
    治理归为产品图后自然进队。加上无效照片（2026-10-12）排除：拍糊的
    图读出来的编码本来就不该信。
    """
    a = (alias + '.') if alias else ''
    return ('%sis_dup=0 AND IFNULL(%sis_invalid,0)=0 '
            'AND IFNULL(%sphoto_kind,\'\') IN (\'label\',\'product\') '
            'AND IFNULL(%sphoto_usage,\'\')<>\'监装\' '
            'AND IFNULL(%sphoto_ignored,0)=0'
            % (a, a, a, a, a))


# ═══════════════════════════════════════════════════════════════════
# 柜号解析（2026-10-07）—— 产品库筛选的唯一真源
# ═══════════════════════════════════════════════════════════════════
#
# 🔴 老板报「筛选的『全部柜号』没有所有的柜号」。根因：柜号解析散在**三处**
#    各写一份 SQL，且三份都只认 `batches.container_no` —— 那是 v3 之前的
#    **冗余列**，早已停止维护。真实库实测：
#      · 22 个批次里 13 个 container_no IS NULL → 产品直接漏在统计外；
#      · 未分柜被算成两行：`_UNCATEGORIZED` 524 件，而它 container_no 为 NULL
#        的那 634 行一条都没进来（真值 781）；
#      · 三档筛选之和 1051 ≠ 不筛选总数 786 —— 互相重叠且对不上，
#        「全部柜号」根本没覆盖全库。
#
# 口径（顺序即优先级）：
#   ① container_id → containers.container_no（柜实体，权威；柜由人建）
#   ② batches.container_no 直接相等（**老库兜底**：可能没挂 container_id，
#      只按 ① 查会让这批产品凭空消失）
# 两路都保留，取并集。四段分别覆盖「清单侧」与「照片关联侧」，
# 与历史口径一致，避免筛选结果口径变窄。

_CONTAINER_PARAMS = 4          # 下面片段里的 ? 个数（改的时候数对）


def _container_filter_sql(code_col='p.code_norm'):
    """返回 (sql片段, 参数个数)。用法：sql += ' AND '+frag，args += [no]*n。

    list_products / count_products 必须共用它 —— 两份各写一遍必然漂移
    （列表显示 100 条、翻页总数却是 80 这种）。
    """
    c = code_col
    frag = ('(' + c + ' IN (SELECT pb.code_norm FROM product_batch pb'
            ' JOIN batches b ON b.id=pb.batch_id'
            ' JOIN containers ct ON ct.id=b.container_id'
            ' WHERE ct.container_no=?)'
            ' OR ' + c + ' IN (SELECT pb2.code_norm FROM product_batch pb2'
            ' JOIN batches b2 ON b2.id=pb2.batch_id'
            ' WHERE (b2.container_id IS NULL OR TRIM(IFNULL(b2.container_id,\'\'))=\'\')'
            ' AND b2.container_no=?)'
            ' OR ' + c + ' IN (SELECT l.code_norm FROM links l'
            ' JOIN photos ph ON ph.id=l.photo_id'
            ' JOIN batches b ON b.id=ph.batch_id'
            ' JOIN containers ct ON ct.id=b.container_id'
            ' WHERE ct.container_no=?)'
            ' OR ' + c + ' IN (SELECT l2.code_norm FROM links l2'
            ' JOIN photos ph2 ON ph2.id=l2.photo_id'
            ' JOIN batches b2 ON b2.id=ph2.batch_id'
            ' WHERE (b2.container_id IS NULL OR TRIM(IFNULL(b2.container_id,\'\'))=\'\')'
            ' AND b2.container_no=?))')
    return frag, _CONTAINER_PARAMS


def _container_list_sql(code_col='p.code_norm'):
    """产品行上「这个产品属于哪些柜」的聚合表达式（供列表显示柜号列）。

    同样四路 UNION，与筛选口径保持一致 —— 显示的柜号和筛得到的柜号
    必须对得上，否则用户会看到「这行写着 A 柜，却筛不出它」。
    """
    c = code_col
    return ('(SELECT GROUP_CONCAT(container_no) FROM ('
            ' SELECT ct.container_no FROM product_batch pb2'
            ' JOIN batches b2 ON b2.id=pb2.batch_id'
            ' JOIN containers ct ON ct.id=b2.container_id'
            ' WHERE pb2.code_norm=' + c + ' AND ct.container_no IS NOT NULL'
            ' UNION'
            ' SELECT b2.container_no FROM product_batch pb2'
            ' JOIN batches b2 ON b2.id=pb2.batch_id'
            ' WHERE pb2.code_norm=' + c + ' AND b2.container_no IS NOT NULL'
            ' UNION'
            ' SELECT ct3.container_no FROM links l3'
            ' JOIN photos ph3 ON ph3.id=l3.photo_id'
            ' JOIN batches b3 ON b3.id=ph3.batch_id'
            ' JOIN containers ct3 ON ct3.id=b3.container_id'
            ' WHERE l3.code_norm=' + c + ' AND ct3.container_no IS NOT NULL'
            ' UNION'
            ' SELECT b3.container_no FROM links l3'
            ' JOIN photos ph3 ON ph3.id=l3.photo_id'
            ' JOIN batches b3 ON b3.id=ph3.batch_id'
            ' WHERE l3.code_norm=' + c + ' AND b3.container_no IS NOT NULL'
            ' ) _cl) AS container_list')


def list_products(con, keyword=None, only_with_photos=None,
                 only_without_standard=None, limit=200, offset=0,
                 sort='code', container_no=None, only_cand=None):
    """[only_cand]: None 全部 / 'any' 有待确认 / 'code' 有读码候选 /
                    'group' 有同组待确认 —— 与列表角标同一份 cand_counts()。

    返回的 cand_count 保留（= code + group，老字段），另加 cand_code /
    cand_group 两个细分字段：前端要分开显示，因为两类证据强度完全不同
    —— 读码是照片里真读出了这个编码，同组只是跟已关联照片连拍在一起。
    """
    # 候选计数：一次算全库（带缓存），再按筛选条件取 code 集合
    cnts = cand_counts(con)

    def _ok(cn):
        c = cnts.get(cn)
        if not c:
            return False
        if only_cand == 'any':
            return (c['code'] or 0) + (c['group'] or 0) > 0
        if only_cand == 'code':
            return (c['code'] or 0) > 0
        if only_cand == 'group':
            return (c['group'] or 0) > 0
        return True

    sql = ('SELECT p.*, EXISTS(SELECT 1 FROM standard_images si'
           ' WHERE si.code_norm = p.code_norm) AS has_standard,'
           + _container_list_sql('p.code_norm') +
           ' FROM products p WHERE 1=1')
    args = []
    if keyword:
        k = BL.normalize(keyword)
        sql += ' AND (code_norm LIKE ? OR name LIKE ?)'
        args += ['%%%s%%' % k, '%%%s%%' % keyword]
    if only_with_photos:
        sql += ' AND photo_count > 0'
    elif only_with_photos is False:
        sql += ' AND photo_count = 0'
    if only_without_standard:
        sql += ' AND has_standard = 0'
    if container_no:
        frag, n = _container_filter_sql('p.code_norm')
        sql += ' AND ' + frag
        args += [container_no] * n
    if only_cand:
        cands = [cn for cn, c in cnts.items()
                 if _ok(cn)]
        if not cands:
            return []
        sql += ' AND p.code_norm IN (%s)' % ','.join('?' * len(cands))
        args += cands
    if sort == 'gap':
        # 缺口优先：没照片的排最前 → 有照片但没标准图的其次 → 其余按编码
        sql += ' ORDER BY (photo_count>0) ASC, has_standard ASC, code_norm'
    else:
        sql += ' ORDER BY code_norm'
    sql += ' LIMIT ? OFFSET ?'
    args += [limit, offset]
    rows = con.execute(sql, args).fetchall()
    # 候选计数拼回去（Row 不可改，统一转成 dict 返回 —— 调用方本来就用 r['x']）
    out = []
    for r in rows:
        d = dict(r)
        cn = d.get('code_norm')
        cc = cnts.get(cn) or {'code': 0, 'group': 0}
        d['cand_code'] = cc['code']
        d['cand_group'] = cc['group']
        d['cand_count'] = cc['code'] + cc['group']
        # 柜号列：逐个过一遍显示口径（`_UNCATEGORIZED` → 未分柜），
        # 空值也给个明确说法，别让那一格看起来像"没柜号也没数据"
        cl = [x for x in (d.get('container_list') or '').split(',') if x.strip()]
        d['container_list'] = ','.join(
            schema.container_label(x, empty='') for x in cl) if cl else ''
        out.append(d)
    if sort == 'cand':
        out.sort(key=lambda d: (-d['cand_count'], d.get('code_norm') or ''))
    return out


def count_products(con, keyword=None, only_with_photos=None,
                   only_without_standard=None, container_no=None,
                   only_cand=None):
    """与 list_products 完全相同的过滤条件，只数总数（分页用）。"""
    cnts = cand_counts(con) if only_cand else None
    if only_cand:
        def _ok(c):
            if only_cand == 'any':
                return (c['code'] or 0) + (c['group'] or 0) > 0
            if only_cand == 'code':
                return (c['code'] or 0) > 0
            return (c['group'] or 0) > 0
        cands = [cn for cn, c in cnts.items() if _ok(c)]
        if not cands:
            return 0
    sql = 'SELECT COUNT(*) FROM products p WHERE 1=1'
    args = []
    if only_cand:
        sql += ' AND p.code_norm IN (%s)' % ','.join('?' * len(cands))
        args += cands
    if keyword:
        k = BL.normalize(keyword)
        sql += ' AND (code_norm LIKE ? OR name LIKE ?)'
        args += ['%%%s%%' % k, '%%%s%%' % keyword]
    if only_with_photos:
        sql += ' AND photo_count > 0'
    elif only_with_photos is False:
        sql += ' AND photo_count = 0'
    if only_without_standard:
        sql += (' AND NOT EXISTS(SELECT 1 FROM standard_images si'
                ' WHERE si.code_norm = p.code_norm)')
    if container_no:
        frag, n = _container_filter_sql('p.code_norm')
        sql += ' AND ' + frag
        args += [container_no] * n
    return con.execute(sql, args).fetchone()[0]


def product_containers(con):
    """产品库「柜号」下拉的唯一来源：**containers 表（柜实体）全量**。

    🔴 2026-10-07 老板报「筛选的『全部柜号』没有所有的柜号」。这里原来 JOIN
    的是 `batches.container_no` —— v3 之前的**冗余列**，早已停止维护：
      · 22 个批次里 13 个 container_no IS NULL → 产品漏在统计外；
      · 未分柜被算成两行：`_UNCATEGORIZED` 524 件，而它 container_no 为 NULL
        的那 634 行一条都没进来（真值 781）；
      · 三档之和 1051 ≠ 总数 786，「全部柜号」根本没覆盖全库。

    现在口径 = 柜实体表为准，与 `_container_filter_sql` 同一套解析：
      · 按 container_id → containers.container_no 统计产品/批次数；
      · 再补一批「只有 container_no、没挂 container_id」的老批次（兜底，
        直接改成纯 container_id 关联会让这批产品凭空消失）；
      · 🔴 **把一个产品都没有的空柜也列出来**：柜是人工建的，用户想查
        「这个柜为什么一件都没有」时，下拉里得能找到那个柜。空柜沉底但不消失。

    返回 [{container_no, label, products, batches}]，按产品数降序。
    """
    agg = {}

    def _row(container_no, products, batches):
        cno = (container_no or '').strip()
        if not cno:
            return None
        d = agg.get(cno)
        if d is None:
            d = {'container_no': cno, 'products': 0, 'batches': 0}
            d['label'] = schema.container_label(cno)
            agg[cno] = d
        # 两路命中同一个柜号时取 max，不相加 —— 相加会把同一批产品重复计数
        d['products'] = max(d['products'], products or 0)
        d['batches'] = max(d['batches'], batches or 0)
        return d

    # ① 主路：柜实体（权威）
    for r in con.execute(
            'SELECT ct.container_no AS container_no,'
            ' COUNT(DISTINCT pb.code_norm) AS products,'
            ' COUNT(DISTINCT pb.batch_id) AS batches'
            ' FROM product_batch pb'
            ' JOIN batches b ON b.id = pb.batch_id'
            ' JOIN containers ct ON ct.id = b.container_id'
            ' GROUP BY ct.container_no'):
        _row(r['container_no'], r['products'], r['batches'])
    # ② 兜底：老库批次没挂 container_id，只有冗余列
    for r in con.execute(
            'SELECT b.container_no AS container_no,'
            ' COUNT(DISTINCT pb.code_norm) AS products,'
            ' COUNT(DISTINCT pb.batch_id) AS batches'
            ' FROM product_batch pb'
            ' JOIN batches b ON b.id = pb.batch_id'
            ' WHERE (b.container_id IS NULL OR TRIM(IFNULL(b.container_id,\'\'))=\'\')'
            '   AND b.container_no IS NOT NULL AND TRIM(b.container_no) != \'\''
            ' GROUP BY b.container_no'):
        _row(r['container_no'], r['products'], r['batches'])
    # ③ 空柜也要在（products=0），否则「这个柜怎么一件都没有」没法查
    for r in con.execute('SELECT container_no FROM containers'):
        _row(r['container_no'], 0, 0)

    out = list(agg.values())
    # 有产品的排前面（多的优先），空柜沉底 —— 但**不许消失**
    out.sort(key=lambda d: (-(d['products'] or 0), d['container_no']))
    return out


def product_photos(con, code_norm):
    """第 5 条：一个产品的所有预检采集图片。"""
    return con.execute(
        'SELECT p.*, l.source, l.confidence, l.evidence, l.created_by AS link_by'
        ' FROM links l JOIN photos p ON p.id = l.photo_id'
        ' WHERE l.code_norm=? ORDER BY p.taken_at', (code_norm,)).fetchall()


def product_photos_grouped(con, code_norm):
    """产品照片 + 批次视角：哪些批次有图、哪些批次没图。

    「整箱拍没拍全」的答案就在这里 —— 缺的批次列出来，不用人去对。
    """
    items = product_photos(con, code_norm)
    # sqlite3.Row 没有 .get()，只能用下标取值（photos 表必有 batch_id 列）
    have = {r['batch_id'] for r in items if r['batch_id']}
    allb = con.execute(
        "SELECT id, name, kind, created_at FROM batches WHERE kind='photos'"
        ' ORDER BY created_at').fetchall()
    batches = [dict(b) for b in allb]
    missing = [b for b in batches if b['id'] not in have]
    return items, batches, missing


def unlinked_photos(con, limit=60, offset=0, exclude_kinds=()):
    """第 4 条：未被关联的照片（人工关联工作台的数据源）。

    [exclude_kinds]：这些分类不进工作台。比如 packing_list（物料清单）是参考文档，
    本就不该关联产品，放进工作台只会污染人工认领队列。
    2026-10-16：photo_usage='监装' 的照片同样不进（监装不关联产品，
    与未关联选项卡同一口径 _UNLINKED_SQL）。
    """
    sql = ('SELECT * FROM photos p WHERE ' + _UNLINKED_SQL
           + ' AND COALESCE(manual_skip,0)=0')
    args = []
    if exclude_kinds:
        ph = ','.join('?' * len(exclude_kinds))
        sql += ' AND photo_kind NOT IN (%s)' % ph
        args += list(exclude_kinds)
    sql += ' ORDER BY govern_state, taken_at LIMIT ? OFFSET ?'
    args += [limit, offset]
    return con.execute(sql, args).fetchall()


def set_photo_skip(con, photo_id, skip=True, by='user'):
    """人工标注时「这张不关联」→ 持久记住，不再回待认领队列。

    与 links 无关：跳过的是照片本身（场景照/糊的/认不出），
    不是「不关联某个编码」。撤销即回到队列。
    """
    cur = con.execute(
        'UPDATE photos SET manual_skip=?, skip_at=?, skip_by=? WHERE id=?',
        (1 if skip else 0, now_iso() if skip else None,
         by if skip else None, photo_id))
    con.commit()
    return cur.rowcount


def set_photo_usage(con, photo_id, usage, by='user'):
    """设置单张照片的用途分类（监装/预检/空=清除）。"""
    usage = (usage or '').strip() or None
    if usage and usage not in schema.PHOTO_USAGES:
        raise ValueError('用途只能是：%s' % ' / '.join(schema.PHOTO_USAGES.keys()))
    cur = con.execute('UPDATE photos SET photo_usage=? WHERE id=?', (usage, photo_id))
    con.commit()
    return cur.rowcount


def set_batch_usage(con, batch_id, usage, by='user'):
    """批量设置一个照片批次下所有照片的用途分类。"""
    usage = (usage or '').strip() or None
    if usage and usage not in schema.PHOTO_USAGES:
        raise ValueError('用途只能是：%s' % ' / '.join(schema.PHOTO_USAGES.keys()))
    cur = con.execute('UPDATE photos SET photo_usage=? WHERE batch_id=?', (usage, batch_id))
    con.commit()
    return cur.rowcount


def set_photo_ignored(con, photo_ids, ignored=1, by='user'):
    """批量标记/恢复「本次忽略」（2026-10-18 老板需求）。

    忽略 = 这张照片本次不关联（新产品先不入库），退出待关联/候选/新产品
    确认等一切关联队列；数据保留，「已忽略」选项卡可查看与恢复。
    与 is_invalid（照片本身坏）是两回事 —— 忽略的照片后续柜的清单导入
    仍可能被 relink 自动捞回关联（忽略只管本次的待办队列）。
    幂等：重复标记同一状态返回 0（SQLite 的 rowcount 对同值 UPDATE 也返回
    匹配行数，所以先 SELECT 出真正需要变更的行再 UPDATE）。
    """
    ids = [str(i) for i in (photo_ids or []) if i]
    if not ids:
        return 0
    ignored = 1 if ignored else 0
    ts = now_iso()
    n = 0
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        cur_ids = [r[0] for r in con.execute(
            'SELECT id FROM photos WHERE id IN (%s)'
            ' AND IFNULL(photo_ignored,0)<>?' % ','.join('?' * len(chunk)),
            chunk + [ignored])]
        if not cur_ids:
            continue
        cur = con.execute(
            'UPDATE photos SET photo_ignored=?, ignored_at=?, ignored_by=?'
            ' WHERE id IN (%s)' % ','.join('?' * len(cur_ids)),
            [ignored, ts if ignored else None, by if ignored else None] + cur_ids)
        n += cur.rowcount
    con.commit()
    return n


def set_photo_kinds(con, photo_ids, kind, by='user'):
    """人工改照片分类（photo_kind）—— 2026-10-15 老板需求。

    模型识别不是百分百准（清单/产品/场景/包装/标识卡会判错），必须给人工
    一个兜底入口。语义三条：
      1. 分类只认 schema.PHOTO_KINDS 的枚举值，传空/未识别值落到 unknown；
      2. 人工选定后把 kind_conf 置 NULL —— 那是**模型的置信度**，人拍的板
         不再挂模型的分数（UI 上也不用再显示「模型判定 xx%」）；
      3. 原始文件与 vision_* 原始输出一律不动（识别结果留痕，可复现）。
    """
    kind = (kind or '').strip()
    if kind and kind not in schema.PHOTO_KINDS:
        raise ValueError('分类只能是：%s' % ' / '.join(schema.PHOTO_KINDS))
    kind = kind or 'unknown'
    ids = [str(i) for i in (photo_ids or []) if i]
    if not ids:
        return 0
    n = 0
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        cur = con.execute(
            'UPDATE photos SET photo_kind=?, kind_conf=NULL WHERE id IN (%s)'
            % ','.join('?' * len(chunk)), [kind] + chunk)
        n += cur.rowcount
    con.commit()
    return n


def set_photos_invalid(con, photo_ids, invalid, by='user'):
    """批量标记/撤销「无效照片」（2026-10-12 老板需求）。

    无效 = 拍糊、误拍、与作业无关的照片。语义三条：
      1. **只写标记，永不删文件** —— 原始照片是取证证据，is_invalid 只是
         工作队列的口径收窄（列表/候选/选图默认排除它）。
      2. 支持一次多张（网格多选批量操作），返回实际更新张数。
      3. invalid_at/invalid_by 留痕（谁在什么时候标的），撤销时清空 ——
         与 manual_skip 同一套留痕习惯。
    """
    ids = [p for p in (photo_ids or []) if p]
    if not ids:
        return 0
    flag = 1 if invalid else 0
    total = 0
    for i in range(0, len(ids), 400):     # IN 参数分批（SQLite 变量上限）
        chunk = ids[i:i + 400]
        qs = ','.join('?' * len(chunk))
        cur = con.execute(
            'UPDATE photos SET is_invalid=?, invalid_at=?, invalid_by=?'
            ' WHERE id IN (%s)' % qs,
            [flag, now_iso() if flag else None, (by if flag else None)] + chunk)
        total += cur.rowcount
    con.commit()
    return total


def auto_invalid_candidates(con, container_id):
    """清单/包装照清理名单（2026-10-15 需求2）：系统识别、用户确认、批量无效。

    口径：本柜 + 分类是 packing_list / packaging + 未标无效 + **未关联**。
    清单/包装照是老板明确说「用户都当无效图」的两类；但**已关联的不进
    名单** —— 有人手动关联过说明另有打算，系统不替人做主。
    返回 {total, linked_n, ids, preview}；preview 给前端摸缩略图（截 60 张，
    确认时按 ids 全量提交 —— 列表只是让人看，不是选择范围）。
    """
    base = ('FROM photos p JOIN batches b ON b.id=p.batch_id '
            'WHERE b.container_id=? AND IFNULL(p.is_invalid,0)=0 '
            "AND p.photo_kind IN ('packing_list','packaging')")
    ids = [r['id'] for r in con.execute(
        'SELECT p.id ' + base + ' '
        'AND p.id NOT IN (SELECT photo_id FROM links) '
        'ORDER BY p.batch_id, p.import_seq, p.rowid', (container_id,))]
    linked_n = con.execute(
        'SELECT COUNT(*) ' + base + ' '
        'AND p.id IN (SELECT photo_id FROM links)', (container_id,)).fetchone()[0]
    return {'total': len(ids), 'linked_n': linked_n, 'ids': ids}


# ── 相似重复照片检测（2026-10-15 需求3）──────────────────────────
# 连拍多张同物是现场常态：同样的编码读三遍会在候选区出现三次「N 待关」，
# 报告选图也要人工去翻。用 dHash（9×8 灰度相邻比较 = 64 位指纹）把
# 「看起来一样」的图找出来，人工确认后只留一张。
# 为什么不用 md5：连拍两张构图/曝光必然有微差，md5 只能抓「完全同一文件」，
# 抓不住「同一张货拍了两遍」—— 需求要的是后者。

def dhash_of(path):
    """dHash 64-bit → 16 位 hex；失败返回 None（指纹算不出不能挡导入）。

    ⚠️ 与下面 _phash（DCT，报告选图 near_std 排序用）是两套：
    这套为「重复照片分组」持久化在 photos.phash 列 —— 导入时算一次，
    重启不重算；DCT 那套按需现算，不落库。别互相覆盖。

    JPEG 走 Image.draft 快速降采样（大图 ~10ms，不走全量解码）；
    PNG/WebP 不支持 draft，全量 decode 会慢些，但只发生在导入时一次。
    """
    try:
        from PIL import Image
        im = Image.open(path)
        try:
            im.draft('L', (160, 120))
        except Exception:  # noqa: BLE001  非 JPEG 没有 draft，忽略
            pass
        im = im.convert('L').resize((9, 8))
        px = list(im.getdata())
        bits = 0
        for row in range(8):
            base = row * 9
            for col in range(8):
                bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
        return '%016x' % bits
    except Exception:  # noqa: BLE001
        return None


def backfill_phash(con, container_id, limit=600):
    """给本柜缺指纹的照片补算。返回剩余未算数（>0 = 前端该提示稍后再开）。"""
    rows = con.execute(
        'SELECT p.id, p.path FROM photos p JOIN batches b ON b.id=p.batch_id '
        'WHERE b.container_id=? AND p.phash IS NULL LIMIT ?',
        (container_id, limit)).fetchall()
    done = 0
    for r in rows:
        h = dhash_of(resolve_photo_path(con, r['id'], r['path']))
        if h:
            con.execute('UPDATE photos SET phash=? WHERE id=?', (h, r['id']))
            done += 1
    con.commit()
    remain = con.execute(
        'SELECT COUNT(*) FROM photos p JOIN batches b ON b.id=p.batch_id '
        'WHERE b.container_id=? AND p.phash IS NULL', (container_id,)).fetchone()[0]
    return remain


def _hex_dist(a, b):
    """两个 16 位 hex 指纹的汉明距离；解析失败返回 99（视为不相似）。"""
    try:
        return bin(int(a, 16) ^ int(b, 16)).count('1')
    except (ValueError, TypeError):
        return 99


def dup_groups(con, container_id, max_dist=6, max_groups=200):
    """相似重复分组（贪心代表聚类）。

    每组返回 {keep, others}：keep = 建议保留张（已关联 > 已有分类 > 序号小），
    others = 与 keep 指纹汉明距离 ≤ max_dist 的其余张。
    只对未标无效的照片分组 —— 已经标过的别再翻出来。
    贪心代表（每张只跟已有组的代表比）而不是两两全比：组数通常几十，
    n×组数 次比对就够了，两千张也是毫秒级。
    """
    rows = con.execute(
        'SELECT p.*, EXISTS(SELECT 1 FROM links l WHERE l.photo_id=p.id) AS linked'
        ' FROM photos p JOIN batches b ON b.id=p.batch_id'
        ' WHERE b.container_id=? AND IFNULL(p.is_invalid,0)=0'
        '   AND p.phash IS NOT NULL AND IFNULL(p.is_dup,0)=0'
        ' ORDER BY p.batch_id, p.import_seq, p.rowid', (container_id,)).fetchall()
    groups = []          # [{keep: row, others: [row]}]
    for r in rows:
        placed = False
        for g in groups:
            if _hex_dist(g['keep']['phash'], r['phash']) <= max_dist:
                g['others'].append(dict(r))
                placed = True
                break
        if not placed:
            groups.append({'keep': dict(r), 'others': []})
    # 只留真有重复的组；keep 重选：已关联的优先当代表
    out = []
    for g in groups:
        if not g['others']:
            continue
        members = [g['keep']] + g['others']
        keep = max(members, key=lambda m: (m['linked'],
                                           1 if m['photo_kind'] else 0,
                                           -(m['import_seq'] or 0)))
        others = [m for m in members if m['id'] != keep['id']]
        out.append({'keep': keep, 'others': others})
    out.sort(key=lambda g: (g['keep']['batch_id'], g['keep']['import_seq'] or 0))
    return out[:max_groups]


def set_supervision_tag(con, photo_ids, tag, by='user'):
    """给监装照片打语义标签（报告区块④⑦用）。

    tag 只能是 [schema.SUPERVISION_TAGS] 的键；空串 = 清除标注。
    支持一次传多张 —— 监装是连拍流，逐张点会点断手。

    ⚠️ 这里**只写元数据，一个像素都不碰**：方向矫正/缩放/裁剪全是报告
    生成环节的事（人工真要修图走 standard_images，报告优先用标准图）。
    理由：原始照片是取证证据，治理管道一旦开始改像素，出错就不可逆了。

    🔴 人工在此表态过就置 sup_tag_confirmed=1（哪怕改成了别的值、或清空）。
    有了这个标记，UI 才知道「这张的细分是人事先拍过板的重跑治理别动它」，
    大模型的新建议只更新 sup_tag_ai* 三列，不会静默改掉人工结果。
    """
    ids = [p for p in (photo_ids or []) if p]
    if not ids:
        return 0
    tag = (tag or '').strip() or None
    if tag and tag not in schema.SUPERVISION_TAGS:
        raise ValueError('标签只能是：%s' % ' / '.join(schema.SUPERVISION_TAGS.keys()))
    qs = ','.join('?' * len(ids))
    cur = con.execute(
        'UPDATE photos SET supervision_tag=?,sup_tag_confirmed=1'
        ' WHERE id IN (%s)' % qs, [tag] + ids)
    con.commit()
    return cur.rowcount


def accept_sup_tag_suggestion(con, photo_id):
    """把大模型建议的监装细分落成人工确认值（UI 的「采用建议」按钮）。

    与 set_supervision_tag 的区别：这里的取值来自 sup_tag_ai，
    所以必须**在写之前校验它还在枚举内** —— 模型可能自造值，
    也可能这一列是历史脏数据。不校验就会让脏值流进报告。
    没有建议（NULL）时返回 0，调用方应报「这张没有建议」而不是静默成功。

    🔴 还要挡「用途不是监装」的照片：预检照的细分建议可能是脏数据，
    而且它压根不该进报告区块④⑦ —— 给它打上「封条」之类的标签，
    等于凭空造一张不存在的柜况图。
    """
    row = con.execute('SELECT sup_tag_ai, photo_usage FROM photos WHERE id=?',
                      (photo_id,)).fetchone()
    if not row:
        return 0
    if (row['photo_usage'] or '') != '监装':
        raise ValueError('只有监装照片才能用监装细分（这张是「%s」）'
                         % (row['photo_usage'] or '未分类'))
    sug = (row['sup_tag_ai'] or '').strip()
    if sug not in schema.SUPERVISION_TAGS:
        raise ValueError('这张照片没有可用的细分建议')
    set_supervision_tag(con, [photo_id], sug, by='accept-ai')
    return 1


def sup_tag_suggestions(con, photo_ids):
    """取这些照片的 AI 细分建议（前端渲染「建议 X · 82%」用）。"""
    ids = [p for p in (photo_ids or []) if p]
    if not ids:
        return {}
    qs = ','.join('?' * len(ids))
    out = {}
    for r in con.execute(
            'SELECT id,sup_tag_ai,sup_tag_ai_conf,sup_tag_ai_reason,sup_tag_confirmed'
            ' FROM photos WHERE id IN (%s)' % qs, ids):
        sug = (r['sup_tag_ai'] or '').strip()
        out[r['id']] = {
            'tag': sug if sug in schema.SUPERVISION_TAGS else None,
            'conf': r['sup_tag_ai_conf'],
            'reason': r['sup_tag_ai_reason'] or '',
            'confirmed': int(r['sup_tag_confirmed'] or 0),
        }
    return out


def sup_tag_pending_count(con, batch_id=''):
    """监装照里「有 AI 建议但人工还没表态」的张数。

    ⚠️ 口径：只数 sup_tag_ai 在枚举内、且人工还没确认过的。
    模型没给建议的不算 —— 「没建议」和「有建议待确认」是两件事，
    混在一个数字里会让 UI 提示指向错误的操作。
    """
    qs = ",".join("'%s'" % t for t in schema.SUPERVISION_TAGS)
    sql = ("SELECT COUNT(*) c FROM photos WHERE photo_usage='监装' AND is_dup=0"
           ' AND IFNULL(sup_tag_confirmed,0)=0 AND sup_tag_ai IN (%s)' % qs)
    args = []
    if batch_id:
        sql += ' AND batch_id=?'
        args.append(batch_id)
    return con.execute(sql, args).fetchone()['c']


def batch_supervision_tags(con, batch_id=''):
    """批次内监装标签的计数（柜详情页/照片页的「待打标签 N」提示）。"""
    sql = ("SELECT IFNULL(supervision_tag,'未标注') t, COUNT(*) c FROM photos"
           " WHERE photo_usage='监装' AND is_dup=0")
    args = []
    if batch_id:
        sql += ' AND batch_id=?'
        args.append(batch_id)
    sql += ' GROUP BY supervision_tag ORDER BY c DESC'
    return {r['t']: r['c'] for r in con.execute(sql, args)}


def skipped_photos(con, limit=60, offset=0):
    """已被跳过的照片（供「撤销跳过」查看）。"""
    return con.execute(
        'SELECT * FROM photos WHERE COALESCE(manual_skip,0)=1'
        ' ORDER BY skip_at DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()


def update_product_fields(con, code_norm, fields):
    """内联编辑产品字段（品名/规格/材质等）。

    只允许更新 PRODUCT_FIELDS 里的非必填业务字段 + remark；
    编码不可改（改了等于换一件货）。
    """
    editable = {'name', 'spec', 'unit', 'brand', 'material', 'category', 'remark'}
    sets, args = [], []
    for k, v in fields.items():
        if k in editable:
            sets.append('%s=?' % k)
            args.append(v)
    if not sets:
        return 0
    sets.append('updated_at=?')
    args += [now_iso(), code_norm]
    cur = con.execute('UPDATE products SET %s WHERE code_norm=?' % ','.join(sets),
                      args)
    con.commit()
    return cur.rowcount


def stats(con):
    d = {}
    d['products'] = con.execute('SELECT COUNT(*) FROM products').fetchone()[0]
    d['confirmed'] = con.execute(
        "SELECT COUNT(*) FROM products WHERE review_state='confirmed'").fetchone()[0]
    d['photos'] = con.execute('SELECT COUNT(*) FROM photos').fetchone()[0]
    d['links'] = con.execute('SELECT COUNT(*) FROM links').fetchone()[0]
    d['with_photos'] = con.execute(
        'SELECT COUNT(*) FROM products WHERE photo_count>0').fetchone()[0]
    d['pending'] = con.execute(
        "SELECT COUNT(*) FROM photos WHERE govern_state='pending'").fetchone()[0]
    # 待关联计数（2026-10-17 老板规则）：只有产品图（label/product）进队列，
    # 白名单口径见 _UNLINKED_SQL —— 旧的 NO_LINK_KINDS 排除已被白名单覆盖。
    d['unlinked'] = con.execute(
        'SELECT COUNT(*) FROM photos p WHERE ' + _UNLINKED_SQL).fetchone()[0]
    d['by_kind'] = {r['photo_kind'] or 'unknown': r['n'] for r in con.execute(
        'SELECT photo_kind, COUNT(*) n FROM photos GROUP BY photo_kind')}
    d['by_source'] = {r['source']: r['n'] for r in con.execute(
        'SELECT source, COUNT(*) n FROM links GROUP BY source')}
    return d


def batches_stats(con, kind='photos'):
    """批次一等公民视图：每个批次的照片量与治理/关联进度。

    [kind]：'photos'=照片批次（预检批次页主视角）；None=全部（含清单导入批次）。
    逐批查询而不是一条大 SQL —— 批次数量是个位数～两位数，可读性优先。
    """
    if kind:
        brows = con.execute('SELECT * FROM batches WHERE kind=? ORDER BY created_at DESC',
                            (kind,)).fetchall()
    else:
        brows = con.execute('SELECT * FROM batches ORDER BY created_at DESC').fetchall()
    out = []
    for b in brows:
        bid = b['id']
        n = lambda sql, args=(bid,): con.execute(sql, args).fetchone()[0]  # noqa: E731
        d = dict(b)
        d['total'] = n('SELECT COUNT(*) FROM photos WHERE batch_id=?')
        d['unique'] = n('SELECT COUNT(*) FROM photos WHERE batch_id=? AND is_dup=0')
        d['dup'] = d['total'] - d['unique']
        d['pending'] = n("SELECT COUNT(*) FROM photos WHERE batch_id=?"
                         " AND govern_state='pending' AND is_dup=0")
        d['failed'] = n("SELECT COUNT(*) FROM photos WHERE batch_id=?"
                        " AND govern_state='failed' AND is_dup=0")
        d['done'] = n("SELECT COUNT(*) FROM photos WHERE batch_id=?"
                      " AND govern_state IN ('done','skipped') AND is_dup=0")
        # 已关联：该批次中至少挂上一个产品的唯一照片数
        d['linked'] = con.execute(
            'SELECT COUNT(DISTINCT l.photo_id) FROM links l'
            ' JOIN photos p ON p.id=l.photo_id WHERE p.batch_id=?',
            (bid,)).fetchone()[0]
        out.append(d)
    return out


def _q_filter(q):
    """照片关键词检索的 SQL 片段 —— **统一入口，治理与分组共用**。

    跨四列：文件名 / 大模型描述 / 大模型提取的编码 / **已关联的产品编码**。
    最后一列最关键：「把某个编码的照片找出来」是主要用法，
    而编码不存在于 photos 表，必须 JOIN links。

    ⚠️ 之前 /api/photos 与 /api/photos/groups 各写一份 LIKE，
       结果加编码检索只改了一处 —— 切到分组视图搜索结果就不一样了。
       两处口径必须同源，抽出来是唯一办法。

    归一化：老板常从清单复制带分隔符的编码（`100 0000 119`），
    库里存 `1000000119`，所以原样与归一化各试一次。
    """
    import build_library as BLM
    qn = BLM.normalize(q)
    terms = [q] if (not qn or qn == q) else [q, qn]
    parts, args = [], []
    for t in terms:
        parts.append(
            '(p.file LIKE ? OR p.vision_desc LIKE ? OR p.vision_codes LIKE ?'
            ' OR EXISTS (SELECT 1 FROM links l2 WHERE l2.photo_id=p.id'
            '   AND l2.code_norm LIKE ?))')
        like = '%%%s%%' % t
        args += [like, like, like, like]
    return ' AND (' + ' OR '.join(parts) + ')', args


def regroup_photos_by_time(con, batch_id=None, dry_run=False, gap_sec=None,
                           max_per_group=None, split_by_dir=True):
    """按「同目录 + 拍照时间」重算 group_idx：主规则是间隔，张数上限只作安全阀。

    老口径：间隔 > 45s **或** 满 12 张就切一组 —— 一次连拍十几张是常态，
    被 12 张硬切得很碎（实测某批次前一组结束与后一组开始是同一秒）。
    10-04 老板拍板：间隔 > gap_sec（默认 45s）才切；张数上限放宽到 30，
    **只当安全阀** —— 主力那批照片是 0~2 秒一张的连续流，没上限会切出
    412 张的巨型组（同组推荐一次列 400 张 = 没法用）。

    🔴 2026-10-19 加**目录强制切组**（老板口径「同一个产品拍的照片……
    是在一个组里或者文件夹里的」）：App 交付包是 `预检/<箱号>/`，
    一件货不会跨两个箱目录拍。只按时间切会把相邻箱号的两段连拍并成一组
    （换箱往往只隔几十秒）。

    时间缺失的照片各自单独成组，不猜它属于哪段连拍。

    ⚠️ 只改 photos.group_idx —— 不动 links、不动文件、不重跑识别。
    影响面：同组推荐 product_group_siblings 与组视图 photo_groups 会跟着变。
    dry_run=True 只统计不写库 —— 先看清影响再决定。
    """
    gap = BL.GROUP_GAP_SEC if gap_sec is None else int(gap_sec)
    cap = BL.GROUP_MAX_PHOTOS if max_per_group is None else int(max_per_group or 0)

    def _dt(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace('Z', ''))
        except Exception:
            return None

    sql = 'SELECT id, batch_id, group_idx, taken_at, carton_no, path, file FROM photos'
    args = []
    if batch_id:
        sql += ' WHERE batch_id=?'
        args.append(batch_id)
    # 目录优先、时间次之：先看同一文件夹里的时间序，再看跨文件夹
    sql += ' ORDER BY batch_id, carton_no, path, taken_at, file'
    rows = con.execute(sql, args).fetchall()

    by_batch = {}
    for r in rows:
        by_batch.setdefault(r['batch_id'], []).append(r)

    plan = []          # [(photo_id, new_group_idx)]
    for _bid, items in by_batch.items():
        gi = -1
        prev = None
        cur_n = 0
        prev_dir = _MISSING
        for r in items:
            dk = photo_dir_key(r) if split_by_dir else None
            t = _dt(r['taken_at'])
            if t is None:
                gi += 1          # 没时间的单独成组（不猜它属于哪段连拍）
                plan.append((r['id'], gi))
                prev = None
                cur_n = 1
                prev_dir = dk
                continue
            cut = prev is None or (t - prev).total_seconds() > gap \
                or (cap and cur_n >= cap)
            if split_by_dir and prev_dir is not _MISSING and dk != prev_dir:
                cut = True       # 换文件夹 = 换一段拍摄，必切
            if cut:
                gi += 1
                cur_n = 0
            plan.append((r['id'], gi))
            prev = t
            cur_n += 1
            prev_dir = dk

    new_of = dict(plan)
    old_pairs = {(r['batch_id'], r['group_idx']) for r in rows}
    new_pairs = {(r['batch_id'], new_of[r['id']]) for r in rows}
    changed = sum(1 for r in rows if r['group_idx'] != new_of[r['id']])
    sizes = {}
    for r in rows:
        key = (r['batch_id'], new_of[r['id']])
        sizes[key] = sizes.get(key, 0) + 1
    out = {
        'photos': len(rows),
        'batches': len(by_batch),
        'groups_before': len(old_pairs),
        'groups_after': len(new_pairs),
        'max_group_size': max(sizes.values()) if sizes else 0,
        'changed': changed,
        'gap_sec': gap,
        'max_per_group': cap,
        'split_by_dir': bool(split_by_dir),
        'dry_run': bool(dry_run),
    }
    if not dry_run and changed:
        con.executemany('UPDATE photos SET group_idx=? WHERE id=?',
                        [(gi, pid) for pid, gi in plan])
        con.commit()
    return out


def photo_groups(con, state='', kind='', batch='', unlinked=0, q='',
                 usage='', limit=30, offset=0, invalid='hide', todo=''):
    """按 (batch_id, group_idx) 聚合照片，返回组列表。

    筛选条件匹配到的照片 → 找到它们所属的组 → 返回这些组的**全部**照片
    （展开后能看到同组上下文，这是分组视图的核心价值）。
    group_idx 为 NULL 的照片各自单独成组（老数据 / 未分组）。

    每组带语义摘要：分类分布、读到的编码、已关联的产品编码 ——
    "这组拍的是哪个产品"一眼可判，比逐张网格强。
    """
    # 1. 匹配筛选的照片（只取 id + 分组字段，轻量）
    # invalid：'hide'（默认）排除无效照片 / 'only' 只看无效 / 'all' 含无效。
    # 与网格列表同一口径（photo_where_sql 同名参数），两边不能各写一份。
    sql = ('SELECT id, batch_id, group_idx FROM photos p WHERE 1=1'
           + ('' if invalid == 'all'
              else ' AND IFNULL(p.is_invalid,0)=%d' % (1 if invalid == 'only' else 0)))
    args = []
    if state:
        sql += ' AND p.govern_state=?'; args.append(state)
    if kind:
        sql += ' AND p.photo_kind=?'; args.append(kind)
    if batch:
        sql += ' AND p.batch_id=?'; args.append(batch)
    if usage:
        if usage == '_unset':
            sql += ' AND p.photo_usage IS NULL'
        else:
            sql += ' AND p.photo_usage=?'; args.append(usage)
    if unlinked:
        # 与 photo_where_sql 同一份口径（含 2026-10-16 监装排除）——
        # 网格列表与分组视图各写一份必然漂。
        sql += ' AND ' + _UNLINKED_SQL
    if q:
        frag, qargs = _q_filter(q)
        sql += frag
        args += qargs
    if todo in ('cand', 'newprod'):
        # 待办收窄（2026-10-15 需求3）：分组视图与网格/五档同一口径
        ids = set(cand_photo_ids(con)) if todo == 'cand' \
            else set(newprod_photo_map(con))
        ids = sorted(ids)
        parts, ea = [], []
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            parts.append('p.id IN (%s)' % ','.join('?' * len(chunk)))
            ea.extend(chunk)
        if not parts:
            return {'total': 0, 'items': []}
        sql += ' AND (%s)' % ' OR '.join(parts)
        args += ea
    matched = con.execute(sql, args).fetchall()
    if not matched:
        return {'total': 0, 'items': []}

    def _gkey(r):
        bid = r['batch_id'] or ''
        gidx = r['group_idx']
        # NULL → 用 id 做唯一键，各自成组
        return (bid, gidx if gidx is not None else 'u:' + r['id'])

    keys = {_gkey(r) for r in matched}

    # 2. 这些组的全部照片（含同组内未直接匹配筛选的照片）
    cond, cargs = [], []
    for bid, gidx in keys:
        if isinstance(gidx, str) and gidx.startswith('u:'):
            cond.append('(p.batch_id IS ? AND p.id=?)')
            cargs += [bid if bid else None, gidx[2:]]
        else:
            cond.append('(p.batch_id IS ? AND p.group_idx=?)')
            cargs += [bid if bid else None, gidx]
    rows = con.execute(
        'SELECT p.* FROM photos p WHERE ' + ' OR '.join(cond)
        + ' ORDER BY p.taken_at', cargs).fetchall()

    # 所有组内照片的 links（一次查，避免 N+1）
    pids = [r['id'] for r in rows]
    link_map = {}
    if pids:
        ph = ','.join('?' * len(pids))
        for l in con.execute(
                'SELECT photo_id, code_norm FROM links WHERE photo_id IN (%s)' % ph,
                pids):
            link_map.setdefault(l['photo_id'], []).append(l['code_norm'])

    # 3. 聚合
    groups = {}
    order = []
    for r in rows:
        key = _gkey(r)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)
    # 按组内首张拍摄时间排序；🔴 决胜项必须是组键本身（每页唯一）——
    # 无 EXIF 的照片兜底时间大量并列，只按 taken_at 排的话并列组之间的
    # 相对顺序不保证稳定，翻页时会整组漏掉（2026-10-14 实测踩坑）。
    order.sort(key=lambda k: (groups[k][0]['taken_at'] or '', str(key)))

    total = len(order)
    page = order[offset:offset + limit]

    items = []
    for key in page:
        phs = groups[key]
        cover = phs[0]
        kinds = {}
        codes_set = set()
        linked_set = set()
        for p in phs:
            k = p['photo_kind'] or 'unknown'
            kinds[k] = kinds.get(k, 0) + 1
            try:
                cs = json.loads(p['vision_codes']) if p['vision_codes'] else []
                if isinstance(cs, list):
                    codes_set.update(cs)
            except Exception:
                pass
            for cn in link_map.get(p['id'], []):
                linked_set.add(cn)
        items.append({
            'key': key[0] + ':' + str(key[1]),
            'batch_id': key[0] or None,
            'group_idx': key[1] if not isinstance(key[1], str) else None,
            'count': len(phs),
            'cover_id': cover['id'],
            'cover_thumb': '/thumb/%s' % cover['id'],
            'kinds': kinds,
            'codes': sorted(codes_set),
            'linked_codes': sorted(linked_set),
            'taken_from': phs[0]['taken_at'],
            'taken_to': phs[-1]['taken_at'],
            'photos': [{
                'id': p['id'], 'thumb': '/thumb/%s' % p['id'],
                'full': '/img/%s' % p['id'], 'file': p['file'],
                'photo_kind': p['photo_kind'], 'govern_state': p['govern_state'],
                'vision_codes': p['vision_codes'], 'vision_desc': p['vision_desc'],
                'taken_at': p['taken_at'],
                'size_mb': round((p['bytes'] or 0) / 1048576, 2),
                'nlink': len(link_map.get(p['id'], [])),
                'is_dup': p['is_dup'],
            } for p in phs],
        })
    return {'total': total, 'items': items}


def photos_by_carton(con, container_id='', state='', kind='', usage='', q='',
                     unlinked=0, invalid='hide', extra_ids=None,
                     limit=30, offset=0):
    """按箱号（carton_no）聚合的照片组（2026-10-14 老板需求：③按箱号分组看）。

    与 photo_groups 同一套骨架：photo_where_sql 匹配筛选 → 内存聚合 →
    组摘要 + 组内全部照片。差异只在分组键：carton_no 而不是连拍组。
    🔴 口径同源：筛选参数与 /api/photos 完全一致（含 invalid 三态、
    unlinked、q），树上/工具栏怎么筛，箱号分组就怎么算。

    [extra_ids] pending 等由 Python 算出来的 id 集合（route 层算好传入，
      与 api_photos 的 pending 模式同构），非空时只保留这些照片。

    组排序：箱号名升序（找箱子按名字找），空箱号组排最后、叫「未标注箱号」。
    组内照片按拍摄时间排序（taken_at, id 决胜项——无 EXIF 兜底时间并列时
    没有决胜项会顺序不稳定，2026-10-14 踩过分页漏行的坑）。
    """
    join, where, args = photo_where_sql(
        state=state, kind=kind, usage=usage, q=q, unlinked=unlinked,
        container_id=container_id, invalid=invalid)
    sql = 'SELECT p.* FROM photos p' + join + where
    if extra_ids:
        parts, ea = [], []
        for i in range(0, len(extra_ids), 400):
            chunk = extra_ids[i:i + 400]
            parts.append('p.id IN (%s)' % ','.join('?' * len(chunk)))
            ea.extend(chunk)
        sql += (' WHERE ' if not where.strip() else ' AND ') + '(%s)' % ' OR '.join(parts)
        args = list(args) + ea
    sql += ' ORDER BY p.taken_at, p.id'
    rows = con.execute(sql, args).fetchall()
    if not rows:
        return {'total': 0, 'items': []}

    # 组内照片的关联编码（一次查，避免 N+1）
    pids = [r['id'] for r in rows]
    ph = ','.join('?' * len(pids))
    link_map = {}
    for l in con.execute('SELECT photo_id, code_norm FROM links '
                         'WHERE photo_id IN (%s)' % ph, pids):
        link_map.setdefault(l['photo_id'], []).append(l['code_norm'])

    def _ckey(r):
        # 空箱号各自进同一个「未标注」组；排序键 (1, '') 让它稳居最后
        v = (r['carton_no'] or '').strip()
        return ('__none__', '') if not v else (v, v)

    groups = {}
    for r in rows:
        groups.setdefault(_ckey(r), []).append(r)
    order = sorted(groups.keys(), key=lambda k: (k[0] == '__none__', k[0]))
    total = len(order)
    page = order[offset:offset + limit]

    items = []
    for key in page:
        phs = sorted(groups[key], key=lambda r: (r['taken_at'] or '', r['id']))
        cover = phs[0]
        kinds = {}
        codes_set = set()
        linked_set = set()
        for p in phs:
            k = p['photo_kind'] or 'unknown'
            kinds[k] = kinds.get(k, 0) + 1
            try:
                cs = json.loads(p['vision_codes']) if p['vision_codes'] else []
                if isinstance(cs, list):
                    codes_set.update(cs)
            except Exception:
                pass
            for cn in link_map.get(p['id'], []):
                linked_set.add(cn)
        items.append({
            'carton_no': key[0] if key[0] != '__none__' else None,
            'count': len(phs),
            'cover_id': cover['id'],
            'cover_thumb': '/thumb/%s' % cover['id'],
            'kinds': kinds,
            'codes': sorted(codes_set),
            'linked_codes': sorted(linked_set),
            'taken_from': phs[0]['taken_at'],
            'taken_to': phs[-1]['taken_at'],
            'photos': [{
                'id': p['id'], 'thumb': '/thumb/%s' % p['id'],
                'full': '/img/%s' % p['id'], 'file': p['file'],
                'photo_kind': p['photo_kind'], 'govern_state': p['govern_state'],
                'vision_codes': p['vision_codes'], 'vision_desc': p['vision_desc'],
                'taken_at': p['taken_at'],
                'size_mb': round((p['bytes'] or 0) / 1048576, 2),
                'nlink': len(link_map.get(p['id'], [])),
                'is_dup': p['is_dup'], 'is_invalid': p['is_invalid'],
            } for p in phs],
        })
    return {'total': total, 'items': items}


# ═══════════════════════════════════════════════════════════════════
# 发现新产品（图片库识别 → 人工确认 → 写入产品库）
#
# 与「人工关联工作台」互补的两条人工闭环：
#   · 工作台：照片 → 已有产品（关联）
#   · 本模块：照片读出但库内没有的编码 → 确认为新产品（入库 + 顺手关联）
# ═══════════════════════════════════════════════════════════════════

# 编码形态（2026-10-18 老板实测放宽）：与 vision._CODE_RE 同一条规则。
# 旧规则 `^[1-9]\d{7,14}[A-Za-z]{0,3}$` 只认纯数字或「数字+≤3 字母后缀」——
# 真实产品库 400 个编码里 399 个是「数字+字母」混合形态（101039030015C、
# 101039030081D01），合格证上的 2030BG0000098 也是 —— 旧正则把主流形态全
# 当噪声滤掉，「新产品确认」和 OCR 候选大量漏报（老板截图实测）。
# 新规则：数字开头、8~18 位、数字字母任意混合（与库内形态一致）。
# 独立定义以避免 store → vision 依赖；改规则时两处同步。
_LOOKS_CODE_RE = re.compile(r'^[1-9][0-9A-Z]{7,17}$')
# 标签前缀（2026-10-18 补 PN）：OCR 常把标签上的「PN:203160000002」整串读出，
# 不剥前缀就连 prefix 匹配都过不了、更别说 exact 自动关联（老板实测）。
_PREFIX_RE = re.compile(r'^(编码|物料|料号|编号|物品编码|ITEM|NO\.?|PART|PARTS|PN|P/N|P\.N\.?|CODE|SN)'
                        r'[:：-]?\s*', re.IGNORECASE)


def strip_code_prefix(s):
    """剥掉标签前缀（PN:/NO./编码: 等）—— 匹配入口也要剥，不只是判形态。

    _match_token 直接拿原始 token 去 index.best：带 PN 前缀的串最多落到
    prefix 模式，而自动关联只认 exact → 明明库里有这个码却关联不上
    （2026-10-18 老板实测：OCR 读出 PN:203160000002，库里就有 203160000002）。
    """
    s = str(s or '').strip().upper()
    return _PREFIX_RE.sub('', s)


def looks_like_code(s):
    """返回 (是否像产品编码, 清洗后的串)。清洗规则与 vision._clean_codes 一致。"""
    s = strip_code_prefix(s)
    s = s.replace(' ', '').replace('　', '').replace('，', '').replace(',', '')
    return bool(_LOOKS_CODE_RE.match(s)), s


def discovered_products(con, ocr_min_conf=0.85, min_conf=0.60, max_photos=12, batch_id=None):
    """聚合「照片里读出、但产品库里没有」的疑似新产品编码。

    来源两路：
      A. 多模态读码 vision_codes（治理时已过 vision._clean_codes 形态过滤，质量高）
      B. OCR token（噪声大：仅收 confidence≥ocr_min_conf 且形态像编码的）

    排除：
      · 已存在于 products（那就不叫"新产品"）
      · packing_list / scene 来源照片（清单是参考文档、场景照无产品信息）
      · photo_usage='监装' 的照片（2026-10-16：监装不关联产品）
      · 用户已忽略的（discover_ignore 表）

    返回按置信度降序的 list[dict]。
    """
    existing = {r['code_norm'] for r in con.execute('SELECT code_norm FROM products')}
    agg = {}   # code_norm -> 聚合字典

    def add(norm, raw, conf, src, photo_id):
        d = agg.get(norm)
        if d is None:
            agg[norm] = {'code': norm, 'raw': raw, 'sample': raw,
                         '_conf': conf, 'sources': {src}, 'photo_ids': [photo_id]}
            return
        d['sources'].add(src)
        if photo_id not in d['photo_ids'] and len(d['photo_ids']) < max_photos:
            d['photo_ids'].append(photo_id)
        if conf > d['_conf']:
            d['_conf'] = conf
            d['raw'] = raw

    # A. 多模态读码
    # ⚠️ `is_dup=0` 是 10-07 补的：重复件（同一批里字节相同的多张）不该出现在
    #    新产品候选里 —— 确认一次就够，而且候选卡上摆三张一样的缩略图纯属噪声。
    #    与 _cand_filter_sql 的重复件口径一致，两档分组才互不打架。
    sql_a = ("SELECT id,photo_kind,kind_conf,vision_codes FROM photos"
             " WHERE vision_codes IS NOT NULL"
             " AND vision_codes NOT IN ('', '[]')"
             " AND is_dup=0"
             " AND IFNULL(photo_ignored,0)=0"
             " AND id NOT IN (SELECT photo_id FROM links)"
             # 监装照片不参与新产品确认（2026-10-16：监装不需要关联）
             " AND IFNULL(photo_usage,'')<>'监装'")
    args_a = []
    if batch_id:
        sql_a += " AND batch_id=?"
        args_a.append(batch_id)
    for r in con.execute(sql_a, args_a):
        if r['photo_kind'] in schema.NO_LINK_KINDS or r['photo_kind'] == 'scene':
            continue
        try:
            codes = json.loads(r['vision_codes'])
        except Exception:
            continue
        if not isinstance(codes, list):
            continue
        kc = r['kind_conf'] or 0.9
        kc = max(0.5, min(1.0, float(kc)))
        conf = schema.SCORE_VISION_CODE * kc
        for c in codes:
            ok, s = looks_like_code(c)
            if not ok:
                continue
            n = BL.normalize(s)
            if not n or n in existing:
                continue
            add(n, s, conf, 'vision', r['id'])

    # B. 高置信 OCR token
    sql_b = ('SELECT p.id pid, p.photo_kind, t.raw_text, t.confidence'
             ' FROM ocr_tokens t JOIN photos p ON p.id = t.photo_id'
             ' WHERE p.id NOT IN (SELECT photo_id FROM links)'
             " AND IFNULL(p.photo_usage,'')<>'监装'"
             ' AND p.is_dup=0 AND IFNULL(p.photo_ignored,0)=0')
    args_b = []
    if batch_id:
        sql_b += " AND p.batch_id=?"
        args_b.append(batch_id)
    for t in con.execute(sql_b, args_b):
        if t['photo_kind'] in schema.NO_LINK_KINDS or t['photo_kind'] == 'scene':
            continue
        ok, s = looks_like_code(t['raw_text'])
        if not ok:
            continue
        conf = float(t['confidence'] or 0)
        if conf < ocr_min_conf:
            continue
        n = BL.normalize(s)
        if not n or n in existing:
            continue
        add(n, s, min(0.95, conf) * 0.9, 'ocr', t['pid'])   # OCR 噪声大，打折

    ignored = {r['code_norm'] for r in con.execute('SELECT code_norm FROM discover_ignore')}
    # 10-05：候选卡上要显示每张缩略图的拍照时间 —— 一次批量查，别逐张（性能铁律②）
    all_pids = sorted({pid for d in agg.values() for pid in d['photo_ids']})
    ptime = {}
    for i in range(0, len(all_pids), 400):
        chunk = all_pids[i:i + 400]
        for r in con.execute('SELECT id, taken_at FROM photos'
                             ' WHERE id IN (%s)' % ','.join('?' * len(chunk)),
                             chunk):
            ptime[r['id']] = r['taken_at']
    out = []
    for d in agg.values():
        if d['code'] in ignored:
            continue
        conf = d['_conf'] + (0.03 if len(d['sources']) > 1 else 0)   # 双来源小加成
        if conf < min_conf:
            continue
        out.append({'code': d['code'], 'raw': d['raw'], 'sample': d['sample'],
                    'confidence': round(min(0.99, conf), 3),
                    'sources': sorted(d['sources']),
                    'photo_count': len(d['photo_ids']),
                    'photo_ids': d['photo_ids'],
                    'photo_times': {pid: ptime.get(pid) for pid in d['photo_ids']}})
    out.sort(key=lambda x: (-x['confidence'], -x['photo_count']))
    return out


def confirm_product(con, code, name='', spec='', photo_ids=None, by='user'):
    """把一个人工确认的新编码写入产品库，并顺手把来源照片关联上。

    返回 {'code_norm', 'linked'}。编码不合法抛 ProductError。
    """
    photo_ids = [p for p in (photo_ids or []) if p]
    clean, errs = validate_product({'code': code, 'name': name or '', 'spec': spec or ''})
    if errs:
        raise ProductError('；'.join(errs))
    cn = clean['code_norm']
    ts = now_iso()
    con.execute(
        'INSERT OR IGNORE INTO products(code_norm,code,name,spec,remark,'
        'review_state,source_batch,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
        (cn, clean['code'], clean['name'], clean['spec'],
         '照片识别发现（%d 张来源照片）' % len(photo_ids), 'confirmed',
         'from_photo', ts, ts))
    linked = 0
    for pid in photo_ids:
        cur = con.execute(
            'INSERT OR REPLACE INTO links(code_norm,photo_id,source,confidence,'
            'evidence,created_at,created_by) VALUES (?,?,?,?,?,?,?)',
            (cn, pid, 'manual', 0.90, '照片识别发现的新产品', ts, by))
        linked += cur.rowcount
    recalc_product_counts(con)
    return {'code_norm': cn, 'linked': linked}


def ignore_discovery(con, code_norm):
    """把一个候选编码拉黑 —— 之后不再出现在发现列表。"""
    con.execute('INSERT OR IGNORE INTO discover_ignore(code_norm,created_at) VALUES (?,?)',
                (BL.normalize(code_norm), now_iso()))
    con.commit()


def count_ignored(con):
    return con.execute('SELECT COUNT(*) FROM discover_ignore').fetchone()[0]


# ═══════════════════════════════════════════════════════════════════
# 候选照片「标记为无关联」（10-05 老板：可能关联的图，看过确认没有关联的
# 可以标记掉，之后不在可能关联的图片里显示）
#
# ── 为什么要落库，不能只在前端隐藏 ──────────────────────────────
# 候选是**算出来的**（读码 / 同组连拍），每次刷新 `cand_code_map` 都重算一遍。
# 只在前端把它 display:none 的话，刷新一次它就原样回来 —— 等于没标记。
# 人工判定的「不是这个产品的照片」必须和 OCR 结果一样**持久**。
#
# ── 粒度：为什么是 (code_norm, photo_id) 而不是 photo_id ─────────
# 一张照片上可能读出多个码 → 它同时是 A、B 两个产品的候选。
# 老板说「它不是 A 的」，不能顺带把 B 的候选也抹掉 ——
# 那等于替他做了范围更大的决定，而这个范围他没授权过。
#
# ── 与 links 的互斥 ────────────────────────────────────────────
# 一对 (code_norm, photo_id) 只有三态：已关联 / 已否决 / 待确认。
# 人工关联时（link(source='manual')）自动清掉同对的否决记录 ——
# 老板改主意了就该能关联回来，旧否决不该卡住他。
def reject_candidate(con, code_norm, photo_id, reason=None, by='user'):
    """标记一张候选照片「与该产品无关联」（幂等）。

    返回 True=本次新标记，False=之前已标记过（不算覆盖，不改原记录）。
    """
    cn = BL.normalize(code_norm)
    if not con.execute('SELECT id FROM photos WHERE id=?', (photo_id,)).fetchone():
        return False
    cur = con.execute(
        'INSERT OR IGNORE INTO cand_reject(code_norm,photo_id,reason,'
        'created_at,created_by) VALUES (?,?,?,?,?)',
        (cn, photo_id, (reason or None), now_iso(), by))
    con.commit()
    return bool(cur.rowcount)


def unreject_candidate(con, code_norm, photo_id):
    """撤销「无关联」标记（幂等）—— 这张照片回到候选列表。"""
    cn = BL.normalize(code_norm)
    cur = con.execute('DELETE FROM cand_reject WHERE code_norm=? AND photo_id=?',
                      (cn, photo_id))
    con.commit()
    return cur.rowcount


def cand_rejects(con, code_norm=None):
    """被标记为无关联的 (code_norm, photo_id) 对。

    [code_norm] 只取该产品；不给则取全部（批量过滤用一次性取全表，
    避免逐张查 —— 性能铁律②）。
    """
    if code_norm:
        cn = BL.normalize(code_norm)
        rows = con.execute(
            'SELECT code_norm,photo_id,reason,created_at,created_by'
            ' FROM cand_reject WHERE code_norm=? ORDER BY created_at', (cn,))
    else:
        rows = con.execute(
            'SELECT code_norm,photo_id,reason,created_at,created_by'
            ' FROM cand_reject ORDER BY code_norm, created_at')
    return [dict(r) for r in rows]


def rejected_pairs(con):
    """{(code_norm, photo_id)} 全量已否决对 —— 候选取数时一次过滤用。"""
    return {(r['code_norm'], r['photo_id'])
            for r in con.execute('SELECT code_norm,photo_id FROM cand_reject')}


def count_cand_rejects(con):
    return con.execute('SELECT COUNT(*) FROM cand_reject').fetchone()[0]


def invalidate_cand_cache():
    """强制下次重算候选（写否决/撤销后调）。

    戳里已计入 cand_reject 行数，所以理论上会自然失效；但**戳只查行数**，
    「标记 A 再撤销 A」行数回到原样，若此时 TTL 恰好没到就会读到旧内容 ——
    而旧内容里 A 还在（那是标记之前算的）。直接清掉，别赌 TTL。
    （磁盘文件不删：每次重算都会按戳覆写，删了只会白白多算一次。）
    """
    _CAND_CACHE.clear()


# ═══════════════════════════════════════════════════════════════════
# 合并建议（场景 5：清单编码 ↔ 图片识别编码 两边都有时，人工裁决合并）
# ═══════════════════════════════════════════════════════════════════

def merge_suggestions(con, max_photos=24):
    """按产品聚合「照片读出编码 ↔ 库内产品」但照片尚未关联的建议。

    视角与人工关联工作台互补：
      · 工作台：这张照片该归谁（照片视角，逐张处理）
      · 这里：  这个产品有哪些照片证据建议合并进来（产品视角，整单裁决）
    清单是权威来源之一，图片识别是另一来源；两边都有时由人拍板。

    exact（归一化完全相等）已在治理时自动关联、不在此列；
    这里主要是 prefix/edit1/edit2 模糊命中 —— 恰是「读出来像但不敢自动写」的那批。
    """
    idx = BL.CodeIndex([(r['code'], r['name'], r['spec'])
                        for r in con.execute('SELECT code,name,spec FROM products')])
    # 白名单口径（2026-10-17 老板规则「只有产品需要关联」）与 _UNLINKED_SQL 同源
    rows = con.execute(
        'SELECT * FROM photos p WHERE ' + _UNLINKED_SQL
        + ' ORDER BY taken_at').fetchall()

    sugg = {}

    def add(p, code_norm, raw, mode, score, src):
        d = sugg.setdefault(code_norm, {'exact': [], 'fuzzy': []})
        item = {'photo_id': p['id'], 'file': p['file'], 'taken_at': p['taken_at'],
                'raw': raw, 'mode': mode, 'score': round(score, 3), 'src': src}
        (d['exact'] if mode == 'exact' else d['fuzzy']).append(item)

    for p in rows:
        # 多模态读码
        try:
            codes = json.loads(p['vision_codes']) if p['vision_codes'] else []
        except Exception:
            codes = []
        for cc in (codes if isinstance(codes, list) else []):
            m = idx.best(str(cc), 0.95)
            if m:
                add(p, m[0], str(cc), m[3], m[2], 'vision')
        # OCR token
        for t in con.execute(
                'SELECT raw_text,confidence FROM ocr_tokens WHERE photo_id=?'
                ' ORDER BY confidence DESC LIMIT 40', (p['id'],)):
            txt = (t['raw_text'] or '').strip()
            if len(txt) < BL.MATCH_MIN_TOKEN_LEN:
                continue
            m = idx.best(txt, float(t['confidence'] or 0))
            if m:
                add(p, m[0], txt[:40], m[3], m[2], 'ocr')

    # 权威 code/name/code_norm 以库内产品为准（idx.best 返回的是原始 code，
    # 不是 code_norm —— 回查必须 code_norm OR code 双路，否则大小写不一致时漏）
    out = []
    for cn, d in sugg.items():
        row = con.execute('SELECT code_norm,code,name FROM products'
                          ' WHERE code_norm=? OR code=?', (cn, cn)).fetchone()
        if not row:
            continue
        d.update({'code_norm': row['code_norm'], 'code': row['code'],
                  'name': row['name']})
        d['photo_count'] = len(d['exact']) + len(d['fuzzy'])
        out.append(d)
    out.sort(key=lambda d: (-(len(d['exact']) > 0), -d['photo_count']))
    return out


# ═══════════════════════════════════════════════════════════════════
# 待确认候选：列表标识 / 筛选 / 详情候选区 —— **三处同源**
# ═══════════════════════════════════════════════════════════════════
# 老板 10-05 要「标准产品库里把有可能关联待确认的照片标识出来，并能筛选」。
# 之前列表只有一个 cand_count（读码、且只认 SQL 精确相等），详情里却有两类
# 候选（读码 + 同组连拍）—— 结果是详情看得到、列表看不出来，也没法筛。
# 这里用一个函数同时喂三处，杜绝各写一份口径。

# 候选映射缓存（2026-10-17 落盘化：冷启动不再重算 3 秒）。
#   · key = 库文件路径 —— 同进程连多个库（测试的临时库 + 真实库）不会互相污染；
#   · stamp = _cand_stamp 全维度内容戳（含过滤载荷 kind/usage/dup）；
#   · 落盘 <数据目录>/_cand_cache.json 带 _CAND_CACHE_VER **逻辑版本号** ——
#     过滤/匹配逻辑变更时升版，旧文件自动作废（否则升级后读到旧口径的 map，
#     正是 10-16 改 _cand_filter_sql 时踩到的坑）；
#   · 磁盘 TTL 兜底：超过 _CAND_DISK_TTL_DAY 天也重算（防漏维度）。
_CAND_CACHE = {}
_CAND_TTL_SEC = 60.0
_CAND_CACHE_VER = 3        # 3 = 反向前缀匹配（2026-10-18 标签图号场景）
_CAND_DISK_TTL_DAY = 7
_CAND_LOCK = threading.Lock()


def _db_key(con):
    """库文件绝对路径（缓存 key + 落盘目录都从它推）。"""
    try:
        row = con.execute('PRAGMA database_list').fetchone()
        if row and row[2]:
            return os.path.abspath(row[2])
    except Exception:  # noqa: BLE001
        pass
    return os.path.abspath(paths.db_path())


def _cand_disk_load(key, stamp):
    try:
        p = os.path.join(os.path.dirname(key), '_cand_cache.json')
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        if (d.get('ver') == _CAND_CACHE_VER
                and list(d.get('stamp') or []) == list(stamp)
                and (time.time() - float(d.get('ts') or 0))
                < _CAND_DISK_TTL_DAY * 86400):
            m = d.get('map')
            if isinstance(m, dict):
                return m
    except Exception:  # noqa: BLE001  损坏/过期/只读目录都当没缓存
        pass
    return None


def _cand_disk_save(key, stamp, m):
    p = os.path.join(os.path.dirname(key), '_cand_cache.json')
    tmp = p + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'ver': _CAND_CACHE_VER, 'stamp': list(stamp),
                       'ts': time.time(), 'map': m}, f, ensure_ascii=False)
        os.replace(tmp, p)      # 原子替换：读者不会看到半文件
    except Exception:  # noqa: BLE001  缓存是优化，写失败不吵不闹
        try:
            os.remove(tmp)
        except Exception:  # noqa: BLE001
            pass


def _cand_stamp(con):
    """库内容戳：任何影响候选结果的变化都必须让它变（否则缓存会撒谎）。

    photos 的**字节数**也要算：治理只改 vision_codes，不改行数。
    ⚠️ cand_reject 的行数同样必须算（10-05）：标记「无关联」不新增照片、
    不改 token，只在候选集合里减掉一条 —— 不计入戳的话，标记后 60 秒内
    列表角标还是旧数字，老板会以为没生效（这个坑与 links 行数同源）。

    2026-10-17：候选过滤带上了 photo_kind / photo_usage / is_dup
    （_cand_filter_sql 与 _UNLINKED_SQL），而缓存要**落盘跨进程**存活 ——
    这几个维度不进戳，「改个用途 / 改判分类 / 标重复」会让磁盘缓存永久
    撒谎（invalidate_cand_cache 只有 reject 端点会调，覆盖不到这些写路径）。
    ocr_tokens 加内容长度和：add_tokens 是删+插，重跑 OCR 行数可能不变
    但文本变了。
    """
    a = con.execute(
        'SELECT COUNT(*), COALESCE(SUM(LENGTH(COALESCE(vision_codes,""))),0),'
        ' COALESCE(SUM(IFNULL(is_invalid,0)),0) FROM photos').fetchone()
    # 过滤载荷维度：重复件 / 关联白名单（LINKABLE_KINDS，2026-10-17 老板规则
    # 「只有产品需要关联」—— 白名单集合变化必须使缓存失效）/ 用途非空 / 监装
    _lk = ','.join("'%s'" % k for k in schema.LINKABLE_KINDS)
    b = con.execute(
        'SELECT COALESCE(SUM(IFNULL(is_dup,0)),0),'
        ' COALESCE(SUM(CASE WHEN photo_kind IN (%s) THEN 1 ELSE 0 END),0),'
        ' COALESCE(SUM(CASE WHEN photo_usage IS NOT NULL THEN 1 ELSE 0 END),0),'
        " COALESCE(SUM(CASE WHEN photo_usage='监装' THEN 1 ELSE 0 END),0)"
        ' FROM photos' % _lk).fetchone()
    tok = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(LENGTH(COALESCE(raw_text,''))),0)"
        ' FROM ocr_tokens').fetchone()
    return (a[0], a[1], a[2],
            con.execute('SELECT COUNT(*) FROM links').fetchone()[0],
            tok[0], tok[1],
            con.execute('SELECT COUNT(*) FROM products').fetchone()[0],
            con.execute('SELECT COUNT(*) FROM cand_reject').fetchone()[0],
            # 2026-10-18：photo_ignored 计数 —— 本次忽略只改这一列，
            # 不进戳的话已忽略照片在候选里阴魂不散 60 秒
            con.execute('SELECT COUNT(*) FROM photos'
                        ' WHERE IFNULL(photo_ignored,0)=1').fetchone()[0],
            b[0], b[1], b[2], b[3])


def _match_codes(kv, buckets, text, conf, memo):
    """token → [(code_norm, score, mode)]：exact / 子串(prefix) / 编辑距离(edit1|2)。

    分数公式照抄 CodeIndex.best（四档 base × token 置信度），三处差别：
      · **一次给出所有命中的产品**（列表要反查，CodeIndex 只给最佳的一个）；
      · 低于 schema.CAND_MIN_SCORE 的不算 —— 与「建议关联」同一道门槛
        （老板 10-02：宁可手输，也不要从一堆低分里挑）；
      · 编辑距离用 **(长度, 首字符) 分桶** 缩小候选。
        列表要对全库产品算一遍：裸扫 596 个 key 要 8.3s，分桶后 3.3s，
        再叠加置信度预筛（edit1 要 conf≥0.795 才可能过门槛）更快。
    ⚠️ 关键是详情 product_candidates **也用这一个 map**，所以列表与详情
    永远一致 —— 不会出现「列表标了 N 张、点开一张没有」。

    2026-10-17 两处提速（真实库实测：整图 3.2s → 冷算 ~1.3s，且落盘缓存
    让冷启动根本不进这里）：
      1. 前缀匹配从「全量扫 keys」改为「枚举 v 的子串查 kv」—— 原来
         782 个 key × 2645 个 variant ≈ 200 万次 `k in v`（实测 723ms）；
         子串枚举每个起点从长到短、命中即停，同一语义（取最长命中，
         并列时取先发现者，与旧行为只在「等长不同串」的边角有差异）。
      2. 两块贵扫描按 v 记忆化（memo）—— 真实库同一串字符被几十张照片
         读出（机型名等），variant 重复率 27%；前缀与编辑距离都是 v 的
         纯函数，与 conf 无关，可以跨 token 复用。
    """
    out = []
    for v in BL.variants(text):
        if len(v) < BL.MATCH_MIN_TOKEN_LEN:
            continue
        hit = kv.get(v)
        if hit:
            sc = min(1.0, BL.MATCH_BASE_EXACT * conf)
            if sc >= schema.CAND_MIN_SCORE:
                out.append((hit, sc, 'exact'))
            continue
        # 清单编码出现在 token 里（照片上多读出前后缀）—— 取最长命中的那个
        best = _prefix_hit(v, kv, memo)
        if best:
            sc = min(1.0, BL.MATCH_BASE_PREFIX * conf)
            if sc >= schema.CAND_MIN_SCORE:
                out.append((best, sc, 'prefix'))
            continue
        # 反向前缀（2026-10-18 现场实测）：**token 是某产品编码的前缀** ——
        # 标签上印的是「图号」（105029020062E，13 位），产品编码 = 图号 +
        # 尾缀（105029020062E41，Bracket RAL6012）。旧匹配只有「产品编码 ⊂
        # token」一个方向，这个方向永远落空 → 明明库里有货却零候选。
        # 只进「待确认关联」候选（自动关联仍只认 exact，防误挂）；
        # 全库唯一命中才给，多命中视为歧义放弃。
        rev = _prefix_rev_hit(v, buckets, memo)
        if rev:
            sc = min(1.0, BL.MATCH_BASE_PREFIX * conf)
            if sc >= schema.CAND_MIN_SCORE:
                out.append((rev, sc, 'prefix'))
            continue
        # 编辑距离：先按置信度预筛 —— 分不够就不用算了（这是耗时的部分）
        if conf < schema.CAND_MIN_SCORE / BL.MATCH_BASE_EDIT1:
            continue
        best = None
        for cn, base in _edit_hits(v, buckets, memo):
            sc = min(1.0, base * conf)
            if sc < schema.CAND_MIN_SCORE:
                continue
            if best is None or sc > best[1]:
                best = (cn, sc, 'edit1' if base == BL.MATCH_BASE_EDIT1
                        else 'edit2')
        if best:
            out.append(best)
    return out


def _prefix_hit(v, kv, memo):
    """v 的最长子串命中（长度≥4）→ code_norm；没有 → None。

    2026-10-17：旧实现对每个 variant 全量扫 keys（`for k in keys: k in v`），
    782 keys × 2645 variants ≈ 200 万次子串判断。改成枚举 v 自己的子串查
    kv：每个起点从长到短，命中即停（该起点不可能有更长的命中）。
    """
    key = ('p', v)
    if key in memo:
        return memo[key]
    best = None
    n = len(v)
    for i in range(n - 3):                 # 子串至少长 4 → 起点 ≤ n-4
        for j in range(n, i + 3, -1):      # 该起点从最长开始
            hit = kv.get(v[i:j])
            if hit:
                if best is None or (j - i) > best[0]:
                    best = ((j - i), hit)
                break                      # 本起点没有更长的了
    memo[key] = best[1] if best else None
    return memo[key]


def _prefix_rev_hit(v, buckets, memo):
    """反向前缀：查**以 v 开头**的产品编码（v 是标签图号，产品编码 = 图号+尾缀）。

    与 _prefix_hit 方向相反（那边是产品编码 ⊂ token）。全库**唯一**命中
    才返回 code_norm；多个不同产品都以 v 开头 = 歧义，返回 None（让人工
    手输，宁缺毋滥）。覆盖率守卫 len(v)/L ≥ 0.75 —— 防 4 位短 token 碰巧
    是某长编码的前缀。按 (长度, 首字符) 桶查，token 尾缀一般 ≤8 位。
    """
    key = ('r', v)
    if key in memo:
        return memo[key]
    n = len(v)
    if n < 8:                      # 太短的前缀歧义风险高，不查
        memo[key] = None
        return None
    best = None
    seen = set()
    for L in range(n + 1, n + 9):
        if n * 4 < L * 3:          # 覆盖率 <75% 停止（更长的只会更差）
            break
        for k, cn in buckets.get((L, v[0]), ()):
            if k.startswith(v) and cn not in seen:
                seen.add(cn)
                best = cn          # 记最后一个；唯一性在循环后判
    memo[key] = best if len(seen) == 1 else None
    return memo[key]


def _edit_hits(v, buckets, memo):
    """v 的编辑距离候选 → [(code_norm, base_score)]（base 未乘 conf）。

    分桶 + 记忆化。d==0 不可能出现（精确命中在上游已截走），防御性跳过。
    """
    key = ('e', v)
    if key in memo:
        return memo[key]
    out = []
    for dl in (-2, -1, 0, 1, 2):
        for k, cn in buckets.get((len(v) + dl, v[0]), []):
            d = BL.levenshtein(v, k)
            if d == 0 or d > BL.MATCH_MAX_EDIT:
                continue
            out.append((cn, BL.MATCH_BASE_EDIT1 if d == 1
                        else BL.MATCH_BASE_EDIT2))
    memo[key] = out
    return out


def cand_code_map(con, force=False):
    """{code_norm: {photo_id: [{raw, mode, score, src}]}} —— 读码类候选。

    扫描一次未关联照片（OCR token **批量查**，不逐张查），反查每个产品。

    缓存三层（2026-10-17，为「照片库/③打开卡 4 秒」修）：
      1. 进程内 TTL 60s —— 翻页/筛选不重算；
      2. **落盘** <数据目录>/_cand_cache.json（戳匹配即用）—— 冷启动
         （每次开程序）不再重算：真实库实测冷算 3.2s → 命中 ~0.1s；
      3. 都没有才真算（_cand_compute），算完立刻落盘。
    🔴 锁：首屏的 linkstate 与照片列表会并发打进来，没锁会两个线程同时
    算一遍 —— CPU 直接翻倍，Edge 那边体感更卡。
    """
    stamp = _cand_stamp(con)
    key = _db_key(con)
    now = time.time()
    ent = _CAND_CACHE.get(key)
    if (not force and ent is not None
            and ent['stamp'] == stamp
            and (now - ent['ts']) < _CAND_TTL_SEC):
        return ent['map']
    with _CAND_LOCK:
        # 等锁期间可能已有人算好（首屏并发）—— 再看一眼，别重复劳动
        ent = _CAND_CACHE.get(key)
        if (not force and ent is not None and ent['stamp'] == stamp):
            return ent['map']
        m = _cand_disk_load(key, stamp)
        if m is None:
            m = _cand_compute(con)
            _cand_disk_save(key, stamp, m)
        _CAND_CACHE[key] = {'stamp': stamp, 'map': m, 'ts': now}
        return m


def _cand_compute(con):
    """真算候选映射（无缓存路径）。拆出来是让 cand_code_map 的锁/落盘
    逻辑保持一眼可读。"""
    kv = {}
    buckets = {}
    for r in con.execute('SELECT code, code_norm FROM products'):
        for k in BL.variants(r['code']):
            if not k or k in kv:
                continue          # 同一变体只认第一个产品（去重，旧行为）
            kv[k] = r['code_norm']
            buckets.setdefault((len(k), k[0]), []).append((k, r['code_norm']))

    rows = con.execute(
        'SELECT ph.id, ph.vision_codes FROM photos ph'
        ' WHERE ph.id NOT IN (SELECT photo_id FROM links)'
        ' AND ' + _cand_filter_sql('ph')).fetchall()
    toks = {}
    for r in con.execute(
            'SELECT ot.photo_id, ot.raw_text, ot.confidence FROM ocr_tokens ot'
            ' JOIN photos ph ON ph.id=ot.photo_id'
            ' WHERE ph.id NOT IN (SELECT photo_id FROM links)'
            ' AND ' + _cand_filter_sql('ph')):
        toks.setdefault(r['photo_id'], []).append((r['raw_text'] or '',
                                                   r['confidence']))

    memo = {}      # ('p'|'e', v) → 前缀/编辑距离中间结果（variant 重复率 27%）
    m = {}
    for ph in rows:
        hits = {}
        try:
            codes = json.loads(ph['vision_codes']) if ph['vision_codes'] else []
        except Exception:  # noqa: BLE001
            codes = []
        for cc in (codes if isinstance(codes, list) else []):
            for cn, sc, mode in _match_codes(kv, buckets, str(cc),
                                             0.95, memo):
                hits.setdefault(cn, []).append(
                    {'raw': str(cc), 'mode': mode,
                     'score': round(sc, 3), 'src': 'vision'})
        for txt, cf in toks.get(ph['id'], []):
            txt = (txt or '').strip()
            if len(txt) < BL.MATCH_MIN_TOKEN_LEN:
                continue
            for cn, sc, mode in _match_codes(kv, buckets, txt,
                                             float(cf or 0), memo):
                hits.setdefault(cn, []).append(
                    {'raw': txt[:40], 'mode': mode,
                     'score': round(sc, 3), 'src': 'ocr'})
        for cn, arr in hits.items():
            m.setdefault(cn, {})[ph['id']] = arr

    # ⚠️ 减掉人工标记「无关联」的 (产品, 照片) 对（10-05）。
    # 在这里减、而不是让 product_candidates 自己减，是因为 cand_counts()
    # 的读码部分也吃这个 map —— 一处减，两处同步生效。列表角标与详情
    # 才不会一个减了一个没减（铁律 18：数字对不上比没有数字更伤信任）。
    rej = rejected_pairs(con)
    if rej:
        for cn in list(m):
            keep = {pid: arr for pid, arr in m[cn].items()
                    if (cn, pid) not in rej}
            if keep:
                m[cn] = keep
            else:
                del m[cn]
    return m


def cand_counts(con):
    """{code_norm: {'code': n, 'group': n}} —— 列表「待确认」的唯一来源。

      code  ：照片里读出这个编码（多模态 / OCR），还没关联 —— **强证据**
      group ：与已关联照片同一段连拍、还没关联到本产品 —— 量大，需人工判断
    """
    out = {cn: {'code': len(v), 'group': 0}
           for cn, v in cand_code_map(con).items()}
    # 同组候选：也要减掉人工标记「无关联」的（10-05）——
    # 老板在详情里看到的「同组待确认」与列表角标必须一致，
    # 减了读码不减同组（或反过来）都会让两边数字对不上。
    #
    # ⚠️ 计数口径与原 GROUP BY 版**逐张一致**：一张照片的
    # (batch_id, group_idx) 唯一，所以它对同一产品只可能落进一个组，
    # 「各组 DISTINCT 之和」==「全部 DISTINCT」。改用 Python 集合是为了
    # 能按 (code, photo) 逐对排除 —— SQL 层没法表达「这个产品否决了这张」。
    rej = rejected_pairs(con)
    seen = {}
    for r in con.execute(
            'SELECT l2.code_norm AS cn, sp.id AS pid'
            ' FROM links l2'
            ' JOIN photos lp ON lp.id=l2.photo_id'
            ' JOIN photos sp ON sp.batch_id=lp.batch_id AND sp.group_idx=lp.group_idx'
            ' WHERE lp.group_idx IS NOT NULL AND ' + _cand_filter_sql('sp') +
            ' AND sp.id NOT IN (SELECT photo_id FROM links'
            '                   WHERE code_norm=l2.code_norm)'):
        if (r['cn'], r['pid']) in rej:
            continue
        out.setdefault(r['cn'], {'code': 0, 'group': 0})
        seen.setdefault(r['cn'], set()).add(r['pid'])
    for cn, ids in seen.items():
        out[cn]['group'] = len(ids)
    return out


def product_candidates(con, code_norm, max_photos=24):
    """指定产品编码的候选未关联照片（读出来像但还没关联的）。

    **取数走 cand_code_map()** —— 与列表的「读码待确认」角标同源。
    以前这里另建一个只含单产品的 CodeIndex 自己扫一遍，口径与列表的 SQL
    不一样（它认编辑距离模糊命中、列表只认精确相等），两边必然对不上。

    用于产品详情「可能关联的图片」：列出可能属于它但尚未关联的照片，一键关联。
    """
    p = con.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                    (code_norm, code_norm)).fetchone()
    if not p:
        return []
    cn = p['code_norm']
    hits = cand_code_map(con).get(cn) or {}
    if not hits:
        return []
    ids = list(hits)
    phs = {r['id']: r for r in con.execute(
        'SELECT * FROM photos WHERE id IN (%s)' % ','.join('?' * len(ids)), ids)}
    out = []
    for pid, matches in hits.items():
        ph = phs.get(pid)
        if not ph:
            continue
        matches = sorted(matches, key=lambda x: -x['score'])
        out.append({
            'photo_id': ph['id'], 'file': ph['file'],
            'taken_at': ph['taken_at'], 'photo_kind': ph['photo_kind'],
            'thumb': '/thumb/%s' % ph['id'], 'full': '/img/%s' % ph['id'],
            'best_match': matches[0],
            'all_matches': matches[:6],
        })
    out.sort(key=lambda x: (-(x['best_match']['mode'] == 'exact'),
                            -x['best_match']['score']))
    return out[:max_photos]


def confirm_merge(con, code_norm, photo_ids, by='user'):
    """人工确认合并建议：把照片批量关联到该产品（source=manual，可追溯）。"""
    n = 0
    for pid in (photo_ids or []):
        if not con.execute('SELECT id FROM photos WHERE id=?', (pid,)).fetchone():
            continue
        link(con, code_norm, pid, source='manual', confidence=1.0,
             evidence='合并建议人工确认', created_by=by)
        n += 1
    return {'code_norm': code_norm, 'linked': n}


# ═══════════════════════════════════════════════════════════════════
# 照片的「待确认关联 / 新产品确认」两个集合（2026-10-07 老板需求）
#
# 目标：照片页与向导③要能按「待确认关联」「新产品确认」分组看照片。
#
# 🔴 **口径必须与既有页面同源，绝不另写一套判定**（铁律 23：数字对不上
#    比没有数字更伤信任）：
#   · 待确认关联 = cand_code_map() 里出现过的照片 —— 与标准产品库列表的
#     「N 待关」角标、产品详情的「可能关联的图片」**同一份** map
#     （含人工标记「无关联」的排除，所以标过就不在这组里，与角标同步降）。
#   · 新产品确认 = discovered_products() 里 photo_ids 的并集 —— 与
#     「新产品确认」页候选卡**同一份**取数（含忽略名单与置信度门槛）。
#
# 两者都**只含未关联照片**（cand_code_map 与 discovered_products 都排除了
# 已关联的），所以它们是「未关联」的子集，一个选项卡可以同时属于多组。
# ═══════════════════════════════════════════════════════════════════

_NP_CACHE = {'stamp': None, 'map': None, 'ts': 0.0}


def _np_stamp(con):
    """新产品候选集合的库内容戳。

    ⚠️ 必须算上 `discover_ignore` 的行数：忽略一个候选编码只是从
    discover_ignore 插一行，不动 photos / ocr_tokens / products ——
    不计入戳的话，忽略后 60 秒内这里还会把它的照片算进「新产品确认」，
    老板点了忽略却没反应（与 cand_reject 同源，10-05 踩过）。
    2026-10-18 同理补 `photo_ignored=1` 的行数：本次忽略也只改这一列。
    """
    return (con.execute('SELECT COUNT(*) FROM discover_ignore').fetchone()[0],
            con.execute('SELECT COUNT(*) FROM products').fetchone()[0],
            con.execute('SELECT COUNT(*) FROM links').fetchone()[0],
            con.execute('SELECT COUNT(*) FROM photos').fetchone()[0],
            con.execute('SELECT COUNT(*) FROM ocr_tokens').fetchone()[0],
            con.execute('SELECT COUNT(*) FROM photos'
                        ' WHERE IFNULL(photo_ignored,0)=1').fetchone()[0])


def newprod_photo_map(con, force=False):
    """{photo_id: [候选新产品编码, ...]} —— 「新产品确认」照片分组的数据源。

    取数**直接调 discovered_products()**，不重写一遍 OCR/多模态聚合 ——
    那个函数已经处理了：排除 products 已有编码、排除装箱单/场景照、
    置信度门槛（多模态与 OCR 两档）、discover_ignore 忽略名单。
    重写一遍必然与「新产品确认」页漂移（候选卡没了、照片还挂着）。
    """
    import time as _t
    stamp = _np_stamp(con)
    now = _t.time()
    if (not force and _NP_CACHE['map'] is not None
            and _NP_CACHE['stamp'] == stamp
            and (now - _NP_CACHE['ts']) < _CAND_TTL_SEC):
        return _NP_CACHE['map']

    out = {}
    for it in discovered_products(con):
        for pid in (it.get('photo_ids') or []):
            out.setdefault(pid, [])
            if it['code'] not in out[pid]:
                out[pid].append(it['code'])
    _NP_CACHE.update(stamp=stamp, map=out, ts=now)
    return out


def photo_where_sql(state='', kind='', batch='', usage='', unlinked=0,
                     linked=0, q='', container_id='', invalid='hide',
                     ignored='hide'):
    """照片筛选的 WHERE 片段 —— **列表与分组计数共用这一份**。

    🔴 为什么要抽出来（铁律 23 的具体形态）：选项卡徽章上的「共 N 张」和
    列表里实际渲染的条数如果各写一份 WHERE，加一个筛选条件就必然漂一位 ——
    而用户看到「未关联 128」下面只有 120 张，第一反应是数据丢了。

    [invalid] 无效照片口径（2026-10-12）：
      'hide'（默认）排除无效照片 —— 工作队列不该被拍糊/误拍的图污染；
      'only'        只看无效（管理/撤销入口）；
      'all'         含无效的全部（审计用）。

    [ignored] 本次忽略口径（2026-10-18 老板需求，与 invalid 同款三态）：
      'hide'（默认）排除已忽略 —— 忽略的照片退出一切关联队列；
      'only'        只看已忽略（「已忽略」选项卡，可恢复）；
      'all'         含忽略的全部（审计用）。
      ⚠️ 与 _UNLINKED_SQL / _cand_filter_sql 的 IFNULL(photo_ignored,0)=0
      是同一口径的两处表达：那里管「队列」，这里管「列表」。

    返回 (join_frag, where_frag, args)，拼在 `FROM photos p` 之后。
    """
    join = ''
    frag = ''
    args = []

    def add(s, a=()):
        nonlocal frag
        frag += (' AND ' if frag else ' WHERE ') + s
        args.extend(a)

    if container_id:
        join = ' JOIN batches b ON b.id=p.batch_id'
        add('b.container_id=?', [container_id])
    if invalid == 'hide':
        add('IFNULL(p.is_invalid,0)=0')
    elif invalid == 'only':
        add('IFNULL(p.is_invalid,0)=1')
    if ignored == 'hide':
        add('IFNULL(p.photo_ignored,0)=0')
    elif ignored == 'only':
        add('IFNULL(p.photo_ignored,0)=1')
    if state:
        add('p.govern_state=?', [state])
    if kind:
        # 树的「按分类」把 NULL 归到 '_unset'（与 facets 的 IFNULL 一致）——
        # 点它要按 NULL 过滤，不然点「未分类」永远 0 行（2026-10-15）
        # 多选（2026-10-19 老板需求）：逗号分隔 → IN；'_unset' 可与具体
        # 分类混选（NULL OR IN(...)）。单值走原路径（索引友好）。
        ks = [k for k in str(kind).split(',') if k]
        if '_unset' in ks:
            others = [k for k in ks if k != '_unset']
            if others:
                add('(p.photo_kind IS NULL OR p.photo_kind IN (%s))'
                    % ','.join('?' * len(others)), others)
            else:
                add('p.photo_kind IS NULL')
        elif len(ks) == 1:
            add('p.photo_kind=?', ks)
        elif ks:
            add('p.photo_kind IN (%s)' % ','.join('?' * len(ks)), ks)
    if batch:
        add('p.batch_id=?', [batch])
    if usage:
        # 多选同 kind（2026-10-19）：逗号分隔 → IN，'_unset' 可混选
        us = [u for u in str(usage).split(',') if u]
        if '_unset' in us:
            others = [u for u in us if u != '_unset']
            if others:
                add('(p.photo_usage IS NULL OR p.photo_usage IN (%s))'
                    % ','.join('?' * len(others)), others)
            else:
                add('p.photo_usage IS NULL')
        elif len(us) == 1:
            add('p.photo_usage=?', us)
        elif us:
            add('p.photo_usage IN (%s)' % ','.join('?' * len(us)), us)
    if unlinked:
        # 监装照片不进未关联（2026-10-16 老板需求：监装不需要关联）——
        # 与徽章/树/分组视图/工作台同用 _UNLINKED_SQL，数字同源。
        add(_UNLINKED_SQL)
    if linked:
        add('p.id IN (SELECT photo_id FROM links)')
    if q:
        # 复用 store._q_filter —— 与分组视图同一套口径，
        # 否则「切到分组视图后搜索结果不一样」这种 bug 必然发生。
        f2, a2 = _q_filter(q)
        s2 = f2.strip()
        if s2.upper().startswith('WHERE'):
            s2 = s2[5:].strip()
        # 🔴 _q_filter 返回的是 ' AND (...)'（为 photo_groups 的 WHERE 1=1
        #    拼接设计的形状）—— 必须把 AND 也剥掉再交给 add()，否则
        #    add 拼出 'WHERE AND (...)' → near "AND" 语法错（2026-10-14
        #    老板实测：照片库搜索任何关键词都 500）。
        if s2.upper().startswith('AND'):
            s2 = s2[3:].strip()
        if s2:
            add(s2, a2)
    return join, frag, args


def photo_flag_counts(con, container_id='', batch_id='', state='', kind='',
                      usage='', q='', unlinked=0, invalid='hide', pending=0,
                      todo=''):
    """五档分组计数（全部 / 已关联 / 待关联 / 待确认关联 / 新产品确认）。

    [container_id/batch_id] 给了就只数该范围（向导③按柜、照片页按筛选）。
    [state/kind/usage/q/unlinked/invalid] 完整筛选上下文（2026-10-14）：
      左侧树选了用途/分类后，徽章与「共 N 张」必须跟着收窄 —— 与列表
      **同一个 photo_where_sql**，不给这几个参数统计就永远显示全范围。

    ⚠️ 「待关联」口径（2026-10-17 老板规则「只有产品需要关联」）：无 links、
    非重复、且**分类是产品图**（label/product，白名单 _UNLINKED_SQL）。
    所以「待确认 + 新产品」之和 ≤ 待关联 —— 差值是重复照片与
    包装/清单/其他预检/场景/未识别这些非产品照。
    计数与 /api/photos 的筛选**同一个 WHERE 拼装函数**（photo_where_sql），
    否则徽章数字与列表条数会漂。
    [pending] 1 = 整个计数按「监装细分待确认」集合收窄（③待办视图的
      「共 N 张」应该是待办数，不是全柜数）。
    [todo] 'cand' / 'newprod'（2026-10-15 需求3：待办进查询条件）——
      整个计数（含 invalid 档）按对应待办集合收窄，与列表同一口径。
    """
    join, where, args = photo_where_sql(state=state, kind=kind, batch=batch_id,
                                        usage=usage, q=q, unlinked=unlinked,
                                        container_id=container_id,
                                        invalid=invalid)
    # 关联待办收窄（需求3）：把待办集合作为 id 条件追加进 WHERE ——
    # 徽章、列表、facets 三处必须同一口径，否则「树上计数与列表对不上」。
    if todo in ('cand', 'newprod'):
        ids = set(cand_photo_ids(con)) if todo == 'cand' \
            else set(newprod_photo_map(con))
        if container_id:
            scope = {r[0] for r in con.execute(
                'SELECT p.id FROM photos p JOIN batches b ON b.id=p.batch_id'
                ' WHERE b.container_id=?', [container_id])}
            ids &= scope
        ids = sorted(ids)
        if not ids:
            return {'all': 0, 'linked': 0, 'unlinked': 0, 'invalid': 0,
                    'ignored': 0,
                    'cand': 0, 'newprod': 0, 'cand_ids': [], 'newprod_ids': []}
        parts, ea = [], []
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            parts.append('p.id IN (%s)' % ','.join('?' * len(chunk)))
            ea.extend(chunk)
        suffix = '(%s)' % ' OR '.join(parts)
        where += (' WHERE ' if not where.strip() else ' AND ') + suffix
        args = list(args) + ea
    # ⚠️ join 必须拼进来：container_id 筛在 b.container_id 上，
    #    漏了 join 就是「no such column: b.container_id」。
    base = 'FROM photos p' + join + where

    def one(extra, ea=()):
        # 没有筛选条件时 base 后面直接接 ' AND ...' 会语法错 —— 补一个 WHERE。
        tail = (' WHERE ' + extra[5:]) if (extra.startswith(' AND ') and not where) \
            else extra
        return con.execute('SELECT COUNT(*) ' + base + tail,
                           list(args) + list(ea)).fetchone()[0]

    # 🔴 入参 unlinked 会被下面 `unlinked = one(...)` 覆盖成**计数值** ——
    #    尾部 invalid 档计算要用的必须是原始入参（2026-10-15 CDP 实测抓到：
    #    invalid 徽章少 1，因为把「未关联数」当筛子传了进去）。
    unlinked_arg = unlinked

    pend_ids = None
    if pending:
        if not container_id:
            return {'all': 0, 'linked': 0, 'unlinked': 0, 'invalid': 0,
                    'ignored': 0,
                    'cand': 0, 'newprod': 0, 'cand_ids': [], 'newprod_ids': []}
        # 与③待办同一集合（supervision_pending_of 已含 invalid=0 口径）
        pend_ids = [r['photo_id']
                    for r in supervision_pending_of(con, container_id)['items']]
        if not pend_ids:
            return {'all': 0, 'linked': 0, 'unlinked': 0, 'invalid': 0,
                    'ignored': 0,
                    'cand': 0, 'newprod': 0, 'cand_ids': [], 'newprod_ids': []}
        parts, ea = [], []
        for i in range(0, len(pend_ids), 400):
            chunk = pend_ids[i:i + 400]
            parts.append('p.id IN (%s)' % ','.join('?' * len(chunk)))
            ea.extend(chunk)
        pextra = ' AND (%s)' % ' OR '.join(parts)
        all_n = one(pextra, ea)
        linked = one(pextra + ' AND p.id IN (SELECT photo_id FROM links)', ea)
        unlinked = one(pextra + ' AND ' + _UNLINKED_SQL, ea)
        cand_ids = sorted(set(pend_ids) & set(cand_photo_ids(con)))
        np_ids = sorted(set(pend_ids) & set(newprod_photo_map(con)))
        return {'all': all_n, 'linked': linked, 'unlinked': unlinked,
                'invalid': 0, 'ignored': 0,
                'cand': len(cand_ids), 'newprod': len(np_ids),
                'cand_ids': cand_ids, 'newprod_ids': np_ids}

    all_n = one('')
    linked = one(' AND p.id IN (SELECT photo_id FROM links)')
    unlinked = one(' AND ' + _UNLINKED_SQL)

    # 两个「待办」集合是 Python 算的（模糊匹配 / OCR 聚合），落到 SQL 只能
    # 把 id 集合灌进 IN。单次几百个参数可接受；>999 就分批用 OR 串。
    scope_pids = None
    if container_id or batch_id:
        # 一次性取范围内的 id 集合，再和两个待办集合取交集 ——
        # ⚠️ 不能只靠外层 SQL 的 WHERE：cand/newprod 的 id 列表是 Python 算的，
        #    不在这里收窄的话，按柜/按批次筛选后徽章仍会显示全库的数
        #    （「向导③只看本柜」却挂着别的柜的待确认数 = 数字撒谎）。
        if container_id:
            sql = ('SELECT p.id FROM photos p JOIN batches b ON b.id=p.batch_id'
                   ' WHERE b.container_id=?')
            par = [container_id]
            if batch_id:
                sql += ' AND p.batch_id=?'
                par.append(batch_id)
        else:
            sql = 'SELECT id FROM photos WHERE batch_id=?'
            par = [batch_id]
        scope_pids = {r[0] for r in con.execute(sql, par)}

    def _count_in(ids):
        ids = [i for i in ids if scope_pids is None or i in scope_pids]
        if not ids:
            return 0, []
        parts, ea = [], []
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            parts.append('p.id IN (%s)' % ','.join('?' * len(chunk)))
            ea.extend(chunk)
        return one(' AND (%s)' % ' OR '.join(parts), ea), ids

    cand_n, cand_ids = _count_in(sorted(cand_photo_ids(con)))
    np_n, np_ids = _count_in(sorted(newprod_photo_map(con)))
    # 无效图片档（2026-10-15 需求5）：同一筛选上下文，invalid 翻成 'only'
    # 再数一次 —— 与列表 flag=invalid 的 WHERE 同源，徽章不会漂。
    join_v, where_v, args_v = photo_where_sql(
        state=state, kind=kind, batch=batch_id, usage=usage, q=q,
        unlinked=unlinked_arg, container_id=container_id, invalid='only')
    if todo in ('cand', 'newprod'):
        # 与上面主计数同一条待办收窄 —— invalid 徽章和列表同源
        where_v += (' WHERE ' if not where_v.strip() else ' AND ') + suffix
        args_v = list(args_v) + ea
    invalid_n = con.execute(
        'SELECT COUNT(*) FROM photos p' + join_v + where_v,
        list(args_v)).fetchone()[0]
    # 已忽略档（2026-10-18）：invalid 翻成 only 的同款做法，ignored='only'
    join_i, where_i, args_i = photo_where_sql(
        state=state, kind=kind, batch=batch_id, usage=usage, q=q,
        unlinked=unlinked_arg, container_id=container_id, invalid='all',
        ignored='only')
    if todo in ('cand', 'newprod'):
        where_i += (' WHERE ' if not where_i.strip() else ' AND ') + suffix
        args_i = list(args_i) + ea
    ignored_n = con.execute(
        'SELECT COUNT(*) FROM photos p' + join_i + where_i,
        list(args_i)).fetchone()[0]
    return {'all': all_n, 'linked': linked, 'unlinked': unlinked,
            'invalid': invalid_n, 'ignored': ignored_n,
            'cand': cand_n, 'newprod': np_n,
            'cand_ids': cand_ids, 'newprod_ids': np_ids}


def photo_facet_counts(con, state='', kind='', batch='', q='', usage='',
                       container_id='', unlinked=0, invalid='hide', todo=''):
    """用途 / 分类（photo_kind）的分布计数 —— 左侧树形筛选的数据源。

    🔴 与 /api/photos 列表**共用 photo_where_sql**（铁律 23）：树上的数字
    和点进去看到的条数必须同源，否则「监装 37」点开是 36 张，用户第一反应
    是数据丢了。

    交叉筛选（facet 的标准行为）：传了 kind 时，用途计数反映该分类范围
    （监装照都有哪些分类）；传了 usage 时，分类计数反映该用途范围。
    两个维度各自过滤**对方**，树才不会列出一堆点进去是 0 的项。

    🔴 自身维度必须排除（2026-10-19 修多选只生效一个）：
      数「用途」时只带 kind、**不带 usage**；数「分类」时只带 usage、
      **不带 kind**。否则选中分类 A 后，kind 的 GROUP BY 结果里只剩 A
      一项，树上其他分类直接消失 —— 用户根本点不到 B，勾选框看着是多选，
      实际只能选一个（老板反馈「虽然有了多选框，但还是只能选一个」）。
      排除自身后，每项的计数 = 「单选它」的张数，点进去的条数与之一致；
      多选总条数 = 所选项计数之和（IN 是互斥并集），数字仍然可验。

    用途侧把 NULL 归到 '_unset'（未分类）—— 与前端下拉的值一致。
    """
    def _base(kind_kw, usage_kw):
        """拼一份 base（FROM+WHERE）。kind/usage 二选一带入，另一个留空。"""
        j, w, a = photo_where_sql(
            state=state, kind=kind_kw, batch=batch, q=q, usage=usage_kw,
            unlinked=unlinked, container_id=container_id, invalid=invalid)
        # 待办收窄（2026-10-15 需求3）：树上的计数与列表同一口径 ——
        # 选了「待确认关联」后，树里各分类的计数只算待办集合内的。
        if todo in ('cand', 'newprod'):
            ids = set(cand_photo_ids(con)) if todo == 'cand' \
                else set(newprod_photo_map(con))
            if container_id:
                scope = {r[0] for r in con.execute(
                    'SELECT p.id FROM photos p JOIN batches b ON b.id=p.batch_id'
                    ' WHERE b.container_id=?', [container_id])}
                ids &= scope
            ids = sorted(ids)
            parts, ea = [], []
            for i in range(0, len(ids), 400):
                chunk = ids[i:i + 400]
                parts.append('p.id IN (%s)' % ','.join('?' * len(chunk)))
                ea.extend(chunk)
            if parts:
                w += (' WHERE ' if not w.strip() else ' AND ') + \
                    '(%s)' % ' OR '.join(parts)
                a = list(a) + ea
        return 'FROM photos p' + j + w, list(a)

    # 用途分布：按已选分类收窄，不受已选用途影响（否则选了监装就只剩监装）
    base_u, args_u = _base(kind, '')
    # 分类分布：按已选用途收窄，不受已选分类影响（否则选了标签就只剩标签）
    base_k, args_k = _base('', usage)

    def group_by(base, args, col):
        # 🔴 GROUP BY 用**表达式本身**而不是 SELECT 别名：SQLite 允许别名，
        #    但混用别名与表达式在不同版本行为不一，直接写表达式最稳。
        sql = ('SELECT IFNULL(%s, \'_unset\') AS k, COUNT(*) AS n ' % col
               + base + ' GROUP BY IFNULL(%s, \'_unset\')' % col)
        return {r['k']: r['n'] for r in con.execute(sql, args)}

    return {'usage': group_by(base_u, args_u, 'p.photo_usage'),
            'kind': group_by(base_k, args_k, 'p.photo_kind')}


def cand_photo_ids(con):
    """待确认关联照片的 id 集合 = cand_code_map() 里所有 photo_id。

    ⛔ 直接取 map 的键值并集，**不重算** —— 标准产品库列表的「N 待关」
    角标吃的也是它，两处必须一致。
    """
    out = set()
    for _cn, hits in (cand_code_map(con) or {}).items():
        out.update(hits.keys())
    return out


def photo_flag_map(con, ids=None):
    """{photo_id: ['cand'|'newprod', ...]} —— 只算给定照片（不传=全量）。"""
    ids = list(ids) if ids is not None else None
    cand = cand_photo_ids(con)
    np_map = newprod_photo_map(con)
    pool = ids if ids is not None else sorted(set(cand) | set(np_map))
    out = {}
    for pid in pool:
        tags = []
        if pid in cand:
            tags.append('cand')
        if pid in np_map:
            tags.append('newprod')
        if tags:
            out[pid] = tags
    return out


# ═══════════════════════════════════════════════════════════════════
# 标准图（场景 4 的"标准格式"：人工裁剪/编辑后的标准资产）
# ═══════════════════════════════════════════════════════════════════

# 文件名里的类别标识（与 schema.PHOTO_KINDS 对应，取人可读的中文）
KIND_FILE_LABEL = {
    'label': '标识卡', 'product': '产品', 'packaging': '包装',
    'packing_list': '清单', 'scene': '场景', 'unknown': '照片',
}

_BAD_FN = re.compile(r'[\\/:*?"<>|]')


def _safe_code_dir(code_norm):
    """产品编码做标准图文件夹名（归一化后已是大写字母数字，仍兜底去非法字符）。"""
    s = _BAD_FN.sub('_', (code_norm or '').strip())
    return s or 'UNKNOWN'


def _standard_subdir(code_norm):
    """某产品的标准图目录：data/standard/<编码>/。"""
    return os.path.join(STANDARD_DIR, _safe_code_dir(code_norm))


def _next_standard_filename(subdir, label):
    """给定产品文件夹与类别标签，返回下一个不冲突的 <label>[_n].jpg 文件名。

    同类第 1 张不带序号，第 2 张起加 _n；扫描文件夹判定（不查库，避免读写竞态）。
    """
    base = _BAD_FN.sub('_', label or '照片')
    if not os.path.exists(os.path.join(subdir, base + '.jpg')):
        return base + '.jpg'
    n = 2
    while os.path.exists(os.path.join(subdir, '%s_%d.jpg' % (base, n))):
        n += 1
    return '%s_%d.jpg' % (base, n)


def _try_rmdir_empty(d):
    """删掉空文件夹（产品标准图删光后不留空目录）。忽略失败。"""
    try:
        if d and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    except OSError:
        pass


def _migrate_standard_layout(con):
    """把历史的扁平标准图（data/standard/<sid>.jpg）搬进 data/standard/<编码>/。

    🔴 幂等：已在子文件夹里的行跳过；文件已不存在则只修正路径不报错；
       单条失败不阻断其余（保留原路径，文件仍在原地）。**绝不抛异常**——
       这是 connect() 启动链路上的步骤，崩了整个产品库起不来。
    """
    import shutil
    rows = con.execute(
        'SELECT id,code_norm,kind,file FROM standard_images').fetchall()
    moved = 0
    for r in rows:
        # 🔴 全用下标：_migrate 也被 upgrade.py 的**裸连接**调用（无 row_factory），
        #    这里用 r['file'] 会抛 "tuple indices must be integers" —— 而且它抛在
        #    **启动链路上**，整个产品库起不来。2026-10-11 发 v0.7.0 时实测踩到。
        sid, cnorm, kind, sfile = r[0], r[1], r[2], r[3]
        fp = sfile or ''
        # 只处理「直接躺在 STANDARD_DIR 下的扁平文件」；已在子目录的跳过
        if not fp or os.path.dirname(os.path.abspath(fp)) != os.path.abspath(STANDARD_DIR):
            continue
        subdir = _standard_subdir(cnorm or 'UNKNOWN')
        os.makedirs(subdir, exist_ok=True)
        label = KIND_FILE_LABEL.get(kind, '照片')
        fname = _next_standard_filename(subdir, label)
        dst = os.path.join(subdir, fname)
        try:
            if os.path.exists(fp):
                if os.path.abspath(fp) != os.path.abspath(dst):
                    shutil.move(fp, dst)
                fp = dst
            con.execute('UPDATE standard_images SET file=? WHERE id=?', (fp, sid))
            moved += 1
        except Exception:  # noqa: BLE001 —— 单条失败不阻断启动
            try:
                con.execute('UPDATE standard_images SET file=? WHERE id=?',
                            (sfile or fp, sid))
            except Exception:
                pass
    if moved:
        con.commit()


def add_standard_image(con, code_norm, src_photo_id, kind, jpg_bytes,
                       width=None, height=None, by='user', origin=None,
                       orig_name=None):
    """保存一张标准图：文件落 STANDARD_DIR，记录挂产品+源照片。

    [origin] 'crop'（默认，从库内照片裁剪）/ 'upload'（用户直接上传的文件）。
    upload 时 src_photo_id 存哨兵值 schema.UPLOAD_SENTINEL（表约束 NOT NULL），
    读取侧一律按 origin 过滤，不拿它去 join photos。
    """
    if kind not in schema.PHOTO_KINDS:
        kind = 'unknown'
    origin = origin if origin in ('crop', 'upload') else 'crop'
    sid = uuid.uuid4().hex[:12]   # 行主键（与文件名脱钩，文件名走可读的类别命名）
    # 🔴 落盘布局：data/standard/<编码>/<类别>[_n].jpg（一个产品一个文件夹，
    #   方便人工在磁盘上按产品浏览/管理标准图）。详见 _migrate_standard_layout。
    subdir = _standard_subdir(code_norm)
    os.makedirs(subdir, exist_ok=True)
    label = KIND_FILE_LABEL.get(kind, '照片')
    fname = _next_standard_filename(subdir, label)
    fp = os.path.join(subdir, fname)
    # 极端并发兜底：理论上同类第 2 张已被 _n 隔开，这里再防一次覆盖
    while os.path.exists(fp):
        fname = '%s_%s.jpg' % (os.path.splitext(fname)[0], uuid.uuid4().hex[:6])
        fp = os.path.join(subdir, fname)
    with open(fp, 'wb') as f:
        f.write(jpg_bytes)
    con.execute(
        'INSERT INTO standard_images(id,code_norm,src_photo_id,kind,file,'
        'width,height,created_at,created_by,origin,orig_name)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (sid, code_norm, src_photo_id, kind, fp, width, height, now_iso(), by,
         origin, orig_name))
    con.commit()
    return {'id': sid, 'file': fp, 'code_norm': code_norm, 'kind': kind,
            'width': width, 'height': height,
            'origin': origin, 'orig_name': orig_name}


def add_standard_upload(con, code_norm, kind, src_path_or_bytes, filename,
                        by='user', long_edge=2000, quality=88):
    """把用户上传的文件登记为该产品的标准图（与库内照片无关，origin='upload'）。

    处理链：EXIF 方向矫正 → 等比降采样（long_edge）→ JPEG 落盘。
    和报告用图是同一套逻辑（report_gen._prep_photo），但这里**要落盘**成资产，
    所以独立实现，不去 import report_gen（那会把 docx 依赖拖进纯数据层）。

    返回 {id, file, width, height, kind, orig_name}；解不出图不抛异常而是
    返回 error —— 一批上传里一张坏图不该让整批白传。
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover
        return {'error': '服务器缺 Pillow，无法处理图片'}
    try:
        if isinstance(src_path_or_bytes, (bytes, bytearray)):
            src = io.BytesIO(bytes(src_path_or_bytes))
        else:
            src = src_path_or_bytes
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)   # 手机竖拍存的是传感器像素+Orientation
            if im.mode not in ('RGB', 'L'):
                im = im.convert('RGB')
            w, h = im.size
            if long_edge and max(w, h) > long_edge:
                sc = long_edge / float(max(w, h))
                im = im.resize((max(1, int(w * sc)), max(1, int(h * sc))),
                               Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format='JPEG', quality=quality, optimize=True)
            data = buf.getvalue()
            fw, fh = im.size     # ⚠️ 必须在 with 块内取：出了块 image 已关闭
    except Exception as e:  # noqa: BLE001
        return {'error': '%s 不是可读的图片（%s）' % (filename or '文件',
                                                   type(e).__name__)}
    r = add_standard_image(con, code_norm, schema.UPLOAD_SENTINEL, kind, data,
                           fw, fh, by=by, origin='upload', orig_name=filename)
    r['bytes'] = len(data)
    return r


def standard_images(con, code_norm, origin=None):
    """某产品的全部标准图（按时间升序；同秒内按插入顺序）。

    [origin] 过滤来源；None = 全部（默认，界面要看到上传的图）。
    """
    if origin:
        # 老数据 origin 为 NULL（=crop），所以 crop 要写成 (origin IS NULL OR origin='crop')
        if origin == 'crop':
            return con.execute(
                "SELECT * FROM standard_images WHERE code_norm=?"
                " AND IFNULL(origin,'crop')='crop' ORDER BY created_at, rowid",
                (code_norm,)).fetchall()
        return con.execute(
            'SELECT * FROM standard_images WHERE code_norm=? AND origin=?'
            ' ORDER BY created_at, rowid', (code_norm, origin)).fetchall()
    return con.execute(
        'SELECT * FROM standard_images WHERE code_norm=? ORDER BY created_at, rowid',
        (code_norm,)).fetchall()


def standard_for_photo(con, photo_id):
    """某源照片最新的一张标准图（导出时替代原图用）。
    created_at 只有秒级精度，同秒多次保存用 rowid 定先后。

    ⚠️ 必须排除 origin='upload'：上传的标准图 src_photo_id 是哨兵值，
    拿它当 photo_id 匹配会串到不相干的照片上。
    """
    return con.execute(
        "SELECT * FROM standard_images WHERE src_photo_id=?"
        " AND IFNULL(origin,'crop')='crop'"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (photo_id,)).fetchone()


def delete_standard_image(con, sid):
    """删除标准图（记录 + 文件 + 空掉的产品文件夹）。"""
    r = con.execute('SELECT file FROM standard_images WHERE id=?', (sid,)).fetchone()
    if not r:
        return 0
    con.execute('DELETE FROM standard_images WHERE id=?', (sid,))
    con.commit()
    fp = r['file']
    try:
        if fp and os.path.exists(fp):
            os.remove(fp)
            _try_rmdir_empty(os.path.dirname(fp))   # 这产品没标准图了就删空目录
    except OSError:
        pass
    return 1


# ═══════════════════════════════════════════════════════════════════
# 标准库落盘（场景 4：人工审核确认的产品库 → 本地目录）
# ═══════════════════════════════════════════════════════════════════

# 文件名里的类别标识（KIND_FILE_LABEL / _BAD_FN 已上移到标准图区块顶部，
# 与 add_standard_image 共用 —— 这里不再重复定义）。

def export_standard(con, out_dir):
    """把已审核（confirmed）产品的照片与标准图复制到 out_dir。

    三类图源，优先级从高到低：
      1. 手动上传的标准图（origin='upload'）—— 老板直接传的标准图，最权威
      2. 库内照片裁剪出的标准图（origin='crop'）
      3. 关联照片原图（回退）

    ⚠️ 手动上传的图**不在**照片循环里（原逻辑只看 links→photos），
       且 `WHERE photo_count>0` 会把「没关联照片但上传了标准图」的产品整条漏掉 ——
       上传了却在导出目录里看不到，等于白传（2026-10-06 修）。

    命名：{产品编码}_{类别}[_n].jpg —— 第 1 张不带序号，同类第 2 张起加 _n；
    按 taken_at 排序保证重复导出文件名稳定（幂等，同名覆盖）。
    附 standard_index.csv（utf-8-sig，Excel 直开不乱码）。
    复制不移动，源照片库不动。
    """
    import shutil
    import csv
    os.makedirs(out_dir, exist_ok=True)
    prods = con.execute(
        "SELECT * FROM products WHERE review_state='confirmed'"
        " AND (photo_count>0 OR EXISTS"
        "      (SELECT 1 FROM standard_images si WHERE si.code_norm=products.code_norm))"
        ' ORDER BY code_norm').fetchall()
    n_photos = 0
    n_upload = 0
    missing = []
    csv_rows = []
    for p in prods:
        photos = [r for r in product_photos(con, p['code_norm']) if not r['is_dup']]
        photos.sort(key=lambda r: (r['taken_at'] or '', r['id']))
        counters = {}

        def _emit(src_path, kind, origin_label, link_src, conf, taken):
            """按类别计数命名并复制，返回是否成功。"""
            nonlocal n_photos
            lbl = KIND_FILE_LABEL.get(kind, '照片')
            counters[lbl] = counters.get(lbl, 0) + 1
            stem = '%s_%s' % (_BAD_FN.sub('_', p['code']), lbl)
            if counters[lbl] > 1:
                stem += '_%d' % counters[lbl]
            dst = os.path.join(out_dir, stem + '.jpg')
            if not os.path.exists(src_path or ''):
                return stem, False
            shutil.copy2(src_path, dst)
            n_photos += 1
            csv_rows.append([p['code'], p['name'] or '', p['spec'] or '',
                             stem + '.jpg', lbl, link_src or '', conf,
                             taken or '', origin_label])
            return stem, True

        # ① 手动上传的标准图（一个产品允许多张，逐张导出）
        for s in standard_images(con, p['code_norm'], origin='upload'):
            stem, ok = _emit(s['file'], s['kind'],
                             '标准图(上传:%s)' % (s['orig_name'] or ''),
                             'upload', None, s['created_at'])
            if ok:
                n_upload += 1
            else:
                missing.append(s['id'])

        # ②③ 库内照片：做过标准图的用标准图，否则回退原图
        for r in photos:
            std = standard_for_photo(con, r['id'])
            if std:
                src_path, kind, ol = std['file'], std['kind'], '标准图(裁剪)'
            else:
                src_path, kind, ol = r['path'], (r['photo_kind'] or 'unknown'), '原图'
            _stem, ok = _emit(src_path, kind, ol, r['source'], r['confidence'],
                              r['taken_at'])
            if not ok:
                missing.append(r['id'])
    with open(os.path.join(out_dir, 'standard_index.csv'), 'w',
              newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['产品编码', '品名', '规格', '文件名', '照片类别',
                    '关联来源', '置信度', '拍摄时间', '图源'])
        w.writerows(csv_rows)
    return {'products': len(prods), 'photos': n_photos, 'uploaded': n_upload,
            'missing': len(missing), 'dir': out_dir}


# ═══════════════════════════════════════════════════════════════════
# 报告素材（大整合第 2 定位点：预检结果快速匹配）
#
# 输入一份货品编码清单 → 从产品标准库 + 指定照片批次里
# 给每个货品检索可用照片，并给出建议（标准图 > 最新 > 高清）。
# 报告写作要的是"每个货品一张拿得出手的图"，所以默认只导建议采用的那张。
# ═══════════════════════════════════════════════════════════════════

# 自动选图策略（2026-10-09 老板需求：选图时要能选「优先标准图 / 优先最新图」等）。
# 🔴 'balanced' 必须是默认且**行为与加策略之前逐位一致** —— 既有测试
#    （units.py）断言了「recommended 是特定那张」，改坏它就是对全量用户的静默回归。
PICK_STRATEGIES = ('balanced', 'std', 'latest', 'hd', 'near_std')
PICK_STRATEGY_LABELS = {
    'balanced': '均衡（标准图 / 最新 / 高清 综合打分）',
    'std':      '优先标准图',
    'latest':   '优先最新图',
    'hd':       '优先高清（同组体积最大）',
    'near_std': '优先近标准图（与标准参考图最像）',
}


def _pick_ranks(items, meta, con, ref_hash, strategy):
    """按策略给出每张候选的**主次序**（小的在前）。返回 None = 不额外排序。

    🔴 为什么用「主次序」而不是只调权重：打分最后有 `min(0.99, score)` 封顶，
    权重一旦加大就全部塌成 0.99 → 全平局 → 主条件反而失效（「优先标准图」
    变成「优先标准图里最早那张」）。主次序是确定性的名次，不受封顶影响。
    """
    if strategy == 'std':
        return [0 if meta[i['photo_id']]['std'] else 1 for i in items]
    if strategy == 'latest':
        _o = sorted(items, key=lambda x: (meta[x['photo_id']]['taken'], x['file']),
                    reverse=True)
        _pos = {i['photo_id']: n for n, i in enumerate(_o)}
        return [_pos[i['photo_id']] for i in items]
    if strategy == 'hd':
        _o = sorted(items, key=lambda x: (meta[x['photo_id']]['bytes'], x['file']),
                    reverse=True)
        _pos = {i['photo_id']: n for n, i in enumerate(_o)}
        return [_pos[i['photo_id']] for i in items]
    if strategy == 'near_std':
        # 该产品**没有**标准参考图时，这个策略无从谈起 —— 退回均衡排序，
        # 而不是把「算不出距离」当 0 硬排（那会变成随机优先）。
        if ref_hash is None:
            return None
        out = []
        for i in items:
            d = _phash_dist(ref_hash, _phash_by_id(con, i['photo_id']))
            out.append(999 if d is None else d)
        return out
    return None      # balanced：沿用既有打分顺序


_CAM_NAME_RE2 = re.compile(r'^(?:IMG_|P_|DSC_)')


def _dedup_same_shot(rows):
    """同一快门的不同来源副本只留一张（相机原图优先）。

    实测（2026-10-20 老板反馈选图里有重复图）：同一张货的照片会同时存在
    `IMG_20260927_113549.jpg`（相机原图，历史图片批次）和
    `20260927_113549_00447.jpg`（App 采集版，标准产品库导入时造的 `p_` 虚拟 id），
    两者是**同一张图**、都关联了同一编码 → 选图页平铺就看成了"重复图片"。
    照片库看不到是因为按组折叠。

    🔴 判据必须同时满足「同目录 + 同一秒 + 一组有相机原图、另一组有 App 版」：
      · App 自己的连拍（`..._00447` / `..._00448`，同秒）**都是 App 命名**，不动 ——
        否则会误删真实连拍（第一版按"剥掉末尾序号"判重，实测就把这两张合并了）；
      · 相机连拍（同秒多张 IMG_）也原样保留；
      · 只有「同秒里既有 IMG_ 又有 App 版」才认定是同一快门的两种副本。
    """
    groups = {}
    for r in rows:
        key = (os.path.dirname(r['file'] or ''), (r['taken_at'] or '')[:19])
        groups.setdefault(key, []).append(r)

    def is_cam(r):
        return bool(_CAM_NAME_RE2.match(os.path.basename(r['file'] or '')))

    keep = set()
    for _key, lst in groups.items():
        cams = [r for r in lst if is_cam(r)]
        apps = [r for r in lst if not is_cam(r)]
        if cams and apps:
            # 同一快门两种副本：只留原图里最大的那张（更清晰）
            keep.add(max(cams, key=lambda r: r['bytes'] or 0)['id'])
        else:
            keep.update(r['id'] for r in lst)
    return [r for r in rows if r['id'] in keep]


def report_lookup(con, codes, batch_ids=None, per_code=24,
                  std_only=False, std_prefer=True, container_id=None,
                  strategy='balanced'):
    """按编码清单检索报告素材。

    [codes]：编码列表（原始字面值即可，内部归一化）。
    [batch_ids]：只在这些照片批次里找；空 = 全库找。
    [std_only]：只返回做过标准图的照片。
    [std_prefer]：标准图在排序中加权（默认 True，关掉后标准图不加权）。
    [strategy]：自动选图策略（见 PICK_STRATEGIES），默认 balanced = 原有行为。
        决定 `recommended`（建议采用）给哪一张。
    [container_id] 柜号（10-05）：每个编码额外给 `in_container` / `container_n`
    —— **该柜内**有没有关联照片。缺了它，界面只能报「检索缺口」，用户分不清
    「这个件报告⑥会没有」和「照片在别的批次、与报告无关」两件事（v4.1 分析 P0-3）。
    返回 list[dict]，顺序与输入一致 —— 缺口（库内无此编码或无照片）原样
    占位返回，**不静默丢弃**：报告里"哪个货品没图"和"有图"同样重要。

    每张候选带标签与理由（G3）：
      标准图 +0.40 / 最新 +0.15 / 高清(同组 bytes 最大) +0.10 / 近标准图 +0.12。
    「近标准参考图」仅当该产品已做过标准图时启用（2026-09-27 拍板）：
      pHash 汉明距离与该产品最新标准图比较，最小且 ≤32/64 才标。
    score 最高者为 recommended（建议采用）；平分取拍摄时间新的。
    """
    bset = [b for b in (batch_ids or []) if b]
    std_bonus = 0.40 if std_prefer else 0.0
    # 柜内批次集合 + 该柜清单里「编码 -> 箱号列表」（都一次查完，别在循环里查）
    # 箱号要收全：同一编码可能分装在多个箱（10-06 老板要求图注列出所有箱）
    cbset = None
    cartons_by_code = {}
    if container_id:
        cbset = {r['id'] for r in con.execute(
            'SELECT id FROM batches WHERE container_id=?', (container_id,))}
        for r in con.execute(
                'SELECT cr.code_norm, cr.package_no FROM checklist_rows cr'
                ' JOIN batches b ON b.id=cr.batch_id'
                ' WHERE b.container_id=? AND IFNULL(cr.package_no, "") != ""',
                (container_id,)):
            lst = cartons_by_code.setdefault(r['code_norm'], [])
            if r['package_no'] not in lst:
                lst.append(r['package_no'])
    out = []
    for raw in codes:
        c = str(raw or '').strip()
        if not c:
            continue
        nrm = BL.normalize(c)
        p = con.execute('SELECT * FROM products WHERE code_norm=? OR code=?',
                        (nrm, c)).fetchone()
        if not p:
            out.append({'input': c, 'found': False, 'reason': '库内无此编码',
                        'code': c, 'photos': [],
                        'in_container': (0 if cbset is not None else None),
                        'container_n': (0 if cbset is not None else None)})
            continue
        # ⚠️ base = 不受批次限制的全库结果；scoped = 加上所选批次后的结果。
        #    两者必须分开算 —— 以前只算一个，导致「全库根本没有照片」和
        #    「照片在别的批次」都报成「所选批次内无照片」，老板据此以为数据丢了
        #    （实际标准产品页能看见，因为它从不按批次过滤）。10-05。
        # 同一快门的不同来源副本（相机原图 + App 采集版）在**最外层**就去重，
        # 让 scoped / photo_count / in_container / container_n 全部同源 ——
        # 只在 scoped 上去重会让「N 张可用」和「柜内 N 张」对不上。
        base = _dedup_same_shot(
            [r for r in product_photos(con, p['code_norm']) if not r['is_dup']])
        if std_only:
            base = [r for r in base if standard_for_photo(con, r['id'])]
        scoped = [r for r in base if r['batch_id'] in bset] if bset else base
        if not scoped:
            if not base:
                # 真缺口：全库都没有 —— 别把锅甩给批次
                reason = '编码在库但没有' + ('做过标准图的照片' if std_only else '关联照片')
                out.append({'input': c, 'found': False, 'reason': reason,
                            'code': p['code'], 'code_norm': p['code_norm'],
                            'name': p['name'], 'spec': p['spec'], 'photos': [],
                            'in_container': (0 if cbset is not None else None),
                            'container_n': (0 if cbset is not None else None)})
            else:
                # 假缺口：照片在，只是不在所选批次里 —— 说清楚在哪、多少张
                cnt = {}
                for r in base:
                    cnt[r['batch_id']] = cnt.get(r['batch_id'], 0) + 1
                others = [{'id': b or '', 'name': _batch_name(con, b), 'n': n}
                          for b, n in sorted(cnt.items(), key=lambda x: -x[1])]
                reason = '所选批次内无照片（其他 %d 个批次共 %d 张）' % (
                    len(others), len(base))
                # 该柜内有没有这张图（界面据此区分「影响报告⑥」与「只是检索范围」）
                _in_c = (len([r for r in base if r['batch_id'] in cbset])
                         if cbset is not None else None)
                out.append({'input': c, 'found': False, 'reason': reason,
                            'code': p['code'], 'code_norm': p['code_norm'],
                            'name': p['name'], 'spec': p['spec'], 'photos': [],
                            'other_batches': others, 'other_count': len(base),
                            'in_container': _in_c, 'container_n': _in_c})
            continue

        ref = standard_ref(con, p['code_norm'])
        ref_hash = _phash(ref) if ref else None

        max_taken = max((r['taken_at'] or '') for r in scoped)
        max_bytes = max((r['bytes'] or 0) for r in scoped)
        items = []
        meta = {}          # photo_id -> 策略排序用的原始量（不污染返回结构）
        for r in scoped:
            tags, score, reasons = [], 0.50, []
            has_std = bool(standard_for_photo(con, r['id']))
            meta[r['id']] = {'std': 1 if has_std else 0,
                             'taken': r['taken_at'] or '',
                             'bytes': r['bytes'] or 0}
            if has_std:
                tags.append('标准图')
                score += std_bonus
                if std_prefer:
                    reasons.append('做过标准图，导出优先')
            if (r['taken_at'] or '') and r['taken_at'] == max_taken:
                tags.append('最新')
                score += 0.15
                reasons.append('该货品最新拍摄（%s）' % (r['taken_at'] or '')[:10])
            if (r['bytes'] or 0) and r['bytes'] == max_bytes:
                tags.append('高清')
                score += 0.10
                reasons.append('同组中分辨率最高')
            items.append({
                'photo_id': r['id'], 'file': r['file'], 'taken_at': r['taken_at'],
                'kind': r['photo_kind'] or 'unknown', 'batch_id': r['batch_id'],
                'bytes': r['bytes'], 'source': r['source'],
                'confidence': r['confidence'], 'tags': tags,
                'score': round(min(0.99, score), 3), 'recommended': False,
                'reasons': reasons or ['备选'],
            })
        items.sort(key=lambda x: (-x['score'], x['taken_at'] or '', x['file']))
        # G3：与参考标准图最接近的一张（距离最小且 ≤32 才算像，完全不像不硬标）
        if ref_hash is not None:
            best_i, best_d = -1, 65
            for i, it in enumerate(items):
                d = _phash_dist(ref_hash, _phash_by_id(con, it['photo_id']))
                if d is not None and d < best_d:
                    best_i, best_d = i, d
            if 0 <= best_i and best_d <= 32:
                it = items[best_i]
                it['tags'].append('近标准图')
                it['score'] = round(min(0.99, it['score'] + 0.12), 3)
                it['reasons'].insert(0, '与标准参考图最接近（差异 %d/64）' % best_d)
                items.sort(key=lambda x: (-x['score'], x['taken_at'] or '', x['file']))
        # ── 自动选图策略（2026-10-09）：在既有打分之上再压一个主次序 ──
        #    balanced 不压（返回 None），排序键与上面两行**逐位一致**，行为不变。
        _rank = _pick_ranks(items, meta, con, ref_hash, strategy)
        if _rank is not None:
            items = [p[1] for p in sorted(
                zip(_rank, items), key=lambda p: (p[0], -p[1]['score'], p[1]['file']))]
            items[0]['reasons'].insert(
                0, '按策略「%s」优先选中' % PICK_STRATEGY_LABELS.get(strategy, strategy))
        items[0]['recommended'] = True
        out.append({
            'input': c, 'found': True,
            'code': p['code'], 'code_norm': p['code_norm'],
            'name': p['name'], 'spec': p['spec'],
            'photo_count': len(items),
            'photos': items[:per_code],
            # 柜内另有几张（命中的是"所选范围"里的图，报告⑥用的是柜内关联图）
            'in_container': (len([r for r in base if r['batch_id'] in cbset])
                             if cbset is not None else None),
            'container_n': (len([r for r in base if r['batch_id'] in cbset])
                            if cbset is not None else None),
        })
    if cbset is not None:
        # 图注要用的箱号：取本柜清单里该编码的**全部**箱（可能分装多箱）
        for item in out:
            key = item.get('code_norm') or BL.normalize(item.get('code') or item.get('input') or '')
            item['cartons'] = list(cartons_by_code.get(key) or [])
            item['carton'] = ' / '.join(item['cartons'])
    return out


def report_export(con, out_dir, codes, batch_ids=None, all_photos=False,
                  long_edge=1600, picks=None):
    """报告素材落盘：{序号}_{编码}/ 子文件夹 + report_index.csv + report.html。

    默认每个货品只导建议采用的那张（报告素材的典型用法）；
    [all_photos]=True 时把检索到的全部照片按建议分排序导出。
    [long_edge]：导出图长边上限（等比缩、JPEG q85，2026-09-27 拍板默认 1600）；
                 0 = 原图。
    [picks]：{编码: photo_id} 人工在检索结果里指定的采用照（G4 一键替换），
             优先于 recommended；CSV 状态记「人工指定」。
    [G5] 同时生成 report.html：单文件、内嵌缩略图、可打印（Ctrl-P 出 PDF）。
    缺口货品不建文件夹，只在 CSV 与报告里记一行状态，一眼看清缺什么。
    """
    import csv
    os.makedirs(out_dir, exist_ok=True)
    results = report_lookup(con, codes, batch_ids=batch_ids)
    pmap = {}
    for k, v in (picks or {}).items():
        if v:
            pmap[BL.normalize(str(k))] = str(v)
    csv_rows = []
    n_files = 0
    seq = 0
    html_items = []
    miss_rows = []
    for r in results:
        if not r['found']:
            csv_rows.append([r['input'], r.get('code', ''), r.get('name', ''),
                             r.get('spec', ''), '缺口', 0, '', '', '', '',
                             r['reason']])
            miss_rows.append((r['input'], r.get('reason', '')))
            continue
        seq += 1
        safe = _BAD_FN.sub('_', r['code'])
        sub = os.path.join(out_dir, '%03d_%s' % (seq, safe))
        os.makedirs(sub, exist_ok=True)
        pick_id = pmap.get(r['code_norm'])
        if all_photos:
            picked = list(r['photos'])
        else:
            chosen = next((x for x in r['photos'] if x['photo_id'] == pick_id),
                          None) if pick_id else None
            if chosen is None:
                chosen = next(x for x in r['photos'] if x['recommended'])
            picked = [chosen]
        b64_map = {}
        for i, ph in enumerate(picked, 1):
            std = standard_for_photo(con, ph['photo_id'])
            row = con.execute('SELECT path FROM photos WHERE id=?',
                              (ph['photo_id'],)).fetchone()
            _rp = resolve_photo_path(con, ph['photo_id'], row['path']) \
                if (row and not std) else None
            src = std['file'] if std else _rp
            if not src or not os.path.exists(src):
                continue
            lbl = ''.join(ph['tags']) or '照片'
            fn = '%02d_%s.jpg' % (i, lbl)
            dst = os.path.join(sub, fn)
            w, h = _copy_image(src, dst, long_edge)
            n_files += 1
            is_pick = bool(pick_id and ph['photo_id'] == pick_id)
            state = '人工指定' if is_pick else ('采用' if ph['recommended'] else '备选')
            csv_rows.append([
                '%03d' % seq, r['code'], r['name'] or '', r['spec'] or '',
                state, len(r['photos']),
                '%03d_%s/%s' % (seq, safe, fn),
                ph['taken_at'] or '', '/'.join(ph['tags']),
                ('%dx%d' % (w, h)) if w else '',
                _batch_name(con, ph['batch_id'])])
            b = _thumb_b64(dst, 320, 75)
            if b:
                b64_map[ph['photo_id']] = b
        # G5 报告数据：main = 采用照（人工指定优先于 top1）；alts = 其余前 3
        main_ph = (next((x for x in picked if x['photo_id'] == pick_id), None)
                   if pick_id else None)
        if main_ph is None:
            main_ph = next((x for x in picked if x['recommended']), None)
        main_b64, alts = None, []
        if main_ph and b64_map.get(main_ph['photo_id']):
            main_b64 = (b64_map[main_ph['photo_id']], main_ph)
        for x in picked:
            if x is main_ph:
                continue
            b = b64_map.get(x['photo_id'])
            if b and len(alts) < 3:
                alts.append((b, x))
        html_items.append((seq, r, main_b64, alts))
    with open(os.path.join(out_dir, 'report_index.csv'), 'w',
              newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['序号', '产品编码', '品名', '规格', '状态', '可用照片数',
                    '文件', '拍摄时间', '照片标签', '尺寸', '来源批次/缺口原因'])
        w.writerows(csv_rows)
    html_path = _write_report_html(out_dir, html_items, miss_rows,
                                   len(results), batch_ids)
    return {'codes': len(results), 'matched': sum(1 for r in results if r['found']),
            'missing': sum(1 for r in results if not r['found']),
            'files': n_files, 'dir': out_dir, 'report_html': html_path}


def _batch_name(con, batch_id):
    if not batch_id:
        return ''
    r = con.execute('SELECT name FROM batches WHERE id=?', (batch_id,)).fetchone()
    return r['name'] if r else batch_id


# ── 报告素材的支撑工具（G2/G3/G5）──────────────────────────────────

def standard_ref(con, code_norm):
    """该产品最新的标准图文件路径 —— 「近标准参考图」的比较基准（G3）。
    没有标准图或文件缺失返回 None，调用方据此跳过该标签。"""
    r = con.execute('SELECT file FROM standard_images WHERE code_norm=?'
                    ' ORDER BY created_at DESC, rowid DESC LIMIT 1', (code_norm,)).fetchone()
    return r['file'] if r and r['file'] and os.path.exists(r['file']) else None


_PHASH_CACHE = {}   # photo_id -> 64bit hash（进程内缓存；server 常驻时二次检索零开销）
_DCT_COS = None


def _dct_cos():
    """32 点 DCT-II 余弦表（只取前 8 个低频系数）。惰性初始化。"""
    global _DCT_COS
    if _DCT_COS is None:
        import math
        N, K = 32, 8
        _DCT_COS = [[math.cos(math.pi * (2 * n + 1) * k / (2 * N)) for k in range(K)]
                    for n in range(N)]
    return _DCT_COS


def _phash(path):
    """64-bit 感知哈希：32x32 灰度 → 行/列分离 DCT 取 8x8 低频 → 中位数符号位。

    ⚠️ 只用于「近标准图」提示排序（G3），不参与任何自动决策 ——
    同物不同摄通常 <20，不同物 >30，阈值 32 是宽松提示不是判定。
    JPEG 用 draft() 快速降采样解码（原图 3072x4096 全解码约 1s，draft 后 ~100ms）。
    失败返回 None（调用方跳过，不阻塞检索）。
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.draft('L', (64, 64))
            im = im.convert('L').resize((32, 32), Image.LANCZOS)
            px = list(im.getdata())
        cos = _dct_cos()
        N, K = 32, 8
        rows = [[sum(px[y * N + n] * cos[n][k] for n in range(N)) for k in range(K)]
                for y in range(N)]
        coef = [[sum(rows[y][k] * cos[y][j] for y in range(N)) for k in range(K)]
                for j in range(K)]
        vals = [coef[j][k] for j in range(K) for k in range(K)]
        srt = sorted(vals)
        med = (srt[31] + srt[32]) / 2.0
        h = 0
        for v in vals:
            h = (h << 1) | (1 if v > med else 0)
        return h
    except Exception:  # noqa: BLE001  坏图/不支持格式 → 无信号
        return None


def _phash_dist(a, b):
    if a is None or b is None:
        return None
    return bin(a ^ b).count('1')


def _phash_by_id(con, photo_id):
    if photo_id in _PHASH_CACHE:
        return _PHASH_CACHE[photo_id]
    r = con.execute('SELECT path FROM photos WHERE id=?', (photo_id,)).fetchone()
    h = _phash(r['path']) if r and r['path'] and os.path.exists(r['path']) else None
    _PHASH_CACHE[photo_id] = h
    return h


def _copy_image(src, dst, long_edge):
    """复制一张图（[long_edge]>0 时等比压缩为 JPEG q85），返回 (w,h)。

    压缩失败回退原样复制 —— 素材完整性优先于体积优化。"""
    import shutil
    try:
        from PIL import Image
    except ImportError:
        shutil.copy2(src, dst)
        return (0, 0)
    if not long_edge or long_edge <= 0:
        shutil.copy2(src, dst)
        try:
            with Image.open(dst) as im:
                return im.size
        except Exception:  # noqa: BLE001
            return (0, 0)
    try:
        with Image.open(src) as im:
            im = im.convert('RGB')
            w, h = im.size
            if max(w, h) > long_edge:
                rr = long_edge / float(max(w, h))
                im = im.resize((max(1, int(w * rr)), max(1, int(h * rr))), Image.LANCZOS)
            im.save(dst, 'JPEG', quality=85)
            return im.size
    except Exception:  # noqa: BLE001
        shutil.copy2(src, dst)
        try:
            with Image.open(dst) as im:
                return im.size
        except Exception:  # noqa: BLE001
            return (0, 0)


def _thumb_b64(path, long_edge=320, quality=75):
    """生成内嵌报告用的 JPEG base64。失败返回 None。"""
    import base64
    import io
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert('RGB')
            w, h = im.size
            if max(w, h) > long_edge:
                rr = long_edge / float(max(w, h))
                im = im.resize((max(1, int(w * rr)), max(1, int(h * rr))), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=quality)
        return base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:  # noqa: BLE001
        return None


def _write_report_html(out_dir, html_items, miss_rows, n_total, batch_ids):
    """生成单文件可打印报告（G5，2026-09-27 拍板）。

    html_items: [(seq, lookup结果, (main_b64, photo)|None, [(b64, photo), ...])]
    打印友好（@media print 分页控制），浏览器 Ctrl-P 直接出 PDF。
    返回文件路径；一个货品图都没有时也写文件（含缺口表），不留空悬念。
    """
    from datetime import datetime as _dt
    items_html = []
    for seq, r, main, alts in html_items:
        code_h = esc_h('%03d · %s' % (seq, r['code']))
        nm = ' · '.join(x for x in (r.get('name'), r.get('spec')) if x)
        body = ''
        if main:
            b64, ph = main
            body += ('<div class="main"><img src="data:image/jpeg;base64,%s">'
                     '<div class="cap">建议采用 · 标签 %s · 拍摄 %s</div></div>'
                     % (b64, esc_h('/'.join(ph['tags']) or '—'),
                        esc_h((ph['taken_at'] or '').replace('T', ' ')[:16])))
        else:
            body += '<div class="cap">导出文件缺失，图片未嵌入</div>'
        if alts:
            figs = ''.join(
                '<figure><img src="data:image/jpeg;base64,%s"><figcaption>%s</figcaption></figure>'
                % (b64, esc_h('/'.join(p['tags']) or '备选'))
                for b64, p in alts)
            body += '<div class="alts-title">备选</div><div class="alts">%s</div>' % figs
        items_html.append('<div class="item"><div class="hd"><span class="code">%s</span>'
                          '<span class="nm">%s</span></div>%s</div>'
                          % (code_h, esc_h(nm), body))
    miss_html = ''
    if miss_rows:
        rows = ''.join('<tr class="miss"><td>%s</td><td>%s</td></tr>'
                       % (esc_h(a), esc_h(b)) for a, b in miss_rows)
        miss_html = ('<h2>缺口（%d）</h2><table><thead><tr><th style="width:220px">编码</th>'
                     '<th>原因</th></tr></thead><tbody>%s</tbody></table>'
                     % (len(miss_rows), rows))
    html = REPORT_HTML_TMPL % dict(
        date=_dt.now().strftime('%Y-%m-%d %H:%M'),
        n_total=n_total, n_ok=len(html_items), n_miss=len(miss_rows),
        batch_txt=esc_h('指定 %d 个批次' % len(batch_ids)) if batch_ids else '全部批次',
        items='\n'.join(items_html), miss=miss_html)
    fp = os.path.join(out_dir, 'report.html')
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(html)
    return fp


def esc_h(s):
    return (str(s or '').replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


REPORT_HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>预检报告素材 · %(date)s</title>
<style>
body{margin:0;background:#0e1a2b;color:#1f2328;font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.sheet{background:#fff;max-width:900px;margin:24px auto;padding:32px 40px;border-radius:10px}
h1{font-size:20px;margin:0 0 4px}
.meta{color:#6b7280;font-size:13px;margin-bottom:20px;padding-bottom:12px;border-bottom:2px solid #0e1a2b}
.item{padding:14px 0;border-bottom:1px solid #eef0f3;page-break-inside:avoid}
.item .hd .code{font-family:Consolas,monospace;font-size:15px;font-weight:600}
.item .hd .nm{color:#6b7280;margin-left:10px;font-size:13px}
.main{margin-top:10px}.main img{max-width:100%%;max-height:420px;border:1px solid #e3e6ea;border-radius:6px}
.cap{font-size:12px;color:#6b7280;margin-top:4px}
.alts-title{font-size:12px;color:#9aa1ab;margin-top:10px}
.alts{display:flex;gap:10px;flex-wrap:wrap}
.alts figure{margin:0;width:170px}
.alts img{width:100%%;height:120px;object-fit:cover;border:1px solid #e3e6ea;border-radius:6px}
.alts figcaption{font-size:11px;color:#9aa1ab;margin-top:2px}
h2{font-size:15px;margin:24px 0 8px}
table{width:100%%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid #eef0f3;text-align:left}
th{background:#f6f7f9}
tr.miss td{color:#b42318;background:#fffafa}
@media print{body{background:#fff}.sheet{margin:0;padding:10px 0;max-width:none;border:0}img{max-height:380px}}
</style></head><body><div class="sheet">
<h1>预检报告素材</h1>
<div class="meta">生成时间 %(date)s · 货品 %(n_total)s 项：命中 %(n_ok)s · 缺口 %(n_miss)s · 检索范围 %(batch_txt)s</div>
%(items)s
%(miss)s
</div></body></html>
"""


# ═══════════════════════════════════════════════════════════════════
# 柜号（批次号）关联：清单批次列表 + 某批次的产品编码
# ═══════════════════════════════════════════════════════════════════

def list_checklist_batches(con):
    """返回所有清单导入批次（含柜号、产品数、导入时间），按时间倒序。"""
    rows = con.execute(
        'SELECT b.id, b.name, b.container_no, b.item_count, b.created_at,'
        ' (SELECT COUNT(*) FROM product_batch pb WHERE pb.batch_id=b.id) AS product_count'
        ' FROM batches b WHERE b.kind=? ORDER BY b.created_at DESC',
        ('checklist',)).fetchall()
    return [dict(r) for r in rows]


def products_by_batch(con, batch_id):
    """返回某个清单批次下的所有产品编码（用于检索页加载货品清单）。

    从 product_batch 多对多表查询，确保同一产品在多个柜号出现时，
    每个柜号的清单都能正确返回该产品。
    """
    rows = con.execute(
        'SELECT p.code_norm, p.code, p.name, p.spec FROM product_batch pb'
        ' JOIN products p ON p.code_norm=pb.code_norm'
        ' WHERE pb.batch_id=? ORDER BY p.code_norm',
        (batch_id,)).fetchall()
    return [dict(r) for r in rows]


def batches_by_container(con, container_no):
    """按柜号查找所有批次（照片+清单），用于同一柜号的跨类型关联。"""
    rows = con.execute(
        'SELECT * FROM batches WHERE container_no=? ORDER BY kind, created_at',
        (container_no,)).fetchall()
    return [dict(r) for r in rows]


def delete_product(con, code_norm):
    """删除一个产品，级联清理关联、标准图、批次关联。

    返回删除的产品数（0=不存在，1=成功）。
    ⚠️ 不删除原照片（照片是独立资产，可能关联其他产品）。
    """
    prod = con.execute('SELECT code_norm FROM products WHERE code_norm=?',
                       (code_norm,)).fetchone()
    if not prod:
        return 0
    # 1. 删除标准图文件
    stds = con.execute('SELECT file FROM standard_images WHERE code_norm=?',
                       (code_norm,)).fetchall()
    for s in stds:
        try:
            if s['file'] and os.path.exists(s['file']):
                os.remove(s['file'])
        except Exception:  # noqa: BLE001
            pass
    con.execute('DELETE FROM standard_images WHERE code_norm=?', (code_norm,))
    # 2. 删除关联
    con.execute('DELETE FROM links WHERE code_norm=?', (code_norm,))
    # 3. 删除批次关联
    con.execute('DELETE FROM product_batch WHERE code_norm=?', (code_norm,))
    # 4. 删除产品
    con.execute('DELETE FROM products WHERE code_norm=?', (code_norm,))
    con.commit()
    recalc_product_counts(con)
    return 1


def product_origins(con, code_norm):
    """返回产品的来源信息：来源类型 + 关联的柜号列表。

    来源类型：
    - 'from_photo'：照片新发现确认（source_batch == 'from_photo'）
    - 'checklist'：清单导入
    - 'unknown'：其他/未知

    柜号列表：
    - 清单导入的产品：从 product_batch → batches 关联查询
    - 照片新发现确认的产品：从关联照片所在的照片批次获取柜号
      （导入照片时输入的柜号）
    """
    prod = con.execute(
        'SELECT source_batch FROM products WHERE code_norm=?', (code_norm,)).fetchone()
    if not prod:
        return None
    sb = prod['source_batch'] or ''
    if sb == 'from_photo':
        source_type = 'from_photo'
    elif sb:
        source_type = 'checklist'
    else:
        source_type = 'unknown'

    if source_type == 'from_photo':
        # 照片新发现确认：柜号来自关联照片所在的照片批次
        rows = con.execute(
            'SELECT DISTINCT b.id, b.name, b.container_no, b.created_at'
            ' FROM links l'
            ' JOIN photos p ON p.id = l.photo_id'
            ' JOIN batches b ON b.id = p.batch_id'
            ' WHERE l.code_norm=? AND b.kind=?'
            ' ORDER BY b.created_at DESC',
            (code_norm, 'photos')).fetchall()
    else:
        # 清单导入：从 product_batch 多对多表查
        rows = con.execute(
            'SELECT b.id, b.name, b.container_no, b.created_at'
            ' FROM product_batch pb'
            ' JOIN batches b ON b.id = pb.batch_id'
            ' WHERE pb.code_norm=? ORDER BY b.created_at DESC',
            (code_norm,)).fetchall()
    containers = [dict(r) for r in rows]
    return {'source_type': source_type, 'containers': containers}


def product_group_siblings(con, code_norm, limit=3):
    """该产品已关联照片的同组其他未关联照片。

    拍照时同货品连拍：一张标签特写 + 一张全景图，同一批次(batch_id)内
    group_idx 相同。当产品关联了其中一张时，自动推荐同组其他照片供人工确认关联。

    ⚠️ 同组必须同时限定 batch_id + group_idx：group_idx 是每次导入从 0 开始的
    局部索引，不限定批次会导致不同日期/批次的照片被误判为同组。

    返回：[{photo_id, file, taken_at, photo_kind, thumb, full, group_idx, batch_id,
            linked_photo_ids（同组中已关联到本产品的照片id）}, ...]
    """
    # 0. 入参可能是原始编码也可能是 code_norm —— 与 product_candidates 同一份宽容
    #    （历史上两边口径不一致过：那边双匹配、这边只认 code_norm）。
    pr = con.execute('SELECT code_norm FROM products'
                     ' WHERE code_norm=? OR code=?', (code_norm, code_norm)).fetchone()
    cn = pr['code_norm'] if pr else code_norm
    # 1. 该产品已关联的照片及其 (batch_id, group_idx)
    linked = con.execute(
        'SELECT l.photo_id, p.batch_id, p.group_idx FROM links l'
        ' JOIN photos p ON p.id = l.photo_id'
        ' WHERE l.code_norm=? AND p.group_idx IS NOT NULL AND p.group_idx != ?',
        (cn, '')).fetchall()
    if not linked:
        return []
    # 用 (batch_id, group_idx) 元组作为组标识，避免跨批次混组
    group_keys = list({(r['batch_id'], r['group_idx']) for r in linked})
    linked_ids = {r['photo_id'] for r in linked}
    # 2. 同组所有照片（排除已关联到本产品的）—— 必须同时匹配 batch_id + group_idx
    # ⚠️ 过滤必须与列表的「同组待确认」计数同源（_cand_filter_sql）：装箱单/
    #    场景照不能进推荐 —— 装箱单上印着整箱编码，拿它关联会把一件货连到几十
    #    个产品上。以前这里只排 is_dup，比列表宽，两边数字对不上。
    # 🔴 2026-10-11：**收敛**。group_idx 是按 taken_at 间隔算的，而微信转来的图
    #    taken_at 是接收时间（35% 同秒），于是组被撑得极大 —— 实测真实库微信来源
    #    平均 22.9 张/组、一次能给 29 张（98% 的情况 ≥10 张）。29 张不是建议，
    #    是负担。改为按 import_seq 取**离已关联照片最近**的 limit 张。
    cond = ' OR '.join(['(batch_id=? AND group_idx=?)'] * len(group_keys))
    params = [v for key in group_keys for v in key] + [cn]
    rows = con.execute((
        'SELECT * FROM photos WHERE (%s)'
        ' AND id NOT IN (SELECT photo_id FROM links WHERE code_norm=?)'
        ' AND ' + _cand_filter_sql() +
        ' ORDER BY batch_id, group_idx, taken_at') % cond,
        params).fetchall()
    # 减掉人工标记「无关联」的（10-05）——与 cand_counts 的同组部分同源，
    # 否则列表角标少了、详情还挂着，老板会以为标记没生效又点一次。
    rej = rejected_pairs(con)
    if rej:
        rows = [r for r in rows if (cn, r['id']) not in rej]
    # 3. 组装输出，标注同组中已关联的照片id
    group_to_linked = {}
    for r in linked:
        key = (r['batch_id'], r['group_idx'])
        group_to_linked.setdefault(key, []).append(r['photo_id'])
    # 收敛：离已关联照片（按 import_seq）最近的 limit 张。大组不再整组甩出来。
    anchor = [r['import_seq'] for r in con.execute(
        'SELECT p.import_seq FROM links l JOIN photos p ON p.id=l.photo_id '
        'WHERE l.code_norm=? AND p.import_seq IS NOT NULL', (cn,)).fetchall()]
    if anchor and limit:
        def _dist(ph):
            s = ph['import_seq']
            if s is None:
                return 10 ** 9
            return min(abs(s - a) for a in anchor)
        rows = sorted(rows, key=lambda ph: (_dist(ph), ph['taken_at'] or ''))[:limit]
    elif limit:
        # import_seq 全空的老数据：退回按时间前后各取一半，别整组给
        rows = rows[:limit]
    out = []
    for ph in rows:
        key = (ph['batch_id'], ph['group_idx'])
        out.append({
            'photo_id': ph['id'], 'file': ph['file'],
            'taken_at': ph['taken_at'], 'photo_kind': ph['photo_kind'],
            'thumb': '/thumb/%s' % ph['id'], 'full': '/img/%s' % ph['id'],
            'group_idx': ph['group_idx'], 'batch_id': ph['batch_id'],
            'linked_photo_ids': group_to_linked.get(key, []),
        })
    return out


# ═══════════════════════════════════════════════════════════════════
# 装柜报告数据源（v3）
# ═══════════════════════════════════════════════════════════════════

def loading_report_data(con, container_id, reverse_checks=True, picks=None):
    """按柜组装装柜报告 8 个区块所需的**全部**数据。

    ⚠️ 这是报告页与柜详情页的**同一份数据源**（铁律 23：数字同源）。
    页面上写的「93 行 · 4 行未核对」与生成器吃的是这里返回的同一份数据 ——
    各写一份 SQL 必然漂，而数字对不上比没有数字更伤信任。

    返回 dict：
      meta      柜元数据（柜号/封条/到离柜/Inspector/Location/Product/Client/REMARKS）
      summary   行数、Order/Loading 合计、未核对数、缺图数
      rows      区块⑤ 按清单**原行**（不合并同码）
      checks    区块⑥ 已关联到本柜清单编码的预检照片（图注 code-name-carton）
      trucks    区块⑦ 监装照片（卡车头/装柜过程/其他）
      conditions 区块④ 柜况代表图（tag 最新一张；2026-10-18 起 picks 每类可多选）
      images    后端内部用的 {photo_id: 绝对路径}（含标准图替换）

    [reverse_checks] ⑥ 是否倒序（样例是从清单尾部往回排；老板可能要求正序）
    [picks]          人工指定用图。旧格式 {code_norm: photo_id}（⑥核对照）；
                     新格式 {'codes': {...}, 'trucks': [photo_id,...]（⑦，None=自动）,
                             'conds': {tag: photo_id}（④柜况每类指定）}
    """
    d = container_detail(con, container_id)
    cno = d['container_no']
    is_unc = d['is_uncategorized']

    # ── 区块⑤：清单行快照（按 seq，原行不合并）────────────────
    rows = []
    for b in d['batches']:
        if b['kind'] != 'checklist':
            continue
        for r in con.execute('SELECT * FROM checklist_rows WHERE batch_id=?'
                             ' ORDER BY seq', (b['id'],)):
            # check = 人工核对结论优先，否则沿用清单预填；两列都空 → 留空。
            # ⚠️ 绝不在这里填 PASS：清单预填的 PASS 是客户的数据，照抄；
            #    人工没核对过就该留空（铁律 17：还没查完 ≠ 没问题）。
            chk = (r['check_result'] or '').strip() or (r['check_import'] or '').strip()
            rows.append({
                'code': r['code'], 'code_norm': r['code_norm'],
                'name': r['name'], 'spec': r['spec'],
                'package_no': r['package_no'],
                'order_qty': r['order_qty'], 'loading_qty': r['loading_qty'],
                'check': chk, 'batch_id': b['id'], 'seq': r['seq'],
            })

    # ── 区块⑥：已关联到本柜清单编码的预检照片 ─────────────────
    codes = {r['code_norm'] for r in rows if r['code_norm']}
    # picks 两种格式（2026-10-11 扩展）：
    #   旧 {code_norm: photo_id|list}          —— 只有⑥核对照
    #   新 {'codes': {...}, 'trucks': [...],   —— ⑥ + 监装照（⑦指定哪些 /
    #       'conds': {tag: photo_id}}             ④柜况每类指定哪张）
    # trucks=None = 人工没表态（自动：TRUCK_PICTURE_TAGS 全进）；
    # trucks=[] = 明确一张都不要（⑦ 整节省略）。这两种必须区分，
    # 「没选」和「选了又全取消」是两个决定。
    picks = picks or {}
    if isinstance(picks, dict) and ('codes' in picks or 'trucks' in picks
                                    or 'conds' in picks):
        code_picks = picks.get('codes') or {}
        truck_ids = picks.get('trucks')
        cond_picks = picks.get('conds') or {}
    else:
        code_picks = picks
        truck_ids = None
        cond_picks = {}
    # 一个编码的清单行：品名取第一条；**箱号收全**（10-06：同一编码可能分装在
    # 多个箱里，图注要把它们都列出来，而不是只报第一个箱）
    head = {}
    cartons = {}
    for r in rows:
        cn = r['code_norm']
        if not cn:
            continue
        head.setdefault(cn, r)
        pk = (r.get('package_no') or '').strip()
        if pk and pk not in cartons.setdefault(cn, []):
            cartons[cn].append(pk)

    checks = []
    images = {}
    if codes and not is_unc:
        qs = ','.join('?' * len(codes))
        # 每个编码默认取**一张**代表照（想要多张就在②里用「采用」勾选）
        auto = {}
        for pid, cn in con.execute(
                'SELECT l.photo_id, l.code_norm FROM links l'
                ' JOIN photos p ON p.id=l.photo_id'
                ' JOIN batches b ON b.id=p.batch_id'
                " WHERE b.container_id=? AND p.is_dup=0"
                "   AND (p.photo_usage IS NULL OR p.photo_usage='预检')"
                '   AND l.code_norm IN (%s)'
                ' GROUP BY l.code_norm'
                ' ORDER BY p.taken_at DESC' % qs,
                [container_id] + sorted(codes)):
            auto.setdefault(cn, [pid])
        # [picks] **叠加覆盖**且支持多张（10-05 只覆盖一张；10-06 老板要求一个
        # 编码可多图）：值可以是 photo_id 或 [photo_id, ...]。
        merged = {cn: list(v) for cn, v in auto.items()}
        for cn, val in (code_picks or {}).items():
            if cn not in codes:
                continue
            want = [val] if isinstance(val, str) else list(val or [])
            want = [str(x) for x in want if x]
            if want:
                merged[cn] = want
        # (编码, 照片) 对 —— 编码**显式带上**，不靠 links 反查（一张图可能被
        # 多个编码关联，反查会张冠李戴，图注编码就会错）
        pairs = [(cn, pid) for cn in sorted(merged) for pid in merged[cn]]
        photo_ids = list(dict.fromkeys(pid for _cn, pid in pairs))
        if photo_ids:
            qs2 = ','.join('?' * len(photo_ids))
            info = {}
            for r in con.execute(
                    'SELECT p.id, p.path, p.taken_at, p.file FROM photos p'
                    ' WHERE p.id IN (%s)' % qs2, photo_ids):
                info.setdefault(r['id'], {'path': r['path'], 'taken_at': r['taken_at']})
            for cn, pid in pairs:
                it = info.get(pid)
                if not it:
                    continue
                h = head.get(cn) or {}
                images[pid] = it['path']
                checks.append({
                    'photo_id': pid, 'code': cn,
                    'name': h.get('name') or '',
                    'carton': ' / '.join(cartons.get(cn) or []),
                    'cartons': list(cartons.get(cn) or []),
                    'taken_at': it['taken_at'],
                    'path': _report_image_path(con, pid, images),
                })
    # 倒序 = 从清单尾部往回排（样例如此）
    if reverse_checks:
        checks.reverse()

    # ── 区块⑦：监装照（卡车头/装柜过程/其他）────────────────────
    # 人工指定（picks.trucks = [photo_id,...]）→ 只出指定的这几张，
    # 顺序跟人工点的顺序一致；id 不属于本柜监装照的静默丢弃（防脏数据）。
    # 没表态（trucks=None）→ 自动：TRUCK_PICTURE_TAGS 全部进。
    trucks = []
    if truck_ids is not None:
        want = [str(x) for x in (truck_ids or []) if x]
        if want:
            qs_t = ','.join('?' * len(want))
            rows_t = {str(r['id']): r for r in con.execute(
                'SELECT id, path, supervision_tag, taken_at FROM photos'
                ' WHERE id IN (%s)' % qs_t, want)}
            for pid in want:
                r = rows_t.get(pid)
                if not r:
                    continue
                chk = con.execute(
                    'SELECT 1 FROM photos p JOIN batches b ON b.id=p.batch_id'
                    ' WHERE p.id=? AND b.container_id=?'
                    " AND p.photo_usage='监装' AND p.is_dup=0",
                    (pid, container_id)).fetchone()
                if not chk:
                    continue
                images[r['id']] = r['path']
                trucks.append({'photo_id': r['id'],
                               'tag': r['supervision_tag'] or 'other',
                               'taken_at': r['taken_at'],
                               'path': _report_image_path(con, r['id'], images)})
    else:
        qmarks = ','.join('?' * len(schema.TRUCK_PICTURE_TAGS))
        for r in con.execute(
                'SELECT id, path, supervision_tag, taken_at FROM photos'
                ' WHERE batch_id IN (SELECT id FROM batches WHERE container_id=?)'
                "   AND photo_usage='监装' AND is_dup=0"
                '   AND IFNULL(supervision_tag,\'other\') IN (%s)'
                ' ORDER BY taken_at' % qmarks,
                [container_id] + list(schema.TRUCK_PICTURE_TAGS)):
            images[r['id']] = r['path']
            trucks.append({'photo_id': r['id'], 'tag': r['supervision_tag'] or 'other',
                           'taken_at': r['taken_at'],
                           'path': _report_image_path(con, r['id'], images)})

    # ── 区块④：柜况代表图 ─────────────────────────────────────
    # 人工指定（picks.conds = {tag: photo_id|[photo_id,...]}）覆盖「tag 最新
    # 一张」的自动值；2026-10-18 老板规则：监装细类**不限一张，可多选**
    # （与 code_picks 同款双态）。逐个校验每张照片真的属于本柜且
    # supervision_tag 就是这个 tag —— 槽位标签会直接印进报告（④ 的图注是
    # 固定文案），挂错图比留空严重。
    # conditions[tag] = [path, ...]（多选；自动路径只有一张）。
    conditions = {}
    for tag, row in (d.get('condition_photos') or {}).items():
        if not row:
            conditions[tag] = []
            continue
        images[row['id']] = resolve_photo_path(con, row['id'], row['path'])
        conditions[tag] = [_report_image_path(con, row['id'], images)]
    for tag, val in (cond_picks or {}).items():
        if tag not in schema.CONTAINER_CONDITION_TAGS:
            continue
        want = [val] if isinstance(val, str) else list(val or [])
        want = [str(x) for x in want if x]
        if not want:
            continue
        paths = []
        for pid in want:
            row = con.execute(
                'SELECT p.id, p.path FROM photos p'
                ' JOIN batches b ON b.id=p.batch_id'
                ' WHERE p.id=? AND b.container_id=? AND p.is_dup=0'
                "   AND IFNULL(p.supervision_tag,'other')=?",
                (pid, container_id, tag)).fetchone()
            if row:
                images[row['id']] = resolve_photo_path(con, row['id'], row['path'])
                paths.append(_report_image_path(con, row['id'], images))
        if paths:
            conditions[tag] = paths

    # ── 汇总 ─────────────────────────────────────────────────
    def _tot(key):
        s = 0.0
        got = False
        unparsed = 0
        for r in rows:
            t = r.get(key)
            if not (t or '').strip():
                continue
            v = schema.to_number(t)
            if v is None:
                unparsed += 1
            else:
                s += v
                got = True
        return (s if got else None), unparsed

    o_tot, o_bad = _tot('order_qty')
    l_tot, l_bad = _tot('loading_qty')
    return {
        'meta': {
            'container_no': cno,
            'seal_no': d.get('seal_no'),
            'arrival_at': d.get('arrival_at'),
            'departure_at': d.get('departure_at'),
            'inspector': d.get('inspector'),
            'location': d.get('location'),
            'product_name': d.get('product_name'),
            'client_name': d.get('client_name'),
            'remark': d.get('remark'),
            'is_uncategorized': is_unc,
            'inspection_date': _report_date(),
        },
        'summary': {
            'row_total': len(rows),
            'row_unchecked': d['row_unchecked'],
            'order_total': o_tot,
            'loading_total': l_tot,
            'order_qty_display': o_tot,
            'loading_qty_display': l_tot,
            'qty_unparsed': o_bad + l_bad,
            'check_photos': len(checks),
            'truck_photos': len(trucks),
            'condition_photos': sum(1 for v in conditions.values() if v),
            'condition_missing': sum(1 for v in conditions.values() if not v),
        },
        'rows': rows,
        'checks': checks,
        'trucks': trucks,
        'conditions': conditions,
        'images': images,
    }


def _report_image_path(con, photo_id, images):
    """报告用图路径：**标准图优先**，没有才回退原图。

    复用「导出标准库」的既有先例 —— 人工裁剪/修过的图质量更好，
    但**原图永远不动**（标准图是独立资产）。
    """
    std = standard_for_photo(con, photo_id)
    if std and std['file'] and os.path.exists(std['file']):
        images[photo_id + ':std'] = std['file']
        return std['file']
    return (images or {}).get(photo_id)


def _report_date():
    from datetime import datetime
    d = datetime.now()
    # 样例格式：`27th Sep, 2026`
    suf = 'th'
    if 4 <= d.day % 100 <= 20:
        suf = {4: 'th', 5: 'th', 6: 'th', 7: 'th', 8: 'th', 9: 'th', 10: 'th',
               11: 'th', 12: 'th', 13: 'th', 14: 'th', 15: 'th', 16: 'th',
               17: 'th', 18: 'th', 19: 'th', 20: 'th'}.get(d.day, 'th')
    elif d.day % 10 == 1:
        suf = 'st'
    elif d.day % 10 == 2:
        suf = 'nd'
    elif d.day % 10 == 3:
        suf = 'rd'
    mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.month - 1]
    return '%d%s %s, %d' % (d.day, suf, mon, d.year)
