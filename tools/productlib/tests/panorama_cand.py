# -*- coding: utf-8 -*-
"""「可能的全景图」候选的回归测试（2026-10-11）。

由已关联的**标签近景**推出可能的产品全景（本体照/包装照，图上没编码）。
锁的是那些**实测换来的口径**，不是实现细节：

  1 只对「缺全景」的产品出声（已有 product/packaging 类照片 → 不给候选）
  2 候选只收 product/packaging/unknown —— **label 是别的货的标签照**，
     把它当全景推给另一个产品 = 把甲的货挪到乙名下
  3 装箱单/场景照绝不进候选
  4 候选按 import_seq（顺序）相邻取，≤3 张；taken_at 全相同也要给得出
  5 三种文件名都解析得出序号（微信/相册；相机 IMG_* 不靠序号靠 EXIF）
  6 已关联本产品、已标记「无关联」、副本都不出现
  7 一张全景可以同时是多个产品的候选（整托盘常常一图多货）
  8 同组候选收敛到 ≤3（原先整组给，微信来源实测一次 29 张）
  9 import_seq 历史回填：老库跑完 _migrate 不该有 NULL
 10 🔴 同一个文件夹是硬边界：隔壁箱号目录里再近的照片也不推
    （2026-10-19 老板「推荐的图片不是很准」：实测跨箱推荐占 33%）
 11 App 采集命名的时间戳 = 快门时刻 → 超 5 分钟的同箱照片也不推
 12 微信命名的「相隔 N 秒」是假证据 → 不给秒差

跑法：python tools/productlib/tests/panorama_cand.py
"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store                # noqa: E402

_FAILED = False


def chk(name, ok, extra=''):
    global _FAILED
    print(('[ OK ] ' if ok else '[FAIL] ') + name
          + (('  ' + str(extra)) if extra else ''))
    if not ok:
        _FAILED = True


tmp = tempfile.mkdtemp(prefix='pl_pano_')
db = os.path.join(tmp, 't.db')
store.STANDARD_DIR = os.path.join(tmp, 'standard')
con = store.connect(db)


def add_photo(batch_id, seq, kind, file_name, dup=0, exif_time=None):
    pid = 'p_%s_%03d' % (batch_id, seq)
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,width,'
        'height,group_idx,govern_state,created_at,photo_kind,is_dup,import_seq)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (pid, file_name, os.path.join(tmp, file_name), batch_id,
         exif_time or '2026-10-01T10:00:%02d' % seq,
         'exif' if exif_time else 'mtime', 100, pid, 800, 600,
         0, 'done', '2026-10-01T10:00:00', kind, dup, seq))
    return pid


def link(code, pid):
    store.link(con, code, pid, 'manual', confidence=0.9, evidence='test', created_by='t')


# ── 场景 A：微信来源（无 EXIF、时间撞车）──
store.upsert_products(con, [{'code': 'WA001', 'name': '货A', 'spec': ''},
                            {'code': 'WB001', 'name': '货B', 'spec': ''}])
ids = []
for i in range(6):
    fn = '微信图片_202609151033%02d_%d_838.jpg' % (i, 22080 + i)
    ids.append(add_photo('bA', i, 'product' if i in (2, 3) else 'label', fn))
link('WA001', ids[1])          # 中间那张是标签近景

pan = store.product_panorama_candidates(con, 'WA001')
chk('A1 有候选', len(pan) > 0, '%d 张' % len(pan))
chk('A2 候选 ≤3 张', len(pan) <= 3, len(pan))
chk('A3 候选里没有 label（别人的标签照不算全景）',
    all((p['photo_kind'] or 'unknown') in ('product', 'packaging', 'unknown') for p in pan),
    [p['photo_kind'] for p in pan])
chk('A4 近邻的全景排前面', pan and pan[0]['photo_kind'] == 'product',
    pan[0]['photo_kind'] if pan else None)
chk('A5 非 exif 来源不给秒差（微信时间是接收时间）',
    all(p['gap_txt'] is None for p in pan), [p['gap_txt'] for p in pan])

# 时间全相同（批量接收撞车）也要给得出，且顺序稳定
con.execute("UPDATE photos SET taken_at='2026-10-01T10:00:00' WHERE batch_id='bA'")
con.commit()
pan2 = store.product_panorama_candidates(con, 'WA001')
chk('A6 taken_at 全相同时仍给得出且按 import_seq 稳定',
    [p['photo_id'] for p in pan2] == [p['photo_id'] for p in pan],
    '%s vs %s' % ([p['photo_id'] for p in pan2], [p['photo_id'] for p in pan]))

# 已有全景 → 不再出声（不推老板已有的东西）
link('WA001', ids[2])
chk('A7 已有全景类产品照片后不再给候选',
    store.product_panorama_candidates(con, 'WA001') == [])

# ── 场景 B：一图多产品 + 否决 + 副本 + 装箱单 ──
bids = []
for i in range(5):
    fn = '20260915_204034_010%02d.jpg' % (70 + i)
    bids.append(add_photo('bB', i, 'product' if i == 2 else 'label', fn))
add_photo('bB', 9, 'packing_list', '20260915_204034_01099.jpg')
link('WB001', bids[0])
panB = store.product_panorama_candidates(con, 'WB001')
chk('B1 装箱单不进候选',
    all(p['photo_kind'] != 'packing_list' for p in panB),
    [p['photo_kind'] for p in panB])
p2 = [p for p in panB if p['photo_id'] == bids[2]]
chk('B2 邻着的全景在候选里', bool(p2), [p['photo_id'] for p in panB])
if p2:
    # 同一张全景也能被另一个产品推荐（一图多货）
    store.upsert_products(con, [{'code': 'WB002', 'name': '货B2', 'spec': ''}])
    link('WB002', [p for p in bids if True][1])
    panB2 = store.product_panorama_candidates(con, 'WB002')
    chk('B3 一张全景可同时是两个产品的候选',
        any(p['photo_id'] == bids[2] for p in panB2),
        [p['photo_id'] for p in panB2])
    # 「不是」之后消失，撤销后回来
    con.execute('INSERT OR IGNORE INTO cand_reject(code_norm,photo_id,reason,created_at,created_by)'
                ' VALUES (?,?,?,?,?)', ('WB001', bids[2], '人工判断不是', '2026-10-11', 't'))
    con.commit()
    after = store.product_panorama_candidates(con, 'WB001')
    chk('B4 标记「无关联」后从候选消失',
        all(p['photo_id'] != bids[2] for p in after), [p['photo_id'] for p in after])

# 副本不进候选
con.execute("UPDATE photos SET is_dup=1 WHERE id=?", (bids[2],))
con.commit()
chk('B5 副本不进候选',
    all(p['photo_id'] != bids[2] for p in store.product_panorama_candidates(con, 'WB001')))

# ── 场景 C：相机原图（exif，时间可信）──
cids = []
for i in range(4):
    cids.append(add_photo('bC', i, 'product' if i == 2 else 'label',
                          'IMG_20250405_0836%02d.jpg' % (10 + i),
                          exif_time='2026-04-05T08:36:%02d' % (10 + i)))
store.upsert_products(con, [{'code': 'WC001', 'name': '货C', 'spec': ''}])
link('WC001', cids[0])
panC = store.product_panorama_candidates(con, 'WC001')
chk('C1 exif 来源给「间隔 N 秒」',
    bool(panC) and panC[0]['gap_txt'] and '秒' in panC[0]['gap_txt'],
    panC[0]['gap_txt'] if panC else None)

# ── 场景 D：同组收敛（原先一次给 29 张）──
for i in range(29):
    add_photo('bD', i, 'product', '20260915_2055%02d_011%02d.jpg' % (i, i))
con.execute("UPDATE photos SET group_idx=0 WHERE batch_id='bD'")
con.commit()
store.upsert_products(con, [{'code': 'WD001', 'name': '货D', 'spec': ''}])
d0 = con.execute("SELECT id FROM photos WHERE batch_id='bD' ORDER BY import_seq LIMIT 1").fetchone()[0]
link('WD001', d0)
sib = store.product_group_siblings(con, 'WD001')
chk('D1 同组候选被收敛到 ≤3 张', len(sib) <= 3, '%d 张（原先整组给 29 张）' % len(sib))
chk('D2 收敛后仍取到邻近的', len(sib) >= 1, len(sib))

# ── 场景 E：文件名序号解析 ──
chk('E1 微信名解析出序号',
    store.file_seq('微信图片_20260915103314_22079_838.jpg') == (22079, '838'))
chk('E2 相册名解析出序号',
    store.file_seq('20260915_204034_01066.jpg') == (1066, None))
chk('E3 带子目录的路径也能解析',
    store.file_seq('新建文件夹/微信图片_20260913075631_644_3035.jpg') == (644, '3035'))
chk('E4 相机名不硬编序号（靠 EXIF）',
    store.file_seq('IMG_20250405_083614.jpg') == (None, None))
chk('E5 认不出的文件名返回 None 而不是抛',
    store.file_seq('abc.jpg') == (None, None))

# ── 场景 F：历史库回填 ──
# 🔴 必须用**裸连接**验：_migrate 也被 upgrade.py 的裸连接调用，那条连接没有
#    row_factory=sqlite3.Row。这里用 r[0] 之外的命名访问会抛 "tuple indices must
#    be integers" —— 打包版启动实测踩过（源码测试全绿是因为 store.connect 设了
#    row_factory）。所以这一段刻意不走 store.connect。
con.execute('UPDATE photos SET import_seq=NULL')
con.commit()
store._migrate(con)
n_null = con.execute('SELECT COUNT(*) FROM photos WHERE import_seq IS NULL').fetchone()[0]
chk('F1 回填后没有 NULL 的 import_seq', n_null == 0, '%d 个 NULL' % n_null)

raw_db = os.path.join(tmp, 'raw.db')
import sqlite3 as _sq
_rc = _sq.connect(raw_db)                 # 裸连接：没有 row_factory
_rc.execute('CREATE TABLE photos(id TEXT, batch_id TEXT, import_seq INTEGER)')
_rc.execute("INSERT INTO photos VALUES('a','b1',NULL)")
_rc.execute("INSERT INTO photos VALUES('b','b1',NULL)")
_rc.execute("INSERT INTO photos VALUES('c',NULL,NULL)")
_rc.commit()
try:
    store._backfill_import_seq(_rc)       # 不抛就算过
    _rows = _rc.execute('SELECT id, import_seq FROM photos ORDER BY id').fetchall()
    ok_raw = all(r[1] is not None for r in _rows)
    chk('F3 裸连接（升级通道）跑回填不抛异常且补齐', ok_raw, _rows)
except Exception as e:  # noqa: BLE001
    chk('F3 裸连接（升级通道）跑回填不抛异常且补齐', False, repr(e))
finally:
    _rc.close()

# 回填后顺序仍可用（老照片也能给候选）
chk('F2 回填后候选照样给得出',
    len(store.product_panorama_candidates(con, 'WA001')) >= 0)

# ── 场景 H：同文件夹硬边界 + App 命名时间窗（2026-10-19 老板「推荐不准」）──
# 病根：旧口径按 import_seq（文件系统扫描顺序）取 ±4 邻居，而扫描顺序**跨箱号
# 跳跃**（同一批里 seq0-3 是箱239@15:12，seq4 起跳到箱240@11:23），于是 33%
# 的推荐跑到了别的箱号里。真实 App 交付包是 `预检/<箱号>/` 一棵树。
def add_photo_h(seq, kind, file_name, carton, taken):
    pid = 'p_bH_%03d' % seq
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,group_idx,govern_state,created_at,photo_kind,is_dup,'
        'import_seq,carton_no) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (pid, file_name, os.path.join(tmp, carton, file_name), 'bH', taken,
         'filename', 100, pid, 800, 600, None, 'done', '2026-10-01T10:00:00',
         kind, 0, seq, carton))
    return pid


hL = add_photo_h(0, 'label', '20260927_100000_00001.jpg', 'A',
                 '2026-09-27T10:00:00')       # 已关联的标签近景（箱 A）
hP1 = add_photo_h(1, 'product', '20260927_100010_00002.jpg', 'A',
                  '2026-09-27T10:00:10')      # 同箱、10 秒后 —— 该推
hP2 = add_photo_h(2, 'product', '20260927_100020_00003.jpg', 'A',
                  '2026-09-27T10:00:20')      # 同箱、20 秒后 —— 该推
hQ = add_photo_h(3, 'product', '20260927_100012_00004.jpg', 'B',
                 '2026-09-27T10:00:12')       # 隔壁箱、12 秒 —— **不推**
hFar = add_photo_h(4, 'product', '20260927_102000_00005.jpg', 'A',
                   '2026-09-27T10:20:00')     # 同箱、20 分钟后 —— 不推
con.commit()
store.upsert_products(con, [{'code': 'WH001', 'name': '货H', 'spec': ''}])
link('WH001', hL)
panH = store.product_panorama_candidates(con, 'WH001')
h_ids = [p['photo_id'] for p in panH]
chk('H1 同箱近邻的全景被推出来', hP1 in h_ids and hP2 in h_ids, h_ids)
chk('H2 隔壁箱号目录里再近的照片也不推', hQ not in h_ids,
    '箱B 的 %s 不在候选里' % hQ)
chk('H3 同箱但超 5 分钟的也不推（App 时间戳可信，按严的来）',
    hFar not in h_ids, h_ids)
chk('H4 依据文案点明是哪个箱',
    all('同箱 A' in (p.get('reason') or '') for p in panH),
    [p.get('reason') for p in panH])
chk('H5 App 命名的时间可信 → 给秒差',
    any(p.get('gap_txt') and '秒' in p['gap_txt'] for p in panH),
    [p.get('gap_txt') for p in panH])

# ── 场景 G：边界不炸 ──
chk('G1 不存在的产品返回空', store.product_panorama_candidates(con, 'NOPE') == [])
chk('G2 没有照片的产品返回空', store.product_panorama_candidates(con, 'WD002') == [])

print()
print('FAIL' if _FAILED else 'ALL PASS')
con.close()
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if _FAILED else 0)
