# -*- coding: utf-8 -*-
"""CDP 实跑：④选图的「监装照片」区块真的渲染、能点、能恢复自动（2026-10-11）。

老板反馈「选图时没看到监装的照片」—— 以前柜况④/卡车⑦全在报告里自动取，
界面上根本看不见。本检查证明：
  · #wSupBox 分组渲染（空柜/柜侧/封条/锁门/卡车头，缩略图 + 「自动」徽标）；
  · 点柜况一张 → ✓④ 徽标 + localStorage 落盘（按柜隔离的 wizPicksSup key）；
  · 点卡车一张 → ✓⑦；
  · 「恢复自动」→ key 清掉、回到自动（不点 = 后端自动取图的语义）；
  · 新端点 /api/containers/{cid}/supervision-photos 的分组与 UI 一致；
  · 带 picks={'trucks':[...]} 生成报告 → ⑦ 只出人工指定的那张；
  · 全程无 JS 异常（新增 loadSupPhotos/renderSup 调用链只有实跑才炸）。

⚠️ 破坏面：自建隔离实例（临时 PL_HOME + 独立端口 8796 / CDP 9356），
   不碰老板的 8765。

跑法：python tools/productlib/checks/cdp_sup_picks.py
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
import urllib.error

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8796'))
CDP_PORT = int(os.environ.get('PL_CDP', '9356'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_suppicks_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_suppicks_db')
URL = 'http://127.0.0.1:%d/' % PORT
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
        return r.status, json.loads(r.read().decode('utf-8'))


def _err_body(e):
    try:
        return e.read().decode('utf8')[:300]
    except Exception:  # noqa: BLE001
        return str(e)


def patch_json(path, obj, timeout=600):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'},
                                 method='PATCH')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise RuntimeError('PATCH %s -> %s: %s' % (path, e.code, _err_body(e)))


def post_file(path, fields, files, timeout=900):
    b = '----plsup' + str(int(time.time()))
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
# 等服务就绪（冷启动要 import onnxruntime/cv2，固定睡 6 秒在慢机器上不够 ——
# 实测过 connection refused 直接炸在造数据第一步）
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % PORT, timeout=2) as r:
            json.loads(r.read()); break
    except Exception:
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例 8796 没起来')
    sys.exit(1)

# ── 造数据：建柜 → 导清单（④不被②挡）→ 传 5 张监装照并打标 ──
code, c = post_json('/api/containers', {'container_no': 'SUPPICKS01',
                                        'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), c if not isinstance(c, dict) else c.get('container_no'))
if not cid:
    srv.terminate()
    sys.exit(1)

code, r = post_file('/api/products/import', {'container_id': cid},
                    [('file', XLSX, os.path.basename(XLSX))])
chk('0 导入真实清单（④ 不被②挡）', code == 200 and (r or {}).get('snap_rows', 0) > 20,
    (r or {}).get('snap_rows'))

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_suppicks_photos')
os.makedirs(tmpd, exist_ok=True)
tag = time.strftime('%m%d%H%M%S')
# 2026-10-18：empty_container 给两张（测细类多选），共 7 张
files = []
for i in range(7):
    p = os.path.join(tmpd, 'SU_%s_%02d.jpg' % (tag, i))
    Image.new('RGB', (1200, 900), (40 * i, 80, 220 - 20 * i)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 7 张照片', code == 200 and (r or {}).get('added', 0) == 7,
    (r or {}).get('added'))

ph = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
items = ph.get('items') or []
chk('0 照片可查', len(items) == 7, len(items))
# 0-1 = empty_container 两张（多选用例），2-4 = 柜况其余三类，5-6 = 卡车头
TAGS = ['empty_container', 'empty_container', 'container_side',
        'container_seal', 'container_lock', 'truck_head', 'truck_head']
for it, tg in zip(items, TAGS):
    patch_json('/api/photos/%s/usage' % it['id'], {'usage': '监装', 'by': 'cdp'})
    post_json('/api/photos/supervision-tag', {'photo_ids': [it['id']],
                                              'tag': tg, 'by': 'cdp'})
sup = http_json('/api/containers/%s/supervision-photos' % cid) or {}
chk('0b 新端点分组 = 7 组、共 7 张', len(sup.get('groups') or []) == 7
    and sup.get('total') == 7, sup.get('total'))
cond_items = next((g['items'] for g in sup.get('groups') or []
                   if g['tag'] == 'empty_container'), [])
chk('0c empty_container 组有 2 张候选（多选用例）', len(cond_items) == 2,
    len(cond_items))

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

        await js("window.enterWizard(%r, 'picks')" % cid)
        await asyncio.sleep(3.5)
        await drain()

        # ── 2026-10-11：④分了「预检/监装」两个选项卡 —— 切到监装再断言 ──
        tab_ok = await js("""(()=>{const b=document.querySelector('#wPickTabs [data-wpt=sup]');
            if(!b) return false; b.click(); return true;})()""")
        await asyncio.sleep(1.5)
        await drain()
        chk('1b ④「监装照片」选项卡可切', tab_ok is True)

        # ── 监装照片区块渲染 ──
        has = await js("!!document.querySelector('#wSupBox')")
        chk('2 🔴 #wSupBox 渲染出来了（以前根本没有这个区块）', has is True)
        labels = await js("[...document.querySelectorAll('#wSupBox .wcai-item .code')]"
                          ".map(e=>e.textContent.trim())")
        chk('3 分组标题有「空柜」和「卡车头」（cond/truck 都在）',
            any('空柜' in (x or '') for x in (labels or []))
            and any('卡车头' in (x or '') for x in (labels or [])), labels)
        n_shots = await js("document.querySelectorAll('#wSupBox .wcai-shot').length")
        chk('4 监装缩略图 7 张（与端点 total 一致）', n_shots == 7, n_shots)
        auto_mark = await js(
            "[...document.querySelectorAll('#wSupBox .wcai-item')][0]"
            ".querySelector('.wcai-shot .rec') ?"
            " [...document.querySelectorAll('#wSupBox .wcai-item')][0]"
            ".querySelector('.wcai-shot .rec').textContent : ''")
        chk('5 柜况组第一张标「自动」（不点也是它）', auto_mark == '自动', auto_mark)

        # ── 点选：柜况换图 + 卡车进⑦ ──
        await js("document.querySelector('#wSupBox [data-kind=\"cond\"]').click()")
        await asyncio.sleep(0.8)
        await js("document.querySelector('#wSupBox [data-kind=\"truck\"]').click()")
        await asyncio.sleep(0.8)
        await drain()
        stored = await js("localStorage.getItem('wizPicksSup:' + %r) || ''" % cid)
        st = {}
        try:
            st = json.loads(stored or '{}')
        except Exception:  # noqa: BLE001
            pass
        chk('6 点选落盘（conds 有值 + trucks 有值）',
            len(st.get('conds') or {}) == 1 and len(st.get('trucks') or []) == 1,
            stored[:120])
        # ── 细类多选（2026-10-18 老板规则：不限一张）──
        await js("[...document.querySelectorAll('#wSupBox [data-kind=\"cond\"]')][1].click()")
        await asyncio.sleep(0.8)
        await drain()
        stored_m = await js("localStorage.getItem('wizPicksSup:' + %r) || ''" % cid)
        stm = {}
        try:
            stm = json.loads(stored_m or '{}')
        except Exception:  # noqa: BLE001
            pass
        chk('6m 同组再点一张：conds 该 tag 收 2 张（多选生效）',
            len((stm.get('conds') or {}).get('empty_container') or []) == 2,
            stored_m[:160])
        picks_n = await js(
            "[...document.querySelectorAll('#wizBar .wstep')]"
            ".find(e=>e.textContent.includes('选图')) ?"
            " [...document.querySelectorAll('#wizBar .wstep')]"
            ".find(e=>e.textContent.includes('选图')).textContent : ''")
        chk('7 步骤条「已选 3 张」跟着变', '已选 3' in (picks_n or ''), picks_n)

        # ── 恢复自动 ──
        await js("window.confirm = ()=>true")
        await js("(()=>{const b=document.querySelector('#wSupReset'); if(b) b.click(); return 1;})()")
        await asyncio.sleep(0.8)
        await drain()
        stored2 = await js("localStorage.getItem('wizPicksSup:' + %r)" % cid)
        n_pick = await js("document.querySelectorAll('#wSupBox .wcai-shot.pick').length")
        chk('8 恢复自动：key 清掉、无选中态',
            stored2 in (None, '') and n_pick == 0, '%r / %s' % (stored2, n_pick))

        # ── 端到端：picks.trucks 指定 → 报告 ⑦ 只出这一张 ──
        truck_pid = next((g['items'][0]['photo_id'] for g in sup['groups']
                          if g['tag'] == 'truck_head'), None)
        code, rr = post_json('/api/report/loading-docx',
                             {'container_id': cid, 'picks': {'trucks': [truck_pid]}})
        chk('9 带 picks.trucks 生成报告成功', code == 200 and (rr or {}).get('path'),
            (rr or {}).get('detail') if code != 200 else rr.get('photos'))
        if code == 200:
            chk('10 报告⑦ = 人工指定的 1 张（自动是 1 张 truck_head，指定后不变但通道已通）',
                ((rr.get('summary') or {}).get('truck_photos') == 1),
                (rr.get('summary') or {}).get('truck_photos'))

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('11 全程无 JS 异常', not bad,
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
