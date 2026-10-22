# -*- coding: utf-8 -*-
"""CDP 实跑：照片详情页「一屏不滚动」布局改造（2026-10-20 老板需求）。

老板原话：初始内容最好一屏不用滚动；左图小一点；下面的同产品编码图片
小一点往上放、只放最近的前几个、可展开；右边的关联产品操作放到上面。

本脚本验**浏览器里真的对**（静态检查看不出滚动和遮挡）：

  1 抽屉首屏不滚动（.db scrollHeight <= clientHeight）—— 本次核心；
  2 「关联产品」是右栏第一块，且**已关联**的照片也有手输框（老 bug：
    旧版只在「还没关联」时渲染，想加第二个编码没有入口）；
  3 编码框在首屏可视区内（不用滚就能看到）；
  4 左栏大图变小（高度 < 抽屉高的 78%）；
  5 同产品编码块在**左栏**、在大图下方，且缩略图是小的（<=80px 高）；
  6 只铺最近 8 张，其余折进「展开更早的 N 张」；点开后补齐；
  7 全程无 JS 异常。

⚠️ 用真实笔记本视口 1440×900 —— 拿 2400 高的视口测「不滚动」是自欺。
⚠️ 自建隔离实例（临时 PL_HOME + 独立端口），不碰老板的 8765。
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
import urllib.error
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8797'))
CDP_PORT = int(os.environ.get('PL_CDP', '9357'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_dwlayout_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_dwlayout_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 14
N_LINK = 12          # 关联到同一编码的张数 → siblings = 11（> 8 才能测折叠）
CODE = 'P-100'

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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:300]}


def post_file(path, fields, files, timeout=600):
    b = '----pldl' + str(int(time.time()))
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

# ── 造数：1 柜 + 14 张真图，前 12 张关联到同一编码 ──
sc, cc = _req('POST', '/api/containers',
              {'container_no': 'DWLAY01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (cc or {}).get('id')
chk('0a 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_dwlayout_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'DL_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (50 + i * 12, 120, 190)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0b 上传 14 张', code == 200 and (r or {}).get('added', 0) == N_PHOTOS,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0c 取到 14 个 id', len(pids) == N_PHOTOS, len(pids))

# 时间递增 + 全部标记产品图；再补产品 + 关联前 12 张到同一编码。
# 🔴 走 sqlite 直接写：产品库没有「手工新增产品」的写接口（产品只能由
#    清单导入 / relink 产出），造数阶段直连是唯一路径（与 cdp_container_filter
#    同源），生产写路径仍然是 store.py。
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
lk = http_json('/api/photos/%s' % pids[0]) or {}
chk('0d 第 1 张已关联到 %s' % CODE,
    (lk.get('links') or [{}])[0].get('code_norm') == CODE,
    json.dumps(lk.get('links'), ensure_ascii=False)[:120])

sib_api = http_json('/api/photos/%s/panoramas' % pids[0]) or {}
chk('0e 接口 siblings == 11（> 8，才测得到折叠）',
    len(sib_api.get('siblings') or []) == N_LINK - 1,
    len(sib_api.get('siblings') or []))

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
    ok = True

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
        # 真实笔记本视口：拿超高视口验「不滚动」是假绿
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

        # ── 进照片库并打开第一张 ──
        await js("""(()=>{const b=[...document.querySelectorAll('[data-tab]')]
            .find(x=>/照片库/.test(x.textContent||'')); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await js("""(()=>{const c=document.querySelector('#grid .shot, .shot');
            if(c) c.click();})()""")
        for _ in range(30):
            await asyncio.sleep(0.5)
            if await js("!!document.querySelector('#dwBody .dw-cols')"):
                break
        # 等异步（panoramas / 同编码块 / 候选）回填
        for _ in range(40):
            await asyncio.sleep(0.5)
            n = await js("document.querySelectorAll('#dwSibs .dw-sib').length")
            if isinstance(n, int) and n > 0:
                break
        await asyncio.sleep(1.0)

        # ── 1 首屏不滚动（本次核心）──
        m = await js("""(()=>{const db=document.querySelector('#drawer .db');
            return JSON.stringify({sh:db.scrollHeight, ch:db.clientHeight});})()""")
        mm = json.loads(m) if isinstance(m, str) and m.startswith('{') else {}
        chk('1 首屏不滚动（scrollHeight <= clientHeight+4）',
            bool(mm) and mm['sh'] <= mm['ch'] + 4, m)

        # ── 2 关联产品置顶 + 已关联也有手输框 ──
        first = await js("""(()=>{const r=document.querySelector('.dw-right');
            if(!r) return 'no-right';
            const sec=r.querySelector('.dsec');
            return JSON.stringify({cls:sec?sec.className:'',
              hasCode:!!r.querySelector('#dwCode'),
              hasLinkBtn:!!r.querySelector('#dwLink'),
              title:(sec&&sec.querySelector('h4')?sec.querySelector('h4').textContent:'').slice(0,20)});})()""")
        ff = json.loads(first) if isinstance(first, str) and first.startswith('{') else {}
        chk('2a 右栏第一块是「关联产品」', '关联产品' in ff.get('title', ''), first)
        chk('2b 这块带 dw-topsec 底色类', 'dw-topsec' in (ff.get('cls') or ''), first)
        # 🔴 老 bug：已关联的照片旧版根本没有手输框
        chk('2c 已关联的照片也有手输编码框', ff.get('hasCode') is True, first)
        chk('2d 有「关联」按钮', ff.get('hasLinkBtn') is True, first)

        # ── 3 编码框在首屏可视区内 ──
        vis = await js("""(()=>{const i=document.querySelector('#dwCode');
            if(!i) return 'no-input';
            const r=i.getBoundingClientRect();
            const d=document.querySelector('#drawer').getBoundingClientRect();
            return JSON.stringify({top:Math.round(r.top), bot:Math.round(r.bottom),
              dh:Math.round(d.height), vh:window.innerHeight});})()""")
        vv = json.loads(vis) if isinstance(vis, str) and vis.startswith('{') else {}
        chk('3 编码框在首屏内（不用滚）',
            bool(vv) and 0 <= vv.get('top', -1) and vv.get('bot', 1e9) <= vv.get('vh', 0),
            vis)

        # ── 4 左栏大图变小 ──
        img = await js("""(()=>{const i=document.querySelector('#dwImg');
            if(!i) return 'no-img';
            const r=i.getBoundingClientRect();
            return JSON.stringify({h:Math.round(r.height), vh:window.innerHeight});})()""")
        ii = json.loads(img) if isinstance(img, str) and img.startswith('{') else {}
        chk('4a 大图渲染出来了', bool(ii) and ii.get('h', 0) > 100, img)
        chk('4b 大图高度 < 视口 78%（变小了）',
            bool(ii) and ii.get('h', 1e9) < ii.get('vh', 0) * 0.78, img)

        # ── 5 同编码块：在左栏、在图下方、缩略图小 ──
        sib = await js("""(()=>{const s=document.querySelector('#dwSibsSec');
            if(!s) return 'no-sibsec';
            const img=document.querySelector('#dwImg'), si=s.querySelector('.dw-sib img');
            return JSON.stringify({
              inLeft: !!s.closest('.dw-left'),
              below: img ? s.getBoundingClientRect().top > img.getBoundingClientRect().top : null,
              th: si ? Math.round(si.getBoundingClientRect().height) : -1,
              shown: document.querySelectorAll('#dwSibs > .dw-sibgrid .dw-sib').length,
              more: !!s.querySelector('.dw-sibmore'),
              moreTxt: (s.querySelector('.dw-sibmore>summary')||{}).textContent||'',
              hasTime: !!s.querySelector('.gshot-t')});})()""")
        ss = json.loads(sib) if isinstance(sib, str) and sib.startswith('{') else {}
        chk('5a 同编码块在左栏', ss.get('inLeft') is True, sib)
        chk('5b 在大图下方', ss.get('below') is True, sib)
        chk('5c 缩略图变小（<=80px 高）', 0 < ss.get('th', -1) <= 80, sib)
        chk('5d 缩略图带拍摄时间', ss.get('hasTime') is True, sib)

        # ── 6 只铺最近 8 张 + 可展开 ──
        chk('6a 首屏只铺 8 张', ss.get('shown') == 8, sib)
        chk('6b 有「展开更早的 N 张」', ss.get('more') is True
            and '3' in (ss.get('moreTxt') or ''), ss.get('moreTxt'))
        # 真实鼠标点开 summary
        box = await js("""(()=>{const s=document.querySelector(
            '#dwSibsSec .dw-sibmore>summary'); if(!s) return null;
            const r=s.getBoundingClientRect();
            return JSON.stringify({x:r.left+r.width/2, y:r.top+r.height/2});})()""")
        if box and isinstance(box, str) and box.startswith('{'):
            bb = json.loads(box)
            for t in ('mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': t, 'x': bb['x'], 'y': bb['y'],
                           'button': 'left', 'clickCount': 1})
            await asyncio.sleep(1.0)
        alln = await js("document.querySelectorAll('#dwSibs .dw-sib').length")
        chk('6c 展开后补齐 11 张', alln == N_LINK - 1, alln)

        # ── 7 展开后仍无异常；右栏「更多」默认是折叠的 ──
        more_state = await js("""(()=>{const d=document.querySelector(
            '.dw-right details.dw-more'); return d ? d.open : 'none';})()""")
        chk('7a 右栏「更多」默认折叠', more_state is False, more_state)
        await drain()
        chk('7b 全程无 JS 异常', not excs,
            str([e.get('exceptionDetails', {}).get('text', '') for e in excs])[:200])
        if excs:
            ok = False

    return ok


try:
    res = asyncio.run(main())
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
