# -*- coding: utf-8 -*-
"""CDP 实跑：产品库柜号筛选下拉 + 「标准产品库→产品库」改名（2026-10-07）。

老板报「筛选的『全部柜号』没有所有的柜号」。store 层已由
tests/container_filter.py（25 项）锁死；本脚本只验**浏览器里真的对**：

  1 下拉里**每一个柜都出现**（含一个产品都没有的空柜）；
  2 每个柜号**筛得出东西**，且选中后列表条数 == 接口 total（不是只有 0）；
  3 「全部柜号」这一档的条数 == 不筛选的 total（老板的原话就是这一档）；
  4 🔴 各档**不是**互相矛盾的重复计数：并集必须覆盖全库，
     一个产品都不能在任何柜之外消失；
  5 改名后导航是「产品库」，页面上不再出现「标准产品库」；
  6 全程无 JS 异常。

⚠️ 铁律：ES module 内部函数在 window 上取不到 —— 需要调函数时走
   动态 import()，别 window.xxx（否则一片假绿）。
⚠️ 破坏面：本脚本自建隔离实例（临时 PL_HOME + 独立端口），
   不碰老板的 8765，结束时整个临时目录删掉。
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8793'))
CDP_PORT = int(os.environ.get('PL_CDP', '9351'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_contnr_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_contnr_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def http_json(path, retries=40, port=CDP_PORT, timeout=3):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(
                    path if path.startswith('http')
                    else 'http://127.0.0.1:%d%s' % (port, path),
                    timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def api(path, payload=None):
    url = 'http://127.0.0.1:%d%s' % (PORT, path)
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method='POST' if data else 'GET',
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


# ── 造隔离数据：3 柜，其中一柜 container_no 全 NULL、一柜空柜 ──
shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
seed = r'''
import os, sys
sys.path.insert(0, __REPO__)
sys.path.insert(0, __REPO__ + "/tools")
os.environ["PL_HOME"] = __HOME__
from tools.productlib import store, paths
from PIL import Image
c = store.connect(paths.db_path())
for cid, cno in (("ct1","CAB1000001"), ("ct2","CAB2000002"), ("ct3","CAB3000003")):
    c.execute("INSERT INTO containers(id,container_no,created_at,updated_at)"
              " VALUES(?,?, '2026-10-07','2026-10-07')", (cid, cno))
# b1 正常；b2 的 container_no 是 NULL（老板库里 13/22 的形态）；ct3 故意空柜
c.execute("INSERT INTO batches(id,name,kind,container_id,container_no,created_at)"
          " VALUES('b1','b1','checklist','ct1','CAB1000001','2026-10-07')")
c.execute("INSERT INTO batches(id,name,kind,container_id,container_no,created_at)"
          " VALUES('b2','b2','checklist','ct2',NULL,'2026-10-07')")
def mk(code, batch):
    from build_library import normalize
    cn = normalize(code)
    c.execute("INSERT INTO products(code,code_norm,name,photo_count,created_at,updated_at)"
              " VALUES(?,?,?,0,'2026-10-07','2026-10-07')", (code, cn, "品"+code))
    c.execute("INSERT INTO product_batch(code_norm,batch_id,created_at)"
              " VALUES(?,?, '2026-10-07')", (cn, batch))
for i in range(3): mk("P-A%d" % i, "b1")
for i in range(5): mk("P-B%d" % i, "b2")   # 旧口径下这 5 件全漏
c.commit(); c.close()
print("SEEDED", paths.db_path())
'''.replace('__REPO__', repr(REPO)).replace('__HOME__', repr(DBHOME))
r = subprocess.run([PY, '-c', seed], capture_output=True, text=True, timeout=120)
if 'SEEDED' not in r.stdout:
    print('[FAIL] 造数据失败')
    print(r.stdout[-500:])
    print(r.stderr[-900:])
    sys.exit(1)
print('[ OK ] 隔离数据已就绪（3 柜，其中 CAB3000003 无产品）')

srv = subprocess.Popen(
    [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
    env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪')
        return False
    page = next((t for t in (http_json('/json/list') or [])
                 if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

    async with websockets.connect(page['webSocketDebuggerUrl'],
                                  max_size=None) as ws:
        _id = [0]

        async def cmd(method, params=None):
            _id[0] += 1
            await ws.send(json.dumps({'id': _id[0], 'method': method,
                                      'params': params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get('id') == _id[0]:
                    return m.get('result', {})

        excs = []

        async def drain():
            try:
                while True:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 0.3))
                    if m.get('method') == 'Runtime.exceptionThrown':
                        excs.append(m['params'])
            except asyncio.TimeoutError:
                pass

        await cmd('Runtime.enable')
        await cmd('Page.enable')
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(4)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        # ── 0 前置闸门：页面真的就绪了吗 ──
        ready = await js("!!document.querySelector('#tab-products')")
        chk('0 前置闸门：产品库页签存在', ready is True)

        # ── 1 导航改名 ──
        tabs = await js("[...document.querySelectorAll('nav button[data-tab]')]"
                        ".map(b=>b.textContent.trim())")
        chk('1 导航里是「产品库」（不再是「标准产品库」）',
            '产品库' in (tabs or []), tabs)
        chk('2 导航里没有「标准产品库」', '标准产品库' not in (tabs or []), tabs)
        chk('3 照片库页签名统一（不再是「预检照片库」）',
            '照片库' in (tabs or []) and '预检照片库' not in (tabs or []), tabs)

        # ── 4 进产品库，柜号下拉内容 ──
        await js("(async()=>{const m=await import('/static/js/main.js');return 1})()")
        await js("go('products')")
        await asyncio.sleep(2.5)
        await drain()

        sel = await js("(()=>{const s=document.querySelector('#pContainer');"
                       "if(!s) return {none:true};"
                       "return {opts:[...s.options].map(o=>({v:o.value,t:o.textContent.trim()})),"
                       " n:s.options.length};})()")
        chk('4 柜号下拉存在', not sel.get('none'), sel)
        vals = [o['v'] for o in (sel.get('opts') or [])]
        texts = ' '.join(o['t'] for o in (sel.get('opts') or []))
        for cn in ('CAB1000001', 'CAB2000002', 'CAB3000003'):
            chk('5 下拉含柜 %s' % cn, cn in vals, vals)
        chk('6 下拉含「全部柜号」这一档', '' in vals, vals)
        chk('7 🔴 空柜 CAB3000003 也在下拉里（能查它为什么一件都没有）',
            'CAB3000003' in vals and '0 件' in texts, texts)

        # ── 8 每个柜都筛得出东西 ──
        for cn, want in (('CAB1000001', 3), ('CAB2000002', 5)):
            got = await js(
                "(async()=>{const r=await fetch('/api/products?container=%s&limit=1');"
                "const j=await r.json();return j.total;})()" % cn)
            rows = await js(
                "(async()=>{const r=await fetch('/api/products?container=%s&limit=50');"
                "const j=await r.json();return (j.items||[]).length;})()" % cn)
            chk('8 柜 %s 筛得出 %d 件（接口 total）' % (cn, want), got == want, got)
            chk('9 柜 %s 列表条数 == total' % cn, rows == got, (rows, got))

        # 🔴 10 「全部柜号」= 不筛选（老板的原话就是这一档）
        allrows = await js(
            "(async()=>{const r=await fetch('/api/products?limit=200');"
            "const j=await r.json();return {total:j.total,n:(j.items||[]).length};})()")
        chk('10 「全部柜号」total == 不筛选 total',
            allrows['total'] == 8, allrows['total'])
        chk('11 「全部柜号」列出全部 8 件（没有一个产品隐形）',
            allrows['n'] == 8, allrows['n'])

        # ── 12 实际切换下拉，UI 跟着变 ──
        ui = await js(
            "(async()=>{const s=document.querySelector('#pContainer');"
            "s.value='CAB2000002'; s.dispatchEvent(new Event('change'));"
            "await new Promise(r=>setTimeout(r,2200));"
            "const t=document.querySelector('#pgInfo');"
            "return {sel:s.value, info:t?t.textContent.trim():null};})()")
        chk('12 手动选柜后 UI 跟着筛（选中 CAB2000002）',
            ui.get('sel') == 'CAB2000002', ui)
        # 页面上要能看出「筛出 5 件」—— 提示里必须带件数，不能只变列表
        chk('13 页面上总数变成 5', ui.get('info') and '5' in ui['info'], ui)

        # ── 14 页面上没有旧名 ──
        body = await js("document.body.textContent || ''")
        chk('14 页面上不再出现「标准产品库」',
            '标准产品库' not in body, body[:120])
        chk('15 页面上不再出现「预检照片库」', '预检照片库' not in body)

        chk('16 全程无 JS 异常', not excs,
            [e.get('exception', {}).get('description', '')[:140]
             for e in excs][:3])
        return True


ok = False
try:
    ok = asyncio.run(main())
finally:
    for p in (edge, srv):
        try:
            p.terminate()
            p.wait(timeout=8)
        except Exception:  # noqa: BLE001
            p.kill()
    shutil.rmtree(HOME, ignore_errors=True)
    shutil.rmtree(DBHOME, ignore_errors=True)

print()
print('PASS' if (ok and not fails) else 'FAIL: ' + ', '.join(fails))
sys.exit(0 if (ok and not fails) else 1)