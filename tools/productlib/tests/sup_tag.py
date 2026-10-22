# -*- coding: utf-8 -*-
"""监装细分：由治理的大模型给建议，人工确认（2026-10-07）。

老板要「监装图片的监装细分，在治理中由大模型分类识别，用户可以确认修改」。

🔴 这里是本项目最容易写错的地方，按「AI 建议绝不能直接生效」来实现：
报告区块④的 4 张柜况代表图是从 supervision_tag 里挑的，**一张贴错标签的图
会被直接印进交给客户的正式报告**，比留空危害大得多。所以：
  · 模型建议只落 sup_tag_ai / _conf / _reason 三列；
  · supervision_tag（报告唯一依据）只能由人工写；
  · 「还没确认」≠「没问题」：没建议和有建议待确认必须是两种显示。

本测试锁死：
  1 set_govern 写建议**不碰** supervision_tag（模型再准也不越权）；
  2 重跑治理/换模型不覆盖人工已确认的值；
  3 枚举校验：模型自造的细分值一律丢弃，且三件套一起清空
    （不许出现「标签是编的但置信度 0.9」这种骗人组合）；
  4 用途不是监装 → 不该有细分建议（预检照没有报告版位可言）；
  5 accept-ai 前后端校验一致：脏建议值报 400 而不是静默写进报告；
  6 迁移幂等：重复 _migrate 不炸（老库 + 半迁移态都要能开）；
  7 待确认计数口径：只数「有有效建议且人工未表态」，不数没建议的。
"""
import os
import sys
import json
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
# ⚠️ 顺序要紧：store.py 自己会把 tools/ 塞进 sys.path，build_library 才能被
#    import（它在 tools/build_library.py，不在仓库根）。先 import store。
from tools.productlib import store, schema, vision  # noqa: E402
import build_library as BL  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_suptag_')
DB = os.path.join(tmp, 't.db')
con = store.connect(DB)
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


con.execute("INSERT INTO batches(id,name,kind,created_at) VALUES('b1','柜A','photos','2026-10-01')")
# 3 张监装照 + 1 张预检照（预检不该有细分建议）
for i, usage in enumerate(['监装', '监装', '监装', '预检'], start=1):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,photo_usage,created_at) '
        "VALUES(?,?,?,'b1','2026-10-01T10:00:00','exif',100,?,"
        "800,600,0,0,'pending','scene',?,'2026-10-01T10:00:00')",
        ('p%d' % i, 'f%d.jpg' % i, '/tmp/f%d.jpg' % i, 'm%d' % i, usage))
con.commit()


def row(pid, col):
    return con.execute('SELECT %s FROM photos WHERE id=?' % col, (pid,)).fetchone()[col]


# ─────────────────────────────────────────────────────────────
# 1  set_govern 只写建议列，绝不碰 supervision_tag
# ─────────────────────────────────────────────────────────────
store.set_govern(con, 'p1', 'done', kind='scene', kind_conf=0.9, usage='监装',
                 sup_tag='container_seal', sup_tag_conf=0.88, sup_tag_reason='封条号特写')
chk('T1 模型建议已落 sup_tag_ai', row('p1', 'sup_tag_ai') == 'container_seal')
chk('T2 置信度与理由一并落库',
    abs(row('p1', 'sup_tag_ai_conf') - 0.88) < 1e-6 and row('p1', 'sup_tag_ai_reason') == '封条号特写')
chk('T3 🔴 建议绝不自动生效：supervision_tag 仍是空',
    row('p1', 'supervision_tag') is None, row('p1', 'supervision_tag'))
chk('T4 未表态时 sup_tag_confirmed=0',
    (row('p1', 'sup_tag_confirmed') or 0) == 0)

# ─────────────────────────────────────────────────────────────
# 2  人工确认后，重跑治理不覆盖人工的值
# ─────────────────────────────────────────────────────────────
n = store.set_supervision_tag(con, ['p1'], 'empty_container')
chk('T5 人工打标成功', n == 1 and row('p1', 'supervision_tag') == 'empty_container')
chk('T6 人工表态后 sup_tag_confirmed=1', row('p1', 'sup_tag_confirmed') == 1)
# 重跑治理，模型这次给了别的建议
store.set_govern(con, 'p1', 'done', kind='scene', kind_conf=0.8, usage='监装',
                 sup_tag='truck_head', sup_tag_conf=0.7, sup_tag_reason='车头')
chk('T7 🔴 重跑治理不覆盖人工标签（仍 empty_container）',
    row('p1', 'supervision_tag') == 'empty_container', row('p1', 'supervision_tag'))
chk('T8 重跑治理会更新建议列（供人看到模型改主意了）',
    row('p1', 'sup_tag_ai') == 'truck_head')
