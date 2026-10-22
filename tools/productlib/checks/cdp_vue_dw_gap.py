# -*- coding: utf-8 -*-
"""诊断：Vue3 照片抽屉左栏「图片 ↔ 文件名」之间的巨大空白（2026-10-20）。

老板反馈（截图）：竖构图照片下方，文件名/柜号/箱号那行离图片很远，
中间空掉一大段。本脚本用竖图（900x1200）复现，逐个量
.dw-left / .dw-imgwrap / img / .dw-src 的盒子，定位空白出在哪一层，
并顺带验证 `max-height: min(56vh, 100%)` 在 auto 高度父容器里是否失效。

⚠️ 自建隔离实例（PL_HOME=临时目录），不碰 8765。
"""
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8799'))
CDP_PORT = int(os.environ.get('PL_CDP', '9359'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_dwgap_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_dwgap_db')
URL = 'http://127.0.0.1:%d/app/photos' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 3
IMG_W, IMG_H = 900, 1200          # 竖构图，和老板截图一致


def http_json(path, port=PORT, retries=60, timeout=8):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def _req(method, path, obj=None, timeout=180):
    data = json.dumps(obj).encode('utf8') if obj is not None else None
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


def post_file(path, fields, files, timeout=600):
    b = '----dwgap' + str(int(time.time()))
    buf = b''
    for k, v in fields.items():
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                % (b, k, v)).encode('utf8')
    for k, fp, fn in files:
        with open(fp, 'rb') as f:
            data = f.read()
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n'
                % (b, k, fn)).encode('utf8')
        buf += data + b'\r\n'
    buf += ('--%s--\r\n' % b).encode('utf8')
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.makedirs(DBHOME, exist_ok=True)

srv = subprocess.Popen(
    [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
    env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % PORT,
                                    timeout=2) as r:
            json.loads(r.read())
            break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例没起来')
    sys.exit(1)

sc, cc = _req('POST', '/api/containers',
              {'container_no': 'GAP01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (cc or {}).get('id')

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_dwgap_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'GAP_%02d.jpg' % i)
    Image.new('RGB', (IMG_W, IMG_H), (50 + i * 12, 160, 120)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
print('upload:', code, json.dumps(r, ensure_ascii=False)[:120], flush=True)

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]

db = os.path.join(DBHOME, 'productlib.db')
con = sqlite3.connect(db)
for i, pid in enumerate(pids):
    con.execute("UPDATE photos SET taken_at=?, photo_kind='label', "
                "photo_usage='预检', time_src='exif', govern_state='done' "
                'WHERE id=?', ('2026-09-20 %02d:%02d:00' % (8, i * 10), pid))
con.commit()
con.close()

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1440,900', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def run():
    page = None
    for _ in range(40):
        lst = http_json('/json/list', port=CDP_PORT, retries=1, timeout=3) or []
        page = next((t for t in lst if t.get('type') == 'page'
                     and 'app/photos' in (t.get('url') or '')), None) \
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

        await cmd('Runtime.enable')
        await cmd('Page.enable')
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1440, 'height': 900, 'deviceScaleFactor': 1,
                   'mobile': False})
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.0)

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str((ex.get('exception') or {}).get('description')
                                     or ex.get('text'))[:300]
            return (r.get('result') or {}).get('value')

        async def click_sel(sel):
            box = await js("""(function(){const e=document.querySelector('%s');
                if(!e) return null; const r=e.getBoundingClientRect();
                return JSON.stringify({x:r.left+r.width/2, y:r.top+r.height/2});})()"""
                           % sel)
            if not box or not isinstance(box, str):
                return False
            b = json.loads(box)
            for t in ('mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': t, 'x': b['x'], 'y': b['y'],
                           'button': 'left', 'clickCount': 1})
            return True

        await click_sel('.shot')
        for _ in range(40):
            await asyncio.sleep(0.5)
            if await js("!!document.querySelector('.dw-cols')"):
                break
        await asyncio.sleep(2.0)

        m = await js("""(()=>{
          const q = s => document.querySelector(s);
          const box = e => { if(!e) return null; const r=e.getBoundingClientRect();
            return {t:Math.round(r.top), b:Math.round(r.bottom),
                    h:Math.round(r.height), w:Math.round(r.width)}; };
          const wrap = q('.dw-imgwrap');
          const im = q('.dw-imgwrap img');
          const cs = im ? getComputedStyle(im) : null;
          const cw = wrap ? getComputedStyle(wrap) : null;
          const cl = q('.dw-left') ? getComputedStyle(q('.dw-left')) : null;
          const ib = im ? im.getBoundingClientRect().bottom : 0;
          const sb = q('.dw-src') ? q('.dw-src').getBoundingClientRect().top : 0;
          return JSON.stringify({
            vh: innerHeight,
            dw: box(q('.dw')),
            cols: box(q('.dw-cols')),
            left: box(q('.dw-left')),
            leftJus: cl ? cl.justifyContent : null,
            wrap: box(wrap),
            wrapFlex: cw ? cw.flex : null,
            img: box(im),
            nat: im ? (im.naturalWidth + 'x' + im.naturalHeight) : null,
            imgMaxH: cs ? cs.maxHeight : null,
            imgMinH: cs ? cs.minHeight : null,
            imgCssH: cs ? cs.height : null,
            imgCssW: cs ? cs.width : null,
            src: box(q('.dw-src')),
            sibs: box(q('.dw-sibs')),
            gapImgToSrc: Math.round(sb - ib),
            gapWrapBottomToSrc: (wrap && q('.dw-src')) ?
              Math.round(q('.dw-src').getBoundingClientRect().top
                         - wrap.getBoundingClientRect().bottom) : null,
            slackInWrap: (wrap && im) ?
              Math.round(wrap.getBoundingClientRect().height
                         - im.getBoundingClientRect().height) : null,
            slackInLeft: (q('.dw-left')) ?
              Math.round(q('.dw-left').getBoundingClientRect().height
                - (wrap ? wrap.getBoundingClientRect().height : 0)
                - (q('.dw-src') ? q('.dw-src').getBoundingClientRect().height : 0)) : null,
          });})()""")
        print('\n===== 盒模型实测 =====')
        try:
            print(json.dumps(json.loads(m), ensure_ascii=False, indent=2))
        except Exception:  # noqa: BLE001
            print(m)


try:
    asyncio.run(run())
finally:
    for p in (srv, edge):
        try:
            p.terminate()
        except Exception:  # noqa: BLE001
            pass
    time.sleep(1)
    shutil.rmtree(HOME, ignore_errors=True)
    shutil.rmtree(DBHOME, ignore_errors=True)
