# -*- coding: utf-8 -*-
"""CDP 实跑：Vue3 新前端（/app/）照片详情页的一屏布局（2026-10-20）。

与 checks/cdp_drawer_layout.py 同一需求，验的是另一套前端：

  1 抽屉首屏不滚动；
  2 「关联产品」是右栏第一块，且已关联的照片也有手输框；
  3 左栏有同产品编码参考块，只铺最近 8 张，其余折起来；
  4 大图高度受控（< 视口 78%）。

⚠️ 1440×900 真实笔记本视口；自建隔离实例，不碰 8765。
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
PORT = int(os.environ.get('PL_PORT', '8798'))
CDP_PORT = int(os.environ.get('PL_CDP', '9358'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuedw_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuedw_db')
URL = 'http://127.0.0.1:%d/app/photos' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 14
N_LINK = 12
CODE = 'P-200'

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


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
    b = '----plvd' + str(int(time.time()))
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
              {'container_no': 'VUEDW01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (cc or {}).get('id')
chk('0a 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_vuedw_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'VD_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (50 + i * 12, 160, 120)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0b 上传 14 张', code == 200 and (r or {}).get('added', 0) == N_PHOTOS,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0c 取到 14 个 id', len(pids) == N_PHOTOS, len(pids))

db = os.path.join(DBHOME, 'productlib.db')
con = sqlite3.connect(db)
con.execute("INSERT OR REPLACE INTO products(code_norm,code,name,photo_count,"
            "created_at,updated_at) VALUES(?,?,?,0,'2026-09-20','2026-09-20')",
            (CODE, CODE, '测试产品'))
for pid in pids[:N_LINK]:
    con.execute('INSERT OR REPLACE INTO links(code_norm,photo_id,source,'
                "confidence,evidence,created_at,created_by) "
                "VALUES(?,?,'manual',1.0,'layout-test','2026-09-20','cdp')",
                (CODE, pid))
for i, pid in enumerate(pids):
    con.execute("UPDATE photos SET taken_at=?, photo_kind='label', "
                "photo_usage='预检', time_src='exif', govern_state='done' "
                'WHERE id=?',
                ('2026-09-20 %02d:%02d:00' % (8 + i // 6, (i % 6) * 10), pid))
con.commit()
con.close()

# 2026-10-21：给 P-200 存 1 张裁剪标准图，源照片 = pids[4]（按时间倒序落在
# 前 8 张里）—— 验「只有源照片带标准图徽标，兄弟照片不乱打」。
import base64  # noqa: E402
import io  # noqa: E402
_b = io.BytesIO()
Image.new('RGB', (1000, 1000), (240, 60, 60)).save(_b, format='JPEG')
_sc, _r = _req('POST', '/api/standard-images',
               {'code': CODE, 'photo_id': pids[4], 'kind': 'product',
                'image': base64.b64encode(_b.getvalue()).decode('ascii'),
                'width': 1000, 'height': 1000})
chk('0d 存 1 张裁剪标准图（源=第5张）',
    _sc == 200 and bool((_r or {}).get('id')), '%s %s' % (_sc, _r))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
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
                  {'width': 1440, 'height': 900, 'deviceScaleFactor': 1,
                   'mobile': False})
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(5.0)
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

        async def click_sel(sel):
            box = await js("""(function(){const e=document.querySelector('%s');
                if(!e) return null; const r=e.getBoundingClientRect();
                return JSON.stringify({x:r.left+r.width/2, y:r.top+r.height/2});})()""" % sel)
            if not box or not isinstance(box, str) or not box.startswith('{'):
                return False
            b = json.loads(box)
            for t in ('mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': t, 'x': b['x'], 'y': b['y'],
                           'button': 'left', 'clickCount': 1})
            return True

        ready = await js("document.querySelectorAll('.shot').length")
        chk('1a 照片网格就绪', isinstance(ready, int) and ready > 0, ready)
        await click_sel('.shot')
        for _ in range(40):
            await asyncio.sleep(0.5)
            if await js("!!document.querySelector('.dw-cols')"):
                break
        for _ in range(40):
            await asyncio.sleep(0.5)
            n = await js("document.querySelectorAll('.dw-sib').length")
            if isinstance(n, int) and n > 0:
                break
        await asyncio.sleep(1.0)

        # 3z 标准图徽标只标源照片（2026-10-21 老板反馈修复）
        #    Vue 卡里没有 data-pid，从 img src /thumb/<id> 反解照片 id。
        r = await js("""(()=>{
          const cards=[...document.querySelectorAll('.dw-sibs .dw-sibgrid .dw-sib')];
          return JSON.stringify(cards.map(c=>{
            const m=(c.querySelector('img')||{}).src||'';
            const pid=(m.match(/\\/thumb\\/([^/?]+)/)||[])[1]||'';
            return {pid:pid, std:!!c.querySelector('.dw-sibstd')};
          }));})()""")
        rr = json.loads(r) if isinstance(r, str) and r.startswith('[') else []
        stdc = [c for c in rr if c.get('std')]
        chk('3z1 前 8 张里只有源照片带「标准图」徽标',
            len(stdc) == 1 and stdc[0].get('pid') == pids[4],
            '%s | src=%s' % (r[:220], pids[4]))
        # 展开「更早的」，折起来的块也不能乱打（模板与 head 同逻辑）
        await js("""(()=>{const h=[...document.querySelectorAll(
            '.dw-sibs .el-collapse-item__header')].pop(); if(h) h.click();})()""")
        await asyncio.sleep(1.2)
        r2 = await js("""(()=>{
          const cards=[...document.querySelectorAll('.dw-sib')];
          const all=cards.map(c=>{
            const m=(c.querySelector('img')||{}).src||'';
            const pid=(m.match(/\\/thumb\\/([^/?]+)/)||[])[1]||'';
            return {pid:pid, std:!!c.querySelector('.dw-sibstd')};
          });
          return JSON.stringify({n:all.length,
            std:all.filter(c=>c.std).map(c=>c.pid)});})()""")
        rr2 = json.loads(r2) if isinstance(r2, str) and r2.startswith('{') else {}
        chk('3z2 展开全部 11 张后仍只有源照片 1 个徽标',
            rr2.get('n') == N_LINK - 1 and rr2.get('std') == [pids[4]], r2[:220])

        # 1 首屏不滚动（Vue3 抽屉体是 .el-drawer__body）
        m = await js("""(()=>{const b=document.querySelector('.el-drawer__body');
            return JSON.stringify({sh:b.scrollHeight, ch:b.clientHeight});})()""")
        mm = json.loads(m) if isinstance(m, str) and m.startswith('{') else {}
        chk('1b 首屏不滚动', bool(mm) and mm['sh'] <= mm['ch'] + 6, m)

        # 2 关联产品置顶
        f = await js("""(()=>{const r=document.querySelector('.dw-right');
            if(!r) return 'no-right';
            const sec=r.querySelector('.dsec');
            const h4=sec?sec.querySelector('h4'):null;
            return JSON.stringify({cls:sec?sec.className:'',
              title:h4?h4.textContent.slice(0,12):'',
              hasInput:!!r.querySelector('.dw-topsec input')});})()""")
        ff = json.loads(f) if isinstance(f, str) and f.startswith('{') else {}
        chk('2a 右栏第一块是「关联产品」', '关联产品' in ff.get('title', ''), f)
        chk('2b 带 dw-topsec 底色类', 'dw-topsec' in (ff.get('cls') or ''), f)
        chk('2c 已关联的照片也有手输框', ff.get('hasInput') is True, f)

        # 3 左栏参考块：只铺 8 张
        s = await js("""(()=>{const l=document.querySelector('.dw-left');
            const sib=l?l.querySelector('.dw-sibs'):null;
            const im=l?l.querySelector('.dw-imgwrap img'):null;
            return JSON.stringify({
              inLeft: !!sib,
              shown: l?l.querySelectorAll('.dw-sibs > .dw-sibgrid .dw-sib').length:-1,
              more: !!(sib && sib.querySelector('.dw-sibmore')),
              moreTxt: (sib && sib.querySelector('.dw-sibmore .el-collapse-item__header')
                        ? sib.querySelector('.dw-sibmore .el-collapse-item__header').textContent.trim() : ''),
              imgH: im?Math.round(im.getBoundingClientRect().height):-1,
              vh: window.innerHeight});})()""")
        ss = json.loads(s) if isinstance(s, str) and s.startswith('{') else {}
        chk('3a 参考块在左栏', ss.get('inLeft') is True, s)
        chk('3b 只铺 8 张', ss.get('shown') == 8, s)
        chk('3c 有「展开更早的 N 张」', ss.get('more') is True
            and '3' in (ss.get('moreTxt') or ''), ss.get('moreTxt'))
        chk('3d 大图高度 < 视口 78%',
            0 < ss.get('imgH', -1) < ss.get('vh', 0) * 0.78, s)

        await drain()
        chk('4 全程无 JS 异常', not excs,
            str([e.get('exceptionDetails', {}).get('text', '') for e in excs])[:200])


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

print('----')
print('FAIL %d' % len(fails))
for f in fails:
    print('  - ' + f)
sys.exit(1 if fails else 0)
