# -*- coding: utf-8 -*-
"""无感升级：启动前自动备份+迁移+核对，且只在真待迁移时备份。

卡住两个漂移：
  1. needs_migration 与 store._migrate 的「列/表/索引」必须一一对应——
     _migrate 加列忘了在 needs_migration 补检查 → 新版本发布后误判「无需升级」
     → 跳过备份 → 退化成 connect() 的静默无备份迁移（2026-10-10 要修的坑）。
  2. auto_upgrade 必须**真把缺失列补回来**（不能只跑一遍空迁移）——这里用
     DROP 一个 _migrate 才加的列模拟「旧版库」，升级后必须补回该列。

本测试只读/幂等，不碰真实数据目录（PL_HOME 指向临时目录）。
"""
import os
import sys
import tempfile
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, paths   # noqa: E402
from tools.productlib import upgrade        # noqa: E402
from tools.productlib import schema as schema_mod   # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print('[ OK ]', msg)
    else:
        FAILS.append(msg)
        print('[FAIL]', msg)


# 临时根，避免碰到真实 PL_HOME；paths.data_dir() 会落到 <root>/data
root = tempfile.mkdtemp(prefix='pl_autoupg_')
os.environ['PL_HOME'] = root
data = paths.data_dir()
os.makedirs(data, exist_ok=True)
db = paths.db_path()


# ── 1) 全新库：needs_migration=False，auto_upgrade 完全静默（不备份）────────
con = store.connect(db)
con.close()
check(not store.needs_migration(db), '全新库 needs_migration = False')
parent = os.path.dirname(data)
before = set(os.listdir(parent))
res = upgrade.auto_upgrade(data)
check(res.get('needed') is False, '全新库 auto_upgrade needed=False（不备份不打扰）')
after = set(os.listdir(parent))
check(before == after, '全新库 auto_upgrade 未产生任何备份目录')


# ── 2) 模拟「旧版库」：删掉一个 _migrate 才加的列 → needs_migration 应变 True ──
#     用原始连接、不经 store.connect（否则 _migrate 又会把它加回来）
raw = sqlite3.connect(db)
raw.execute('ALTER TABLE products DROP COLUMN review_state')
raw.commit()
raw.close()
check(store.needs_migration(db) is True,
      '缺 review_state 列 → needs_migration = True（能发现待迁移）')


# ── 3) 自动升级旧库：先备份、再迁移、再核对，必须成功且补回该列 ─────────────
res2 = upgrade.auto_upgrade(data)
check(res2.get('needed') is True, '旧库 auto_upgrade needed=True')
check(res2.get('failed') is False, '旧库 auto_upgrade 未失败')
check(bool(res2.get('backup')), '旧库 auto_upgrade 产生了备份目录')
check(os.path.isfile(os.path.join(res2['backup'], 'productlib.db')),
      '备份含 productlib.db（迁移前快照，还原能回到升级前）')
check(store.needs_migration(db) is False, '升级后 needs_migration = False')
raw2 = sqlite3.connect(db)
cols = {r[1] for r in raw2.execute('PRAGMA table_info(products)')}
raw2.close()
check('review_state' in cols, '升级后 products.review_state 列已补回')


# ── 4) 显式 --upgrade 对已最新库：应跳过备份（不重复造副本）─────────────────
n_before = len([d for d in os.listdir(parent) if '备份' in d])
rc = upgrade.main(['--data', data])
n_after = len([d for d in os.listdir(parent) if '备份' in d])
check(rc == 0, 'upgrade.main 在已最新库上返回 0')
check(n_after == n_before, 'upgrade.main 对已最新库不重复备份')


# ── 5) 🔴 裸连接跑完整 _migrate（复刻 upgrade.upgrade 的调用方式）──────────
# 2026-10-11 发 v0.7.0 时实测踩到：upgrade.py 用**裸连接** sqlite3.connect
# 调 store._migrate，那条连接没有 row_factory=sqlite3.Row；而
# _migrate_standard_layout 里用了 r['file'] 命名访问 → 抛
# "tuple indices must be integers or slices, not str" → 服务**拒启动**。
#
# 为什么之前没炸：所有既有测试都走 store.connect（它设了 row_factory），
# 只有打包版的「启动即无感升级」这条路径是裸连接。而它炸的条件是
# 「库里还有没迁移过的扁平标准图」—— 空库/新库测不出来。
#
# 这条测试刻意不走 store.connect，直接复刻 upgrade.upgrade 的三行。
legacy = os.path.join(root, 'legacy_std.db')
std_dir = os.path.join(root, 'std_flat')          # 标准图的「扁平」根目录
os.makedirs(std_dir, exist_ok=True)
flat_png = os.path.join(std_dir, 'sid1.jpg')       # 直接躺在根下 = 待迁移的旧布局
with open(flat_png, 'wb') as f:
    f.write(b'\xff\xd8\xff\xe0stub')
store.STANDARD_DIR = std_dir                       # 让迁移认这个根
lc = sqlite3.connect(legacy)
lc.executescript(schema_mod.SCHEMA)
lc.execute("INSERT INTO standard_images(id,code_norm,kind,file,src_photo_id,created_at)"
           " VALUES('sid1','ABC123','product',?,'ph1',?)", (flat_png, '2026-10-01'))
lc.execute("INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,"
           "width,height,group_idx,govern_state,created_at)"
           " VALUES('ph1','a.jpg','a.jpg','b1','2026-10-01T10:00:00','mtime',1,'m',"
           "100,100,0,'done','2026-10-01')")
lc.execute("INSERT INTO batches(id,name,kind,created_at,container_no)"
           " VALUES('b1','旧批次','photos','2026-10-01','OLD_CNT')")
lc.commit(); lc.close()

lc = sqlite3.connect(legacy)          # 裸连接：无 row_factory，与 upgrade.py 一致
try:
    lc.execute('PRAGMA journal_mode=WAL')
    lc.executescript(schema_mod.SCHEMA)
    store._migrate(lc)                # ← 以前在这里炸
    lc.commit()
    ok_bare = True
    err = ''
except Exception as e:               # noqa: BLE001
    ok_bare = False
    err = repr(e)
finally:
    lc.close()
check(ok_bare, '裸连接（upgrade.py 的调用方式）跑完整 _migrate 不抛：%s' % err)
lc = sqlite3.connect(legacy)
new_file = lc.execute("SELECT file FROM standard_images WHERE id='sid1'").fetchone()[0]
n_null = lc.execute('SELECT COUNT(*) FROM photos WHERE import_seq IS NULL').fetchone()[0]
lc.close()
check(os.path.dirname(os.path.abspath(new_file)) != os.path.abspath(std_dir),
      '裸连接迁移里扁平标准图也照常搬进了产品文件夹：%s' % new_file)
check(n_null == 0, '裸连接迁移把 import_seq 也回填了（NULL %d）' % n_null)


print()
if FAILS:
    print('ALL_FAIL %d' % len(FAILS))
    for f in FAILS:
        print('  -', f)
    raise SystemExit(1)
print('全部通过')
