# -*- coding: utf-8 -*-
"""打包版冒烟走查（cdp_portable.py）—— 在**绿色包**上跑，不是源码目录。

为什么需要单独一个：`cdp_regress.py` 跑的是源码服务（8765），它假设库里有真实
数据（已关联/未关联各有上千张）。绿色包通常解在**空目录**里、数据是空的，
那套断言会假红。而打包真正的风险恰好在这里 ——
**spec 漏收一个模块/一个动态路由，源码版全绿，包里整页 404**。

所以这个脚本只断言「包该有的都有」：
  A. 静态资源 —— 每个 js 模块 + css 都 200（新增文件最容易漏）
  B. 无 console error / 无未捕获运行时异常
  C. 七个页签逐个切换，每页渲染出内容且**无 API 4xx/5xx**（抓漏包的动态路由）
  D. 作业向导选柜后五步逐个点开，每步详情有内容、不出现「读取失败」
  E. 本轮新增的入口在包里（照片页「关联」视图按钮、切过去渲染两段）

用法：
    python tools/productlib/checks/cdp_portable.py http://127.0.0.1:8899/
"""
import asyncio
import base64
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
URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765/').rstrip('/') + '/'
PORT = int(os.environ.get('PL_CDP_PORT', '9345'))
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_portable')
SHOT = os.path.join(tempfile.gettempdir(), 'pl_portable')

# 真源 = web/static/js/main.js 实际 import 的那批（与 web_contract.py 的模块闭包同源）
MODULES = ['core', 'main', 'modal', 'dirpicker', 'wizard', 'home', 'containers',
           'batches', 'photos', 'products', 'drawer', 'standard', 'discover',
           'report', 'settings']
TABS = ['home', 'containers', 'products', 'batches', 'report', 'set']

fails = []
warns = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


def warn(name, info=''):
    print(('[WARN] ' + name) + ((' | ' + str(info)) if info else ''))
    warns.append(name)


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen([EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
                         '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
                         '--window-size=1440,1100', URL],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def http_json(path, retries=40):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (PORT, path), timeout=3) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None


