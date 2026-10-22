# -*- coding: utf-8 -*-
"""产品库柜号筛选：「全部柜号」必须真的覆盖所有柜（2026-10-07）。

老板报「筛选的『全部柜号』，没有所有的柜号」。根因：柜号解析散在**三处**
各写一份 SQL，且三份都只认 `batches.container_no` —— v3 之前的**冗余列**，
早已停止维护。真实库实测：22 个批次里 13 个 container_no IS NULL，未分柜
只统计到 524（真值 781），三档之和 1051 ≠ 总数 786。

🔴 本测试锁死的是**不变量**，不是某个具体数字：
  1 并集不变量：所有柜筛出来的并集 == 不筛选总数（**没有产品是隐形的**）；
     ⚠️ 注意**不能**断言「各柜之和 == 总数」—— 同一产品可以出现在多个柜的
     清单里（老板 10-07 真实库里 EMCU9914616 有 447 件、未分柜 785 件，
     并集 786），逐档相加天然大于总数，那是**正常重叠**不是 bug。
  2 档内去重：单柜筛选的行数 == 该柜去重数（不能自己跟自己重复计数）；
  3 下拉 == 柜实体表全量（含**一个产品都没有的空柜**，否则用户想查
     「这个柜为什么一件都没有」时根本选不到那个柜）；
  4 同一柜不被算成两行（未分柜曾同时以 `_UNCATEGORIZED` 和 NULL 出现两次）；
  5 老库兜底：只有 container_no、没挂 container_id 的批次，其产品不能
     凭空消失（改成纯 container_id 关联的老坑）；
  6 下拉与筛选**同源**：下拉里的每个柜号筛得出去，且 label 不泄露内部值。
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema  # noqa: E402
import build_library as BL  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_contnr_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


# ── 造三柜 ──
# ct1: 批次挂 container_id，且 container_no 有值（正常新库形态）
# ct2: 批次挂 container_id，但 container_no 是 NULL（← 老板库里 13/22 的形态）
# ct3: 空柜，一个产品都没有（必须出现在下拉里）
# ct4: 老库形态 —— 批次不挂 container_id，只有 container_no
for cid, cno in (('ct1', 'CAB1000001'), ('ct2', 'CAB2000002'),
                 ('ct3', 'CAB3000003'), ('ct4', 'CAB4000004')):
    con.execute("INSERT INTO containers(id,container_no,created_at,updated_at)"
                " VALUES(?,?, '2026-10-07','2026-10-07')", (cid, cno))


def mkbatch(bid, cid, cno, kind='checklist'):
    con.execute("INSERT INTO batches(id,name,kind,container_id,container_no,created_at)"
                " VALUES(?,?,'%s',%s,%s,'2026-10-07')"
                % (kind, repr(cid) if cid else 'NULL', repr(cno) if cno else 'NULL'),
                (bid, bid))


def mkprod(code, batch):
    cn = BL.normalize(code)
    con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
                " VALUES(?,?,?, '2026-10-07','2026-10-07')", (code, cn, '品' + code))
    con.execute("INSERT INTO product_batch(code_norm,batch_id,created_at)"
                " VALUES(?,?, '2026-10-07')", (cn, batch))


mkbatch('b1', 'ct1', 'CAB1000001')
mkbatch('b2', 'ct2', None)            # 🔴 container_no 为 NULL
mkbatch('b3', None, 'CAB4000004')     # 🔴 老库：不挂 container_id
for i in range(3):
    mkprod('P-A%d' % i, 'b1')
for i in range(5):
    mkprod('P-B%d' % i, 'b2')         # 这 5 件在旧口径下会被整批漏掉
for i in range(2):
    mkprod('P-D%d' % i, 'b3')
con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
            " VALUES('P-X9',?,'无柜产品','2026-10-07','2026-10-07')",
            (BL.normalize('P-X9'),))
con.commit()

CNOS = [it['container_no'] for it in store.product_containers(con)]
TOT = store.count_products(con)


def union_count2(c2_, cnos):
    """在指定连接上算「命中任一柜」的产品数。"""
    frag, _ = store._container_filter_sql('p.code_norm')
    parts, args = [], []
    for cn in cnos:
        parts.append(frag)
        args += [cn] * 4
    return c2_.execute('SELECT COUNT(*) n FROM products p WHERE '
                       + ' OR '.join(parts), args).fetchone()['n']


def union_count(cnos):
    return union_count2(con, cnos)


# ── 1 下拉覆盖全部柜（含空柜）──
chk('T1 下拉包含全部 4 个柜（含无产品的 CAB3000003）',
    set(CNOS) == {'CAB1000001', 'CAB2000002', 'CAB3000003', 'CAB4000004'}, CNOS)
chk('T2 空柜也在下拉里（能查「这柜为什么一件都没有」）',
    'CAB3000003' in CNOS)
chk('T3 下拉无重复（同一柜不出现两次）', len(CNOS) == len(set(CNOS)), CNOS)
empty = [it for it in store.product_containers(con) if it['container_no'] == 'CAB3000003']
chk('T4 空柜计数为 0 而不是缺字段', empty and empty[0]['products'] == 0, empty)

# ── 2 🔴 并集不变量：没有产品是隐形的 ──
# ⚠️ 上面刻意造了一个 P-X9「不属于任何柜」的产品，所以这里的正确断言是
#    「并集 == 总数 - 真正无归属的产品数」，不是「并集 == 总数」。
#    业务含义：**凡是挂了柜的产品，一个都不能漏**；无归属产品本来就不该
#    出现在任何柜档里（它靠「全部柜号」这一档才能被看到）。
u = union_count(CNOS)
chk('T5 🔴 挂了柜的产品一个都不漏（并集 10 == 总数 11 - 无归属 1）',
    u == TOT - 1, '并集=%d 总数=%d' % (u, TOT))

# ── 3 container_no 为 NULL 的批次，其产品不能漏 ──
n2 = store.count_products(con, container_no='CAB2000002')
chk('T6 🔴 container_no 为 NULL 的批次产品没被漏掉（应 5）', n2 == 5, n2)
c2 = [it for it in store.product_containers(con)
      if it['container_no'] == 'CAB2000002']
chk('T7 下拉里该柜计数也是 5（下拉与筛选同源）',
    c2 and c2[0]['products'] == 5, c2)

# ── 4 老库兜底 ──
n4 = store.count_products(con, container_no='CAB4000004')
chk('T8 老库批次（无 container_id）产品没消失（应 2）', n4 == 2, n4)

# ── 5 档内不重复计数 ──
for cn in CNOS:
    frag, _ = store._container_filter_sql('p.code_norm')
    r = con.execute('SELECT COUNT(*) n, COUNT(DISTINCT p.code_norm) d'
                    ' FROM products p WHERE ' + frag, [cn] * 4).fetchone()
    chk('T9 档内不重复计数：%s' % cn, r['n'] == r['d'], '%s/%s' % (r['n'], r['d']))

# ── 6 关键字 + 柜号叠加不报错、且是子集 ──
n_kw = store.count_products(con, keyword='P-A', container_no='CAB1000001')
chk('T10 关键字+柜号可叠加', n_kw == 3, n_kw)
chk('T11 叠加筛选是总数的子集', n_kw <= TOT)

# ── 7 list 与 count 同源（翻页总数必须等于列表条件）──
rows = store.list_products(con, container_no='CAB2000002', limit=200)
chk('T12 list 与 count 口径一致（都是 5）',
    len(rows) == store.count_products(con, container_no='CAB2000002') == 5,
    (len(rows), store.count_products(con, container_no='CAB2000002')))

# ── 8 label 不泄露内部值 ──
for it in store.product_containers(con):
    chk('T13 label 不是内部值：%s' % it['container_no'],
        it['label'] != schema.UNCATEGORIZED_NO, it['label'])

# ── 9 container_list 列能显示出柜号（与筛选同源）──
rows = store.list_products(con, limit=200)
cl = [r['container_list'] for r in rows if r['container_list']]
chk('T14 container_list 有值（列表柜号列不再是空的）', len(cl) > 0, len(cl))
chk('T15 container_list 里能看到 CAB2000002（NULL 列柜也显示得出）',
    any('CAB2000002' in (x or '') for x in cl))

# ── 10 未分柜场景（老板真实库里踩到的那条）──
con2 = store.connect(os.path.join(tmp, 'u.db'))
con2.execute("INSERT INTO containers(id,container_no,created_at,updated_at)"
             " VALUES('u1',?,'2026-10-07','2026-10-07')",
             (schema.UNCATEGORIZED_NO,))
con2.execute("INSERT INTO batches(id,name,kind,container_id,container_no,created_at)"
             " VALUES('ub1','ub1','checklist','u1',NULL,'2026-10-07')")
con2.execute("INSERT INTO batches(id,name,kind,container_id,container_no,created_at)"
             " VALUES('ub2','ub2','checklist','u1',?,'2026-10-07')",
             (schema.UNCATEGORIZED_NO,))
for i in range(4):
    cn = BL.normalize('Q-%d' % i)
    con2.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
                 " VALUES(?,?,'x','2026-10-07','2026-10-07')", ('Q-%d' % i, cn))
    con2.execute("INSERT INTO product_batch(code_norm,batch_id,created_at)"
                 " VALUES(?,'ub1','2026-10-07')", (cn,))
for i in range(3):
    cn = BL.normalize('R-%d' % i)
    con2.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
                 " VALUES(?,?,'x','2026-10-07','2026-10-07')", ('R-%d' % i, cn))
    con2.execute("INSERT INTO product_batch(code_norm,batch_id,created_at)"
                 " VALUES(?,'ub2','2026-10-07')", (cn,))
con2.commit()
opts = store.product_containers(con2)
chk('T16 未分柜只出现一行（不再被算成两行）', len(opts) == 1, opts)
chk('T17 未分柜计数含 NULL 那批（应 7，旧口径只给 3）',
    opts and opts[0]['products'] == 7, opts)
chk('T18 未分柜筛选 == 7',
    store.count_products(con2, container_no=schema.UNCATEGORIZED_NO) == 7)
chk('T19 未分柜并集 == 总数 7', union_count2(con2, [schema.UNCATEGORIZED_NO]) == 7)

con2.close()
con.close()
shutil.rmtree(tmp, ignore_errors=True)
print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')