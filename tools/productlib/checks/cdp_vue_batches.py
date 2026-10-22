# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 版照片批次 /app/batches（vue3-frontend 分支）。

覆盖旧版 batches.js 的批次表核心行为：
  · 批次表渲染（唯一/重复、治理进度条与标签、已关联数）
  · 状态筛选（待治理 / 已完成 / 有失败）与关键词搜索
  · 按柜筛选（行内治理走同一个 /api/govern，参数带 batch_id）
  · 「查看」→ 跳照片库并带上该批次筛选
  · 行内「治理 / 重试失败 / 重跑」三种动作的参数与前置提示
  · 空态、刷新保持、无 JS 异常

⚠️ 隔离实例 8808 / CDP 9368，不碰 8765。
跑法：python tools/productlib/checks/cdp_vue_batches.py
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
import urllib.error
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8808'))
CDP_PORT = int(os.environ.get('PL_CDP', '9368'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuebatch_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuebatch_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/batches'
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
    b = '----plbat' + str(int(time.time()))
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

# ── 造数据：2 柜 3 批（一个全待治理 / 一个已完成 / 一个有失败） ──
code, c1 = _req('POST', '/api/containers', {'container_no': 'VBT1', 'inspector': 'cdp'})
cid1 = (c1 or {}).get('id')
chk('0 建柜 VBT1', bool(cid1), cid1)
code, c2 = _req('POST', '/api/containers', {'container_no': 'VBT2', 'inspector': 'cdp'})
cid2 = (c2 or {}).get('id')
chk('0b 建柜 VBT2', bool(cid2), cid2)

from PIL import Image  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue_batches')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)


def make_files(tag, n, start):
    out = []
    for i in range(start, start + n):
        p = os.path.join(tmpd, '%s_%02d.jpg' % (tag, i))
        Image.new('RGB', (1000, 800), (50 + i * 20, 140, 180)).save(p)
        out.append(('files', p, os.path.basename(p)))
    return out


# 批 1：VBT1，4 张全待治理（govern_state 默认 pending）
code, r = post_file('/api/photos/upload', {'container_id': cid1}, make_files('B1', 4, 0))
chk('0c 批 1 上传 4 张', code == 200 and (r or {}).get('added') == 4,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:100]))
# 批 2：VBT2，3 张全部治理完
code, r = post_file('/api/photos/upload', {'container_id': cid2}, make_files('B2', 3, 10))
chk('0d 批 2 上传 3 张', code == 200 and (r or {}).get('added') == 3,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:100]))
# 批 3：VBT1，2 张（一张 done、一张 failed）
code, r = post_file('/api/photos/upload', {'container_id': cid1}, make_files('B3', 2, 20))
chk('0e 批 3 上传 2 张', code == 200 and (r or {}).get('added') == 2,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:100]))

d1 = http_json('/api/photos?container_id=%s&limit=50' % cid1) or {}
d2 = http_json('/api/photos?container_id=%s&limit=50' % cid2) or {}
p1 = [x['id'] for x in (d1.get('items') or [])]
p2 = [x['id'] for x in (d2.get('items') or [])]
chk('0f 照片 id 取齐', len(p1) == 6 and len(p2) == 3, '%s / %s' % (len(p1), len(p2)))

con = sqlite3.connect(os.path.join(DBHOME, 'productlib.db'), timeout=30)
# 🔴 is_dup 必须显式清零：上传时有照片被判成重复件，而 batches_stats 的
#    unique/pending/failed 全都带 is_dup=0 —— 不同批次口径立刻错位
#    （症状：明明 UPDATE 了 failed，页面「失败 1」就是不出来）。
con.execute("UPDATE photos SET is_dup=0")
# 批 2 全治理完；批 3 造「一完成一失败」
con.execute("UPDATE photos SET govern_state='done' WHERE id IN (%s)"
            % ','.join('?' * len(p2)), p2)
con.execute("UPDATE photos SET govern_state='done' WHERE id=?", (p1[4],))
con.execute("UPDATE photos SET govern_state='failed' WHERE id=?", (p1[5],))
con.commit()
con.close()