chk('T9 人工已确认标记不丢', row('p1', 'sup_tag_confirmed') == 1)

# ─────────────────────────────────────────────────────────────
# 3  accept-ai：采用建议 = 人工表态
# ─────────────────────────────────────────────────────────────
store.set_govern(con, 'p2', 'done', kind='scene', kind_conf=0.9, usage='监装',
                 sup_tag='container_lock', sup_tag_conf=0.83, sup_tag_reason='锁具特写')
got = store.accept_sup_tag_suggestion(con, 'p2')
chk('T10 采用建议成功', got == 1)
chk('T11 采用后 supervision_tag = 建议值',
    row('p2', 'supervision_tag') == 'container_lock')
chk('T12 采用即视为人工表态', row('p2', 'sup_tag_confirmed') == 1)

# 没有建议的照：accept 必须报「没有可用的建议」，不能静默 ok=0
store.set_govern(con, 'p3', 'done', kind='scene', kind_conf=0.7, usage='监装',
                 sup_tag=None, sup_tag_conf=0.0, sup_tag_reason='')
raised = ''
try:
    store.accept_sup_tag_suggestion(con, 'p3')
except ValueError as e:
    raised = str(e)
chk('T13 没建议时采用报明确错误（不是静默成功）', '建议' in raised, raised)
chk('T14 没建议时 supervision_tag 仍为空', row('p3', 'supervision_tag') is None)

# 🔴 脏建议值（枚举外）不许流进报告
con.execute("UPDATE photos SET sup_tag_ai='自己编的类' WHERE id='p3'")
raised = ''
try:
    store.accept_sup_tag_suggestion(con, 'p3')
except ValueError as e:
    raised = str(e)
chk('T15 🔴 枚举外的建议值被拒（不写进报告列）', '建议' in raised, raised)
chk('T16 被拒后 supervision_tag 仍为空（没被脏值污染）',
    row('p3', 'supervision_tag') is None)
con.execute("UPDATE photos SET sup_tag_ai=NULL WHERE id='p3'")

# ─────────────────────────────────────────────────────────────
# 4  vision.classify 的枚举校验（三件套同生共死）
# ─────────────────────────────────────────────────────────────
_real_call = vision._call


def with_json(payload):
    """假 _call：返回模型那段 JSON。

    ⚠️ payload 是**已序列化好的字符串**——这里必须原样返回，
    再 json.dumps 一次就变成「引号包着的 JSON」，_parse_json 解不出 dict，
    classify 会静默返回 None（看着像功能没生效，其���是自己把数据搞坏了）。
    """
    def f(prompt, image_path, max_tokens=400, timeout=60):
        return payload
    return f


# 4a 正常监装照
_REAL_JSON = json.dumps({'kind': 'scene', 'confidence': 0.9, 'reason': '空柜',
                         'usage': '监装', 'sup_tag': 'empty_container',
                         'sup_tag_confidence': 0.91, 'sup_tag_reason': '柜内无货'},
                        ensure_ascii=False)
vision._call = with_json(_REAL_JSON)
r = vision.classify('/nonexistent.jpg')
chk('T17 监装照正常返回细分建议',
    r and r[4] == 'empty_container' and abs(r[5] - 0.91) < 1e-6 and r[6] == '柜内无货', r)

# 4b 预检照：用途不是监装 → 细分必须为 None
_REAL_JSON = json.dumps({'kind': 'product', 'confidence': 0.9, 'reason': '产品',
                         'usage': '预检', 'sup_tag': 'empty_container',
                         'sup_tag_confidence': 0.95, 'sup_tag_reason': '编的'})
vision._call = with_json(_REAL_JSON)
r = vision.classify('/nonexistent.jpg')
chk('T18 🔴 预检照不给细分建议（预检没有报告版位）',
    r and r[4] is None and r[5] == 0.0 and r[6] == '', r)

# 4c 模型自造细分值 → 丢弃，且置信度一起清零（不许「编的值 + 高置信」）
_REAL_JSON = json.dumps({'kind': 'scene', 'confidence': 0.9, 'reason': 'x',
                         'usage': '监装', 'sup_tag': 'seal_photo',
                         'sup_tag_confidence': 0.9, 'sup_tag_reason': '编的'})
vision._call = with_json(_REAL_JSON)
r = vision.classify('/nonexistent.jpg')
chk('T19 🔴 自造细分值被丢弃', r and r[4] is None, r)
chk('T20 🔴 丢弃时置信度归零（不留下骗人的高分）', r and r[5] == 0.0, r)
chk('T21 丢弃时理由也清空（不留半截数据）', r and r[6] == '', r)

