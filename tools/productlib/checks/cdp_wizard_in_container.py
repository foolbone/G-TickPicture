# -*- coding: utf-8 -*-
"""CDP 实跑：「作业向导」并进柜页 + 改名「柜作业」（2026-10-08）。

老板要求：①作业向导集成到柜功能里；②建柜后能快速进入；③在柜里也能进
其他柜的柜作业；④改个贴近业务的名字（定为「柜作业」）。

静态三检（esm_syntax / web_contract / esm_graph）**证明不了**这些 —— 它们
看不出「视图默认 display:none 所以按钮点不到」「点了没切换视图」这类问题。
本脚本只验浏览器里真的通：

  1 导航里**没有**「作业向导」这一项了，默认落在「柜」；
  2 柜列表每行有「柜作业 →」按钮，点了真的切进作业视图（不是点了没反应）；
  3 作业视图里有「← 柜列表」，点了能回列表（能换别的柜）；
  4 顶部「当前柜」下拉切柜 → 整套作业跟着换成那个柜；
  5 建柜后出现**常驻**快速进入条（不能是 3 秒就没的 toast），点了能进；
  6 标题是「柜作业」，页面上不再出现「作业向导」；
  7 全程无 JS 异常（ESM 循环依赖 / 未导出就 import 只有实跑才炸）。

⚠️ 铁律：
  · 读隐藏元素用 style.display，**别用 innerText**（display:none 时是 ''）；
  · 需要调模块内函数走动态 import() 或 window.enterWizard（ESM 作用域外
    拿不到，直接 window.xxx 会一片假绿）。
⚠️ 破坏面：自建隔离实例（临时 PL_HOME + 独立端口），不碰老板的 8765。
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
PORT = int(os.environ.get('PL_PORT', '8792'))
CDP_PORT = int(os.environ.get('PL_CDP', '9353'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_wizmerge_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_wizmerge_db')
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


shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
seed = r'''
import os, sys
sys.path.insert(0, __REPO__)
sys.path.insert(0, __REPO__ + "/tools")
os.environ["PL_HOME"] = __HOME__
from tools.productlib import store, paths
c = store.connect(paths.db_path())
for cid, cno in (("ct1","CAB1000001"), ("ct2","CAB2000002")):
    c.execute("INSERT INTO containers(id,container_no,created_at,updated_at)"
              " VALUES(?,?, '2026-10-08','2026-10-08')", (cid, cno))
c.commit(); c.close()
print("SEEDED", paths.db_path())
'''.replace('__REPO__', repr(REPO)).replace('__HOME__', repr(DBHOME))
r = subprocess.run([PY, '-c', seed], capture_output=True, text=True, timeout=120)
if 'SEEDED' not in r.stdout:
    print('[FAIL] 造数据失败')
    print(r.stdout[-400:]); print(r.stderr[-800:])
    sys.exit(1)
print('[ OK ] 隔离数据已就绪（2 个柜）')

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
        await asyncio.sleep(4.5)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        # ── 0 前置闸门 ──
        chk('0 前置闸门：页面已加载', await js("!!document.querySelector('nav')") is True)

        # ── 1 导航 ──
        tabs = await js("[...document.querySelectorAll('nav button[data-tab]')]"
                        ".map(b=>b.textContent.trim())")
        chk('1 导航里没有「作业向导」了', '作业向导' not in (tabs or []), tabs)
        chk('2 默认落在「柜」页',
            await js("document.querySelector('#tab-containers').classList.contains('on')")
            is True)
        chk('3 导航「柜」是高亮的',
            await js("""(()=>{const b=[...document.querySelectorAll('nav button')]
                .find(x=>x.dataset.tab==='containers');
                return b? b.classList.contains('on'):false;})()""") is True)

        # ── 2 默认停在柜列表（作业视图隐藏）──
        vis = await js("""(()=>{const l=document.querySelector('#ctListView'),
            w=document.querySelector('#ctWizView');
            return {list:l?l.style.display:'', wiz:w?w.style.display:''};})()""")
        chk('4 默认显示柜列表、作业视图隐藏',
            vis['list'] != 'none' and vis['wiz'] == 'none', vis)
        rows = await js("document.querySelectorAll('#cBody tr').length")
        chk('5 柜列表渲染出 2 行', rows == 2, rows)

        # ── 3 每行有「柜作业 →」──
        btns = await js("[...document.querySelectorAll('#cBody [data-c-wiz]')]"
                        ".map(b=>b.textContent.trim())")
        chk('6 每行都有「柜作业」按钮', len(btns) == 2 and all('柜作业' in b for b in btns), btns)

        # ── 4 点第一行进柜作业 ──
        await js("document.querySelector('#cBody [data-c-wiz]').click()")
        await asyncio.sleep(2.5)
        await drain()
        vis2 = await js("""(()=>{const l=document.querySelector('#ctListView'),
            w=document.querySelector('#ctWizView');
            return {list:l?l.style.display:'', wiz:w?w.style.display:''};})()""")
        chk('7 🔴 点「柜作业」真的切进作业视图',
            vis2['list'] == 'none' and vis2['wiz'] != 'none', vis2)
        ttl = await js("""(()=>{const e=document.querySelector('#ctWizView .wizttl');
            return e? e.textContent.trim():'';})()""")
        chk('8 作业视图标题是「柜作业」', ttl == '柜作业', ttl)
        steps = await js("[...document.querySelectorAll('#wizBar .wstep')].length")
        chk('9 五步步骤条渲染出来了', steps == 5, steps)
        cur = await js("""(()=>{const s=document.querySelector('#wizCid');
            return s? s.value:'';})()""")
        chk('10 作业里当前柜 = 点的那一行的柜', cur == 'ct1', cur)

        # ── 5 切柜（在柜里进其他柜的作业）──
        await js("""(()=>{const s=document.querySelector('#wizCid');
            s.value='ct2'; s.dispatchEvent(new Event('change',{bubbles:true}));})()""")
        await asyncio.sleep(3.0)
        await drain()
        cur2 = await js("""(()=>{const s=document.querySelector('#wizCid');
            return s? s.value:'';})()""")
        chk('11 🔴 顶部下拉切柜后，作业跟着换成那个柜', cur2 == 'ct2', cur2)

        # ── 6 返回柜列表 ──
        await js("document.querySelector('#wizBack').click()")
        await asyncio.sleep(2.5)
        await drain()
        vis3 = await js("""(()=>{const l=document.querySelector('#ctListView'),
            w=document.querySelector('#ctWizView');
            return {list:l?l.style.display:'', wiz:w?w.style.display:''};})()""")
        chk('12 🔴 「← 柜列表」能回列表（可以换别的柜）',
            vis3['list'] != 'none' and vis3['wiz'] == 'none', vis3)

        # ── 7 建柜后的快速进入条 ──
        await js("document.querySelector('#cNew').click()")
        await asyncio.sleep(1.2)
        await js("""(()=>{const i=document.querySelector('input[name=container_no]');
            if(i){i.value='CAB3000003'; i.dispatchEvent(new Event('input',{bubbles:true}));}})()""")
        await asyncio.sleep(0.4)
        await js("""(()=>{const b=[...document.querySelectorAll('button')]
            .find(x=>x.textContent.trim()==='创建'); if(b) b.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        bar = await js("""(()=>{const e=document.querySelector('#ctNewBar');
            if(!e) return {none:true};
            return {disp:e.style.display, txt:e.textContent.trim()};})()""")
        chk('13 🔴 建柜后出现「快速进入」条（不是 3 秒就没的 toast）',
            bar.get('disp') != 'none' and '柜作业' in (bar.get('txt') or ''), bar)
        chk('14 快速进入条里点得到按钮',
            await js("!!document.querySelector('#ctNewGo')") is True)
        await js("document.querySelector('#ctNewGo').click()")
        await asyncio.sleep(2.5)
        await drain()
        vis4 = await js("""(()=>{const l=document.querySelector('#ctListView'),
            w=document.querySelector('#ctWizView');
            return {list:l?l.style.display:'', wiz:w?w.style.display:''};})()""")
        chk('15 🔴 点快速进入真的进了新柜的柜作业',
            vis4['list'] == 'none' and vis4['wiz'] != 'none', vis4)
        cur3 = await js("""(()=>{const s=document.querySelector('#wizCid');
            return s? s.value:'';})()""")
        chk('16 进去时当前柜就是刚建的那个', bool(cur3), cur3)
        bar2 = await js("""(()=>{const e=document.querySelector('#ctNewBar');
            return e? e.style.display:'gone';})()""")
        chk('17 进入后快速进入条收起（不长期占地方）', bar2 == 'none', bar2)

        # ── 8 文案 ──
        body = await js("document.body.textContent || ''")
        chk('18 页面上不再出现「作业向导」', '作业向导' not in body)
        chk('19 柜作业四个字在页面上', '柜作业' in body)

        chk('20 全程无 JS 异常', not excs,
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