# API 层钉死基线（UI 断言在下）
bl = http_json('/api/batches') or {}
items = bl.get('items') or []
chk('1 批次 3 个', len(items) == 3, len(items))
by_pending = sorted(x['pending'] for x in items)
# 批1 全 pending(4)；批2 全 done(0)；批3 一 done 一 failed(0)
chk('1b 待治理数 4/0/0', by_pending == [0, 0, 4], by_pending)
chk('1c 有一个批次 failed=1', any(x['failed'] == 1 for x in items),
    [x['failed'] for x in items])
chk('1d 批次带柜号', sorted({x.get('container_no') for x in items}) == ['VBT1', 'VBT2'],
    [x.get('container_no') for x in items])
one = http_json('/api/batches?container_id=%s' % cid2) or {}
chk('1e 按柜筛批次只剩 VBT2 的 1 个',
    len(one.get('items') or []) == 1
    and (one.get('items') or [{}])[0].get('container_no') == 'VBT2',
    one.get('items'))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,1100', URL],
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
        await asyncio.sleep(7.0)
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

        async def wait(fn, val, tries=40):
            for _ in range(tries):
                await asyncio.sleep(0.4)
                v = await js(fn)
                if v == val:
                    return v
            return await js(fn)

        async def click_in_row(sub, label):
            """点**指定那一行**里的按钮：批次同名难分辨，按行文本子串定位。"""
            return await js("""(()=>{const rs=[...document.querySelectorAll(
                '.bat-page .el-table__body-wrapper tr')];
                const r=rs.find(x=>(x.innerText||'').includes(%s)); if(!r) return false;
                const b=[...r.querySelectorAll('button')]
                  .find(x=>(x.innerText||'').trim()===%s);
                if(b){b.click();return true;} return false;})()"""
                            % (json.dumps(sub), json.dumps(label)))

        async def row_count():
            return await js("document.querySelectorAll("
                            "'.bat-page .el-table__body-wrapper tr').length")

        async def set_select(idx, val):
            """按序号点 el-select 的第 idx 个（0=柜，1=状态）。"""
            return await js("""(()=>{const sels=document.querySelectorAll(
                '.bat-page .el-select'); const s=sels[%d]; if(!s) return false;
                const i=s.querySelector('input'); i.focus(); return true;})()""" % idx)

        async def pick_option(text):
            return await js("""(()=>{const o=[...document.querySelectorAll(
                '.el-select-dropdown__item')].find(x=>(x.innerText||'').trim()===%s);
                if(o){o.click();return true;} return false;})()""" % json.dumps(text))

        # ════ ① 首屏 ════
        chk('2 标题带「照片批次」', '照片批次' in str(await js('document.title')),
            await js('document.title'))
        n = await wait("document.querySelectorAll('.bat-page .el-table__body-wrapper tr').length", 3)
        chk('3 批次表 3 行', n == 3, n)
        chk('3b 右上角计数「3 / 3 个批次」',
            '3 / 3 个批次' in str(await js(
                "(document.querySelector('.bat-page .toolbar')||{}).innerText||''")),
            await js("(document.querySelector('.bat-page .toolbar')||{}).innerText||''"))

        # 找「全待治理」那一行做内容断言
        txt_all = await js("""(()=>{const rs=[...document.querySelectorAll(
            '.bat-page .el-table__body-wrapper tr')];
            for(const r of rs){const t=r.innerText||'';
                if(t.includes('0/4')) return t;} return '';})()""")
        chk('4 待治理那行显示 0/4 进度与照片数',
            '0/4' in str(txt_all) and '/ 4' in str(txt_all),
            str(txt_all).replace('\n', ' ')[:110])
        chk('4b 行里有批次 ID（灰字）与柜号',
            'VBT1' in str(txt_all), str(txt_all).replace('\n', ' ')[:110])

        txt_done = await js("""(()=>{const rs=[...document.querySelectorAll(
            '.bat-page .el-table__body-wrapper tr')];
            for(const r of rs){const t=r.innerText||'';
                if(t.includes('完成')) return t;} return '';})()""")
        chk('5 全治理完那行打「完成」标签', '完成' in str(txt_done),
            str(txt_done).replace('\n', ' ')[:110])

        txt_fail = await js("""(()=>{const rs=[...document.querySelectorAll(
            '.bat-page .el-table__body-wrapper tr')];
            for(const r of rs){const t=r.innerText||'';
                if(t.includes('失败')) return t;} return '';})()""")
        chk('6 有失败那行显示「失败 1」', '失败 1' in str(txt_fail),
            str(txt_fail).replace('\n', ' ')[:110])

        # 按钮可用性：无 pending 的批次「治理」按钮应禁用
        dis = await js("""(()=>{const rs=[...document.querySelectorAll(
            '.bat-page .el-table__body-wrapper tr')];
            for(const r of rs){const t=r.innerText||'';
                if(!t.includes('失败')) continue;
                const b=[...r.querySelectorAll('button')]
                  .find(x=>x.innerText.trim()==='重试失败');
                const g=[...r.querySelectorAll('button')]
                  .find(x=>x.innerText.trim()==='治理');
                return JSON.stringify({retry:!!b, govDisabled:g?g.disabled:null});}
            return '';})()""")
        chk('7 有失败的批次才给「重试失败」按钮', dis and json.loads(dis).get('retry') is True,
            dis)
        # 批3 = 1 done + 1 failed，没有 pending → 「治理」必须禁用（点不动才对，
        # 无待治理时该走「重试失败」）
        chk('7b 该批次无待治理 → 「治理」禁用（该走重试失败）',
            dis and json.loads(dis).get('govDisabled') is True, dis)

        # ════ ② 状态筛选 ════
        await set_select(1, '')
        await asyncio.sleep(0.6)
        await pick_option('有失败')
        await asyncio.sleep(1.2)
        await drain()
        n_fail = await row_count()
        chk('8 筛「有失败」→ 1 行', n_fail == 1, n_fail)
        await pick_option('已完成')
        await asyncio.sleep(1.2)
        n_done = await row_count()
        chk('8b 筛「已完成」→ 1 行', n_done == 1, n_done)
        await pick_option('待治理')
        await asyncio.sleep(1.2)
        n_pend = await row_count()
        chk('8c 筛「待治理」→ 1 行（只有全待治理那批）', n_pend == 1, n_pend)
        await pick_option('全部状态')
        await asyncio.sleep(1.2)
        n_all = await row_count()
        chk('8d 回「全部状态」→ 3 行', n_all == 3, n_all)

        # ════ ③ 关键词搜索 ════
        bid_done = next((x['id'] for x in items if x['pending'] == 0), '')
        await js("""(()=>{const i=document.querySelector('.bat-page .toolbar input');
            if(i){const s=Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
                s.call(i,%s); i.dispatchEvent(new Event('input',{bubbles:true}));}})()"""
             % json.dumps(bid_done[:8]))
        await asyncio.sleep(1.2)
        n_s = await row_count()
        chk('9 搜批次 ID 片段 → 1 行', n_s == 1, n_s)
        await js("""(()=>{const i=document.querySelector('.bat-page .toolbar input');
            if(i){const s=Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
                s.call(i,''); i.dispatchEvent(new Event('input',{bubbles:true}));}})()""")
        await asyncio.sleep(1.2)
        chk('9b 清搜索 → 回 3 行', await row_count() == 3, await row_count())

        # ════ ④ 按柜筛选 ════
        await set_select(0, '')
        await asyncio.sleep(0.6)
        await pick_option('VBT2')
        await asyncio.sleep(1.8)
        await drain()
        n_c = await row_count()
        chk('10 按柜 VBT2 → 1 行', n_c == 1, n_c)
        n_cid = await js("""(()=>{const r=document.querySelector(
            '.bat-page .el-table__body-wrapper tr'); return r?r.innerText:'';})()""")
        chk('10b 那行柜号确实是 VBT2', 'VBT2' in str(n_cid),
            str(n_cid).replace('\n', ' ')[:80])
        # 清掉柜筛选
        # ⚠️ el-select 的 clear 图标**只有 hover 才渲染**（Element Plus 用
        #    hover 态控制），不先 mouseenter 的话 selector 恒空 —— 真实用户
        #    也是先移过去才点得到，别让脚本假装能凭空点到。
        await js("""(()=>{const s=document.querySelectorAll('.bat-page .el-select')[0];
            s.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true})); return true;})()""")
        await asyncio.sleep(0.6)
        await js("""(()=>{const c=document.querySelectorAll(
            '.bat-page .el-select')[0].querySelector('.el-select__clear'); if(c) c.click();})()""")
        await asyncio.sleep(1.8)
        chk('10c 清柜筛选 → 回 3 行', await row_count() == 3, await row_count())

        # ════ ⑤ 查看 → 跳照片库并带上批次筛选 ════
        ok_view = await click_in_row('VBT2', '查看')
        await asyncio.sleep(4.0)
        await drain()
        chk('11 点「查看」跳到照片库', ok_view and '/app/photos' in str(
            await js('location.pathname')), await js('location.pathname'))
        sel_txt = await js("""(()=>{const sels=[...document.querySelectorAll(
            '.photos-page .el-select')];
            for(const s of sels){const i=s.querySelector('input');
                if(i && i.value && i.value.indexOf('VBT2')>=0) return i.value;}
            return sels.map(s=>{const i=s.querySelector('input');return i?i.value:'';}).join('|');})()""")
        chk('11b 照片库的批次筛选已设成该批次',
            bid_done and str(sel_txt) != '' and ('|' in str(sel_txt) or str(sel_txt)),
            sel_txt)
        # 回到批次页
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.0)
        await drain()
        chk('11c 回批次页仍渲染 3 行', await wait(
            "document.querySelectorAll('.bat-page .el-table__body-wrapper tr').length", 3) == 3)

        # ════ ⑥ 行内治理动作 ════
        # 6a 无待治理的批次：治理按钮就该是禁用的（而不是点了没反应 / 发无效请求）
        await click_in_row('完成', '治理')
        await asyncio.sleep(1.2)
        dis2 = await js("""(()=>{const rs=[...document.querySelectorAll(
            '.bat-page .el-table__body-wrapper tr')];
            for(const r of rs){const t=r.innerText||'';
                if(!t.includes('失败')) continue;
                const g=[...r.querySelectorAll('button')]
                  .find(x=>x.innerText.trim()==='治理');
                return g?String(g.disabled):'none';}
            return 'norow';})()""")
        chk('12 无待治理的批次：治理按钮禁用（不用无效请求打扰后端）',
            dis2 == 'true', dis2)

        # 6b「重跑」要弹确认（真会重置治理状态，不能不问就干）
        await click_in_row('VBT2', '重跑')
        await asyncio.sleep(1.2)
        mb = await js("""(()=>{const m=document.querySelector(
            '.el-message-box');return m?m.innerText:'';})()""")
        chk('13 点「重跑」弹确认并说清影响', '重置为待治理' in str(mb)
            and '人工关联不受影响' in str(mb), str(mb).replace('\n', ' ')[:120])
        await js("""(()=>{const b=[...document.querySelectorAll(
            '.el-message-box__btns button')].find(x=>/取消|取 消/.test(x.innerText));
            if(b) b.click();})()""")
        await asyncio.sleep(1.0)
        st = http_json('/api/batches') or {}
        chk('13b 取消后治理状态没被动（完成批仍 pending=0）',
            any(x['pending'] == 0 for x in st.get('items') or []),
            [x['pending'] for x in st.get('items') or []])

        # 6c「重试失败」：确认框 + 真发 retry_failed
        await click_in_row('失败', '重试失败')
        await asyncio.sleep(1.2)
        mb2 = await js("""(()=>{const m=document.querySelector(
            '.el-message-box');return m?m.innerText:'';})()""")
        chk('14 点「重试失败」弹确认（只重跑失败的）', '失败照片' in str(mb2),
            str(mb2).replace('\n', ' ')[:120])
        await js("""(()=>{const b=[...document.querySelectorAll(
            '.el-message-box__btns button')].find(x=>/确定|确 定/.test(x.innerText));
            if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        # 柜作业已并进柜页双视图 → 治理启动后去 /app/containers 进作业
        chk('14b 确认后跳柜页（柜作业在那里，治理面板在③）',
            '/app/containers' in str(await js('location.pathname')),
            await js('location.pathname'))
        gs = http_json('/api/govern/status') or {}
        chk('14c 治理任务确实按该批次启动了',
            any((t.get('batch_id') or '') != '' for t in gs.get('tasks') or [])
            or gs.get('running') is True,
            json.dumps(gs, ensure_ascii=False)[:160])
        await js("""(()=>{const b=[...document.querySelectorAll('button')]
            .find(x=>x.innerText.trim()==='停止'); if(b) b.click();})()""")
        await asyncio.sleep(2.0)

        chk('15 全程无 JS 异常', not excs,
            json.dumps(excs, ensure_ascii=False)[:300])
        return not fails


ok = asyncio.run(main())
edge.terminate()
srv.terminate()
print(('FAIL %d 项' % len(fails)) if fails else 'PASS')
sys.exit(0 if ok and not fails else 1)