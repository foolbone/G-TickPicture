# -*- coding: utf-8 -*-
"""CDP 实跑：Vue3 版侧栏收起/ 展开（vue3-frontend 分支）。

老板 2026-10-18 提的「新版菜单要能够收起来」：
  · 收起后侧栏从 216px 变 56px，一级菜单只剩图标（不是文字被裁掉）
  · 折叠态图标真居中，且不溢出侧栏（EP 默认 el-menu--collapse 是 64px 宽，
    在 56px 侧栏里会撑出横向滚动条 —— 这条必须断言）
  · 次级入口在折叠态仍有图标行（常用功能收起后不至于找不着）
  · 收起状态落 localStorage：刷新后仍是折叠的
  · 展开能恢复216px，且展开态五项文字、次级入口文字都在
  · 收起不影响路由 / 内容区（页面照常渲染、菜单仍可点进别的页）

⚠️ 隔离实例 8813 / CDP 9373，不碰 8765。
跑法：python tools/productlib/checks/cdp_vue_sidebar.py
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
PORT = int(os.environ.get('PL_PORT', '8813'))
CDP_PORT = int(os.environ.get('PL_CDP', '9373'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuesb_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuesb_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/containers'
SHOT_DIR = os.path.join(tempfile.gettempdir(), 'pl_vue_sidebar_shots')
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def http_json(path, port=PORT, retries=40, timeout=8):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
shutil.rmtree(SHOT_DIR, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.makedirs(DBHOME, exist_ok=True)
os.makedirs(SHOT_DIR, exist_ok=True)

srv = subprocess.Popen(
    [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
    env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try:
        with urllib.request.urlopen(BASE + '/api/ping', timeout=2) as r:
            json.loads(r.read()); break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例没起来')
    sys.exit(1)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,1000', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version', port=CDP_PORT, retries=40, timeout=3):
        print('[FAIL] 调试端口未就绪'); return False
    page = next((t for t in (http_json('/json/list', port=CDP_PORT) or [])
                 if t.get('type') == 'page'
                 and '/app/' in (t.get('url') or '')), None)
    if not page:
        print('[FAIL] 找不到 /app/ 的 page'); return False

    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
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
        await asyncio.sleep(7.5)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str((ex.get('exception') or {}).get('description')
                                     or ex.get('text'))[:200]
            return (r.get('result') or {}).get('value')

        async def shot(name):
            r = await cmd('Page.captureScreenshot', {'format': 'png'})
            import base64
            p = os.path.join(SHOT_DIR, name)
            with open(p, 'wb') as f:
                f.write(base64.b64decode(r.get('data') or ''))
            return p

        ASIDE = "document.querySelector('.app-aside')"
        MENU = "document.querySelector('.app-menu')"

        # ════ ① 初始展开态 ════
        chk('1 初始为展开态 216px',
            await js("Math.round(%s.getBoundingClientRect().width)" % ASIDE) == 216,
            await js("Math.round(%s.getBoundingClientRect().width)" % ASIDE))
        chk('1b 展开态五项菜单都有文字',
            await js("""(()=>{const t=[...document.querySelectorAll(
                '.app-menu .el-menu-item')].map(e=>(e.innerText||'').trim());
                return JSON.stringify(t);})()""")
            == '["柜","产品库","照片库","报告档案","设置"]',
            await js("""(()=>{const t=[...document.querySelectorAll(
                '.app-menu .el-menu-item')].map(e=>(e.innerText||'').trim());
                return JSON.stringify(t);})()"""))
        chk('1c 有收起按钮',
            await js("!!document.querySelector('.fold-btn')") is True)
        await shot('1_expanded.png')

        # ════ ② 点收起 ════
        await js("document.querySelector('.fold-btn').click()")
        await asyncio.sleep(1.5)
        await drain()
        w = await js("Math.round(%s.getBoundingClientRect().width)" % ASIDE)
        chk('2 点收起 → 侧栏 56px', w == 56, w)
        chk('2b 折叠态菜单只剩图标（文字不再占位）',
            await js("!!%s.classList.contains('el-menu--collapse')" % MENU) is True
            and await js("""(()=>{const t=[...document.querySelectorAll(
                '.app-menu .el-menu-item')].map(e=>(e.innerText||'').trim());
                return JSON.stringify(t);})()""") == '["","","","",""]',
            await js("""(()=>{const t=[...document.querySelectorAll(
                '.app-menu .el-menu-item')].map(e=>(e.innerText||'').trim());
                return JSON.stringify(t);})()"""))
        # EP 默认 el-menu--collapse 是 64px 宽，item 有 margin/padding-left。
        # 在 56px 侧栏里会横向溢出 —— 断言菜单不产生横向滚动且图标居中。
        ov = await js("""(()=>{const m=%s; const r=m.getBoundingClientRect();
            const it=m.querySelector('.el-menu-item');
            const ir=it&&it.getBoundingClientRect();
            const ic=it&&it.querySelector('.el-icon');
            const icr=ic&&ic.getBoundingClientRect();
            const tg=it&&it.querySelector('.el-menu-tooltip__trigger');
            const ts=tg&&getComputedStyle(tg);
            return JSON.stringify({
                menuW: Math.round(r.width), scrollW: m.scrollWidth,
                itemLeft: ir?Math.round(ir.left):-1, itemRight: ir?Math.round(ir.right):-1,
                iconMid: icr?Math.round((icr.left+icr.right)/2):-1,
                itemMid: ir?Math.round((ir.left+ir.right)/2):-1,
                tgJust: ts?ts.justifyContent:'',
                tgPad: ts?ts.paddingLeft+'/'+ts.paddingRight:''});})()""" % MENU)
        info = json.loads(ov) if isinstance(ov, str) else {}
        chk('2c 折叠菜单不横向溢出（EP 默认 64px 会撑破 56px 侧栏）',
            info.get('scrollW', 999) <= 57, ov)
        chk('2d 折叠态图标水平居中',
            info.get('iconMid', -1) > 0
            and abs(info.get('iconMid', 0) - info.get('itemMid', 99)) <= 3, ov)
        chk('2e 折叠态次级入口换成了图标行（3 个）',
            await js("""(()=>{const c=document.querySelector('.app-sub-ic');
                if(!c||c.style.display==='none') return 0;
                return c.querySelectorAll('.sub-ic').length;})()""") == 3,
            await js("document.querySelectorAll('.app-sub-ic .sub-ic').length"))
        chk('2f 展开态的次级入口文字行已隐藏',
            await js("""(()=>{const c=document.querySelector('.app-sub');
                return !c||c.style.display==='none';})()""") is True)
        await shot('2_folded.png')

        # ════ ③ 折叠态仍能导航 ════
        await js("""(()=>{const it=[...document.querySelectorAll(
            '.app-menu .el-menu-item')].find(e=>e.innerText==='' );})()""")
        await js("""(()=>{const items=[...document.querySelectorAll(
            '.app-menu .el-menu-item')];
            const i=items[2]; if(i) i.click();})()""")
        await asyncio.sleep(4.5)
        await drain()
        chk('3 折叠态点图标仍能导航（去照片库）',
            '/app/photos' in str(await js('location.pathname')),
            await js('location.pathname'))
        chk('3b 折叠态下照片库正常渲染',
            await js("!!document.querySelector('.photos-page')") is True)
        chk('3c 折叠态当前项高亮仍在',
            await js("""(()=>{const a=document.querySelector(
                '.app-menu .el-menu-item.is-active');
                return a? a.querySelector('.el-icon')!=null : false;})()""") is True)
        await shot('3_folded_nav.png')

        # ════ ④ 刷新后仍是折叠 ════
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(7.0)
        await drain()
        chk('4 刷新后仍保持折叠（localStorage 持久化）',
            await js("Math.round(%s.getBoundingClientRect().width)" % ASIDE) == 56,
            await js("Math.round(%s.getBoundingClientRect().width)" % ASIDE))
        chk('4b localStorage 里存的是 1',
            await js("localStorage.getItem('plSideFold')") == '1',
            await js("localStorage.getItem('plSideFold')"))

        # ════ ⑤ 展开恢复 ════
        await js("document.querySelector('.fold-btn').click()")
        await asyncio.sleep(1.5)
        await drain()
        chk('5 再点一次展开回 216px',
            await js("Math.round(%s.getBoundingClientRect().width)" % ASIDE) == 216,
            await js("Math.round(%s.getBoundingClientRect().width)" % ASIDE))
        chk('5b 展开后菜单/次级入口都回来了',
            await js("document.querySelectorAll('.app-menu .el-menu-item').length") == 5
            and await js("""(()=>{const c=document.querySelector('.app-sub');
                return c? c.style.display!=='none' : false;})()""") is True)
        chk('5c 展开后无横向溢出',
            await js("%s.scrollWidth <= %s.clientWidth + 1" % (ASIDE, ASIDE)) is True)
        await shot('4_reexpanded.png')

        chk('6 全程无 JS 异常', not excs, json.dumps(excs, ensure_ascii=False)[:300])
        print('截图目录: ' + SHOT_DIR)
        return not fails


ok = asyncio.run(main())
edge.terminate()
srv.terminate()
print(('FAIL %d 项' % len(fails)) if fails else 'PASS')
sys.exit(0 if ok and not fails else 1)