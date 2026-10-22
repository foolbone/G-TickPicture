# -*- coding: utf-8 -*-
"""截图核对：向导第③步（选照片）的三条老板反馈是否真修好。

老板 2026-10-18 22:44 截图（同一条今天又发了一次）：
  1. 左侧树随页面滚动就跑了，要冻住
  2. 筛选区字体大小不一、控件大小没对齐
  3. 不同按钮没有区分

本脚本不写断言库，只做「造 30 张 → 截图 → 打几何」，
用图 + 数字一起说话（避免又变成只读代码就宣称修好）。

跑法：python tools/productlib/checks/shot_wizard_step3.py
产物：%TEMP%/pl_step3_shots/
"""
import asyncio
import base64
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
PORT = int(os.environ.get('PL_PORT', '8815'))
CDP_PORT = int(os.environ.get('PL_CDP', '9375'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_shot_step3_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_shot_step3_db')
SHOTS = os.path.join(tempfile.gettempdir(), 'pl_step3_shots')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/wizard?step=photos'
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def http_json(path, port=PORT, retries=40, timeout=8):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def _req(method, path, obj=None, timeout=120):
    data = json.dumps(obj).encode('utf8') if obj is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


def post_file(path, fields, files, timeout=600):
    b = '----pls3' + str(int(time.time()))
    buf = b''
    for k, v in fields.items():
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                % (b, k, v)).encode('utf8')
    for k, fp, fn in files:
        with open(fp, 'rb') as f:
            data = f.read()
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n' % (b, k, fn)).encode('utf8')
        buf += data + b'\r\n'
    buf += ('--%s--\r\n' % b).encode('utf8')
    req = urllib.request.Request(BASE + path, data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


for d in (HOME, DBHOME, SHOTS):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)

srv = subprocess.Popen(
    [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
    env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try:
        with urllib.request.urlopen(BASE + '/api/ping', timeout=2) as r:
            json.loads(r.read()); break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例没起来'); sys.exit(1)

from PIL import Image  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_step3_img')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)

code, c = _req('POST', '/api/containers', {'container_no': 'SHOT3', 'inspector': 'cdp'})
wid = (c or {}).get('id')
print('container id =', wid, flush=True)

files = []
for i in range(90):
    p = os.path.join(tmpd, 'S3_%02d.jpg' % i)
    Image.new('RGB', (900, 675), (60 + i * 5, 120, 160)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': wid}, files)
print('upload ->', code, json.dumps(r, ensure_ascii=False)[:100], flush=True)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,1000', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    for _ in range(40):
        if http_json('/json/version', port=CDP_PORT, retries=1, timeout=3):
            break
        await asyncio.sleep(0.5)
    page = next((t for t in (http_json('/json/list', port=CDP_PORT) or [])
                 if t.get('type') == 'page'
                 and '/app/' in (t.get('url') or '')), None)
    if not page:
        print('[FAIL] 找不到 page'); return
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

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str(ex.get('text'))[:150]
            return (r.get('result') or {}).get('value')

        async def shot(name):
            r = await cmd('Page.captureScreenshot', {'format': 'png'})
            with open(os.path.join(SHOTS, name), 'wb') as f:
                f.write(base64.b64decode(r.get('data') or ''))
            return name

        await cmd('Runtime.enable')
        await cmd('Page.enable')
        # 先落到任意页把柜锚点写进 localStorage['plCid']（全站唯一真相源），
        # 否则 ?step=photos 是空态（「先建一个柜」），截不到工具条。
        await cmd('Page.navigate', {'url': BASE + '/app/home'})
        await asyncio.sleep(4.0)
        await js("localStorage.setItem('plCid', %s)" % json.dumps(wid))
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(8.0)

        n = await js("document.querySelectorAll('.shot-grid > *').length")
        print('网格卡片数 =', n, flush=True)
        print('截图:', await shot('3_top.png'), flush=True)

        # 1920 视口再截一张：顶栏摘要要全字（老板现场屏幕 ≥1920，
        # 1500 测试窗下摘要会省略号，看不出对标旧版的效果）
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1920, 'height': 1000,
                   'deviceScaleFactor': 1, 'mobile': False})
        await asyncio.sleep(1.5)
        print('1920 顶栏:', await js("""(()=>{
            const ws=[...document.querySelectorAll('.wstep .ws')];
            const cut=ws.filter(e=>e.scrollWidth>e.clientWidth+1).length;
            const sb=document.querySelector('.wstepbar');
            return JSON.stringify({cut:cut,
              barW:Math.round(sb.getBoundingClientRect().width),
              steps:[...document.querySelectorAll('.wstep')]
                     .map(e=>e.innerText.replace(/\\n/g,' ').trim())});})()"""),
              flush=True)
        print('截图:', await shot('3_top_wide.png'), flush=True)
        await cmd('Emulation.clearDeviceMetricsOverride')
        await asyncio.sleep(1.0)

        geo = await js("""(()=>{
            const tr=document.querySelector('.ptree-wrap');
            const grid=document.querySelector('.shot-grid');
            return JSON.stringify({
              tree: tr? {top:Math.round(tr.getBoundingClientRect().top),
                         h:Math.round(tr.getBoundingClientRect().height),
                         w:Math.round(tr.getBoundingClientRect().width)}:null,
              gridH: grid?Math.round(grid.getBoundingClientRect().height):null});})()""")
        print('顶部几何:', geo, flush=True)

        # 最坏情况：把摘要替换成老板真实数据那种最长的文本，量会不会被截。
        # 测试库照片数少，摘要天然偏短 —— 不模拟就会「假绿」。
        print('最坏情况(长摘要):', await js("""(()=>{
            const ws=[...document.querySelectorAll('.wstep .ws')];
            const worst=['EMCU9914616','1003 行','1072 张 · 治理 1072/1072',
                         '未选（可跳过）','已生成 7 份'];
            ws.forEach((e,i)=>{ if(worst[i]) e.textContent=worst[i]; });
            const cut=[];
            ws.forEach(e=>{ if(e.scrollWidth>e.clientWidth+1)
                cut.push(e.textContent+' 需'+e.scrollWidth+' 给'+e.clientWidth); });
            const hd=document.querySelector('.wiz-head');
            const sb=hd.querySelector('.wstepbar');
            return JSON.stringify({
              cut:cut, sbW:Math.round(sb.getBoundingClientRect().width),
              headH:Math.round(hd.getBoundingClientRect().height),
              barOverflow: sb.scrollWidth>sb.clientWidth+1,
              headOverflow: hd.scrollWidth>hd.clientWidth+1});})()"""), flush=True)

        print('头部一行:', await js("""(()=>{const hd=document.querySelector('.wiz-head');
            if(!hd) return 'no head';
            const q=s=>hd.querySelector(s);
            const r=e=>e&&e.getBoundingClientRect();
            const bk=r(q('button')), sb=r(q('.wstepbar')),
                  sel=r(q('.wiz-cid')), pl=r(q('.pill'));
            const cut=[]; document.querySelectorAll('.wstep .ws').forEach(e=>{
              if(e.scrollWidth>e.clientWidth+1) cut.push((e.innerText||'').trim());});
            return JSON.stringify({
              headH: Math.round(hd.getBoundingClientRect().height),
              order: bk.right<=sb.left+2 && sb.right<=sel.left+2 && sel.right<=pl.left+2,
              sbW: Math.round(sb.width), cut: cut,
              steps: [...document.querySelectorAll('.wstep')].map(e=>e.innerText.replace(/\\n/g,' '))});})()"""), flush=True)

        hs = await js("""(()=>[...document.querySelectorAll(
            '.wclbar .el-select, .wclbar .el-input, .wclbar .el-button,'
            + '.wclbar .el-radio-group, .wclbar .el-checkbox')]
            .map(e=>({h:Math.round(e.getBoundingClientRect().height),
                      fs:getComputedStyle(e).fontSize,
                      cls:String(e.className).slice(0,64),
                      t:(e.innerText||'').trim().slice(0,10)})))()""")
        print('工具栏控件:', json.dumps(hs, ensure_ascii=False), flush=True)

        btns = await js("""(()=>[...document.querySelectorAll('.wclbar button')]
            .map(b=>{const s=getComputedStyle(b);
              return {t:(b.innerText||'').trim().slice(0,10),
                      bg:s.backgroundColor, color:s.color,
                      border:s.borderTopColor,
                      cls:String(b.className).slice(0,72)};}))()""")
        print('按钮分层:', json.dumps(btns, ensure_ascii=False), flush=True)

        # 往下滚两段，看树是否冻住
        for y in (300, 700, 1400):
            await js("(document.querySelector('.app-scroll')||document.body).scrollTop=%d" % y)
            await asyncio.sleep(1.0)
            t = await js("Math.round(document.querySelector('.ptree-wrap')"
                         ".getBoundingClientRect().top)")
            print('滚到 %d -> 树 top = %s (滚动量=%s)' % (y, t, await js("(document.querySelector('.app-scroll')||document.body).scrollTop")), flush=True)
        print('截图:', await shot('3_scrolled.png'), flush=True)
        print('截图目录:', SHOTS, flush=True)


asyncio.run(main())
edge.terminate()
srv.terminate()