# -*- coding: utf-8 -*-
"""CDP 实跑：柜的**作业时长**展示（2026-10-20 老板需求），新旧两端一起验。

造两个柜把两种时间可信度都打出来：
  · CTR-A  文件名 App 采集命名 `20260927_084655_00001.jpg` + 两个时间簇
           → time_src=filename 但形态可信 → 应显示净作业时长
  · CTR-B  文件名 `PICT_0001.jpg`（无时间）→ 落到文件 mtime → 必须标「文件时刻」

断言（两端各一套）：
  1 柜列表有「作业时长」列
  2 可信柜显示起止 + 净作业时长
  3 不可信柜带警示（不能把拷贝耗时冒充作业时长）
  4 柜详情有逐段明细（起止/耗时/时间来源）
  5 全程无 JS 异常

⚠️ 隔离实例 8811 / CDP 9371，不碰 8765。
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
PORT = int(os.environ.get('PL_PORT', '8811'))
CDP_PORT = int(os.environ.get('PL_CDP', '9371'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_wd_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_wd_db')
BASE = 'http://127.0.0.1:%d' % PORT
OLD_URL = BASE + '/'
VUE_URL = BASE + '/app/containers'
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

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


def post_file(path, fields, files, timeout=600):
    b = '----wd' + str(int(time.time()))
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
tmpd = os.path.join(tempfile.gettempdir(), 'pl_wd_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)


_mkseq = [0]


def mk(fname):
    # ⚠️ 每张必须**像素不同**：入库按内容 hash 去重，同色图只会进 1 张，
    #    段数/张数断言就会假绿成「1 段 1 张」。
    _mkseq[0] += 1
    p = os.path.join(tmpd, fname)
    Image.new('RGB', (900, 1200),
              (60 + _mkseq[0] * 19, 140, 160)).save(p)
    return ('files', p, fname)


# 柜 A：App 采集命名，两个时间簇（08:46 与 10:30）→ 应该是 2 个作业段
_, ca = _req('POST', '/api/containers',
             {'container_no': 'CTR-A', 'seal_no': 'S1', 'inspector': 'cdp'})
cid_a = ca['id']
post_file('/api/photos/upload', {'container_id': cid_a},
          [mk('20260927_0846{:02d}_00001.jpg'.format(i)) for i in (0, 20, 40)]
          + [mk('20260927_1030{:02d}_00001.jpg'.format(i)) for i in (0, 25)])

# 柜 B：文件名里没有时间 → 取文件 mtime → 必须标成不可信
_, cb = _req('POST', '/api/containers',
             {'container_no': 'CTR-B', 'seal_no': 'S2', 'inspector': 'cdp'})
cid_b = cb['id']
post_file('/api/photos/upload', {'container_id': cid_b},
          [mk('PICT_%04d.jpg' % i) for i in range(3)])

lst = http_json('/api/containers') or {}
items = lst.get('items') or []
wa = next((x for x in items if x['container_no'] == 'CTR-A'), None)
wb = next((x for x in items if x['container_no'] == 'CTR-B'), None)
chk('0a 柜 A 汇总：2 段且可信', bool(wa) and wa.get('work')
    and wa['work']['segments'] == 2 and wa['work']['trusted'] is True,
    (wa or {}).get('work'))
chk('0b 柜 B 汇总：不可信', bool(wb) and wb.get('work')
    and wb['work']['trusted'] is False, (wb or {}).get('work'))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1440,900', OLD_URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def run():
    page = None
    for _ in range(40):
        lst2 = http_json('/json/list', port=CDP_PORT, retries=1, timeout=3) or []
        page = next((t for t in lst2 if t.get('type') == 'page'
                     and '127.0.0.1' in (t.get('url') or '')), None) \
            or next((t for t in lst2 if t.get('type') == 'page'), None)
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
            if not box or not isinstance(box, str) or not box.startswith('{'):
                return False
            b = json.loads(box)
            for t in ('mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': t, 'x': b['x'], 'y': b['y'],
                           'button': 'left', 'clickCount': 1})
            return True

        async def click_in_row(row_text, btn_text):
            """点某一行里的指定按钮（新端 el-table 行没有行级 id，只能按文本找）。"""
            box = await js("""(()=>{
              const tr=[...document.querySelectorAll('.el-table__body tr')]
                .find(r=>r.innerText.trim().indexOf(%s)===0);
              if(!tr) return 'no-row';
              const b=[...tr.querySelectorAll('button')]
                .find(x=>x.innerText.trim()===%s);
              if(!b) return 'no-btn';
              const r=b.getBoundingClientRect();
              return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2});})()"""
                           % (json.dumps(row_text), json.dumps(btn_text)))
            if not isinstance(box, str) or not box.startswith('{'):
                return False
            b = json.loads(box)
            for t in ('mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': t, 'x': b['x'], 'y': b['y'],
                           'button': 'left', 'clickCount': 1})
            return True

        async def old_detail(cid):
            """旧端开指定柜的详情抽屉。"""
            await click_sel('#cBody [data-c-open="%s"]' % cid)
            for _ in range(30):
                await asyncio.sleep(0.3)
                if await js("!!document.querySelector('#ctBody .wsegt')"):
                    return True
            return False

        async def vue_detail(no):
            """新端开指定柜的**详情抽屉**（不是柜号链接 —— 那走柜作业视图）。"""
            if not await click_in_row(no, '详情'):
                return False
            for _ in range(30):
                await asyncio.sleep(0.3)
                if await js("!!document.querySelector('.cd-body .el-table')"):
                    return True
            return False

        # ── 旧端 ─────────────────────────────────────────────
        await cmd('Page.navigate', {'url': OLD_URL})
        await asyncio.sleep(4.0)
        await drain()
        await js("try{localStorage.setItem('plTab','containers')}catch(e){}")
        await cmd('Page.reload')
        await asyncio.sleep(5.0)
        await drain()

        heads = await js("""(()=>{const hs=[...document.querySelectorAll('#tab-containers th')]
            .map(e=>e.textContent.trim()); return JSON.stringify(hs);})()""")
        chk('旧端 1 柜列表表头有「作业时长」',
            isinstance(heads, str) and '作业时长' in heads, heads)

        rows = await js("""(()=>{const tr=[...document.querySelectorAll('#cBody tr')];
            const out={};
            tr.forEach(r=>{const tds=[...r.querySelectorAll('td')].map(e=>e.innerText.replace(/\\s+/g,' ').trim());
                if(tds[0] && tds[0].indexOf('CTR-')===0) out[tds[0].split(' ')[0]]=tds.join(' | ');});
            return JSON.stringify(out);})()""")
        rr = json.loads(rows) if isinstance(rows, str) and rows.startswith('{') else {}
        ra = rr.get('CTR-A') or ''
        rb = rr.get('CTR-B') or ''
        chk('旧端 2a 可信柜显示起止 + 净作业时长',
            ('净作业' in ra) and ('09-27' in ra), ra[:150])
        chk('旧端 2b 段数跟着给', '2 段' in ra, ra[:150])
        chk('旧端 3 不可信柜标出「文件时刻」', '文件时刻' in rb, rb[:150])

        async def old_close():
            """关旧端详情抽屉。⚠️ 必须走 UI 点按钮：closeContainer 是 ES module
            内的函数、没挂 window，在 Runtime.evaluate 里调会抛 ReferenceError，
            抽屉根本关不掉（踩过一次）。"""
            if not await js("!!document.querySelector('#ctDrawer.on')"):
                return True
            await click_sel('#ctClose')
            for _ in range(40):
                await asyncio.sleep(0.2)
                if not await js("!!document.querySelector('#ctDrawer.on')"):
                    return True
            return False

        async def old_probe(cid):
            await old_close()
            # ⚠️ 抽屉里还留着上一柜的作业段表，等待条件会被旧内容抢先满足，
            #    抓到的是上一个柜 —— 所以关完必须确认，再开下一个。
            await asyncio.sleep(0.6)
            ok = await old_detail(cid)
            await asyncio.sleep(0.8)
            await drain()
            r = await js("""(()=>{const b=document.querySelector('#ctBody');
                if(!b) return 'no-body';
                const t=b.innerText.replace(/\\s+/g,' ');
                const ti=document.querySelector('#ctTitle');
                return JSON.stringify({title: ti?ti.textContent.trim():'',
                  hasHead:t.indexOf('作业时长')>=0,
                  rows: b.querySelectorAll('.wsegt tbody tr').length,
                  trustedTag: t.indexOf('拍摄时刻')>=0,
                  untrustedTag: t.indexOf('文件时刻')>=0,
                  snippet: t.slice(0, 240)});})()""")
            return ok, (json.loads(r) if isinstance(r, str) and r.startswith('{') else {})

        okA, dA = await old_probe(cid_a)
        chk('旧端 4a 可信柜详情有作业时长块',
            okA and dA.get('hasHead') is True, dA.get('snippet'))
        chk('旧端 4b 可信柜逐段明细 >= 2 段', (dA.get('rows') or 0) >= 2,
            dA.get('rows'))
        chk('旧端 4c 可信柜标「拍摄时刻」', dA.get('trustedTag') is True,
            dA.get('trustedTag'))
        okB, dB = await old_probe(cid_b)
        chk('旧端 4d 换柜后确实切到不可信柜',
            okB and dB.get('title') == 'CTR-B', dB.get('title'))
        chk('旧端 4e 不可信柜标「文件时刻」', dB.get('untrustedTag') is True,
            dB.get('snippet'))
        await old_close()

        # ── Vue3 新端 ────────────────────────────────────────
        await cmd('Page.navigate', {'url': VUE_URL})
        await asyncio.sleep(7.0)
        await drain()

        vh = await js("""(()=>{const hs=[...document.querySelectorAll('.el-table__header th')]
            .map(e=>e.innerText.trim()); return JSON.stringify(hs);})()""")
        chk('新端 1 柜列表表头有「作业时长」',
            isinstance(vh, str) and '作业时长' in vh, vh)

        vr = await js("""(()=>{const tr=[...document.querySelectorAll('.el-table__body tr')];
            const out={};
            tr.forEach(r=>{const tds=[...r.querySelectorAll('td')].map(e=>e.innerText.replace(/\\s+/g,' ').trim());
                if(tds[0] && tds[0].indexOf('CTR-')===0){
                    out[tds[0].split(' ')[0]]={txt:tds.join(' | '),
                      warn: r.querySelectorAll('.wt-warn').length};}});
            return JSON.stringify(out);})()""")
        vv = json.loads(vr) if isinstance(vr, str) and vr.startswith('{') else {}
        va = (vv.get('CTR-A') or {}).get('txt') or ''
        vbb = vv.get('CTR-B') or {}
        chk('新端 2a 可信柜显示起止 + 净作业时长',
            ('净作业' in va) and ('09-27' in va), va[:150])
        chk('新端 2b 段数跟着给', '2 段' in va, va[:150])
        chk('新端 3 不可信柜有警示图标', (vbb.get('warn') or 0) >= 1,
            'warn=%s txt=%s' % (vbb.get('warn'), (vbb.get('txt') or '')[:120]))

        async def vue_probe(no):
            ok = await vue_detail(no)
            await asyncio.sleep(1.0)
            await drain()
            r = await js("""(()=>{const b=document.querySelector('.cd-body');
                if(!b) return 'no-body';
                const t=b.innerText.replace(/\\s+/g,' ');
                return JSON.stringify({hasHead:t.indexOf('作业时长')>=0,
                  rows: b.querySelectorAll('.el-table__body tr').length,
                  hasFrom: t.indexOf('2026-09-27')>=0,
                  trustedTag: t.indexOf('拍摄时刻')>=0,
                  untrustedTag: t.indexOf('文件时刻')>=0,
                  snippet: t.slice(0, 240)});})()""")
            return ok, (json.loads(r) if isinstance(r, str) and r.startswith('{') else {})

        okVA, vA = await vue_probe('CTR-A')
        chk('新端 4a 可信柜详情有作业时长块',
            okVA and vA.get('hasHead') is True, vA.get('snippet'))
        chk('新端 4b 可信柜逐段明细 >= 2 段', (vA.get('rows') or 0) >= 2,
            vA.get('rows'))
        chk('新端 4c 可信柜标「拍摄时刻」', vA.get('trustedTag') is True,
            vA.get('trustedTag'))

        # 换柜：重新导航关掉抽屉（抽屉是遮罩层，盖住列表点不到第二个柜）
        await cmd('Page.navigate', {'url': VUE_URL})
        await asyncio.sleep(7.0)
        await drain()
        _, vB = await vue_probe('CTR-B')
        chk('新端 4d 不可信柜标「文件时刻」', vB.get('untrustedTag') is True,
            vB.get('snippet'))

        await drain()
        chk('5 全程无 JS 异常', not excs,
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
