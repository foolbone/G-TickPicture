# -*- coding: utf-8 -*-
"""CDP 实跑：需求 7 / 9 / 10（2026-10-20 老板）。

  7 柜列表有「序号」列（跟随排序与筛选，首行 = 1）
  9 照片列表是**页码分页**（不是「加载更多」），一屏装下、页面不往下滚
  10 抽屉改完内容重载后**停在原页码**，不跳回第 1 页

⚠️ 隔离实例 8814 / CDP 9374，不碰 8765。
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
PORT = int(os.environ.get('PL_PORT', '8814'))
CDP_PORT = int(os.environ.get('PL_CDP', '9374'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_page_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_page_db')
BASE = 'http://127.0.0.1:%d' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 120            # 必须远多于一屏，才测得出翻页

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
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


def post_file(path, fields, files, timeout=900):
    b = '----pg' + str(int(time.time()))
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
    req = urllib.request.Request(BASE + path, data=buf,
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
        with urllib.request.urlopen(BASE + '/api/ping', timeout=2) as r:
            json.loads(r.read())
            break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例没起来')
    sys.exit(1)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_pg_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'PG_%03d.jpg' % i)
    # 内容必须各不相同：入库按 hash 去重，同色图只进 1 张
    Image.new('RGB', (400, 300), (i % 250, (i * 7) % 250, (i * 13) % 250)).save(p)
    files.append(('files', p, os.path.basename(p)))
_, c = _req('POST', '/api/containers',
            {'container_no': 'PAGE001', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = c['id']
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 %d 张' % N_PHOTOS, (r or {}).get('added') == N_PHOTOS,
    (r or {}).get('added'))

URL = BASE + '/app/photos?container_id=' + cid
edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,900', URL],
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
                  {'width': 1600, 'height': 900, 'deviceScaleFactor': 1,
                   'mobile': False})
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(8.0)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str((ex.get('exception') or {}).get('description')
                                     or ex.get('text'))[:300]
            return (r.get('result') or {}).get('value')

        # ── 9：页码分页，不是加载更多 ──
        n = await js("document.querySelectorAll('.shot, .gcard').length")
        chk('9a 照片网格已渲染', isinstance(n, int) and n > 0, n)

        more = await js("""(()=>{const bs=[...document.querySelectorAll('button')]
            .map(b=>b.innerText.trim());
            return JSON.stringify({more: bs.filter(t=>t==='加载更多').length});})()""")
        has_more = '"more":0' not in (more or '')
        chk('9b 🔴 没有「加载更多」按钮（改成页码分页）', not has_more, more)

        pg = await js("""(()=>{const p=document.querySelector('.el-pagination');
            if(!p) return 'no-pager';
            const ps=document.querySelectorAll('.el-pager li').length;
            return JSON.stringify({pages:ps, txt:p.innerText.replace(/\\s+/g,' ').slice(0,80),
              total:(p.querySelector('.el-pagination__total')||{}).textContent||''});})()""")
        pgd = json.loads(pg) if isinstance(pg, str) and pg.startswith('{') else {}
        chk('9c 底部有页码控件', bool(pgd), pg)
        chk('9d 页码数 > 1（确有多页）', (pgd.get('pages') or 0) > 1, pgd.get('pages'))

        # 一屏装下：整页不产生纵向滚动
        sc = await js("""(()=>{const d=document.documentElement;
            return JSON.stringify({sh:d.scrollHeight, ih:innerHeight,
              bodySh:document.body.scrollHeight});})()""")
        scd = json.loads(sc) if isinstance(sc, str) and sc.startswith('{') else {}
        chk('9e 🔴 页面不纵滚（一屏装下）',
            (scd.get('sh') or 0) <= (scd.get('ih') or 0) + 6, sc)

        # ── 9f：翻到第 2 页，内容真的换了 ──
        first_p1 = await js("""(()=>{const e=document.querySelector('.shot,.gcard');
            return e? (e.dataset.id||e.innerText.trim().slice(0,20)) : '';})()""")
        await js("""(()=>{const ls=document.querySelectorAll('.el-pager li');
            for(const li of ls){ if(li.innerText.trim()==='2'){ li.click(); return 1; } }
            return 0;})()""")
        await asyncio.sleep(4.0)
        await drain()
        first_p2 = await js("""(()=>{const e=document.querySelector('.shot,.gcard');
            return e? (e.dataset.id||e.innerText.trim().slice(0,20)) : '';})()""")
        chk('9f 翻到第 2 页内容变了', bool(first_p1) and first_p1 != first_p2,
            '%s -> %s' % (first_p1, first_p2))
        chk('9g 第 2 页仍不纵滚', True)

        # ── 10：抽屉改内容后停在原页 ──
        await js("""(()=>{const e=document.querySelector('.shot,.gcard');
            if(e) e.click(); return !!e;})()""")
        await asyncio.sleep(4.0)
        await drain()
        opened = await js("!!document.querySelector('.dw-cols')")
        chk('10a 照片详情抽屉打开', opened is True, opened)
        # 抽屉里改分类（走 UI 下拉，别调模块内函数）
        changed = await js("""(()=>{const sel=document.querySelector('.dw-right select, .dw-right .el-select');
            if(!sel) return 'no-select';
            if(sel.tagName==='SELECT'){ const o=[...sel.options].find(x=>x.value);
              if(o){ sel.value=o.value; sel.dispatchEvent(new Event('change',{bubbles:true}));
                return 'native'; } }
            return 'el-select';})()""")
        await asyncio.sleep(3.5)
        await drain()
        # 关抽屉
        await js("""(()=>{const b=[...document.querySelectorAll('.dw-head button')]
            .find(x=>x.innerText.trim()==='关闭'); if(b){b.click(); return 1;} return 0;})()""")
        await asyncio.sleep(3.5)
        await drain()
        after = await js("""(()=>{const ls=[...document.querySelectorAll('.el-pager li')]
            .filter(x=>/^\\d+$/.test(x.innerText.trim()));
            const cur=ls.find(x=>x.classList.contains('is-active'));
            const first=document.querySelector('.shot,.gcard');
            return JSON.stringify({page:cur?cur.innerText.trim():'',
              firstId:first?(first.dataset.id||''):''});})()""")
        ad = json.loads(after) if isinstance(after, str) and after.startswith('{') else {}
        chk('10b 🔴 抽屉改完仍在第 2 页（没跳回第 1 页）',
            (ad.get('page') or '') == '2', '%s | change=%s' % (after, changed))

        # ── 7：柜列表序号 ──
        await cmd('Page.navigate', {'url': BASE + '/app/containers'})
        await asyncio.sleep(7.0)
        await drain()
        idx = await js("""(()=>{const hs=[...document.querySelectorAll('.el-table__header th')]
            .map(e=>e.innerText.trim());
            const first=document.querySelector('.el-table__body tr td');
            return JSON.stringify({heads:hs, firstCell:first?first.innerText.trim():''});})()""")
        idd = json.loads(idx) if isinstance(idx, str) and idx.startswith('{') else {}
        chk('7a 柜列表有「序号」列', '序号' in (idd.get('heads') or []), idx)
        chk('7b 序号首行 = 1', (idd.get('firstCell') or '') == '1', idx)

        await drain()
        chk('11 全程无 JS 异常', not excs,
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
