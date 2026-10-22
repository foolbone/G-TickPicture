# -*- coding: utf-8 -*-
"""CDP 实跑：旧版「照片治理」抽屉的**关闭路径**（2026-10-21 老板报「打开了关闭不了」）。

根因：抽屉是 position:fixed 右侧 560px / z-index 70，**它自己把唯一的关闭
入口盖住了** —— 开关按钮 #wGovToggle 在向导卡片标题行最右缘，正好落在抽屉
覆盖区下面；抽屉内又没有 × 按钮、没有 Esc、没有点外面关闭。

⚠️ 本脚本**必须用真实鼠标事件**（Input.dispatchMouseEvent），不能用
   程序化 t.click()：后者绕过命中测试，按钮被浮层盖住时照样触发 handler
   —— 之前的 cdp_old_wizard.py 8a/8b/8c 就是这么写的，所以这个缺陷一直
   测不出来（假绿）。本脚本用真实点击复现「点不到」，再验修复后的三条关闭
   路径（✕ 按钮 / Esc / 点面板外）都能真关掉。

跑法：python tools/productlib/checks/cdp_gov_close.py
     （默认打已在运行的 8765 dev 服务；PL_PORT 可改端口）
"""
import asyncio
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

for _k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(_k, None)
os.environ['no_proxy'] = '*'

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8765'))
CDP_PORT = int(os.environ.get('PL_CDP', str(random.randint(9400, 9800))))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_govclose_edge')
BASE = 'http://127.0.0.1:%d' % PORT

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def hj(path, port=PORT, timeout=8):
    with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path),
                                timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,900', BASE + '/'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    page = None
    for _ in range(40):
        try:
            lst = hj('/json/list', CDP_PORT, 3)
        except Exception:
            lst = []
        lst = lst if isinstance(lst, list) else []
        # ⚠️ 必须按 URL 挑页：/json/list 的第一个 page 可能是
        #    sync-confirmation-dialog（Edge 的账号确认页），连上去会全程无响应。
        page = next((t for t in lst
                     if t.get('type') == 'page'
                     and t.get('url', '').startswith(BASE)), None)
        if page:
            break
        time.sleep(0.5)
    if not page:
        chk('0 找到产品库页面', False, 'no page')
        return

    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        i = [0]

        async def cmd(m, p=None):
            i[0] += 1
            await ws.send(json.dumps({'id': i[0], 'method': m, 'params': p or {}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get('id') == i[0]:
                    return r.get('result', {})

        async def js(e):
            r = await cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True,
                                               'awaitPromise': True})
            if r.get('exceptionDetails'):
                return 'EXC: ' + str(r['exceptionDetails'])[:300]
            return (r.get('result') or {}).get('value')

        async def real_click(sel):
            """**真实鼠标**点击：取元素中心坐标 → Input.dispatchMouseEvent。
            走命中测试，被浮层盖住时点不到真元素（这正是要验的）。"""
            box = await js("""(function(){const e=document.querySelector('%s');
                if(!e) return null; const r=e.getBoundingClientRect();
                if(r.width<1||r.height<1) return null;
                return JSON.stringify({x:Math.round(r.left+r.width/2),
                                       y:Math.round(r.top+r.height/2)});})()""" % sel)
            if not box or not isinstance(box, str) or not box.startswith('{'):
                return 'no-box'
            b = json.loads(box)
            for t in ('mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': t, 'x': b['x'], 'y': b['y'],
                           'button': 'left', 'clickCount': 1})
            return b

        async def gov_display():
            return await js("""(()=>{const w=document.querySelector('#wizGovWrap');
                return w? getComputedStyle(w).display : 'none';})()""")

        async def esc():
            for t in ('keyDown', 'keyUp'):
                await cmd('Input.dispatchKeyEvent',
                          {'type': t, 'key': 'Escape', 'code': 'Escape',
                           'windowsVirtualKeyCode': 27, 'nativeVirtualKeyCode': 27})

        await cmd('Runtime.enable')
        await cmd('Page.enable')
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1600, 'height': 900, 'deviceScaleFactor': 1,
                   'mobile': False})
        await js("try{localStorage.setItem('plTab','containers')}catch(e){}")
        await cmd('Page.reload', {'ignoreCache': True})
        await asyncio.sleep(7.0)

        picked = await js("""(()=>{
          const rows=[...document.querySelectorAll('#cBody tr')];
          for(const r of rows){
            const t=r.innerText.replace(/\\s+/g,' ');
            if(t.indexOf('（未分柜）')>=0) continue;
            const b=r.querySelector('[data-c-wiz]');
            if(b){ b.click(); return b.dataset.cWiz; }
          }
          return '';})()""")
        chk('0 进入柜作业', bool(picked) and not str(picked).startswith('EXC'),
            str(picked)[:40])
        await asyncio.sleep(6.0)

        await js("""(()=>{const s=document.querySelector('[data-step="photos"]');
            if(s){ s.click(); return 1; } return 0;})()""")
        await asyncio.sleep(6.0)

        chk('1 ③步已渲染（治理开关存在）',
            await js("!!document.querySelector('#wGovToggle')") is True)

        # ── 路径 A：真实点击开关打开 ──
        await real_click('#wGovToggle')
        await asyncio.sleep(1.2)
        disp = await gov_display()
        chk('2 真实点击「照片治理」能打开抽屉', disp == 'flex', 'display=%s' % disp)

        if disp != 'flex':
            return

        # 根因取证：抽屉开着时，开关按钮那个坐标上命中的是谁
        probe = await js("""(()=>{
          const t=document.querySelector('#wGovToggle');
          const w=document.querySelector('#wizGovWrap');
          if(!t||!w) return JSON.stringify({err:1});
          const r=t.getBoundingClientRect();
          const cx=Math.round(r.left+r.width/2), cy=Math.round(r.top+r.height/2);
          const top=document.elementFromPoint(cx,cy);
          return JSON.stringify({cx:cx, cy:cy,
            hit: top? (top.id? '#'+top.id : top.tagName+'.'+String(top.className).slice(0,24)) : null,
            hitInGov: !!(top && w.contains(top))});})()""")
        pd = json.loads(probe) if isinstance(probe, str) and probe.startswith('{') else {}
        print('[..] 抽屉开着时开关按钮坐标命中：%s' % probe, flush=True)

        # ── 路径 B：抽屉内 ✕ 按钮（真实点击）──
        has_x = await js("!!document.querySelector('#gGovClose')")
        chk('3 抽屉内有「✕ 关闭」按钮', has_x is True)
        await real_click('#gGovClose')
        await asyncio.sleep(1.0)
        d2 = await gov_display()
        chk('4 🔴 点「✕ 关闭」真能关掉抽屉', d2 == 'none', 'display=%s' % d2)

        # ── 路径 C：Esc ──
        await real_click('#wGovToggle')
        await asyncio.sleep(1.0)
        if await gov_display() != 'flex':
            await js("document.querySelector('#wGovToggle').click()")
            await asyncio.sleep(0.8)
        await esc()
        await asyncio.sleep(0.9)
        d3 = await gov_display()
        chk('5 🔴 Esc 能关掉抽屉', d3 == 'none', 'display=%s' % d3)

        # ── 路径 D：点抽屉外 ──
        await js("document.querySelector('#wGovToggle').click()")
        await asyncio.sleep(0.9)
        if await gov_display() == 'flex':
            for t in ('mousePressed', 'mouseReleased'):
                await cmd('Input.dispatchMouseEvent',
                          {'type': t, 'x': 400, 'y': 500,
                           'button': 'left', 'clickCount': 1})
            await asyncio.sleep(0.9)
        d4 = await gov_display()
        chk('6 🔴 点面板外能关掉抽屉', d4 == 'none', 'display=%s' % d4)

        # ── 回归：抽屉开着时，治理面板里的「照片批次」仍能呼出批次抽屉 ──
        await js("document.querySelector('#wGovToggle').click()")
        await asyncio.sleep(0.9)
        await js("""(()=>{const b=document.querySelector('#bOpen');
            if(b){ b.click(); return 1; } return 0;})()""")
        await asyncio.sleep(1.2)
        batches = await js("""(()=>{
          const d=document.querySelector('#bDrawer');
          const w=document.querySelector('#wizGovWrap');
          if(!d) return JSON.stringify({err:1});
          const r=d.getBoundingClientRect();
          const top=document.elementFromPoint(Math.round(r.left+r.width/2),
                                              Math.round(r.top+20));
          return JSON.stringify({on: d.classList.contains('on'),
            w: Math.round(r.width), h: Math.round(r.height),
            hitId: top? (top.id||'') : null,
            hitInGov: !!(top&&w&&w.contains(top))});})()""")
        bd = json.loads(batches) if isinstance(batches, str) and batches.startswith('{') else {}
        chk('7 治理面板里「照片批次」能呼出批次抽屉',
            bd.get('on') is True and (bd.get('w') or 0) > 200, batches)
        chk('8 🔴 批次抽屉不被治理抽屉盖住（能点到）',
            bd.get('hitInGov') is not True, batches)

        # 收拾：把批次抽屉与治理抽屉都关掉
        await js("""(()=>{const b=document.querySelector('#bClose');
            if(b) b.click(); const g=document.querySelector('#gGovClose');
            if(g) g.click(); return 1;})()""")
        await asyncio.sleep(0.6)

        # 无 JS 异常
        errs = await js("""(()=>{
          const e=window.__plErrs||[]; return JSON.stringify(e.slice(0,5));})()""")
        chk('9 无 JS 异常', not (isinstance(errs, str) and errs not in ('[]', '')),
            errs)

        print('FAIL %d' % len(fails))


try:
    asyncio.run(main())
finally:
    edge.terminate()
    time.sleep(1)
    shutil.rmtree(HOME, ignore_errors=True)

sys.exit(1 if fails else 0)
