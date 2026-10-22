# -*- coding: utf-8 -*-
"""CDP 实跑：「标准图」徽标只标真的源照片（2026-10-21 老板反馈修复）

老板反馈：「这个产品的关联编码只有一张标准图，可是图片下方同产品的其他图片
都被标上了标准图。」根因：前端按「产品有没有标准图」给同编码所有照片打徽标。
修复：逐张比 src_photo_id，只有裁剪标准图的**源照片**才打（旧版 drawer.js
同编码参考块；新版 PhotoDrawer.vue 同步）。

本脚本在隔离实例里造真图 + 真标准图，浏览器里断言：
  A 产品有 1 张裁剪标准图（源照片 = 第 2 张）→ 同编码参考块里只有那张带徽标，
    其余兄弟照片一个都不带（老板报的 bug）；
  B 产品详情页标题「N 张标准图」按裁剪+上传总数算（不被哨兵值虚高）；
  C 详情页批次网格里也只有源照片带「标」角标；
  D 只有上传标准图（无裁剪）的产品 → 任何兄弟照片都不带徽标；
  E 全程无 JS 异常。

⚠️ 自建隔离实例（临时 PL_HOME + 独立端口），不碰老板的 8765/8766。
"""
import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

os.environ['no_proxy'] = '*'

import websockets  # noqa: E402
from PIL import Image  # noqa: E402

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8795'))
CDP_PORT = int(os.environ.get('PL_CDP', '9355'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_stdbadge_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_stdbadge_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
CODE = 'STD-BADGE-1'
CODE_UP = 'STD-BADGE-2'

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def http_json(path, port=PORT, retries=60, timeout=8):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(retries):
        try:
            with op.open('http://127.0.0.1:%d%s' % (port, path), timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def _req(method, path, obj=None, timeout=180):
    data = json.dumps(obj).encode('utf8') if obj is not None else None
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:300]}


def post_file(path, fields, files, timeout=600):
    b = '----plsb' + str(int(time.time()))
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
    buf += ('--%s--\r\n' % (b,)).encode('utf8')
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=timeout) as r:
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

