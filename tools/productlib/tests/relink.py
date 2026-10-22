# -*- coding: utf-8 -*-
"""补关联（relink）：先导照片、后导清单的场景。

═══ 问题根因 ═══
治理管道 govern_one() 拿 CodeIndex 匹配编码，索引建自 **products 表**。
先导照片时 products 是空的 → index.best() 全部返回 None → 零关联。
等清单导进来，照片 govern_state 已是 'done'，govern_all() 的
`WHERE govern_state='pending'` 永远不会重扫它们 → 关联永远补不上。

**识别结果本身没丢**：ocr_tokens（逐条原始文本 + 置信度）和
photos.vision_codes（多模态读出的码）都已落库。所以补关联**不需要
重跑 OCR / 多模态**（不花 API 钱、不耗时间），只要拿新清单重建索引，
把已存的 token 重新匹配一遍即可。

本测试锁死三件事：
  1. 复现 —— 先照片后清单，token 落库但零关联；
  2. relink_due_to_checklist() 能把这些 token 补成关联；
  3. 纪律不破 —— 只认 exact，人工关联不被覆盖，重复调用幂等，
     NO_LINK_KINDS（装箱单/场景）不写关联。
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, pipeline, schema  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_relink_')
db = os.path.join(tmp, 't.db')
con = store.connect(db)

# ── 造 3 张"已治理完"的照片，并手工塞入 OCR token ──────────────
# 直接写 token 而不跑真 OCR：这里要验的是**匹配与补关联**，
# 不是识别本身。govern_one 的 OCR 段落已有 pc_ocr_probe 实跑覆盖。
CODES = ['103011013388A', '103011013399B', '103011013377C']


def mk_photo(name):
    pid = 'p_' + name
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,created_at) '
        "VALUES(?,'/x/'||?,'/x/'||?,'b1','2026-10-01T10:00:00','exif',100,'m'||?,"
        "800,600,0,0,'done','label','2026-10-01T10:00:00')",
        (pid, name, name, name))
    return pid


pid_a, pid_b, pid_c = mk_photo('a.jpg'), mk_photo('b.jpg'), mk_photo('c.jpg')

# a：token 正好等于清单里的编码 → 补关联后应 exact 命中
store.add_tokens(con, pid_a, [{'t': '103011013388A', 'c': 0.95}])
# b：OCR 带连字符/空格（归一化后仍应相等）
store.add_tokens(con, pid_b, [{'t': '103-0110-13399 B', 'c': 0.93}])
# c：读出来的码根本不在清单里 → **绝不能**凭空建关联
store.add_tokens(con, pid_c, [{'t': '999999999999Z', 'c': 0.99}])

# 场景照：明知不关联，补关联也不能碰它
pid_scene = 'p_scene'
con.execute(
    'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,width,'
    "height,is_dup,group_idx,govern_state,photo_kind,created_at) "
    "VALUES(?,'/x/s.jpg','/x/s.jpg','b1','2026-10-01T10:00:00','exif',100,'ms',"
    "800,600,0,0,'done','scene','2026-10-01T10:00:00')", (pid_scene,))
store.add_tokens(con, pid_scene, [{'t': '103011013388A', 'c': 0.99}])

# ── ① 复现：products 为空 → 零关联 ────────────────────────────
n_prod = con.execute('SELECT COUNT(*) FROM products').fetchone()[0]
assert n_prod == 0, '前置条件：清单还没导，products 应为空'
empty_index = pipeline._build_index(con) if hasattr(pipeline, '_build_index') else None
if empty_index is None:
    import build_library as BL
    empty_index = BL.CodeIndex([])
hits = pipeline.replay_hits(con, empty_index, [pid_a, pid_b, pid_c]) \
    if hasattr(pipeline, 'replay_hits') else None
if hits is None:
    print('[ SKIP ] pipeline 尚无 replay_hits，本用例只验证前置状态')
else:
    assert all(len(v) == 0 for v in hits.values()), \
        'products 为空时不应有任何命中：%r' % hits
    print('[ OK ] 复现：清单未导入时零命中（与线上症状一致）')

# ── ② 后导清单 → 跑补关联 ──────────────────────────────────────
store.upsert_products(con, [
    {'code': '103011013388A', 'name': '阀门A', 'spec': 'DN50'},
    {'code': '103011013399B', 'name': '阀门B', 'spec': 'DN80'},
    {'code': '103011013377C', 'name': '阀门C', 'spec': 'DN100'},
])

r = pipeline.relink_due_to_checklist(con, progress=None) \
    if hasattr(pipeline, 'relink_due_to_checklist') else None

if r is None:
    print('[ SKIP ] pipeline 尚无 relink_due_to_checklist，核心用例未跑')
else:
    # a / b 应各拿到 1 条 auto_ocr 关联（b 靠归一化命中）
    la = con.execute("SELECT * FROM links WHERE photo_id=? AND source='auto_ocr'",
                     (pid_a,)).fetchall()
    lb = con.execute("SELECT * FROM links WHERE photo_id=? AND source='auto_ocr'",
                     (pid_b,)).fetchall()
    assert len(la) == 1, 'a 应补 1 条自动关联，实际 %d' % len(la)
    assert len(lb) == 1, 'b（带分隔符）归一化后应命中，实际 %d' % len(lb)
    assert la[0]['code_norm'] == '103011013388A', la[0]['code_norm']
    assert lb[0]['code_norm'] == '103011013399B', lb[0]['code_norm']

    # c 的码不在清单 → 不得凭空建关联
    lc = con.execute('SELECT * FROM links WHERE photo_id=?', (pid_c,)).fetchall()
    assert len(lc) == 0, '清单外的码不得建关联，实际 %r' % [x['code_norm'] for x in lc]

    # 场景照不写关联（NO_LINK 纪律）
    ls = con.execute('SELECT * FROM links WHERE photo_id=?', (pid_scene,)).fetchall()
    assert len(ls) == 0, '场景照不得关联'

    print('[ OK ] 补关联：exact 命中 a/b，清单外 c 与场景照均未建关联')

    # ── ③ 人工关联不被覆盖 + 幂等 ──────────────────────────────
    store.link(con, '103011013377C', pid_a, 'manual',
               created_by='boss', confidence=1.0)
    r2 = pipeline.relink_due_to_checklist(con)
    # 再跑一次，a 的自动关联数不应翻倍（UNIQUE 约束 + 幂等）
    n_auto = con.execute(
        "SELECT COUNT(*) FROM links WHERE photo_id=? AND source='auto_ocr'",
        (pid_a,)).fetchone()[0]
    assert n_auto == 1, '重复补关联不应重复写，实际 %d' % n_auto
    man = con.execute(
        "SELECT * FROM links WHERE photo_id=? AND source='manual'", (pid_a,)
    ).fetchone()
    assert man and man['code_norm'] == '103011013377C', '人工关联被覆盖了！'
    assert r2['written'] == 0, '第二次不应有新写入，实际 %r' % r2
    print('[ OK ] 幂等：重复调用不重复写，人工关联完好')

    # ── ④ 统计口径 ──────────────────────────────────────────────
    # scanned 应覆盖候选照片；written 必须是**净增**（DB 实际多出的行）
    assert r['scanned'] >= 4, 'scanned 应覆盖候选照片，实际 %r' % r['scanned']
    n_auto_total = con.execute(
        "SELECT COUNT(*) FROM links WHERE source LIKE 'auto_%'").fetchone()[0]
    assert r['written'] == n_auto_total, \
        'written 应为净增：返回 %d，库中 auto 关联 %d' % (r['written'], n_auto_total)
    # c 的码不在清单 → _match_token 直接返回 None，压根不算尝试。
    # 所以尝试数 == 净增 == 2（只有 a、b）。
    assert r['candidates'] == 2, '应只有 a、b 匹配出编码：%r' % r['candidates']
    assert r['written'] + r['replaced'] == 2, \
        '写入尝试应为 2（a、b 各一）：%r' % r
    print('[ OK ] relink 统计：scanned=%d candidates=%d written=%d replaced=%d'
          % (r['scanned'], r['candidates'], r['written'], r['replaced']))

    # ── ⑤ 净增口径专项：同一照片被两个清单重复命中 ──────────────
    # products 表 code_norm 是主键，所以两条清单的 1000000119 与
    # 1000000119.0 归一后**只会存一行**；要造出"覆盖"得让同一照片
    # 命中两个不同 code_norm。这里直接塞一个已存在的 auto 关联，
    # 再用 --limit 之外的路径验证 written 不虚高。
    con.execute("DELETE FROM links WHERE photo_id IN (?,?)", (pid_a, pid_b))
    con.execute("DELETE FROM links WHERE photo_id=?", (pid_scene,))
    con.commit()
    # 预置一条 a→阀门C 的自动关联（错误关联，模拟历史脏数据）
    store.link(con, '103011013377C', pid_a, 'auto_ocr', confidence=0.9,
               created_by='system')
    n_before = con.execute('SELECT COUNT(*) FROM links').fetchone()[0]
    r3 = pipeline.relink_due_to_checklist(con)
    n_after = con.execute('SELECT COUNT(*) FROM links').fetchone()[0]
    # a 现在已有 auto 关联 → 不在候选范围。
    # 候选里仍有 c 和场景照（它们只是没命中，不是被排除）。
    assert r3['scanned'] == 3, \
        '候选应为 b/c/场景照三张（a 已有 auto 关联被排除）：%r' % r3['scanned']
    assert r3['written'] == n_after - n_before, \
        'written(%d) 必须等于实际净增(%d)' % (r3['written'], n_after - n_before)
    print('[ OK ] 净增口径：scanned=%d written=%d 实际净增=%d（一致）'
          % (r3['scanned'], r3['written'], n_after - n_before))

# ═══ skip_linked：重新治理可选跳过已关联（2026-10-18 老板需求）═══
# 场景：a 有预置 auto 关联（上面塞的 103011013377C），b/c 未关联。
# govern_one 降级跑（use_ocr/use_vision 全 False，不花 API、不跑 OCR），
# 只验证 reset 范围与 clear_auto_links 范围这两处 skip_linked 口径。
from PIL import Image  # noqa: E402
for _pid in (pid_a, pid_b, pid_c):
    _p = os.path.join(tmp, _pid + '.jpg')
    Image.new('RGB', (800, 600), (120, 120, 120)).save(_p)
    con.execute('UPDATE photos SET path=?, file=? WHERE id=?',
                (_p, _pid + '.jpg', _pid))
con.commit()

r_skip = pipeline.govern_all(con, reset=True, use_ocr=False, use_vision=False,
                             skip_linked=True)
assert r_skip['total'] == 2, \
    'skip_linked：只重跑未关联的 b/c（total=%s，a 必须被跳过）' % r_skip['total']
_st_a = con.execute('SELECT govern_state FROM photos WHERE id=?',
                    (pid_a,)).fetchone()[0]
assert _st_a == 'done', 'a 已关联必须保持 done（不重置），实际 %r' % _st_a
_la = con.execute('SELECT COUNT(*) FROM links WHERE photo_id=?',
                  (pid_a,)).fetchone()[0]
assert _la == 1, 'a 的 auto 关联必须保留（跳过即不清），实际 %d' % _la
print('[ OK ] skip_linked：已关联跳过（a 保持 done + auto 关联保留），'
      '未关联重跑（total=%d）' % r_skip['total'])

r_all = pipeline.govern_all(con, reset=True, use_ocr=False, use_vision=False)
assert r_all['total'] == 4, \
    '不跳过：a/b/c 加场景照全被重置重跑（total=%s）' % r_all['total']
print('[ OK ] 不跳过（旧行为）：已关联的 a 也重置重跑（total=%d）' % r_all['total'])

con.close()
shutil.rmtree(tmp, ignore_errors=True)
print('ALL_PASS')
