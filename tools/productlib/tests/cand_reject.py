# -*- coding: utf-8 -*-
"""候选照片「标记为无关联」（10-05 老板口径）。

老板要「可能关联的照片，用户查看确认没有关联的，可以标记为无关联，
之后不在可能关联的图片显示」。

这个功能最容易做坏的地方不是写入，是**它会在别处复活**：
  · 候选是**算出来的**（读码/同组），每次刷新重算 —— 只在前端隐藏等于没标记；
  · 清单重导会跑 relink，用**同一批 token** 重新匹配 —— 刚否掉的关联
    会被无声建回来，标记成了摆设；
  · 列表角标与详情取数是两条 SQL —— 减了一处没减另一处，
    老板会看到「列表少了 1、详情还挂着 1」，进而怀疑整个系统。

所以本测试锁死的是「**标记之后它不会在别处回来**」：
  1 落库持久（重算后仍然没有）；
  2 读码候选 + 同组候选**两处**都不再显示；
  3 列表角标与详情同源（都减，都不撒谎）；
  4 撤销能还原；
  5 **自动关联写不回来**（apply_auto_links 与 relink 都要挡住）；
  6 **只影响这一个产品** —— 同一张照片若是别的产品的候选仍然照常出现
     （老板否的是「它不是 A 的」，不是「它不属于任何产品」）；
  7 人工关联会清掉同对否决（反悔了能关联回来，不被旧标记卡住）。
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
from tools.productlib import pipeline  # noqa: E402
import build_library as BL  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_candrej_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


con.execute("INSERT INTO batches(id,name,kind,created_at) VALUES('b1','柜A','photos','2026-10-05')")
# ⚠️ code_norm 必须写 normalize 之后的形态（`C-A` -> `CA`）：
#    links/cand_reject 落库时都会归一化，写原样会让 JOIN 落空（测试假红）。
for c in ('C-A1', 'C-B1', 'C-GRP'):
    con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
                " VALUES(?,?,?, '2026-10-05','2026-10-05')",
                (c, BL.normalize(c), '品' + c))
N = BL.normalize


def mk(pid, batch='b1', grp=0, dup=0, kind='label', vision=None):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,vision_codes,created_at) '
        "VALUES(?,?,?,?,'2026-10-05T10:00:00','exif',100,?,"
        "800,600,?,?,'done',?,?,'2026-10-05T10:00:00')",
        (pid, '/x/' + pid, '/x/' + pid, batch, 'm' + pid, dup, grp, kind,
         json.dumps(vision) if vision else None))
    return pid


def tok(pid, text, conf=0.95):
    store.add_tokens(con, pid, [{'t': text, 'c': conf}])


# 读码候选：p_a1/p_a2 都读出 C-A；p_b 读出 C-B（验证「只影响本产品」）
mk('p_a1', vision=['C-A1'])
mk('p_a2', vision=['C-A1'])
mk('p_b', vision=['C-B1'])
# 同组候选：C-GRP 关联 p_g1，同组还有 p_g2
mk('p_g1', grp=1); mk('p_g2', grp=1)
store.link(con, 'C-GRP', 'p_g1', source='test', confidence=0.9)
con.commit()

store.invalidate_cand_cache()
store.cand_code_map(con, force=True)


def cc(code, key):
    return (store.cand_counts(con).get(N(code)) or {}).get(key, 0)


def cand_ids(code):
    return [x['photo_id'] for x in store.product_candidates(con, N(code))]


def sib_ids(code):
    return [x['photo_id'] for x in store.product_group_siblings(con, N(code))]


print('=== 1 基线：标记前都有 ===')
chk('C-A 读码候选=2 张', cc('C-A1', 'code') == 2, cand_ids('C-A1'))
chk('C-GRP 同组候选=1 张', cc('C-GRP', 'group') == 1, sib_ids('C-GRP'))

print('=== 2 落库持久：标记后重算仍然没有 ===')
store.reject_candidate(con, 'C-A1', 'p_a1', reason='人工确认')
con.commit()
store.invalidate_cand_cache()
store.cand_code_map(con, force=True)   # 强制重算，模拟刷新页面
chk('详情里不再出现 p_a1', 'p_a1' not in cand_ids('C-A1'), cand_ids('C-A1'))
chk('重算后仍只剩 1 张（刷新不会复活）', cand_ids('C-A1') == ['p_a2'], cand_ids('C-A1'))
chk('列表角标同步下降 2->1', cc('C-A1', 'code') == 1, cc('C-A1', 'code'))
chk('角标 == 详情张数（同源）', cc('C-A1', 'code') == len(cand_ids('C-A1')),
    {'角标': cc('C-A1', 'code'), '详情': len(cand_ids('C-A1'))})

print('=== 3 同组候选也排除 + 角标同源 ===')
store.reject_candidate(con, 'C-GRP', 'p_g2', reason='人工确认')
con.commit()
store.invalidate_cand_cache()
chk('同组详情不再出现 p_g2', 'p_g2' not in sib_ids('C-GRP'), sib_ids('C-GRP'))
chk('同组角标归零', cc('C-GRP', 'group') == 0, cc('C-GRP', 'group'))
chk('同组角标 == 详情张数', cc('C-GRP', 'group') == len(sib_ids('C-GRP')),
    {'角标': cc('C-GRP', 'group'), '详情': len(sib_ids('C-GRP'))})

print('=== 4 只影响这一个产品（粒度是 (产品,照片) 不是照片）===')
chk('p_a1 在 C-B 那边不受影响（它本来不是 C-B 候选）',
    'p_a1' not in cand_ids('C-B1'), cand_ids('C-B1'))
store.reject_candidate(con, 'C-B1', 'p_b', reason='人工确认')
con.commit()
store.invalidate_cand_cache()
chk('标记 p_b 不牵连 C-A 的候选', sorted(cand_ids('C-A1')) == ['p_a2'], cand_ids('C-A1'))
# 同一张照片同时是两个产品的候选时，否 A 不能抹掉 B
mk('p_two', vision=['C-A1', 'C-B1'])
con.commit()
store.invalidate_cand_cache()
store.cand_code_map(con, force=True)
chk('p_two 进了 C-A 与 C-B 两个候选', sorted(cand_ids('C-A1')) == ['p_a2', 'p_two']
    and 'p_two' in cand_ids('C-B1'), {'A': cand_ids('C-A1'), 'B': cand_ids('C-B1')})
store.reject_candidate(con, 'C-A1', 'p_two', reason='人工确认')
con.commit()
store.invalidate_cand_cache()
chk('否掉「p_two 属于 C-A」后，它在 C-B 仍然照常出现',
    'p_two' not in cand_ids('C-A1') and 'p_two' in cand_ids('C-B1'),
    {'A': cand_ids('C-A1'), 'B': cand_ids('C-B1')})

print('=== 5 挡住自动关联（标记不是摆设）===')
# 模拟清单重导后的 relink：同一批 token 重新匹配，会再次命中 C-A / p_a1
idx = pipeline._build_index(con)
hits = pipeline.replay_hits(con, idx, ['p_a1'])
chk('replay_hits 确实又命中了（说明这条路径真实存在）',
    any(h[0] and N(h[0]) == N('C-A1') for h in hits.get('p_a1', [])),
    hits.get('p_a1'))
n = pipeline.apply_auto_links(con, 'p_a1', hits.get('p_a1', []))
con.commit()
has_link = con.execute("SELECT COUNT(*) FROM links WHERE code_norm=? AND photo_id=?",
                       (N('C-A1'), 'p_a1')).fetchone()[0]
chk('apply_auto_links 写不进被否决的关联（写入数=0）', n == 0, {'written': n})
chk('库里确实没有这条关联', has_link == 0, has_link)
# 反面：没被否决的 p_a2 必须仍能自动关联（别把闸门写死成全都不写）
n2 = pipeline.apply_auto_links(con, 'p_a2', hits.get('p_a2') or [('C-A1', 0.95, 'exact', 'OCR:exact')])
con.commit()
ok2 = con.execute("SELECT COUNT(*) FROM links WHERE code_norm=? AND photo_id=?",
                  (N('C-A1'), 'p_a2')).fetchone()[0]
chk('未被否决的 p_a2 仍能自动关联（闸门没写过头）', n2 == 1 and ok2 == 1,
    {'written': n2, 'in_db': ok2})

print('=== 6 撤销能还原 ===')
store.unreject_candidate(con, 'C-A1', 'p_a1')
con.commit()
store.invalidate_cand_cache()
store.cand_code_map(con, force=True)
chk('撤销后照片回到候选', 'p_a1' in cand_ids('C-A1'), cand_ids('C-A1'))
chk('撤销后角标回升', cc('C-A1', 'code') == len(cand_ids('C-A1')),
    {'角标': cc('C-A1', 'code'), '详情': len(cand_ids('C-A1'))})
store.unreject_candidate(con, 'C-A1', 'p_a1')   # 幂等：再撤一次不报错也不重复
chk('重复撤销是幂等的（不报错）', True)

print('=== 7 幂等 + 人工关联清掉否决 ===')
chk('重复标记返回 False（不覆盖原记录）',
    store.reject_candidate(con, 'C-A1', 'p_a1', reason='第一次的理由') is True
    and store.reject_candidate(con, 'C-A1', 'p_a1', reason='第二次的理由') is False)
rows = store.cand_rejects(con, 'C-A1')
one = [r for r in rows if r['photo_id'] == 'p_a1']
chk('库里只有一条记录且保留首次理由', len(one) == 1 and one[0]['reason'] == '第一次的理由',
    one)
# 反悔：先否决，再人工关联 —— 关联应成功且否决被清掉
store.link(con, 'C-A1', 'p_a1', source='manual', confidence=1.0, created_by='user')
con.commit()
left = con.execute("SELECT COUNT(*) FROM cand_reject WHERE code_norm=? AND photo_id=?",
                   (N('C-A1'), 'p_a1')).fetchone()[0]
chk('人工关联后同对否决被清掉（不被旧标记卡住）', left == 0, left)
linked = con.execute("SELECT source FROM links WHERE code_norm=? AND photo_id=?",
                     (N('C-A1'), 'p_a1')).fetchone()
chk('关联确实建成了（人工那一路不被系统闸门误伤）',
    linked is not None and linked['source'] == 'manual',
    dict(linked) if linked else None)

print('=== 8 不存在的照片不该被写进去 ===')
chk('给不存在的 photo_id 标记返回 False',
    store.reject_candidate(con, 'C-A1', 'p_not_exist') is False)
chk('库里没有这条脏记录',
    con.execute("SELECT COUNT(*) FROM cand_reject WHERE photo_id='p_not_exist'"
                ).fetchone()[0] == 0)

print('=== 8b 解除关联也要清否决（否则「关联→解除」变成单向门）===')
# 复现老板的完整操作序列：否决 → 关联 → 解除
store.reject_candidate(con, 'C-UNDO', 'p_undo', reason='先否了')
con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
            " VALUES('C-UNDO',?,'反悔测试','2026-10-05','2026-10-05')",
            (BL.normalize('C-UNDO'),))
con.commit()
mk('p_undo', vision=['C-UNDO'])
con.commit()
store.invalidate_cand_cache()
store.cand_code_map(con, force=True)
store.link(con, 'C-UNDO', 'p_undo', source='manual', confidence=1.0, created_by='user')
con.commit()
store.unlink(con, 'C-UNDO', 'p_undo')
con.commit()
store.invalidate_cand_cache()
store.cand_code_map(con, force=True)
left_undo = con.execute("SELECT COUNT(*) FROM cand_reject WHERE code_norm=? AND photo_id=?",
                        (BL.normalize('C-UNDO'), 'p_undo')).fetchone()[0]
chk('解除关联后否决被清掉', left_undo == 0, left_undo)
chk('解除后照片回到候选（关联→解除是可逆的）',
    'p_undo' in [x['photo_id'] for x in store.product_candidates(con, N('C-UNDO'))],
    [x['photo_id'] for x in store.product_candidates(con, N('C-UNDO'))])

print('=== 9 筛选口径仍然自洽 ===')
rows = store.list_products(con, limit=100, only_cand='code')
for r in rows:
    c = r['code_norm']
    chk('筛出来的 %s 角标>0 且详情确有候选' % c,
        r['cand_code'] > 0 and len(cand_ids(c)) > 0,
        {'角标': r['cand_code'], '详情': len(cand_ids(c))})

print()
print('PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS))
con.close()
try:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
except Exception:
    pass
sys.exit(1 if FAILS else 0)
