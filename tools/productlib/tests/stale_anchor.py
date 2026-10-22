# -*- coding: utf-8 -*-
"""脏柜锚点自愈（2026-10-07 老板在全新环境用绿色包撞到的那一页）。

现象：绿色包解到**空 data 目录**的全新机器上打开，浏览器却报
「读取向导进度失败：Internal Server Error」，后端日志是
`store.ContainerError: 柜不存在：6012cfb02968`。

根因链（两条独立的都得堵）：
  1 **后端**：`/api/containers/{cid}/progress` 没接 `ContainerError`，
     「柜不存在」冒成 **500**。它是用户可恢复状态（换库/换机器的正常结果），
     不是服务器故障 —— 而且前端拿 404 表示「服务进程是旧的」，用 400 才不撞车。
  2 **前端**：`localStorage['plCid']` 按 origin 存、**跨库共用**。柜号是
     「这个库里的」东西，锚点指向库里没有的柜就是脏数据 —— `loadContainerOptions`
     要把它清掉并落到第一个柜，而不是甩一句报错让用户自己猜。

本测试锁死：
  A 后端：柜不存在 → **400**（不是 500，也不是 404），且带可读原因；
  B 后端：真实存在的柜 → 200，口径不变（不被这次改动带偏）；
  C 前端契约：/api/containers 里的 id 集合与 404/400 的判定依据一致
    （前端只能靠「id 不在列表里」+「消息含柜不存在」这两个信号自愈）。
"""
import os
import sys
import shutil
import tempfile
import json
import urllib.request
import urllib.error

tmp = tempfile.mkdtemp(prefix='pl_anchor_')
# ⚠️ 必须在 import store 之前设：store.DEFAULT_DB / paths 都在导入时算
os.environ['PL_HOME'] = tmp
os.environ['PL_DB'] = os.path.join(tmp, 'a.db')

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, routes  # noqa: E402
from tools.productlib.routes import progress as _progress  # noqa: E402
from fastapi import HTTPException  # noqa: E402

con = store.connect()
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


# ── A. 柜不存在 → 400（不是 500，也不是 404）──
fake = '6012cfb02968'          # 老板日志里那个旧柜号
try:
    _progress.api_container_progress(fake)
    chk('A1 柜不存在会抛错（不是静默返回空）', False, '居然正常返回了')
except HTTPException as e:
    chk('A1 柜不存在 → 400（可恢复状态，不是服务器故障）',
        e.status_code == 400, '%s %s' % (e.status_code, e.detail))
    chk('A2 报错带可读原因（前端靠它认「脏锚点」）',
        '柜不存在' in str(e.detail), e.detail)
except Exception as e:  # noqa: BLE001
    chk('A1 柜不存在 → 400', False, '抛的是 %s: %s' % (type(e).__name__, e))

# 关键：**不能**是 500（未捕获）也不能是 404（会被前端当成「服务进程旧」）
try:
    _progress.api_container_progress(fake)
    code = None
except HTTPException as e:
    code = e.status_code
chk('A3 不是 404（前端用 404 表示「服务进程是旧的」，不能撞车）',
    code != 404, code)
chk('A4 不是 500（用户看不懂 Internal Server Error 是什么意思）',
    code != 500, code)

# ── B. 真实柜 → 正常，口径不变 ──
c1 = store.create_container(con, 'REAL0001', seal_no='S1', inspector='t',
                           client_name='A', location='B')
d = _progress.api_container_progress(c1['id'])
chk('B1 真实柜取得到进度', isinstance(d, dict) and 'steps' in d,
    list(d)[:6])
chk('B2 柜号回显正确', d.get('container_no') == 'REAL0001', d.get('container_no'))
chk('B3 后端 steps 的键是「柜/清单/照片/选图/治理/报告」六项',
    sorted(d['steps']) == ['checklist', 'container', 'govern', 'photos',
                           'picks', 'report'],
    sorted(d['steps']))
# 2026-10-11 v0.8.0：picks 升级为**后端**步骤（container_picks_stats，
# 与 report_lookup 同源 —— 前端自己算必然和统计条漂移）。旧断言
# 「picks 必须不在 steps 里」已随该版设计作废，改为锁「必须在」。
chk('B3c photos 与 govern 分开返回（前端要合并成一步的完成态）',
    'photos' in d['steps'] and 'govern' in d['steps'])

# ── C. 前端自愈所依赖的契约 ──
# 前端拿 /api/containers 的 id 集合判断「锚点是不是脏的」，所以必须保证：
#   ① 每个 containers 项都带 id；② 同一个 cid 在列表与 progress 里是同一个值。
from tools.productlib.routes import containers as _containers  # noqa: E402
items = _containers.api_containers().get('items') or []
chk('C1 /api/containers 每项都带 id（前端自愈的判据）',
    all(('id' in it) and it['id'] for it in items),
    [it.get('id') for it in items])
ids = {it['id'] for it in items}
chk('C2 库里的柜都能在列表里找到（一致）', c1['id'] in ids, sorted(ids))
chk('C3 老板那个旧柜号确实不在库里（这就是他的场景）', fake not in ids)
chk('C4 「脏锚点」判定 = 锚点 id 不在列表里 —— 前端照此实现即可',
    (fake in ids) is False and (c1['id'] in ids) is True)

con.close()
shutil.rmtree(tmp, ignore_errors=True)
print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
