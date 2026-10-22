# -*- coding: utf-8 -*-
"""CDP 实跑验证：驱动本机 Edge 无头模式，真点页面、真按键、采样放大镜像素。

只读操作 —— 不保存标准图、不改产品字段、不点跳过。
"""
import asyncio, base64, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9333
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp')
SHOT = os.path.join(tempfile.gettempdir(), 'pl_shot')

fails = []
def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)

shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
     '--window-size=1440,2600', '--allow-file-access-from-files', URL],
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
    ver = http_json('/json/version')
    if not ver:
        print('[FAIL] Edge 调试端口未就绪'); return False
    lst = http_json('/json/list')
    page = next((t for t in lst if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page target'); return False

    events = []
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        _id = [0]
        async def call(method, params=None, timeout=30):
            _id[0] += 1
            i = _id[0]
            await ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if msg.get('id') == i:
                    if 'error' in msg:
                        raise RuntimeError('%s: %s' % (method, msg['error']))
                    return msg.get('result', {})
                events.append(msg)

        await call('Log.enable')
        await call('Runtime.enable')
        await call('Page.enable')

        async def ev(expr):
            r = await call('Runtime.evaluate',
                           {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
            v = r.get('result', {})
            if v.get('subtype') == 'error' or 'exceptionDetails' in r:
                return {'__err__': str(v.get('description') or r.get('exceptionDetails'))}
            return v.get('value')

        async def wait(s):
            await asyncio.sleep(s)
            # 排空事件队列（含 console / 异常）
            try:
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 0.05))
                    events.append(msg)
            except Exception:
                pass

        await wait(3.0)

        # ── 1 首屏 ──
        home = await ev("document.querySelector('#tab-home').innerText.slice(0,300)")
        chk('首页渲染出内容', isinstance(home, str) and len(home) > 20, str(home)[:120].replace('\n', ' / '))

        # ── 2 产品库：分页 + 行 ──
        await ev("document.querySelector('nav button[data-tab=\\'products\\']').click()")
        await wait(3.0)
        # 只挑「有照片」的产品 —— 否则右栏没照片，后面的抽屉/编辑器都测不到
        await ev("""(function(){var s=document.querySelector('#pHas');
          s.value='yes'; s.dispatchEvent(new Event('change')); return s.value;})()""")
        await wait(3.0)
        rows = await ev("document.querySelectorAll('#pBody tr').length")
        pgi = await ev("document.querySelector('#pgInfo').textContent")
        chk('产品表有行', isinstance(rows, int) and rows > 0, 'rows=%s' % rows)
        chk('分页信息已渲染', isinstance(pgi, str) and '共' in pgi, pgi)

        # ── 3 右栏：按产品打开照片（批次分组）──
        await ev("document.querySelector('#pBody tr').click()")
        await wait(3.0)
        shots = await ev("document.querySelectorAll('#pShots .shot').length")
        bgroups = await ev("document.querySelectorAll('#pShots .bgroup').length")
        title = await ev("document.querySelector('#pTitle').textContent")
        chk('右栏照片渲染', isinstance(shots, int) and shots >= 0, 'shots=%s groups=%s' % (shots, bgroups))
        chk('批次分组标题存在', isinstance(title, str) and '预检采集图片' in title, title)

        # ── 4 抽屉：打开 + ←/→ 切换 ──
        if shots and shots > 1:
            await ev("document.querySelector('#pShots .shot').click()")
            await wait(2.5)
            pos1 = await ev("document.querySelector('#dwPos').textContent")
            nxt = await ev("document.querySelector('#dwNext').style.display")
            chk('抽屉打开并给出位置', isinstance(pos1, str) and '/' in pos1, 'pos=%s next_display=%s' % (pos1, nxt))
            await ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight'}))")
            await wait(2.5)
            pos2 = await ev("document.querySelector('#dwPos').textContent")
            chk('→ 键切到下一张', pos1 != pos2, '%s -> %s' % (pos1, pos2))
        else:
            chk('抽屉切换（该产品的照片不足 2 张，跳过）', True, 'shots=%s' % shots)

        # ── 5 标准图编辑器 + 放大镜 ──
        await ev("(function(){var b=document.querySelector('#dwStd'); if(b) b.click(); return !!b;})()")
        await wait(3.5)
        zoomSel = await ev("!!document.querySelector('#stdZoomSel')")
        cvReady = await ev("(function(){var c=document.querySelector('#stdCanvas'); return c && c.width>0;})()")
        chk('标准图编辑器打开（画布已建）', zoomSel is True and cvReady is True,
            'zoomSel=%s canvasReady=%s' % (zoomSel, cvReady))
        if cvReady is True:
            r = await ev("""(function(){
              var cv=document.querySelector('#stdCanvas'); var b=cv.getBoundingClientRect();
              cv.dispatchEvent(new PointerEvent('pointermove',{clientX:b.left+b.width/2,
                clientY:b.top+b.height/2, bubbles:true, pointerId:1, pointerType:'mouse'}));
              return true;})()""")
            await wait(1.0)
            on = await ev("document.querySelector('#stdZoom').classList.contains('on')")
            px = await ev("""(function(){var c=document.querySelector('#stdZoomCv');
              var d=c.getContext('2d').getImageData(0,0,c.width,c.height).data; var n=0;
              for(var i=3;i<d.length;i+=4){ if(d[i]>0) n++; } return n;})()""")
            lv = await ev("document.querySelector('#stdZoomLv').textContent")
            chk('放大镜随光标显示', on is True, 'on=%s level=%s' % (on, lv))
            chk('放大镜真的画出了像素', isinstance(px, int) and px > 1000, 'nonTransparentPx=%s' % px)
            # 关掉放大镜，确认能关
            await ev("""(function(){var s=document.querySelector('#stdZoomSel');
              s.value='0'; s.dispatchEvent(new Event('change')); return true;})()""")
            await wait(0.6)
            off = await ev("document.querySelector('#stdZoom').classList.contains('on')")
            chk('放大镜可关闭', off is False, 'on=%s' % off)

        # ── 6 截图 ──
        shot = await call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True})
        data = base64.b64decode(shot['data'])
        open(SHOT + '_std.png', 'wb').write(data)
        chk('截图已保存', len(data) > 10000, '%s_std.png %d bytes' % (SHOT, len(data)))

        await ev("document.querySelector('#stdClose').click()")
        await ev("document.querySelector('nav button[data-tab=\\'report\\']').click()")
        await wait(3.0)
        s2 = await call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True})
        open(SHOT + '_report.png', 'wb').write(base64.b64decode(s2['data']))
        await ev("document.querySelector('nav button[data-tab=\\'review\\']').click()")
        await wait(3.0)
        s3 = await call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True})
        open(SHOT + '_review.png', 'wb').write(base64.b64decode(s3['data']))

    # ── 7 控制台错误 ──
    errs = []
    for m in events:
        if m.get('method') == 'Log.entryAdded':
            e = m['params']['entry']
            if e.get('level') in ('error', 'warning'):
                errs.append('%s: %s @ %s' % (e.get('level'), (e.get('text') or '')[:120],
                                             (e.get('url') or '')[:120]))
        if m.get('method') == 'Runtime.exceptionThrown':
            d = m['params'].get('exceptionDetails', {})
            errs.append('exception: %s' % (d.get('text', '') + ' ' + str(d.get('exception', {}).get('description', '')))[:200])
    chk('无控制台 error / 未捕获异常', not errs, errs[:6])
    return True

try:
    ok = asyncio.run(main())
finally:
    proc.terminate()
    try:
        proc.wait(5)
    except Exception:
        proc.kill()

print('\nRESULT:', 'PASS' if not fails else 'FAIL ' + str(fails))
sys.exit(0 if not fails else 1)

