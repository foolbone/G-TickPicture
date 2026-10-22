# -*- coding: utf-8 -*-
"""CDP 实跑：候选照片「标记为无关联」前端（2026-10-05）。

老板要「可能关联的照片，查看确认没有关联的，可以标记为无关联，
之后不在可能关联的图片显示」。

store 与路由层已由 tests/cand_reject.py + curl 实跑锁死；本脚本只验
**浏览器里真的能用**，且专盯三个只有实跑才暴露的问题：
  1 每行真的有「无关联」按钮，且点了会弹确认框（不可逆动作必须有确认）；
  2 确认后这张照片**从 DOM 里消失**（不是只变灰、不是藏起来）；
  3 「已标记无关联」区块出现，且能**展开、能撤销**，撤销后照片回来；
  4 角标同步下降（老板在列表页也看得到数变了）；
  5 全程无 JS 异常（前端加按钮最容易漏 event 参数顺序 / undefined）。

⚠️ 端口：默认 8765 常常被开发中的服务占着，本脚本用 --port 指定的实例，
   并且**结束时把自己标记的数据清干净**（不留脏标记在老板的库里）。
"""
import asyncio, json, os, re, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8790'))
URL = 'http://127.0.0.1:%d/' % PORT
CDP_PORT = int(os.environ.get('PL_CDP', '9347'))
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_reject')
# 挑一个**只有同组候选、候选数少**的产品：破坏面最小，断言也最稳
PROD = os.environ.get('PL_CODE', '103006010003EMX')

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''),
          flush=True)  # flush：卡住时要能看出停在第几条，否则一片空白无从下手
    if not cond:
        fails.append(name)


def http_json(url, retries=40, port=CDP_PORT, timeout=3):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url if url.startswith('http')
                                        else 'http://127.0.0.1:%d%s' % (port, url),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None


