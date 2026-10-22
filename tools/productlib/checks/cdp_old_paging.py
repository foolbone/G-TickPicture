# -*- coding: utf-8 -*-
"""CDP 实跑：**旧版**照片库页码分页 + 柜列表序号（2026-10-20 老板）。

跑在已在运行的服务上（默认 8765，dev 源码模式），不另起实例 ——
真实库照片多，正好够翻页。
⚠️ 只做只读查看，不点任何写操作按钮。

跑法：python tools/productlib/checks/cdp_old_paging.py
      PL_PORT=8765（默认）
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import random
import tempfile
import time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8765'))
CDP_PORT = int(os.environ.get('PL_CDP', str(random.randint(9400, 9800))))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_oldpg_edge')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/'

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def http_json(path, port=PORT, retries=20, timeout=8):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


ping = None
for _ in range(10):
    ping = http_json('/api/ping')
    if ping:
        break
if not ping:
    print('[FAIL] %s 上没有服务，先起来再跑' % BASE)
    sys.exit(1)
print('[ .. ] 服务 %s version=%s mode=%s' % (BASE, ping.get('version'),
                                            ping.get('mode')))

shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,900', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def run():
    page = None
    for _ in range(40):
        lst = http_json('/json/list', port=CDP_PORT, retries=1, timeout=3) or []
        page = next((t for t in lst if t.get('type') == 'page'
                     and '127.0.0.1' in (t.get('url') or '')), None) \
            or next((t for t in lst if t.get('type') == 'page'), None)
        if page:
            break
        time.sleep(0.5)
    if not page:
        print('[FAIL] 找不到 page')
        return

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
        # ⚠️ 必须禁用缓存：Edge 对静态 js 会启发式缓存，改了 photos.js 后
        #    仍跑老代码（表现为「页码没渲染、还是一次 60 张」）。
        await cmd('Network.enable')
        await cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1600, 'height': 900, 'deviceScaleFactor': 1,
                   'mobile': False})
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(4.0)
        # 切到照片库 tab（旧端用 localStorage 记页）
        await cmd('Runtime.evaluate',
                  {'expression': "try{localStorage.setItem('plTab','batches')}catch(e){}"})
        await cmd('Page.reload')
        await asyncio.sleep(6.0)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str((ex.get('exception') or {}).get('description')
                                     or ex.get('text'))[:300]
            return (r.get('result') or {}).get('value')

        n = await js("document.querySelectorAll('#shots .shot').length")
        chk('1 旧端照片网格已渲染', isinstance(n, int) and n > 0, n)

        more = await js("""(()=>{const b=document.querySelector('#moreBtn');
            return JSON.stringify({exists:!!b, tag:b?b.tagName:'',
              txt:b?b.innerText.replace(/\\s+/g,' ').slice(0,80):'',
              pgb:b?b.querySelectorAll('.pgb').length:0});})()""")
        md = json.loads(more) if isinstance(more, str) and more.startswith('{') else {}
        chk('2 🔴 没有「加载更多」按钮', '加载更多' not in (md.get('txt') or ''), more)
        chk('3 🔴 底部有页码按钮（.pgb）', (md.get('pgb') or 0) >= 3, more)
        chk('3b 容器不是 button（innerHTML 塞不进 button）',
            (md.get('tag') or '') != 'BUTTON', md.get('tag'))

        sc = await js("""(()=>{const d=document.documentElement;
            return JSON.stringify({sh:d.scrollHeight, ih:innerHeight});})()""")
        scd = json.loads(sc) if isinstance(sc, str) and sc.startswith('{') else {}
        chk('4 🔴 页面不纵滚（一屏装下）',
            (scd.get('sh') or 0) <= (scd.get('ih') or 0) + 6, sc)

        first1 = await js("""(()=>{const e=document.querySelector('#shots .shot');
            return e? e.dataset.id : '';})()""")
        clicked = await js("""(()=>{const b=document.querySelector('#moreBtn [data-pg="2"]');
            if(!b) return 0; b.click(); return 1;})()""")
        await asyncio.sleep(3.5)
        await drain()
        first2 = await js("""(()=>{const e=document.querySelector('#shots .shot');
            return e? e.dataset.id : '';})()""")
        chk('5 翻到第 2 页内容变了', bool(clicked) and first1 != first2,
            '%s -> %s' % (first1, first2))

        on = await js("""(()=>{const b=document.querySelector('#moreBtn .pgb.on');
            return b? b.innerText.trim() : '';})()""")
        chk('6 当前页高亮 = 2', (on or '') == '2', on)

        # 柜列表序号
        await cmd('Runtime.evaluate',
                  {'expression': "try{localStorage.setItem('plTab','containers')}catch(e){}"})
        await cmd('Page.reload')
        await asyncio.sleep(5.0)
        await drain()
        idx = await js("""(()=>{const hs=[...document.querySelectorAll('#tab-containers th')]
            .map(e=>e.innerText.trim());
            const td=document.querySelector('#cBody tr td');
            return JSON.stringify({heads:hs, first:td?td.innerText.trim():''});})()""")
        idd = json.loads(idx) if isinstance(idx, str) and idx.startswith('{') else {}
        chk('7a 旧端柜列表有「序号」列', '序号' in (idd.get('heads') or []), idx)
        chk('7b 序号首行 = 1', (idd.get('first') or '') == '1', idx)

        await drain()
        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('8 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:200] if bad else ''))


try:
    asyncio.run(run())
finally:
    try:
        edge.terminate()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(1)
    shutil.rmtree(HOME, ignore_errors=True)

print('----')
print('FAIL %d' % len(fails))
for f in fails:
    print('  - ' + f)
sys.exit(1 if fails else 0)
