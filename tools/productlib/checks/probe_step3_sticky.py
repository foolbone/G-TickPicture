# -*- coding: utf-8 -*-
"""探针：向导③左树 sticky 为什么不生效（祖先链 overflow / position）。

sticky 失效只有三种可能，逐个打出来别猜：
  ① 元素自己 position 不是 sticky / top 没生效
  ② 某个祖先 overflow 不是 visible（切断了 sticky 的滚动上下文）
  ③ sticky 的行程被父容器高度吃光（父高 == 元素高，没有位移空间）

跑法：python tools/productlib/checks/probe_step3_sticky.py
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
PORT = int(os.environ.get('PL_PORT', '8816'))
CDP_PORT = int(os.environ.get('PL_CDP', '9376'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_probe_s3_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_probe_s3_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/wizard?step=photos'
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def http_json(path, port=PORT, retries=40, timeout=8):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def _req(method, path, obj=None):
    data = json.dumps(obj).encode('utf8') if obj is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


def post_file(path, fields, files, timeout=600):
    b = '----plpro' + str(int(time.time()))
    buf = b''
    for k, v in fields.items():
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                % (b, k, v)).encode('utf8')
    for k, fp, fn in files:
        with open(fp, 'rb') as f:
            data = f.read()
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n' % (b, k, fn)).encode('utf8')
        buf += data + b'\r\n'
    buf += ('--%s--\r\n' % b).encode('utf8')
    req = urllib.request.Request(BASE + path, data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


for d in (HOME, DBHOME):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)

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
    print('[FAIL] 服务没起来'); sys.exit(1)

from PIL import Image  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_probe_s3_img')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
_, c = _req('POST', '/api/containers', {'container_no': 'PROBE3', 'inspector': 'cdp'})
wid = (c or {}).get('id')
files = []
for i in range(90):
    p = os.path.join(tmpd, 'P3_%02d.jpg' % i)
    Image.new('RGB', (900, 675), (60 + i * 2, 120, 160)).save(p)
    files.append(('files', p, os.path.basename(p)))
print('upload ->', post_file('/api/photos/upload',
                             {'container_id': wid}, files)[0], flush=True)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,1000', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    for _ in range(40):
        if http_json('/json/version', port=CDP_PORT, retries=1, timeout=3):
            break
        await asyncio.sleep(0.5)
    page = next((t for t in (http_json('/json/list', port=CDP_PORT) or [])
                 if t.get('type') == 'page' and '/app/' in (t.get('url') or '')), None)
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

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str(ex.get('text'))[:200]
            return (r.get('result') or {}).get('value')

        await cmd('Runtime.enable')
        await cmd('Page.enable')
        await cmd('Page.navigate', {'url': BASE + '/app/home'})
        await asyncio.sleep(4.0)
        await js("localStorage.setItem('plCid', %s)" % json.dumps(wid))
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(8.0)

        print('== 树自身 ==', await js("""(()=>{const e=document.querySelector(
            '.ptree-wrap'); if(!e) return 'NO .ptree-wrap';
            const s=getComputedStyle(e); const r=e.getBoundingClientRect();
            return JSON.stringify({pos:s.position, top:s.top,
              overflow:s.overflow, alignSelf:s.alignSelf,
              h:Math.round(r.height), w:Math.round(r.width)});})()"""), flush=True)

        print('== 祖先链 ==', await js("""(()=>{const e=document.querySelector(
            '.ptree-wrap'); if(!e) return 'none';
            const out=[]; let p=e.parentElement;
            while(p && p!==document.documentElement){
              const s=getComputedStyle(p); const r=p.getBoundingClientRect();
              out.push(p.tagName+'.'+String(p.className).slice(0,40)
                +' | overflowY='+s.overflowY+' overflowX='+s.overflowX
                +' | display='+s.display
                +' | h='+Math.round(r.height)
                +' | scrollTop='+p.scrollTop+' scrollH='+p.scrollHeight
                +' clientH='+p.clientHeight);
              p=p.parentElement;}
            return out.join('\\n');})()"""), flush=True)

        print('== 兄弟/父 ==', await js("""(()=>{const e=document.querySelector(
            '.ptree-wrap'); const prow=e&&e.parentElement;
            const pm=document.querySelector('.pmain');
            return JSON.stringify({
              prowCls: prow?String(prow.className):'',
              prowH: prow?Math.round(prow.getBoundingClientRect().height):-1,
              prowAlign: prow?getComputedStyle(prow).alignItems:'',
              pmH: pm?Math.round(pm.getBoundingClientRect().height):-1});})()"""), flush=True)

        print('== 滚动容器 ==', await js("""(()=>{const a=document.querySelector(
            '.app-scroll'); const b=document.querySelector('.app-main');
            return JSON.stringify({
              appScroll: a?{scrollTop:a.scrollTop, scrollH:a.scrollHeight,
                            clientH:a.clientHeight,
                            overflow:getComputedStyle(a).overflow}:null,
              appMain: b?{scrollTop:b.scrollTop, scrollH:b.scrollHeight,
                          clientH:b.clientHeight,
                          overflow:getComputedStyle(b).overflow}:null});})()"""), flush=True)

        for y in (300, 700, 1400):
            await js("(document.querySelector('.app-scroll')||document.body)"
                     ".scrollTop=%d" % y)
            await asyncio.sleep(0.8)
            print('滚 %d -> 树 top=%s 实际滚动量=%s' % (
                y,
                await js("Math.round(document.querySelector('.ptree-wrap')"
                         ".getBoundingClientRect().top)"),
                await js("(document.querySelector('.app-scroll')||document.body).scrollTop")),
                flush=True)


asyncio.run(main())
edge.terminate()
srv.terminate()