# 4d 用途「不确定」→ 同样不给细分
_REAL_JSON = json.dumps({'kind': 'scene', 'confidence': 0.4, 'reason': 'x',
                         'usage': '不确定', 'sup_tag': 'container_side',
                         'sup_tag_confidence': 0.8})
vision._call = with_json(_REAL_JSON)
r = vision.classify('/nonexistent.jpg')
chk('T22 用途不确定时不给细分建议', r and r[4] is None and r[3] is None, r)

# 4e 细分给了但没置信度 → 照收，但置信度 0（不能凭空信任）
_REAL_JSON = json.dumps({'kind': 'scene', 'confidence': 0.9, 'reason': 'x',
                         'usage': '监装', 'sup_tag': 'other'})
vision._call = with_json(_REAL_JSON)
r = vision.classify('/nonexistent.jpg')
chk('T23 没给置信度时置 0（不凭空信任）',
    r and r[4] == 'other' and r[5] == 0.0, r)

# 4f 未配置模型 → 整体 None（下游降级），不能返回半截元组
vision._call = lambda *a, **k: (_ for _ in ()).throw(vision.VisionUnavailable('x'))
r = vision.classify('/nonexistent.jpg')
chk('T24 未配置模型时整体返回 None', r is None, r)
vision._call = _real_call

# ─────────────────────────────────────────────────────────────
# 5  建议读取接口的清洗口径
# ─────────────────────────────────────────────────────────────
con.execute("UPDATE photos SET sup_tag_ai='不存在的类', sup_tag_ai_conf=0.8,"
            " sup_tag_confirmed=0 WHERE id='p3'")
s = store.sup_tag_suggestions(con, ['p1', 'p2', 'p3', '不存在'])
chk('T25 sup_tag_suggestions 返回清洗后的建议（脏值→null）',
    s['p3']['tag'] is None and s['p1']['tag'] == 'truck_head', s)
chk('T26 脏值仍带出置信度/理由（前端可显示「有建议但无效」）',
    s['p3']['conf'] == 0.8 and s['p3']['reason'] == '', s)
chk('T27 confirmed 标记如实返回',
    s['p1']['confirmed'] == 1 and s['p2']['confirmed'] == 1)
chk('T28 查不存在的照片不炸（只返回已知的）',
    '不存在' not in s and set(s.keys()) == {'p1', 'p2', 'p3'}, sorted(s))
chk('T29 空入参返回空字典', store.sup_tag_suggestions(con, []) == {})

# ─────────────────────────────────────────────────────────────
# 6  待确认计数口径
# ─────────────────────────────────────────────────────────────
# p1 已确认 + p2 已确认 + p3 脏建议（无效）→ 有效待确认应为 0
con.execute("UPDATE photos SET sup_tag_ai='container_side', sup_tag_ai_conf=0.6,"
            " sup_tag_confirmed=0 WHERE id='p3'")
n = store.sup_tag_pending_count(con)
chk('T30 待确认计数=1（只有 p3）', n == 1, n)
con.execute("UPDATE photos SET sup_tag_confirmed=1 WHERE id='p3'")
chk('T31 人工确认后待确认归零', store.sup_tag_pending_count(con) == 0)
# 预检照即使有建议也不该进待确认（它没有报告版位）
con.execute("UPDATE photos SET sup_tag_ai='container_side', sup_tag_confirmed=0,"
            " sup_tag_ai_conf=0.7 WHERE id='p4'")
chk('T32 🔴 预检照不进待确认计数', store.sup_tag_pending_count(con) == 0,
    store.sup_tag_pending_count(con))
con.execute("UPDATE photos SET sup_tag_ai=NULL WHERE id='p4'")
# 重复件不进计数
con.execute("UPDATE photos SET sup_tag_ai='container_side', sup_tag_confirmed=0,"
            " is_dup=1 WHERE id='p4'")
chk('T33 重复件不进待确认计数', store.sup_tag_pending_count(con) == 0)
con.execute("UPDATE photos SET is_dup=0 WHERE id='p4'")
# 批次维度过滤生效
con.execute("UPDATE photos SET sup_tag_ai='container_side', sup_tag_confirmed=0,"
            " sup_tag_ai_conf=0.7, is_dup=0 WHERE id='p4'")
# T31 把 p3 确认掉了，这里把它重新置为「待确认」：
# 现在 p3(监装,待确认) 应被数到，p4(预检,待确认) 不该被数到。
con.execute("UPDATE photos SET sup_tag_confirmed=0 WHERE id='p3'")
chk('T34 批次过滤口径一致（预检照在全库与批次下都不计，只数监装 p3）',
    store.sup_tag_pending_count(con) == 1
    and store.sup_tag_pending_count(con, batch_id='b1') == 1,
    (store.sup_tag_pending_count(con), store.sup_tag_pending_count(con, batch_id='b1')))
