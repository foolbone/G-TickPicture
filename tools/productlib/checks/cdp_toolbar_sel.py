# -*- coding: utf-8 -*-
"""CDP 实跑：③ 工具条分区 + 批量改判分类 + 清除已选（2026-10-15 老板三项反馈）。

  · 工具条分区：#wShState/#wShQ/#wShCand/查询/重置 在「查询区」(.tgrp)，
    按箱号分组/批量选择在「工具区」(.tgrp-tool)，清理与重复图片收进
    「更多 ▾」下拉（默认隐藏、点更多出现、点外面消失）；
  · 查询按钮带放大镜 svg、工具按钮带专用图形 svg（筛选/工具一眼区分）；
  · ③ 批量改判分类：批量选择 → 全选本页 → 选分类 → 应用分类 → 卡片
    角标变新分类、左侧树计数同步（POST /api/photos/kind）；
  · 清除已选：勾选后清空 → 计数归 0、卡片 ✓ 抹掉、**仍留在选择模式**；
  · ③ 顶部「批量选择」按钮进模式后再点可退出（修 selSetMode(true) 恒真）。

⚠️ 隔离实例 8799 / CDP 9359，不碰 8765。evaluate 顶层 const 跨调用残留，
   表达式一律包 IIFE（老坑）。
跑法：python tools/productlib/checks/cdp_toolbar_sel.py
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
PORT = int(os.environ.get('PL_PORT', '8799'))
CDP_PORT = int(os.environ.get('PL_CDP', '9359'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_tbsel_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_tbsel_db')
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


def post_json(path, obj, timeout=300):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf8', 'replace')
        try:
            return e.code, json.loads(body or '{}')
        except Exception:  # noqa: BLE001
            return e.code, {'raw': body[:200]}


def post_file(path, fields, files, timeout=600):
    b = '----pltbsel' + str(int(time.time()))
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
    buf += ('--%s--\r\n' % b).encode('utf-8')
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf8', 'replace')
        try:
            return e.code, json.loads(body or '{}')
        except Exception:  # noqa: BLE001
            return e.code, {'raw': body[:200]}


shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
os.makedirs(DBHOME, exist_ok=True)

srv = subprocess.Popen(
    [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
    env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/api/ping' % PORT, timeout=2) as r:
            json.loads(r.read()); break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例没起来')
    sys.exit(1)

# ── 造数据：产品 1 个 + 柜 1 个 + 照片 4 张 ──
post_json('/api/products', {'code': 'TBSEL-A1', 'name': '测试品'})
code, c = post_json('/api/containers', {'container_no': 'TBSEL01',
                                        'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_tbsel_photos')
os.makedirs(tmpd, exist_ok=True)
files = []
for i in range(4):
    p = os.path.join(tmpd, 'TB_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (40 * i + 30, 110, 170)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 4 张照片', code == 200 and (r or {}).get('added', 0) == 4,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:200]))

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
        await asyncio.sleep(4.5)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        # ════ A. 照片库页：清除已选 ════
        # 冷启动（新 profile）模块加载可能 >4.5s：go('batches') 若早于
        # TAB_LOADERS 注册发出，只切了 class 没跑 loader → 网格永远空。
        # 轮询等出图，每 2s 补发一次 go（幂等，重复跑 loader 无害）。
        n0 = 0
        for i in range(40):
            await asyncio.sleep(0.5)
            if i % 4 == 0:
                await js("window.go && window.go('batches')")
            n0 = await js("document.querySelectorAll('#shots .shot').length")
            if n0:
                break
        await drain()
        chk('A1 照片网格 4 张', n0 == 4, n0)
        await js("document.querySelector('#selBtn').click()")
        await asyncio.sleep(0.4)
        await js("""(()=>{[...document.querySelectorAll('#shots .shot')]
            .slice(0,3).forEach(c=>c.click());})()""")
        await asyncio.sleep(0.4)
        n_sel = await js("document.querySelector('#selN').textContent")
        chk('A2 勾选后计数 = 3', n_sel == '3', n_sel)
        # 清除已选：计数归零、✓ 抹掉、操作条还在（仍留在选择模式）
        await js("document.querySelector('#selClear').click()")
        await asyncio.sleep(0.4)
        n_sel2 = await js("document.querySelector('#selN').textContent")
        on_cnt = await js("document.querySelectorAll('#shots .shot.sel-on').length")
        bar_on = await js("document.querySelector('#selBar').style.display !== 'none'")
        chk('A3 清除已选 → 计数 0', n_sel2 == '0', n_sel2)
        chk('A4 清除已选 → 卡片 ✓ 全抹掉', on_cnt == 0, on_cnt)
        chk('A5 清除已选后仍在选择模式（操作条可见）', bar_on is True, bar_on)
        # 退出选择，恢复普通模式
        await js("document.querySelector('#selExit').click()")
        await asyncio.sleep(0.3)

        # ════ B. 柜作业③：工具条分区 + 更多下拉 ════
        await js("window.enterWizard(%r, 'photos')" % cid)
        # 等③网格出图再断言（轮询，同上）
        nw = 0
        for i in range(40):
            await asyncio.sleep(0.5)
            nw = await js("document.querySelectorAll('#wizShots .shot').length")
            if nw:
                break
        await drain()
        has_bar = await js("!!document.querySelector('#wclbar, .wclbar')")
        chk('B1 ③工具条已渲染', has_bar is True, has_bar)
        chk('B1b ③网格 4 张', nw == 4, nw)
        # 查询区：状态/关键词/待办/查询/重置 在同一个 .tgrp 里
        qgrp = await js("""(()=>{const g=document.querySelector(
            '.wclbar .tgrp'); if(!g) return null;
            const ids=['wShState','wShQ','wShUnlinked','wShCand',
                       'wShSearch','wShReset'];
            return ids.every(i=>g.querySelector('#'+i)) ? 'ok' : 'miss';})()""")
        chk('B2 查询区六个控件同组', qgrp == 'ok', qgrp)
        # 工具区：按箱号分组/批量选择 在 .tgrp-tool；清理/重复在下拉里
        tgrp = await js("""(()=>{const g=document.querySelector(
            '.wclbar .tgrp-tool'); if(!g) return null;
            const ok=!!g.querySelector('#wShCarton')&&!!g.querySelector('#wSelBtn')
                     &&!!g.querySelector('#wMoreBtn');
            const in_menu=!!g.querySelector('#wCleanInvalid')
                         &&!!g.querySelector('#wDupBtn');
            return (ok&&in_menu)?'ok':'miss';})()""")
        chk('B3 工具区含箱号分组/批量选择/更多，清理与重复收进下拉', tgrp == 'ok', tgrp)
        # 更多 ▾：默认菜单不可见 → 点更多可见 → 点外面消失
        menu_hidden = await js("""(()=>{const m=document.querySelector(
            '#wMoreDrop .tdrop-m'); return m ? getComputedStyle(m).display : 'none';})()""")
        chk('B4 更多菜单默认隐藏', menu_hidden == 'none', menu_hidden)
        await js("document.querySelector('#wMoreBtn').click()")
        await asyncio.sleep(0.3)
        menu_on = await js("""(()=>{const m=document.querySelector(
            '#wMoreDrop .tdrop-m'); return m ? getComputedStyle(m).display : 'none';})()""")
        chk('B5 点「更多」菜单展开', menu_on == 'block', menu_on)
        # 点外面（页面标题区）→ 收起
        await js("document.querySelector('.wdh').click()")
        await asyncio.sleep(0.3)
        menu_off = await js("""(()=>{const m=document.querySelector(
            '#wMoreDrop .tdrop-m'); return m ? getComputedStyle(m).display : 'none';})()""")
        chk('B6 点外面菜单收起', menu_off == 'none', menu_off)
        # 图标：查询带放大镜（svg）、工具按钮各带 svg
        ico_q = await js("!!document.querySelector('#wShSearch svg')")
        ico_tool = await js("""(()=>['wShCarton','wMoreBtn','wCleanInvalid','wDupBtn']
            .every(i=>document.querySelector('#'+i+' svg')))()""")
        chk('B7 查询按钮带图标', ico_q is True, ico_q)
        chk('B8 工具按钮带图标（含下拉内两项）', ico_tool is True, ico_tool)

        # ════ C. ③ 批量改判分类 ════
        await js("document.querySelector('#wSelBtn').click()")
        await asyncio.sleep(0.4)
        bar_on3 = await js("document.querySelector('#wSelBar').style.display !== 'none'")
        chk('C1 进选择模式操作条出现', bar_on3 is True, bar_on3)
        await js("document.querySelector('#wSelAll').click()")   # 全选本页
        await asyncio.sleep(0.4)
        n_sel3 = await js("document.querySelector('#wSelN').textContent")
        chk('C2 全选本页 = 4', n_sel3 == '4', n_sel3)
        # 下拉选项已填充（KIND_LABELS 一份）
        kind_opts = await js("document.querySelectorAll('#wSelKind option').length")
        chk('C3 改判分类下拉已填充', (kind_opts or 0) > 3, kind_opts)
        await js("""(()=>{const s=document.querySelector('#wSelKind');
            s.value='product'; s.dispatchEvent(new Event('change'));})()""")
        await js("document.querySelector('#wSelKindDo').click()")
        await asyncio.sleep(4.0)     # 等 POST + photos:changed 刷新
        await drain()
        badge_n = await js("document.querySelectorAll('#wizShots .shot .badge.k-product').length")
        chk('C4 应用分类后 4 张卡片角标变「产品」', badge_n == 4, badge_n)
        tree_n = await js("""(()=>{const b=[...document.querySelectorAll(
            '#wPhTree .ptree-i')].find(x=>{const l=x.querySelector('.ptree-l');
            return l && l.textContent==='产品';});
            return b ? (b.querySelector('.ptree-n')||{}).textContent : 'none';})()""")
        chk('C5 左侧树「产品」计数 = 4', str(tree_n) == '4', tree_n)
        n_sel4 = await js("document.querySelector('#wSelN').textContent")
        chk('C6 改判后勾选清零（不退出选择模式）', n_sel4 == '0', n_sel4)

        # ════ D. ③ 顶部按钮切换退出（修 selSetMode(true) 恒真）═══
        btn_txt = await js("document.querySelector('#wSelBtn').textContent")
        chk('D1 顶部按钮文字 = 退出选择', '退出选择' in (btn_txt or ''), btn_txt)
        await js("document.querySelector('#wSelBtn').click()")
        await asyncio.sleep(0.4)
        bar_off = await js("document.querySelector('#wSelBar').style.display === 'none'")
        btn_txt2 = await js("document.querySelector('#wSelBtn').textContent")
        chk('D2 再点顶部按钮退出选择模式', bar_off is True, bar_off)
        chk('D3 按钮文字恢复「批量选择」', '批量选择' in (btn_txt2 or ''), btn_txt2)

        # 运行期异常（ESM 缺 import 等静态抓不到的问题）一律算失败
        chk('Z 无运行期异常', len(excs) == 0,
            json.dumps(excs[:1], ensure_ascii=False)[:300] if excs else '')
        return True


try:
    ok = asyncio.run(main())
    edge.terminate(); srv.terminate()
    print('RESULT:', 'PASS' if (ok and not fails) else 'FAIL',
          '(%d fails)' % len(fails), flush=True)
    sys.exit(0 if (ok and not fails) else 1)
except Exception as e:  # noqa: BLE001
    print('[FAIL] 脚本异常:', e, flush=True)
    try:
        edge.terminate(); srv.terminate()
    except Exception:  # noqa: BLE001
        pass
    sys.exit(1)
