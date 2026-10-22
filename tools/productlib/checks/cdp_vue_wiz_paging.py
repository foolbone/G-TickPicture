# -*- coding: utf-8 -*-
"""CDP 实跑：**新版**柜作业③照片的页码分页 + 布局（2026-10-20 老板）。

新版有深链 /app/wizard?step=photos&cid=xxx，不用点步骤。
验证：页码分页（无「加载更多」）、每页张数按视口算、页面不纵滚、翻页生效。

⚠️ 跑在已在运行的服务上（默认 8765 dev，需先 npm run build 出 Vue3 产物）。
   和 checks/cdp_vue_wizard.py 分工：那个验 ①②⑤，这个专验③的分页。
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

# ⚠️ shell 可能设了 http_proxy，本机回环会被送去代理 → 502（老坑）
for _k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(_k, None)
os.environ['no_proxy'] = '*'

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8765'))
CDP_PORT = int(os.environ.get('PL_CDP', str(random.randint(9400, 9800))))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuewizpg_edge')
CID = os.environ.get('PL_CID', '67ee5dd4bf8a')

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def hj(path, port=PORT, timeout=10):
    with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path), timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


shutil.rmtree(HOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,900'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    page = None
    for _ in range(40):
        lst = hj('/json/list', CDP_PORT, 4)
        lst = lst if isinstance(lst, list) else []
        page = next((t for t in lst if t.get('type') == 'page'), None)
        if page:
            break
        time.sleep(0.5)
    if not page:
        print('[FAIL] 找不到 page')
        return
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        i = [0]

        async def cmd(m, p=None):
            i[0] += 1
            myid = i[0]
            await ws.send(json.dumps({'id': myid, 'method': m, 'params': p or {}}))
            while True:
                r = json.loads(await ws.recv())
                if r.get('id') == myid:
                    return r.get('result', {})

        async def js(e):
            r = await cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True,
                                               'awaitPromise': True})
            if r.get('exceptionDetails'):
                return 'EXC: ' + str(r['exceptionDetails'])[:200]
            return (r.get('result') or {}).get('value')

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
        await cmd('Network.enable')
        await cmd('Network.setCacheDisabled', {'cacheDisabled': True})
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1600, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})

        url3 = 'http://127.0.0.1:%d/app/wizard?step=photos&cid=%s' % (PORT, CID)
        await cmd('Page.navigate', {'url': url3})
        # ⚠️ 新版是懒加载：progress/树/网格分层回来，11s 只够看到一半，
        #    等不够会把「还没渲染」误判成功能坏（踩过一次）。
        await asyncio.sleep(18.0)
        await drain()

        p3 = await js("""(()=>{
          const pg=document.querySelector('.el-pagination');
          const btns=[...document.querySelectorAll('button')].map(b=>b.innerText.trim());
          const cards=document.querySelectorAll('.shot, .gcard').length;
          return JSON.stringify({
            url: location.href,
            title: (document.querySelector('.wd-h, .wcard b')||{}).textContent||'',
            body: document.body.innerText.replace(/\\s+/g,' ').slice(0,260),
            hasPager: !!pg,
            pagerTxt: pg? pg.innerText.replace(/\\s+/g,' ').slice(0,80):'',
            moreBtn: btns.filter(t=>t==='加载更多').length,
            cards: cards,
            docSh: document.documentElement.scrollHeight,
            vh: innerHeight});})()""")
        pd = json.loads(p3) if isinstance(p3, str) and p3.startswith('{') else {}
        chk('0 ③页面打开', bool(pd) and (pd.get('cards') or 0) > 0, pd.get('cards'))
        chk('1 🔴 ③没有「加载更多」', (pd.get('moreBtn') or 0) == 0, pd.get('moreBtn'))
        chk('2 🔴 ③是页码分页', pd.get('hasPager') is True, pd.get('pagerTxt'))
        chk('3 🔴 页面不纵滚（一屏装下）',
            (pd.get('docSh') or 0) <= (pd.get('vh') or 0) + 8,
            'sh=%s vh=%s' % (pd.get('docSh'), pd.get('vh')))

        first = await js("""(()=>{const e=document.querySelector('.shot,.gcard');
            return e? (e.dataset.id||e.innerText.trim().slice(0,24)) : '';})()""")
        ok = await js("""(()=>{const ls=document.querySelectorAll('.el-pager li');
            for(const li of ls){ if(li.innerText.trim()==='2'){ li.click(); return 1; } }
            return 0;})()""")
        await asyncio.sleep(4.5)
        await drain()
        second = await js("""(()=>{const e=document.querySelector('.shot,.gcard');
            return e? (e.dataset.id||e.innerText.trim().slice(0,24)) : '';})()""")
        chk('4 翻到第 2 页内容变了', bool(ok) and first != second,
            '%s -> %s' % (first, second))

        onp = await js("""(()=>{const ls=[...document.querySelectorAll('.el-pager li')]
            .filter(x=>/^\\d+$/.test(x.innerText.trim()));
            const c=ls.find(x=>x.classList.contains('is-active'));
            const e=document.querySelector('.shot,.gcard');
            return JSON.stringify({cur:c?c.innerText.trim():'',
              first:e?(e.dataset.id||''):'',
              gp: window.__gp || null,
              docSh: document.documentElement.scrollHeight,
              n: document.querySelectorAll('.shot,.gcard').length});})()""")
        chk('5 页码高亮 = 2', 'cur":"2"' in (onp or '') or '"cur": "2"' in (onp or ''), onp)

        # ── 治理抽屉（2026-10-20 老板需求4 + 10-21 反馈「点了没反应」）──
        gov = await js("""(()=>{
          const btns=[...document.querySelectorAll('button')];
          const t = btns.find(b=>b.innerText.trim().indexOf('照片治理')>=0);
          if(!t) return JSON.stringify({hasBtn:false, btns:btns.map(b=>b.innerText.trim()).slice(0,12)});
          const before = !!document.querySelector('.el-drawer');
          t.click();
          return JSON.stringify({hasBtn:true, before:before});})()""")
        await asyncio.sleep(3.0)
        await drain()
        gov2 = await js("""(()=>{
          const d=[...document.querySelectorAll('.el-drawer')];
          const vis=d.filter(x=>{const r=x.getBoundingClientRect(); return r.width>0 && r.height>0;});
          return JSON.stringify({nDrawer:d.length, nVisible:vis.length,
            w: vis[0]? Math.round(vis[0].getBoundingClientRect().width):0,
            txt: vis[0]? vis[0].innerText.replace(/\\s+/g,' ').slice(0,60):''});})()""")
        chk('7a ③标题行有「照片治理」按钮', 'hasBtn":true' in (gov or ''), (gov or '')[:100])
        chk('7b 🔴 点治理按钮真的弹出抽屉', 'nVisible":1' in (gov2 or ''), gov2)

        await drain()
        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('6 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:200] if bad else ''))


try:
    asyncio.run(main())
finally:
    try:
        edge.terminate()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(1)
    shutil.rmtree(HOME, ignore_errors=True)

print('----')
print('FAIL %d' % len(fails))
for f in fails:
    print('  - ' + f)
sys.exit(1 if fails else 0)