# ── 造数：1 柜 + 6 张真图，前 3 张关联到 CODE，后 3 张关联到 CODE_UP ──
sc, cc = _req('POST', '/api/containers',
              {'container_no': 'STDBG01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (cc or {}).get('id')
chk('0a 建柜', bool(cid), cid)

tmpd = os.path.join(tempfile.gettempdir(), 'pl_stdbadge_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(6):
    p = os.path.join(tmpd, 'SB_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (60 + i * 20, 130, 200)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0b 上传 6 张', code == 200 and (r or {}).get('added', 0) == 6,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0c 取到 6 个 id', len(pids) == 6, len(pids))

import sqlite3  # noqa: E402
db = os.path.join(DBHOME, 'productlib.db')
con = sqlite3.connect(db)
for cno in (CODE, CODE_UP):
    con.execute("INSERT OR REPLACE INTO products(code_norm,code,name,photo_count,"
                "created_at,updated_at) VALUES(?,?,?,3,'2026-10-21','2026-10-21')",
                (cno, cno, '徽章测试件'))
for pid in pids[:3]:
    con.execute('INSERT OR REPLACE INTO links(code_norm,photo_id,source,'
                "confidence,evidence,created_at,created_by) "
                "VALUES(?,?,'manual',1.0,'badge-test','2026-10-21','cdp')",
                (CODE, pid))
for pid in pids[3:]:
    con.execute('INSERT OR REPLACE INTO links(code_norm,photo_id,source,'
                "confidence,evidence,created_at,created_by) "
                "VALUES(?,?,'manual',1.0,'badge-test','2026-10-21','cdp')",
                (CODE_UP, pid))
for i, pid in enumerate(pids):
    con.execute("UPDATE photos SET taken_at=?, photo_kind='label', "
                "photo_usage='预检', time_src='exif', govern_state='done' "
                'WHERE id=?',
                ('2026-10-21 %02d:%02d:00' % (9 + i // 6, (i % 6) * 10), pid))
con.commit()
con.close()

# CODE 的裁剪标准图：源照片 = pids[1]（第 2 张）—— 只有它该带徽标
buf = io.BytesIO()
Image.new('RGB', (1000, 1000), (240, 40, 40)).save(buf, format='JPEG')
b64 = base64.b64encode(buf.getvalue()).decode('ascii')
sc2, r2 = _req('POST', '/api/standard-images',
               {'code': CODE, 'photo_id': pids[1], 'kind': 'product',
                'image': b64, 'width': 1000, 'height': 1000})
chk('0d 给 %s 存 1 张裁剪标准图（源=第2张）' % CODE,
    sc2 == 200 and bool((r2 or {}).get('id')), '%s %s' % (sc2, r2))

# CODE_UP 只上传 2 张（无裁剪）—— 任何兄弟照片都不该带徽标
up_tmp = os.path.join(tmpd, 'up1.jpg')
Image.new('RGB', (900, 900), (40, 200, 90)).save(up_tmp)
fd = {}
fb = []
with open(up_tmp, 'rb') as f:
    fb.append(('files', up_tmp, 'up1.jpg'))
sc3, r3 = post_file('/api/standard-images/upload',
                    {'code': CODE_UP, 'kind': 'product'}, fb)
chk('0e 给 %s 上传 2 张标准图（无裁剪）' % CODE_UP,
    sc3 == 200 and (r3 or {}).get('uploaded') == 1, '%s %s' % (sc3, r3))

# 接口口径先行（不等浏览器）：ids 只有源照片、count 含上传
pp = http_json('/api/products/%s/photos' % CODE) or {}
chk('1a 接口 standard_photo_ids 只含源照片（第2张）',
    pp.get('standard_photo_ids') == [pids[1]], pp.get('standard_photo_ids'))
chk('1b 接口 standard_count == 1（纯裁剪）', pp.get('standard_count') == 1,
    pp.get('standard_count'))
pu = http_json('/api/products/%s/photos' % CODE_UP) or {}
chk('1c 纯上传产品 ids=[]（哨兵不混进来）',
    pu.get('standard_photo_ids') == [], pu.get('standard_photo_ids'))
chk('1d 纯上传产品 count == 1（上传也计数）', pu.get('standard_count') == 1,
    pu.get('standard_count'))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1440,900', URL],
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
                  {'width': 1440, 'height': 900, 'deviceScaleFactor': 1,
                   'mobile': False})
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(4.5)
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

        # ── 进照片库，打开第 1 张（CODE 的兄弟照片含第 2/3 张）──
        await js("""(()=>{const b=[...document.querySelectorAll('[data-tab]')]
            .find(x=>/照片库/.test(x.textContent||'')); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await js("""(()=>{const cs=[...document.querySelectorAll('#grid .shot, .shot')];
            if(cs.length) cs[0].click();})()""")
        for _ in range(30):
            await asyncio.sleep(0.5)
            if await js("!!document.querySelector('#dwBody .dw-cols')"):
                break
        for _ in range(40):
            await asyncio.sleep(0.5)
            n = await js("document.querySelectorAll('#dwSibs .dw-sib').length")
            if isinstance(n, int) and n > 0:
                break
        await asyncio.sleep(1.2)

        # ── 2 同编码参考块：只有源照片（第2张）带徽标 ──
        r = await js("""(()=>{
          const cards=[...document.querySelectorAll('#dwSibs .dw-sib')];
          return JSON.stringify({
            total: cards.length,
            std: cards.map(c=>({pid:c.dataset.sibpid,
                                std:!!c.querySelector('.dw-sibstd')}))
          });})()""")
        rr = json.loads(r) if isinstance(r, str) and r.startswith('{') else {}
        std_cards = [c for c in (rr.get('std') or []) if c.get('std')]
        chk('2a 兄弟照片有 2 张（第2、3张）', rr.get('total') == 2, r)
        chk('2b 只有源照片带「标准图」徽标（老板报的 bug）',
            len(std_cards) == 1 and std_cards[0].get('pid') == pids[1], r)

        # ── 3 产品详情页：标题张数 + 批次网格角标 ──
        await js("""(()=>{const b=[...document.querySelectorAll('[data-tab]')]
            .find(x=>/产品库/.test(x.textContent||'')); if(b) b.click();})()""")
        await asyncio.sleep(2.0)
        await js("""(()=>{const tr=[...document.querySelectorAll('#pBody tr')]
            .find(t=>(t.dataset.code||'')==='%s'); if(tr) tr.click();})()""" % CODE)
        for _ in range(30):
            await asyncio.sleep(0.5)
            if await js("!!document.querySelector('#pShots .grid')"):
                break
        await asyncio.sleep(2.0)
        r = await js("""(()=>{
          const t=document.querySelector('#pTitle');
          const cards=[...document.querySelectorAll('#pShots .shot')];
          return JSON.stringify({
            title:(t?t.textContent:'').replace(/\\s+/g,' ').slice(0,80),
            shots: cards.length,
            std: cards.map(c=>({id:c.dataset.id, std:!!c.querySelector('.stdb')}))
          });})()""")
        rr = json.loads(r) if isinstance(r, str) and r.startswith('{') else {}
        std_cards = [c for c in (rr.get('std') or []) if c.get('std')]
        chk('3a 标题显示「1 张标准图」（哨兵不虚高）',
            '1 张标准图' in (rr.get('title') or ''), rr.get('title'))
        chk('3b 批次网格 3 张照片里只有源照片带「标」角标',
            rr.get('shots') == 3 and len(std_cards) == 1
            and std_cards[0].get('id') == pids[1], r)

        # ── 4 纯上传产品：详情页任何照片都不带角标 ──
        await js("""(()=>{const tr=[...document.querySelectorAll('#pBody tr')]
            .find(t=>(t.dataset.code||'')==='%s'); if(tr) tr.click();})()""" % CODE_UP)
        for _ in range(30):
            await asyncio.sleep(0.5)
            t = await js("(document.querySelector('#pTitle')||{}).textContent||''")
            if isinstance(t, str) and CODE_UP in t:
                break
        await asyncio.sleep(2.0)
        r = await js("""(()=>{
          const t=document.querySelector('#pTitle');
          const cards=[...document.querySelectorAll('#pShots .shot')];
          return JSON.stringify({
            title:(t?t.textContent:'').replace(/\\s+/g,' ').slice(0,80),
            shots: cards.length,
            stdn: cards.filter(c=>c.querySelector('.stdb')).length
          });})()""")
        rr = json.loads(r) if isinstance(r, str) and r.startswith('{') else {}
        chk('4a 纯上传产品标题显示「1 张标准图」',
            '1 张标准图' in (rr.get('title') or ''), rr.get('title'))
        chk('4b 纯上传产品没有任何照片带「标」角标',
            rr.get('stdn') == 0, r)

        chk('E 全程无 JS 异常', not excs,
            [ (e.get('exceptionDetails') or {}).get('text') for e in excs ][:3])


try:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
finally:
    subprocess.run(['taskkill', '/F', '/PID', str(srv.pid)],
                   capture_output=True)
    subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'],
                   capture_output=True)
    shutil.rmtree(HOME, ignore_errors=True)
    shutil.rmtree(DBHOME, ignore_errors=True)
    shutil.rmtree(tmpd, ignore_errors=True)

print('----')
print('FAIL %d' % len(fails))
if fails:
    print('FAILED: ' + '; '.join(fails))
    sys.exit(1)
print('ALL PASS')
