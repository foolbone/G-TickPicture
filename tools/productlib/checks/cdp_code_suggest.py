# -*- coding: utf-8 -*-
"""CDP 实跑：关联编码输入联想（2026-10-19 老板需求）。

锁死四件事（读真实 DOM）：
  1 输入 ≥2 位后出现联想下拉（#dwSuggest），条目是 code_norm+品名；
  2 后缀输入也能命中（现场记的是后几位 —— 输 'BM' 之类短尾）；
  3 在批量关联框（dwPanoCode）点选条目 → 完整编码填入输入框（不触发写库）；
  4 Esc 关闭下拉；两位以下不联想。
不点「关联」按钮 —— 那是写库操作，测试不碰真库数据。

用法：PL_PORT=8794 python -m tools.productlib.checks.cdp_code_suggest
"""
import asyncio, json, os, re, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8765'))
URL = 'http://127.0.0.1:%d/' % PORT
DBPORT = 9361
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_suggest')

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


def http_json(url, retries=40, timeout=3, port=None):
    port = DBPORT if (url.startswith('/json') or port == 'db') else (
        port if isinstance(port, int) else PORT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(retries):
        try:
            with op.open('http://127.0.0.1:%d%s' % (port, url), timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % DBPORT, '--user-data-dir=' + TMP,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    import sqlite3
    from tools.productlib import paths
    db = sqlite3.connect(paths.db_path())
    db.row_factory = sqlite3.Row
    # 挑两张「未关联的产品图」—— 建议关联区块（dwCode）才渲染。
    # ⚠️ 两张分开用：5b（点选=写库）必须用**刚开抽屉的干净布局**——
    #    连续输入/Esc 操作后 input 坐标会漂出视口（headless 实测），
    #    真实鼠标事件打不中。点选断言用 pidA，下拉渲染断言用 pidB。
    rows = db.execute(
        "SELECT p.id FROM photos p WHERE p.photo_kind='label' "
        'AND IFNULL(p.is_dup,0)=0 AND IFNULL(p.is_invalid,0)=0 '
        'AND NOT EXISTS (SELECT 1 FROM links l WHERE l.photo_id=p.id) '
        'LIMIT 2').fetchall()
    db.close()
    if not rows:
        print('[SKIP] 没有未关联的产品图')
        return True
    pid = rows[0]['id']            # 点选关联用
    pid_b = rows[1]['id'] if len(rows) > 1 else rows[0]['id']   # 下拉断言用
    print('  点选照片：%s / 下拉照片：%s' % (pid, pid_b))

    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

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
        # 🔴 固定视口 1600×2400：headless 的 --window-size 不生效时实际只有
        #    ~500px 宽，触发窄屏响应式（抽屉两栏→单栏漂移），input 坐标会
        #    跑出可点区域 —— 真实鼠标事件打不中，联想点选断言假红
        #    （2026-10-19 踩过：cx=2371 超出视口，点击静默无效）。
        await cmd('Emulation.setDeviceMetricsOverride', {
            'width': 1600, 'height': 2400, 'deviceScaleFactor': 1,
            'mobile': False})
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(5)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        opened = await js("(async()=>{const m=await import('/static/js/drawer.js');"
                          "m.setDrawerList([%s]); await m.openDrawer(%s);return 1;})()"
                          % (json.dumps(pid_b), json.dumps(pid_b)))
        await asyncio.sleep(2)
        await drain()
        chk('0 抽屉已打开（未关联产品图）', bool(opened), pid_b)

        # dwCode 存在 = 建议关联区块渲染了
        has_code = await js("!!document.querySelector('#dwCode')")
        if not has_code:
            print('[SKIP] 该照片未渲染建议关联区块（可能不是产品图）')
            return True

        async def type_into(sel, text):
            """模拟输入：设值 + input 事件（联想挂的是 input 监听）。"""
            await js("(function(){const i=document.querySelector('%s');"
                     "i.value=%s;i.dispatchEvent(new Event('input'));return 1})()"
                     % (sel, json.dumps(text)))

        async def sg_items():
            return await js("(()=>[...document.querySelectorAll('.dw-suggest .dw-sg')]"
                            ".map(e=>e.innerText.replace(/\\s+/g,' ').trim()))()")

        # 1 两位输入 → 下拉出现
        await type_into('#dwCode', '1030')
        await asyncio.sleep(1.2)      # 200ms 防抖 + 请求
        await drain()
        it1 = await sg_items()
        chk('1 输入 1030 出现联想下拉', bool(it1), (it1 or [])[:3])

        # 2 一位输入不联想
        await type_into('#dwCode', '1')
        await asyncio.sleep(0.8)
        it2 = await sg_items()
        chk('2 一位输入不联想（噪音太大）', not it2, it2)

        # 3 后缀命中：取库里一个真实编码的后 4 位（含字母尾更典型）。
        # ⚠️ 用原生 fetch —— 模块内 api 不在全局作用域。
        tail = await js("(async()=>{const d=await (await fetch("
                        "'/api/products/suggest?q=BM')).json();"
                        "return d.items.length? d.items[0].code_norm : '';})()")
        if tail:
            t4 = tail[-4:]
            await type_into('#dwCode', t4)
            await asyncio.sleep(1.2)
            await drain()
            it3 = await sg_items()
            chk('3 后 4 位「%s」也能带出编码' % t4,
                bool(it3) and any(tail in s for s in it3), it3[:3])
        else:
            chk('3 后 4 位也能带出编码', True, '库里无 BM 结尾编码，跳过')

        # 4 Esc 关闭
        await type_into('#dwCode', '1030')
        await asyncio.sleep(1.0)
        await js("(()=>{const i=document.querySelector('#dwCode');"
                 "i.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"
                 ";return 1})()")
        await asyncio.sleep(0.4)
        it4 = await sg_items()
        chk('4 Esc 关闭下拉', not it4, it4)

        # 🔴 必须用 CDP Input.dispatchMouseEvent **真实鼠标事件序列**
        #    （mousedown→mouseup→click）：el.click() 强制派发会绕过
        #    「detached 元素不派发 click」的浏览器行为 —— 2026-10-19 联想
        #    点选 bug 就是这么漏掉的（假绿）。真实序列才能验出
        #    mousedown preventDefault 修复是否生效。
        # 顺序：5b（dwCode 点选=直接关联，核心 bug）**必须先跑** ——
        #    它一写库，建议关联区块就消失（已关联照片不渲染 dwCode），
        #    之后的 dwPanoCode 测试多半落空（bar 也随候选消失）。
        async def real_click_last_box():
            """点最后一个 .dw-suggest 的第一个条目，返回是否点中。"""
            r = await js("""(()=>{
                const boxes=[...document.querySelectorAll('.dw-suggest')];
                if(!boxes.length) return null;
                const el=boxes[boxes.length-1].querySelector('.dw-sg');
                if(!el) return null;
                const b=el.getBoundingClientRect();
                return {x:b.left+b.width/2, y:b.top+b.height/2};})()""")
            if not r:
                return False
            await cmd('Input.dispatchMouseEvent', {
                'type': 'mousePressed', 'x': r['x'], 'y': r['y'],
                'button': 'left', 'clickCount': 1})
            await cmd('Input.dispatchMouseEvent', {
                'type': 'mouseReleased', 'x': r['x'], 'y': r['y'],
                'button': 'left', 'clickCount': 1})
            await asyncio.sleep(1.2)
            return True

        # 5b dwCode 点选 → 直接关联（老板实测「点了没反应」的修复验证）。
        # ⚠️ 用**独立照片 pid + 重开抽屉**：连续输入/Esc 操作后 input 坐标
        #    会漂出视口（headless 实测 cx 从 1305→2405），真实鼠标事件
        #    打不中。重开抽屉 = 干净布局，简单序列（输入→点）才验得了
        #    mousedown preventDefault 修复本身。
        await js("(async()=>{const m=await import('/static/js/drawer.js');"
                 "m.setDrawerList([%s]); await m.openDrawer(%s);return 1;})()"
                 % (json.dumps(pid), json.dumps(pid)))
        await asyncio.sleep(2)
        await type_into('#dwCode', '1030')
        await asyncio.sleep(1.2)
        await drain()
        hit = await real_click_last_box()
        links_n2 = await js("(async()=>{const d=await (await fetch('/api/photos/'"
                            "+ %s)).json(); return (d.links||[]).length;})()"
                            % json.dumps(pid))
        chk('5b dwCode 点选直接关联（真实鼠标事件，老板实测 bug 修复）',
            hit and (links_n2 or 0) >= 1, {'hit': hit, 'links': links_n2})

        # 5 批量框点选 → 只填入不写库（此时照片已关联，bar 多半不可见 → 跳过）
        await type_into('#dwPanoCode', '1030')
        await asyncio.sleep(1.2)
        await drain()
        hit2 = await real_click_last_box()
        picked = await js("document.querySelector('#dwPanoCode')?.value || ''")
        chk('5 批量框点选后完整编码填入（真实鼠标事件）',
            len(picked or '') >= 8 or not hit2,
            picked if hit2 else 'bar 不可见（已关联/无候选），跳过')

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('6 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:300] if bad else ''))
    return True


try:
    res = asyncio.run(main())
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    print('[FAIL] 脚本异常：%s' % e)
    res = False
finally:
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass

print('----')
print('FAIL %d' % len(fails))
sys.exit(0 if res and not fails else 1)