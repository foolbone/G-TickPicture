# -*- coding: utf-8 -*-
"""CDP 实跑：验证 ①页面不再有流程步骤条 ②批次表收进抽屉、主线只剩 导入→治理→浏览。"""
import asyncio, base64, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9335
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp3')
SHOT = os.path.join(tempfile.gettempdir(), 'pl_layout')

fails = []
def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)

shutil.rmtree(TMP, ignore_errors=True); os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen([EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
     '--window-size=1440,1400', URL],
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
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪'); return False
    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page'); return False

    events = []
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        _id = [0]
        async def call(method, params=None):
            _id[0] += 1; i = _id[0]
            await ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if msg.get('id') == i:
                    if 'error' in msg:
                        raise RuntimeError('%s: %s' % (method, msg['error']))
                    return msg.get('result', {})
                events.append(msg)
        await call('Log.enable'); await call('Runtime.enable'); await call('Page.enable')
        async def ev(expr):
            r = await call('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
            v = r.get('result', {})
            if v.get('subtype') == 'error' or 'exceptionDetails' in r:
                return {'__err__': str(v.get('description') or r.get('exceptionDetails'))}
            return v.get('value')
        async def wait(s):
            await asyncio.sleep(s)
            try:
                while True:
                    events.append(json.loads(await asyncio.wait_for(ws.recv(), 0.05)))
            except Exception:
                pass

        await call('Emulation.setDeviceMetricsOverride',
                   {'width': 1440, 'height': 1400, 'deviceScaleFactor': 1, 'mobile': False})
        await wait(3.0)

        # ── ① 流程步骤条已不存在 ──
        chk('#stepper 元素已移除', await ev("!document.querySelector('#stepper')") is True)
        chk('.step 节点数为 0', await ev("document.querySelectorAll('.step').length") == 0)
        chk('JS 里 renderStepper 已不存在',
            await ev("typeof renderStepper === 'undefined'") is True)
        chk('STEP_TAB 已不存在', await ev("typeof STEP_TAB === 'undefined'") is True)

        # ── ② 进预检照片入库页 ──
        await ev("document.querySelector('nav button[data-tab=\\'batches\\']').click()")
        await wait(4.0)
        panels = await ev("""[...document.querySelectorAll('#tab-batches .panel h3')]
          .map(h=>h.textContent.split('\\u3010')[0].trim())""")
        chk('页面只剩 导入 / 治理 / 浏览 三块', len(panels) == 3, panels)
        chk('批次表不在主页面里',
            await ev("!document.querySelector('#tab-batches #bBody')") is True)
        chk('批次呼出入口按钮存在',
            await ev("!!document.querySelector('#bOpen')") is True)
        btnTxt = await ev("document.querySelector('#bOpen').textContent.trim()")
        chk('入口显示批次数', '照片批次' in (btnTxt or ''), btnTxt)
        h1 = await ev("document.querySelector('#tab-batches').scrollHeight")
        s0 = await call('Page.captureScreenshot', {'format': 'png'})
        open(SHOT + '_main.png', 'wb').write(base64.b64decode(s0['data']))
        print('     预检照片入库页高度 =', h1, 'px')

        # ── ③ 抽屉：开 → 有批次 → 关 ──
        await ev("document.querySelector('#bOpen').click()")
        await wait(3.0)
        on = await ev("document.querySelector('#bDrawer').classList.contains('on')")
        rows = await ev("document.querySelectorAll('#bBody tr').length")
        total = await ev("document.querySelector('#bTotal').textContent")
        chk('点入口抽屉滑出', on is True)
        chk('抽屉里批次表有数据', isinstance(rows, int) and rows > 0, 'rows=%s %s' % (rows, total))
        x = await ev("""(function(){var d=document.querySelector('#bDrawer');
          var r=d.getBoundingClientRect(); return Math.round(r.left);})()""")
        chk('抽屉真的滑到视口内（left < 1440）', isinstance(x, int) and x < 1440, 'left=%s' % x)
        s1 = await call('Page.captureScreenshot', {'format': 'png'})
        open(SHOT + '_drawer.png', 'wb').write(base64.b64decode(s1['data']))

        # 「查看」→ 抽屉自动收起 + 筛选切到该批次
        before = await ev("document.querySelector('#fBatch').value")
        await ev("""(function(){var b=document.querySelector('#bBody [data-b-view]');
          if(b){ b.click(); return true; } return false;})()""")
        await wait(2.5)
        after = await ev("document.querySelector('#fBatch').value")
        closed = await ev("!document.querySelector('#bDrawer').classList.contains('on')")
        chk('点「查看」切到该批次', after and after != before, '%s -> %s' % (before, after))
        chk('点「查看」后抽屉自动收起', closed is True)

        # Esc 关闭
        await ev("document.querySelector('#bOpen').click()")
        await wait(1.5)
        await ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))")
        await wait(0.8)
        chk('Esc 可关抽屉',
            await ev("!document.querySelector('#bDrawer').classList.contains('on')") is True)
        # 点遮罩关闭
        await ev("document.querySelector('#bOpen').click()")
        await wait(1.5)
        await ev("document.querySelector('#bMask').click()")
        await wait(0.8)
        chk('点遮罩可关抽屉',
            await ev("!document.querySelector('#bDrawer').classList.contains('on')") is True)

        # 其它页也确认没有流程条
        for t in ('products', 'review', 'report', 'set'):
            await ev("document.querySelector('nav button[data-tab=\\'%s\\']').click()" % t)
            await wait(1.2)
        chk('切页无残留 stepper',
            await ev("document.querySelectorAll('.stepper,.step').length") == 0)

    errs = []
    for m in events:
        if m.get('method') == 'Log.entryAdded' and m['params']['entry'].get('level') == 'error':
            errs.append('%s @ %s' % ((m['params']['entry'].get('text') or '')[:100],
                                     (m['params']['entry'].get('url') or '')[:80]))
        if m.get('method') == 'Runtime.exceptionThrown':
            errs.append('exception: %s' % str(m['params'])[:160])
    chk('无控制台 error / 异常', not errs, errs[:5])
    return True

try:
    asyncio.run(main())
finally:
    proc.terminate()
    try:
        proc.wait(5)
    except Exception:
        proc.kill()
print('\nRESULT:', 'PASS' if not fails else 'FAIL ' + str(fails))
sys.exit(0 if not fails else 1)

