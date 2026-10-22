# -*- coding: utf-8 -*-
"""拍照时间字段：候选卡要显示每张缩略图的拍照时间（10-05）。

老板要求「只要展示图片的地方都要显示拍照时间」。前端已有的 taken_at 不动，
本测试只锁后端新加的 photo_times（发现新产品页的缩略图原来只有 photo_id，
前端拿不到时间）：

  1 每个候选的 photo_times 覆盖它全部 photo_ids；
  2 值就是 photos.taken_at 原样（前端只格式化，不猜）；
  3 缺时间的照片给 None 而不是编一个（前端显示「时间未知」）；
  4 批量查（IN 分批 400），不许逐张 query —— 性能铁律②。
"""
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_phototime_')
DB = os.path.join(tmp, 't.db')
con = store.connect(DB)
FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


con.execute("INSERT INTO batches(id,name,kind,created_at)"
            " VALUES('b1','柜A','photos','2026-10-01')")


def mk(pid, codes=None, taken='2026-10-01T10:00:00'):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,kind_conf,'
        'vision_codes,created_at) '
        "VALUES(?,?,?,?,?,?,100,?,800,600,0,0,'done','label',0.9,?,"
        "'2026-10-01T10:00:00')",
        (pid, '/x/' + pid, '/x/' + pid, 'b1', taken,
         'exif' if taken else 'none', 'm' + pid,
         json.dumps(codes) if codes else None))
    return pid


# 一个编码被两张照片读出；另一张没有 EXIF 时间
mk('p1', ['1000000119'], '2026-10-01T09:00:00')
mk('p2', ['1000000119'], None)
mk('p3', ['1000000119'], '2026-10-01T09:00:07')

# 量一下批量查的次数（性能铁律②：批量查，别逐张）
# sqlite3.Connection.execute 不可 monkeypatch，用 set_trace_callback 统计语句
sqls = []
con.set_trace_callback(sqls.append)
items = store.discovered_products(con)
con.set_trace_callback(None)
counts = {'in': sum(1 for q in sqls
                     if 'FROM photos' in q and ' IN (' in q)}

it = [x for x in items if x['code'] == '1000000119']
chk('候选已返回', bool(it), [x['code'] for x in items][:3])
if it:
    d = it[0]
    pt = d.get('photo_times') or {}
    chk('photo_times 覆盖全部 photo_ids',
        set(pt) == set(d['photo_ids']), {'ids': d['photo_ids'], 'keys': list(pt)})
    chk('时间原样带回（前端只格式化）',
        pt.get('p1') == '2026-10-01T09:00:00' and pt.get('p3') == '2026-10-01T09:00:07',
        pt)
    chk('缺时间给 None，不编造', 'p2' in pt and pt.get('p2') is None, pt.get('p2'))
    chk('批量查（IN 分批，不逐张）', counts['in'] <= 2, counts)

# 回归：本次只加字段，没碰过滤逻辑 —— 关联掉**全部**来源照片后候选才消失
#（只关联一张时其余照片仍读出该码，候选理应还在）
store.link(con, '1000000119', 'p1', source='test', confidence=1.0)
con.commit()
chk('只关联一张时其余来源仍算候选',
    bool([x for x in store.discovered_products(con) if x['code'] == '1000000119']))
for _pid in ('p2', 'p3'):
    store.link(con, '1000000119', _pid, source='test', confidence=1.0)
con.commit()
items2 = store.discovered_products(con)
chk('全部关联后候选消失',
    not [x for x in items2 if x['code'] == '1000000119'],
    [x['code'] for x in items2][:3])

con.close()
print('PASS' if not FAILS else 'FAIL: ' + ' | '.join(FAILS))
sys.exit(1 if FAILS else 0)
