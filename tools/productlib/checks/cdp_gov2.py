# -*- coding: utf-8 -*-
"""CDP 实跑：五需求前端链路（2026-10-15）。

  · ③ 四档选项卡（全部/已关联/未关联/无效图片）渲染 + 徽章计数；
  · 「清单/包装清理」模态：系统识别 → 确认 → 批量无效；
  · 「重复图片」模态：dHash 分组 → 确认 → 保留张外的标无效；
  · 抽屉「可能的全景图」：候选渲染 + 确认为同一产品（真关联落库）；
  · 改判即重治：抽屉改分类 → 自动 regovern → toast 提示。

⚠️ 隔离实例 8814 / CDP 9374，不碰 8765。evaluate 表达式一律包 IIFE。
跑法：python tools/productlib/checks/cdp_gov2.py
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
PORT = int(os.environ.get('PL_PORT', '8814'))
CDP_PORT = int(os.environ.get('PL_CDP', '9374'))
HOME = tempfile.mkdtemp(prefix='pl_gv_edge_')
DBHOME = tempfile.mkdtemp(prefix='pl_gv_db_')
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


def _req(method, path, obj=None, timeout=120):
    data = json.dumps(obj).encode('utf8') if obj is not None else None
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:200]}


def post_file(path, fields, files, timeout=600):
    b = '----plgv' + str(int(time.time()))
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:200]}


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

code, c = _req('POST', '/api/containers',
               {'container_no': 'GV01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)

from PIL import Image, ImageDraw  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_gv_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)


def _pat(path, seed, extra_mark=False):
    im = Image.new('RGB', (480, 360), (245, 245, 245))
    dr = ImageDraw.Draw(im)
    for i in range(0, 480, 19):
        dr.line([(i, 0), (i - 360, 360)], fill=(40 + seed * 30, 90, 160), width=5)
    dr.ellipse([60 + seed * 50, 60, 220 + seed * 50, 220], fill=(200, 50, 50))
    if extra_mark:
        # 与 dup_a 同图案但多一小块白斑 —— 视觉上是「重复拍」，字节上不是
        # 同一文件（导入去重不抓它，正留给「重复图片」模态处理）
        dr.rectangle([300, 40, 360, 100], fill=(245, 245, 245))
    im.save(path)


_pat(os.path.join(tmpd, 'dup_a.jpg'), 0)
_pat(os.path.join(tmpd, 'dup_b.jpg'), 0, extra_mark=True)   # 相似≠相同
_pat(os.path.join(tmpd, 'solo.jpg'), 3)       # 图案不同
_pat(os.path.join(tmpd, 'plist.jpg'), 5)      # 会被全景确认关联走
_pat(os.path.join(tmpd, 'pkg.jpg'), 8)        # 当包装照用（清理模态）
files = [('files', os.path.join(tmpd, f), f)
         for f in ('dup_a.jpg', 'dup_b.jpg', 'solo.jpg', 'plist.jpg', 'pkg.jpg')]
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 5 张', code == 200 and (r or {}).get('added', 0) == 5,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:100]))

d = http_json('/api/photos?container_id=%s&limit=20' % cid) or {}
byfile = {x['file'].split('/')[-1].split('\\')[-1]: x['id']
          for x in (d.get('items') or [])}
pid_a = byfile.get('dup_a.jpg')
pid_b = byfile.get('dup_b.jpg')
pid_g = byfile.get('pkg.jpg')
chk('0b 取到照片 id', all([pid_a, pid_b, pid_g]), byfile)

# 产品 + 关联 dup_a（全景候选与「建议保留已关联」都吃这条）
code, r = _req('POST', '/api/products/from-photo',
               {'code': 'GT-900', 'name': '全景产品', 'photo_ids': [pid_a]})
chk('0c 建产品并关联 dup_a', code == 200, r)

time.sleep(1)
edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,900', URL],
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
        excs = []

        async def cmd(method, params=None):
            _id[0] += 1
            await ws.send(json.dumps({'id': _id[0], 'method': method,
                                      'params': params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get('id') == _id[0]:
                    return m.get('result', {})
                if m.get('method') == 'Runtime.exceptionThrown':
                    excs.append(m['params'])

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
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str((ex.get('exception') or {}).get('description')
                                     or ex.get('text'))[:200]
            return (r.get('result') or {}).get('value')

        # ════ ① ③ 四档选项卡 ════
        await js("window.enterWizard('%s', 'photos')" % cid)
        for _ in range(30):
            await asyncio.sleep(0.5)
            n = await js("document.querySelectorAll('#wizShots .shot').length")
            if n:
                break
        await asyncio.sleep(1.5)
        await drain()
        tabs = await js("""(()=>[...document.querySelectorAll('#wShTabs [data-ptab]')]
            .map(b=>b.textContent.replace(/—|\\d+/g,'').trim()))()""")
        chk('1 ③ 选项卡=全部/已关联/待关联/已忽略/无效图片',
            tabs == ['全部', '已关联', '待关联', '已忽略', '无效图片'], tabs)
        inv_n = await js("""(()=>{const b=[...document.querySelectorAll(
            '#wShTabs [data-ptab]')].find(b=>b.dataset.ptab==='invalid');
            return b? b.querySelector('.n').textContent : 'NO-TAB';})()""")
        chk('2 无效档徽章初始为 0', str(inv_n) == '0', inv_n)
        # 🔴 老板反馈「③看不到批量选择」—— 按钮原先藏在只在待确认视图
        #    显示的 wSupBar 里。挪进常驻工具条后：正常视图必须可见可用
        vis = await js("""(()=>{const b=document.querySelector('#wSelBtn');
            return b? (b.offsetParent !== null) : 'NO-BTN';})()""")
        chk('2b 正常视图「批量选择」按钮可见', vis is True, vis)
        await js("document.querySelector('#wSelBtn').click()")
        await asyncio.sleep(0.8)
        bar_on = await js(
            "document.querySelector('#wSelBar').style.display !== 'none'")
        chk('2c 点后批量操作条出现', bar_on is True, bar_on)
        await js("document.querySelector('#wSelExit').click()")
        await asyncio.sleep(0.5)

        # ════ ② 抽屉全景图 ════
        await js("document.querySelector('#wizShots .shot[data-id=\\'%s\\']').click()"
                 % pid_a)
        await asyncio.sleep(2.5)
        await drain()
        pano_on = await js(
            "(()=>{const s=document.querySelector('#dwPanoSec');"
            "return s? s.style.display!=='none' : 'NO-SEC';})()")
        chk('3 全景段可见', pano_on is True, pano_on)
        pano_n = await js("document.querySelectorAll('#dwPano .pano-item').length")
        chk('4 全景候选 ≥2（dup_b/solo/plist 邻近）', (pano_n or 0) >= 2, pano_n)
        # 确认第一张候选 → 真关联落库（记录点的是哪张，别硬编码 dup_b）
        pano_pid = await js("""(()=>{const b=document.querySelector(
            '#dwPano [data-pano-link]');
            return b? b.dataset.panoLink : '';})()""")
        await js("document.querySelector('#dwPano [data-pano-link]').click()")
        await asyncio.sleep(1.2)
        await drain()
        await asyncio.sleep(1.3)
        await drain()
        links_c = http_json('/api/photos/%s' % pano_pid) or {}
        n_links = len(links_c.get('links') or [])
        chk('5 确认全景=真关联落库（候选张挂上 GT-900）', n_links == 1,
            'pid=%s links=%s' % (pano_pid,
                [l.get('code_norm') for l in (links_c.get('links') or [])]))

        # ════ ③ 改判即重治 ════
        # ⚠️ 全景确认成功后 doDrawerLink 把抽屉切到了被确认的那张 ——
        #    关掉重开 dup_a，改判才改的是目标照片。重开前必须等网格
        #    重渲完（photos:changed 会触发 loadWizardPhotos），并校验
        #    抽屉当前照片（#dwImg 的 data-pid），别改错张。
        await js("document.querySelector('#dwClose').click()")
        await asyncio.sleep(1.0)
        reopen = 'NO-CARD'
        for _ in range(30):
            await asyncio.sleep(0.5)
            reopen = await js("""(()=>{const c=document.querySelector(
                '#wizShots .shot[data-id="%s"]');
                if(!c) return 'NO-CARD';
                c.click(); return 'clicked';})()""" % pid_a)
            if reopen == 'clicked':
                break
        chk('5b 重开 dup_a 抽屉', reopen == 'clicked', reopen)
        await asyncio.sleep(2.0)
        await drain()
        cur_pid = await js(
            "(document.querySelector('#dwImg')||{dataset:{}}).dataset.pid||''")
        chk('5c 抽屉当前照片=dup_a', cur_pid == pid_a, cur_pid)
        await js("""(()=>{const s=document.querySelector('#dwKind');
            s.value='label'; s.dispatchEvent(new Event('change'));})()""")
        got_reg = 'NO'
        for _ in range(30):                       # OCR 可能要几秒，轮询 toast
            await asyncio.sleep(0.5)
            await drain()
            t = await js("(document.querySelector('#toast')||{}).textContent||''")
            if '重新识别' in (t or ''):
                got_reg = t
                break
        chk('6 改判后自动重治（toast 提示）', '已按「产品·有编码」重新识别' in (got_reg or ''),
            got_reg)
        kind_db = (http_json('/api/photos/%s' % pid_a) or {}).get('photo_kind')
        chk('7 改判落库 kind=label', kind_db == 'label', kind_db)
        await js("document.querySelector('#dwClose').click()")
        await asyncio.sleep(0.5)

        # ════ ④ 清单/包装清理 ════
        # plist 已被全景确认关联走了 —— 用独立的 pkg.jpg（包装照，未关联）
        code, r = _req('POST', '/api/photos/kind',
                       {'photo_ids': [pid_g], 'kind': 'packaging'})
        chk('8 后端把 pkg 判为包装', code == 200, r)
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(4.0)
        await drain()
        await js("window.enterWizard('%s', 'photos')" % cid)
        for _ in range(30):
            await asyncio.sleep(0.5)
            n = await js("document.querySelectorAll('#wizShots .shot').length")
            if n:
                break
        await asyncio.sleep(1.0)
        await js("document.querySelector('#wCleanInvalid').click()")
        await asyncio.sleep(1.5)
        await drain()
        dbg2 = await js("(()=>{return JSON.stringify({cid:(window.getCid? 'fn':'nofn'),"
            " toast:(document.querySelector('#toast')||{}).textContent?.slice(0,120)||'',"
            " modal:!!document.querySelector('.modal-head')});})()")
        print('[DBG] after-clean-click:', dbg2, flush=True)
        mt = await js("(document.querySelector('.modal-head b')||{}).textContent||''")
        chk('9 清理模态弹出（清单/包装照）', '清理' in (mt or ''), mt)
        body = await js("(document.querySelector('.modal-body')||{}).textContent||''")
        chk('10 模态识别到 1 张未关联清单照', '识别到 1 张' in (body or ''),
            (body or '')[:80])
        await js("document.querySelector('[data-m-ok]').click()")
        await asyncio.sleep(2.5)
        await drain()
        inv_n = await js("""(()=>{const b=[...document.querySelectorAll(
            '#wShTabs [data-ptab]')].find(b=>b.dataset.ptab==='invalid');
            return b? b.querySelector('.n').textContent : 'NO-TAB';})()""")
        chk('11 确认后无效档徽章=1（且同步刷新）', str(inv_n) == '1', inv_n)

        # ════ ⑤ 重复图片 ════
        await js("document.querySelector('#wDupBtn').click()")
        await asyncio.sleep(2.5)
        await drain()
        mt = await js("(document.querySelector('.modal-head b')||{}).textContent||''")
        chk('12 重复模态弹出（1 组）', '重复图片（1 组）' in (mt or ''), mt)
        keeps = await js("""(()=>{const k=document.querySelector('.duprow .keep .tag');
            return k? k.textContent : 'NO';})()""")
        # dup_a 已改判 label 且关联着 → 它当保留张；dup_b 进勾选
        keeps_ok = await js("""(()=>{const boxes=[...document.querySelectorAll(
            'input[data-dup-id]')];
            return JSON.stringify(boxes.map(x=>x.dataset.dupId));})()""")
        picked = json.loads(keeps_ok or '[]')
        chk('13 勾选集=重复张（dup_b）', picked == [pid_b], picked)
        # 🔴 老板实测：模态里图片裂的（thumb 字段没下发）—— 图片必须真加载
        img_ok = False
        for _ in range(20):
            await asyncio.sleep(0.5)
            w = await js("""(()=>{const im=document.querySelector('.duprow img');
                return im? im.naturalWidth : -1;})()""")
            if w and w > 0:
                img_ok = True
                break
        chk('12b 重复模态图片真实加载（naturalWidth>0）', img_ok,
            'naturalWidth=%s' % w)
        # 顺带核：占位兜底 —— thumb 对不存在路径返回 SVG 而非 500
        code_ph = http_json('/api/photos/dups?container_id=%s' % cid) or {}
        chk('12c dups 数据带 thumb 字段',
            bool((code_ph.get('groups') or [{}])[0].get('keep', {}).get('thumb')),
            'thumb')
        await js("document.querySelector('[data-m-ok]').click()")
        # 数据面探针：dup_b 是否真的标上了 + linkstate 是否给出 2
        await asyncio.sleep(1.5)
        await drain()
        pb = http_json('/api/photos/%s' % pid_b) or {}
        ls = http_json('/api/photos/linkstate?container_id=%s' % cid) or {}
        chk('14b 数据面：dup_b 已标无效且 linkstate 给出 2',
            pb.get('is_invalid') == 1 and ls.get('invalid') == 2,
            'is_invalid=%s linkstate=%s' % (pb.get('is_invalid'), ls.get('invalid')))
        # 徽章刷新走 photos:changed → loadPhotoTabs 重拉 linkstate ——
        # 轮询等它到 2，别用固定 sleep 读中间态
        inv_n = 'NO'
        for _ in range(20):
            await asyncio.sleep(0.5)
            await drain()
            inv_n = await js("""(()=>{const b=[...document.querySelectorAll(
                '#wShTabs [data-ptab]')].find(b=>b.dataset.ptab==='invalid');
                return b? b.querySelector('.n').textContent : 'NO-TAB';})()""")
            if str(inv_n) == '2':
                break
        chk('14 确认后无效档徽章=2（清单+重复张）', str(inv_n) == '2', inv_n)

        # 无效图片档列表
        await js("""(()=>{const b=[...document.querySelectorAll(
            '#wShTabs [data-ptab]')].find(b=>b.dataset.ptab==='invalid');
            b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        cards = await js("document.querySelectorAll('#wizShots .shot').length")
        chk('15 无效图片档列出 2 张', cards == 2, cards)

        # ════ 5d ③ 关联待办下拉 + 全选筛选结果 + 抽屉标无效（老板 10-15 追加）══
        # ⚠️ 先切回「全部」档 —— 15 的无效档是当前筛选的一部分，后续全选/
        #    抽屉操作都得在无档位筛选的状态下做，口径才对得上。
        await js("""(()=>{const b=[...document.querySelectorAll(
            '#wShTabs [data-ptab]')].find(x=>x.dataset.ptab==='');
            if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        # 待办下拉：选「待确认关联」后网格与 linkstate 同口径收窄
        await js("""(()=>{const s=document.querySelector('#wShCand');
            s.value='cand'; s.dispatchEvent(new Event('change'));})()""")
        wgrid = 'NO'
        for _ in range(16):
            await asyncio.sleep(0.5)
            await drain()
            wgrid = await js("document.querySelectorAll('#wizShots .shot').length")
            ls_w = http_json('/api/photos/linkstate?container_id=%s&todo=cand' % cid) or {}
            if wgrid == min(ls_w.get('all', -1), 60):
                break
        chk('15b ③待办下拉收窄（网格=待办集合）',
            wgrid == min(ls_w.get('all', -1), 60),
            'grid=%s linkstate.all=%s' % (wgrid, ls_w.get('all')))
        # 全选筛选结果在③（todo=cand 下 0 张 → 选 0；复位后再选全部）
        await js("document.querySelector('#wSelBtn').click()")
        await asyncio.sleep(0.6)
        await js("document.querySelector('#wSelAllFiltered').click()")
        await asyncio.sleep(2.5)
        await drain()
        sel_n = await js("document.querySelector('#wSelN').textContent")
        chk('15c ③全选筛选结果（待办口径）', str(sel_n) == str(ls_w.get('all', -1)),
            'selN=%s all=%s' % (sel_n, ls_w.get('all')))
        await js("""(()=>{const s=document.querySelector('#wShCand');
            s.value=''; s.dispatchEvent(new Event('change'));})()""")
        await asyncio.sleep(2.5)
        await drain()
        await js("document.querySelector('#wSelAllFiltered').click()")
        await asyncio.sleep(3.0)
        await drain()
        sel_n2 = await js("document.querySelector('#wSelN').textContent")
        t_d = await js("(document.querySelector('#toast')||{}).textContent||''")
        api_total = (http_json('/api/photos?container_id=%s&limit=1' % cid) or {}).get('total')
        print('[DBG] 15d selN=%r toast=%r api=%r' % (sel_n2, t_d[-80:], api_total),
              flush=True)
        chk('15d ③全选筛选结果=筛选总数', str(sel_n2) == str(api_total),
            'selN=%s api=%s' % (sel_n2, api_total))
        await js("document.querySelector('#wSelExit').click()")
        await asyncio.sleep(0.5)
        # 抽屉标无效在③（共享抽屉，老板要求详情页就地操作）
        opened = 'NO-CARD'
        for _ in range(16):
            await asyncio.sleep(0.5)
            opened = await js("""(()=>{const c=document.querySelector(
                '#wizShots .shot');
                if(!c) return 'NO-CARD';
                c.click();
                return document.querySelector('#dwImg')?
                    (document.querySelector('#dwImg').dataset.pid||'opened'):
                    'no-img';})()""")
            if opened not in ('NO-CARD', 'no-img'):
                break
        print('[DBG] 15e drawer opened pid:', opened, flush=True)
        inv_pid = opened if opened not in ('NO-CARD', 'no-img', 'opened') else ''
        has_inv = await js("!!document.querySelector('#dwInvalid')")
        print('[DBG] 15e dwInvalid exists:', has_inv, flush=True)
        await js("document.querySelector('#dwInvalid').click()")
        await asyncio.sleep(2.0)
        await drain()
        t_e = await js("(document.querySelector('#toast')||{}).textContent||''")
        inv_now = (http_json('/api/photos/%s' % inv_pid) or {}).get('is_invalid')
        print('[DBG] 15e toast:', repr(t_e[-60:]), 'is_invalid:', inv_now,
              flush=True)
        chk('15e ③抽屉标无效落库', inv_now == 1, inv_now)
        await js("document.querySelector('#dwInvalid').click()")
        await asyncio.sleep(2.0)
        await drain()
        inv_now2 = (http_json('/api/photos/%s' % inv_pid) or {}).get('is_invalid')
        chk('15f ③抽屉取消无效', inv_now2 == 0, inv_now2)
        await js("document.querySelector('#dwClose').click()")
        await asyncio.sleep(0.5)

        # ════ ⑥ 照片库：待办下拉 / 全选筛选结果 / 抽屉标无效 ════
        await js("window.go('batches')")
        await asyncio.sleep(3.0)
        await drain()
        # 待确认关联进查询条件（需求3）：选了之后列表=待办集合
        await js("""(()=>{const s=document.querySelector('#fCand');
            s.value='cand'; s.dispatchEvent(new Event('change'));})()""")
        await asyncio.sleep(3.0)
        await drain()
        ls_c = http_json('/api/photos/linkstate?container_id=%s&todo=cand' % cid) or {}
        grid_n = await js("document.querySelectorAll('#shots .shot').length")
        # 列表与徽章同源：网格首屏条数 = min(待办数, 每页 60)
        chk('17 待办下拉收窄（列表=待办集合）',
            grid_n == min(ls_c.get('all', -1), 60),
            'grid=%s linkstate.all=%s' % (grid_n, ls_c.get('all')))
        # 复位
        await js("""(()=>{const s=document.querySelector('#fCand');
            s.value=''; s.dispatchEvent(new Event('change'));})()""")
        await asyncio.sleep(2.5)
        await drain()
        # 全选当前筛选结果（需求1）：勾选数 = 筛选总数（跨页）
        await js("document.querySelector('#selBtn').click()")
        await asyncio.sleep(0.8)
        await js("document.querySelector('#selAllFiltered').click()")
        await asyncio.sleep(3.0)
        await drain()
        sel_n = await js("document.querySelector('#selN').textContent")
        api_total = (http_json('/api/photos?container_id=%s&limit=1' % cid) or {}).get('total')
        chk('18 全选筛选结果=筛选总数（跨页）', str(sel_n) == str(api_total),
            'selN=%s api=%s' % (sel_n, api_total))
        await js("document.querySelector('#selExit').click()")
        await asyncio.sleep(0.5)
        # 抽屉标无效 + 重新识别按钮（需求1/4）
        await js("document.querySelector('#shots .shot').click()")
        await asyncio.sleep(2.0)
        await drain()
        has_btn = await js("!!document.querySelector('#dwInvalid')")
        has_rg = await js("!!document.querySelector('#dwRegov')")
        chk('19 抽屉有标无效+重新识别按钮', has_btn is True and has_rg is True,
            'inv=%s regov=%s' % (has_btn, has_rg))
        inv_pid = await js(
            "(document.querySelector('#dwImg')||{dataset:{}}).dataset.pid||''")
        await js("document.querySelector('#dwInvalid').click()")
        await asyncio.sleep(2.0)
        await drain()
        inv_now = (http_json('/api/photos/%s' % inv_pid) or {}).get('is_invalid')
        chk('20 抽屉标无效落库', inv_now == 1, inv_now)
        await js("document.querySelector('#dwInvalid').click()")
        await asyncio.sleep(2.0)
        await drain()
        inv_now2 = (http_json('/api/photos/%s' % inv_pid) or {}).get('is_invalid')
        chk('21 再点取消无效', inv_now2 == 0, inv_now2)
        await js("document.querySelector('#dwClose').click()")
        await asyncio.sleep(0.5)

        # OCR 补跑端点形状（需求4）：status 可查、字段齐
        st_o = http_json('/api/govern/ocr-backfill/status') or {}
        chk('22 OCR 补跑状态端点字段齐',
            all(k in st_o for k in ('running', 'done', 'total', 'linked')), st_o)

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('16 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:300] if bad else ''))
    return not bad


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
print('PASS' if (res and not fails) else ('FAIL %d 项' % len(fails)))
sys.exit(0 if (res and not fails) else 1)
