# -*- coding: utf-8 -*-
"""CDP 实跑：关联后刷新要保持当前位置 + 抽屉自身也要刷新（2026-10-14 老板追加需求）。

背景：v0.10.0 那轮做了「关联后广播 photos:changed 自动刷新」，但老板实测三条不满：
  ① 抽屉重绘用的是 _drawerCache 里的**关联前旧数据** —— 「已关联产品」不更新；
  ② 抽屉整体重换 #dwBody，.db 的 scrollTop 归零 —— 正看着的信息段被弹回图顶；
  ③ 列表 reset 把 offset 清 0，「加载更多」翻过的页丢了 —— 用户被弹回第一页。
本轮修复：drawer 关联/解除/批量关联后作废详情缓存；抽屉重绘记录并还原滚动；
photos.js / wizard.js 的 photos:changed listener 先记 scrollY、补回翻过的页数再还原。

本脚本验证（隔离实例 8798 / CDP 9358，不碰 8765）：
  1. 手输编码关联后，**抽屉仍开着**且右栏「已关联产品」出现该编码、建议区块消失；
  2. 抽屉滚动位置不归零（关联前记的 scrollTop，关联后还在）；
  3. 背后列表 window.scrollY 不被弹回顶部；
  4. 五档视图翻过页后关联，列表不缩回第一页（仍是两页的条数）；
  5. 解除关联后抽屉回到「未关联」状态（手输框回来），列表卡片「关联」消失；
  6. 全程无 JS 异常。

⚠️ CDP 坑（沿用）：Runtime.evaluate 顶层 const 跨调用残留 → 表达式必须包 IIFE。
跑法：python tools/productlib/checks/cdp_refresh_position.py
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
PORT = int(os.environ.get('PL_PORT', '8798'))
CDP_PORT = int(os.environ.get('PL_CDP', '9358'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_refresh_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_refresh_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 61          # 列表每页 60 → 必须凑出第二页，才能验「不缩回首页」

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
    b = '----plrefresh' + str(int(time.time()))
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
    print('[FAIL] 隔离实例 %d 没起来' % PORT)
    sys.exit(1)

# ── 造数据：产品 1 个 + 柜 1 个 + 照片 N_PHOTOS 张（真 jpg，复用上传链路）──
code, r = post_json('/api/products', {'code': 'REFR-A1', 'name': '刷新测试品'})
chk('0 建产品', code in (200, 201), '%s %s' % (code, r))
code, c = post_json('/api/containers', {'container_no': 'REFR01',
                                        'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_refresh_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd, exist_ok=True)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'RF_%03d.jpg' % i)
    Image.new('RGB', (1200, 900), (40 + i % 200, 110, 170)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 %d 张照片' % N_PHOTOS,
    code == 200 and (r or {}).get('added', 0) == N_PHOTOS,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:200]))

# 窗口刻意小：抽屉（100vh）才滚得动，才能验「滚动位置不归零」
edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1280,560', URL],
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
            # ⚠️ 必须 surfaced 异常：表达式里点不存在的元素会静默 TypeError，
            #     不看 exceptionDetails 就会表现成「动作没发生」（本轮踩过）
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str((ex.get('exception') or {}).get('description')
                                     or ex.get('text'))[:200]
            return (r.get('result') or {}).get('value')

        async def wait_cards(n, tries=24):
            """等卡片数稳定到 n。⚠️ 不能固定 sleep：切视图/刷新时请求在飞，
            早早点「加载更多」会被 st._seq 守卫把旧响应吞了（实测 flake）。"""
            last = -1
            for _ in range(tries):
                await asyncio.sleep(0.5)
                c = await js("document.querySelectorAll('#shots .shot').length")
                if c == n:
                    return c
                last = c
            return last

        # 捕获同步异常 + **unhandledrejection**（async 事件监听器里抛出的错
        # 走的是这条路，Runtime.exceptionThrown 不一定报，drain 抓不到）
        await js("""(()=>{window.__errs=[];
            window.addEventListener('error',e=>window.__errs.push('error: '+e.message));
            window.addEventListener('unhandledrejection',
              e=>window.__errs.push('rejection: '+(e.reason&&e.reason.stack||e.reason)));})()""")

        # 进照片库页
        await js("window.go && window.go('batches')")
        await asyncio.sleep(3.0)
        await drain()

        # ── 翻到第二页（full 视图每页 60）──
        n1 = await js("document.querySelectorAll('#shots .shot').length")
        chk('1 首屏 60 张（每页 60）', n1 == 60, n1)
        await js("document.querySelector('#moreBtn').click()")
        n2 = await wait_cards(61)
        chk('2 加载更多后 61 张（有第二页）', n2 == 61, n2)

        # ── 切五档（link）视图，再翻一次页 ──
        await js("""(()=>{const b=[...document.querySelectorAll('#shotView button')]
            .find(x=>x.dataset.v==='link'); if(b) b.click();})()""")
        nt1 = await wait_cards(60)
        chk('3 五档视图首屏 60 张', nt1 == 60, nt1)
        await js("document.querySelector('#moreBtn').click()")
        nt2 = await wait_cards(61)
        chk('4 五档视图翻页后 61 张', nt2 == 61, nt2)

        # ── 把窗口滚到一个非零位置 ──
        await js("window.scrollTo(0, 600)")
        await asyncio.sleep(0.4)
        y_before = await js("window.scrollY")
        chk('5 列表已滚动到 600（前提）', y_before == 600, y_before)

        # ── 开抽屉，记滚动位置 ──
        await js("document.querySelector('#shots .shot').click()")
        await asyncio.sleep(2.5)
        await drain()
        pid1 = await js("""(()=>{const d=document.querySelector('#drawer');
            return d && d.classList.contains('on')
                 ? document.querySelector('#dwImg').dataset.pid : '';})()""")
        chk('6 抽屉已打开', bool(pid1), pid1)
        # 诊断探针：开抽屉这个动作本身有没有把窗口滚走？
        y_after_open = await js("window.scrollY")
        chk('6b 开抽屉不碰窗口滚动（诊断）', y_after_open == 600,
            'scrollY=%s（关联前是 600）' % y_after_open)
        # 抽屉滚到中下部（内容不够高时拿得到多少算多少，下面按实况判）
        await js("""(()=>{const db=document.querySelector('#drawer .db');
            if(db) db.scrollTop = Math.min(140, db.scrollHeight);})()""")
        await asyncio.sleep(0.4)
        s_before = await js("""(()=>{const db=document.querySelector('#drawer .db');
            return db ? db.scrollTop : -1;})()""")
        scrollable = await js("""(()=>{const db=document.querySelector('#drawer .db');
            return db ? (db.scrollHeight > db.clientHeight + 40) : false;})()""")
        chk('7 抽屉可滚动（窗口 560px 高）', scrollable is True,
            'scrollTop=%s' % s_before)

        # ── 关联（手输编码）──
        link_ret = await js("""(()=>{const i=document.querySelector('#dwCode');
            const b=document.querySelector('#dwLink');
            if(!i || !b) return 'MISSING code='+(!!i)+' link='+(!!b);
            i.value='REFR-A1'; b.click();
            return 'clicked';})()""")
        chk('7b 关联按钮可点（诊断）', link_ret == 'clicked', link_ret)
        # 探针：关联后不同时间点的窗口滚动 + 列表状态（返回字符串，避免
        # returnByValue 对对象字面量的序列化问题）
        probes = []
        for i in range(10):
            await asyncio.sleep(0.5)
            probes.append(await js(
                "(()=>{const q=s=>document.querySelector(s);"
                "const n=document.querySelectorAll('#shots .shot').length;"
                "const m=q('#moreBtn');"
                "return 't+%.1fs scrollY='+window.scrollY"
                "+' cards='+n+' more='+(m?m.style.display:'?')"
                "+' total='+(q('#fTotal')?q('#fTotal').textContent:'');})()"
                .replace('%.1f', str(0.5 * (i + 1)))))
        await asyncio.sleep(1.0)
        await drain()
        for p in probes:
            print('     [探针] %s' % p, flush=True)

        # 8. 抽屉仍开着 + 内容已刷新（缓存失效）
        dw_open = await js("document.querySelector('#drawer').classList.contains('on')")
        toast_txt = await js("""(()=>{const t=document.querySelector('.toast');
            return t ? t.textContent : '';})()""")
        chk('8 关联后抽屉没被关掉', dw_open is True,
            'drawer_on=%s toast=%r' % (dw_open, toast_txt))
        linked_head = await js("""(()=>{const h=[...document.querySelectorAll(
            '#dwBody .dsec h4')].find(x=>x.textContent.includes('已关联产品'));
            return h ? h.textContent : '';})()""")
        # ⚠️ 编码会被 normalize 删分隔符（REFR-A1 → REFRA1），断言改用**品名**
        has_name = await js("""[...document.querySelectorAll('#dwBody .dsec')]
            .some(s=>s.textContent.includes('刷新测试品'))""")
        cands_gone = await js("!document.querySelector('#dwCands')"
                              " && !document.querySelector('#dwCode')")
        chk('9 抽屉刷新：已关联产品（1）且品名出现',
            linked_head == '已关联产品（1）' and has_name is True,
            '%r / has_name=%s' % (linked_head, has_name))
        chk('10 抽屉刷新：建议关联/手输区块消失（已关联不再显示）',
            cands_gone is True, cands_gone)

        # 11. 抽屉滚动位置保持
        # 口径：还原值 = min(原 scrollTop, 当时内容最大可滚)。关联会让右栏变矮
        # （建议关联区消失），且预览图是还原**之后**才加载完的（内容又长高），
        # 浏览器都不会自动补滚动 —— 所以不断言精确相等，要求「没归零、没大幅
        # 跑偏」（≥ 可滚范围的一半）。
        s_after_obj = await js("""(()=>{const db=document.querySelector('#drawer .db');
            return db ? {top:db.scrollTop, max:db.scrollHeight-db.clientHeight}
                      : {top:-1,max:-1};})()""")
        s_after = (s_after_obj or {}).get('top')
        new_max = (s_after_obj or {}).get('max')
        if s_before > 0:
            ok = s_after > 0 and s_after >= min(s_before, new_max) * 0.5
            chk('11 抽屉滚动位置保持', ok,
                'before=%s after=%s newMax=%s' % (s_before, s_after, new_max))
        else:
            chk('11 抽屉滚动位置保持', True, 'SKIP：内容不够高，scrollTop 本来就是 0')

        # 12. 列表滚动位置保持
        y_after = await js("window.scrollY")
        chk('12 列表滚动没被弹回顶部', abs(y_after - 600) <= 30,
            'before=600 after=%s' % y_after)

        # 13. 列表不缩回第一页（仍是 61 张）—— refill 是异步的，等它稳定
        n_after = await wait_cards(61)
        chk('13 列表没缩回第一页（还是 61 张）', n_after == 61, n_after)

        # 14. 列表卡片显示关联 + 后端口径
        linked_ui = await js("""[...document.querySelectorAll('#shots .shot .meta')]
            .some(e=>e.textContent.includes('关联'))""")
        chk('14 卡片显示「关联」', linked_ui is True)
        d = http_json('/api/photos?container_id=%s&limit=10' % cid) or {}
        it = next((x for x in d.get('items') or [] if x['id'] == pid1), {})
        chk('15 后端 nlink=1（前后一致）', it.get('nlink') == 1, it.get('nlink'))

        # ── 解除关联：抽屉也要刷新回未关联状态 ──
        await js("""(()=>{const u=document.querySelector('#dwBody .un');
            if(u) u.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        back = await js("""(()=>{const on=document.querySelector('#drawer')
            .classList.contains('on');
            const i=document.querySelector('#dwCode');
            const h=[...document.querySelectorAll('#dwBody .dsec h4')]
            .find(x=>x.textContent.includes('已关联产品'));
            return {on:on, input:!!i, head:h?h.textContent:''};})()""")
        chk('16 解除后抽屉回到未关联状态（手输框回来、计数归零）',
            back.get('on') is True and back.get('input') is True
            and back.get('head') == '已关联产品（0）',
            json.dumps(back, ensure_ascii=False))
        unlinked_ui = await js("""[...document.querySelectorAll('#shots .shot .meta')]
            .some(e=>e.textContent.includes('关联'))""")
        chk('17 解除后卡片「关联」消失（列表也刷新了）', unlinked_ui is False)

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        page_errs = await js("window.__errs || []") or []
        allbad = bad + [e for e in page_errs if 'favicon' not in str(e)]
        chk('18 全程无 JS 异常', not allbad,
            (json.dumps(allbad[:3], ensure_ascii=False)[:500] if allbad else ''))
    return not bad and not page_errs


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
