# -*- coding: utf-8 -*-
"""产品库「柜号」下拉：必须以产品清单里的柜号为准（10-05 老板口径）。

原来的下拉取 /api/batches?kind=photos（照片批次）的柜号，两个问题：
  1 混进与产品无关的柜号 —— 真实库里照片批次的 container_no 塞过交付文件名
    （`集刻交付_柜号9914616_20261001_1120_第01卷-共02卷`），下拉里出现超长选项；
  2 漏掉只登记在清单里、还没拍照的柜号 —— 清单先导入是常见顺序，这些柜号
    在照片批次里根本不存在。

store.product_containers() 只认 product_batch → batches（清单批次）这一路：

  1 清单柜号必在，照片批次柜号（清单没登记的）不出现；
  2 交付文件名那种脏值不出现（它只存在于照片批次）；
  3 products = 该柜号下的去重产品数，batches = 清单批次数；
  4 无柜号 / 空柜号的批次不产生选项；
  5 按产品数降序 —— 一眼看出哪个柜号货最多；
  6 筛选过滤（list_products container_no）选中清单柜号时，数出来的产品数
    == 选项上标注的产品数（同源硬断言）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_containers_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


def batch(bid, name, kind, container):
    con.execute("INSERT INTO batches(id,name,kind,container_no,created_at)"
                " VALUES(?,?,?,?, '2026-10-01')", (bid, name, kind, container))


def bind(code, batch_id):
    con.execute("INSERT OR IGNORE INTO products(code,code_norm,name,created_at,updated_at)"
                " VALUES(?,?,?,?, '2026-10-01')",
                (code, code, '品' + code, '2026-10-01'))
    con.execute("INSERT INTO product_batch(code_norm,batch_id,created_at)"
                " VALUES(?,?, '2026-10-01')", (code, batch_id))


# 清单柜号 A（2 个批次、3 个产品，其中 1 个跨两批）
batch('ckA1', '清单A1', 'checklist', 'UETV8107553')
batch('ckA2', '清单A2', 'checklist', 'UETV8107553')
for c in ('P1', 'P2'):
    bind(c, 'ckA1')
bind('P3', 'ckA2')
bind('P1', 'ckA2')          # P1 跨两个清单批次 —— 去重后仍是 3 个产品
# 清单柜号 B（1 个产品，数量少 → 排后面）
batch('ckB', '清单B', 'checklist', 'EMCU9914616')
bind('P4', 'ckB')
# 无柜号清单批次：不该出现
batch('ckC', '清单C', 'checklist', None)
bind('P5', 'ckC')
# 照片批次：有"交付文件名"脏值 + 有清单里没有的柜号 —— 都不该出现在下拉
batch('phX', '照片X', 'photos', '集刻交付_柜号9914616_20261001_1120_第01卷-共02卷')
batch('phY', '照片Y', 'photos', 'PHOTO_ONLY_BOX')

rows = store.product_containers(con)
nos = [r['container_no'] for r in rows]

chk('1 清单柜号都在', 'UETV8107553' in nos and 'EMCU9914616' in nos, nos)
chk('2 照片批次的脏值/多余柜号不出现',
    '集刻交付_柜号9914616_20261001_1120_第01卷-共02卷' not in nos
    and 'PHOTO_ONLY_BOX' not in nos, nos)
chk('3 无柜号批次不产生选项', len(rows) == 2, len(rows))
a = next(r for r in rows if r['container_no'] == 'UETV8107553')
chk('4 跨批次去重：A 柜 3 件 2 批',
    a['products'] == 3 and a['batches'] == 2, dict(a))
chk('5 按产品数降序', nos[0] == 'UETV8107553', nos)

# 6 同源硬断言：选中 A 柜筛选出来的产品数 == 角标上的 3
got = store.list_products(con, container_no='UETV8107553', limit=100)
cnt = store.count_products(con, container_no='UETV8107553')
chk('6 筛选结果与选项标注同源（A 柜 3 件）',
    len(got) == 3 and cnt == 3 and a['products'] == len(got),
    {'选项': a['products'], '筛选': len(got), 'count': cnt})

# 7 内部兜底柜号不得外泄到界面（10-06 老板在产品库下拉看到 _UNCATEGORIZED）
from tools.productlib import schema  # noqa: E402
chk('7 container_label 把内部值翻成「未分柜」',
    schema.container_label('_UNCATEGORIZED') == '（未分柜）'
    and schema.container_label('') == '（无柜号）'
    and schema.container_label(None) == '（无柜号）'
    and schema.container_label('EMCU9914616') == 'EMCU9914616',
    schema.container_label('_UNCATEGORIZED'))
_unc = store.create_container(con, schema.UNCATEGORIZED_NO)['id']
batch('b_unc', '老批次(无柜号)', 'checklist', schema.UNCATEGORIZED_NO)
bind('P_UNC', 'b_unc')          # 兜底柜下真的挂着产品（才会出现在下拉里）
con.commit()
_opts = store.product_containers(con)
_unc_opt = [x for x in _opts if x['container_no'] == schema.UNCATEGORIZED_NO]
chk('7b product_containers 的 label 不是内部值',
    bool(_unc_opt) and _unc_opt[0]['label'] == '（未分柜）',
    _unc_opt[0] if _unc_opt else '（没有该选项）')
_row = store.list_products(con, limit=5)
chk('7c 产品行的柜号列不含内部值',
    all(schema.UNCATEGORIZED_NO not in (r.get('container_list') or '')
        for r in _row),
    [r.get('container_list') for r in _row][:3])

con.close()
print('PASS' if not FAILS else 'FAIL: ' + ' | '.join(FAILS))
sys.exit(1 if FAILS else 0)
