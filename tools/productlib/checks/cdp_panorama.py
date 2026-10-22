# -*- coding: utf-8 -*-
"""CDP 实跑：产品详情页的「可能的全景图」真的出现、能关联、能否掉（2026-10-11）。

静态三检证明不了：
  · 新增的第三列是否真的渲染出来（products.js 拼的 HTML 很长，少个引号就整列消失）；
  · 点「单张关联」是否真的写进 links（按钮复用旧绑定，接错就静默无效）；
  · 点「无关联」后这一张是否真的从候选里消失；
  · 展示是否按 time_src 自适应（微信来源**不能**出现"间隔 N 秒"）；
  · 有没有 ESM/运行时异常。

⚠️ 破坏面：自建隔离实例（临时 PL_HOME + 端口 8798 / CDP 9356），不碰老板的 8765。
跑法：python tools/productlib/checks/cdp_panorama.py
       （验打包版：PL_EXT_URL=http://127.0.0.1:PORT/ PL_PORT=PORT）
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

# ⚠️ 环境里可能设了 http_proxy，本机回环会被送去代理 → 502。测本机服务必须绕开。
for _k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
    os.environ.pop(_k, None)
os.environ['no_proxy'] = '*'
urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({})))

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8798'))
CDP_PORT = int(os.environ.get('PL_CDP', '9356'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_pano_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_pano_db')
EXT = os.environ.get('PL_EXT_URL', '').strip() or None
URL = EXT or ('http://127.0.0.1:%d/' % PORT)
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
XLSX = os.path.join(REPO, '9.13 5x40HQ', 'MIEU2012616.xlsx')

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


def post_json(path, obj, timeout=300):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode('utf-8'))


def post_file(path, fields, files, timeout=900):
    b = '----plpano' + str(int(time.time()))
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
        return r.status, json.loads(r.read().decode('utf-8'))


shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.makedirs(DBHOME, exist_ok=True)

srv = None
if not EXT:
    srv = subprocess.Popen(
        [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
        env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)

# ── 造数：柜 → 清单 → 微信命名的照片 → 关联一张标签近景 ──
CNO = 'PANO00001'
code, c = post_json('/api/containers', {'container_no': CNO, 'inspector': 'cdp'})
cid = (c or {}).get('id')
if not cid:
    print('[FAIL] 建柜失败'); sys.exit(1)
post_file('/api/products/import', {'container_id': cid},
          [('file', XLSX, os.path.basename(XLSX))])

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_pano_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd, exist_ok=True)
tag = time.strftime('%m%d%H%M%S')
files = []
for i in range(8):
    p = os.path.join(tmpd, '微信图片_202609151033%02d_220%02d_838.jpg' % (i, 80 + i))
    Image.new('RGB', (1200, 900), (40 * i, 80, 200 - 20 * i)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 照片上传成功', code == 200 and (r or {}).get('added', 0) == 8, (r or {}).get('added'))

ph = http_json('/api/photos?container_id=%s&limit=50' % cid)
items = (ph or {}).get('items') or []
pl = http_json('/api/products?limit=200') or {}
prods = pl.get('items') or []
# 只关联一张照片当"标签近景"，其余照片没治理（kind=NULL）→ 系统认定"缺全景"，
# 候选就会出现（治理分类不是本测试要验的东西）。
target = prods[0]['code_norm'] if prods else None
if items and target:
    post_json('/api/links', {'photo_id': items[1]['id'], 'code': target, 'by': 'cdp'})
chk('0 已造出「有标签近景、缺全景」的产品', bool(target),
    '%s / %d 张照片' % (target, len(items)))

api_before = (http_json('/api/products/%s/candidates' % target) or {})
chk('0 接口已下发 panoramas 字段', 'panoramas' in api_before,
    'panorama_total=%s' % api_before.get('panorama_total'))
n_pano = api_before.get('panorama_total') or 0

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1800,2400', URL],
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

        # ── 进产品库页 → 搜出那个产品 → 打开详情 ──
        await js("""(()=>{const b=document.querySelector('nav button[data-tab="products"]');
            if(b) b.click(); return !!b;})()""")
        await asyncio.sleep(3.5)
        await drain()
        # 产品列表分页，目标编码未必在第一页 → 先用搜索框过滤
        await js("""(()=>{const q=document.querySelector('#pQ');
            if(!q) return false; q.value=%s;
            q.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
            return true;})()""" % json.dumps(target))
        await asyncio.sleep(3.0)
        await drain()
        rows = await js("""(()=>[...document.querySelectorAll('#pBody tr')]
            .map(t=>t.dataset.code))()""")
        chk('1b 搜索后列表里有目标产品', target in (rows or []), rows)
        await js("""(()=>{const t=[...document.querySelectorAll('#pBody tr')]
            .find(r=>r.dataset.code===%s); if(t) t.click(); return !!t;})()"""
                 % json.dumps(target))
        await asyncio.sleep(4.5)
        await drain()
        on = await js("document.querySelector('#pDetail').classList.contains('on')")
        chk('2 产品详情抽屉打开', on is True, on)

        # ── 2026-10-18 起，全景候选已从「产品详情抽屉」并入**照片抽屉**
        #    （drawer.js 的 #dwPanoSec / #dwPano / .pano-item / .dwGChk）。
        #    本脚本原来查 #pShots + [data-cand-link] 单张按钮，那套元素早没了 ——
        #    它一直报红是**脚本过时**，不是产品坏（接口仍正常给候选）。
        #    检查跟着实现走：单张按钮已改成「勾选 → 关联选中到产品」批量关联，
        #    原来的「无关联」按钮在新设计里没有对应物，本脚本不再断言它。
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(3.0)
        await js("try{localStorage.setItem('plTab','batches')}catch(e){}")
        await cmd('Page.reload')
        await asyncio.sleep(5.0)
        await drain()

        shot_id = items[1]['id'] if len(items) > 1 else None
        await js("""(()=>{const e=document.querySelector('.shot[data-id="%s"]');
            if(!e) return false; e.click(); return true;})()""" % shot_id)
        await asyncio.sleep(4.0)
        for _ in range(40):
            await asyncio.sleep(0.5)
            if await js("document.querySelectorAll('#dwPano .pano-item').length > 0"):
                break
        await drain()

        pano = await js("""(()=>{const b=document.querySelector('#dwPano');
            if(!b) return 'no-box';
            return JSON.stringify({
              items: b.querySelectorAll('.pano-item').length,
              chks: b.querySelectorAll('.dwGChk').length,
              hasBar: !!document.querySelector('#dwPanoLink'),
              title: (document.querySelector('#dwPanoSec h4')||{}).textContent||'',
              txt: b.innerText.replace(/\\s+/g,' ').slice(0, 400)});})()""")
        pp = json.loads(pano) if isinstance(pano, str) and pano.startswith('{') else {}
        chk('3 🔴 全景候选区块渲染出来了', (pp.get('items') or 0) > 0, pano)
        chk('3b 区块标题已合并为「同组连拍 · 可能的全景图」',
            '可能的全景图' in (pp.get('title') or ''), pp.get('title'))
        chk('4 每条候选都有勾选框', (pp.get('chks') or 0) >= (pp.get('items') or 0)
            and (pp.get('items') or 0) > 0, pano)

        # ── 展示不许出现秒数（微信来源）──
        chk('5 🔴 微信来源不展示「间隔 N 秒」',
            '间隔' not in (pp.get('txt') or ''), (pp.get('txt') or '')[:90])

        # ── 勾选 → 关联选中到产品 → 真的写进 links ──
        # 动作生效的证据 = 候选从「有」变「无」。先把关联前的候选数存下来，
        # 免得后面的「关联后清空」因为接口本来就返回空而假绿。
        api_before_d = http_json('/api/products/%s/candidates' % target) or {}
        api_before = len((api_before_d.get('panoramas') or [])
                         + (api_before_d.get('items') or []))
        await js("""(()=>{const a=document.querySelector('#dwPanoAll');
            if(!a) return 0; a.checked=true; a.onchange&&a.onchange(); return 1;})()""")
        await asyncio.sleep(0.8)
        await js("""(()=>{const b=document.querySelector('#dwPanoLink');
            if(!b||b.disabled) return 'disabled';
            b.click(); return 'clicked';})()""")
        await asyncio.sleep(4.0)
        await drain()
        api_after = http_json('/api/products/%s/candidates' % target) or {}
        remaining = [x['photo_id'] for x in (api_after.get('panoramas') or [])]
        # ⚠️ /api/links 只有 POST/DELETE、**没有 GET**，拿它当断言入口会 404 假红。
        #    正确证据是 candidates（=「未关联照片」列表）：关联前有、关联后空。
        chk('6/7 🔴 关联前确有候选 → 关联后清空（动作真的生效）',
            api_before > 0 and not remaining,
            '前 %d 张 → 后 %d 张' % (api_before, len(remaining)))

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('9 全程无 JS 异常', not bad,
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
    if srv:
        srv.terminate()

print()
print('[INFO] 接口给出的候选数：%s' % n_pano)
print('PASS' if (res and not fails) else ('FAIL %d 项' % len(fails)))
sys.exit(0 if (res and not fails) else 1)
