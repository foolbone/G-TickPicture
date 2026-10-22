# -*- coding: utf-8 -*-
"""五档分组口径（2026-10-07 老板第二轮：待确认关联 / 新产品确认）。

需求：照片要能按「已关联 / 未关联 / **待确认关联** / **新产品确认**」分组看。
这两档是**已有概念的复用**，不是新定义 —— 所以本测试锁死的是「同源」：

  1 待确认关联 = cand_code_map 的 photo_id 并集 —— 与产品库列表的
    「N 待关」角标、产品详情的「可能关联的图片」同一份 map；
  2 新产品确认 = discovered_products 的 photo_ids 并集 —— 与「新产品确认」
    页候选卡同一份取数（含忽略名单与置信度门槛）；
  3 两档都**只含未关联照片**（所以是「未关联」的子集）；
  4 五档计数与 /api/photos 列表**共用 photo_where_sql** —— 徽章数字与
    列表条数必须一致（各写一份 WHERE 必然漂一位）；
  5 人工关联一张之后，它立刻从「待确认关联」里消失（缓存按库内容戳失效）；
  6 标记「无关联」后同样消失（与角标同步降）。

单开一个文件而不是塞进 cand_flag.py：那个 fixture 是产品库视角，
这里要的是**照片视角 + 按柜范围**。
"""
import os
import sys
import json
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
# ⚠️ 顺序要紧：store.py 自己会把 tools/ 塞进 sys.path，build_library 才能被
#    import（它在 tools/build_library.py）。先 import store。
from tools.productlib import store  # noqa: E402
import build_library as BL  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_flag_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


con.execute("INSERT INTO batches(id,name,kind,created_at)"
            " VALUES('b1','柜A','photos','2026-10-01')")
con.execute("INSERT INTO batches(id,name,kind,created_at)"
            " VALUES('b2','柜B','photos','2026-10-01')")
for c in ('C-EXACT1', 'C-SUB1'):
    con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
                " VALUES(?,?,?, '2026-10-01','2026-10-01')",
                (c, BL.normalize(c), '品' + c))


def mk(pid, batch='b1', grp=0, dup=0, kind='label', vision=None):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,vision_codes,created_at) '
        "VALUES(?,?,?,?,'2026-10-01T10:00:00','exif',100,?,"
        "800,600,?,?,'done',?,?,'2026-10-01T10:00:00')",
        (pid, '/x/' + pid, '/x/' + pid, batch, 'm' + pid, dup, grp, kind,
         json.dumps(vision) if vision else None))
    return pid


def tok(pid, text, conf=0.95):
    store.add_tokens(con, pid, [{'t': text, 'c': conf}])


# 柜A：
mk('p_linked', vision=['C-EXACT1'])       # 会关联 → 不该出现在任何待办档
mk('p_cand', vision=['C-EXACT1'])          # 读码像 C-EXACT1，未关联 → 待确认关联
mk('p_sub', vision=['C-SUB1-EXTRA'])       # 子串命中 → 待确认关联
mk('p_new', vision=['9999999999999'])      # 库里没有 → 新产品确认
mk('p_dup', vision=['9999999999998'], dup=1)   # 重复件：不该进任何档
mk('p_scene', kind='scene', vision=['9999999999997'])  # 场景照：不该进任何档
mk('p_tok')                               # OCR 读码命中 → 待确认关联
tok('p_tok', 'C-EXACT1', 0.99)
mk('p_plain')                              # 什么都没读出来 → 只算「未关联」
# 柜B（验证按柜过滤）：
mk('p_b_new', batch='b2', vision=['8888888888888'])
con.commit()

store.link(con, BL.normalize('C-EXACT1'), 'p_linked', source='manual',
           confidence=1.0, created_by='test')
con.commit()

# ══════════════════════════════════════════════════════════════════
# ① 与既有口径同源
# ══════════════════════════════════════════════════════════════════
cand_ids = store.cand_photo_ids(con)
np_map = store.newprod_photo_map(con)
np_ids = set(np_map)

chk('F1 待确认关联含读码精确命中', 'p_cand' in cand_ids, sorted(cand_ids))
chk('F2 待确认关联含 OCR 命中', 'p_tok' in cand_ids, sorted(cand_ids))
chk('F3 待确认关联含子串命中', 'p_sub' in cand_ids, sorted(cand_ids))
chk('F4 已关联的不在待确认里', 'p_linked' not in cand_ids)
chk('F5 重复件不在待确认里', 'p_dup' not in cand_ids, sorted(cand_ids))
chk('F6 场景照不在待确认里', 'p_scene' not in cand_ids, sorted(cand_ids))
chk('F7 新产品确认含库中无的编码', 'p_new' in np_ids, sorted(np_ids))
chk('F8 重复件不在新产品确认里', 'p_dup' not in np_ids, sorted(np_ids))
chk('F9 场景照不在新产品确认里', 'p_scene' not in np_ids, sorted(np_ids))
chk('F10 已关联的不在新产品确认里', 'p_linked' not in np_ids)
chk('F11 两档都只含未关联照片',
    not ({'p_linked'} & (cand_ids | np_ids)))