async def main():
    print('目标: %s' % URL)
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪')
        return False
    # 🔴 /json/list 第一个 page 可能是 Edge 内部页（sync-confirmation-dialog 等）
    #    —— 必须按 URL 挑目标页，取第一个 type=page 会连到错误页面全盘假红。
    pages = [t for t in (http_json('/json/list') or []) if t.get('type') == 'page']
    page = next((t for t in pages if (t.get('url') or '').startswith(URL)), None) \
        or next((t for t in pages if '127.0.0.1' in (t.get('url') or '')), None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

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

        await call('Log.enable')
        await call('Runtime.enable')
        await call('Page.enable')
        await call('Network.enable')

        async def ev(expr):
            r = await call('Runtime.evaluate',
                           {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
            v = r.get('result', {})
            if v.get('subtype') == 'error' or 'exceptionDetails' in r:
                return {'__err__': str(v.get('description') or r.get('exceptionDetails'))[:300]}
            return v.get('value')

        async def wait(s):
            await asyncio.sleep(s)
            try:
                while True:
                    events.append(json.loads(await asyncio.wait_for(ws.recv(), 0.05)))
            except Exception:
                pass

        def api_errors():
            return [e['params']['response']['url'] for e in events
                    if e.get('method') == 'Network.responseReceived'
                    and e['params']['response']['status'] >= 400
                    and '/api/' in e['params']['response']['url']]

        await call('Emulation.setDeviceMetricsOverride',
                   {'width': 1440, 'height': 1100, 'deviceScaleFactor': 1, 'mobile': False})
        await wait(4.0)

        # ── A. 静态资源 ──
        print('== A. 静态资源（抓漏包） ==')
        res = await ev("""performance.getEntriesByType('resource')
            .filter(r=>r.name.endsWith('.js')||r.name.endsWith('.css'))
            .map(r=>[r.name.split('/').pop(), Math.round(r.transferSize||r.decodedBodySize||0)])""")
        got = dict(res) if isinstance(res, list) else {}
        for m in MODULES:
            chk('模块 %s.js 已加载' % m, (m + '.js') in got, got.get(m + '.js'))
        chk('app.css 已加载', 'app.css' in got, got.get('app.css'))
        # 逐个直取：performance 列表只记成功项，404 反而看不见
        bad = []
        for m in MODULES:
            code = await ev("""(async()=>{const r=await fetch('/static/js/%s.js');
                return r.status;})()""" % m)
            if code != 200:
                bad.append('%s.js=%s' % (m, code))
        chk('每个 js 直取都是 200', not bad, bad)
        code = await ev("(async()=>{const r=await fetch('/static/app.css');return r.status;})()")
        chk('app.css 直取 200', code == 200, code)

        # ── B. 报错 ──
        print('== B. 运行时报错 ==')
        errs = [e for e in events if e.get('method') == 'Log.entryAdded'
                and e['params'].get('entry', {}).get('level') == 'error']
        chk('无 console error', not errs,
            [e['params']['entry'].get('text', '')[:90] for e in errs][:5])
        exc = [e for e in events if e.get('method') == 'Runtime.exceptionThrown']
        chk('无未捕获运行时异常（漏包最典型的表现）', not exc,
            [str(e['params'].get('exceptionDetails', {})
                 .get('exception', {}).get('description', ''))[:110] for e in exc][:5])
        chk('页面无未捕获异常', (await ev("(window.__jserr||[]).length")) == 0)
        chk('核心 API 已挂载 window',
            await ev("typeof go === 'function' && typeof window.PL === 'object'") is True)
        chk('起步阶段无 API 报错', not api_errors(), api_errors()[:5])

        # ── C. 逐页切换 ──
        print('== C. 七个页签逐个点开 ==')
        for t in TABS:
            await ev("go('%s')" % t)
            await wait(1.6)
            vis = await ev("""(()=>{const s=document.querySelector('#tab-%s');
                return s? (s.classList.contains('on') && s.innerText.trim().length>20) : false;})()""" % t)
            chk('页签 %s 渲染出内容' % t, vis is True)
            ae = api_errors()
            chk('  ├ %s 无 API 报错' % t, not ae, ae[:4])

        # ── D. 柜作业五步 ──
        # 柜作业 2026-10-08 起并进柜页：go('wizard') 已不存在，
        # 必须 go('containers') → 选柜 → enterWizard() 才会显示作业视图
        # （视图 display:none 时 innerText 是空字符串，不进就是一片假绿）。
        print('== D. 柜作业五步（动态路由 progress 在这里露馅） ==')
        await ev("go('containers')")
        await wait(1.5)
        cid = await ev("""(()=>{const s=document.querySelector('#globalCid');
            if(!s||s.options.length<2) return '';
            s.selectedIndex=1; s.dispatchEvent(new Event('change',{bubbles:true}));
            return s.value;})()""")
        if not cid:
            warn('包里没有柜，跳过柜作业五步（空库时属正常，不是漏包）')
        else:
            await ev("enterWizard('')")
            await wait(3.0)
            steps = await ev("""[...document.querySelectorAll('#wizBar .wstep')]
                .map(s=>s.dataset.step)""")
            chk('步骤条五步都在', isinstance(steps, list) and len(steps) == 5, steps)
            for st in (steps or []):
                await ev("""(()=>{const s=document.querySelector(
                    '#wizBar .wstep[data-step="%s"]'); if(s) s.click();})()""" % st)
                await wait(2.2)
                body = await ev("""(()=>{const b=document.querySelector('#wizBody')||document.querySelector('#wBody');
                    return b? b.innerText.trim():'';})()""")
                okstep = isinstance(body, str) and len(body) > 10 \
                    and '读取失败' not in body and 'Not Found' not in body
                chk('  ├ 步骤「%s」详情有内容且无读取失败' % st, okstep,
                    (body or '')[:80])

        # ── E. 新增功能入口 ──
        print('== E. 新增功能入口在包里 ==')
        await ev("go('batches')")
        await wait(1.8)
        nav = await ev("""(()=>{const b=[...document.querySelectorAll('nav button')]
            .find(x=>x.dataset.tab==='batches'); return b?b.textContent.trim():'';})()""")
        chk('包内导航已是「照片库」', nav == '照片库', nav)
        intro = await ev("""(()=>{const e=document.querySelector('#fIntro');
            return e? getComputedStyle(e).display : null;})()""")
        # ⚠️ 2026-10-22：#fIntro / #fIntroToggle 说明块已从 index.html **移除**
        #    （只剩 photos.js 里带 if 守卫的死代码）。元素不存在也算「默认收起」，
        #    原来只认 display=='none' → 恒 FAIL（存量假红）。
        chk('包内说明块已移除或默认收起', intro in (None, 'none'), intro)
        has_link = await ev("!!document.querySelector('#shotView [data-v=link]')")
        chk('照片页有「关联」视图按钮', has_link is True, has_link)
        if has_link:
            await ev("PL.setShotView('link')")
            await wait(6.0)
            secs = await ev("""(()=>[...document.querySelectorAll('#shotTabs [data-ptab]')]
                .map(b=>b.dataset.ptab))()""")
            chk('「关联」视图渲染五档选项卡（空库徽章为 0，不是缺一段）',
                secs == ['', 'linked', 'unlinked', 'ignored', 'invalid'], secs)
            nums = await ev("""(()=>[...document.querySelectorAll('#shotTabs [data-ptab] .n')]
                .map(n=>n.textContent.trim()))()""")
            chk('五档徽章都有数字（空库全 0）',
                isinstance(nums, list) and len(nums) == 5
                and all(n.isdigit() for n in nums), nums)
            await ev("PL.setShotView('full')")
            await wait(1.2)
        # 向导③的选项卡只在**向导真的渲染了**时才在 DOM 里。
        # 空库（没有任何柜）时向导条可能渲染但③照片区不出 —— 那是设计，不是漏包。
        # 先问后端有没有柜：没有柜就跳过（与 D 段同款兜底，空库假红 2026-10-17）。
        has_container = await ev("""(async()=>{try{const r=await fetch('/api/containers');
            const j=await r.json(); return ((j.items||j||[]).length>0);}catch(e){return false;}})()""")
        wiz_live = await ev("!!document.querySelector('#wizBar .wstep')")
        if wiz_live and has_container:
            await ev("""(()=>{const s=document.querySelector(
                '#wizBar .wstep[data-step=photos]'); if(s) s.click();})()""")
            await wait(3.0)
            chk('向导③本柜照片有五档选项卡',
                await ev("""(()=>[...document.querySelectorAll('#wShTabs [data-ptab]')]
                    .map(b=>b.dataset.ptab))()""")
                == ['', 'linked', 'unlinked', 'ignored', 'invalid'])
        else:
            warn('空库：向导不渲染或没有柜，跳过向导③选项卡断言（不是漏包）')
        chk('包内没有已废弃的「按关联分组」复选框',
            await ev("!!document.querySelector('#wShGroupLink')") is False)

        d = await ev("({w:document.documentElement.clientWidth,h:document.documentElement.clientHeight})")
        s = await call('Page.captureScreenshot',
                       {'format': 'png', 'captureBeyondViewport': True,
                        'clip': {'x': 0, 'y': 0, 'width': d['w'],
                                 'height': d['h'], 'scale': 1}})
        p = '%s.png' % SHOT
        open(p, 'wb').write(base64.b64decode(s['data']))
        print('[ .. ] 截图 -> %s' % p)

        print('----')
        print('PASS / FAIL: %d 项失败' % len(fails))
        for f in fails:
            print('  - ' + f)
        for w in warns:
            print('  ! ' + w)
        return len(fails) == 0


ok = False
try:
    ok = asyncio.run(main())
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    shutil.rmtree(TMP, ignore_errors=True)
print('==== RESULT: %s ====' % ('ALL PASS' if ok else 'HAS FAILURE'))
sys.exit(0 if ok else 1)
