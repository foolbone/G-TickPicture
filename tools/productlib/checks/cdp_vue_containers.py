# -*- coding: utf-8 -*-
"""CDP 实跑：柜页双视图 + 筛选标签行/方案（vue3-frontend 分支）。

对齐 2026-10-08 老板信息架构「作业向导并进柜」后新增/改版的这些行为：
  柜页双视图
  · 点柜号 → 同一页切到柜作业视图（**不跳旧版**，也不新开窗口）
  · 柜作业视图里的「← 柜列表」能切回；有未保存改动会拦一下
  · 建完柜自动进作业（不让人手动再点一次柜号）
  · 整页没有一处跳旧版的链接/开窗
  照片库批次子视图
  · 「照片/批次」两视图同页切换；批次视图行内「查看」回到照片视图且带上批次筛选
  筛选标签行（三页通用）
  · 筛完条件常显、可单个摘掉、默认值不进标签行
  筛选方案（照片库）
  · 保存当前筛选 → localStorage → 重新套用结果一致
  · 侧栏一级项恰好 5 个（对齐旧版导航）

⚠️ 隔离实例 8810 / CDP 9370，不碰 8765。
跑法：python tools/productlib/checks/cdp_vue_containers.py
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
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuect_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuect_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/containers'
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
    b = '----plct' + str(int(time.time()))
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

# ── 造数据：两个柜，各导一次照片（→ 两个批次）──
from PIL import Image  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue_ct')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)

CIDS = []
for no, n in (('VC1', 2), ('VC2', 3)):
    code, c = _req('POST', '/api/containers', {'container_no': no, 'inspector': 'cdp'})
    cid = (c or {}).get('id')
    CIDS.append(cid)
    chk('0 建柜 ' + no, bool(cid), cid)
    files = []
    for i in range(n):
        p = os.path.join(tmpd, '%s_%02d.jpg' % (no, i))
        Image.new('RGB', (800, 600), (80 + i * 30, 140, 170)).save(p)
        files.append(('files', p, os.path.basename(p)))
    code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
    chk('0b %s 上传 %d 张' % (no, n), code == 200 and (r or {}).get('added') == n,
        '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:80]))

cts = (http_json('/api/containers') or {}).get('items') or []
chk('1 /api/containers 两个柜', len([c for c in cts
                                   if c.get('container_no') in ('VC1', 'VC2')]) == 2,
    len(cts))
chk('1b /api/batches 两个批次', len((http_json('/api/batches') or {}).get('items') or []) == 2)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,1200', URL],
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
        await asyncio.sleep(7.5)
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

        async def set_input(sel, idx, val):
            return await js("""(()=>{const c=document.querySelector(%s);
                const i=c&&c.querySelectorAll('input')[%d];
                if(!i) return false;
                const s=Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype,'value').set;
                s.call(i,%s); i.dispatchEvent(new Event('input',{bubbles:true}));
                return true;})()"""
                            % (json.dumps(sel), idx, json.dumps(val)))

        async def click_in_row(kw, label):
            return await js("""(()=>{const rs=[...document.querySelectorAll(
                '.ct-page .el-table__body-wrapper tr')];
                for(const r of rs){ if(!r.innerText.includes(%s)) continue;
                    const b=[...r.querySelectorAll('button')]
                      .find(x=>(x.innerText||'').trim()===%s);
                    if(b){b.click(); return true;}}}
                return false;})()""" % (json.dumps(kw), json.dumps(label)))

        # ════ ① 柜列表视图 ════
        chk('2 标题带「柜」', '柜' in str(await js('document.title')),
            await js('document.title'))
        n_row = await js("document.querySelectorAll('.ct-page .el-table__body-wrapper tr').length")
        chk('3 柜列表渲染出两行', n_row == 2, n_row)
        chk('4 侧栏一级项恰好 5 个（对齐旧版导航）',
            await js("document.querySelectorAll('.el-menu-item').length") == 5,
            await js("JSON.stringify([...document.querySelectorAll('.el-menu-item')]"
                     ".map(e=>e.innerText.trim()))"))
        chk('4b 次级入口区有三个（批次/新产品确认/柜作业）',
            await js("document.querySelectorAll('.app-sub .sub-i').length") == 3,
            await js("JSON.stringify([...document.querySelectorAll('.app-sub .sub-i')]"
                     ".map(e=>e.innerText.trim()))"))

        # 柜号本身可点（不是只有按钮能进）
        chk('5 柜号是可点的链接', await js(
            "document.querySelectorAll('.ct-page .clink').length") == 2,
            await js("document.querySelectorAll('.ct-page .clink').length"))

        # ════ ② 点柜号进柜作业（同页第二视图，不跳旧版）════
        await js("""(()=>{const a=[...document.querySelectorAll('.ct-page .clink')]
            .find(x=>x.innerText.trim()==='VC1'); if(a) a.click();})()""")
        await asyncio.sleep(3.5)
        await drain()
        chk('6 点柜号 → 同页切到柜作业视图',
            await js("document.querySelectorAll('.wizard-page').length") == 1,
            await js("!!document.querySelector('.wizard-page')"))
        chk('6b 柜列表视图已隐藏（真的切了不是叠加）',
            await js("document.querySelectorAll('.ct-page .el-table').length") == 0,
            await js("document.querySelectorAll('.ct-page .el-table').length"))
        chk('6c 仍是 /app/containers（没跳路由）',
            '/app/containers' in str(await js('location.pathname')),
            await js('location.pathname'))
        chk('7 柜作业里锚点柜 = VC1（选对柜了）',
            'VC1' in str(await js("document.body.innerText")),
            [x for x in str(await js("document.body.innerText")).split('\n')
             if 'VC' in x][:2])

        # ════ ③ 切回列表 ════
        await js("""(()=>{const b=[...document.querySelectorAll('.wizard-page button')]
            .find(x=>(x.innerText||'').trim()==='← 柜列表'); if(b) b.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        chk('8 「← 柜列表」切回列表视图',
            await js("document.querySelectorAll('.wizard-page').length") == 0
            and await js("document.querySelectorAll('.ct-page .el-table').length") == 1,
            'wiz=%s tbl=%s' % (await js("document.querySelectorAll('.wizard-page').length"),
                               await js("document.querySelectorAll('.ct-page .el-table').length")))

        # ════ ④ 全站无跳旧版 ════
        n_old = await js("""(()=>{let n=0;
            for(const a of document.querySelectorAll('a')){
                const h=a.getAttribute('href')||'';
                if(h==='/'||h.startsWith('/#')) n++;}
            return n;})()""")
        chk('9 侧栏内除「返回旧版」外无跳旧版链接', n_old <= 1, n_old)
        chk('9b 源码里不再有 window.open 跳旧版（页面里点不出第二个窗口）',
            await js("document.querySelectorAll('.ct-page a[target=_blank]').length") == 0)

        # ════ ⑤ 筛选标签行 ════
        chk('10 未筛选时没有标签行',
            await js("document.querySelectorAll('.ct-page .chips').length") == 0,
            await js("document.querySelectorAll('.ct-page .chips').length"))
        await set_input('.ct-page .el-input', 0, 'VC1')
        await asyncio.sleep(0.5)
        await js("""(()=>{const i=document.querySelector('.ct-page .el-input input');
            i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
            i.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',bubbles:true}));})()""")
        await asyncio.sleep(2.5)
        await drain()
        chips = await js("""(()=>{const c=document.querySelector('.ct-page .chips');
            return c?c.innerText.replace(/\\n/g,' '):'';})()""")
        chk('11 筛完出现标签行且写明条件', 'VC1' in str(chips), chips)
        chk('11b 列表同步只剩 1 行',
            await js("document.querySelectorAll('.ct-page .el-table__body-wrapper tr').length") == 1,
            await js("document.querySelectorAll('.ct-page .el-table__body-wrapper tr').length"))
        # 点标签上的 × 清掉
        await js("""(()=>{const t=document.querySelector('.ct-page .chips .el-tag');
            const c=t&&t.querySelector('.el-tag__close'); if(c) c.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        chk('12 点标签 × → 条件清掉、标签行消失、回 2 行',
            await js("document.querySelectorAll('.ct-page .chips').length") == 0
            and await js("document.querySelectorAll('.ct-page "
                         ".el-table__body-wrapper tr').length") == 2,
            'chips=%s rows=%s' % (
                await js("document.querySelectorAll('.ct-page .chips').length"),
                await js("document.querySelectorAll('.ct-page "
                         ".el-table__body-wrapper tr').length")))

        # ════ ⑥ 建柜后自动进作业 ════
        await js("""(()=>{const b=[...document.querySelectorAll('.ct-page button')]
            .find(x=>(x.innerText||'').replace(/\s/g,'')==='新建柜'); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        await set_input('.ct-page .el-dialog .el-input', 0, 'VC9')
        await js("""(()=>{const b=[...document.querySelectorAll('.ct-page .el-dialog button')]
            .find(x=>(x.innerText||'').trim()==='创建'); if(b) b.click();})()""")
        await asyncio.sleep(4.0)
        await drain()
        chk('13 建柜后自动进该柜的作业视图（不让人再点一次柜号）',
            await js("document.querySelectorAll('.wizard-page').length") == 1
            and 'VC9' in str(await js('document.body.innerText')),
            'wiz=%s' % await js("document.querySelectorAll('.wizard-page').length"))

        # ════ ⑦ 照片库批次子视图 ════
        await cmd('Page.navigate', {'url': BASE + '/app/photos'})
        await asyncio.sleep(7.5)
        await drain()
        # ⚠️ el-radio-button 渲染的是 <label><span class="el-radio-button__inner">，
        #    **不是 <button>** —— 按 button 找恒空。
        pv_btn = await js("""(()=>{const b=[...document.querySelectorAll(
            '.photos-page .pvgroup .el-radio-button__inner')]
            .map(x=>x.innerText.trim()); return JSON.stringify(b);})()""")
        chk('14 照片库有「照片/批次」两个子视图',
            '照片' in str(pv_btn) and '批次' in str(pv_btn), pv_btn)
        await js("""(()=>{const b=[...document.querySelectorAll(
            '.photos-page .pvgroup .el-radio-button__inner')]
            .find(x=>x.innerText.trim()==='批次'); if(b) b.click();})()""")
        await asyncio.sleep(4.0)
        await drain()
        n_bt = await js("""(()=>{const c=document.querySelector('.photos-page .batch-table');
            return c?c.querySelectorAll('.el-table__body-wrapper tr').length:-1;})()""")
        chk('15 切到批次视图 → 批次表出现且与后端同源', n_bt == 2, n_bt)
        chk('15b 照片网格已隐藏（真切换）',
            await js("!!document.querySelector('.photos-page .shot-grid')") is False)
        await js("""(()=>{const r=[...document.querySelectorAll(
            '.photos-page .batch-table .el-table__body-wrapper tr')][0];
            const b=r&&[...r.querySelectorAll('button')]
              .find(x=>(x.innerText||'').trim()==='查看'); if(b) b.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        chk('16 批次行「查看」回照片视图并带上批次筛选',
            await js("!!document.querySelector('.photos-page .shot-grid')") is True
            and await js("!!document.querySelector('.photos-page .chips')") is True,
            'grid=%s chips=%s' % (
                await js("!!document.querySelector('.photos-page .shot-grid')"),
                await js("!!document.querySelector('.photos-page .chips')")))

        # ════ ⑧ 筛选方案保存/复用 ════
        await js("""(()=>{const b=[...document.querySelectorAll('.photos-page button')]
            .find(x=>(x.innerText||'').trim()==='筛选方案 ▾'); if(b) b.click();})()""")
        await asyncio.sleep(1.2)
        await js("""(()=>{const it=[...document.querySelectorAll('.el-dropdown-menu__item')]
            .find(x=>(x.innerText||'').includes('保存当前筛选')); if(it) it.click();})()""")
        await asyncio.sleep(2.0)
        await drain()
        # ElMessageBox.prompt 的输入框
        ok_save = await js("""(()=>{const i=document.querySelector('.el-message-box input');
            if(!i) return false;
            const s=Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
            s.call(i,'我的常用视图'); i.dispatchEvent(new Event('input',{bubbles:true}));
            return true;})()""")
        await asyncio.sleep(0.8)
        await js("""(()=>{const b=[...document.querySelectorAll('.el-message-box button')]
            .find(x=>(x.innerText||'').trim()==='保存'); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        saved = await js("localStorage.getItem('plPhotoFilters')")
        chk('17 保存筛选方案落 localStorage',
            ok_save and '我的常用视图' in str(saved), str(saved)[:140])

        # 清掉当前筛选，再套用方案，结果应与保存时一致
        await js("""(()=>{const b=[...document.querySelectorAll('.photos-page .chips button')]
            .find(x=>(x.innerText||'').includes('全清')); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        chk('17b 全清 → 标签行消失',
            await js("document.querySelectorAll('.photos-page .chips').length") == 0,
            await js("document.querySelectorAll('.photos-page .chips').length"))
        await js("""(()=>{const b=[...document.querySelectorAll('.photos-page button')]
            .find(x=>(x.innerText||'').trim()==='筛选方案 ▾'); if(b) b.click();})()""")
        await asyncio.sleep(1.2)
        await js("""(()=>{const it=[...document.querySelectorAll('.el-dropdown-menu__item')]
            .find(x=>(x.innerText||'').includes('我的常用视图')); if(it) it.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        chk('18 套用方案 → 条件回到保存时的样子',
            await js("!!document.querySelector('.photos-page .chips')") is True,
            await js("""(()=>{const c=document.querySelector('.photos-page .chips');
                return c?c.innerText.replace(/\\n/g,' '):'无';})()"""))

        chk('19 全程无 JS 异常', not excs, json.dumps(excs, ensure_ascii=False)[:300])
        return not fails


ok = asyncio.run(main())
edge.terminate()
srv.terminate()
print(('FAIL %d 项' % len(fails)) if fails else 'PASS')
sys.exit(0 if ok and not fails else 1)
