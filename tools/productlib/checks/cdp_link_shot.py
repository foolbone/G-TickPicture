# -*- coding: utf-8 -*-
"""截图：照片页「关联」分组视图 + 向导③ 勾上分组后的样子。"""
import asyncio, base64, json, os, shutil, subprocess, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9343
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_link')
SHOT = os.path.join(tempfile.gettempdir(), 'pl_link')
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
    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        _id = [0]

        async def call(method, params=None):
            _id[0] += 1
            i = _id[0]
            await ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if msg.get('id') == i:
                    return msg.get('result', {})

        await call('Runtime.enable')
        await call('Page.enable')

        async def ev(expr):
            r = await call('Runtime.evaluate',
                           {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
            return r.get('result', {}).get('value')

        async def wait(s):
            await asyncio.sleep(s)

        async def shot(name, h=1100):
            await call('Emulation.setDeviceMetricsOverride',
                       {'width': 1440, 'height': h, 'deviceScaleFactor': 1, 'mobile': False})
            await asyncio.sleep(0.6)
            d = await ev("({w:document.documentElement.clientWidth,h:document.documentElement.clientHeight})")
            s = await call('Page.captureScreenshot',
                           {'format': 'png', 'captureBeyondViewport': True,
                            'clip': {'x': 0, 'y': 0, 'width': d['w'], 'height': d['h'], 'scale': 1}})
            p = '%s_%s.png' % (SHOT, name)
            open(p, 'wb').write(base64.b64decode(s['data']))
            print('截图 ->', p)

        await wait(4)
        await ev("go('batches')")
        await wait(2)
        await ev("PL.setShotView('link')")
        await wait(9)
        print('选项卡 =', await ev("[...document.querySelectorAll('#shotTabs [data-ptab]')].map(b=>b.textContent.trim())"))
        print('角标数 =', await ev("document.querySelectorAll('#shots .fbadge').length"))
        await shot('view')

        # 柜作业已并进柜页（2026-10-08）：先切到柜页选柜，再进柜作业
        await ev("go('containers')")
        await wait(2)
        await ev("""(()=>{const s=document.querySelector('#globalCid');
            if(s&&s.options.length>1){s.selectedIndex=1;
              s.dispatchEvent(new Event('change',{bubbles:true}));}})()""")
        await wait(3.5)
        await ev("enterWizard('')")
        await wait(2)
        await ev("document.querySelector('#wizBar .wstep[data-step=photos]').click()")
        await wait(3)
        await ev("""(()=>{const b=[...document.querySelectorAll('#wShTabs [data-ptab]')]
            .find(x=>x.dataset.ptab==='cand'); if(b) b.click();})()""")
        await wait(9)
        print('向导选项卡 =', await ev("[...document.querySelectorAll('#wShTabs [data-ptab]')].map(b=>b.textContent.trim())"))
        print('向导角标数 =', await ev("document.querySelectorAll('#wizShots .fbadge').length"))
        await shot('wizard')
        return True


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
