# -*- coding: utf-8 -*-
"""CDP 实跑：顶栏必须**永远是一行**（导航按钮不得换行掉到第二行）。

背景（10-07 老板截图）：约 1500px 宽的窗口下，`nav{flex-wrap:wrap}` 被挤成两行，
「设置」掉到第二行、压在 header 底边框上。根因是右侧状态胶囊（柜号下拉 + 统计 + 多模态模型名）
太宽，把可收缩的 nav 挤到 min-content 以下。本检查横向扫多个常见窗口宽度，逐个断言：
  ① 所有 nav 按钮 top 一致（同一行）
  ② nav 按钮底边不越过 .hrow 底边
  ③ 页面无横向溢出（scrollWidth <= clientWidth + 1）
  ④ header 高度稳定（不因换行变高）

跑法（先确保 8765 在跑）：
  python tools/productlib/checks/cdp_header.py
"""
import asyncio, base64, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
EDGE_ALT = r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
URL = os.environ.get('PL_URL', 'http://127.0.0.1:8765/')
PORT = int(os.environ.get('PL_CDP_PORT', '9341'))
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_hdr')
SHOT = os.path.join(tempfile.gettempdir(), 'pl_header')
WIDTHS = [1920, 1680, 1536, 1440, 1366, 1280]

fails = []
def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)

def edge_exe():
    for p in (EDGE, EDGE_ALT):
        if os.path.exists(p):
            return p
    return None

shutil.rmtree(TMP, ignore_errors=True); os.makedirs(TMP, exist_ok=True)
exe = edge_exe()
if not exe:
    print('[FAIL] 找不到 Edge'); sys.exit(1)
