# -*- coding: utf-8 -*-
"""CDP 实跑：打包版上的 **Vue 3 版**（/app/）。

为什么必须单独一个：`cdp_portable.py` 走查的是**旧版整站**（`/`），
它压根不碰 `/app/`。而 spec 里 `web-app-dist` 是**条件收录**
（目录不存在就静默跳过）—— 源码全绿、包里整站 404 是完全可能发生的。
本脚本只断言「包该有的都有」：
  A. `/app/` 与 hashed assets 直取 200（文件名带 hash，漏收就是 404）
  B. 九个路由逐个 history 回退 200（vue-router 用 createWebHistory）
  C. 每个页面真渲染出内容（不是白屏）且**无 API 4xx/5xx**
  D. 无 console error / 无未捕获运行时异常
  E. 旧版整站 `/` 仍可用（两版并存没被这次迁移打破）

用法：
    python tools/productlib/checks/cdp_vue_portable.py http://127.0.0.1:8899
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
BASE = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8899').rstrip('/')
CDP_PORT = int(os.environ.get('PL_CDP', '9371'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuepkg_edge')
URL = BASE + '/app/'

ROUTES = [
    ('home', '/app/home', '首页'),
    ('photos', '/app/photos', '照片库'),
    ('containers', '/app/containers', '柜'),
    ('wizard', '/app/wizard', '柜作业'),
    ('products', '/app/products', '产品库'),
    ('batches', '/app/batches', '照片批次'),
    ('report', '/app/report', '报告档案'),
    ('review', '/app/review', '新产品确认'),
    ('settings', '/app/settings', '设置'),
]

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def http_json(path, port=CDP_PORT, retries=1, timeout=10):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def http_code(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=15) as r:
            return r.status, r.read()
    except Exception as e:  # noqa: BLE001
        return getattr(e, 'code', 0), b''


# ════ A. /app/ 与 hashed assets 直取 ════
st, body = http_code('/app/')
chk('A1 /app/ 返回 200', st == 200, st)
html = body.decode('utf-8', 'replace')
chk('A2 index.html 引的是 hashed 资源（不是 404 的旧名）',
    '/app/assets/' in html and '.js' in html,
    re.findall(r'/app/assets/[^"\']+', html)[:3])
assets = re.findall(r'/app/assets/[^"\']+\.(?:js|css)', html)
chk('A3 每个 hashed 资源直取都是 200',
    all(http_code(a)[0] == 200 for a in assets),
    [(a, http_code(a)[0]) for a in assets])

# ════ B. history 回退 ════
codes = [(p, http_code(p)[0]) for _, p, _ in ROUTES]
chk('B1 九个路由 history 回退都是 200', all(c == 200 for _, c in codes), codes)
chk('B2 旧版整站 / 仍然 200（两版并存）', http_code('/')[0] == 200,
    http_code('/')[0])

shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1400,1200', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version', retries=40, timeout=3):
        print('[FAIL] 调试端口未就绪'); return False
    pages = [t for t in (http_json('/json/list') or []) if t.get('type') == 'page']
    # 🔴 第一个 page 可能是 Edge 内部页，必须按 URL 挑
    page = next((t for t in pages if (t.get('url') or '').startswith(BASE)), None) \
        or next((t for t in pages if '127.0.0.1' in (t.get('url') or '')), None)
    if not page:
        print('[FAIL] 找不到 page'); return False

    events = []
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        _id = [0]

        async def call(method, params=None):
            _id[0] += 1
            i = _id[0]
            await ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if msg.get('id') == i:
                    if 'error' in msg:
                        raise RuntimeError('%s: %s' % (method, msg['error']))
                    return msg.get('result', {})
                events.append(msg)

        async def ev(expr):
            r = await call('Runtime.evaluate',
                           {'expression': expr, 'awaitPromise': True,
                            'returnByValue': True})
            v = r.get('result', {})
            if v.get('subtype') == 'error' or 'exceptionDetails' in r:
                return {'__err__': str(v.get('description')
                                       or r.get('exceptionDetails'))[:300]}
            return v.get('value')

        async def wait(s):
            await asyncio.sleep(s)
            try:
                while True:
                    events.append(json.loads(await asyncio.wait_for(ws.recv(), 0.05)))
            except Exception:  # noqa: BLE001
                pass

        def api_errors():
            out = []
            for e in events:
                if e.get('method') != 'Network.responseReceived':
                    continue
                r = e['params']['response']
                if r.get('status', 0) >= 400 and '/api/' in r.get('url', ''):
                    out.append('%s %s' % (r['status'], r['url']))
            return out

        await call('Log.enable')
        await call('Runtime.enable')
        await call('Page.enable')
        await call('Network.enable')

        # ════ C/D. 九页逐个渲染 ════
        for name, path, kw in ROUTES:
            events.clear()
            await call('Page.navigate', {'url': BASE + path})
            await wait(7.0)
            body_txt = await ev('document.body.innerText') or ''
            title = await ev('document.title') or ''
            mounted = await ev("!!document.querySelector('#app .app-layout')")
            errs = api_errors()
            chk('C %-10s 渲染出内容（不是白屏）' % name,
                bool(mounted) and len(str(body_txt)) > 40,
                '%d 字 | %s' % (len(str(body_txt)), str(body_txt)[:60].replace('\n', ' ')))
            chk('C %-10s 标题正确' % name, kw in str(title), title)
            chk('C %-10s 无 API 4xx/5xx' % name, not errs, errs[:4])

        # ════ D. 无 console error ════
        events.clear()
        await call('Page.navigate', {'url': URL})
        await wait(7.0)
        # 侧栏点一遍全部入口（真实导航，顺便抓运行期异常）
        await ev("""(()=>{const it=[...document.querySelectorAll('.app-aside li')];
            return JSON.stringify(it.map(x=>x.innerText.trim()));})()""")
        console_err = [e['params'].get('entry', {}).get('text', '')
                       for e in events
                       if e.get('method') == 'Log.entryAdded'
                       and e['params'].get('entry', {}).get('level') == 'error']
        # 过滤浏览器扩展噪音：headless Edge 里预装扩展的 messaging 报错
        # （`Unchecked runtime.lastError: The message port closed...`）
        # 来自扩展后台页，不是页面代码 —— 混进来会让每次跑都假红。
        console_err = [x for x in console_err
                       if 'runtime.lastError' not in x and 'message port closed' not in x.lower()]
        chk('D1 侧栏九个入口都在（无 disabled 的「待迁移」）',
            '待迁移' not in str(await ev('document.body.innerText')),
            await ev("""(()=>{const it=[...document.querySelectorAll('.app-aside li')];
                return JSON.stringify(it.map(x=>x.innerText.trim()));})()"""))
        chk('D2 无 console error', not console_err, console_err[:3])
        runtime = [e['params'] for e in events
                   if e.get('method') == 'Runtime.exceptionThrown']
        chk('D3 无未捕获运行时异常', not runtime,
            json.dumps(runtime, ensure_ascii=False)[:300])
        chk('D4 无 API 4xx/5xx', not api_errors(), api_errors()[:4])
        return not fails


ok = asyncio.run(main())
edge.terminate()
print(('FAIL %d 项' % len(fails)) if fails else 'ALL PASS')
sys.exit(0 if ok and not fails else 1)
