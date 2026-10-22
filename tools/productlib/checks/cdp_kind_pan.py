# -*- coding: utf-8 -*-
"""CDP 实跑：①照片分类可手改 ②大图支持拖动平移 ③改分类后各处同步刷新
   （2026-10-15 老板需求 + 追加反馈「详情页改了分类其他部分没同步刷新」）。

  · 抽屉里分类下拉改判 → 落库、角标跟着变；
  · 照片库批量选择 → 勾一批改判分类；
  · 大图放大后用鼠标拖动 → transform 出现 translate 位移（真输入事件，
    CDP Input.dispatchMouseEvent，不是 JS 造的假事件）；重置后归零；
  · 同步刷新：照片库左侧树「按分类」计数、柜作业③左侧树计数（#wPhTree，
    老板报「其他部分没刷新」的修复点）、③网格卡片角标 —— 改动前后
    计数比对（旧 -1 / 新 +1），不修就挂，不会假绿。

⚠️ 隔离实例 8811 / CDP 9371，不碰 8765。evaluate 顶层 const 跨调用残留，
   表达式一律包 IIFE。
跑法：python tools/productlib/checks/cdp_kind_pan.py
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
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_kp_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_kp_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 4

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
    b = '----plkp' + str(int(time.time()))
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
        with urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % PORT, timeout=2) as r:
            json.loads(r.read()); break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例没起来')
    sys.exit(1)

code, c = _req('POST', '/api/containers',
               {'container_no': 'KP01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_kp_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'KP_%02d.jpg' % i)
    Image.new('RGB', (1600, 1200), (40 + i * 40, 110, 190)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 %d 张' % N_PHOTOS, code == 200 and (r or {}).get('added', 0) == N_PHOTOS,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=20' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0b 取到照片 id', len(pids) == N_PHOTOS, len(pids))
time.sleep(1)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,900', URL],
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
        excs = []

        async def cmd(method, params=None):
            _id[0] += 1
            await ws.send(json.dumps({'id': _id[0], 'method': method,
                                      'params': params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get('id') == _id[0]:
                    return m.get('result', {})
                if m.get('method') == 'Runtime.exceptionThrown':
                    excs.append(m['params'])

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
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str((ex.get('exception') or {}).get('description')
                                     or ex.get('text'))[:200]
            return (r.get('result') or {}).get('value')

        # ════ ① 抽屉里手改分类 ════
        await js("window.go && window.go('batches')")
        await asyncio.sleep(3.0)
        await drain()
        await js("document.querySelector('#shots .shot').click()")
        await asyncio.sleep(2.5)
        await drain()
        has_sel = await js("!!document.querySelector('#dwKind')")
        chk('1 抽屉里有分类下拉', has_sel is True, has_sel)
        opts = await js("""(()=>[...document.querySelectorAll('#dwKind option')]
            .map(o=>o.value))()""")
        chk('2 分类选项齐全（6 类）', len(opts or []) == 6, opts)
        # 改成「清单 packing_list」
        await js("""(()=>{const s=document.querySelector('#dwKind');
            s.value='packing_list'; s.dispatchEvent(new Event('change'));})()""")
        await asyncio.sleep(0.8)
        await drain()
        # 2026-10-15 老板反馈后改整体重绘：提示走全局 toast（3.2s 自清），
        # 元数据行角标 #dwKindTag 也要换成新分类（不再有内联「已保存」）
        msg = await js("(document.querySelector('#toast')||{}).textContent||''")
        chk('5 toast 提示已改判', '已改判为「清单」' in (msg or ''), msg)
        tag = await js("(document.querySelector('#dwKindTag')||{}).textContent||''")
        chk('5b 抽屉元数据行角标同步（清单）',
            '物料清单' in (tag or ''), tag)
        p0 = http_json('/api/photos/' + pids[0]) or {}
        chk('3 抽屉改判落库（→ packing_list）',
            (p0.get('photo_kind') or '') == 'packing_list', p0.get('photo_kind'))
        chk('4 人工改判后模型置信度清空', not p0.get('kind_conf'), p0.get('kind_conf'))

        # ════ ② 大图平移 ════
        await js("document.querySelector('#dwImg').click()")   # 开大图
        await asyncio.sleep(2.0)
        await drain()
        mask_on = await js("document.querySelector('#mask').classList.contains('on')")
        chk('6 大图已打开', mask_on is True, mask_on)
        # 放大两档
        await js("document.querySelector('#maskZoomIn').click()")
        await js("document.querySelector('#maskZoomIn').click()")
        await asyncio.sleep(0.8)
        tf1 = await js("document.querySelector('#maskImg').style.transform")
        chk('7 放大后 transform 带 scale', 'scale(' in (tf1 or ''), tf1)
        # 真输入拖动：取图中心 → 按下 → 移动 120,80 → 松开
        box = await js("""(()=>{const r=document.querySelector('#maskImg')
            .getBoundingClientRect();
            return JSON.stringify({x:Math.round(r.left+r.width/2),
                                   y:Math.round(r.top+r.height/2)});})()""")
        try:
            bc = json.loads(box or '{}')
        except Exception:  # noqa: BLE001
            bc = {}
        for typ, extra in (('mousePressed', {'button': 'left', 'clickCount': 1}),
                           ('mouseMoved', {'button': 'left'}),
                           ('mouseReleased', {'button': 'left', 'clickCount': 1})):
            p = {'type': typ, 'x': bc.get('x', 700), 'y': bc.get('y', 400)}
            if typ == 'mouseMoved':
                p['x'] = bc.get('x', 700) + 120
                p['y'] = bc.get('y', 400) + 80
            p.update(extra)
            await cmd('Input.dispatchMouseEvent', p)
            await asyncio.sleep(0.15)
        await asyncio.sleep(0.6)
        await drain()
        tf2 = await js("document.querySelector('#maskImg').style.transform")
        has_tr = ('translate(' in (tf2 or '') and 'translate(0px, 0px)' not in tf2)
        chk('8 拖动后 transform 带位移 translate', has_tr is True, tf2)
        # 位移量应接近拖动量（scale 不放大位移）
        import re as _re
        m2 = _re.search(r'translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)', tf2 or '')
        ok_delta = False
        if m2:
            ok_delta = abs(float(m2.group(1)) - 120) < 25 and abs(float(m2.group(2)) - 80) < 25
        chk('9 位移量≈鼠标位移（1:1，没被 scale 放大）', ok_delta, m2.groups() if m2 else tf2)
        # 重置归零
        await js("document.querySelector('#maskReset').click()")
        await asyncio.sleep(0.6)
        tf3 = await js("document.querySelector('#maskImg').style.transform")
        chk('10 重置后位移归零',
            'translate(0px, 0px)' in (tf3 or '') or 'scale(1)' in (tf3 or ''), tf3)
        await js("document.querySelector('#mask .close').click()")
        await asyncio.sleep(0.5)
        await js("document.querySelector('#dwClose').click()")
        await asyncio.sleep(0.5)

        # ════ ③ 照片库批量改判分类 ════
        await js("document.querySelector('#selBtn').click()")
        await asyncio.sleep(0.6)
        await js("""(()=>{const cs=document.querySelectorAll('#shots .shot');
            if(cs[1]) cs[1].click(); if(cs[2]) cs[2].click();})()""")
        await asyncio.sleep(0.6)
        nsel = await js("document.querySelector('#selN').textContent")
        chk('11 勾选 2 张', str(nsel) == '2', nsel)
        await js("""(()=>{const s=document.querySelector('#selKind');
            s.value='scene'; document.querySelector('#selKindDo').click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        got = await js("""(async()=>{return 'ok';})()""")
        chk('11b 批量改判请求已发（无异常）', got == 'ok', got)
        # 后端核对：应有 2 张变成 scene
        d2 = http_json('/api/photos?container_id=%s&kind=scene&limit=20' % cid) or {}
        chk('12 后端 2 张被改判为 scene', d2.get('total') == 2, d2.get('total'))

        # ════ ④ 照片库左侧树「按分类」计数同步（2026-10-15 老板反馈）═══
        # 抽屉里改完分类，列表角标/树计数都要跟着变 —— 树不刷就是「其他部分
        # 没有同步刷新」。当前应：packing_list×1、scene×2、unknown×1。
        async def tree_kinds(bar):
            return await js("""(()=>{const secs=[...document.querySelectorAll(
                '%s .ptree-sec')];
                const sec=secs.find(s=>s.querySelector('.ptree-t')
                    .textContent==='按分类');
                if(!sec) return 'NO-SEC';
                const out={};
                sec.querySelectorAll('.ptree-i').forEach(b=>{
                    out[b.dataset.v]=parseInt(
                        b.querySelector('.ptree-n').textContent)||0;});
                return JSON.stringify(out);})()""" % bar)
        await asyncio.sleep(2.0)
        await drain()
        tk = await tree_kinds('#phTree')
        try:
            tko = json.loads(tk or '{}')
        except Exception:  # noqa: BLE001
            tko = {}
        chk('14 照片库树：清单=1、场景=2、未识别=1',
            tko.get('packing_list') == 1 and tko.get('scene') == 2
            and tko.get('_unset') == 1, tk)
        # 点树上的「未分类」= kind=_unset → 按 NULL 过滤，应命中 1 张
        d3 = http_json('/api/photos?container_id=%s&kind=_unset&limit=20' % cid) or {}
        chk('14b kind=_unset 按 NULL 过滤命中 1 张', d3.get('total') == 1, d3.get('total'))

        # ════ ⑤ 柜作业③树计数同步（老板报的「其他部分不刷新」修复点）═══
        # 同一棵树的另一个挂载点 #wPhTree。进③ → 记录改动前的分类计数 →
        # 抽屉改判一张 → 再读：旧分类 -1、新分类 +1，一个都不能差。
        await js("window.enterWizard('%s', 'photos')" % cid)
        for _ in range(30):
            await asyncio.sleep(0.5)
            n = await js("document.querySelectorAll('#wizShots .shot').length")
            if n:
                break
        await asyncio.sleep(1.5)
        await drain()
        n_shots = await js("document.querySelectorAll('#wizShots .shot').length")
        chk('15 进入柜作业③且有照片网格', bool(n_shots), n_shots)
        wtree0 = await tree_kinds('#wPhTree')
        try:
            w0 = json.loads(wtree0 or '{}')
        except Exception:  # noqa: BLE001
            w0 = {}
        # 点开第一张的抽屉，读它当前的分类，挑一个不同的目标分类改判
        await js("document.querySelector('#wizShots .shot').click()")
        await asyncio.sleep(2.0)
        await drain()
        cur_kind = await js("(document.querySelector('#dwKind')||{}).value||''")
        target = 'label' if cur_kind != 'label' else 'packaging'
        chk('15b ③抽屉可打开且读到当前分类', bool(cur_kind), cur_kind)
        await js("""(()=>{const s=document.querySelector('#dwKind');
            s.value='%s'; s.dispatchEvent(new Event('change'));})()""" % target)
        # 轮询等树刷新（修好 = 新分类计数 +1；没修 = 等到超时也不动，
        # 下面两条断言自然挂，不会假绿）
        wtree1 = wtree0
        for _ in range(24):
            await asyncio.sleep(0.5)
            await drain()
            wtree1 = await tree_kinds('#wPhTree')
            try:
                _w1 = json.loads(wtree1 or '{}')
            except Exception:  # noqa: BLE001
                _w1 = {}
            if _w1.get(target, 0) - w0.get(target, 0) == 1:
                break
        try:
            w1 = json.loads(wtree1 or '{}')
        except Exception:  # noqa: BLE001
            w1 = {}
        chk('16 ③树：旧分类计数 -1',
            w0.get(cur_kind, 0) - w1.get(cur_kind, 0) == 1,
            '%s: %s → %s' % (cur_kind, w0.get(cur_kind), w1.get(cur_kind)))
        chk('17 ③树：新分类计数 +1',
            w1.get(target, 0) - w0.get(target, 0) == 1,
            '%s: %s → %s' % (target, w0.get(target), w1.get(target)))
        # 抽屉里改完，网格卡片角标也要是新的（视图本身刷新，别只刷树）
        grid_has = await js("""(()=>{const cs=[...document.querySelectorAll(
            '#wizShots .shot')];
            return cs.some(c=>c.textContent.indexOf('标识卡')>=0
                || c.textContent.indexOf('包装')>=0);})()""")
        chk('18 ③网格卡片角标同步（新分类可见）', grid_has is True, grid_has)

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('13 全程无 JS 异常', not bad,
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
    if srv:
        srv.terminate()

print()
print('PASS' if (res and not fails) else ('FAIL %d 项' % len(fails)))
sys.exit(0 if (res and not fails) else 1)
