# -*- coding: utf-8 -*-
"""左侧树形筛选：facets 计数 + 监装待办筛选（2026-10-14 老板需求）。

锁死三条口径：
  1 photo_facet_counts 与 photo_where_sql **同一份 WHERE** —— 树上的数字
     和点进去的列表条数不会漂（铁律 23）；
  2 交叉筛选：给了 kind，用途计数只算该分类；给了 usage，分类计数只算该用途；
  3 /api/photos?pending=1 与③的待办清单同一个集合（supervision_pending_of），
     按 container_id 收窄；没给柜号返回空，不撒谎成全库数。
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_tree_')
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
            " VALUES('c1','TREE01','2026-10-14','2026-10-14')")
con.execute("INSERT INTO batches(id,name,kind,container_id,created_at)"
            " VALUES('b1','批1','photos','c1','2026-10-14')")


def mk(pid, usage=None, kind='label', invalid=0, suptag=None, ai_tag=None,
       confirmed=0, carton=None):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,vision_codes,'
        'photo_usage,supervision_tag,is_invalid,sup_tag_ai,sup_tag_confirmed,'
        'carton_no,created_at) '
        "VALUES(?,'/x/'||?, '/x/'||?,'b1','2026-10-14T10:00:00','exif',100,?,"
        "800,600,0,0,'done',?,?,?,?,?,?,?,?,'2026-10-14T10:00:00')",
        (pid, pid, pid, 'm' + pid, kind, '[]', usage, suptag, invalid, ai_tag,
         confirmed, carton))


# 用途：监装 3 / 预检 2 / 未分类 1；分类：label 4 / scene 1 / carton 1；另 1 张无效监装
mk('t_sup1', usage='监装', kind='label', suptag='empty_container', confirmed=1)
mk('t_sup2', usage='监装', kind='label', ai_tag='empty_container')   # 有待确认
mk('t_sup3', usage='监装', kind='carton')                            # 有待确认
mk('t_pre1', usage='预检', kind='label')
mk('t_pre2', usage='预检', kind='scene')
mk('t_none', usage=None, kind='label')
mk('t_bad', usage='监装', kind='label', invalid=1)                   # 无效
con.commit()   # 后面 RP.api_* 用独立连接读库，必须先落盘

# ── 1 facets 与列表同源 ──
f = store.photo_facet_counts(con, container_id='c1')
chk('1 用途计数（未分类单列）',
    f['usage'] == {'监装': 3, '预检': 2, '_unset': 1}, f['usage'])
# label：sup1/sup2/pre1/none = 4（t_bad 也 label 但无效默认排除）；scene 1；carton 1
chk('2 分类计数', f['kind'] == {'label': 4, 'scene': 1, 'carton': 1}, f['kind'])
# 与 photo_where_sql 逐项对账（树上的数字 == 列表能查出来的条数）
j, w, a = store.photo_where_sql(container_id='c1', usage='监装')
n = con.execute('SELECT COUNT(*) FROM photos p' + j + w, a).fetchone()[0]
chk('3 树上「监装 3」= 列表条数', f['usage']['监装'] == n == 3, '%s/%s' % (f['usage']['监装'], n))
# 无效默认排除（hide）
j2, w2, a2 = store.photo_where_sql(container_id='c1')
n_all = con.execute('SELECT COUNT(*) FROM photos p' + j2 + w2, a2).fetchone()[0]
chk('4 无效照片不进 facets（默认 hide）',
    sum(f['usage'].values()) == n_all == 6, '%s/%s' % (sum(f['usage'].values()), n_all))

# ── 2 交叉筛选 ──
f2 = store.photo_facet_counts(con, container_id='c1', kind='label')
# label 下：监装 sup1/sup2 = 2，预检 pre1 = 1，未分类 none = 1
chk('5 交叉：按分类看用途（label 下 监装2/预检1/未分类1）',
    f2['usage'] == {'监装': 2, '预检': 1, '_unset': 1}, f2['usage'])
f3 = store.photo_facet_counts(con, container_id='c1', usage='监装')
chk('6 交叉：按用途看分类（监装下 label2/carton1）',
    f3['kind'] == {'label': 2, 'carton': 1}, f3['kind'])

# ── 3 pending 筛选（监装细分待办）──
pend = store.supervision_pending_of(con, 'c1')
pids = {r['photo_id'] for r in pend['items']}
# A. 用途=监装且细分没确认：sup2/sup3；B. 用途未分类但有 AI 建议：无（none 没 ai_tag）
chk('7 待办集合 = 监装未确认', pids == {'t_sup2', 't_sup3'}, sorted(pids))
# /api/photos?pending=1 的口径：同一个集合、按柜收窄
import tools.productlib.routes.photos as RP  # noqa: E402

# ⚠️ 不能直接回测试用的 con：视图函数 finally 里会 close()，把测试连接关掉。
#    每次开新连接（同库）。
_dbpath = os.path.join(tmp, 't.db')
RP.con = lambda: store.connect(_dbpath)
r = RP.api_photos(container_id='c1', pending=1, limit=60)
got = {x['id'] for x in r['items']}
chk('8 pending=1 只回待办集合', got == pids and r['total'] == len(pids),
    '%s/%s' % (sorted(got), r['total']))
r2 = RP.api_photos(pending=1)
chk('9 没给柜号 → 空（不撒谎成全库）', r2['total'] == 0 and r2['items'] == [])

# ── 4 五档徽章同源收窄（2026-10-14 老板反馈：树选了监装统计没更新）──
fc = store.photo_flag_counts(con, container_id='c1', usage='监装')
chk('10 徽章 all 随用途收窄（监装=3）', fc['all'] == 3, fc['all'])
fc2 = store.photo_flag_counts(con, container_id='c1', kind='label')
chk('11 徽章 all 随分类收窄（label=4）', fc2['all'] == 4, fc2['all'])
fc3 = store.photo_flag_counts(con, container_id='c1', pending=1)
chk('12 pending=1 徽章 all = 待办数 2', fc3['all'] == 2, fc3['all'])
fc4 = RP.api_photo_linkstate(container_id='c1', usage='监装')
chk('13 linkstate 端点透传筛选', fc4['all'] == 3, fc4['all'])

# ── 5 按箱号分组（2026-10-14 老板需求：③按箱号分组看）──
con.execute("UPDATE photos SET carton_no='CTN-A' WHERE id IN ('t_sup1','t_sup2')")
con.execute("UPDATE photos SET carton_no='CTN-B' WHERE id='t_pre1'")
con.commit()
cg = store.photos_by_carton(con, container_id='c1')
chk('14 箱号聚合：3 组（CTN-A/CTN-B/未标注），空箱号排最后',
    cg['total'] == 3 and [x['carton_no'] for x in cg['items']] == ['CTN-A', 'CTN-B', None],
    [(x['carton_no'], x['count']) for x in cg['items']])
ga = cg['items'][0]
chk('15 组摘要：张数/分类/关联', ga['count'] == 2 and ga['kinds'] == {'label': 2}
    and ga['linked_codes'] == [], 'count=%s kinds=%s' % (ga['count'], ga['kinds']))
chk('16 组内照片带完整渲染字段', all(
    p['thumb'] and p['file'] and 'nlink' in p and 'is_invalid' in p
    for p in ga['photos']), list(ga['photos'][0].keys())[:6])
cg2 = store.photos_by_carton(con, container_id='c1', usage='预检')
# 预检 2 张：t_pre1=CTN-B，t_pre2 未标箱号 → 「未标注」组（口径正确）
chk('17 交叉：按用途筛后 CTN-B(1) + 未标注(1)',
    cg2['total'] == 2 and [x['carton_no'] for x in cg2['items']] == ['CTN-B', None]
    and [x['count'] for x in cg2['items']] == [1, 1],
    [(x['carton_no'], x['count']) for x in cg2['items']])
pend_ids = [r['photo_id'] for r in
            store.supervision_pending_of(con, 'c1')['items']]
cg3 = store.photos_by_carton(con, container_id='c1', extra_ids=pend_ids)
chk('18 pending 交叉：待办集合的箱号分组',
    cg3['total'] == 2 and cg3['items'][0]['carton_no'] == 'CTN-A',
    [(x['carton_no'], x['count']) for x in cg3['items']])
rp = RP.api_photos_carton_groups(container_id='c1', limit=30)

def photo_where_q():
    j, w, a = store.photo_where_sql(container_id='c1', q='t_pre1')
    return j, w, a

chk('19 carton-groups 端点可用', rp['total'] == 3, rp['total'])

# ── 6 搜索（q）不再语法错（2026-10-14 老板实测：搜索任何词都 500）──
# _q_filter 返回 ' AND (...)'，photo_where_sql 的 q 分支此前只剥 WHERE/1=1
# 前缀 → add() 拼出 'WHERE AND (...)' → near "AND"
j3, w3, a3 = photo_where_q()
chk('20 photo_where_sql 带 q 不缺 WHERE', w3.strip().upper().startswith('WHERE'),
    w3[:60])
rq = RP.api_photos(container_id='c1', q='t_pre1')
chk('21 搜索命中文件名（不再 500）', rq['total'] == 1,
    'total=%s' % rq['total'])

print()
print('PASS' if not FAILS else 'FAIL %d 项: %s' % (len(FAILS), FAILS))
sys.exit(0 if not FAILS else 1)
