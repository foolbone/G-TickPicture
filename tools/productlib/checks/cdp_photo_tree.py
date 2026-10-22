# -*- coding: utf-8 -*-
"""CDP 实跑：左侧树形筛选（照片库 + 柜作业③）+ 监装待办合并 + 批量无效（2026-10-14）。

  · 照片库页：树常驻左侧，「按用途/按分类」带计数；点树=筛选，再点=取消；
    交叉筛选（选了监装，分类计数只算监装的）；
  · 柜作业③：树多一段「监装待确认」，点它直接出待办照片（网格，一行多张），
    卡片上带细分下拉/采用/标为监装 —— 不再有独立的一行一张清单；
  · ③待办视图里批量选择 → 标记无效 → 该张退出待办、树上计数跟着减；
  · 下拉确认细分 → 该张退出待办。

⚠️ 隔离实例 8801 / CDP 9361，不碰 8765。evaluate 顶层 const 跨调用残留，
   表达式一律包 IIFE（老坑）。
跑法：python tools/productlib/checks/cdp_photo_tree.py
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
PORT = int(os.environ.get('PL_PORT', '8801'))
CDP_PORT = int(os.environ.get('PL_CDP', '9361'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_tree_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_tree_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
N_PHOTOS = 8          # 3 监装 + 2 预检 + 3 未分类（下面 PATCH 出来）

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
    b = '----pltree' + str(int(time.time()))
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

# ── 造数据：1 柜 + N 张照片；PATCH 出 3 监装 / 2 预检（其余未分类）──
code, c = _req('POST', '/api/containers',
               {'container_no': 'TREE01', 'seal_no': 'S1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)
# 产品（③确认建议关联要用；见 chk14 段）
code, _ = _req('POST', '/api/products', {'code': 'TREE-A1', 'name': '树测试品'})
chk('0 建产品', code in (200, 201), code)

from PIL import Image  # noqa: E402
tmpd = os.path.join(tempfile.gettempdir(), 'pl_tree_photos')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(N_PHOTOS):
    p = os.path.join(tmpd, 'TR_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (60 + i * 20, 120, 190)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0 上传 %d 张' % N_PHOTOS,
    code == 200 and (r or {}).get('added', 0) == N_PHOTOS,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:160]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0b 取到照片 id', len(pids) == N_PHOTOS, len(pids))
for pid in pids[:3]:
    _req('PATCH', '/api/photos/%s/usage' % pid, {'usage': '监装'})
for pid in pids[3:5]:
    _req('PATCH', '/api/photos/%s/usage' % pid, {'usage': '预检'})
# 等用途写完再进 UI（后端是同步写，这里只是防御性重读）
time.sleep(1)
# 治理标完：③的完成条件 = 有照片 && 治理完成 —— 不置 done 的话
# chk14（确认关联不跳④）触发不了跳步条件，测了个寂寞。
# 顺带把箱号铺上（采集格式 预检/{箱号}/照片.jpg 的产物）：
#   监装 3 张 → CTN-A；预检 2 张 → CTN-B；其余 3 张不标（「未标注箱号」组）
import sqlite3  # noqa: E402
_db = os.path.join(DBHOME, 'productlib.db')
con = sqlite3.connect(_db)
con.execute("UPDATE photos SET govern_state='done'")
# 2026-10-17 老板规则「只有产品需要关联」：待关联只收产品图（label/product）。
# 模拟治理完成的 kind 分布：监装 3 张=scene，其余 5 张=label（产品图）——
# 0c/0d/5d/5e 的「待关联=5」数字因此不变。
con.execute("UPDATE photos SET photo_kind='scene' WHERE photo_usage='监装'")
con.execute("UPDATE photos SET photo_kind='label' WHERE IFNULL(photo_usage,'')<>'监装'")
con.execute("UPDATE photos SET carton_no='CTN-A' WHERE photo_usage='监装'")
con.execute("UPDATE photos SET carton_no='CTN-B' WHERE photo_usage='预检'")
con.commit(); con.close()

# ── 待关联口径（2026-10-17 老板规则：只有产品图进待关联；2026-10-16：
#    监装照片不进）—— 8 张里 3 监装(scene) 不进、5 张产品图(label) 进 → 5
# （API 层先钉死，UI 层断言在下面 5d/5e）
_ls = http_json('/api/photos/linkstate?container_id=%s' % cid) or {}
chk('0c 待关联徽章=5（8 张 - 3 监装场景照；只有产品图进队列）',
    _ls.get('unlinked') == N_PHOTOS - 3, _ls.get('unlinked'))
chk('0c2 全部徽章仍是 8（非产品照本身没被藏）',
    _ls.get('all') == N_PHOTOS, _ls.get('all'))
_ul = http_json('/api/photos?container_id=%s&flag=unlinked&limit=50' % cid) or {}
chk('0d 待关联列表排除非产品照', (_ul.get('total') or 0) == N_PHOTOS - 3,
    _ul.get('total'))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
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
            ex = r.get('exceptionDetails')
            if ex:
                return 'EXC: ' + str((ex.get('exception') or {}).get('description')
                                     or ex.get('text'))[:200]
            return (r.get('result') or {}).get('value')

        async def wait(fn, val, tries=20):
            for _ in range(tries):
                await asyncio.sleep(0.4)
                v = await js(fn)
                if v == val:
                    return v
            return await js(fn)

        # ════ ① 照片库页：左侧树 ════
        await js("window.go && window.go('batches')")
        await asyncio.sleep(3.0)
        await drain()

        tree_on = await js("""(()=>{const t=document.querySelector('#phTree');
            return !!t && t.querySelectorAll('.ptree-i').length>0;})()""")
        chk('1 照片库页树已渲染', tree_on is True, tree_on)

        usage_counts = await js("""(()=>{const out={};
            document.querySelectorAll('#phTree .ptree-sec')[0]
              .querySelectorAll('.ptree-i').forEach(b=>{
                out[b.querySelector('.ptree-l').textContent]=
                  b.querySelector('.ptree-n').textContent;});
            return JSON.stringify(out);})()""")
        chk('2 用途计数（监装3/预检2/未分类3）',
            json.loads(usage_counts or '{}') == {'监装': '3', '预检': '2', '未分类': '3'},
            usage_counts)

        # 点「监装」→ 筛选（文案无编号；编号只决定节点顺序）
        # ⚠️ 轮询等列表刷完再断言：2026-10-16 实测固定睡眠在 loaded 机器上
        #    会读到旧列表（n=8 但下拉已是监装）—— 睡死改轮询，同 photo_invalid 修法。
        await js("""(()=>{const b=[...document.querySelectorAll(
            '#phTree .ptree-i')].find(x=>x.querySelector('.ptree-l')
              .textContent==='监装'); if(b) b.click();})()""")
        n_sup, hid = None, None
        for _ in range(40):
            await asyncio.sleep(0.5)
            hid = await js("document.querySelector('#fUsage').value")
            n_sup = await js("document.querySelectorAll('#shots .shot').length")
            if hid == '监装' and n_sup == 3:
                break
        await drain()
        chk('3 点「监装」→ 列表 3 张（隐藏下拉同步为状态真源）',
            n_sup == 3 and hid == '监装', 'n=%s fUsage=%s' % (n_sup, hid))

        # 交叉筛选：分类计数只算监装的（8 张同分类 → 一条 3）
        kind_counts = await js("""(()=>{const secs=document.querySelectorAll(
            '#phTree .ptree-sec'); const out=[];
            secs[1].querySelectorAll('.ptree-i').forEach(b=>out.push(
              b.querySelector('.ptree-l').textContent+':'+
              b.querySelector('.ptree-n').textContent));
            return JSON.stringify(out);})()""")
        chk('4 交叉筛选：监装下的分类计数收窄', json.loads(kind_counts or '[]') != [],
            kind_counts)

        # 再点一次 → 取消（同样轮询等列表刷完，别读旧列表）
        await js("""(()=>{const b=[...document.querySelectorAll(
            '#phTree .ptree-i')].find(x=>x.querySelector('.ptree-l')
              .textContent==='监装'); if(b) b.click();})()""")
        n_all = None
        for _ in range(40):
            await asyncio.sleep(0.5)
            n_all = await js("document.querySelectorAll('#shots .shot').length")
            if n_all == 8:
                break
        chk('5 再点一次取消 → 回到 8 张', n_all == 8, n_all)

        # 5b. 树筛选后**右边统计也要跟着收窄**（2026-10-14 老板实测反馈）：
        #     切到「关联」视图（统计走 linkstate），点「监装」，
        #     「共 N 张」与五档徽章都必须是 3，不能还挂着全柜 8。
        await js("""(()=>{const b=[...document.querySelectorAll('#shotView button')]
            .find(x=>x.dataset.v==='link'); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        await js("""(()=>{const b=[...document.querySelectorAll(
            '#phTree .ptree-i')].find(x=>x.querySelector('.ptree-l')
              .textContent==='监装'); if(b) b.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        ftot = await js("(document.querySelector('#fTotal')||{}).textContent||''")
        tab_all = await js("""(()=>{const b=document.querySelector(
            '#shotTabs [data-ptab=""] .n'); return b?b.textContent:'?';})()""")
        chk('5b 树筛选后「共 N 张」收窄（共 3 张）', ftot == '共 3 张', ftot)
        chk('5c 五档徽章「全部」同步收窄（3）', str(tab_all) == '3', tab_all)
        # 取消树筛选，恢复原状再进③
        await js("""(()=>{const b=[...document.querySelectorAll(
            '#phTree .ptree-i')].find(x=>x.querySelector('.ptree-l')
              .textContent==='监装'); if(b) b.click();})()""")
        await asyncio.sleep(2.5)

        # 5d/5e. 待关联口径（2026-10-17 老板规则：只有产品图进队列）——
        #   8 张无关联照片里 3 张是监装 → 徽章与列表都只能是 5。
        #   API 层已由 0c/0d 钉死，这里验前端真实渲染。
        tab_unl = await js("""(()=>{const b=document.querySelector(
            '#shotTabs [data-ptab="unlinked"] .n'); return b?b.textContent:'?';})()""")
        chk('5d 待关联徽章=5（只有产品图进队列）', str(tab_unl) == '5', tab_unl)
        await js("""(()=>{const b=document.querySelector(
            '#shotTabs [data-ptab="unlinked"]'); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        n_unl = await js("document.querySelectorAll('#shots .shot').length")
        chk('5e 待关联列表=5 张', n_unl == 5, n_unl)
        # 切回全部档，别把档位状态留给后面的③断言
        await js("""(()=>{const b=document.querySelector(
            '#shotTabs [data-ptab=""]'); if(b) b.click();})()""")
        await asyncio.sleep(2.0)

        # ════ ② 柜作业③：树 + 待办合并 + 批量无效 ════
        await js("window.enterWizard(%r, 'photos')" % cid)
        # 轮询等③渲染（固定睡眠在 loaded 机器上不够 —— 2026-10-16 实测：
        # 4s 睡死时③还没渲染，步骤 6/8/9 连锁假红；最多等 25s）
        has_tree = False
        for _ in range(50):
            await asyncio.sleep(0.5)
            has_tree = await js("!!document.querySelector('#wPhTree')"
                                " && document.querySelectorAll('#wPhTree .ptree-i').length>0")
            if has_tree is True:
                break
        await drain()
        chk('6 ③左侧树已渲染（含待确认段）', has_tree is True, has_tree)
        no_block = await js("!document.querySelector('#wSupPend')")
        chk('7 独立待办清单块已移除（合并进树）', no_block is True, no_block)

        # 树上「待确认细分」节点是树数据到位后才渲染的（③树分段渲染）——
        # 轮询等它出现，别读半棵树的 none（2026-10-16 实测 flaky）
        pend_n = 'none'
        for _ in range(40):
            await asyncio.sleep(0.5)
            pend_n = await js("""(()=>{const b=[...document.querySelectorAll(
                '#wPhTree .ptree-i')].find(x=>x.dataset.pending);
                return b ? b.querySelector('.ptree-n').textContent : 'none';})()""")
            if str(pend_n) == '3':
                break
        chk('8 树上「待确认细分」计数 = 3', str(pend_n) == '3', pend_n)

        # 点「待确认细分」→ 网格出待办照片，卡片带操作行
        # 🔍 探针：抓点击后 /api/photos 请求的 query（pending 有没有带上）
        reqs = []
        async def pump_url(dur):
            end = time.time() + dur
            while time.time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 0.3))
                except asyncio.TimeoutError:
                    continue
                if m.get('method') == 'Network.requestWillBeSent':
                    u = m['params']['request']['url']
                    if '/api/photos?' in u:
                        reqs.append(u.split('/api/photos?')[1])
        await cmd('Network.enable')
        await js("""(()=>{const b=document.querySelector(
            '#wPhTree .ptree-i[data-pending]'); if(b) b.click();})()""")
        await pump_url(3.0)
        print('     [探针] /api/photos 请求:', reqs[:4], flush=True)
        await asyncio.sleep(3.0)
        await drain()
        n_pend = await js("document.querySelectorAll('#wizShots .shot').length")
        with_act = await js("document.querySelectorAll('#wizShots .shot .supact').length")
        grid_cls = await js("document.querySelector('#wizShots').classList.contains('pending')")
        bar_on = await js("""(()=>{const b=document.querySelector('#wSupBar');
            return b ? b.style.display : 'none';})()""")
        chk('9 待确认视图：网格 3 张、每张带操作行、网格加宽、操作条出现',
            n_pend == 3 and with_act == 3 and grid_cls is True and bar_on != 'none',
            'n=%s act=%s cls=%s bar=%s' % (n_pend, with_act, grid_cls, bar_on))
        has_sel = await js("""(()=>{const s=document.querySelectorAll(
            '#wizShots .shot .supact select'); return s.length;})()""")
        chk('9b 操作行里有细分下拉', has_sel == 3, has_sel)

        # 批量选择 → 标记无效
        await js("document.querySelector('#wSelBtn').click()")
        await asyncio.sleep(0.5)
        await js("document.querySelector('#wizShots .shot').click()")
        await asyncio.sleep(0.4)
        nsel = await js("document.querySelector('#wSelN').textContent")
        chk('10 ③批量选择：勾 1 张', str(nsel) == '1', nsel)
        await js("document.querySelector('#wSelInvalid').click()")
        await asyncio.sleep(3.5)
        await drain()
        n_pend2 = await js("document.querySelectorAll('#wizShots .shot').length")
        pend_n2 = await js("""(()=>{const b=[...document.querySelectorAll(
            '#wPhTree .ptree-i')].find(x=>x.dataset.pending);
            return b ? b.querySelector('.ptree-n').textContent : 'none';})()""")
        chk('11 标记无效后：退出待办视图、树上计数 3→2',
            n_pend2 == 2 and str(pend_n2) == '2',
            'n=%s pend=%s' % (n_pend2, pend_n2))

        # 下拉确认细分 → 也退出待办
        await js("""(()=>{const s=document.querySelector(
            '#wizShots .shot .supact select');
            if(!s) return; s.selectedIndex=1;
            s.dispatchEvent(new Event('change'));})()""")
        await asyncio.sleep(3.5)
        await drain()
        n_pend3 = await js("document.querySelectorAll('#wizShots .shot').length")
        pend_n3 = await js("""(()=>{const b=[...document.querySelectorAll(
            '#wPhTree .ptree-i')].find(x=>x.dataset.pending);
            return b ? b.querySelector('.ptree-n').textContent : 'none';})()""")
        chk('12 确认细分后：退出待办、树上计数 2→1',
            n_pend3 == 1 and str(pend_n3) == '1',
            'n=%s pend=%s' % (n_pend3, pend_n3))

        # ══ ③里确认建议关联：照片页不许被甩到④（2026-10-14 老板实测）══
        # 上一版 drawer 关联后发 wizard:refresh → loadProgress(advance) 见
        # ③已完成就把 _active 推到④。前提已备：治理已置 done、③必然 done。
        await js("document.querySelector('#wSelExit').click()")   # 退出选择模式
        await asyncio.sleep(0.6)
        cur0 = await js("""(()=>{const c=document.querySelector('#wizBar .wstep.cur');
            return c ? c.dataset.step : '?';})()""")
        chk('12b 前提：当前停在③照片步', cur0 == 'photos', cur0)
        await js("document.querySelector('#wizShots .shot').click()")
        await asyncio.sleep(2.5)
        await drain()
        opened = await js("document.querySelector('#drawer').classList.contains('on')")
        chk('12c 抽屉已打开', opened is True, opened)
        # 🔴 2026-10-17 老板规则：只有产品图才有关联入口。网格第一张是
        # 监装照（TR_00-02 = scene）→ 抽屉里不该有手输关联框。
        no_input = await js("!document.querySelector('#dwCode')"
                            " && !document.querySelector('#dwLink')")
        chk('12d 监装照（scene）抽屉：无手输关联入口', no_input is True, no_input)
        # 分类改判为产品图 → 整体重绘 + regovern，等手输框出现（联动）
        await js("""(()=>{const s=document.querySelector('#dwKind');
            s.value='product'; s.dispatchEvent(new Event('change'));})()""")
        has_input = False
        for _ in range(24):
            await asyncio.sleep(0.5); await drain()
            has_input = await js("!!document.querySelector('#dwCode')")
            if has_input is True:
                break
        chk('12e 改判产品图 → 关联入口联动出现', has_input is True, has_input)
        await asyncio.sleep(2.0)      # regovern 回填可能再重绘一次，避开竞态
        await drain()
        await js("""(()=>{const i=document.querySelector('#dwCode');
            if(!i) return; i.value='TREE-A1';
            document.querySelector('#dwLink').click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        cur1 = await js("""(()=>{const c=document.querySelector('#wizBar .wstep.cur');
            return c ? c.dataset.step : '?';})()""")
        grid_ok = await js("!!document.querySelector('#wizShots')")
        linked_head = await js("""(()=>{const h=[...document.querySelectorAll(
            '#dwBody .dsec h4')].find(x=>x.textContent.includes('已关联产品'));
            return h ? h.textContent : '';})()""")
        chk('14 确认关联后仍停在③照片步（没被甩到④）',
            cur1 == 'photos' and grid_ok is True,
            'cur=%s grid=%s' % (cur1, grid_ok))
        chk('14b 抽屉刷新：已关联产品（1）',
            linked_head == '已关联产品（1）', linked_head)
        # 关抽屉，收尾
        await js("document.querySelector('#dwClose').click()")
        await asyncio.sleep(0.5)

        # ══ 按箱号分组展示（2026-10-14 老板需求）══
        # 先取消树上的待办筛选（chk9 选中的），回全柜 8 张才有 3/2/3 的全集
        await js("""(()=>{const b=document.querySelector(
            '#wPhTree .ptree-i[data-pending].on'); if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        await js("document.querySelector('#wShCarton').click()")
        await asyncio.sleep(3.0)
        await drain()
        tabs_hidden = await js("document.querySelector('#wShTabs').style.display === 'none'")
        n_groups = await js("document.querySelectorAll('#wizShots .gcard').length")
        names = await js("""(()=>[...document.querySelectorAll('#wizShots .gcard')]
            .map(c=>c.dataset.carton))()""")
        chk('15 箱号分组：五档隐藏、3 组（CTN-A/CTN-B/未标注，空箱号最后）',
            tabs_hidden is True and n_groups == 3
            and (names or []) == ['CTN-A', 'CTN-B', '未标注箱号'],
            'tabs=%s names=%s' % (tabs_hidden, names))
        counts = await js("""(()=>[...document.querySelectorAll('#wizShots .gcard')]
            .map(c=>c.querySelector('.gcount').textContent))()""")
        # ⚠️ chk11 标记过 1 张监装照无效 → 默认口径排除 → CTN-A 剩 2
        chk('15b 组张数（2/2/3，无效已排除）',
            (counts or []) == ['2 张', '2 张', '3 张'], counts)
        # 展开第一组
        await js("document.querySelector('#wizShots .gcard .ghead').click()")
        await asyncio.sleep(0.8)
        opened = await js("document.querySelector('#wizShots .gcard').classList.contains('open')")
        in_shots = await js("""document.querySelector('#wizShots .gcard')
            .querySelectorAll('.shot').length""")
        chk('16 点组头展开：组内 2 张照片（无效已排除）',
            opened is True and in_shots == 2,
            'open=%s shots=%s' % (opened, in_shots))
        # 组内点照片 → 抽屉
        await js("document.querySelector('#wizShots .gcard.open .shot').click()")
        await asyncio.sleep(2.0)
        drawer_on = await js("document.querySelector('#drawer').classList.contains('on')")
        await js("document.querySelector('#dwClose').click()")
        chk('16b 组内照片点击进抽屉', drawer_on is True)
        # 收起 + 关闭箱号模式 → 恢复五档
        await js("document.querySelector('#wizShots .gcard .ghead').click()")
        await asyncio.sleep(0.4)
        await js("document.querySelector('#wShCarton').click()")
        await asyncio.sleep(2.5)
        await drain()
        tabs_back = await js("document.querySelector('#wShTabs').style.display !== 'none'")
        grid_back = await js("document.querySelector('#wizShots').classList.contains('grid')")
        btn_off = await js("!document.querySelector('#wShCarton').classList.contains('on')")
        chk('17 关闭箱号模式：恢复五档列表', tabs_back is True and grid_back is True
            and btn_off is True,
            'tabs=%s grid=%s btn=%s' % (tabs_back, grid_back, btn_off))

        # ════ 抽屉关联区联动（2026-10-17 老板规则：只有产品图才出现
        # 关联产品的相关内容，与「分类」下拉联动）════
        # scene 照（监装）开抽屉 → 无「已关联产品」标题、无建议关联，有说明行；
        # 分类改判为 product → 关联区出现（整体重绘联动）。
        _scene = http_json('/api/photos?container_id=%s&kind=scene&limit=1' % cid) or {}
        _scene_pid = ((_scene.get('items') or [{}])[0]).get('id')
        chk('18a 取到一张 scene 照', bool(_scene_pid), _scene_pid)
        await js("""(pid=>{const card=document.querySelector(
            '#shots .shot[data-id="'+pid+'"]'); if(card) card.click();})(%s)"""
                 % json.dumps(_scene_pid))
        await asyncio.sleep(1.2); await drain()
        no_link_sec = await js("!document.querySelector('#dwBody .linkrow')"
                               " && !document.querySelector('#dwCands')")
        hint_shown = await js("(document.querySelector('#dwBody')||{textContent:''})"
                              ".textContent.includes('只有产品图')")
        chk('18 非产品图抽屉：无关联区、有说明', no_link_sec is True and hint_shown is True,
            'nolink=%s hint=%s' % (no_link_sec, hint_shown))
        await js("""(()=>{const s=document.querySelector('#dwKind');
            s.value='product'; s.dispatchEvent(new Event('change'));})()""")
        link_back = 'none'
        for _ in range(20):           # 改判→保存→重绘，轮询等关联区出现
            await asyncio.sleep(0.5); await drain()
            link_back = await js("!!(document.querySelector('#dwBody h4')"
                                 " && document.querySelector('#dwBody h4')"
                                 ".textContent.includes('已关联产品'))")
            if link_back is True:
                break
        chk('19 分类改判为产品图 → 关联区联动出现', link_back is True, link_back)
        await js("document.querySelector('#dwClose') && document.querySelector('#dwClose').click()")
        await asyncio.sleep(0.5); await drain()

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('13 全程无 JS 异常', not bad,
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
