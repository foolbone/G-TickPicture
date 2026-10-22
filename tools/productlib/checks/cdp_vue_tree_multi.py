# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 新前端（/app/）的照片库左侧树**多选**（2026-10-19）。

旧版（web/index.html）由 checks/cdp_tree_multi.py 覆盖；本脚本钉死新前端
同一套口径 —— 两套前端共用 /api/*，行为不该分叉：

  1 选了第一个分类后，「按分类」段**仍列出全部分类**（能继续加选 🔴病根）；
  2 再点第二个 → 两项同时高亮，列表条数 == 两项之和；
  3 段标题出现「已选 N」+「清空」；点清空回到全量；
  4 全程无 JS 异常。

⚠️ 铁律：el.click() 是假绿（走不了真实事件序列）→ 用
   Input.dispatchMouseEvent；headless 的 --window-size 不生效 → 必须
   Emulation.setDeviceMetricsOverride 固定 1600×2400；打隔离端口不碰 8765。

跑法：python tools/productlib/checks/cdp_vue_tree_multi.py
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
PORT = int(os.environ.get('PL_PORT', '8823'))
CDP_PORT = int(os.environ.get('PL_CDP', '9383'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vtm_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vtm_db')
URL = 'http://127.0.0.1:%d/app/photos' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 12

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


def _req(method, path, obj=None, timeout=120):
    data = json.dumps(obj).encode('utf8') if obj is not None else None
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:200]}


def post_file(path, fields, files, timeout=600):
    b = '----plvtm' + str(int(time.time()))
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
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:200]}


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

code, c = _req('POST', '/api/containers',
               {'container_no': 'VMULTI1', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0a 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_vtm_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'VM_%02d.jpg' % i)
    Image.new('RGB', (900, 700), (80 + i * 12, 130, 200)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0b 上传 12 张', code == 200 and (r or {}).get('added', 0) == N_PHOTOS,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0c 取到 12 个 id', len(pids) == N_PHOTOS, len(pids))
_db = os.path.join(DBHOME, 'productlib.db')
con = sqlite3.connect(_db)
i = 0
for kind, n in (('label', 5), ('scene', 3), ('carton', 4)):
    for _ in range(n):
        con.execute('UPDATE photos SET photo_kind=? WHERE id=?', (kind, pids[i]))
        i += 1
con.execute("UPDATE photos SET govern_state='done'")
con.commit()
con.close()

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version', port=CDP_PORT, retries=40, timeout=3):
        print('[FAIL] 调试端口未就绪')
        return False
    page = next((t for t in (http_json('/json/list', port=CDP_PORT) or [])
                 if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

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
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1600, 'height': 2400, 'deviceScaleFactor': 1,
                   'mobile': False})
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(5)
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

        async def click(v):
            box = await js(
                "(function(){const s=document.querySelector('.ptree-sec"
                "[data-sec=\"kind\"]'); if(!s) return null;"
                "const b=s.querySelector('.ptree-i[data-v=\"%s\"]'); if(!b) return null;"
                "b.scrollIntoView({block:'center'});"
                "const r=b.getBoundingClientRect();"
                "return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2});})()" % v)
            if not box or str(box).startswith('EXC'):
                return False, box
            p = json.loads(box)
            if not (0 <= p['x'] <= 1600 and 0 <= p['y'] <= 2400):
                return False, 'out of viewport %s' % p
            for typ in ('mouseMoved', 'mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': typ, 'x': p['x'], 'y': p['y'],
                           'button': 'left' if typ != 'mouseMoved' else 'none',
                           'clickCount': 1})
            return True, p

        async def wait_shots(val, tries=40):
            for _ in range(tries):
                await asyncio.sleep(0.5)
                n = await js("document.querySelectorAll('.shot').length")
                if n == val:
                    return n
            return await js("document.querySelectorAll('.shot').length")

        def kind_js(cls):
            return ("(()=>{const s=document.querySelector('.ptree-sec"
                    "[data-sec=\"kind\"]'); return JSON.stringify("
                    "[...s.querySelectorAll('.ptree-i%s')].map(b=>b.dataset.v));})()"
                    % cls)

        ready = await js("document.querySelectorAll('.ptree-i').length")
        chk('1 新前端树已渲染', isinstance(ready, int) and ready >= 3, ready)
        n0 = await wait_shots(12, tries=20)
        chk('2 初始 12 张', n0 == 12, n0)
        k0 = await js(kind_js(''))
        chk('3 分类段列出全部 3 类',
            sorted(json.loads(k0 or '[]')) == ['carton', 'label', 'scene'], k0)

        ok, info = await click('label')
        chk('4 真实鼠标点到 label', ok is True, info)
        n1 = await wait_shots(5)
        chk('4b 选 label → 5 张', n1 == 5, n1)
        k1 = await js(kind_js(''))
        chk('5 选了 label 后分类段仍 3 项（能继续加选 🔴病根）',
            sorted(json.loads(k1 or '[]')) == ['carton', 'label', 'scene'], k1)

        ok, info = await click('scene')
        chk('6 再点 scene', ok is True, info)
        n2 = await wait_shots(8)
        chk('6b 多选 label+scene → 8 张（= 5+3）', n2 == 8, n2)
        on2 = await js(kind_js('.on'))
        chk('6c 两项同时高亮',
            sorted(json.loads(on2 or '[]')) == ['label', 'scene'], on2)
        cnt = await js("""(()=>{const s=document.querySelector('.ptree-sec'
            +'[data-sec=\"kind\"]'); const c=s.querySelector('.ptree-cnt');
            return c?c.textContent:'none';})()""")
        chk('6d 段标题显示已选 2', str(cnt) == '2', cnt)

        box = await js("""(()=>{const s=document.querySelector(
            '.ptree-sec[data-sec=\"kind\"]'); const b=s.querySelector('.ptree-clr');
            if(!b) return null; const r=b.getBoundingClientRect();
            return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2});})()""")
        chk('7 「清空」按钮已渲染', bool(box) and not str(box).startswith('EXC'),
            box)
        if box and not str(box).startswith('EXC'):
            p = json.loads(box)
            for typ in ('mouseMoved', 'mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': typ, 'x': p['x'], 'y': p['y'],
                           'button': 'left' if typ != 'mouseMoved' else 'none',
                           'clickCount': 1})
            n3 = await wait_shots(12)
            chk('7b 清空后回到 12 张', n3 == 12, n3)
        await drain()
        chk('8 全程无 JS 异常', not excs,
            str([str(e)[:120] for e in excs[:2]]))
        return True


ok = asyncio.run(main())
srv.terminate()
edge.terminate()
print('\n' + ('全部通过' if (ok and not fails) else
              '失败 %d 项：%s' % (len(fails), fails)))
sys.exit(0 if (ok and not fails) else 1)
