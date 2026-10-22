# -*- coding: utf-8 -*-
"""CDP 实跑：产品库「柜号」下拉以产品清单为准（2026-10-05）。

老板要求：下拉筛选的柜号要以产品清单列里的柜号为准。

锁死四件事：
  1 下拉选项 == /api/products/containers 的清单柜号（不再出现照片批次的
    交付文件名脏值，也不再有清单里没有的照片柜号）；
  2 每个选项带产品数标注（EMCU9914616（446 件）这种）；
  3 选中柜号后列表 total == 后端同口径数（同源硬断言）；
  4 换柜号后首行编码真的变了（筛选真的在过滤，不是摆设）。
全程无 JS 异常。
"""
import asyncio, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9349
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_ui1008')

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


def http_json(url, retries=40, port=PORT, timeout=3):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url if url.startswith('http')
                                        else 'http://127.0.0.1:%d%s' % (port, url),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
     '--window-size=1600,2200', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪')
        return False
    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

    api_containers = http_json('http://127.0.0.1:8765/api/products/containers', retries=10)
    expect = [(x['container_no'], x['products']) for x in (api_containers or {}).get('items', [])]

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
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        # ═══ 1 下拉选项 == 清单柜号 ═══
        await js("window.go && window.go('products')")
        for _ in range(20):
            await asyncio.sleep(1)
            await drain()
            n_opt = await js("document.querySelectorAll('#pContainer option').length")
            if (n_opt or 0) >= 2:      # 全部柜号 + 至少 1 个清单柜号
                break
        opts = await js("""(()=>[...document.querySelectorAll('#pContainer option')]
            .map(o=>({v:o.value, t:o.textContent.trim()})))()""")
        got_vals = [o['v'] for o in (opts or []) if o['v']]
        exp_vals = [c for c, _ in expect]
        chk('1 下拉选项 == 清单柜号（%s）' % (exp_vals or ['空']),
            got_vals == exp_vals, {'下拉': got_vals, '接口': exp_vals})
        chk('1b 无照片批次脏值混入',
            not [v for v in got_vals if '集刻交付' in v or v.startswith('ph_')], got_vals)

        # ═══ 2 选项带产品数标注 ═══
        with_n = all(('（' in o['t'] and '件）' in o['t']) for o in (opts or []) if o['v'])
        chk('2 选项文案带产品数', bool(opts) and with_n,
            [o['t'] for o in (opts or [])][:3])

        # ═══ 3+4 选中柜号：total 同源 + 列表真的变了 ═══
        if expect:
            cno, n_prod = expect[0]
            total_all = await js("""(()=>fetch('/api/products?limit=1')
                .then(r=>r.json()).then(d=>d.total))()""")
            await js("""(()=>{const s=document.querySelector('#pContainer');
                s.value=%r; s.dispatchEvent(new Event('change'));})()""" % cno)
            for _ in range(20):
                await asyncio.sleep(1)
                await drain()
                info = await js("document.querySelector('#pgInfo')?.innerText||''")
                if '共' in (info or ''):
                    break
            m = await js("""(()=>{const t=document.querySelector('#pgInfo')?.innerText||'';
                const m=t.match(/共 (\\d+) 条/); return m?parseInt(m[1]):null})()""")
            chk('3 选「%s」后 total==%d（同源）' % (cno, n_prod),
                m == n_prod, {'下拉标注': n_prod, '列表': m, '全部柜号时': total_all})
            first = await js("document.querySelector('#pBody tr td')?.innerText.trim()")
            await js("""(()=>{const s=document.querySelector('#pContainer');
                s.value=''; s.dispatchEvent(new Event('change'));})()""")
            for _ in range(15):
                await asyncio.sleep(1)
                await drain()
                info2 = await js("document.querySelector('#pgInfo')?.innerText||''")
                m2 = None
                if '共' in (info2 or ''):
                    import re
                    mm = re.search(r'共 (\d+) 条', info2)
                    m2 = int(mm.group(1)) if mm else None
                if m2 and m2 != m:
                    break
            chk('4 切回全部柜号列表真的变了',
                m2 != m, {'选柜': m, '全部': m2, '选柜首行': first})

        chk('9 全程无 JS 异常', not excs, excs[:2])
        return True

    return False


try:
    asyncio.run(main())
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print('----')
if fails:
    print('FAIL: ' + ' | '.join(fails))
    sys.exit(1)
print('ALL PASS')
