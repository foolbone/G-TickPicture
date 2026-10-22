# -*- coding: utf-8 -*-
"""无效照片标记（2026-10-12 老板需求，批量操作）。

锁死四条口径：
  1 set_photos_invalid 批量置/清，留痕 invalid_at/invalid_by，撤销即清空；
  2 photo_where_sql 默认 'hide' 排除无效、'only' 只看无效、'all' 含无效
    —— 列表与五档计数共用这一份，徽章数字不会漂；
  3 无效照片不进候选/待确认队列（_cand_filter_sql 一处收口）；
  4 无效监装照不进 ④选图候选与 ③细分确认待办（supervision 两处 SQL）。
永不删文件 —— 只改标记。
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_inval_')
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
            " VALUES('c1','INV01','2026-10-12','2026-10-12')")
con.execute("INSERT INTO batches(id,name,kind,container_id,created_at)"
            " VALUES('b1','批1','photos','c1','2026-10-12')")
con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
            " VALUES('INV-A1','INV-A1','品A','2026-10-12','2026-10-12')")


def mk(pid, usage=None, suptag=None):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,vision_codes,'
        'photo_usage,supervision_tag,created_at) '
        "VALUES(?,'/x/'||?, '/x/'||?,?,'2026-10-12T10:00:00','exif',100,?,"
        '800,600,0,0,\'done\',\'label\',?,?,?,\'2026-10-12T10:00:00\')',
        (pid, pid, pid, 'b1', 'm' + pid,
         json.dumps(['INV-A1']), usage, suptag))
    return pid


p1 = mk('p_ok', usage='监装', suptag='empty_container')
p2 = mk('p_cand')            # 读码命中 INV-A1 → 待确认关联
p3 = mk('p_sup', usage='监装')   # 监装未确认细分 → 细分确认待办
p4 = mk('p_plain')

# ── 1 批量置/清 + 留痕 ──
n = store.set_photos_invalid(con, [p2, p3, p4], True, by='tester')
chk('1 批量标记 3 张', n == 3, n)
row = con.execute('SELECT * FROM photos WHERE id=?', (p2,)).fetchone()
chk('2 置 is_invalid=1 且留痕',
    row['is_invalid'] == 1 and row['invalid_at'] and row['invalid_by'] == 'tester',
    dict(row)['invalid_at'])
n = store.set_photos_invalid(con, [p4], False, by='tester')
row = con.execute('SELECT * FROM photos WHERE id=?', (p4,)).fetchone()
chk('3 撤销后标记与留痕清空',
    row['is_invalid'] == 0 and not row['invalid_at'] and not row['invalid_by'], n)
n = store.set_photos_invalid(con, [], True)
chk('4 空列表返回 0', n == 0, n)

# ── 2 photo_where_sql 三态 ──
def ids(invalid):
    join, frag, args = store.photo_where_sql(container_id='c1', invalid=invalid)
    sql = 'SELECT p.id FROM photos p' + join + frag + ' ORDER BY p.id'
    return sorted(r['id'] for r in con.execute(sql, args))

chk('5 默认 hide：只剩 2 张（有效）', ids('hide') == [p1, p4], ids('hide'))
chk('6 only：只看无效 2 张（p4 已撤销）', ids('only') == [p2, p3], ids('only'))
chk('7 all：全量 4 张', ids('all') == sorted([p1, p2, p3, p4]), ids('all'))
# 五档计数同源：photo_flag_counts 走默认 hide → 全部档不数无效
cnt = store.photo_flag_counts(con, container_id='c1')
chk('8 五档计数「全部」排除无效', cnt['all'] == 2, cnt)

# ── 3 候选/待确认排除无效 ──
cand = store.cand_photo_ids(con)
chk('9 无效照片不进「待确认关联」', p2 not in cand, sorted(cand))
flags = store.photo_flag_map(con)
chk('10 角标 map 同步排除', p2 not in flags, sorted(flags))

# ── 4 监装选图/待办排除无效 ──
sup = store.supervision_photos_of(con, 'c1')
sup_ids = [i['photo_id'] for g in sup['groups'] for i in g['items']]
chk('11 ④选图候选不含无效监装照', p3 not in sup_ids and p1 in sup_ids, sup_ids)
pend = store.supervision_pending_of(con, 'c1')
pend_ids = [i['photo_id'] for i in pend['items']]
chk('12 ③细分确认待办不含无效', p3 not in pend_ids, pend_ids)

# ── 撤销后全部回来（可逆，不是删除）──
store.set_photos_invalid(con, [p2, p3, p4], False)
cand2 = store.cand_photo_ids(con)
pend2 = store.supervision_pending_of(con, 'c1')
chk('13 撤销后候选回归', p2 in cand2, sorted(cand2))
chk('14 撤销后监装待办回归', p3 in [i['photo_id'] for i in pend2['items']],
    [i['photo_id'] for i in pend2['items']])

# 迁移检查：新库含新列 → needs_migration False（对临时库）
chk('15 needs_migration 不再要求迁移',
    store.needs_migration(os.path.join(tmp, 't.db')) is False)

print()
print('PASS %d 项' % CNT[0] if not FAILS else 'FAIL %d/%d' % (len(FAILS), CNT[0]))
sys.exit(0 if not FAILS else 1)