# 与页面口径逐一对账（不能用同一份实现自证，要对**页面用的那个函数**）
_dc = store.discovered_products(con)
chk('F12 新产品确认集合 == 发现页 photo_ids 并集',
    np_ids == {p for d in _dc for p in d['photo_ids']},
    '%s vs %s' % (sorted(np_ids),
                  sorted({p for d in _dc for p in d['photo_ids']})))
_cc = store.cand_counts(con)
_cand_from_counts = set()
for cn, c in _cc.items():
    if (c['code'] or 0) + (c['group'] or 0) > 0:
        _cand_from_counts |= set(store.cand_code_map(con).get(cn) or {})
chk('F13 待确认集合 == 列表角标口径（cand_counts 背后的 map）',
    cand_ids == _cand_from_counts,
    '%s vs %s' % (sorted(cand_ids), sorted(_cand_from_counts)))

# ══════════════════════════════════════════════════════════════════
# ② 五档计数与列表条数一致（徽章不能漂）
# ══════════════════════════════════════════════════════════════════
def list_count(**kw):
    """按 photo_where_sql 数一遍 —— 与 /api/photos 的 total 同源。"""
    _j, frag, args = store.photo_where_sql(**kw)
    sql = ('SELECT COUNT(*) FROM (SELECT p.id FROM photos p' + _j + frag + ')')
    return con.execute(sql, args).fetchone()[0]


def flag_count(ids, **kw):
    _j, frag, args = store.photo_where_sql(**kw)
    ids = list(ids)
    parts, ea = [], []
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        parts.append('p.id IN (%s)' % ','.join('?' * len(chunk)))
        ea.extend(chunk)
    frag += (' WHERE ' if not frag.strip() else ' AND ') + '(%s)' % ' OR '.join(parts)
    return con.execute('SELECT COUNT(*) FROM (SELECT p.id FROM photos p'
                       + _j + frag + ')', list(args) + ea).fetchone()[0]


c = store.photo_flag_counts(con)
chk('F14 全部计数 == 列表不加筛选的条数',
    c['all'] == list_count(), '%s vs %s' % (c['all'], list_count()))
chk('F15 已关联计数 == 列表 linked=1 的条数',
    c['linked'] == list_count(linked=1), '%s vs %s' % (c['linked'], list_count(linked=1)))
chk('F16 未关联计数 == 列表 unlinked=1 的条数',
    c['unlinked'] == list_count(unlinked=1),
    '%s vs %s' % (c['unlinked'], list_count(unlinked=1)))
chk('F17 待确认计数 == 列表按 cand_ids 过滤的条数',
    c['cand'] == flag_count(c['cand_ids']),
    '%s vs %s' % (c['cand'], flag_count(c['cand_ids'])))
chk('F18 新产品计数 == 列表按 newprod_ids 过滤的条数',
    c['newprod'] == flag_count(c['newprod_ids']),
    '%s vs %s' % (c['newprod'], flag_count(c['newprod_ids'])))
chk('F19 待确认 + 新产品 ≤ 未关联（两者都是未关联的子集）',
    c['cand'] + c['newprod'] <= c['unlinked'],
    '%d + %d <= %d' % (c['cand'], c['newprod'], c['unlinked']))

# ══════════════════════════════════════════════════════════════════
# ③ 按柜过滤（向导③只看本柜）
# ══════════════════════════════════════════════════════════════════
cid_a = con.execute("SELECT id FROM containers LIMIT 1").fetchone()
# 直接用 batch 维度的等价口径：柜A 的照片 = batch b1
ca = store.photo_flag_counts(con, batch_id='b1')
chk('F20 按批次过滤后全部 == 该批次照片数',
    ca['all'] == con.execute('SELECT COUNT(*) FROM photos WHERE batch_id=?',
                             ('b1',)).fetchone()[0], ca['all'])
chk('F21 按批次过滤后不含别的批次照片',
    'p_b_new' not in ca['newprod_ids'], ca['newprod_ids'])
chk('F22 按批次过滤后新产品计数正确',
    ca['newprod'] == 1, ca['newprod'])

# ══════════════════════════════════════════════════════════════════
# ④ 人工动作后集合与计数实时下降（缓存不撒谎）
# ══════════════════════════════════════════════════════════════════
store.link(con, BL.normalize('C-EXACT1'), 'p_cand', source='manual',
           confidence=1.0, created_by='test')