def api(path, payload=None):
    """直接打后端（用来查真实状态 + 收尾清理）。"""
    url = 'http://127.0.0.1:%d%s' % (PORT, path)
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method='POST' if data else 'GET',
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + TMP,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪')
        return False
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
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(4)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        async def wait_rows(sel, n=1, tries=8):
            # ⚠️ tries 别开太大：每轮 sleep(1.0)，等不到的页面会把
            # 整个脚本拖成十几分钟且**零输出**（看不出卡在哪一步）。
            # 8 轮 × 1s 足够覆盖详情取数；宁可早失败也不要无声地慢。
            for i in range(tries):
                await asyncio.sleep(1.0)
                await drain()
                c = await js("document.querySelectorAll('%s').length" % sel)
                if (c or 0) >= n:
                    return c
            return 0

        # ⚠️ 取候选行必须**排除「已标记无关联」区块**（#rejBody）——
        #    那里面每行也用 .cand-item 渲染（复用样式），不排除的话，
        #    标记后它自己冒出来顶上一位，行数不减 → 「候选行数减少」假红。
        #    （CSS 没有「父级否定」选择器，只能在 JS 里 filter 掉。）
        CAND_JS = ("""(()=>[...document.querySelectorAll('#pShots .cand-item')]
            .filter(e=>!e.closest('#rejBody'))
            .map(e=>{const b=e.querySelector('[data-rej]')||e.querySelector('[data-sib-link]');
                     return b?(b.dataset.rej||b.dataset.sibLink):''}))()""")
        CAND_JS_N = ("""[...document.querySelectorAll('#pShots .cand-item')]
            .filter(e=>!e.closest('#rejBody')).length""")

        async def open_detail():
            """打开目标产品详情。

            ⚠️ **不能调 window.openProduct**（2026-10-05 踩过）：它是 ES module
            作用域里的函数，**不挂 window**，`window.openProduct` 是 undefined，
            `window.openProduct && ...` 整条变成空操作 —— 表现是脚本一路
            「跑完了」但 `.cand-item` 恒为 0，看起来像功能没实现。
            正解与 cdp_ui1007 一致：填搜索框 → 切 tab → 点表格第一行。
            """
            await js("""(()=>{const i=document.querySelector('#pQ');
                if(i){i.value='%s';i.dispatchEvent(new Event('input'));}
                const b=[...document.querySelectorAll('nav button')]
                  .find(x=>x.dataset.tab==='products');b&&b.click();})()""" % PROD)
            await asyncio.sleep(1.2)
            await drain()
            await wait_rows('#pBody tr', 1)
            await js("document.querySelector('#pBody tr') &&"
                     " document.querySelector('#pBody tr').click()")
            await wait_rows('#pShots .cand-item', 1)
            await asyncio.sleep(5)
            await drain()

        # 干净起点：先把这个产品上残留的标记清掉（上次跑可能中断）
        for r in api('/api/products/%s/candidates/rejected' % PROD).get('items', []):
            api('/api/products/%s/candidates/unreject' % PROD,
                {'photo_ids': [r['photo_id']]})
        await open_detail()

        # ⚠️ 先断言详情真的打开了，再往下测 —— 否则后面全在断言「0 == 0」，
        #    看着像跑过了，其实什么都没验（first_pid 为空串时
        #    `'x' not in [...]` 恒真，会报出一片假绿）。
        n_open = await js("document.querySelectorAll('#pShots .cand-item').length")
        chk('0 产品详情已打开且有候选行', (n_open or 0) > 0, n_open)
        if not (n_open or 0):
            print('（详情未打开，后续断言无意义，终止）')
            return True

        rej_btns = await js("document.querySelectorAll('#pShots [data-rej]').length")
        chk('1 每条候选都有「无关联」按钮', (rej_btns or 0) > 0, rej_btns)
        first_pid = await js("(()=>{const b=document.querySelector('#pShots [data-rej]');"
                             "return b?b.dataset.rej:''})()")
        chk('1 按钮带 photo_id（点它才知道标哪张）', bool(first_pid), first_pid)
        btn_text = await js("(()=>{const b=document.querySelector('#pShots [data-rej]');"
                            "return b?b.innerText.trim():''})()")
        chk('1 按钮文案是「无关联」', btn_text == '无关联', btn_text)

        # ⚠️ 选择器必须排除「已标记无关联」区块（#rejBody）—— 那里面每行
        #    也用 .cand-item 渲染（复用样式），不排除的话标记后它自己
        #    冒出来顶上一位，行数不减 → 断言「候选行数减少」假红
        #    （实测 before=4/after=4，remaining 末尾多个空串就是它）。
        CAND_SEL = '#pShots .cand-item'
        before_ids = await js(CAND_JS)
        n_before = await js(CAND_JS_N)
        chk('1 标记前有候选行', (n_before or 0) > 0, n_before)

        # ── 2 点击必须弹确认框（不可逆动作不能一点就生效）──
        # ⚠️ **必须先覆盖 window.confirm 再点**（2026-10-05 卡死过一次）：
        #    headless 下真 confirm 会**阻塞** CDP 的 Runtime.evaluate，
        #    js() 永远不返回 —— 表现是脚本挂在这一行、零输出、整轮跑
        #    30 分钟被 kill。别指望「headless 会自动 dismiss」。
        await js("""(()=>{window.__cf=[];
            window.confirm=(m)=>{window.__cf.push(m);return true;};})()""")
        await js("""(()=>{const b=[...document.querySelectorAll('#pShots [data-rej]')]
            .find(x=>!x.disabled); b&&b.click();})()""")
        await asyncio.sleep(1.0)
        await drain()
        cfs = await js("(()=>window.__cf||[])()")
        chk('2 点「无关联」弹确认框', bool(cfs), cfs)
        cftxt = cfs[0] if cfs else ''
        chk('2 确认框说清「可撤销」', '撤销' in cftxt, cftxt[:80])
        chk('2 确认框说清「只影响本产品」', '只影响本产品' in cftxt, cftxt[:120])

        # ── 3 确认后从 DOM 消失 + 角标下降 ──
        await asyncio.sleep(6)
        await drain()
        after_ids = await js(CAND_JS)
        chk('3 被标记的那张已从候选 DOM 消失', first_pid not in (after_ids or []),
            {'marked': first_pid, 'remaining': after_ids})
        chk('3 候选行数减少', (len(after_ids or [])) == (len(before_ids or []) - 1),
            {'before': len(before_ids or []), 'after': len(after_ids or [])})

        # 后端真相：角标降了、已标记清单有它
        st = api('/api/products/%s/candidates' % PROD)
        chk('3 后端候选里也确实没了',
            first_pid not in [x['photo_id'] for x in st.get('group_siblings', [])]
            and first_pid not in [x['photo_id'] for x in st.get('items', [])],
            [x['photo_id'] for x in st.get('group_siblings', [])])
        rj = api('/api/products/%s/candidates/rejected' % PROD)
        chk('3 已标记清单里有它且带缩略图',
            any(x['photo_id'] == first_pid and x.get('thumb') for x in rj.get('items', [])),
            rj.get('items'))

        # ── 4 「已标记无关联」区块 + 展开 + 撤销 ──
        await open_detail()
        has_blk = await js("!!document.querySelector('#rejToggle')")
        chk('4 详情出现「已标记无关联」区块', bool(has_blk), has_blk)
        body_shown = await js("(()=>{const b=document.querySelector('#rejBody');"
                              "return b?b.style.display:''})()")
        chk('4 该区块默认折叠（多数时候只有一两张，别占地方）',
            body_shown == 'none', repr(body_shown))
        await js("document.querySelector('#rejToggle') && document.querySelector('#rejToggle').click()")
        await asyncio.sleep(1.0)
        await drain()
        shown2 = await js("(()=>{const b=document.querySelector('#rejBody');"
                          "return b?b.style.display:''})()")
        chk('4 点标题能展开', shown2 != 'none', repr(shown2))
        unrej_n = await js("document.querySelectorAll('#pShots [data-unrej]').length")
        chk('4 展开后有「撤销」按钮', (unrej_n or 0) > 0, unrej_n)

        await js("document.querySelector('#pShots [data-unrej]')"
                 " && document.querySelector('#pShots [data-unrej]').click()")
        await asyncio.sleep(6)
        await drain()
        st2 = api('/api/products/%s/candidates' % PROD)
        back = [x['photo_id'] for x in st2.get('group_siblings', [])] + \
               [x['photo_id'] for x in st2.get('items', [])]
        chk('4 撤销后照片回到候选', first_pid in back, back)
        rj2 = api('/api/products/%s/candidates/rejected' % PROD)
        chk('4 撤销后已标记清单清空这条',
            not any(x['photo_id'] == first_pid for x in rj2.get('items', [])),
            rj2.get('items'))

        chk('5 全程无 JS 异常', not excs,
            [e.get('exception', {}).get('description', '')[:120] for e in excs][:3])
        return True


ok = False
try:
    ok = asyncio.run(main())
finally:
    # 收尾：把本脚本标记的数据清干净，别在老板的库里留脏标记
    try:
        for r in api('/api/products/%s/candidates/rejected' % PROD).get('items', []):
            api('/api/products/%s/candidates/unreject' % PROD,
                {'photo_ids': [r['photo_id']]})
        print('[ OK ] 收尾清理：本脚本产生的标记已全部撤销')
    except Exception as e:  # noqa: BLE001
        print('[WARN] 收尾清理失败（请手动查 %s 的已标记无关联）: %s' % (PROD, e))
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    shutil.rmtree(TMP, ignore_errors=True)

print()
print('PASS' if (ok and not fails) else 'FAIL: ' + ', '.join(fails))
sys.exit(0 if (ok and not fails) else 1)
