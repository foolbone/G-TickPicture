# -*- coding: utf-8 -*-
"""CDP 实跑：左侧树「用途/分类」**多选**（2026-10-19 老板报「多选框只能选一个」）。

病根：photo_facet_counts 拿同一份 WHERE 同时 GROUP BY 用途和分类 —— 选了
分类 A 之后，分类分布里只剩 A 一项，树上其他分类**直接消失**，用户物理上
点不到第二个。store 层已由 _diag_facet_multi.py（21 项）钉死，本脚本只验
**浏览器里真的能多选**：

  1 选了第一个分类后，分类段**仍列出全部分类**（可继续加选）—— 病根断言；
  2 再点第二个 → 两项同时高亮，列表条数 == 两项之和；
  3 段标题出现「已选 N」与「清空」，点清空回到全量 —— 多选的反操作；
  4 用途段同样能多选（监装 + 预检 == 全量）；
  5 柜作业③同一棵树同样能多选（两处共用 loadPhotoTree）；
  6 全程无 JS 异常。

⚠️ 铁律（2026-10-19 cdp_code_suggest 的教训）：
   · `el.click()` 是**假绿**——必须 Input.dispatchMouseEvent 走真实事件序列；
   · headless 的 --window-size 不生效（实测视口约 500px，元素坐标会飘出
     视口）→ 一律 Emulation.setDeviceMetricsOverride 固定 1600×2400；
   · evaluate 顶层 const 跨调用残留 → 表达式一律包 IIFE。
   · 打隔离端口，绝不碰老板的 8765。

跑法：python tools/productlib/checks/cdp_tree_multi.py
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
PORT = int(os.environ.get('PL_PORT', '8821'))
CDP_PORT = int(os.environ.get('PL_CDP', '9381'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_treemulti_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_treemulti_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

# 12 张：分类 label 5 / scene 3 / carton 4；用途 预检 7 / 监装 5
KIND_PLAN = {'label': 5, 'scene': 3, 'carton': 4}
USAGE_PLAN = {'预检': 7, '监装': 5}
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
    b = '----pltm' + str(int(time.time()))
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

# ── 造数：1 柜 + 12 张真图，再按计划铺 kind / usage ──
code, c = _req('POST', '/api/containers',
               {'container_no': 'MULTI01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0a 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_treemulti_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'TM_%02d.jpg' % i)
    Image.new('RGB', (900, 700), (60 + i * 15, 120, 190)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0b 上传 12 张', code == 200 and (r or {}).get('added', 0) == N_PHOTOS,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0c 取到 12 个照片 id', len(pids) == N_PHOTOS, len(pids))

_db = os.path.join(DBHOME, 'productlib.db')
con = sqlite3.connect(_db)
i = 0
for kind, n in KIND_PLAN.items():
    for _ in range(n):
        con.execute('UPDATE photos SET photo_kind=? WHERE id=?', (kind, pids[i]))
        i += 1
i = 0
for usage, n in USAGE_PLAN.items():
    for _ in range(n):
        con.execute('UPDATE photos SET photo_usage=? WHERE id=?', (usage, pids[i]))
        i += 1
con.execute("UPDATE photos SET govern_state='done'")
con.commit()
con.close()

# API 层先钉死：多选 == 单选之和（UI 断言之前，避免前端问题掩盖后端）
one = http_json('/api/photos?container_id=%s&kind=label&limit=50' % cid) or {}
two = http_json('/api/photos?container_id=%s&kind=label,scene&limit=50' % cid) or {}
one_sc = http_json('/api/photos?container_id=%s&kind=scene&limit=50' % cid) or {}
chk('0d API 多选 label+scene == 5+3',
    two.get('total') == one.get('total') + one_sc.get('total') == 8,
    '%s+%s=%s' % (one.get('total'), one_sc.get('total'), two.get('total')))
fac = http_json('/api/photos/facets?container_id=%s&kind=label,scene' % cid) or {}
chk('0e API facets：选了两项后分类分布仍是全量 3 项',
    len(fac.get('kind') or {}) == 3, fac.get('kind'))

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
        # 🔴 headless 的 --window-size 不生效 → 显式固定视口，否则元素坐标
        #    飘出视口，真实鼠标事件点到空气里（2026-10-19 老坑）
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1600, 'height': 2400, 'deviceScaleFactor': 1,
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

        async def click(bar, v):
            """真实鼠标点树上 data-v=v 的项（不用 el.click() —— 假绿）。"""
            box = await js(
                "(function(){const b=[...document.querySelectorAll('%s .ptree-i')]"
                ".find(x=>x.dataset.v===%r); if(!b) return null;"
                "b.scrollIntoView({block:'center'});"
                "const r=b.getBoundingClientRect();"
                "return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2});})()"
                % (bar, v))
            if not box or box.startswith('EXC'):
                return False, box
            p = json.loads(box)
            x, y = p['x'], p['y']
            if y < 0 or y > 2400 or x < 0 or x > 1600:
                return False, 'out of viewport %s' % p
            for typ in ('mouseMoved', 'mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': typ, 'x': x, 'y': y,
                           'button': 'left' if typ != 'mouseMoved' else 'none',
                           'clickCount': 1})
            return True, p

        async def click_clr(bar):
            box = await js(
                "(function(){const b=document.querySelector('%s .ptree-clr');"
                " if(!b) return null; const r=b.getBoundingClientRect();"
                "return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2});})()"
                % bar)
            if not box:
                return False, 'no clear button'
            p = json.loads(box)
            for typ in ('mouseMoved', 'mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': typ, 'x': p['x'], 'y': p['y'],
                           'button': 'left' if typ != 'mouseMoved' else 'none',
                           'clickCount': 1})
            return True, p

        async def wait_shots(box, val, tries=40):
            for _ in range(tries):
                await asyncio.sleep(0.5)
                n = await js("document.querySelectorAll('%s .shot').length" % box)
                if n == val:
                    return n
            return await js("document.querySelectorAll('%s .shot').length" % box)

        # ════ ① 照片库页：分类多选 ════
        await js("window.go && window.go('batches')")
        await asyncio.sleep(3.0)
        await drain()
        ready = await js("""(()=>{const t=document.querySelector('#phTree');
            return t ? t.querySelectorAll('.ptree-i').length : 0;})()""")
        chk('1 照片库树已渲染', isinstance(ready, int) and ready >= 5, ready)

        kinds0 = await js("""(()=>{const s=[...document.querySelectorAll(
            '#phTree .ptree-sec')].find(x=>x.dataset.sec==='kind');
            return JSON.stringify([...s.querySelectorAll('.ptree-i')]
              .map(b=>b.dataset.v));})()""")
        chk('2 分类段列出全部 3 类',
            sorted(json.loads(kinds0 or '[]')) == ['carton', 'label', 'scene'],
            kinds0)
        n0 = await wait_shots('#shots', 12, tries=10)
        chk('2b 初始 12 张', n0 == 12, n0)

        ok, info = await click('#phTree', 'label')
        chk('3 真实鼠标点到 label', ok is True, info)
        n1 = await wait_shots('#shots', 5)
        chk('3b 选 label → 列表 5 张', n1 == 5, n1)

        # 🔴 病根断言：选了 label 之后，其他分类必须还在（否则点不到第二个）
        kinds1 = await js("""(()=>{const s=[...document.querySelectorAll(
            '#phTree .ptree-sec')].find(x=>x.dataset.sec==='kind');
            return JSON.stringify([...s.querySelectorAll('.ptree-i')]
              .map(b=>b.dataset.v));})()""")
        chk('4 选了 label 后分类段仍是 3 项（能继续加选 🔴病根）',
            sorted(json.loads(kinds1 or '[]')) == ['carton', 'label', 'scene'],
            kinds1)

        ok, info = await click('#phTree', 'scene')
        chk('5 真实鼠标点到 scene', ok is True, info)
        n2 = await wait_shots('#shots', 8)
        chk('5b 多选 label+scene → 列表 8 张（= 5+3）', n2 == 8, n2)
        on2 = await js("""(()=>{const s=[...document.querySelectorAll(
            '#phTree .ptree-sec')].find(x=>x.dataset.sec==='kind');
            return JSON.stringify([...s.querySelectorAll('.ptree-i.on')]
              .map(b=>b.dataset.v));})()""")
        chk('5c 两项同时高亮（不是互斥单选）',
            sorted(json.loads(on2 or '[]')) == ['label', 'scene'], on2)
        # 隐藏下拉**不参与**多选（树集合才是真源，下拉只是旧的单选残壳），
        # 所以它必须保持空 —— 若它被写成多值，说明又养出了第二份筛选状态。
        fk = await js("(document.querySelector('#fKind')||{}).value||''")
        chk('5d 隐藏下拉保持空（树集合才是真源，避免双真源）', fk == '', fk)
        cnt = await js("""(()=>{const s=[...document.querySelectorAll(
            '#phTree .ptree-sec')].find(x=>x.dataset.sec==='kind');
            const c=s.querySelector('.ptree-cnt');
            return c?c.textContent:'none';})()""")
        chk('5e 段标题显示已选 2', str(cnt) == '2', cnt)

        ok, info = await click_clr('#phTree')
        chk('6 点「清空」', ok is True, info)
        n3 = await wait_shots('#shots', 12)
        chk('6b 清空后回到 12 张', n3 == 12, n3)
        on0 = await js("""(()=>{const s=[...document.querySelectorAll(
            '#phTree .ptree-sec')].find(x=>x.dataset.sec==='kind');
            return s.querySelectorAll('.ptree-i.on').length;})()""")
        chk('6c 清空后无高亮', on0 == 0, on0)
        await drain()

        # ── 用途段多选（同样曾经「只能选一个」）──
        ok, info = await click('#phTree', '预检')
        chk('7 真实鼠标点到「预检」', ok is True, info)
        n4 = await wait_shots('#shots', 7)
        chk('7b 选预检 → 7 张', n4 == 7, n4)
        us1 = await js("""(()=>{const s=[...document.querySelectorAll(
            '#phTree .ptree-sec')].find(x=>x.dataset.sec==='usage');
            return JSON.stringify([...s.querySelectorAll('.ptree-i')]
              .map(b=>b.dataset.v));})()""")
        chk('7c 选了预检后用途段仍 2 项（还能加选监装）',
            sorted(json.loads(us1 or '[]')) == ['监装', '预检'], us1)
        ok, info = await click('#phTree', '监装')
        chk('8 真实鼠标点到「监装」', ok is True, info)
        n5 = await wait_shots('#shots', 12)
        chk('8b 用途多选 预检+监装 → 12 张', n5 == 12, n5)
        await click_clr('#phTree')
        await wait_shots('#shots', 12, tries=10)
        # 清用途段（清空按钮是段内的，上面点的是第一个 = 用途段？按 DOM 顺序
        # 用途段在前，所以上面清的是用途段）—— 分类段已清空，这里确认无高亮
        on_left = await js("document.querySelectorAll('#phTree .ptree-i.on').length")
        chk('8c 清完后树上没有残留高亮', on_left == 0, on_left)
        await drain()

        # ════ ② 柜作业③：同一棵树 ════
        await js("window.enterWizard(%r, 'photos')" % cid)
        has_tree = False
        for _ in range(50):
            await asyncio.sleep(0.5)
            has_tree = await js("!!document.querySelector('#wPhTree')"
                                " && document.querySelectorAll("
                                "'#wPhTree .ptree-i').length>0")
            if has_tree is True:
                break
        await drain()
        chk('9 柜作业③树已渲染', has_tree is True, has_tree)
        # 先回「全部」档（③进来时可能停在别的档）；③首屏要等缩略图/请求，
        # 固定睡眠不够 —— 轮询到列表非空，别拿半截 DOM 当基线。
        await js("""(()=>{const b=document.querySelector(
            '#wShTabs [data-ptab=""]'); if(b) b.click();})()""")
        # ③首屏要等请求/缩略图；且初始可能是**分组视图**（.gcard 而非 .shot）
        # —— 只认 .shot 会把正常的分组态读成 0（11b/11e 才是真断言）。
        # 🔴 曾挂在这里：进③时 _wTree 被重置成旧的 {usage,kind} 结构 →
        #    _wTree.kinds.length 抛 TypeError（async 里变 rejected promise，
        #    静默吞掉）→ 首屏一张不出，点了树才恢复。这里卡「进来就有照片」。
        m0 = 0
        for _ in range(40):
            await asyncio.sleep(0.5)
            m0 = await js("document.querySelectorAll('#wizShots > *').length")
            if isinstance(m0, int) and m0 > 0:
                break
        cls = await js("""(()=>{const b=document.querySelector('#wizShots');
            return b ? ([...b.children].slice(0, 3).map(x=>x.className).join('|')
                        || 'empty') : 'none';})()""")
        chk('9b ③进③就有照片（首屏不被结构 bug 吞掉）',
            isinstance(m0, int) and m0 == 12, '%s | %s' % (m0, cls))

        ok, info = await click('#wPhTree', 'label')
        chk('10 ③真实鼠标点到 label', ok is True, info)
        m1 = await wait_shots('#wizShots', 5)
        chk('10b ③选 label → 5 张', m1 == 5, m1)
        wk1 = await js("""(()=>{const s=[...document.querySelectorAll(
            '#wPhTree .ptree-sec')].find(x=>x.dataset.sec==='kind');
            return JSON.stringify([...s.querySelectorAll('.ptree-i')]
              .map(b=>b.dataset.v));})()""")
        chk('10c ③选了 label 后分类段仍 3 项（🔴病根同样适用）',
            sorted(json.loads(wk1 or '[]')) == ['carton', 'label', 'scene'], wk1)
        ok, info = await click('#wPhTree', 'carton')
        chk('11 ③再点 carton', ok is True, info)
        m2 = await wait_shots('#wizShots', 9)
        chk('11b ③多选 label+carton → 9 张（=5+4）', m2 == 9, m2)
        won = await js("""(()=>{const s=[...document.querySelectorAll(
            '#wPhTree .ptree-sec')].find(x=>x.dataset.sec==='kind');
            return JSON.stringify([...s.querySelectorAll('.ptree-i.on')]
              .map(b=>b.dataset.v));})()""")
        chk('11c ③两项同时高亮',
            sorted(json.loads(won or '[]')) == ['carton', 'label'], won)
        # 只取消其中一项 → 剩 carton 4 张（多选是集合，不是开关式单选）
        ok, info = await click('#wPhTree', 'label')
        chk('11d ③再点 label 取消它', ok is True, info)
        m3 = await wait_shots('#wizShots', 4)
        chk('11e ③取消一项后只剩 carton 4 张', m3 == 4, m3)
        await drain()

        chk('12 全程无 JS 异常', not excs,
            str([str(e)[:120] for e in excs[:2]]))
        return True


ok = asyncio.run(main())
srv.terminate()
edge.terminate()
print('\n' + ('全部通过' if (ok and not fails) else
              '失败 %d 项：%s' % (len(fails), fails)))
sys.exit(0 if (ok and not fails) else 1)
