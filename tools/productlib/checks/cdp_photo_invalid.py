# -*- coding: utf-8 -*-
"""CDP 实跑：无效照片标记（批量）+ 关联后自动刷新 + 抽屉左右布局（2026-10-14）。

  · 批量选择 → 标记无效 → 默认列表消失、卡片带「无效」角标；
    「仅看无效」能看到并可撤销（可逆，不删文件）；
  · 抽屉左右两栏：.dw-cols / 左图 / 右信息，高频操作（用途）在最上，
    低频识别细节默认折叠；
  · 抽屉里手输编码关联后，背后列表自动刷新（photos:changed → 卡片带「关联 1」）。

⚠️ 破坏面：自建隔离实例（临时 PL_HOME + 端口 8797 / CDP 9357），不碰 8765。
跑法：python tools/productlib/checks/cdp_photo_invalid.py
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
PORT = int(os.environ.get('PL_PORT', '8797'))
CDP_PORT = int(os.environ.get('PL_CDP', '9357'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_inval_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_inval_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

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


def post_json(path, obj, timeout=300):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf8', 'replace')
        try:
            return e.code, json.loads(body or '{}')
        except Exception:  # noqa: BLE001
            return e.code, {'raw': body[:200]}


def post_file(path, fields, files, timeout=600):
    b = '----plinval' + str(int(time.time()))
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
        body = e.read().decode('utf8', 'replace')
        try:
            return e.code, json.loads(body or '{}')
        except Exception:  # noqa: BLE001
            return e.code, {'raw': body[:200]}


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
        with urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % PORT, timeout=2) as r:
            json.loads(r.read()); break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例 8797 没起来')
    sys.exit(1)

# ── 造数据：产品 1 个 + 柜 1 个 + 照片 3 张 ──
code, r = post_json('/api/products', {'code': 'INVAL-A1', 'name': '测试品'})
pid_prod = (r or {}).get('id') or (r or {}).get('code')
code, c = post_json('/api/containers', {'container_no': 'INVAL01',
                                        'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_inval_photos')
os.makedirs(tmpd, exist_ok=True)
files = []
for i in range(3):
    p = os.path.join(tmpd, 'IV_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (50 * i, 120, 180)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 3 张照片', code == 200 and (r or {}).get('added', 0) == 3,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:200]))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
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

        # 进照片库页（导航 key = batches）
        await js("window.go && window.go('batches')")
        await asyncio.sleep(2.5)
        await drain()

        # ── ① 批量标记无效 ──
        n0 = await js("document.querySelectorAll('#shots .shot').length")
        chk('1 照片网格 3 张', n0 == 3, n0)
        await js("document.querySelector('#selBtn').click()")
        await asyncio.sleep(0.4)
        vis = await js("document.querySelector('#selBar').style.display !== 'none'")
        chk('2 批量操作条出现', vis is True, vis)
        # 勾前两张（点卡片 = 勾选）
        await js("""[...document.querySelectorAll('#shots .shot')].slice(0,2)
                     .forEach(c=>c.click())""")
        await asyncio.sleep(0.3)
        nsel = await js("document.querySelector('#selN').textContent")
        chk('3 勾选 2 张', str(nsel) == '2', nsel)
        await js("document.querySelector('#selInvalid').click()")
        # ⚠️ 轮询而不是睡死 2s：标记 POST 发那会儿服务端可能还在跑
        #    applyFlagBadges 引发的全库 cand/newprod 冷计算（纯 Python 占
        #    GIL），响应被拖过 2s 时旧列表还没刷完 —— 睡死会偶发读到 3 张。
        n1 = 3
        for _ in range(24):
            await asyncio.sleep(0.5)
            n1 = await js("document.querySelectorAll('#shots .shot').length")
            if n1 == 1:
                break
        await drain()
        chk('4 标记后默认列表剩 1 张（hide 生效）', n1 == 1, n1)
        # 仅看无效（⚠️ 必须包 IIFE：evaluate 顶层 const 会跨调用残留，
        # 第二次同名 const 直接 SyntaxError 静默失败 —— 本脚本踩过）
        await js("""(()=>{const s=document.querySelector('#fInvalid');
                     s.value='only'; s.dispatchEvent(new Event('change'));})()""")
        await asyncio.sleep(2.0)
        n2 = await js("document.querySelectorAll('#shots .shot').length")
        badge = await js("document.querySelectorAll('#shots .shot .invalb').length")
        chk('5 仅看无效：2 张带「无效」角标', n2 == 2 and badge == 2, '%s/%s' % (n2, badge))
        # 撤销（仍在选择模式：全选本页 → 取消无效）
        await js("document.querySelector('#selAll').click()")
        await asyncio.sleep(0.3)
        await js("document.querySelector('#selValid').click()")
        await asyncio.sleep(2.0)
        await js("""(()=>{const s=document.querySelector('#fInvalid');
                     s.value='hide'; s.dispatchEvent(new Event('change'));})()""")
        await asyncio.sleep(2.5)
        # 若仍不对，再补一次 change（排查竞态）；无论如何记录实况
        n3 = await js("document.querySelectorAll('#shots .shot').length")
        if n3 != 3:
            await js("""(()=>{const s=document.querySelector('#fInvalid');
                         s.value='hide'; s.dispatchEvent(new Event('change'));})()""")
            await asyncio.sleep(2.5)
            n3 = await js("document.querySelectorAll('#shots .shot').length")
        fiv = await js("document.querySelector('#fInvalid').value")
        chk('6 撤销后默认列表回到 3 张（可逆）', n3 == 3,
            'n=%s fInvalid=%s' % (n3, fiv))
        await js("document.querySelector('#selExit').click()")   # 退出选择模式
        await asyncio.sleep(1.0)

        # ── ③ 抽屉左右布局 ──
        ncards = await js("document.querySelectorAll('#shots .shot').length")
        await js("document.querySelector('#shots .shot').click()")
        await asyncio.sleep(2.5)
        await drain()
        dbg_on = await js("document.querySelector('#drawer').classList.contains('on')")
        dbg_body = await js("(document.querySelector('#dwBody').innerHTML||'').slice(0,120)")
        cols = await js("!!document.querySelector('#drawer .dw-cols')")
        left_img = await js("!!document.querySelector('#drawer .dw-left #dwImg')")
        right_usage = await js("""(()=>{const r=document.querySelector('#drawer .dw-right');
            if(!r) return false; return !!r.querySelector('#dwUsage');})()""")
        top_first = await js("""(()=>{const r=document.querySelector('#drawer .dw-right');
            if(!r) return ''; const f=r.firstElementChild;
            return (f && f.querySelector('#dwInvalid')) ? 'actions-first'
                   : (f && f.querySelector('#dwUsage')) ? 'usage-first'
                   : (f ? (f.id||f.className) : '');})()""")
        folded = await js("!!document.querySelector('#drawer details.dw-more')"
                          " && !document.querySelector('#drawer details.dw-more[open]')")
        sticky = await js("""getComputedStyle(document.querySelector('#drawer .dw-left'))
            .position === 'sticky'""")
        chk('7 抽屉两栏结构 .dw-cols', cols is True,
            'on=%s cards=%s body=%r' % (dbg_on, ncards, dbg_body))
        chk('8 左栏是大图', left_img is True)
        chk('9 右栏含用途选择（高频操作）', right_usage is True, top_first)
        # 2026-10-15 需求1/4 起右栏顶部是「标无效 / 重新识别」按钮行
        # （详情页就地操作），用途行紧随其后 —— 断言跟着改成 actions-first
        chk('10 右栏第一个元素 = 操作按钮行（置顶）', top_first == 'actions-first', top_first)
        chk('11 识别细节默认折叠', folded is True)
        chk('12 左栏 sticky（右栏滚动图不动）', sticky is True)
        # 关抽屉
        await js("document.querySelector('#dwClose').click()")
        await asyncio.sleep(0.5)

        # ── ② 关联确认后自动刷新 ──
        before = await js("""[...document.querySelectorAll('#shots .shot .meta')]
            .some(e=>e.textContent.includes('关联'))""")
        pid1 = await js("document.querySelector('#shots .shot').dataset.id")
        chk('13 关联前卡片无「关联 N」', before is False, before)
        # 打开抽屉手输编码关联
        await js("document.querySelector('#shots .shot').click()")
        await asyncio.sleep(2.0)
        await js("""(()=>{const i=document.querySelector('#dwCode');
            if(!i) return; i.value='INVAL-A1';
            document.querySelector('#dwLink').click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        linked_ui = await js("""[...document.querySelectorAll('#shots .shot .meta')]
            .some(e=>e.textContent.includes('关联'))""")
        chk('14 关联后背后列表自动刷新（卡片带「关联」）', linked_ui is True)
        # 后端口径核对：该照片 nlink=1
        d = http_json('/api/photos?container_id=%s&limit=10' % cid) or {}
        it = next((x for x in d.get('items') or [] if x['id'] == pid1), {})
        chk('15 后端 nlink=1（前后一致）', it.get('nlink') == 1, it.get('nlink'))

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('16 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:300] if bad else ''))
    return not bad


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
