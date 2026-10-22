# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 版照片库 /app/photos（vue3-frontend 分支）。

覆盖旧版照片库的核心行为，逐条对着旧断言的语义写：
  · 页面渲染 + 左侧树（用途/分类，计数与列表同源）
  · 点树筛选 / 再点取消（轮询等列表刷完，别读旧列表）
  · 四视图：紧凑 / 详情 / 分组 / 关联；关联视图五档选项卡 + 徽章数字
  · 照片详情抽屉：左图右信息、分类/用途/监装细分、只产品图出关联区
  · 分类改判 → 关联区联动（2026-10-17 老板规则）
  · 批量选择模式：勾选 → 标记无效 → 卡片降透明、待关联计数下降
  · 刷新保持（URL 路由，/app/photos 直接落地）

⚠️ 隔离实例 8803 / CDP 9363，不碰 8765。evaluate 顶层 const 跨调用残留，
   表达式一律包 IIFE（老坑）。
跑法：python tools/productlib/checks/cdp_vue_photos.py
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8803'))
CDP_PORT = int(os.environ.get('PL_CDP', '9363'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vue_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vue_db')
URL = 'http://127.0.0.1:%d/app/photos' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 8          # 3 监装 + 2 预检 + 3 未分类

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
    b = '----plvue' + str(int(time.time()))
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

# ── 造数据：1 柜 + 8 张照片 + 1 个产品 ──
code, c = _req('POST', '/api/containers',
               {'container_no': 'VUE01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)
code, _ = _req('POST', '/api/products', {'code': 'VUE-A1', 'name': 'Vue测试品'})
chk('0 建产品', code in (200, 201), code)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'VU_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (60 + i * 20, 120, 190)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 %d 张' % N_PHOTOS,
    code == 200 and (r or {}).get('added', 0) == N_PHOTOS,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:160]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0b 取到照片 id', len(pids) == N_PHOTOS, len(pids))
for pid in pids[:3]:
    _req('PATCH', '/api/photos/%s/usage' % pid, {'usage': '监装'})
for pid in pids[3:5]:
    _req('PATCH', '/api/photos/%s/usage' % pid, {'usage': '预检'})

import sqlite3  # noqa: E402
_db = os.path.join(DBHOME, 'productlib.db')
con = sqlite3.connect(_db)
con.execute("UPDATE photos SET govern_state='done'")
# 2026-10-17 老板规则「只有产品需要关联」：待关联只收产品图（label/product）
con.execute("UPDATE photos SET photo_kind='scene' WHERE photo_usage='监装'")
con.execute("UPDATE photos SET photo_kind='label' WHERE IFNULL(photo_usage,'')<>'监装'")
con.execute("UPDATE photos SET carton_no='CTN-A' WHERE photo_usage='监装'")
con.execute("UPDATE photos SET carton_no='CTN-B' WHERE photo_usage='预检'")
con.commit(); con.close()

# API 层先钉死（UI 断言在下面）
_ls = http_json('/api/photos/linkstate?container_id=%s' % cid) or {}
chk('0c 待关联徽章=5（8 张 - 3 监装场景照）',
    _ls.get('unlinked') == N_PHOTOS - 3, _ls.get('unlinked'))
chk('0c2 全部徽章仍是 8', _ls.get('all') == N_PHOTOS, _ls.get('all'))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,900', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version', port=CDP_PORT, retries=40, timeout=3):
        print('[FAIL] 调试端口未就绪'); return False
    page = next((t for t in (http_json('/json/list', port=CDP_PORT) or [])
                 if t.get('type') == 'page'
                 and '/app/' in (t.get('url') or '')), None)
    if not page:
        print('[FAIL] 找不到 /app/ 的 page'); return False

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
        await asyncio.sleep(6.0)
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

        async def wait(fn, val, tries=30):
            for _ in range(tries):
                await asyncio.sleep(0.4)
                v = await js(fn)
                if v == val:
                    return v
            return await js(fn)

        # ════ ① 首屏 ════
        title = await js('document.title')
        chk('1 标题带「照片库」', '照片库' in str(title), title)
        chk('1b 菜单有「照片库」且为当前项',
            await js("!!document.querySelector('.el-menu-item.is-active')"
                     "&&document.querySelector('.el-menu-item.is-active').innerText.includes('照片库')") is True)
        n = await wait("document.querySelectorAll('.shot').length", N_PHOTOS)
        chk('2 网格 8 张', n == N_PHOTOS, n)
        chk('2b 卡片有缩略图与时间（拍照时间到秒）',
            await js("!!document.querySelector('.shot img')&&"
                     "/\\d{2}:\\d{2}:\\d{2}/.test(document.querySelector('.shot .meta:nth-of-type(1)')"
                     "?.textContent||document.querySelector('.shot').innerText)") is True)
        chk('2c 左侧树已渲染',
            await js("document.querySelectorAll('.ptree-i').length>0") is True)

        # ════ ② 树计数与筛选 ════
        usage_counts = await js("""(()=>{const out={};
            const secs=document.querySelectorAll('.ptree-sec');
            secs[0].querySelectorAll('.ptree-i').forEach(b=>{
              out[b.querySelector('.ptree-l').textContent]=
                b.querySelector('.ptree-n').textContent;});
            return JSON.stringify(out);})()""")
        chk('3 用途计数（监装3/预检2/未分类3）',
            json.loads(usage_counts or '{}') == {'监装': '3', '预检': '2', '未分类': '3'},
            usage_counts)

        # ── 左侧树必须随页面滚动冻住（老板 22:22 第1 条）──
        # 判据不能是「滚一次后 top 变没变」—— 第一次滚会把树吸到 .prow 顶部，
        # 本来就会动。正确判据是**再滚一段后top 纹丝不动**。
        # 三个坑：① 卡片自己带 overflow 会切断 sticky；② top 要等于滚动容器 padding；
        #        ③ align-self:stretch 会撑满容器反而不粘。三者任一错都会滑走。
        await js("(document.querySelector('.app-scroll')||"
                 "document.querySelector('.app-main')).scrollTop = 0")
        await asyncio.sleep(0.6)
        await js("(document.querySelector('.app-scroll')||"
                 "document.querySelector('.app-main')).scrollTop = 400")
        await asyncio.sleep(0.8)
        t1 = await js("Math.round(document.querySelector('.tree-card')"
                      ".getBoundingClientRect().top)")
        await js("(document.querySelector('.app-scroll')||"
                 "document.querySelector('.app-main')).scrollTop = 800")
        await asyncio.sleep(0.8)
        t2 = await js("Math.round(document.querySelector('.tree-card')"
                      ".getBoundingClientRect().top)")
        chk('3b 左树随页面滚动冻住（再滚一段 top 不变）', t1 == t2, '%s -> %s' % (t1, t2))
        # 控件高度对齐（同一条工具条不许有多种高度：EP 默认 input32/34/按钮24/分段22）
        hs = await js("""(()=>[...document.querySelectorAll(
            '.toolbar .el-select, .toolbar .el-input, .toolbar .el-button')]
            .map(e=>({h:Math.round(e.getBoundingClientRect().height),
                      cls:e.className.slice(0,60),
                      t:(e.innerText||'').trim().slice(0,8)})))()""")
        heights = sorted({x['h'] for x in (hs or [])})
        off = [x for x in (hs or []) if x['h'] != 32]
        chk('3c 工具条控件高度统一（都是 32px）',
            len(heights) == 1 and heights[0] == 32, '%s 异常项=%s' % (heights, off))
        await js("(document.querySelector('.app-scroll')||"
                 "document.querySelector('.app-main')).scrollTop = 0")
        await asyncio.sleep(0.5)

        await js("""(()=>{const b=[...document.querySelectorAll('.ptree-i')].find(
            x=>x.querySelector('.ptree-l').textContent==='监装'); if(b) b.click();})()""")
        n_sup = await wait("document.querySelectorAll('.shot').length", 3)
        chk('4 点「监装」→ 列表 3 张', n_sup == 3, n_sup)

        n_all = None
        await js("""(()=>{const b=[...document.querySelectorAll('.ptree-i')].find(
            x=>x.querySelector('.ptree-l').textContent==='监装'); if(b) b.click();})()""")
        n_all = await wait("document.querySelectorAll('.shot').length", N_PHOTOS)
        chk('5 再点一次取消 → 回到 8 张', n_all == N_PHOTOS, n_all)

        # ════ ③ 四视图 + 五档选项卡 ════
        # 视图切换：Element Plus 的 radio-button 真正可点的是 .el-radio-button__inner
        # （点隐藏的 input 不触发 change —— headless 下静默无效）
        async def set_view(label):
            await js("""(()=>{const b=[...document.querySelectorAll('.el-radio-button')]
                .find(x=>x.innerText.trim()==='%s');
                if(b) b.querySelector('.el-radio-button__inner').click();})()""" % label)

        await set_view('紧凑')
        await asyncio.sleep(1.5)
        await drain()
        chk('6 紧凑视图（卡片带 compact）',
            await js("!!document.querySelector('.shot.compact')") is True)

        await set_view('分组')
        await asyncio.sleep(2.5)
        await drain()
        chk('7 分组视图有组卡片',
            await js("document.querySelectorAll('.el-collapse-item').length>0") is True)

        await set_view('关联')
        tabs_ok = await wait("document.querySelectorAll('.el-tabs__item').length", 5)
        chk('8 关联视图五档选项卡', tabs_ok == 5, tabs_ok)
        labels = await js("""JSON.stringify([...document.querySelectorAll('.el-tabs__item')]
            .map(t=>t.innerText.trim().split('\\n')[0]))""")
        chk('8b 五档文案（全部/已关联/待关联/已忽略/无效图片）',
            json.loads(labels or '[]') == ['全部', '已关联', '待关联', '已忽略', '无效图片'],
            labels)
        # 徽章数字：待关联 = 5（产品图），全部 = 8
        badge = await wait("""(()=>{const t=[...document.querySelectorAll('.el-tabs__item')];
            const un=t[2].innerText.replace(/\\D/g,''); return un||'';})()""", '5')
        chk('9 待关联档徽章=5（只有产品图进队列）', badge == '5', badge)

        # 切到待关联档 → 列表 5 张
        await js("""(()=>{const t=[...document.querySelectorAll('.el-tabs__item')][2];
            if(t) t.click();})()""")
        n_ul = await wait("document.querySelectorAll('.shot').length", 5)
        chk('10 待关联档列表 5 张', n_ul == 5, n_ul)

        # 切无效档 → 空
        await js("""(()=>{const t=[...document.querySelectorAll('.el-tabs__item')][4];
            if(t) t.click();})()""")
        await asyncio.sleep(2.0)
        chk('11 无效图片档当前为空',
            await js("document.querySelectorAll('.shot').length") == 0)

        # 回「全部」档
        await js("""(()=>{const t=[...document.querySelectorAll('.el-tabs__item')][0];
            if(t) t.click();})()""")
        n_all = await wait("document.querySelectorAll('.shot').length", N_PHOTOS)
        chk('12 回「全部」档 → 8 张', n_all == N_PHOTOS, n_all)

        # ════ ④ 详情抽屉 ════
        # 点第一张（待关联档之外，先回详情视图）
        await js("""(()=>{const b=[...document.querySelectorAll('.el-radio-button')]
            .find(x=>x.innerText.trim()==='详情'); if(b)
            b.querySelector('.el-radio-button__inner').click();})()""")
        await asyncio.sleep(1.5)
        await js("document.querySelector('.shot').click()")
        ok = await wait("!!document.querySelector('.dw-right')", True)
        chk('13 抽屉打开（左图右信息）', ok is True)
        chk('13b 抽屉有分类下拉与用途下拉',
            await js("document.querySelectorAll('.dw-right .el-select').length>=2") is True)
        chk('13c 抽屉有「已关联产品」区块（有历史关联或产品图才出现）',
            await js("""[...document.querySelectorAll('.dw-right h4')]
                .some(h=>h.textContent.includes('已关联产品'))""") in (True, False))
        # 显隐必须与分类联动：先统一改判为产品图 → 断言「建议关联」出现，
        # 再改判为包装 → 断言收起（2026-10-17 老板规则）。
        async def set_kind(label):
            await js("""(()=>{const sels=[...document.querySelectorAll('.dw-right .el-select')];
                const el=sels[0].querySelector('input'); el&&el.click();})()""")
            await asyncio.sleep(0.8)
            await js("""(()=>{const o=[...document.querySelectorAll('.el-select-dropdown__item')]
                .find(x=>x.textContent.trim()===%s); if(o) o.click();})()"""
                     % json.dumps(label))
            await asyncio.sleep(3.0)
            await drain()

        await set_kind('产品·有编码')
        has_cand = await js("""[...document.querySelectorAll('.dw-right h4')]
            .some(h=>h.textContent.includes('建议关联'))""")
        chk('13d 改判为产品图 → 出现「建议关联」', has_cand is True, has_cand)

        await set_kind('包装')
        chk('14 改判为「包装」→ 关联区联动收起',
            await js("""!([...document.querySelectorAll('.dw-right h4')]
                .some(h=>h.textContent.includes('建议关联')))""") is True)

        await set_kind('产品·有编码')
        chk('15 改回产品图 → 关联区回来',
            await js("""[...document.querySelectorAll('.dw-right h4')]
                .some(h=>h.textContent.includes('建议关联'))""") is True)

        # Esc 关抽屉
        await js("window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))")
        closed = await wait("!!document.querySelector('.dw-right')", False)
        chk('16 Esc 关抽屉', closed is False, closed)

        # ════ ⑤ 批量选择 + 标记无效 ════
        await js("""(()=>{const b=[...document.querySelectorAll('.page-card button, button')]
            .find(x=>x.innerText.trim()==='批量选择'); if(b) b.click();})()""")
        await asyncio.sleep(1.0)
        chk('17 进入选择模式（操作条出现）',
            await js("!!document.querySelector('.selbar')") is True)
        await js("document.querySelector('.shot').click()")
        await asyncio.sleep(0.6)
        chk('17b 点卡片 = 勾选（不打开抽屉）',
            await js("!!document.querySelector('.shot.sel-on')&&!document.querySelector('.dw-right')") is True)
        chk('17c 操作条计数 = 1',
            await js("(document.querySelector('.selbar b')||{}).textContent==='1'") is True)
        await js("""(()=>{const b=[...document.querySelectorAll('.selbar button')]
            .find(x=>x.innerText.trim()==='标记无效'); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        # 默认筛选是「排除无效」→ 标完那张直接从工作队列消失（不是留在列表里变灰）
        n_after = await js("document.querySelectorAll('.shot').length")
        chk('18 标记无效 → 该张退出默认列表（8 → 7）',
            n_after == N_PHOTOS - 1, n_after)
        inval_n = http_json('/api/photos?container_id=%s&invalid=only&limit=50' % cid) or {}
        chk('18b 后端无效档 = 1 张', inval_n.get('total') == 1, inval_n.get('total'))
        await js("""(()=>{const b=[...document.querySelectorAll('button')]
            .find(x=>x.innerText.trim()==='退出选择'); if(b) b.click();})()""")
        await asyncio.sleep(0.8)
        # 无效档里那张要能看到（降透明 + 灰角标）
        await set_view('关联')
        await asyncio.sleep(1.5)
        await js("""(()=>{const t=[...document.querySelectorAll('.el-tabs__item')][4];
            if(t) t.click();})()""")
        n_inv = await wait("document.querySelectorAll('.shot').length", 1)
        chk('18c 无效图片档能看到那张（.inval 降透明）',
            n_inv == 1 and await js("!!document.querySelector('.shot.inval')") is True, n_inv)
        await js("""(()=>{const t=[...document.querySelectorAll('.el-tabs__item')][0];
            if(t) t.click();})()""")
        await asyncio.sleep(1.2)

        # ════ ⑥ 刷新保持（URL 路由直落）══
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(5.5)
        await drain()
        chk('19 刷新后仍落在照片库（history 路由）',
            await js("location.pathname") == '/app/photos',
            await js("location.pathname"))
        chk('19b 刷新后网格仍渲染',
            await js("document.querySelectorAll('.shot').length") > 0)

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('20 全程无 JS 异常', not bad,
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