# 批次不匹配时为 0（别把别的批次的张数算进来）
chk('T35 不存在的批次返回 0', store.sup_tag_pending_count(con, batch_id='zzz') == 0)

# ─────────────────────────────────────────────────────────────
# 7  迁移幂等（老库 / 半迁移态都必须能开）
# ─────────────────────────────────────────────────────────────
con.close()
store._migrate(store.connect(DB))
store._migrate(store.connect(DB))
c3 = store.connect(DB)
cols = {r['name'] for r in c3.execute('PRAGMA table_info(photos)')}
chk('T36 重复迁移不炸且四列都在',
    {'sup_tag_ai', 'sup_tag_ai_conf', 'sup_tag_ai_reason',
     'sup_tag_confirmed'} <= cols)
chk('T37 迁移后人工确认的数据还在',
    c3.execute("SELECT supervision_tag FROM photos WHERE id='p1'").fetchone()[0]
    == 'empty_container')
idx = {r['name'] for r in c3.execute("SELECT name FROM sqlite_master WHERE type='index'")}
chk('T38 建议列索引已建', 'idx_photos_supai' in idx, sorted(idx))
c3.close()

# 半迁移态：只补了一半列（模拟 ALTER 落盘但版本号没写的经典砖化现场）。
# ⚠️ 两个坑都踩过一遍：
#  ① 不能手搓只有两列的 photos 表 —— connect 会 executescript 整份 SCHEMA，
#     里面到处引用 photos 其它列，那样炸的是建表不是迁移。得从**真库**出发：
#     先正常建库，再把新列 DROP 掉。
#  ② connect 用 _schema_initialized **按库路径**去重，同进程内第二次连同一个
#     路径会跳过 _migrate。所以要验证「重开能自愈」必须先把该路径的初始化
#     标记清掉（等价于重启进程），否则测的是那把去重锁而不是迁移。
half = os.path.join(tmp, 'half.db')
hc = store.connect(half)
for col in ('sup_tag_ai_conf', 'sup_tag_ai_reason', 'sup_tag_confirmed'):
    hc.execute('ALTER TABLE photos DROP COLUMN %s' % col)
hc.commit()
hcols_before = {r['name'] for r in hc.execute('PRAGMA table_info(photos)')}
hc.close()
chk('T39 前置：半迁移现场已造好（只剩 sup_tag_ai）',
    'sup_tag_ai' in hcols_before and 'sup_tag_confirmed' not in hcols_before,
    sorted(hcols_before))
store._schema_initialized.discard(os.path.abspath(half))   # 等价于重启进程
h = store.connect(half)
hcols = {r['name'] for r in h.execute('PRAGMA table_info(photos)')}
chk('T40 🔴 半迁移库重开能自愈补齐缺的列',
    {'sup_tag_ai', 'sup_tag_ai_conf', 'sup_tag_ai_reason',
     'sup_tag_confirmed'} <= hcols, sorted(hcols))
h.close()
# 再重开一次也不能炸（幂等：上一轮已经把列补齐了）
store._schema_initialized.discard(os.path.abspath(half))
h = store.connect(half)
chk('T41 补齐后再重开不炸（迁移幂等）',
    'sup_tag_confirmed' in {r['name'] for r in h.execute('PRAGMA table_info(photos)')})
h.close()

# ─────────────────────────────────────────────────────────────
# 8  🔴 路由顺序：字面量路径必须早于 /api/photos/{pid}
# ─────────────────────────────────────────────────────────────
# 这个坑真的踩过：三个 supervision 端点写对了、checks/routes.py 也全绿，
# 但 GET /api/photos/supervision-tags 返回的是**照片详情**的形状 ——
# 因为 '/api/photos/{pid}' 注册在前，把 'supervision-tags' 当 pid 吞了。
# checks/routes.py 只校验「端点有没有被登记」，抓不到顺序错位，所以写死在这。
from tools.productlib.server import app  # noqa: E402
_paths = [r.path for r in app.routes if getattr(r, 'methods', None)]
_lits = ['/api/photos/supervision-tag', '/api/photos/supervision-tag/accept-ai',
         '/api/photos/supervision-tags']
for _p in _lits:
    chk('T42 端点存在：%s' % _p, _p in _paths)
    chk('T43 🔴 %s 排在 /api/photos/{pid} 之前' % _p,
        _paths.index(_p) < _paths.index('/api/photos/{pid}'),
        '%d vs %d' % (_paths.index(_p), _paths.index('/api/photos/{pid}')))

shutil.rmtree(tmp, ignore_errors=True)
print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')