con.commit()
c2 = store.photo_flag_counts(con)
chk('F23 关联后待确认计数下降', c2['cand'] == c['cand'] - 1,
    '%s -> %s' % (c['cand'], c2['cand']))
chk('F24 关联后该照片不在待确认集合里', 'p_cand' not in store.cand_photo_ids(con))
chk('F25 关联后已关联计数上升', c2['linked'] == c['linked'] + 1,
    '%s -> %s' % (c['linked'], c2['linked']))

# 标记「无关联」→ 从待确认里消失（与列表角标同步降）
n_before = store.cand_counts(con).get(BL.normalize('C-SUB1'), {}).get('code', 0)
store.reject_candidate(con, 'C-SUB1', 'p_sub', '人工看过，没有关联')
con.commit()
n_after = store.cand_counts(con).get(BL.normalize('C-SUB1'), {}).get('code', 0)
chk('F26 标记无关联后角标下降', n_after == n_before - 1,
    '%s -> %s' % (n_before, n_after))
chk('F27 标记无关联后该照片不在待确认集合里',
    'p_sub' not in store.cand_photo_ids(con))

# 忽略新产品候选 → 照片从新产品确认里消失
store.ignore_discovery(con, BL.normalize('9999999999999'))
con.commit()
chk('F28 忽略候选后照片不再算新产品确认',
    'p_new' not in store.newprod_photo_map(con), sorted(store.newprod_photo_map(con)))

# ══════════════════════════════════════════════════════════════════
# ⑤ 角标端点用的 photo_flag_map（只算给定 ids）
# ══════════════════════════════════════════════════════════════════
_fm = store.photo_flag_map(con, ['p_new', 'p_plain', 'p_linked'])
chk('F31 photo_flag_map 只返回传入的 id', set(_fm) <= {'p_new', 'p_plain', 'p_linked'},
    sorted(_fm))
chk('F32 不传 ids 时只返回「有待办」的（不是全部照片）',
    set(store.photo_flag_map(con))
    == (store.cand_photo_ids(con) | set(store.newprod_photo_map(con))),
    'cand=%s np=%s' % (sorted(store.cand_photo_ids(con)),
                       sorted(store.newprod_photo_map(con))))
chk('F33 没待办的照片不出现在结果里',
    'p_plain' not in _fm and 'p_linked' not in _fm, sorted(_fm))

# ══════════════════════════════════════════════════════════════════
# ⑥ 空集合不炸（空库是最常见的第一天状态）
# ══════════════════════════════════════════════════════════════════
c3 = store.photo_flag_counts(con, container_id='不存在的柜')
chk('F29 空范围五档全 0 且不抛异常',
    c3['all'] == 0 and c3['cand'] == 0 and c3['newprod'] == 0, c3)
chk('F30 空范围的 id 列表是空数组（不是 null）',
    c3['cand_ids'] == [] and c3['newprod_ids'] == [], c3)

# ══════════════════════════════════════════════════════════════════
# ⑦ 监装照片不进关联队列（2026-10-16 老板需求：监装不需要关联）
# ══════════════════════════════════════════════════════════════════
_base = store.photo_flag_counts(con)
_st_before = store.stats(con)['unlinked']
mk('p_sup_unl')                              # 监装 + 没读出码 → 只该在「全部」
mk('p_sup_code', vision=['C-EXACT1'])        # 监装 + 读出库内码 → 不进待确认
mk('p_sup_new', vision=['7777777777777'])    # 监装 + 读出库外码 → 不进新产品
mk('p_pre_plain')                            # 预检 + 没读出码 → 仍然算未关联
for pid in ('p_sup_unl', 'p_sup_code', 'p_sup_new'):
    con.execute("UPDATE photos SET photo_usage='监装' WHERE id=?", (pid,))
con.execute("UPDATE photos SET photo_usage='预检' WHERE id='p_pre_plain'")
con.commit()

c4 = store.photo_flag_counts(con)
chk('F34 全部计数 +4（监装/预检照片都还是照片）',
    c4['all'] == _base['all'] + 4,
    '%s -> %s' % (_base['all'], c4['all']))
chk('F35 未关联计数只 +1（4 张新照片里只有预检那张进队列）',
    c4['unlinked'] == _base['unlinked'] + 1,
    '%s -> %s' % (_base['unlinked'], c4['unlinked']))
chk('F36 待确认计数不变（监装照片读出的码不算候选）',
    c4['cand'] == _base['cand'],
    '%s -> %s' % (_base['cand'], c4['cand']))
chk('F37 新产品计数不变（监装照片读出的新码不算新产品）',
    c4['newprod'] == _base['newprod'],
    '%s -> %s' % (_base['newprod'], c4['newprod']))
