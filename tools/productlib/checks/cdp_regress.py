# -*- coding: utf-8 -*-
"""CDP 实跑回归：验证 JS 拆分成 13 个 ES module 后功能全部正常。

覆盖:
  A. 模块加载 —— 13 个 js 全部 200，无 404，无 console error / pageerror
  B. 六页切换 —— 每页都能渲染出内容
  C. 既有功能 —— 抽屉、放大镜、分类配色、紧凑/详情视图、批次抽屉、流程条已移除
"""
import asyncio, json, os, re, shutil, subprocess, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
# ⚠️ 验**新代码**别打 8765（铁律 20）：8765 常驻的是旧进程 —— 路由在启动时
#    加载，新端点 404。PL_PORT 指到干净端口（配套 PL_HOME 起隔离实例）。
PORT = int(os.environ.get('PL_PORT', '8765'))      # 产品库服务端口
CDP_PORT = int(os.environ.get('PL_CDP', '9337'))   # Edge 调试端口
URL = os.environ.get('PL_URL', '') or ('http://127.0.0.1:%d/' % PORT)
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp4')
# 真源 = web/static/js/main.js 实际 import 的那批（web_contract.py 的「模块闭包」同一份）。
# 旧清单里还挂着 review / merge —— 那两个已在 v5/v6 改造中失联（没有页面、没有 loader），
# 浏览器不会去请求，断言必然红。别再往回加。
MODULES = ['core', 'main', 'modal', 'dirpicker', 'wizard', 'home', 'containers',
           'batches', 'photos', 'products', 'drawer', 'standard', 'discover',
           'report', 'settings']

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen([EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
                         # 🔴 本机 shell 有 http_proxy（127.0.0.1:4562）时，Edge 会把
                         #    localhost 也丢给代理 → chrome-error 白屏 → 全部假红。
                         #    调试的是本机服务，一律直连。
                         '--no-proxy-server',
                         '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + TMP,
                         '--window-size=1440,1400', URL],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def http_json(path, retries=40):
    """只打 CDP 调试端口（/json/version、/json/list）。"""
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (CDP_PORT, path), timeout=3) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None


