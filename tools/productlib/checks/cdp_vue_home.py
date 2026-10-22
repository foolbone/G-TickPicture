# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 版首页概览/app/home（vue3-frontend 分支）。

覆盖旧版 home.js + #tab-home 的核心行为：
  · 概览卡数字与 /api/stats 当场比对（数字同源：不做前端二次加工）
  · 覆盖率算式、多模态状态文案（未配置 → 降级运行）
  · 快速开始五个入口真能跳到对应路由
  · 批次统计卡与 /api/batches 当场比对（含完成/失败/已关联三口径）
  · 批次明细表：进度标签/进度条/已关联列
  · 系统说明五步文案在
  · 空态（无批次时出 el-empty 而不是空白）
  · 刷新保持、无 JS 异常

⚠️ 隔离实例 8810 / CDP 9370，不碰 8765。
跑法：python tools/productlib/checks/cdp_vue_home.py
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
PORT = int(os.environ.get('PL_PORT', '8810'))
CDP_PORT = int(os.environ.get('PL_CDP', '9370'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuehome_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuehome_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/home'
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


def _req(method, path, obj=None, timeout=120):
    data = json.dumps(obj).encode('utf8') if obj is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:200]}


def post_file(path, fields, files, timeout=600):
    b = '----plhome' + str(int(time.time()))
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
    req = urllib.request.Request(BASE + path, data=buf,
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
        with urllib.request.urlopen(BASE + '/api/ping', timeout=2) as r:
            json.loads(r.read()); break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例没起来')
    sys.exit(1)

# ── 造数据：1 个柜 + 2 张照片；第二个柜不导照片（批次进度不齐） ──
from PIL import Image  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue_home')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)

code, c1 = _req('POST', '/api/containers', {'container_no': 'VH1', 'inspector': 'cdp'})
cid1 = (c1 or {}).get('id')
chk('0 建柜 VH1', bool(cid1), cid1)

files = []
for i in range(2):
    p = os.path.join(tmpd, 'HM_%02d.jpg' % i)
    Image.new('RGB', (900, 700), (60 + i * 40, 140, 180)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, up = post_file('/api/photos/upload', {'container_id': cid1}, files)
chk('0b VH1 上传 2 张', code == 200 and (up or {}).get('added') == 2,
    '%s %s' % (code, json.dumps(up, ensure_ascii=False)[:90]))

code, c2 = _req('POST', '/api/containers', {'container_no': 'VH2', 'inspector': 'cdp'})
cid2 = (c2 or {}).get('id')
chk('0c 建柜 VH2', bool(cid2), cid2)
# ⚠️ 批次是**上传时**才产生的 —— 建了空柜不会有批次。
#    两个柜各导一次 → 两个批次，且治理进度天然不齐（更好验进度口径）。
files2 = []
for i in range(3):
    p = os.path.join(tmpd, 'HM2_%02d.jpg' % i)
    Image.new('RGB', (800, 600), (120, 60 + i * 30, 90)).save(p)
    files2.append(('files', p, os.path.basename(p)))
code, up2 = post_file('/api/photos/upload', {'container_id': cid2}, files2)
chk('0d VH2 上传 3 张（第二个批次）', code == 200 and (up2 or {}).get('added') == 3,
    '%s %s' % (code, json.dumps(up2, ensure_ascii=False)[:90]))

# API 层基线
st = http_json('/api/stats') or {}
chk('1 /api/stats 有产品/照片/关联三项',
    all(k in st for k in ('products', 'photos', 'links', 'pending', 'unlinked')),
    json.dumps(st, ensure_ascii=False)[:150])
bt = http_json('/api/batches') or {}
items = bt.get('items') or []
chk('2 /api/batches 有 2 个批次', len(items) == 2, len(items))

# 与旧 home.js 同口径的期望值（脚本内独立算一遍，不抄前端）
exp_total = len(items)
exp_done = len([b for b in items
                if b.get('pending') == 0 and b.get('failed') == 0
                and (b.get('unique') or 0) > 0])
exp_fail = len([b for b in items if (b.get('failed') or 0) > 0])
exp_link = sum((b.get('linked') or 0) for b in items)
exp_cov = (round(st['with_photos'] / st['products'] * 100)
           if st.get('products') else 0)
print('  [基线] stats=%s' % json.dumps(st, ensure_ascii=False)[:120], flush=True)
print('  [基线] 批次 %s 完成%d 失败%d 关联%d 覆盖%d%%'
      % (exp_total, exp_done, exp_fail, exp_link, exp_cov), flush=True)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1400,1400', URL],
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
        await asyncio.sleep(8.0)
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

        # ════ ① 首屏 ════
        chk('3 标题带「首页」', '首页' in str(await js('document.title')),
            await js('document.title'))

        # 概览卡：按标签文字取数字，避免靠 DOM 顺序
        # 概览卡：只取**第一组** .cards（页面里还有第二组=批次统计卡）
        cards = await js("""(()=>{const cs=document.querySelectorAll('.home-page .cards');
            if(!cs.length) return '{}';
            const out={};
            for(const c of cs[0].querySelectorAll('.card')){
                const l=c.querySelector('.l'), n=c.querySelector('.n');
                if(l&&n) out[l.innerText.trim()]=n.innerText.trim();}
            return JSON.stringify(out);})()""")
        chk('4 六张概览卡都在（产品/有照片的产品/照片/待治理/待关联/关联）',
            all(k in str(cards) for k in
                ('产品', '有照片的产品', '照片', '待治理', '待关联', '关联')), cards)

        cv = json.loads(str(cards)) if str(cards).startswith('{') else {}
        chk('5 产品数与 /api/stats 同源',
            str(st.get('products', 0)) in str(cv.get('产品', '')),
            '%s vs %s' % (cv.get('产品'), st.get('products')))
        chk('5b 照片数与 /api/stats 同源',
            str(st.get('photos', 0)) in str(cv.get('照片', '')),
            '%s vs %s' % (cv.get('照片'), st.get('photos')))
        chk('5c 关联数与 /api/stats 同源',
            str(st.get('links', 0)) in str(cv.get('关联', '')),
            '%s vs %s' % (cv.get('关联'), st.get('links')))
        chk('5d 待治理/待关联两数与后端同源',
            str(st.get('pending', 0)) in str(cv.get('待治理', ''))
            and str(st.get('unlinked', 0)) in str(cv.get('待关联', '')),
            '%s/%s' % (cv.get('待治理'), cv.get('待关联')))
        chk('6 「有照片的产品」是 with_photos / products 两数并列',
            cv.get('有照片的产品') == '%s / %s' % (st.get('with_photos', 0),
                                                  st.get('products', 0)),
            cv.get('有照片的产品'))
        covtxt = await js("""(()=>{const e=document.querySelector('.home-page .cov');
            return e?e.innerText:'';})()""")
        chk('6b 覆盖率文案算式正确', ('%d%%' % exp_cov) in str(covtxt),
            '%s（期望 %d%%）' % (str(covtxt).replace('\n', ' '), exp_cov))
        chk('7 多模态未配置 → 概览页也说「降级运行」',
            '降级运行' in str(await js("""(()=>{const e=document.querySelector(
                '.home-page .phead .faint'); return e?e.innerText:'';})()""")),
            await js("""(()=>{const e=document.querySelector(
                '.home-page .phead .faint'); return e?e.innerText:'';})()"""))

        # ════ ② 快速开始 ════
        heads = await js("""(()=>{const hs=[...document.querySelectorAll('.home-page h3')]
            .map(h=>h.innerText.trim()); return JSON.stringify(hs);})()""")
        chk('8 三块标题都在（快速开始/批次统计/系统说明）',
            all(k in str(heads) for k in ('快速开始', '批次统计', '系统说明')), heads)
        btns = await js("""(()=>{const bs=[...document.querySelectorAll('.home-page .quick button')]
            .map(b=>b.innerText.trim()); return JSON.stringify(bs);})()""")
        chk('8b 快速开始五个入口都在',
            all(m in str(btns) for m in
                ('①', '②', '③', '④', '⑤')), btns)
        # 点「② 跑治理」应落在 /app/wizard
        await js("""(()=>{const b=[...document.querySelectorAll('.home-page .quick button')]
            .find(x=>x.innerText.trim().startsWith('②')); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        chk('9 点「② 跑治理」跳到柜作业',
            '/app/wizard' in str(await js('location.pathname')),
            await js('location.pathname'))
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.0)
        await drain()
        # 点「③ 审核入库」应落在 /app/review
        await js("""(()=>{const b=[...document.querySelectorAll('.home-page .quick button')]
            .find(x=>x.innerText.trim().startsWith('③')); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        chk('9b 点「③ 审核入库」跳到新产品确认',
            '/app/review' in str(await js('location.pathname')),
            await js('location.pathname'))
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.0)
        await drain()

        # ════ ③ 批次统计 ════
        bcards = await js("""(()=>{const cs=[...document.querySelectorAll('.home-page .cards')];
            if(cs.length<2) return '{}';
            const out={};
            for(const c of cs[1].querySelectorAll('.card')){
                const l=c.querySelector('.l'), n=c.querySelector('.n');
                if(l&&n) out[l.innerText.trim()]=n.innerText.trim();}
            return JSON.stringify(out);})()""")
        bv = json.loads(str(bcards)) if str(bcards).startswith('{') else {}
        chk('10 批次统计四张卡都在',
            all(k in str(bcards) for k in
                ('批次总数', '已完成', '有失败', '已关联照片')), bcards)
        chk('10b 批次总数与 /api/batches 同源',
            str(bv.get('批次总数', '')) == str(exp_total),
            '%s vs %s' % (bv.get('批次总数'), exp_total))
        chk('10c 已完成口径 = pending/failed 都为 0 且 unique>0',
            bv.get('已完成') == '%s / %s' % (exp_done, exp_total),
            '%s vs %s / %s' % (bv.get('已完成'), exp_done, exp_total))
        chk('10d 有失败数与后端同源',
            str(bv.get('有失败', '')) == str(exp_fail),
            '%s vs %s' % (bv.get('有失败'), exp_fail))
        chk('10e 已关联照片数与后端同源',
            str(bv.get('已关联照片', '')) == str(exp_link),
            '%s vs %s' % (bv.get('已关联照片'), exp_link))

        rows = await js("""(()=>{const rs=[...document.querySelectorAll(
            '.home-page .el-table__body-wrapper tr')];
            return JSON.stringify(rs.map(r=>r.innerText.replace(/\\n/g,' | ')));})()""")
        rl = json.loads(str(rows)) if str(rows).startswith('[') else []
        chk('11 明细表行数与 /api/batches 同源', len(rl) == exp_total,
            '%d vs %d' % (len(rl), exp_total))
        # ⚠️ 批次名是「网页上传 <id>」，**不含柜号** —— 别拿柜号去断言批次行
        #    行文本按 ' | ' 切后末尾还有「已关联」列，进度列是倒数第 3 段；
        #    这里用正则定位，别写死下标。
        import re as _re
        pat = _re.compile(r'2026-\d\d-\d\d \d\d:\d\d')
        cnt = _re.compile(r'\b(\d+) / (\d+)\b')
        prg = _re.compile(r'\b(\d+)/(\d+)\b')
        ok_rows = []
        for r in rl:
            has_t = bool(pat.search(r))
            m1, m2 = cnt.search(r), prg.search(r)
            ok_rows.append(bool(has_t and m1 and m2
                                and m1.group(1) == m2.group(2)
                                and m1.group(2) == m2.group(2)))
        chk('11b 每行带导入时间到分钟 + 唯一/总数 + 进度 n/m（且三者自洽）',
            bool(rl) and all(ok_rows), str(rl)[:220])
        n_prog = await js("document.querySelectorAll('.home-page .el-progress').length")
        chk('12 每行一条进度条', n_prog == exp_total, '%s vs %s' % (n_prog, exp_total))

        # ════ ④ 系统说明 ════
        body = await js('document.body.innerText')
        chk('13 系统说明五步都在',
            all(k in str(body) for k in
                ('导入照片', '跑治理', '人工标注', '产品库', '检索与报告')))
        chk('13b 设计原则那句保留（错关联比没关联危险）',
            '错关联比没关联危险' in str(body))
        # 概览不占一级项（对齐旧版：首页 section 本来就不在导航里），
        # 它挂在品牌区上 —— 断言品牌链接指向 /app/home 且可点。
        chk('14 概览入口在品牌区（可点，不占一级导航项）',
            await js("!!document.querySelector(\"a.app-logo\")") is True
            and await js("document.querySelector('a.app-logo').getAttribute('href')")
            == '/app/home',
            await js("(()=>{const e=document.querySelector('a.app-logo');"
                     "return e?e.innerText.trim()+' -> '+e.getAttribute('href'):'无';})()"))
        chk('14b 侧栏无「待迁移」的置灰项',
            '待迁移' not in str(body),
            [x for x in str(body).split('\n') if '待迁移' in x][:2])

        # ════ ⑤ 刷新保持 ════
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.5)
        await drain()
        chk('15 刷新仍落在 /app/home', '/app/home' in str(await js('location.pathname')),
            await js('location.pathname'))
        chk('15b 刷新后概览数字还在（不是空库假象）',
            '批次总数' in str(await js('document.body.innerText')))

        chk('16 全程无 JS 异常', not excs, json.dumps(excs, ensure_ascii=False)[:300])
        return not fails


ok = asyncio.run(main())
edge.terminate()
srv.terminate()
print(('FAIL %d 项' % len(fails)) if fails else 'PASS')
sys.exit(0 if ok and not fails else 1)
