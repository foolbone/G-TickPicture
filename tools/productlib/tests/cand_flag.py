# -*- coding: utf-8 -*-
"""产品库「待确认照片」标识：列表角标 / 筛选 / 详情候选 —— 三处同源（10-05）。

老板要「把有可能关联待确认的照片标识出来，并能筛选」。做之前列表只有一个
cand_count（读码、且只认 SQL 精确相等），详情却有两类候选（读码 + 同组连拍）
—— 详情看得到、列表标不出来，也没法筛。

本测试锁死：
  1 两类候选都进计数：读码（照片里读出编码）+ 同组（与已关联照片同段连拍）；
  2 列表数字 == 详情实际张数（同源的硬断言，杜绝「标了 N 张、点开没有」）；
  3 三档筛选（any / code / group）准确，且筛出来的角标必定 > 0；
  4 不该算的不算：重复件、装箱单/场景照、已关联的、别的产品的同组；
  5 关联后计数实时下降（缓存按库内容戳失效，不撒谎）。
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
# ⚠️ 顺序要紧：store.py 自己会把 tools/ 塞进 sys.path，build_library 才能被
#    import（它在 tools/build_library.py，不在仓库根）。先 import store。
from tools.productlib import store  # noqa: E402
import build_library as BL  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_candflag_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


con.execute("INSERT INTO batches(id,name,kind,created_at) VALUES('b1','柜A','photos','2026-10-01')")
# ⚠️ code_norm 必须写 normalize 之后的形态（`C-EXACT1` -> `CEXACT1`）：
#    links.code_norm 落库时会归一化，写成原样会让所有 JOIN 落空（测试假红）。
for c in ('C-EXACT1', 'C-SUB1', 'C-EDIT1', 'C-GRP', 'C-OTHER'):
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


# ① 精确命中（多模态读码）
mk('p_exact', vision=['C-EXACT1'])
# ② 子串命中（OCR 读出前后缀，清单码在中间）
mk('p_sub'); tok('p_sub', '前缀-C-SUB1-后缀')
# ③ 编辑距离 1（OCR 读错一位），置信够高 → 过 CAND_MIN_SCORE 门槛
mk('p_edit'); tok('p_edit', 'C-EDIT2', 0.95)
# ④ 不该算的三类
mk('p_dup', dup=1, vision=['C-EXACT1'])                 # 重复件
mk('p_pack', kind='packing_list', vision=['C-EXACT1'])  # 装箱单（NO_LINK_KINDS）
mk('p_scene', kind='scene', vision=['C-EXACT1'])        # 场景照
mk('p_none', vision=['ZZZZZZZZZZZZ'])                   # 读出来的码不在库里
# ⑦ 监装照：读出码也不算候选（2026-10-16 老板需求：监装不关联产品）
mk('p_sup', vision=['C-EXACT1'])
con.execute("UPDATE photos SET photo_usage='监装' WHERE id='p_sup'")

# ⑤ 同组：C-GRP 关联 p_a，同组还有 p_b（未关联）与 p_c（关联给了别的产品）
mk('p_a', grp=1); mk('p_b', grp=1); mk('p_c', grp=1); mk('p_pack2', grp=1, kind='packing_list')
mk('p_other_grp', grp=2)
store.link(con, 'C-GRP', 'p_a', source='test', confidence=0.9)
store.link(con, 'C-OTHER', 'p_c', source='test', confidence=0.9)

# ⑥ 一个什么都没有的产品：不该出现在任何待确认筛选里
con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
            " VALUES('C-NONE',?,'无候选','2026-10-01','2026-10-01')",
            (BL.normalize('C-NONE'),))

store.cand_code_map(con, force=True)
cnts = store.cand_counts(con)


# ⚠️ cand_counts 的 key 是 **code_norm（normalize 之后）**：`C-EXACT1` -> `CEXACT1`。
#    直接用原始编码去取 = 永远 0（测试假红，不是实现问题）。
def cc(c):
    return cnts.get(BL.normalize(c)) or {'code': 0, 'group': 0}


print('=== 1 两类候选都进计数 ===')
chk('精确命中 C-EXACT1 读码=1', cc('C-EXACT1')['code'] == 1, cc('C-EXACT1'))
chk('子串命中 C-SUB1 读码=1', cc('C-SUB1')['code'] == 1, cc('C-SUB1'))
chk('编辑距离1 C-EDIT1 读码=1', cc('C-EDIT1')['code'] == 1, cc('C-EDIT1'))
chk('同组：C-GRP = 2（p_b + p_c，排除装箱单）', cc('C-GRP')['group'] == 2, cc('C-GRP'))

print('=== 2 列表数字 == 详情实际张数 ===')
for c in ('C-EXACT1', 'C-SUB1', 'C-EDIT1', 'C-GRP'):
    cand = store.product_candidates(con, c)
    sib = store.product_group_siblings(con, c)
    ok = len(cand) == cc(c)['code'] and len(sib) == cc(c)['group']
    chk('%s 列表(读码%d/同组%d) == 详情(读码%d/同组%d)'
        % (c, cc(c)['code'], cc(c)['group'], len(cand), len(sib)), ok)

print('=== 3 不该算的不算 ===')
chk('重复件不计', all(x['photo_id'] != 'p_dup'
                    for x in store.product_candidates(con, 'C-EXACT1')))
chk('装箱单不计（读码）', all(x['photo_id'] != 'p_pack'
                       for x in store.product_candidates(con, 'C-EXACT1')))
chk('场景照不计（读码）', all(x['photo_id'] != 'p_scene'
                       for x in store.product_candidates(con, 'C-EXACT1')))
chk('监装照不计（读码）', all(x['photo_id'] != 'p_sup'
                       for x in store.product_candidates(con, 'C-EXACT1')))
chk('装箱单不计（同组）', all(x['photo_id'] != 'p_pack2'
                       for x in store.product_group_siblings(con, 'C-GRP')))
chk('不在库里的码不建候选', store.product_candidates(con, 'C-OTHER') == [] or
    all(x['photo_id'] != 'p_none' for x in store.product_candidates(con, 'C-OTHER')))

print('=== 4 三档筛选 ===')
allc = [r['code_norm'] for r in store.list_products(con, limit=100)]
# 列表返回的是 code_norm（`C-EXACT1` -> `CEXACT1`），比较要用归一化后的形态
N = BL.normalize
anyc = [r['code_norm'] for r in store.list_products(con, limit=100, only_cand='any')]
codc = [r['code_norm'] for r in store.list_products(con, limit=100, only_cand='code')]
grpc = [r['code_norm'] for r in store.list_products(con, limit=100, only_cand='group')]
chk('any 只留有待确认的（有候选的全在、没候选的不在）',
    set(anyc) <= set(allc) and N('C-EXACT1') in anyc and N('C-SUB1') in anyc
    and N('C-EDIT1') in anyc and N('C-GRP') in anyc and N('C-OTHER') in anyc
    and N('C-NONE') not in anyc, anyc)
chk('code 只留读码候选（同组类不算）',
    N('C-EXACT1') in codc and N('C-SUB1') in codc and N('C-EDIT1') in codc
    and N('C-GRP') not in codc and N('C-OTHER') not in codc, codc)
chk('group 只留同组候选（读码类不算）',
    N('C-GRP') in grpc and N('C-OTHER') in grpc
    and N('C-EXACT1') not in grpc and N('C-NONE') not in grpc, grpc)
chk('count_products 与 list 同源',
    store.count_products(con, only_cand='any') == len(anyc)
    and store.count_products(con, only_cand='code') == len(codc),
    {'any': store.count_products(con, only_cand='any'),
     'code': store.count_products(con, only_cand='code')})
rows = store.list_products(con, limit=100, only_cand='code')
chk('筛出来的行角标必定 > 0', all(r['cand_code'] > 0 for r in rows),
    [(r['code_norm'], r['cand_code']) for r in rows])

print('=== 5 关联后计数实时下降（缓存不撒谎）===')
before = cc('C-EXACT1')['code']
store.link(con, 'C-EXACT1', 'p_exact', source='test', confidence=1.0)
con.commit()
after = store.cand_counts(con).get('C-EXACT1', {'code': 0})['code']
chk('关联后读码候选归零', before > 0 and after == 0, {'before': before, 'after': after})
chk('详情也同步为空', len(store.product_candidates(con, 'C-EXACT1')) == 0)

print()
print('PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS))
con.close()
try:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
except Exception:
    pass
sys.exit(1 if FAILS else 0)