proc = subprocess.Popen([exe, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
     '--window-size=%d,1000' % WIDTHS[0], URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def http_json(path, retries=40):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (PORT, path), timeout=3) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None

PROBE = r"""
(function(){
  var row = document.querySelector('header .hrow');
  var hd  = document.querySelector('header');
  var btns = [].slice.call(document.querySelectorAll('nav button'));
  var r  = row.getBoundingClientRect();
  var rb = [].slice.call(row.children).map(function(el){
      var x = el.getBoundingClientRect();
      return {tag: el.tagName + (el.id ? '#' + el.id : '') + (el.dataset && el.dataset.tab ? '[' + el.dataset.tab + ']' : ''),
              top: Math.round(x.top), bottom: Math.round(x.bottom),
              left: Math.round(x.left), right: Math.round(x.right), w: Math.round(x.width)};
  });
  return {
    vw: window.innerWidth,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    hdrH: Math.round(hd.getBoundingClientRect().height),
    rowH: Math.round(r.height),
    rowBottom: Math.round(r.bottom),
    navTops: btns.map(function(b){ return Math.round(b.getBoundingClientRect().top); }),
    navLabels: btns.map(function(b){ return b.textContent.trim(); }),
    setTop: (function(){ var b = document.querySelector('nav button[data-tab="set"]');
                        return b ? Math.round(b.getBoundingClientRect().top) : null; })(),
    setBottom: (function(){ var b = document.querySelector('nav button[data-tab="set"]');
                        return b ? Math.round(b.getBoundingClientRect().bottom) : null; })(),
    kids: rb
  };
})()
"""

async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪'); return False
    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page'); return False

    events = []
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        _id = [0]
        async def call(method, params=None):
            _id[0] += 1; i = _id[0]
            await ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if msg.get('id') == i:
                    if 'error' in msg:
                        raise RuntimeError('%s: %s' % (method, msg['error']))
                    return msg.get('result', {})
                events.append(msg)
        await call('Log.enable'); await call('Runtime.enable'); await call('Page.enable')
        async def ev(expr):
            r = await call('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
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

        for w in WIDTHS:
            await call('Emulation.setDeviceMetricsOverride',
                       {'width': w, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
            await wait(1.6)
            d = await ev(PROBE)
            if not isinstance(d, dict) or '__err__' in d:
                chk('W=%d 探针可执行' % w, False, d)
                continue
            tops = d['navTops']
            same_row = len(set(tops)) == 1
            no_bleed = d['setBottom'] is not None and d['setBottom'] <= d['rowBottom'] + 1
            no_ovf = d['scrollW'] <= d['clientW'] + 1
            hdr_ok = d['hdrH'] <= 60
            chk('W=%d 导航全在同一行' % w, same_row, 'tops=%s labels=%s' % (tops, d['navLabels']))
            chk('W=%d 「设置」不越出顶栏底边' % w, no_bleed,
                'setBottom=%s rowBottom=%s' % (d['setBottom'], d['rowBottom']))
            chk('W=%d 无横向溢出' % w, no_ovf, 'scrollW=%s clientW=%s' % (d['scrollW'], d['clientW']))
            chk('W=%d 顶栏高度正常' % w, hdr_ok, 'hdrH=%s' % d['hdrH'])
            if not (same_row and no_bleed):
                print('     子项右边界：', ', '.join('%s→%d' % (k['tag'], k['right']) for k in d['kids']))
            s = await call('Page.captureScreenshot', {'format': 'png', 'clip':
                {'x': 0, 'y': 0, 'width': min(w, d['clientW']), 'height': 70, 'scale': 1}})
            open('%s_%d.png' % (SHOT, w), 'wb').write(base64.b64decode(s['data']))

        # ── 带上真实柜号再扫一遍 ──
        # 下拉里显示的是「柜号 · N 行」，是顶栏里**最长的真实文本**；只测占位符会漏掉截断。
        cid = await ev("(async()=>{const r=await fetch('/api/containers');"
                       "const j=await r.json();const a=j.items||[];"
                       "if(!a.length) return null;"
                       "a.sort((x,y)=>(y.checklist_rows||0)-(x.checklist_rows||0));"
                       "return a[0].id;})()")
        if not cid or not isinstance(cid, str):
            print('[WARN] 库里没有柜，跳过「带柜号」那一轮')
        else:
            await ev("localStorage.setItem('plCid', %s)" % json.dumps(cid))
            await call('Page.reload', {})
            await wait(3.5)
            for w in (1920, 1440, 1280):
                await call('Emulation.setDeviceMetricsOverride',
                           {'width': w, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
                await wait(1.4)
                d = await ev(PROBE)
                chk('W=%d 带柜号时导航仍在一行' % w,
                    isinstance(d, dict) and len(set(d.get('navTops') or [])) == 1,
                    (d or {}).get('navTops'))
                m = await ev(r"""(function(){
                  var s=document.querySelector('#globalCid');
                  var cs=getComputedStyle(s);
                  var c=document.createElement('canvas').getContext('2d');
                  c.font=cs.fontSize+' '+cs.fontFamily;
                  var txt=(s.options[s.selectedIndex]||{}).textContent||'';
                  var pad=parseFloat(cs.paddingLeft)+parseFloat(cs.paddingRight);
                  return {txt:txt, textW:Math.round(c.measureText(txt).width),
                          boxW:Math.round(s.getBoundingClientRect().width),
                          need:Math.round(c.measureText(txt).width+pad+18)};
                })()""")
                if isinstance(m, dict) and 'textW' in m:
                    chk('W=%d 柜号下拉不截断文本' % w, m['need'] <= m['boxW'] + 1,
                        '「%s」需 %spx / 实有 %spx' % (m['txt'], m['need'], m['boxW']))
                sc = await call('Page.captureScreenshot', {'format': 'png', 'clip':
                    {'x': 0, 'y': 0, 'width': min(w, 1920), 'height': 70, 'scale': 1}})
                open('%s_cid_%d.png' % (SHOT, w), 'wb').write(base64.b64decode(sc['data']))

    print('\n截图：%s_<宽>.png' % SHOT)
    print(('[FAIL] %d 项未通过' % len(fails)) if fails else '[ OK ] 全部通过')
    return not fails

if __name__ == '__main__':
    try:
        ok = asyncio.run(main())
    finally:
        # 收干净：残留的 Edge 会占住端口/profile，下一次跑就attach到旧实例 → 假红。
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(0 if ok else 1)