chk('F38 首页未关联数只 +1（stats 同口径）',
    store.stats(con)['unlinked'] == _st_before + 1,
    '%s -> %s' % (_st_before, store.stats(con)['unlinked']))


def list_ids(**kw):
    """按 photo_where_sql 取 id 列表 —— 与 /api/photos 的 total 同源。"""
    _j, frag, args = store.photo_where_sql(**kw)
    return [r[0] for r in con.execute(
        'SELECT p.id FROM photos p' + _j + frag, args)]


_ul = list_ids(unlinked=1)
chk('F39 未关联列表不含监装照片、含预检照片',
    not ({'p_sup_unl', 'p_sup_code', 'p_sup_new'} & set(_ul))
    and 'p_pre_plain' in _ul, sorted(_ul))
chk('F40 未关联工作台（unlinked_photos）不含监装照片',
    'p_sup_unl' not in {r['id'] for r in
                        store.unlinked_photos(con, limit=200)})
chk('F41 待确认集合不含监装照片',
    not ({'p_sup_code'} & set(store.cand_photo_ids(con))),
    sorted(store.cand_photo_ids(con)))
chk('F42 新产品集合不含监装照片',
    'p_sup_new' not in set(store.newprod_photo_map(con)),
    sorted(store.newprod_photo_map(con)))
chk('F43 合并建议（merge_suggestions）不含监装照片',
    'p_sup_code' not in {it['photo_id'] for s in store.merge_suggestions(con)
                         for k in ('exact', 'fuzzy') for it in s.get(k, [])})

# ⑧ 本次忽略（2026-10-18 老板需求：新产品确认可标记本次忽略）
# ══════════════════════════════════════════════════════════════════
_base8 = store.photo_flag_counts(con)
_st8 = store.stats(con)
chk('F44 忽略前：待关联里有 p_pre_plain', 'p_pre_plain' in list_ids(unlinked=1),
    sorted(list_ids(unlinked=1)))
store.set_photo_ignored(con, ['p_pre_plain'], 1, by='tester')
c8 = store.photo_flag_counts(con)
chk('F45 忽略后：待关联计数 -1（退出队列）',
    c8['unlinked'] == _base8['unlinked'] - 1,
    '%s -> %s' % (_base8['unlinked'], c8['unlinked']))
chk('F46 忽略后：待关联列表不含它', 'p_pre_plain' not in list_ids(unlinked=1),
    sorted(list_ids(unlinked=1)))
chk('F47 已忽略档计数 = 1', c8['ignored'] == 1, c8['ignored'])
chk('F48 已忽略列表：photo_ignored=1 可查',
    [r['id'] for r in con.execute(
        'SELECT id FROM photos WHERE photo_ignored=1')] == ['p_pre_plain'],
    [r['id'] for r in con.execute('SELECT id FROM photos WHERE photo_ignored=1')])
chk('F49 stats 待关联数同步 -1（同源）',
    store.stats(con)['unlinked'] == _st8['unlinked'] - 1,
    '%s -> %s' % (_st8['unlinked'], store.stats(con)['unlinked']))
# 恢复：回队列
store.set_photo_ignored(con, ['p_pre_plain'], 0, by='tester')
c8b = store.photo_flag_counts(con)
chk('F50 恢复后：待关联计数回来',
    c8b['unlinked'] == _base8['unlinked'] and c8b['ignored'] == 0,
    'unlinked=%s ignored=%s' % (c8b['unlinked'], c8b['ignored']))
chk('F51 幂等：重复忽略第 2 次返回 0 变更',
    store.set_photo_ignored(con, ['p_pre_plain'], 1, by='tester') == 1
    and store.set_photo_ignored(con, ['p_pre_plain'], 1, by='tester') == 0)
store.set_photo_ignored(con, ['p_pre_plain'], 0, by='tester')
# 忽略的照片也不进新产品/待确认候选
chk('F52 忽略前：新产品集合含 p_b_new', 'p_b_new' in store.newprod_photo_map(con),
    sorted(store.newprod_photo_map(con)))
store.set_photo_ignored(con, ['p_b_new'], 1, by='tester')
chk('F52b 忽略后：新产品确认集合不含被忽略的',
    'p_b_new' not in set(store.newprod_photo_map(con)),
    sorted(store.newprod_photo_map(con)))
store.set_photo_ignored(con, ['p_b_new'], 0, by='tester')
chk('F53 恢复后：新产品集合回来',
    'p_b_new' in store.newprod_photo_map(con),
    sorted(store.newprod_photo_map(con)))
con.close()
shutil.rmtree(tmp, ignore_errors=True)
print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
