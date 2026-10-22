# -*- coding: utf-8 -*-
"""检索页「缺口」文案必须区分：真缺口 vs 被批次挡住的假缺口（10-05）。

═══ 老板报的现象 ═══
检索页勾了批次后检索编码，结果写「编码在库但所选批次内无照片」，
但标准产品页里明明能看到这个编码的照片 —— 像是数据丢了。

═══ 根因 ═══
report_lookup() 只算了一份结果（先按批次过滤、再按标准图过滤），
空了就报「所选批次内无照片」。于是两种完全不同的情况被合成一句话：

  A 真缺口：全库根本没有关联照片   → 应该说「没有关联照片」
  B 假缺口：照片在，但在别的批次   → 应该说「在其他 N 个批次共 M 张」+ 列出批次

老板在标准产品页看到的正是 B（产品页从不按批次过滤）。B 被说成
「无照片」，等于把「你的筛选范围窄了」报错成「数据没了」——
**提示撒谎比没提示更伤信任**。

本测试锁死：A/B 分开、B 给出批次清单与张数、std_only 组合同样成立、
不勾批次时行为不变（兼容）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_gap_')
con = store.connect(os.path.join(tmp, 't.db'))

FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


# ── 造数据：两个批次，两个产品 ────────────────────────────
con.execute("INSERT INTO batches(id,name,kind,created_at) VALUES('b1','柜A','photos','2026-10-01')")
con.execute("INSERT INTO batches(id,name,kind,created_at) VALUES('b2','柜B','photos','2026-10-02')")

con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at) "
            "VALUES('C1','C1','在别的批次','2026-10-01','2026-10-01')")
con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at) "
            "VALUES('C2','C2','全库都没照片','2026-10-01','2026-10-01')")
con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at) "
            "VALUES('C3','C3','就在本批次','2026-10-01','2026-10-01')")


def mk(pid, batch, dup=0):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,created_at) '
        "VALUES(?,?,?,?,'2026-10-01T10:00:00','exif',100,?,"
        "800,600,?,0,'done','label','2026-10-01T10:00:00')",
        (pid, '/x/' + pid, '/x/' + pid, batch, 'm' + pid, dup))


mk('p1', 'b1')      # C1 的照片在 b1
mk('p2', 'b1')      # C1 的第二张（也在 b1）
mk('p3', 'b2')      # C3 的照片在 b2
store.link(con, 'C1', 'p1', source='test', confidence=0.9)
store.link(con, 'C1', 'p2', source='test', confidence=0.9)
store.link(con, 'C3', 'p3', source='test', confidence=0.9)
# C2 故意不建任何关联

print('=== 1 只选 b2：C1 的照片在 b1 → 假缺口，必须说出批次与张数 ===')
r = {x['code']: x for x in store.report_lookup(con, ['C1'], batch_ids=['b2'])}
a = r['C1']
chk('判为缺口', a['found'] is False)
chk('文案不再只说「所选批次内无照片」', '无照片（其他' in a['reason'], a['reason'])
chk('给出张数 2', a.get('other_count') == 2, a.get('other_count'))
ob = a.get('other_batches') or []
chk('给出批次名「柜A」', any(x['name'] == '柜A' and x['n'] == 2 for x in ob), ob)

print('=== 2 只选 b2：C2 全库都没有 → 真缺口，不许甩锅给批次 ===')
r = {x['code']: x for x in store.report_lookup(con, ['C2'], batch_ids=['b2'])}
b = r['C2']
chk('判为缺口', b['found'] is False)
chk('文案 = 没有关联照片（不提批次）', b['reason'] == '编码在库但没有关联照片', b['reason'])
chk('不带 other_batches', not b.get('other_batches'))

print('=== 3 不勾批次：行为与改动前一致（兼容） ===')
r = {x['code']: x for x in store.report_lookup(con, ['C1', 'C2', 'C3'])}
chk('C1 命中（全库能找到 2 张）', r['C1']['found'] and r['C1']['photo_count'] == 2,
    r['C1'].get('photo_count'))
chk('C2 真缺口文案不变', r['C2']['reason'] == '编码在库但没有关联照片', r['C2']['reason'])
chk('C3 命中', r['C3']['found'])

print('=== 4 选对批次：C1 在 b1 → 正常命中，不该是缺口 ===')
r = {x['code']: x for x in store.report_lookup(con, ['C1'], batch_ids=['b1'])}
chk('C1 命中', r['C1']['found'] and r['C1']['photo_count'] == 2, r['C1'].get('photo_count'))

print('=== 5 std_only 组合：没有标准图时，真缺口要说「没做过标准图」 ===')
r = {x['code']: x for x in store.report_lookup(con, ['C1'], batch_ids=[], std_only=True)}
chk('全库 std_only → 没有做过标准图的照片',
    r['C1']['reason'] == '编码在库但没有做过标准图的照片', r['C1']['reason'])

print()
print('PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS))
con.close()
try:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
except Exception:
    pass
sys.exit(1 if FAILS else 0)
