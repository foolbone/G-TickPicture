# -*- coding: utf-8 -*-
"""人工改照片分类（2026-10-15 老板需求：模型识别不一定准，要能手改）。

锁死四条口径：
  1 set_photo_kinds 单张/批量都走同一个入口，返回实际更新张数；
  2 分类只认 schema.PHOTO_KINDS 的枚举值，越界报错（不静默落 unknown）；
  3 传空 = 落 unknown（「取消分类」的语义）；
  4 人工选定后 kind_conf 清空 —— 那是**模型的置信度**，人拍的板不挂
    模型分数（UI 上也就不会再显示「模型判定 xx%」）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_kind_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


con.execute("INSERT INTO containers(id,container_no,created_at,updated_at)"
            " VALUES('c1','KIND01','2026-10-15','2026-10-15')")
con.execute("INSERT INTO batches(id,name,kind,container_id,created_at)"
            " VALUES('b1','批1','photos','c1','2026-10-15')")


def mk(pid, kind='label', conf=0.82):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,kind_conf,'
        'created_at) '
        "VALUES(?,'/x/'||?,'/x/'||?,'b1','2026-10-15T10:00:00','exif',100,?,"
        "800,600,0,0,'done',?,?,'2026-10-15')",
        (pid, pid, pid, 'm' + pid, kind, conf))


mk('k1'); mk('k2'); mk('k3'); mk('k4')
con.commit()

# ── 1 单张改判 ──
n = store.set_photo_kinds(con, ['k1'], 'packing_list')
row = con.execute('SELECT photo_kind, kind_conf FROM photos WHERE id=?',
                  ('k1',)).fetchone()
chk('1 单张改判：行数与落库', n == 1 and row['photo_kind'] == 'packing_list',
    '%s %s' % (n, dict(row)))
chk('2 人工改判后清掉模型置信度', row['kind_conf'] is None, row['kind_conf'])

# ── 2 批量改判 ──
n2 = store.set_photo_kinds(con, ['k2', 'k3'], 'scene')
kinds = [r[0] for r in con.execute(
    'SELECT photo_kind FROM photos WHERE id IN ("k2","k3") ORDER BY id')]
chk('3 批量改判 2 张', n2 == 2 and kinds == ['scene', 'scene'], '%s %s' % (n2, kinds))
chk('4 没被点名的那张不动',
    con.execute('SELECT photo_kind FROM photos WHERE id=?', ('k4',))
    .fetchone()[0] == 'label')

# ── 3 枚举校验 ──
try:
    store.set_photo_kinds(con, ['k4'], '瞎写的分类')
    chk('5 越界分类报错', False, '没抛异常')
except ValueError as e:
    chk('5 越界分类报错', True, str(e)[:40])

# ── 4 空值 = unknown ──
n3 = store.set_photo_kinds(con, ['k4'], '')
chk('6 传空落 unknown',
    n3 == 1 and con.execute('SELECT photo_kind FROM photos WHERE id=?', ('k4',))
    .fetchone()[0] == 'unknown', n3)

# ── 5 空列表不炸 ──
chk('7 空 id 列表返回 0', store.set_photo_kinds(con, [], 'label') == 0)

# ── 6 端点（走视图函数）──
import tools.productlib.routes.photos as RP  # noqa: E402
_dbpath = os.path.join(tmp, 't.db')
RP.con = lambda: store.connect(_dbpath)
r = RP.api_set_photo_kind({'photo_ids': ['k1', 'k2'], 'kind': 'product'})
chk('8 端点批量改判', r['ok'] and r['updated'] == 2 and r['kind'] == 'product', r)
try:
    from fastapi import HTTPException
    RP.api_set_photo_kind({'photo_ids': ['k1'], 'kind': '不是分类'})
    chk('9 端点越界 400', False, '没抛')
except HTTPException as e:
    chk('9 端点越界 400', e.status_code == 400, e.status_code)
try:
    RP.api_set_photo_kind({'photo_ids': [], 'kind': 'label'})
    chk('10 空列表 400', False, '没抛')
except HTTPException as e:
    chk('10 空列表 400', e.status_code == 400, e.status_code)

print()
print('PASS' if not FAILS else 'FAIL %d 项: %s' % (len(FAILS), FAILS))
sys.exit(0 if not FAILS else 1)
