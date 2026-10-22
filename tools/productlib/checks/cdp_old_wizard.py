# -*- coding: utf-8 -*-
"""CDP 实跑：**旧版柜作业**第②步清单 / 第③步照片的翻页（2026-10-20 老板）。

验：
  ② 清单：有上一篇/下一页，且一页装得下（页码可见、页面不纵滚）
  ③ 照片：容器是页码（.pgb），不是「加载更多」按钮
  ③ 箱号组视图同款

跑在已在运行的服务上（默认 8765 dev）。
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

# shell 可能设了 http_proxy，本机回环被送去代理会 502
for _k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(_k, None)
os.environ['no_proxy'] = '*'

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8765'))
CDP_PORT = int(os.environ.get('PL_CDP', str(random.randint(9400, 9800))))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_wiz_edge')
BASE = 'http://127.0.0.1:%d' % PORT

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def hj(path, port=PORT, timeout=8):
    with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path), timeout=timeout) as r:
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
        lst = hj('/json/list', CDP_PORT, 3)
        lst = lst if isinstance(lst, list) else []
        page = next((t for t in lst if t.get('type') == 'page'), None)
        if page:
            break
        time.sleep(0.5)
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

        await cmd('Runtime.enable')
        await cmd('Page.enable')
        await cmd('Network.enable')
        await cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1600, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
        await js("try{localStorage.setItem('plTab','containers')}catch(e){}")
        await cmd('Page.reload', {'ignoreCache': True})
        await asyncio.sleep(6.0)

        # 找一个有清单 + 照片的柜，点「柜作业」
        picked = await js("""(()=>{
          const rows=[...document.querySelectorAll('#cBody tr')];
          for(const r of rows){
            const t=r.innerText.replace(/\\s+/g,' ');
            if(t.indexOf('（未分柜）')>=0) continue;
            const m=t.match(/清单行\\s*(\\d+)/);
            const pm=t.match(/^\\s*(\\d+)/);
            const b=r.querySelector('[data-c-wiz]');
            if(b){ b.click(); return b.dataset.cWiz; }
          }
          return '';})()""")
        chk('0 进入柜作业', bool(picked) and not str(picked).startswith('EXC'), str(picked)[:40])
        await asyncio.sleep(5.0)

        # ① → ③ 照片
        await js("""(()=>{const s=document.querySelector('[data-step="photos"]');
            if(s){ s.click(); return 1; } return 0;})()""")
        await asyncio.sleep(5.0)
        photos = await js("""(()=>{
          const box=document.querySelector('#wizShots');
          const more=document.querySelector('#wShMore');
          return JSON.stringify({
            hasBox: !!box, n: box? box.querySelectorAll('.shot,.gcard').length : -1,
            moreTag: more? more.tagName : '',
            pgb: more? more.querySelectorAll('.pgb').length : 0,
            moreTxt: more? more.innerText.replace(/\\s+/g,' ').slice(0,70) : '',
            docSh: document.documentElement.scrollHeight, vh: innerHeight
          });})()""")
        pd = json.loads(photos) if isinstance(photos, str) and photos.startswith('{') else {}
        chk('1 ③照片网格已渲染', (pd.get('n') or 0) > 0, pd.get('n'))
        chk('2 🔴 ③没有「加载更多」', '加载更多' not in (pd.get('moreTxt') or ''), pd.get('moreTxt'))
        chk('3 🔴 ③是页码控件', (pd.get('pgb') or 0) >= 2, photos)

        # ③ 箱号组视图
        await js("""(()=>{const b=document.querySelector('[data-wtab="carton"], #wShTabs [data-ptab="carton"]');
            if(b){ b.click(); return 1; } return 0;})()""")
        await asyncio.sleep(4.0)
        carton = await js("""(()=>{const more=document.querySelector('#wShMore');
            return JSON.stringify({pgb: more? more.querySelectorAll('.pgb').length:0,
              txt: more? more.innerText.replace(/\\s+/g,' ').slice(0,70):''});})()""")
        cd = json.loads(carton) if isinstance(carton, str) and carton.startswith('{') else {}
        chk('4 ③箱号组视图也是页码', (cd.get('pgb') or 0) >= 2, carton)

        # ② 清单
        await js("""(()=>{const s=document.querySelector('[data-step="checklist"]');
            if(s){ s.click(); return 1; } return 0;})()""")
        await asyncio.sleep(4.0)
        cl = await js("""(()=>{
          const prev=document.querySelector('#wClPrev'), next=document.querySelector('#wClNext');
          const body=document.querySelector('#wizClBody');
          const pg=(document.querySelector('.wclpager')||{}).innerText||'';
          return JSON.stringify({hasPrev:!!prev, hasNext:!!next,
            rows: body? body.querySelectorAll('tr').length : -1,
            pager: pg.replace(/\\s+/g,' ').trim().slice(0,60),
            docSh: document.documentElement.scrollHeight, vh: innerHeight});})()""")
        cd2 = json.loads(cl) if isinstance(cl, str) and cl.startswith('{') else {}
        chk('5 ②清单有上一页/下一页', cd2.get('hasPrev') is True and cd2.get('hasNext') is True, cl)
        chk('6 ②页码文案', '页' in (cd2.get('pager') or ''), cd2.get('pager'))
        chk('7 ②每页行数按视口收敛（不再 50 行一页）',
            (cd2.get('rows') or 0) <= 25, cd2.get('rows'))

        # ── 治理抽屉（2026-10-20 老板需求4：按钮 + 右侧抽屉，不占下方）──
        # 断言跑在②之后，按钮只在③渲染 —— 先切回③
        await js("""(()=>{const s=document.querySelector('[data-step="photos"]');
            if(s){ s.click(); return 1; } return 0;})()""")
        await asyncio.sleep(4.0)
        gov = await js("""(()=>{
          const t = document.querySelector('#wGovToggle');
          const w = document.querySelector('#wizGovWrap');
          if(!t || !w) return JSON.stringify({hasBtn:!!t, hasWrap:!!w});
          const before = {on: w.classList.contains('on'), display: getComputedStyle(w).display};
          t.click();
          const after = {on: w.classList.contains('on'), display: getComputedStyle(w).display,
                         width: Math.round(w.getBoundingClientRect().width),
                         height: Math.round(w.getBoundingClientRect().height),
                         top: Math.round(w.getBoundingClientRect().top),
                         zIndex: getComputedStyle(w).zIndex,
                         txt: w.innerText.replace(/\\s+/g,' ').slice(0,60)};
          // 抽屉内容（治理本体）是否真的可见
          const panel = document.querySelector('#govPanel');
          const fb = document.querySelector('#govPanel .foldbody');
          const vis = {panel: !!panel, panelW: panel? Math.round(panel.getBoundingClientRect().width):0,
                       foldbodyDisplay: fb? getComputedStyle(fb).display : null,
                       runBtn: !!document.querySelector('#govPanel #gRun')};
          return JSON.stringify({hasBtn:true, hasWrap:true, vis:vis,
            before:before, after:after});})()""")
        try:
            gd = json.loads(gov) if isinstance(gov, str) and gov.startswith('{') else {}
        except Exception:
            gd = {}
        chk('8a 治理按钮在③标题行', gd.get('hasBtn') is True, gov and gov[:80])
        af = gd.get('after') or {}
        vi = gd.get('vis') or {}
        # 10-21：抽屉改用 style.display 控制（内联样式压过 class），断言跟着改
        chk('8b 🔴 点按钮呼出抽屉（默认收起、不占下方）',
            (gd.get('before') or {}).get('display') == 'none'
            and af.get('display') == 'flex', 'display=%s' % af.get('display'))
        chk('8c 🔴 抽屉真看得见（有尺寸、有治理内容）',
            (af.get('width') or 0) > 200 and (af.get('height') or 0) > 200
            and (vi.get('panelW') or 0) > 100 and vi.get('runBtn') is True,
            gov and gov[:200])

        print('FAIL %d' % len(fails))


try:
    asyncio.run(main())
finally:
    edge.terminate()
    time.sleep(1)
    shutil.rmtree(HOME, ignore_errors=True)

sys.exit(1 if fails else 0)
