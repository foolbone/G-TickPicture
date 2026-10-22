# -*- coding: utf-8 -*-
"""CDP 实跑：检索页缺口必须区分「真缺口」与「照片在别的批次」（2026-10-05）。

老板报的现象：勾了批次检索，结果写「编码在库但所选批次内无照片」，
但标准产品页里明明能看到照片 —— 像是数据丢了。

本脚本在真实浏览器里锁死三件事：
  1 假缺口（照片在别的批次）必须说出「照片在别的批次 + 批次名 + 张数」，
    并给出「加选并重检 / 不限批次重检」按钮；
  2 真缺口（全库都没照片）**不许**出现这行（不能甩锅给批次）；
  3 点「加选并重检」后，假缺口真的变成命中（按钮不是摆设）。
另外全程监听 Runtime.exceptionThrown，不允许有 JS 异常。
"""
import asyncio, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9340
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_ui1005')

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


def post_json(path, payload, timeout=60):
    req = urllib.request.Request(
        'http://127.0.0.1:8765' + path,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


# ── 先问后端：拿一个「假缺口」和一个「真缺口」的编码 ──────────────
prods = http_json('http://127.0.0.1:8765/api/products?limit=120&sort=code',
                  retries=3, timeout=30)
codes = [r['code'] for r in (prods or {}).get('items', [])][:80]
bts = http_json('http://127.0.0.1:8765/api/batches?kind=photos', retries=3, timeout=20)
latest = ((bts or {}).get('items') or [{}])[0].get('id', '')
print('编码 %d 个，最新批次 %s' % (len(codes), latest))

res = post_json('/api/report/lookup', {'codes': codes, 'batch_ids': [latest]})
fake = [r for r in res['items'] if not r['found'] and r.get('other_batches')]
real = [r for r in res['items'] if not r['found'] and not r.get('other_batches')]
print('后端：假缺口 %d 个 / 真缺口 %d 个' % (len(fake), len(real)))
if not fake or not real:
    print('[FAIL] 样例不足，无法验证'); sys.exit(1)
FAKE = fake[0]['input']
REAL = real[0]['input']
FAKE_BATCH = fake[0]['other_batches'][0]['name']
print('样例：假缺口 %s（在 %s）/ 真缺口 %s' % (FAKE, FAKE_BATCH, REAL))

shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
     '--window-size=1440,2200', URL],
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

        # ── 进检索页 ──
        await js("document.querySelector('nav button[data-tab=report]').click()")
        await asyncio.sleep(2.5)
        await drain()

        # 录入两个编码
        await js("(()=>{const t=document.querySelector('#rpText');"
                 "t.value='%s\\n%s';document.querySelector('#rpParse').click();})()" % (FAKE, REAL))
        await asyncio.sleep(1)
        n_code = await js("document.querySelectorAll('#rpCodes .chip').length")
        chk('0 两个编码已录入', n_code == 2, n_code)

        # 只选最新批次 → 检索
        await js("document.querySelector('#rpBatchLatest').click()")
        await js("document.querySelector('#rpGo').click()")
        await asyncio.sleep(6)
        await drain()

        cards = await js("""(()=>{
            const out=[];
            document.querySelectorAll('#rpResult .rp-item.miss').forEach(el=>{
              const why=el.querySelector('.rp-why');
              out.push({code: el.querySelector('.code')?.textContent||'',
                        reason: el.querySelector('.muted')?.textContent||'',
                        why: why? why.innerText : null,
                        hasBtn: !!el.querySelector('[data-expand]')});
            });
            return out;
        })()""")
        print('缺口卡片：%s' % json.dumps(cards, ensure_ascii=False)[:400])
        f = next((c for c in cards if c['code'] == FAKE), None)
        r = next((c for c in cards if c['code'] == REAL), None)

        chk('1 假缺口卡片存在', bool(f), f and f['code'])
        if f:
            chk('1 假缺口说明「照片在别的批次」',
                bool(f['why']) and '照片在别的批次' in f['why'], f['why'])
            chk('1 假缺口列出批次名 %s' % FAKE_BATCH,
                bool(f['why']) and FAKE_BATCH in f['why'], f['why'])
            chk('1 假缺口给出一键修正按钮', f['hasBtn'] is True, f['hasBtn'])
            chk('1 假缺口文案带张数', bool(f['reason']) and '共' in f['reason'] and '张' in f['reason'],
                f['reason'])
        chk('2 真缺口卡片存在', bool(r), r and r['code'])
        if r:
            chk('2 真缺口不显示「别的批次」那一行（不甩锅给批次）', r['why'] is None, r['why'])
            chk('2 真缺口文案 = 没有关联照片',
                r['reason'] == '编码在库但没有关联照片', r['reason'])

        gap = await js("document.querySelector('#rpResult .rpgap')?.innerText||''")
        chk('3 顶部提示区分了假缺口', '不在所选批次' in (gap or ''), gap)

        # ── 点「加选并重检」：假缺口应变成命中 ──
        before = await js("document.querySelectorAll('#rpResult .rp-item.miss').length")
        await js("(()=>{const b=document.querySelector("
                 "'#rpResult .rp-why [data-expand]:not([data-expand=\"\"])');"
                 "if(b) b.click();})()")
        await asyncio.sleep(7)
        await drain()
        after = await js("document.querySelectorAll('#rpResult .rp-item.miss').length")
        hit = await js("""(()=>{
            const el=[...document.querySelectorAll('#rpResult .rp-item')]
              .find(x=>x.querySelector('.code')?.textContent==='%s');
            return el? {miss: el.classList.contains('miss'),
                        shots: el.querySelectorAll('.rp-shot').length} : null;
        })()""" % FAKE)
        chk('3 加选后缺口数减少', before > after, {'before': before, 'after': after})
        chk('3 假缺口变成命中并出图', bool(hit) and not hit['miss'] and hit['shots'] > 0, hit)

        chk('9 全程无 JS 异常', not excs, excs[:2])
        return True

    return False


try:
    ok = asyncio.run(main())
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
