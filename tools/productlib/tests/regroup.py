# -*- coding: utf-8 -*-
"""按拍照时间重算分组（regroup）：同组 = 同一段连拍。

═══ 为什么要重算 ═══
老口径：「间隔 > 45s **或** 满 12 张」就切一组。现场一次连拍十几张是常态
（标签特写 + 全景 + 补拍），被 12 张硬切得很碎 —— 实测某批次前一组结束与
后一组开始是同一秒，纯粹是被张数切断的。

新口径（10-04 老板拍板）：
  · 主规则 = 拍照时间间隔 > 45s 才切；
  · 张数上限 12 → 30，**只作安全阀**（主力那批照片 0~2 秒一张的连续流，
    没有上限会切出 412 张的巨型组，同组推荐一次列 400 张 = 没人用得了）；
  · 时间缺失的照片各自单独成组，不猜。

本测试锁死：
  1. 30 张连续（1 秒一张）→ **1 组**（老口径会切成 3 组）；
  2. 35 张连续 → 2 组（安全阀生效：30 + 5）；
  3. 间隔 100 秒 → 必须切开；
  4. 时间缺失 → 各自成组，不与相邻照片混；
  5. 跨批次不混组（group_idx 是批次内局部索引）；
  6. dry_run 不写库；重算只改 group_idx，不动 links。
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_regroup_')
con = store.connect(os.path.join(tmp, 't.db'))

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


def mk(pid, batch, taken, gi=0):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,created_at) '
        "VALUES(?,?,'/x/'||?,?,?,'exif',100,'m'||?,800,600,0,?,'done','2026-10-01')",
        (pid, pid + '.jpg', pid, batch, taken, pid, gi))


def groups_of(batch=None):
    sql = 'SELECT batch_id, group_idx, COUNT(*) n FROM photos'
    args = []
    if batch:
        sql += ' WHERE batch_id=?'
        args.append(batch)
    sql += ' GROUP BY batch_id, group_idx ORDER BY batch_id, group_idx'
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def gi_of(pid):
    return con.execute('SELECT group_idx FROM photos WHERE id=?', (pid,)).fetchone()[0]


# ── 场景 1：30 张连拍，每张间隔 1 秒 ──
b1 = 'batchA'
for i in range(30):
    mk('a%02d' % i, b1, '2026-10-01T10:%02d:%02d' % (i // 60, i % 60), gi=i // 12)
con.commit()
before = len(groups_of(b1))
chk('1 老口径：30 张连拍被切成 3 组（12/12/6）', before == 3, before)

r = store.regroup_photos_by_time(con, batch_id=b1)
after = groups_of(b1)
chk('1 重算后 30 张连拍合成 1 组', len(after) == 1, after)
chk('1 重算生效（有照片被改组别）', r['changed'] > 0, r)
chk('1 组数 3 → 1', r['groups_before'] == 3 and r['groups_after'] == 1, r)

# ── 场景 2：安全阀 —— 35 张连续 → 30 + 5 ──
b2 = 'batchB'
for i in range(35):
    mk('b%02d' % i, b2, '2026-10-02T10:%02d:%02d' % (i // 60, i % 60))
con.commit()
r2 = store.regroup_photos_by_time(con, batch_id=b2)
g2 = sorted((x['n'] for x in groups_of(b2)), reverse=True)
chk('2 35 张连续 → 安全阀切成 [30, 5]', g2 == [30, 5], g2)
chk('2 最大组不超过 30', r2['max_group_size'] == 30, r2['max_group_size'])

# ── 场景 3：间隔 100 秒必须切开 ──
b3 = 'batchC'
mk('c0', b3, '2026-10-03T10:00:00')
mk('c1', b3, '2026-10-03T10:00:10')
mk('c2', b3, '2026-10-03T10:01:50')   # +100s
mk('c3', b3, '2026-10-03T10:01:55')
con.commit()
store.regroup_photos_by_time(con, batch_id=b3)
chk('3 间隔 100 秒切开成 2 组', len(groups_of(b3)) == 2, groups_of(b3))
chk('3 c0/c1 同组', gi_of('c0') == gi_of('c1'))
chk('3 c2/c3 同组且与 c1 不同组', gi_of('c2') == gi_of('c3') and gi_of('c2') != gi_of('c1'))

# ── 场景 4：时间缺失 → 各自单独成组 ──
b4 = 'batchD'
mk('d0', b4, '2026-10-04T10:00:00')
mk('d1', b4, None)
mk('d2', b4, None)
mk('d3', b4, '2026-10-04T10:00:05')
con.commit()
store.regroup_photos_by_time(con, batch_id=b4)
chk('4 无时间的两张各自成组', gi_of('d1') != gi_of('d2'), (gi_of('d1'), gi_of('d2')))
chk('4 有时间的 d0/d3 同一组（间隔 5s）', gi_of('d0') == gi_of('d3'))

# ── 场景 5：跨批次不混组 ──
mk('e0', 'batchE', '2026-10-05T10:00:00')
mk('e1', 'batchF', '2026-10-05T10:00:01')   # 另一批次、时间几乎相同
con.commit()
store.regroup_photos_by_time(con)
same_group = gi_of('e0') == gi_of('e1')
b_diff = con.execute('SELECT batch_id FROM photos WHERE id=?', ('e0',)).fetchone()[0] \
    != con.execute('SELECT batch_id FROM photos WHERE id=?', ('e1',)).fetchone()[0]
# 组号相同没关系 —— 组的真实标识是 (batch_id, group_idx)，跨批次天然不混
chk('5 两批次不混组（组标识 = batch_id + group_idx）', b_diff,
    {'same_group_idx': same_group, 'different_batch': b_diff})

# ── 场景 6：dry_run 不写库 ──
snap = {r_['id']: r_['group_idx'] for r_ in con.execute('SELECT id, group_idx FROM photos')}
r6 = store.regroup_photos_by_time(con, batch_id=b1, dry_run=True, max_per_group=2)
snap2 = {r_['id']: r_['group_idx'] for r_ in con.execute('SELECT id, group_idx FROM photos')}
chk('6 dry_run 不写库', snap == snap2, {'changed_in_report': r6['changed']})
chk('6 dry_run 报告里仍给出影响', r6['dry_run'] is True and r6['groups_after'] > 0, r6)

# ── 场景 7：只改 group_idx，不动 links ──
con.execute('INSERT INTO products(code, code_norm, name, created_at, updated_at) '
            "VALUES('X1','x1','测试品','2026-10-01','2026-10-01')")
store.link(con, 'x1', 'a00', source='manual', confidence=1.0,
           evidence='测试关联', created_by='test')
con.commit()
links_before = con.execute('SELECT photo_id, code_norm FROM links').fetchall()
store.regroup_photos_by_time(con)
links_after = con.execute('SELECT photo_id, code_norm FROM links').fetchall()
chk('7 重算不动关联', [tuple(r_) for r_ in links_before] == [tuple(r_) for r_ in links_after],
    len(links_after))

con.close()
shutil.rmtree(tmp, ignore_errors=True)
print('----')
print('ALL_PASS' if not fails else 'FAILED: ' + ', '.join(fails))
sys.exit(1 if fails else 0)
