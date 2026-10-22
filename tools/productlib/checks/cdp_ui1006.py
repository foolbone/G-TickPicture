# -*- coding: utf-8 -*-
"""CDP 实跑：产品库「待确认照片」标识 + 筛选（2026-10-05）。

老板要：把有可能关联待确认的照片标识出来，并且能筛选。

锁死四件事：
  1 列表出现「读码 N」「同组 N」两类角标（不是只有一个笼统的「N 待关」）；
  2 「有待确认照片 / 有读码候选 / 有同组候选」三个筛选都真的过滤，
    且**筛出来的每一行角标都 > 0**（不能点开是空的）；
  3 核心一致性：列表角标数字 == 详情候选区实际张数
    （读码 = .cand-check 数，同组 = .sib-check 数）—— 同源的硬断言；
  4 「待确认多的排前」排序生效；全程无 JS 异常。
"""
import asyncio, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 19341
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_ui1006')
# ⚠️ 调试端口选 1xxxx 高位：本机临时端口（ephemeral）会撞上 9341 这种普通端口，
#    headless Edge 绑不上就静默挂死（10-05 实测卡 20 分钟无输出）

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
        print('[FAIL] 调试端口未就绪'); return False
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

        async def set_sel(sel, val, wait=6.0):
            await js("(()=>{const s=document.querySelector('%s');s.value='%s';"
                     "s.dispatchEvent(new Event('change'));})()" % (sel, val))
            await asyncio.sleep(wait)
            await drain()

        await js("document.querySelector('nav button[data-tab=products]').click()")
        # 首次进列表要现算候选（全库 ~2.8s），固定 sleep 不够 —— 轮询等行出现
        got_rows = 0
        for _ in range(40):
            await asyncio.sleep(1.0)
            await drain()
            got_rows = await js("document.querySelectorAll('#pBody tr').length")
            if got_rows:
                break
        chk('0 列表已加载', got_rows > 0, got_rows)

        # 每行角标的解析：读码 N / 同组 N
        ROWS_JS = """(()=>[...document.querySelectorAll('#pBody tr')].map(tr=>{
            const tds=tr.querySelectorAll('td');
            const txt=(tds[4]?.innerText||'').replace(/\\s+/g,' ');
            const m1=(txt.match(/读码 (\\d+)/)||[])[1];
            const m2=(txt.match(/同组 (\\d+)/)||[])[1];
            return {code:tr.dataset.code, raw:txt.trim(),
                    code_n:parseInt(m1||'0'), group_n:parseInt(m2||'0')};
        }))()"""

        # ═══ 1 角标存在 ═══
        rows = await js(ROWS_JS)
        with_any = [r for r in rows if r['code_n'] + r['group_n'] > 0]
        chk('1 列表出现待确认角标', len(with_any) > 0,
            {'行数': len(rows), '有角标的': len(with_any), '样例': with_any[:2]})
        chk('1 角标带类别字样（读码/同组，不是光一个数字）',
            bool(with_any) and all(('读码' in r['raw'] or '同组' in r['raw'])
                                    for r in with_any),
            [r['raw'] for r in with_any[:3]])

        # ═══ 2 三个筛选都生效，且筛出来的行角标 > 0 ═══
        for val, key, label in [('cand', None, '有待确认照片'),
                                ('cand_code', 'code_n', '有读码候选'),
                                ('cand_group', 'group_n', '有同组候选')]:
            await set_sel('#pHas', val)
            rows = await js(ROWS_JS)
            ok = len(rows) > 0 and all(r['code_n'] + r['group_n'] > 0 for r in rows)
            if key:
                ok = ok and all(r[key] > 0 for r in rows)
            chk('2 筛选「%s」每行都有角标' % label, ok,
                {'行数': len(rows), '首行': rows[0] if rows else None})

        # ═══ 3 列表角标 == 详情候选数（同源硬断言）═══
        await set_sel('#pHas', 'cand_code')      # 读码候选：两类角标都有，能一次验两个
        rows = await js(ROWS_JS)
        target = max(rows, key=lambda r: r['code_n'] + r['group_n'])
        print('   用于一致性核对的行：%s（读码 %d / 同组 %d）'
              % (target['code'], target['code_n'], target['group_n']))
        await js("(()=>{const tr=[...document.querySelectorAll('#pBody tr')]"
                 ".find(x=>x.dataset.code==='%s');tr&&tr.click();})()" % target['code'])
        await asyncio.sleep(8)
        await drain()
        got = await js("""(()=>({
            cand: document.querySelectorAll('#pShots .cand-check').length,
            sib: document.querySelectorAll('#pShots .sib-check').length
        }))()""")
        chk('3 详情读码候选数 == 列表「读码」角标',
            got and got['cand'] == target['code_n'],
            {'列表': target['code_n'], '详情': got})
        chk('3 详情同组候选数 == 列表「同组」角标',
            got and got['sib'] == target['group_n'],
            {'列表': target['group_n'], '详情': got})

        # ═══ 4 排序「待确认多的排前」═══
        await js("document.querySelector('#pDetailClose').click()")
        await asyncio.sleep(1)
        await set_sel('#pHas', 'cand')
        await set_sel('#pSort', 'cand')
        rows = await js(ROWS_JS)
        sums = [r['code_n'] + r['group_n'] for r in rows]
        chk('4 待确认排序：首行是当页最多的',
            bool(sums) and sums[0] == max(sums), sums[:5])
        # 缺口优先排序下首屏可能整屏都是同一类；切到待确认排序后两类才必然同框
        chk('4 两类角标能在同一屏并存',
            any(r['code_n'] > 0 for r in rows) and any(r['group_n'] > 0 for r in rows),
            {'读码行': sum(1 for r in rows if r['code_n'] > 0),
             '同组行': sum(1 for r in rows if r['group_n'] > 0)})

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
    shutil.rmtree(TMP, ignore_errors=True)

print('----')
print('PASS' if not fails else 'FAIL: ' + ', '.join(fails))
sys.exit(1 if fails else 0)
