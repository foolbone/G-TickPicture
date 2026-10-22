# -*- coding: utf-8 -*-
"""CDP 实跑：④选图的柜级统计条真的渲染出来、数字与后端同源（2026-10-10）。

静态三检（esm_syntax / web_contract / esm_graph）证明不了这些：
  · 新增的 .wpstat 统计条是否真的出现在④里（不是写了没渲染）；
  · 数字是否取自后端 steps.picks.stats（而不是前端另算一套）；
  · 「已采用」那一格会不会在采用后跟着变（_updPickStat 有没有接上）；
  · 有没有 ESM/运行时异常（新增函数调用链只有实跑才炸）。

🔴 判据用「UI 上的数字 == /api 的 stats」，不写死期望值 ——
   写死就变成「两边各自对同一个常量」，抓不到漂移（铁律 23）。
⚠️ 破坏面：自建隔离实例（临时 PL_HOME + 独立端口 8795 / CDP 9355），
   不碰老板的 8765。

跑法：python tools/productlib/checks/cdp_picks_stats.py
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
PORT = int(os.environ.get('PL_PORT', '8795'))
CDP_PORT = int(os.environ.get('PL_CDP', '9355'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_picksstats_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_picksstats_db')
# 指向**已跑起来的服务**（打包版 exe）时不自起源码服务，其余断言照跑 ——
# 同一套判据既能验源码也能验绿包，不写两份。PORT 也要指到那个端口（造数据用）。
EXT = os.environ.get('PL_EXT_URL', '').strip() or None
URL = EXT or ('http://127.0.0.1:%d/' % PORT)
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
XLSX = os.path.join(REPO, '9.13 5x40HQ', 'MIEU2012616.xlsx')

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


def post_json(path, obj, timeout=600):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf8'))


def post_file(path, fields, files, timeout=900):
    b = '----plpicks' + str(int(time.time()))
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
        return r.status, json.loads(r.read().decode('utf8'))


shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.makedirs(DBHOME, exist_ok=True)

srv = None
if not EXT:
    srv = subprocess.Popen(
        [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
        env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)

# ── 造数据：建柜 → 导真实清单 → 传照片 → 关联若干 ──
CNO = 'PICKS10001'
code, c = post_json('/api/containers', {'container_no': CNO, 'seal_no': 'S1',
                                        'inspector': 'cdp', 'client_name': 'ACME',
                                        'location': 'Changsha'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), c if not isinstance(c, dict) else c.get('container_no'))
if not cid:
    if srv: srv.terminate()
    sys.exit(1)

code, r = post_file('/api/products/import', {'container_id': cid},
                    [('file', XLSX, os.path.basename(XLSX))])
chk('0 导入真实清单', code == 200 and (r or {}).get('snap_rows', 0) > 20,
    (r or {}).get('snap_rows'))

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_picksstats_photos')
os.makedirs(tmpd, exist_ok=True)
tag = time.strftime('%m%d%H%M%S')
files = []
for i in range(6):
    p = os.path.join(tmpd, 'PS_%s_%02d.jpg' % (tag, i))
    Image.new('RGB', (1200, 900), (40 * i, 80, 220 - 20 * i)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 6 张照片', code == 200 and (r or {}).get('added', 0) == 6,
    (r or {}).get('added'))

ph = http_json('/api/photos?container_id=%s&limit=50' % cid)
items = (ph or {}).get('items') or []
pl = http_json('/api/products?limit=200') or {}
allp = pl.get('items') or []
# 前 4 个产品关联到第一张照片 —— 制造「命中」样本
nlink = 0
for row in allp[:4]:
    try:
        sc, _ = post_json('/api/links', {'code': row.get('code') or row.get('code_norm'),
                                         'photo_id': items[0]['id'], 'by': 'cdp'})
        nlink += (1 if sc == 200 else 0)
    except Exception:  # noqa: BLE001
        pass
chk('0 造出 4 条人工关联', nlink == 4, nlink)

stats = (http_json('/api/containers/%s/progress' % cid) or {}).get('steps', {}) \
        .get('picks', {}).get('stats')
chk('0 后端下发 picks.stats', bool(stats) and stats.get('codes_total', 0) > 0, stats)
if not stats:
    if srv: srv.terminate()
    sys.exit(1)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    ok = True
    if not http_json('/json/version', port=CDP_PORT, retries=40, timeout=3):
        print('[FAIL] 调试端口未就绪'); return False
    page = next((t for t in (http_json('/json/list', port=CDP_PORT) or [])
                 if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page'); return False

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
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(4.5)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        chk('1 前置闸门：页面已加载',
            await js("!!document.querySelector('nav')") is True)

        # ── 进柜作业 → ④选图 ──
        await js("window.enterWizard(%r, 'picks')" % cid)
        await asyncio.sleep(3.5)
        await drain()
        wiz = await js("""(()=>{const w=document.querySelector('#ctWizView');
            return w? w.style.display : '';})()""")
        chk('2 进到柜作业视图', wiz != 'none', wiz)
        cur = await js("(()=>{const e=document.querySelector('.wcard-h b'); return e?e.textContent.trim():'';})()")
        chk('3 当前卡片是④选图', '选图' in (cur or ''), cur)

        # ── 统计条渲染 ──
        has = await js("!!document.querySelector('.wpstat')")
        chk('4 🔴 统计条 .wpstat 渲染出来了', has is True)
        # 老板 10-11：次要指标默认收进「其他指标」，展开后再断言全量数字
        await js("(()=>{const b=document.querySelector('#wStatMoreBtn'); if(b) b.click(); return 1;})()")
        await asyncio.sleep(0.5)
        txt = await js("(()=>{const e=document.querySelector('.wpstat'); return e? e.innerText:'';})()")
        cells = await js("[...document.querySelectorAll('.wpstat-c')].map(e=>e.innerText.replace(/\\s+/g,' ').trim())")
        chk('5 统计条有 8 个数字格（4 编码 + 4 照片维度）', len(cells or []) == 8, cells)

        # ── 数字与后端同源（不写死期望值）──
        def has_num(s, n):
            return str(n) in (s or '')
        chk('6 清单编码数与后端一致', has_num(txt, stats['codes_total']),
            '%s | %s' % (stats['codes_total'], (txt or '')[:60].replace('\n', ' ')))
        chk('7 命中数与后端一致', has_num(txt, stats['with_photo']), stats['with_photo'])
        chk('8 缺口数与后端一致', has_num(txt, stats['missing']), stats['missing'])
        chk('9 命中占比与后端一致', ('%s%%' % stats['hit_rate']) in (txt or ''),
            stats['hit_rate'])
        chk('10 本柜照片数一致', has_num(txt, stats['photo_total']), stats['photo_total'])
        chk('11 已关联照片数一致', has_num(txt, stats['photo_linked']), stats['photo_linked'])
        chk('12 标准图数一致', has_num(txt, stats['std_photos']), stats['std_photos'])

        # ── 「已采用」格初始为 0 ──
        adopt0 = await js("(()=>{const e=document.querySelector('#wPickStatAdopt'); return e? e.innerText.replace(/\\s+/g,' ').trim():'';})()")
        chk('13 「已采用」格存在且初始 0', adopt0 and adopt0.startswith('0'), adopt0)

        # ── 检索 → 采用一张 → 已采用格要跟着变 ──
        # 2026-10-11：载入/检索已全自动（进④即跑），不再有 #wLoadCodes/#wLookup2 按钮
        await asyncio.sleep(6.0)
        await drain()
        shots = await js("document.querySelectorAll('.wcai-shot').length")
        chk('14 检索出候选缩略图', (shots or 0) > 0, shots)
        if shots:
            await js("document.querySelector('.wcai-shot').click()")
            await asyncio.sleep(1.5)
            await drain()
            adopt1 = await js("(()=>{const e=document.querySelector('#wPickStatAdopt'); return e? e.innerText.replace(/\\s+/g,' ').trim():'';})()")
            chk('15 🔴 采用一张后「已采用」格跟着变',
                adopt1 and not adopt1.startswith('0'), '%s -> %s' % (adopt0, adopt1))

        # ── 无 JS 异常 ──
        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('16 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:300] if bad else ''))
        if bad:
            ok = False
    return ok


try:
    res = asyncio.run(main())
except Exception as e:  # noqa: BLE001
    print('[FAIL] 脚本异常：%s' % e)
    res = False
finally:
    try:
        edge.terminate()
    except Exception:  # noqa: BLE001
        pass
    if srv: srv.terminate()

print()
print('PASS' if (res and not fails) else ('FAIL %d 项' % len(fails)))
sys.exit(0 if (res and not fails) else 1)
