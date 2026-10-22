# -*- coding: utf-8 -*-
"""CDP 实跑：验证「分类配色」与「紧凑/详情 双视图 + 悬停浮层」。

关键：CSS :hover 只能靠真实鼠标事件触发 —— 必须用 Input.dispatchMouseEvent 移动鼠标。
"""
import asyncio, base64, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9334
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp2')
SHOT = os.path.join(tempfile.gettempdir(), 'pl_view')

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
     '--window-size=1440,2000', URL],
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

        await call('Log.enable'); await call('Runtime.enable'); await call('Page.enable')
        async def ev(expr):
            r = await call('Runtime.evaluate',
                           {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
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
                   {'width': 1440, 'height': 1600, 'deviceScaleFactor': 1, 'mobile': False})
        await wait(3.0)

        # ── 进照片浏览页 ──
        await ev("document.querySelector('nav button[data-tab=\\'batches\\']').click()")
        await wait(4.0)
        n = await ev("document.querySelectorAll('#shots .shot').length")
        chk('照片网格有卡片', isinstance(n, int) and n > 0, 'shots=%s' % n)

        # ── 1 分类配色：同一页里不同分类应是不同颜色 ──
        info = await ev("""(function(){
          var out = {};
          document.querySelectorAll('#shots .shot .badge').forEach(function(b){
            var t = (b.textContent||'').trim();
            var c = getComputedStyle(b).backgroundColor;
            if(!b.className.includes('stdb')) out[t] = c;
          });
          return out;})()""")
        chk('分类角标取到颜色', isinstance(info, dict) and len(info) >= 2, json.dumps(info, ensure_ascii=False))
        colors = set(info.values())
        chk('不同分类颜色不同（≥3 种）', len(colors) >= 3,
            '%d 种颜色 / %d 个分类' % (len(colors), len(info)))
        # 用户点名的两个：标识卡绿、产品蓝
        green = any('21, 128, 61' in c for c in info.values())
        blue = any('29, 78, 216' in c for c in info.values())
        chk('标识卡用绿色 (21,128,61)', green, [k for k, v in info.items() if '21, 128, 61' in v])
        chk('产品用蓝色 (29,78,216)', blue, [k for k, v in info.items() if '29, 78, 216' in v])
        # 角标是否中文（扫视友好）
        zh = await ev("""(function(){var b=document.querySelector('#shots .shot .badge');
          return b ? b.textContent.trim() : '';})()""")
        chk('角标是中文分类名', any(ch in (zh or '') for ch in '标识卡产品包装清单场景未分类'), zh)

        # ── 2 双视图切换 ──
        await ev("document.querySelector('#shotView button[data-v=\\'compact\\']').click()")
        await wait(1.0)
        isCompact = await ev("document.body.classList.contains('v-compact')")
        metaDisp = await ev("""(function(){var m=document.querySelector('#shots .shot .meta');
          return m ? getComputedStyle(m).display : 'no-meta';})()""")
        chk('切紧凑：body 加 v-compact', isCompact is True)
        chk('切紧凑：文件名/时间常显区被隐藏', metaDisp == 'none', 'meta display=%s' % metaDisp)
        hinfoNone = await ev("""(function(){var h=document.querySelector('#shots .shot .hinfo');
          return h ? getComputedStyle(h).display : 'no-hinfo';})()""")
        chk('未悬停时浮层不显示', hinfoNone == 'none', 'hinfo display=%s' % hinfoNone)

        # ── 3 真实鼠标悬停 → 浮层出现 ──
        rect = await ev("""(function(){var s=document.querySelector('#shots .shot');
          s.scrollIntoView({block:'center'}); var r=s.getBoundingClientRect();
          return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};})()""")
        await call('Input.dispatchMouseEvent',
                   {'type': 'mouseMoved', 'x': rect['x'], 'y': rect['y'], 'button': 'none'})
        await wait(0.8)
        hinfoHover = await ev("""(function(){var h=document.querySelector('#shots .shot .hinfo');
          return h ? getComputedStyle(h).display : 'no-hinfo';})()""")
        htxt = await ev("""(function(){var h=document.querySelector('#shots .shot .hinfo');
          return h ? h.innerText.replace(/\\n/g,' | ') : '';})()""")
        chk('悬停后浮层显示', hinfoHover == 'block', 'display=%s' % hinfoHover)
        chk('浮层里有文件名+时间/大小', 'MB' in (htxt or '') and len(htxt or '') > 8, htxt)
        await call('Page.captureScreenshot', {'format': 'png'})
        s1 = await call('Page.captureScreenshot', {'format': 'png'})
        open(SHOT + '_compact_hover.png', 'wb').write(base64.b64decode(s1['data']))

        # 鼠标移开 → 浮层收起
        await call('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 5, 'y': 5, 'button': 'none'})
        await wait(0.6)
        off = await ev("""(function(){var h=document.querySelector('#shots .shot .hinfo');
          return h ? getComputedStyle(h).display : 'no-hinfo';})()""")
        chk('鼠标移开后浮层收起', off == 'none', 'display=%s' % off)

        # ── 4 切回详情 + 记住选择 ──
        await ev("document.querySelector('#shotView button[data-v=\\'full\\']').click()")
        await wait(1.0)
        metaBack = await ev("""(function(){var m=document.querySelector('#shots .shot .meta');
          return m ? getComputedStyle(m).display : 'no-meta';})()""")
        saved = await ev("localStorage.getItem('shotView')")
        chk('切回详情：信息常显回来', metaBack != 'none', 'display=%s' % metaBack)
        chk('选择写入 localStorage', saved == 'full', 'shotView=%s' % saved)
        s2 = await call('Page.captureScreenshot', {'format': 'png'})
        open(SHOT + '_full.png', 'wb').write(base64.b64decode(s2['data']))

    errs = []
    for m in events:
        if m.get('method') == 'Log.entryAdded':
            e = m['params']['entry']
            if e.get('level') == 'error':
                errs.append('%s @ %s' % ((e.get('text') or '')[:100], (e.get('url') or '')[:80]))
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

