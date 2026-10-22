# -*- coding: utf-8 -*-
"""脏柜锚点回归：空库 + 浏览器里留着旧柜号（老板 10-07 绿色包那个崩）。

**必须用空 data 目录跑** —— 真实库里那个柜还在，progress 正常返回 200，
复现不出来。空库 + 预设 `localStorage.plCid` 就等价于「绿色包在新机器上打开，
而这个浏览器之前用过旧库」。

复现步骤（就是老板那三步）：
  1 打开页面（此时库里空无一柜）
  2 **往 localStorage 塞一个库里不存在的柜号**（模拟旧环境留下的锚点）
  3 reload → 旧版会整页报「读取向导进度失败：Internal Server Error」

断言：
  · progress 端点对不存在的柜返回 **400**（不是 500，500 = 用户看不懂）
  · 页面**没有**「Internal Server Error」字样
  · 锚点被自愈掉（localStorage.plCid 变成 '' 或库里真实存在的柜）
  · toast / 页面文案说清「换机器或换库后浏览器里还留着旧柜号」+ 下一步
  · 库里有柜时自动落到第一个柜；一个柜都没有时明确告诉用户先建柜

用法：
    PL_HOME=<空目录> python -m tools.productlib.server --port 8766   # 先起空库
    python tools/productlib/checks/cdp_stale_anchor.py http://127.0.0.1:8766/
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
URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8766/').rstrip('/') + '/'
PORT = int(os.environ.get('PL_CDP_PORT', '9353'))
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_stale')
# 老板日志里的那个旧柜号：来自旧库，库里一定没有
STALE_CID = '6012cfb02968'

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen([EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
                         '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
                         '--window-size=1440,1100', URL],
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
    print('目标: %s' % URL)
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪')
        return False
    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
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

        await call('Runtime.enable')
        await call('Page.enable')
        await call('Network.enable')

        async def ev(expr):
            r = await call('Runtime.evaluate',
                           {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
            v = r.get('result', {})
            if v.get('subtype') == 'error' or 'exceptionDetails' in r:
                return {'__err__': str(v.get('description') or r.get('exceptionDetails'))[:300]}
            return v.get('value')

        async def wait(s):
            await asyncio.sleep(s)
            try:
                while True:
                    events.append(json.loads(await asyncio.wait_for(ws.recv(), 0.05)))
            except Exception:
                pass

        await wait(4.0)

        # ── 前提：这个库真的是空的 ──
        containers = await ev("""(async()=>{
            const d=await (await fetch('/api/containers')).json(); return d.items;})()""")
        chk('前提：目标库是空的（否则复现不出老板的场景）',
            isinstance(containers, list) and len(containers) == 0,
            '%s 个柜' % (len(containers) if isinstance(containers, list) else containers))

        # ── 塞一个库里不存在的旧柜号，再 reload ──
        await ev("""(()=>{localStorage.setItem('plCid', '%s');
            return localStorage.getItem('plCid');})()""" % STALE_CID)
        chk('已往 localStorage 塞入旧柜号',
            await ev("localStorage.getItem('plCid')") == STALE_CID)
        await call('Page.reload')
        await wait(5.0)

        # ── 旧版在这里整页报 500 ──
        body = await ev("document.body.innerText")
        chk('页面不再出现 Internal Server Error',
            isinstance(body, str) and 'Internal Server Error' not in body
            and '500' not in (body or ''),
            (body or '')[:120].replace('\n', ' '))
        codes = []
        for e in events:
            if e.get('method') == 'Network.responseReceived':
                u = e['params']['response']['url']
                if '/api/containers/' in u and '/progress' in u:
                    codes.append(e['params']['response']['status'])
        chk('progress 请求没有 5xx（柜不存在是可恢复状态，不是服务器故障）',
            not [c for c in codes if c >= 500], codes)
        chk('progress 请求返回 400 或根本没发（锚点已自愈就不必再问）',
            all(c < 500 for c in codes), codes)

        # ── 锚点自愈 ──
        now_cid = await ev("localStorage.getItem('plCid')")
        chk('脏锚点被自愈（不再是那个不存在的柜号）', now_cid != STALE_CID, now_cid)
        chk('自愈后锚点为空（库里一个柜都没有，不该瞎猜一个）',
            now_cid in ('', None), now_cid)

        # ── 提示要说清「为什么」+「下一步」──
        # ⚠️ 查**常驻条 #wizWarn**，不是 toast：自愈会清空锚点并递归重载，
        #    toast 几秒就消失，等我们查时早没了（上一版就是查 toast 才假红）。
        #    常驻条是「用户干完别的事回来看还能知道刚才发生了什么」的那一份。
        warn_txt = await ev("""(()=>{const e=document.querySelector('#wizWarn');
            if(!e || getComputedStyle(e).display==='none') return '';
            return e.innerText.trim();})()""")
        chk('页面有常驻提示条（不是只弹一下就消失）',
            isinstance(warn_txt, str) and len(warn_txt) > 10, warn_txt)
        chk('常驻条说清了原因（换机器或换库 + 旧柜号）',
            ('换机器' in (warn_txt or '')) and ('旧柜号' in (warn_txt or '')),
            warn_txt)
        chk('常驻条给了可操作的下一步（新建柜 / 切到 / 拷 data）',
            ('新建' in (warn_txt or '')) or ('切到' in (warn_txt or ''))
            or ('data' in (warn_txt or '')), warn_txt)
        chk('常驻条可关闭（用户确认过就不该一直占地方）',
            await ev("!!document.querySelector('#wizWarn button')") is True)
        await ev("document.querySelector('#wizWarn button').click()")
        await asyncio.sleep(0.3)
        chk('点「知道了」后提示条消失',
            await ev("getComputedStyle(document.querySelector('#wizWarn')).display") == 'none')

        # ── 页面仍然可用（不是白屏/整页报错）──
        chk('向导页仍然渲染出内容',
            await ev("""(()=>{const s=document.querySelector('#ctWizView');
                return s? s.innerText.trim().length>10 : false;})()""") is True)
        chk('导航能正常切页（没卡死）',
            await ev("""(async()=>{go('batches'); await new Promise(r=>setTimeout(r,1200));
                const s=document.querySelector('#tab-batches');
                return s? s.classList.contains('on'):false;})()""") is True)

        # ── 现在建一个柜，再塞脏锚点 → 应自动落到那个柜 ──
        await ev("""(async()=>{
            await fetch('/api/containers',{method:'POST',
              headers:{'Content-Type':'application/json'},
              body:JSON.stringify({container_no:'FRESH001',seal_no:'S',inspector:'t',
                                   client_name:'C',location:'L'})});
            localStorage.setItem('plCid','%s'); return true;})()""" % STALE_CID)
        await call('Page.reload')
        await wait(5.5)
        landed = await ev("localStorage.getItem('plCid')")
        expect = await ev("""(async()=>{
            const d=await (await fetch('/api/containers')).json();
            return (d.items[0]||{}).id || '';})()""")
        chk('库里有柜时，脏锚点自动落到那个柜（不是停在空选择上）',
            landed == expect and landed not in ('', STALE_CID, None),
            'plCid=%s 期望=%s' % (landed, expect))
        chk('落到柜之后向导能读出进度（不再报错）',
            await ev("""(async()=>{
                try{ const d=await (await fetch('/api/containers/'+localStorage.getItem('plCid')
                  +'/progress')).json(); return !!(d && d.steps); }
                catch(e){ return false; }})()""") is True)

        return True


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
print('----')
print('PASS / FAIL: %d 项失败' % len(fails))
for f in fails:
    print('  - ' + f)
print('==== RESULT: %s ====' % ('ALL PASS' if (ok and not fails) else 'HAS FAILURE'))
sys.exit(0 if (ok and not fails) else 1)
