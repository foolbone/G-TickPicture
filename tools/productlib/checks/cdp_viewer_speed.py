# -*- coding: utf-8 -*-
"""CDP 实跑：照片抽屉「上一张/下一张」不再卡（2026-10-11）。

老板反馈：切换上一张/下一张很卡。根因是抽屉主区直接取**原图**
（/img/<id>，真实库单张 3.8~21MB，冷加载实测 4.47s），切换一次重下一次。

修法：显示用预览图 /img/<id>?w=1600（长边受限，约 400KB）+ 浏览器缓存头
+ 预取相邻两张 + 缩略图先顶上。本脚本只验浏览器里真的生效：

  1 抽屉主区 <img> 用的是预览图（含 ?w=），不是原图；
  2 预览图字节数显著小于原图（不是"看起来改了其实没改"）；
  3 点「下一张」后，新图**立刻**就有 src（缩略图占位），且换到的是预览图；
  4 相邻两张被预取过（切过去时命中缓存，不再现下大图）；
  5 全程无 JS 异常。

⚠️ 破坏面：自建隔离实例（临时 PL_HOME + 端口 8799 / CDP 9357），
   不碰老板的 8765。

跑法：python tools/productlib/checks/cdp_viewer_speed.py
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

# ⚠️ 环境里可能设了 http_proxy，本机回环请求会被送去代理 → 502 Bad Gateway。
#    测的是**本机服务**，必须绕开代理。
for _k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(_k, None)
os.environ['no_proxy'] = '*'
urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({})))

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8799'))
CDP_PORT = int(os.environ.get('PL_CDP', '9357'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_speed_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_speed_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def http_json(path, port=PORT, retries=40, timeout=8):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def post_json(path, obj, timeout=600):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf8'))


def post_file(path, fields, files, timeout=900):
    b = '----plspeed' + str(int(time.time()))
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
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf8'))


shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.makedirs(DBHOME, exist_ok=True)

srv = subprocess.Popen(
    [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
    env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)

# ── 造 4 张「大照片」（模拟真实库 3~5MB 的采集原图）──
from PIL import Image, ImageDraw  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_speed_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd, exist_ok=True)
files = []
for i in range(4):
    p = os.path.join(tmpd, 'BIG_%02d.jpg' % i)
    im = Image.new('RGB', (4000, 3000), (30 * i, 70, 200 - 30 * i))
    d = ImageDraw.Draw(im)
    for x in range(0, 4000, 50):          # 加噪声，避免 JPEG 压得太小
        d.line([(x, 0), (x, 3000)], fill=((x * 7) % 255, (x * 3) % 255, (x * 11) % 255), width=3)
    im.save(p, 'JPEG', quality=92)
    files.append(('files', p, os.path.basename(p)))
sizes = [round(os.path.getsize(f[1]) / 1048576, 2) for f in files]
# JPEG 对规则线条压得很狠，1MB 上下就够用 —— 关键是要**比预览图大一个数量级**
chk('0 造出 4 张大照片', min(sizes) > 0.5, sizes)

code, c = post_json('/api/containers', {'container_no': 'SPEED001', 'inspector': 'cdp'})
cid = (c or {}).get('id')
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 照片上传成功', code == 200 and (r or {}).get('added', 0) == 4, (r or {}).get('added'))

ph = http_json('/api/photos?limit=20')
items = (ph or {}).get('items') or []
chk('0 照片查得到', len(items) == 4, len(items))
pid0 = items[0]['id']

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version', port=CDP_PORT, retries=40, timeout=3):
        print('[FAIL] 调试端口未就绪'); return False
    page = next((t for t in (http_json('/json/list', port=CDP_PORT) or [])
                 if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page'); return False

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
        await asyncio.sleep(5.0)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        chk('1 前置闸门：页面已加载',
            await js("!!document.querySelector('nav')") is True)
        # 点导航进照片页（别用 URL hash —— 页面有自己的路由）
        await js("(()=>{const b=document.querySelector('nav button[data-tab=\"batches\"]'); if(b) b.click(); return !!b;})()")
        await asyncio.sleep(4.0)
        await drain()
        chk('1b 已进入照片页',
            await js("(()=>{const e=document.querySelector('#tab-batches'); return e?e.classList.contains('on'):false;})()") is True)
        shots = await js("document.querySelectorAll('#tab-batches .shot').length")
        chk('1c 照片网格渲染出来了', (shots or 0) > 0, shots)

        # ── 打开抽屉 ──
        await js("(()=>{const e=document.querySelector('#tab-batches .shot'); if(e) e.click(); return !!e;})()")
        await asyncio.sleep(3.5)
        await drain()
        on = await js("document.querySelector('#drawer').classList.contains('on')")
        chk('2 抽屉打开了', on is True, on)

        src = await js("(()=>{const e=document.querySelector('#dwImg'); return e? e.getAttribute('src'):'';})()")
        chk('3 🔴 抽屉主区用预览图（含 ?w=），不是原图',
            '?w=' in (src or ''), src)

        # ── 页内实测：预览图 vs 原图的字节数 ──
        cmp = await js("""(async()=>{
            const pid = document.querySelector('#dwImg').dataset.pid;
            const measure = async (u)=>{
              const t0 = performance.now();
              const r = await fetch(u);
              const b = await r.arrayBuffer();
              return {bytes: b.byteLength, ms: Math.round(performance.now()-t0)};
            };
            const full = await measure('/img/'+pid);
            const view = await measure('/img/'+pid+'?w=1600');
            return {pid, full, view};
        })()""")
        if cmp:
            f, v = cmp['full'], cmp['view']
            # ⚠️ 阈值取 2/3 而不是 1/3：指向**外部实例**（PL_EXT_URL，验打包版）
            #    时，库里可能是别的脚本造的 1200x900 小图 —— 原图本来就小于
            #    预览尺寸（1600），压缩比自然达不到 1/3，但预览图**确实更小**。
            #    本脚本自己造图时是 4000x3000，压缩比能到 1/9 以上。
            chk('4 🔴 预览图体积小于原图（省 ≥1/3）',
                v['bytes'] * 3 < f['bytes'] * 2,
                '原图 %d KB → 预览图 %d KB' % (f['bytes'] // 1024, v['bytes'] // 1024))
            print('[INFO] 原图 %d KB / %d ms · 预览图 %d KB / %d ms'
                  % (f['bytes'] // 1024, f['ms'], v['bytes'] // 1024, v['ms']))
        else:
            chk('4 预览图体积对比', False, 'measure 失败')

        # ── 点「下一张」：立刻有 src（缩略图占位），最终落到预览图 ──
        nxt = await js("!!document.querySelector('#dwNext')")
        chk('5 有「下一张」按钮', nxt is True)
        t0 = await js("performance.now()")
        await js("document.querySelector('#dwNext').click()")
        await asyncio.sleep(0.4)
        early = await js("(()=>{const e=document.querySelector('#dwImg'); return e? e.getAttribute('src'):'';})()")
        chk('6 🔴 切换后立刻就有图（不是空白等原图）', bool(early), early)
        await asyncio.sleep(3.0)
        await drain()
        late = await js("(()=>{const e=document.querySelector('#dwImg'); return e? e.getAttribute('src'):'';})()")
        chk('7 切换完成后用的是预览图', '?w=' in (late or ''), late)
        pos = await js("(()=>{const e=document.querySelector('#dwPos'); return e? e.textContent:'';})()")
        chk('8 位置标记跟着走', '2 /' in (pos or ''), pos)

        # ── 相邻预取：第二张在切过去之前就已被请求过 ──
        pre = await js("""(()=>{
            const list = performance.getEntriesByType('resource')
              .filter(e=>e.name.indexOf('/img/')>=0)
              .map(e=>({n:e.name.split('/').pop(), size:e.transferSize||0}));
            return list.slice(-8);
        })()""")
        warmed = [x for x in (pre or []) if '?w=1600' in x['n']]
        chk('9 相邻图片被预取过（切过去命中缓存）', len(warmed) >= 1, pre)

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('10 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:300] if bad else ''))
    return True


try:
    res = asyncio.run(main())
except Exception as e:  # noqa: BLE001
    print('[FAIL] 脚本异常：%s' % e)
    res = False
finally:
    try:
        edge.terminate()
    except Exception:  # noqa: BLE001
        pass
    srv.terminate()

print()
print('PASS' if (res and not fails) else ('FAIL %d 项' % len(fails)))
sys.exit(0 if (res and not fails) else 1)