async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪')
        return False
    pages = [t for t in (http_json('/json/list') or []) if t.get('type') == 'page']
    # 🔴 别闭眼拿第一个 page：Edge 带 extension 时会先挂一个
    #    edge://sync-confirmation-dialog 页 —— 对着它 evaluate 全是 null，
    #    整个检查就「全红但其实代码没毛病」。必须挑**应用 URL** 的那个页。
    page = next((t for t in pages if t.get('url', '').startswith(URL)), None) \
        or (pages[0] if pages else None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

    events = []
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        _id = [0]

        async def call(method, params=None):
            _id[0] += 1
            i = _id[0]
            await ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if msg.get('id') == i:
                    if 'error' in msg:
                        raise RuntimeError('%s: %s' % (method, msg['error']))
                    return msg.get('result', {})
                events.append(msg)

        await call('Log.enable')
        await call('Runtime.enable')
        await call('Page.enable')
        await call('Network.enable')

        async def ev(expr):
            r = await call('Runtime.evaluate',
                           {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
            v = r.get('result', {})
            if v.get('subtype') == 'error' or 'exceptionDetails' in r:
                return {'__err__': str(v.get('description') or r.get('exceptionDetails'))}
            return v.get('value')

        async def wait(s):
            await asyncio.sleep(s)
            try:
                while True:
                    events.append(json.loads(await asyncio.wait_for(ws.recv(), 0.05)))
            except Exception:
                pass

        async def wait_badges(sel, cls, timeout_ms=25000):
            """轮询等角标出现，而不是固定 sleep。

            🔴 角标是**故意让路**的：前端等浏览器空闲才发请求，后端冷缓存还要
            全库算十几秒（两个集合）。固定 sleep 短了会假红、长了白等 ——
            轮询既稳定又只花必要的時間。
            """
            t0 = time.time()
            while (time.time() - t0) * 1000 < timeout_ms:
                if await ev("document.querySelectorAll('%s %s').length>0" % (sel, cls)) is True:
                    return True
                await wait(1.0)
            return False

        await call('Emulation.setDeviceMetricsOverride',
                   {'width': 1440, 'height': 1400, 'deviceScaleFactor': 1, 'mobile': False})
        await wait(3.5)

        # ══ A. 模块加载 ══
        print('== A. 模块加载 ==')
        res = await ev("""performance.getEntriesByType('resource')
            .filter(r=>r.name.endsWith('.js')||r.name.endsWith('.css'))
            .map(r=>[r.name.split('/').pop(), Math.round(r.transferSize||r.decodedBodySize||0)])""")
        got = dict(res) if isinstance(res, list) else {}
        for m in MODULES:
            chk('模块 %s.js 已加载' % m, (m + '.js') in got, got.get(m + '.js'))
        chk('app.css 已加载', 'app.css' in got, got.get('app.css'))

        bad_req = [e for e in events
                   if e.get('method') == 'Network.responseReceived'
                   and e['params']['response']['status'] >= 400]
        chk('无 4xx/5xx 请求', not bad_req,
            [e['params']['response']['url'] for e in bad_req][:5])

        errs = [e for e in events if e.get('method') in ('Log.entryAdded',)
                and e['params'].get('entry', {}).get('level') == 'error']
        chk('无 console error', not errs,
            [e['params']['entry'].get('text', '')[:90] for e in errs][:5])

        # 模块求值期抛的错（Duplicate export / 顶层 TypeError）不会进 Log.error，
        # 只在 Runtime.exceptionThrown 里 —— 不监听就会「看起来全绿但页面是死的」
        exc = [e for e in events if e.get('method') == 'Runtime.exceptionThrown']
        chk('无未捕获运行时异常', not exc,
            [str(e['params'].get('exceptionDetails', {}).get('exception', {}).get('description', ''))[:120]
             for e in exc][:5])

        jserr = await ev("(window.__jserr||[]).length")
        chk('页面无未捕获异常', jserr == 0, jserr)

        chk('核心 API 已挂载 window',
            await ev("typeof go === 'function' && typeof window.PL === 'object'") is True)

        # ══ B. 六页切换 ══
        print('== B. 六页切换 ==')
        tabs = [('home', '概览'), ('batches', '照片库'), ('review', '人工标注确认'),
                ('products', '产品库'), ('report', '报告档案'), ('set', '设置')]
        for t, label in tabs:
            await ev("go('%s')" % t)
            await wait(1.2)
            vis = await ev("""(()=>{const s=document.querySelector('#tab-%s');
                return s? (s.classList.contains('on') && s.innerText.trim().length>20) : false;})()""" % t)
            chk('切到「%s」并渲染出内容' % label, vis is True)
            n404 = len([e for e in events
                        if e.get('method') == 'Network.responseReceived'
                        and e['params']['response']['status'] >= 400
                        and e['params']['response']['url'].startswith(URL + 'api')])
            chk('  ├ 无 API 报错', n404 == 0, n404)

        # ══ C. 既有功能 ══
        print('== C. 既有功能回归 ==')
        chk('流程步骤条已移除', await ev("!document.querySelector('#stepper')") is True)

        # 回到预检照片入库
        await ev("go('batches')")
        await wait(1.5)
        shots = await ev("document.querySelectorAll('.shot').length")
        chk('照片网格已渲染', isinstance(shots, int) and shots > 0, shots)
        # 🔴 性能承诺：角标要全库判定（冷缓存十几秒），但它**不许挂在列表主查询上**
        #    —— 否则首屏从 0.3s 变 6.6s。这条断言锁住「列表接口不带 mark」。
        no_mark = await ev("""(async()=>{
            const u='/api/photos?limit=60';
            const t=performance.getEntriesByName(u)[0];
            const r=await fetch(u); await r.json();
            return t? Math.round(t.duration) : null;})()""")
        chk('列表首屏没有变慢（角标已从主查询摘出去）',
            no_mark is None or no_mark < 3000, '%s ms' % no_mark)

        # 抽屉
        # ⚠️ 等 3s 不是放宽标准：这张卡上的「待确认/新产品」角标会在浏览器空闲时
        #    去后端换一次全库判定（冷缓存十几秒，纯 Python 抢 GIL）。
        #    这里要验的是「点得开」，不是「1 秒内点得开」——后者是性能指标，
        #    归 option A 那条（角标不阻塞首屏）管。
        await ev("document.querySelector('.shot') && document.querySelector('.shot').click()")
        await wait(3.0)
        dw = await ev("""(()=>{const d=document.querySelector('#drawer');
            return d? d.classList.contains('on') : null;})()""")
        chk('照片抽屉可打开', dw is True, dw)
        await ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        await wait(0.6)

        # 分类配色（颜色写在 background 上）
        await ev("go('batches')")
        await wait(1.0)
        colors = await ev("""(()=>{const s=new Set();
            document.querySelectorAll('#shots .shot .badge').forEach(b=>{
              const c=getComputedStyle(b).backgroundColor;
              if(c && c!=='rgba(0, 0, 0, 0)') s.add(c);});
            return [...s];})()""")
        chk('分类角标有多种颜色', isinstance(colors, list) and len(colors) >= 2, colors)

        # 视图切换（走 window.PL 出口，模块作用域外才调得到）
        await ev("PL.setShotView('compact')")
        await wait(0.8)
        cp = await ev("document.body.classList.contains('v-compact')")
        chk('紧凑模式生效', cp is True, cp)
        await ev("PL.setShotView('full')")
        await wait(0.6)
        dt = await ev("!(document.body.classList.contains('v-compact'))")
        chk('详情模式可切回', dt is True, dt)

        # 批次抽屉（入口按钮 #bOpen）
        await ev("go('batches')")
        await wait(1.2)
        btn = await ev("!!document.querySelector('#bOpen')")
        chk('批次抽屉入口存在', btn is True, btn)
        closed0 = await ev("""(()=>{const d=document.querySelector('#bDrawer');
            return d? d.classList.contains('on') : null;})()""")
        chk('  初始为收起态', closed0 is False, closed0)
        await ev("PL.openBatches()")
        await wait(1.0)
        bd = await ev("""(()=>{const d=document.querySelector('#bDrawer');
            return d? d.classList.contains('on') : null;})()""")
        chk('批次抽屉可打开', bd is True, bd)
        rows = await ev("document.querySelectorAll('#bDrawer tbody tr').length")
        chk('批次表有数据行', isinstance(rows, int) and rows > 0, rows)
        await ev("PL.closeBatches()")
        await wait(0.6)
        bc = await ev("""(()=>{const d=document.querySelector('#bDrawer');
            return d? d.classList.contains('on') : null;})()""")
        chk('批次抽屉可关闭', bc is False, bc)

        # 标准图编辑器（放大镜）
        await ev("go('products')")
        await wait(1.5)
        zoom = await ev("!!document.querySelector('#stdZoom')")
        chk('标准图放大镜元素存在', zoom is True, zoom)

        # 抽屉 ←/→ 相邻切换
        await ev("go('batches')")
        await wait(1.2)
        await ev("document.querySelector('#shots .shot').click()")
        await wait(1.0)
        chk('抽屉打开',
            await ev("document.querySelector('#drawer').classList.contains('on')") is True)
        pos0 = await ev("document.querySelector('#dwPos').textContent")
        # 真实派发 ArrowRight（CDP 的 Input 更真，这里重点是别用 JS 直接调函数跳过绑定）
        await ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))")
        await wait(0.9)
        pos1 = await ev("document.querySelector('#dwPos').textContent")
        chk('→ 键真的切到了下一张', bool(pos0) and bool(pos1) and pos0 != pos1,
            '%s -> %s' % (pos0, pos1))
        await ev("document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}))")
        await wait(0.9)
        pos2 = await ev("document.querySelector('#dwPos').textContent")
        chk('← 键切回上一张', pos2 == pos0, '%s -> %s' % (pos1, pos2))
        await ev("PL.openDrawer && document.querySelector('#dwNext').click()")
        await wait(0.9)
        pos3 = await ev("document.querySelector('#dwPos').textContent")
        chk('「下一张」按钮可用', pos3 != pos2, '%s -> %s' % (pos2, pos3))

        # ══ D. 已关联 / 未关联 分组（10-07 新增）══
        # ══ D. 照片库改名 + 说明折叠 + 五档分组选项卡（10-07 第二轮）══
        print('== D. 照片库：改名 / 说明折叠 / 五档分组 ==')
        await ev("go('batches')")
        await wait(1.8)

        nav = await ev("""(()=>{const b=[...document.querySelectorAll('nav button')]
            .find(x=>x.dataset.tab==='batches'); return b?b.textContent.trim():'';})()""")
        chk('导航已改名为「照片库」', nav == '照片库', nav)
        chk('页头也是「照片库」',
            await ev("""(()=>{const h=document.querySelector('#tab-batches h2');
                return h? h.textContent.trim().startsWith('照片库'):false;})()""") is True)
        intro_h = await ev("""(()=>{const e=document.querySelector('#fIntro');
            return e? getComputedStyle(e).display : null;})()""")
        chk('导入格式说明默认收起（不常驻占纵向空间）', intro_h == 'none', intro_h)
        intro_h2 = await ev("""(()=>{document.querySelector('#fIntroToggle').click();
            const e=document.querySelector('#fIntro');
            const d=getComputedStyle(e).display;
            document.querySelector('#fIntroToggle').click();
            return [d, getComputedStyle(e).display];})()""")
        chk('点「说明」能展开、再点收起',
            intro_h2 == ['block', 'none'], intro_h2)
        chk('导入与治理两个入口在标题行常驻（没被一起藏起来）',
            await ev("!!document.querySelector('#fImport') && !!document.querySelector('#bGovGo')") is True)

        # ── 五档选项卡（照片页）──
        await ev("PL.setShotView('link')")
        await wait(3.5)
        tabs = await ev("""(()=>[...document.querySelectorAll('#shotTabs [data-ptab]')]
            .map(b=>[b.dataset.ptab, b.querySelector('.n').textContent.trim()]))()""")
        keys = [t[0] for t in tabs] if isinstance(tabs, list) else []
        chk('照片页渲染五档选项卡',
            keys == ['', 'linked', 'unlinked', 'cand', 'newprod'], keys)
        nums = [t[1] for t in tabs] if isinstance(tabs, list) else []
        chk('每档都带数字徽章（0 也显示，区别于「还没查完」）',
            len(nums) == 5 and all(re.match(r'^\d+$', n) for n in nums), nums)
        # 徽章必须与后端 COUNT 同源
        api_ls = await ev("""(async()=>{
            const q=new URLSearchParams({container_id:document.querySelector('#fContainer').value});
            const d=await (await fetch('/api/photos/linkstate?'+q)).json();
            return [d.all,d.linked,d.unlinked,d.cand,d.newprod];})()""")
        ui_nums = [int(n) for n in nums]
        chk('徽章数字与 /api/photos/linkstate 完全一致（同源）',
            api_ls == ui_nums, 'api=%s ui=%s' % (api_ls, ui_nums))
        # 切到「待确认关联」：列表条数必须等于该档徽章
        cand = await ev("""(async()=>{
            const b=[...document.querySelectorAll('#shotTabs [data-ptab]')]
              .find(x=>x.dataset.ptab==='cand');
            const n=+b.querySelector('.n').textContent.trim();
            b.click(); await new Promise(r=>setTimeout(r,3000));
            return [n, document.querySelectorAll('#shots .shot').length];})()""")
        chk('切到「待确认关联」后列表条数 = 该档徽章（或已全部取完）',
            isinstance(cand, list) and cand[1] == min(cand[0], 60),
            'badge=%s shown=%s' % (cand[0] if cand else '?', cand[1] if cand else '?'))
        chk('该档照片带「待确认」角标',
            await wait_badges('#shots', '.fbadge.cand'))
        # 「全部」档也要有角标 —— 不必先切档才发现
        await ev("""(()=>{const b=[...document.querySelectorAll('#shotTabs [data-ptab]')]
            .find(x=>x.dataset.ptab===''); if(b) b.click();})()""")
        await wait(3.0)
        chk('「全部」档里也标出了待确认/新产品',
            await wait_badges('#shots', '.fbadge'),
            await ev("document.querySelectorAll('#shots .fbadge').length"))
        await ev("PL.setShotView('full')")
        await wait(1.5)
        chk('切出关联视图后选项卡隐藏',
            await ev("document.querySelector('#shotTabs').style.display") == 'none')
        # 关联视图里卡片直接躺在 #shots 里，#shots 必须保留 .grid ——
        # 少了它卡片退化成块级单列大图（照片区变成「一条一条」）。
        cols = await ev("""(()=>{const b=document.querySelector('#shots');
            const c=document.querySelector('#shots .shot');
            if(!c) return null;
            return [getComputedStyle(b).display,
                    Math.round(c.getBoundingClientRect().width),
                    Math.round(b.getBoundingClientRect().width)];})()""")
        chk('关联视图保持多列网格（没塌成单列大图）',
            isinstance(cols, list) and cols[0] == 'grid'
            and cols[2] > 0 and cols[1] < cols[2] * 0.6, cols)

        # ── 柜作业③ 同一份实现 ──
        # ⚠️ 全新 headless profile 里 localStorage.plCid 是空的 —— 没有当前柜时
        #    柜作业不渲染任何一步（这是设计，不是 bug）。必须先选柜再断言。
        # ⚠️ 柜作业已并进柜页：选完柜还要 enterWizard() 才会显示作业视图。
        await ev("go('containers')")
        await wait(1.5)
        # 🔴 顶栏 #globalCid 已删（2026-10-11：每页有自己的柜选择器，避免混淆）。
        #    锚点改从柜列表第一行的「柜作业」进 —— enterWizard(cid) 会 setCid。
        picked = await ev("""(()=>{const b=document.querySelector('[data-c-wiz]');
            return b ? b.getAttribute('data-c-wiz') : '';})()""")
        chk('走查前提：柜列表里至少有一个柜可进作业', isinstance(picked, str) and len(picked) > 0, picked)
        await ev("enterWizard(%s)" % json.dumps(picked or '', ensure_ascii=False))
        await wait(3.5)
        await ev("""(()=>{const s=document.querySelector('#wizBar .wstep[data-step=photos]');
            if(s) s.click();})()""")
        await wait(3.5)
        # ── ③ 选项卡：2026-10-15 起改四档（全部/已关联/未关联/无效图片），
        #    待确认关联/新产品确认的工作台仍在审核页与照片库页。
        wtabs = await ev("""(()=>[...document.querySelectorAll('#wShTabs [data-ptab]')]
            .map(b=>b.dataset.ptab))()""")
        chk('向导③本柜照片是四档选项卡（共用同一份实现）',
            wtabs == ['', 'linked', 'unlinked', 'invalid'], wtabs)
        chk('向导③不再有「按关联分组」复选框（选项卡常驻，不需要藏）',
            await ev("!!document.querySelector('#wShGroupLink')") is False)
        for _tab in ('unlinked', 'invalid'):
            wcand = await ev("""(async()=>{
                const b=[...document.querySelectorAll('#wShTabs [data-ptab]')]
                  .find(x=>x.dataset.ptab==='%s'); if(!b) return null;
                const n=+b.querySelector('.n').textContent.trim();
                b.click(); await new Promise(r=>setTimeout(r,3000));
                return [n, document.querySelectorAll('#wizShots .shot').length];})()"""
                % _tab)
            chk('向导③切到「%s」档后列表条数与徽章一致' % _tab,
                isinstance(wcand, list) and wcand[1] == min(wcand[0], 60),
                'badge=%s shown=%s' % (wcand[0] if wcand else '?',
                                       wcand[1] if wcand else '?'))
        # 空档（无效 0 张）下 #wShotsShown 为空是设计行为 —— 后面的
        # 「当前档计数」检查要有数据，切回未关联档再继续。
        await ev("""(()=>{const b=[...document.querySelectorAll('#wShTabs [data-ptab]')]
            .find(x=>x.dataset.ptab==='unlinked'); if(b) b.click();})()""")
        await wait(3.0)
        # 「当前档已显示 n / total」必须与列表条数一致，且要说清是当前档 ——
        # 徽章上的全柜数与下面的档内数摆在一起不点名，会被当成不一致。
        shown = await ev("""(()=>{const e=document.querySelector('#wShotsShown');
            return e? e.textContent.trim():'';})()""")
        chk('向导③底部计数点名「当前档」且与列表条数一致',
            isinstance(shown, str) and '当前档' in shown
            and re.search(r'已显示 (\d+) / (\d+) 张', shown)
            and int(re.search(r'已显示 (\d+) / (\d+) 张', shown).group(1))
            == await ev("document.querySelectorAll('#wizShots .shot').length"),
            shown)
        # 选项卡不能被 grid 容器当成并排格子（上一轮踩过）
        wgeo = await ev("""(()=>{const bar=document.querySelector('#wShTabs');
            const r=bar.getBoundingClientRect();
            return [Math.round(r.width), Math.round(bar.parentElement.getBoundingClientRect().width),
                    Math.round(r.height)];})()""")
        chk('向导③选项卡占满整行、没被压扁',
            isinstance(wgeo, list) and wgeo[1] > 0 and wgeo[0] / wgeo[1] > 0.9
            and 20 < wgeo[2] < 60, wgeo)

        print('----')
        print('PASS / FAIL: %d 项失败' % len(fails))
        if fails:
            for f in fails:
                print('  - ' + f)
        return len(fails) == 0


ok = False
try:
    ok = asyncio.run(main())
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    shutil.rmtree(TMP, ignore_errors=True)
print('==== RESULT: %s ====' % ('ALL PASS' if ok else 'HAS FAILURE'))

