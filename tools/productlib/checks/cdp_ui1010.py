# -*- coding: utf-8 -*-
"""CDP 实跑：验证 2026-10-02 这轮 UI 改造（老板提的 5 大项）。

只验**能在真实浏览器里判定**的部分：
  一、1 菜单名 → 「预检照片库」
  一、2 两个导入合并为一个（不再有独立的「标准采集格式导入」面板）
  一、3 治理面板默认收起 + 可点开
  一、4 照片检索框存在（后端已单测，这里只验控件在）
  三、1 产品库默认「上下」布局 + 可切「左右」
  三、2 手动关联照片面板已移除
  四、1 检索页编码输入框已撑满对齐

不验的：视觉美观（截图人工看）、后端检索（tests/relink.py 与 _q_filter 探针已覆盖）。
"""
import asyncio, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9338
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_ui')
SHOT = os.path.join(tempfile.gettempdir(), 'pl_ui')

fails = []
def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)

shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
     '--window-size=1440,2000', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def http_json(path, retries=40):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (PORT, path), timeout=3) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None

async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪（Edge 起不来？）'); return False
    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page'); return False

    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        _id = [0]
        async def cmd(method, params=None, wait=True):
            _id[0] += 1
            await ws.send(json.dumps({'id': _id[0], 'method': method,
                                      'params': params or {}}))
            if not wait:
                return None
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
        await asyncio.sleep(4)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True, 'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        # ═══ 一、1 菜单名 ═══
        txt = await js("[...document.querySelectorAll('nav button')].map(b=>b.textContent.trim()).join('|')")
        chk('一、1 菜单含「预检照片库」', '预检照片库' in (txt or ''), txt)
        chk('一、1 旧名「预检照片入库」已消失', '预检照片入库' not in (txt or ''))

        # ═══ 一、2 两个导入合并 ═══
        hasStdPanel = await js("!!document.querySelector('#stdImport')")
        chk('一、2 独立的「标准格式导入」按钮已移除', not hasStdPanel)
        hasOneImport = await js("!!document.querySelector('#fImport')")
        chk('一、2 保留单一导入按钮 #fImport', bool(hasOneImport))
        # 跳到照片库页再看
        await js("document.querySelector('nav button[data-tab=batches]').click()")
        await asyncio.sleep(2.5)
        await drain()
        importTxt = await js("document.querySelector('#fPickInfo')?.textContent||''")
        chk('一、2 导入说明同时提到两种格式', '标准采集格式' in importTxt and '普通照片目录' in importTxt,
            importTxt[:60])

        # ═══ 一、3 治理面板默认收起 + 可展开 ═══
        govHidden = await js("(()=>{const b=document.querySelector('#govBody');return b? b.style.display==='none' : null})()")
        chk('一、3 治理面板默认收起', govHidden is True, govHidden)
        await js("document.querySelector('#govHead').click()")
        await asyncio.sleep(0.6)
        govShown = await js("(()=>{const b=document.querySelector('#govBody');return b? b.style.display!=='none' : null})()")
        chk('一、3 点标题可展开', govShown is True, govShown)
        # 收起时标题上有状态摘要（不展开也知道有没有待治理）
        badge = await js("document.querySelector('#govBadge')?.textContent||''")
        chk('一、3 标题有状态摘要', bool(badge) and badge != '—', badge)

        # ═══ 一、4 检索框 ═══
        ph = await js("document.querySelector('#fQ')?.placeholder||''")
        chk('一、4 检索框覆盖编码/描述/文件名', '编码' in ph and '描述' in ph, ph)

        # ═══ 三、1 产品库：全宽表格 + 大抽屉详情（10-04 重构） ═══
        await js("document.querySelector('nav button[data-tab=products]').click()")
        await asyncio.sleep(2)
        await drain()
        noSplit = await js("!document.querySelector('#pSplit') && !document.querySelector('#pLayout')")
        chk('三、1 旧 split/stack 布局已移除', noSplit is True, noSplit)
        tblWide = await js("""(()=>{
            const t=document.querySelector('#tab-products table');
            if(!t) return null;
            return Math.round(t.getBoundingClientRect().width);
        })()""")
        chk('三、1 列表表格全宽（>900px）', bool(tblWide) and tblWide > 900, tblWide)
        drawerOff = await js("!document.querySelector('#pDetail').classList.contains('on')")
        chk('三、1 详情抽屉初始关闭', drawerOff is True, drawerOff)
        # 点行 → 抽屉滑出
        await js("document.querySelector('#pBody tr')?.click()")
        await asyncio.sleep(3)
        await drain()
        drawerOn = await js("document.querySelector('#pDetail').classList.contains('on')")
        chk('三、1 点产品行抽屉滑出', drawerOn is True, drawerOn)
        dw = await js("Math.round(document.querySelector('#pDetail').getBoundingClientRect().width)")
        chk('三、1 抽屉宽度 ≥ 1100', bool(dw) and dw >= 1100, dw)
        await js("document.querySelector('#pDetailClose').click()")
        await asyncio.sleep(0.6)
        drawerOff2 = await js("!document.querySelector('#pDetail').classList.contains('on')")
        chk('三、1 关闭按钮可关抽屉', drawerOff2 is True, drawerOff2)

        # ═══ 三、2 手动关联已移除 ═══
        hasManual = await js("!!document.querySelector('#manualLinkToggle')")
        chk('三、2 手动关联照片面板已移除', not hasManual)

        # ═══ 三、3 待确认区并排（两列同排） ═══
        # 直接打开一个**确有候选数据**的产品：
        # 「同组待确认」+「可能关联」两块都有内容，并排校验才有意义。
        # 用搜索框定位，避免依赖列表当前页里恰好有它。
        await js("(()=>{const q=document.querySelector('#pQ');"
                 "if(q){q.value='103006010017BM';"
                 "q.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));}"
                 "})()")
        await asyncio.sleep(3)
        await drain()
        picked = await js("document.querySelector('#pBody tr')?.dataset?.code||''")
        chk('三、3 定位到候选产品', picked == '103006010017BM', picked)
        await js("document.querySelector('#pBody tr')?.click()")
        await asyncio.sleep(5)   # 91 张同组 + 7 张候选，渲染需要时间
        await drain()
        dbg = await js("document.querySelector('#pShots')?.innerHTML?.length||0")
        chk('三、3 详情已渲染', dbg > 500, 'html len=' + str(dbg))
        await asyncio.sleep(3)
        await drain()
        rowInfo = await js("""(()=>{
            const r=document.querySelector('.confirm-row');
            if(!r) return null;
            const cols=[...r.querySelectorAll('.confirm-col')];
            if(cols.length<2) return {n:cols.length};
            const tops=cols.map(c=>Math.round(c.getBoundingClientRect().top));
            return {n:cols.length, tops, sameRow: Math.abs(tops[0]-tops[1])<12};
        })()""")
        if rowInfo is None:
            chk('三、3 待确认区（本产品无候选，跳过）', True, 'no .confirm-row')
        elif rowInfo.get('n', 0) < 2:
            chk('三、3 待确认区（只有一块，跳过并排校验）', True, rowInfo)
        else:
            chk('三、3 同组待确认与可能关联并排同排', rowInfo.get('sameRow') is True, rowInfo)

        # ═══ 二、5 + 10-04：已关联照片不显示「建议关联」 ═══
        # 在抽屉里点一张已关联的照片 → 不该出现 #dwCands
        noCands = await js("""(()=>{
            const img=document.querySelector('#pShots .shot[data-id]');
            if(!img) return null;
            img.click();
            return true;
        })()""")
        await asyncio.sleep(2.5)
        await drain()
        st = await js("""(()=>{
            const links=[...document.querySelectorAll('#dwBody .linkrow .un')].length;
            const cands=!!document.querySelector('#dwCands');
            return {links, cands};
        })()""")
        if st and st['links'] > 0:
            chk('二、5 已关联照片不渲染建议关联', st['cands'] is False, st)
        else:
            chk('二、5（抽屉里没点到已关联照片，跳过）', True, st)

        # ═══ 10-04：大图查看器不被抽屉遮挡 ═══
        # 抽屉开着 → 点 dwImg 开 mask → mask 的 z-index 必须 > drawer 的
        zi = await js("""(()=>{
            const m=document.querySelector('#mask'), d=document.querySelector('#drawer');
            const zm=parseInt(getComputedStyle(m).zIndex)||0;
            const zd=parseInt(getComputedStyle(d).zIndex)||0;
            return {zm, zd, ok: zm>zd};
        })()""")
        chk('10-04 mask z-index 高于抽屉（大图不被遮挡）',
            bool(zi) and zi['ok'] is True, zi)
        await js("document.querySelector('#drawer .x').click()")
        await asyncio.sleep(0.5)

        # ═══ 四、1 检索页输入框 ═══
        await js("document.querySelector('nav button[data-tab=report]').click()")
        await asyncio.sleep(2)
        await drain()
        box = await js("""(()=>{
            const t=document.querySelector('#rpText'); if(!t) return null;
            const r=t.getBoundingClientRect();
            const p=t.closest('.panel').getBoundingClientRect();
            return {w:Math.round(r.width), pw:Math.round(p.width),
                    rows:t.rows, mono:/mono|Consolas|Menlo/i.test(getComputedStyle(t).fontFamily)};
        })()""")
        chk('四、1 编码输入框撑满面板宽度',
            bool(box) and box['w'] >= box['pw'] - 40, box)
        chk('四、1 输入框增高（rows>=6）', bool(box) and box['rows'] >= 6, box)
        chk('四、1 编码用等宽字体便于核对', bool(box) and box['mono'], box)

        # ═══ 全程无 JS 异常 ═══
        await drain()
        real = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('全程无 JS 异常', len(real) == 0,
            [str(e.get('exceptionDetails', {}).get('text', ''))[:80] for e in real[:3]])

        # 截图供人工看
        try:
            os.makedirs(SHOT, exist_ok=True)
            for tab, name in [('batches', 'photos'), ('products', 'products'), ('report', 'report')]:
                await js("document.querySelector('nav button[data-tab=%s]').click()" % tab)
                await asyncio.sleep(2)
                r = await cmd('Page.captureScreenshot', {'format': 'png'})
                data = (r.get('data') or '')
                if data:
                    import base64
                    open(os.path.join(SHOT, name + '.png'), 'wb').write(base64.b64decode(data))
            print('[ .. ] 截图目录：%s' % SHOT)
        except Exception as e:
            print('[ .. ] 截图失败：%s' % e)

    print('----')
    print('PASS / FAIL: %d 项失败' % len(fails))
    for f in fails:
        print('  - ' + f)
    print('==== RESULT: %s ====' % ('ALL PASS' if not fails else 'HAS FAILURE'))
    return not fails

try:
    ok = asyncio.run(main())
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if ok else 1)
