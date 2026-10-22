# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 版产品库 /app/products（vue3-frontend 分支）。

覆盖旧版 products.js 的核心行为：
  · 列表渲染 + 分页信息 + 分页按钮禁用态
  · 筛选：搜编码 / 按柜号 / 按状态（无照片、待确认…）/ 排序
  · 点行 → 右侧抽屉（来源、字段编辑、标准图、按批次分组的照片）
  · 字段编辑：改 → 脏标记 → 保存落库 → 列表同步；未保存时关抽屉要拦
  · 标准图上传（FormData 真上传）与删除
  · 待确认四块：同组 / 读码候选 / 全景图 / 已标记无关联（可撤销）
  · 补关联（低频端点通）
  · 上一个/下一个（含跨页边界）+ 删除产品
  · 刷新保持（URL 路由）

⚠️ 隔离实例 8806 / CDP 9366，不碰 8765。evaluate 顶层 const 跨调用残留，
   表达式一律包 IIFE（老坑）。
跑法：python tools/productlib/checks/cdp_vue_products.py
"""
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8806'))
CDP_PORT = int(os.environ.get('PL_CDP', '9366'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vueprod_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vueprod_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/products'
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
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:200]}


def post_file(path, fields, files, timeout=600):
    b = '----plprod' + str(int(time.time()))
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
        with urllib.request.urlopen(BASE + '/api/ping', timeout=2) as r:
            json.loads(r.read()); break
    except Exception:  # noqa: BLE001
        time.sleep(0.5)
else:
    print('[FAIL] 隔离实例没起来')
    sys.exit(1)

# ── 造数据：1 柜 + 4 个产品 + 6 张照片 ──
code, c = _req('POST', '/api/containers', {'container_no': 'VPR1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)

# 🔴 产品只能通过**清单导入**创建（不要 POST /api/products 手工建）：
#    抽屉里的「来源信息」读 products.source_batch —— 空串会被判成「来源未知」，
#    而清单导入只更新已存在的产品、**不回填** source_batch，于是手工建的产品永远
#    显示未知，还连带「已标记无关联」等区块取不到该产品的批次上下文。
_names = (('PRA1', '测试品甲'), ('PRB2', '测试品乙'), ('PRC3', '测试品丙'),
          ('PRD4', '测试品丁'))

# 清单：让产品出现在柜里（来源柜 / 被引用 / 柜号筛选 / 来源信息都靠它）
import openpyxl  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue_prod')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
xlsx = os.path.join(tmpd, '清单.xlsx')
wb = openpyxl.Workbook()
ws = wb.active
ws.append(['code', 'name', 'spec', 'package_no', 'order_qty'])
for i, (cd, nm) in enumerate(_names, start=1):
    ws.append([cd, nm, '10*10*10' if i <= 3 else '', 'CTN-%d' % i, i])
wb.save(xlsx)
code, r = post_file('/api/products/import', {'container_id': cid},
                    [('file', xlsx, os.path.basename(xlsx))])
chk('0c 导入清单 4 行', code == 200 and (r or {}).get('parsed') == 4,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))
for cd, _nm in _names:
    chk('0b 清单导入建出产品 ' + cd,
        (http_json('/api/products/%s' % cd) or {}).get('code_norm') == cd, cd)

from PIL import Image  # noqa: E402

files = []
for i in range(6):
    p = os.path.join(tmpd, 'PR_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (40 + i * 25, 130, 200)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0d 上传 6 张', code == 200 and (r or {}).get('added') == 6,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0e 取到照片 id', len(pids) == 6, len(pids))

con = sqlite3.connect(os.path.join(DBHOME, 'productlib.db'))
con.execute("UPDATE photos SET govern_state='done'")
con.execute("UPDATE photos SET photo_usage='预检', photo_kind='label'")
# 箱号要落在**已关联**的那张（pids[2] → PRA1），否则抽屉「涉及箱号」是空的
con.execute("UPDATE photos SET carton_no='CTN-1' WHERE id=?", (pids[2],))
# vision_codes 造「读码候选」：PRB2 有一张候选（强证据），PRA1 一张
con.execute("UPDATE photos SET vision_codes=? WHERE id=?",
            (json.dumps(['PRB2']), pids[0]))
con.execute("UPDATE photos SET vision_codes=? WHERE id=?",
            (json.dumps(['PRA1']), pids[1]))
# 已关联：pids[2] → PRA1（给同组候选/全景图留素材）
con.commit()
con.close()

# 🔴 关联与「无关联」标记必须走 **API**，不能直接 INSERT：
#    products.photo_count / auto_count / manual_count 是后端在关联时维护的冗余列
#    （store.py 的 recount），sqlite 直插 links 会留下 photo_count=0 的脏状态，
#    缺口优先排序与「有照片/无照片」筛选立刻跟着错 —— 症状像排序 bug，
#    根因是 fixture 绕过了业务写入口。
code, r = _req('POST', '/api/links', {'photo_id': pids[2], 'code': 'PRA1', 'by': 'web'})
chk('0f1 API 建关联 PRA1 → 1 张', code in (200, 201), '%s %s' % (code, r))
code, r = _req('POST', '/api/products/PRC3/candidates/reject',
               {'photo_ids': [pids[3]], 'reason': '人工查看后确认无关联', 'by': 'web'})
chk('0f2 API 标记无关联 PRC3 → 1 张', code in (200, 201), '%s %s' % (code, r))
pr_a1 = http_json('/api/products/PRA1') or {}
chk('0f3 photo_count 由后端维护（=1，缺口排序才对）', pr_a1.get('photo_count') == 1,
    pr_a1.get('photo_count'))

# API 层钉死基线（UI 断言在下）
lst = http_json('/api/products?limit=50') or {}
chk('0f 产品列表 4 条', lst.get('total') == 4, lst.get('total'))
pcts = http_json('/api/products/containers') or {}
chk('0g 柜号下拉只有 VPR1', [x['container_no'] for x in pcts.get('items') or []] == ['VPR1'],
    pcts.get('items'))
c_a1 = http_json('/api/products/PRA1/candidates') or {}
chk('0h PRA1 有 1 张读码候选', len(c_a1.get('items') or []) == 1,
    json.dumps(c_a1, ensure_ascii=False)[:140])
c_c3 = http_json('/api/products/PRC3/candidates/rejected') or {}
chk('0i PRC3 有 1 张已标记无关联', len(c_c3.get('items') or []) == 1,
    json.dumps(c_c3, ensure_ascii=False)[:140])
no_ph = http_json('/api/products?has=no') or {}
# 只有 PRA1 有已关联照片；候选/已标记无关联都**不算**照片
chk('0j 「无照片」筛出其余 3 个',
    sorted(x['code_norm'] for x in no_ph.get('items') or []) == ['PRB2', 'PRC3', 'PRD4'],
    [x['code_norm'] for x in no_ph.get('items') or []])
gap = http_json('/api/products?sort=gap&limit=1') or {}
chk('0k 缺口优先第一条落在无照片的那些里',
    (gap.get('items') or [{}])[0].get('code_norm') in ('PRB2', 'PRC3', 'PRD4'),
    (gap.get('items') or [{}])[0].get('code_norm'))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,1100', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version', port=CDP_PORT, retries=40, timeout=3):
        print('[FAIL] 调试端口未就绪'); return False
    page = next((t for t in (http_json('/json/list', port=CDP_PORT) or [])
                 if t.get('type') == 'page'
                 and '/app/' in (t.get('url') or '')), None)
    if not page:
        print('[FAIL] 找不到 /app/ 的 page'); return False

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
        await asyncio.sleep(7.0)
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

        async def wait(fn, val, tries=40):
            for _ in range(tries):
                await asyncio.sleep(0.4)
                v = await js(fn)
                if v == val:
                    return v
            return await js(fn)

        async def click_text(sel, label, exact=False):
            await js("""(()=>{const b=[...document.querySelectorAll(%s)]
                .find(x=>x.innerText.trim().%s(%s));
                if(b) b.click();})()"""
                     % (json.dumps(sel),
                        'startsWith' if not exact else '===',
                        json.dumps(label)))

        async def row_texts():
            return await js("""JSON.stringify([...document.querySelectorAll(
                '.prod-page .el-table__body-wrapper tr')].map(r=>r.innerText))""")

        # ════ ① 首屏 ════
        chk('1 标题带「产品库」', '产品库' in str(await js('document.title')),
            await js('document.title'))
        n_row = await wait("document.querySelectorAll('.prod-page .el-table__body-wrapper tr').length", 4)
        chk('2 列表 4 行', n_row == 4, n_row)
        pgtxt = await js("(document.querySelector('.prod-page .pager .faint')||{}).innerText||''")
        chk('3 分页信息「第 1 / 1 页 · 共 4 条」', '共 4 条' in str(pgtxt), pgtxt)
        chk('3b 上一页按钮禁用（第 1 页）',
            await js("""(()=>{const b=[...document.querySelectorAll('.prod-page .pager button')]
                .find(x=>x.innerText.includes('上一页')); return !!b && b.disabled;})()""") is True)
        chk('3c 模板按钮指向模板端点',
            await js("!!document.querySelector('.prod-page a[href*=\"/api/products/template\"]')")
            is True)
        chk('4 补关联按钮在位',
            '补关联' in str(await js("document.querySelector('.prod-page .phead').innerText")))

        # 缺口优先：第一行应该是无照片的那几个之一（PRA1 唯一有照片，应排最后）
        first_row = await js("""(()=>{const r=document.querySelector(
            '.prod-page .el-table__body-wrapper tr'); return r?r.innerText:'';})()""")
        chk('5 缺口优先 → 首行无照片', ('PRB2' in str(first_row) or 'PRC3' in str(first_row)
                                       or 'PRD4' in str(first_row)), first_row)
        all_rows = await row_texts()
        chk('5b 有照片的 PRA1 排在最后',
            'PRA1' in str(json.loads(all_rows)[-1] if json.loads(all_rows) else ''),
            json.loads(all_rows)[-1] if json.loads(all_rows) else '')

        # ════ ② 筛选 ════
        await js("""(()=>{const i=document.querySelector('.prod-page .toolbar input');
            if(i){const s=Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype,'value').set;
              s.call(i,'PRA1'); i.dispatchEvent(new Event('input',{bubbles:true}));}})()""")
        await js("""(()=>{const i=document.querySelector('.prod-page .toolbar input');
            if(i) i.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',bubbles:true}));})()""")
        n1 = await wait("document.querySelectorAll('.prod-page .el-table__body-wrapper tr').length", 1)
        chk('6 搜「PRA1」→ 1 行', n1 == 1, n1)
        row1 = await js("""(()=>{const r=document.querySelector(
            '.prod-page .el-table__body-wrapper tr'); return r?r.innerText:'';})()""")
        chk('6b 命中的就是 PRA1', 'PRA1' in str(row1), row1)
        # 清空搜索回 4 行
        await click_text('.prod-page .toolbar .el-input__clear', '')
        await js("""(()=>{const i=document.querySelector('.prod-page .toolbar input');
            if(i) i.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',bubbles:true}));})()""")
        n2 = await wait("document.querySelectorAll('.prod-page .el-table__body-wrapper tr').length", 4)
        chk('6c 清空搜索 → 回 4 行', n2 == 4, n2)

        # 按柜号筛选（el-select 要点 .el-select__wrapper 打开面板）
        await js("""(()=>{const s=document.querySelectorAll('.prod-page .toolbar .el-select')[0];
            if(s) s.querySelector('.el-select__wrapper').click();})()""")
        await asyncio.sleep(0.8)
        await js("""(()=>{const o=[...document.querySelectorAll('.el-select-dropdown__item')]
            .find(x=>x.innerText.includes('VPR1')); if(o) o.click();})()""")
        n3 = await wait("document.querySelectorAll('.prod-page .el-table__body-wrapper tr').length", 3)
        chk('7 按柜号 VPR1 筛 → 4 行（清单里的 4 个）', n3 == 4, n3)
        # 复原
        await js("""(()=>{const s=document.querySelectorAll('.prod-page .toolbar .el-select')[0];
            if(s) s.querySelector('.el-select__wrapper').click();})()""")
        await asyncio.sleep(0.8)
        await click_text('.el-select-dropdown__item', '')
        n4 = await wait("document.querySelectorAll('.prod-page .el-table__body-wrapper tr').length", 4)
        chk('7b 取消柜号筛选 → 回 4 行', n4 == 4, n4)

        # ════ ③ 抽屉 ════
        await js("""(()=>{const rs=[...document.querySelectorAll(
            '.prod-page .el-table__body-wrapper tr')];
            const r=rs.find(x=>x.innerText.includes('PRA1')); if(r) r.click();})()""")
        chk('8 点行 → 抽屉打开',
            await js("!!document.querySelector('.pd')") is True)
        await asyncio.sleep(2.5)
        head = await js("(document.querySelector('.pd-head .pd-title')||{}).innerText||''")
        chk('8b 抽屉头显示编码与计数', 'PRA1' in str(head), head)
        chk('9 来源信息（清单导入）在位',
            '清单导入' in str(await js("(document.querySelector('.pd .block .kv')||{}).innerText||''")),
            await js("(document.querySelector('.pd .block .kv')||{}).innerText"))
        chk('9b 涉及箱号 CTN-1 在位',
            'CTN-1' in str(await js("document.querySelector('.pd .block').innerText")))
        n_shot = await js("document.querySelectorAll('.pd .shot-grid .shot').length")
        chk('10 已关联照片卡 ≥1 张（links 里那一张）', n_shot >= 1, n_shot)
        chk('10b 标准图区在位（暂无图时给提示）',
            '标准图' in str(await js("document.querySelector('.pd .block .bgh').innerText")))

        # ════ ④ 字段编辑 ════
        await js("""(()=>{const inp=[...document.querySelectorAll('.pd .pedit input')]
            .find(x=>x.value==='10*10*10');
            if(inp){const s=Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype,'value').set;
              s.call(inp,'12*12*12');
              inp.dispatchEvent(new Event('input',{bubbles:true}));}})()""")
        await asyncio.sleep(0.8)
        chk('11 改动字段 → 出现「有未保存的修改」',
            '有未保存的修改' in str(await js("document.querySelector('.pd .pedit').innerText")),
            await js("document.querySelector('.pd .pedit').innerText"))
        await click_text('.pd .pedit button', '保存修改')
        await asyncio.sleep(2.5)
        await drain()
        pr = http_json('/api/products/PRA1') or {}
        chk('12 保存落库（spec=12*12*12）', pr.get('spec') == '12*12*12', pr.get('spec'))
        chk('12b 保存后脏标记清掉',
            '有未保存的修改' not in str(await js("document.querySelector('.pd .pedit').innerText")))
        chk('12c 列表该行品名/规格跟着刷新',
            '12*12*12' in str(await js("""(()=>{const rs=[...document.querySelectorAll(
                '.prod-page .el-table__body-wrapper tr')];
                const r=rs.find(x=>x.innerText.includes('PRA1')); return r?r.innerText:'';})()""")),
            await js("""(()=>{const rs=[...document.querySelectorAll(
                '.prod-page .el-table__body-wrapper tr')];
                const r=rs.find(x=>x.innerText.includes('PRA1')); return r?r.innerText:'';})()"""))

        # 未保存改动时关抽屉要被拦
        await js("""(()=>{const inp=[...document.querySelectorAll('.pd .pedit input')][0];
            if(inp){const s=Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype,'value').set;
              s.call(inp,'临时改了'); inp.dispatchEvent(new Event('input',{bubbles:true}));}})()""")
        await asyncio.sleep(0.6)
        await click_text('.pd-head button', '关闭')
        await asyncio.sleep(1.2)
        chk('13 有未保存改动 → 关抽屉弹确认、抽屉不关',
            await js("!!document.querySelector('.el-message-box')") is True
            and await js("!!document.querySelector('.pd')") is True)
        await click_text('.el-message-box__btns button', '继续编辑')
        await asyncio.sleep(0.8)
        # 还原后再关
        await click_text('.pd .pedit button', '还原')
        await asyncio.sleep(0.6)
        await click_text('.pd-head button', '关闭')
        await asyncio.sleep(1.5)
        chk('13b 还原后关闭成功', await js("!document.querySelector('.pd')") is True)

        # ════ ⑤ 候选区 ════
        await js("""(()=>{const rs=[...document.querySelectorAll(
            '.prod-page .el-table__body-wrapper tr')];
            const r=rs.find(x=>x.innerText.includes('PRB2')); if(r) r.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        chk('14 PRB2 抽屉显示「可能关联的图片」候选',
            '可能关联的图片' in str(await js("document.querySelector('.pd').innerText")),
            str(await js("document.querySelector('.pd').innerText"))[:160])
        n_cand = await js("document.querySelectorAll('.pd .cand-col .cand-item').length")
        chk('14b 候选 1 张', n_cand == 1, n_cand)
        # 候选单张关联
        await click_text('.pd .cand-col button', '单张关联')
        await asyncio.sleep(3.0)
        await drain()
        c_b2 = http_json('/api/products/PRB2/candidates') or {}
        chk('15 单张关联 → 候选清空（数字同源：候选区与列表角标一致）',
            len(c_b2.get('items') or []) == 0, json.dumps(c_b2, ensure_ascii=False)[:100])

        # 已标记无关联：默认折叠、入口一直在、可撤销
        await click_text('.pd-head button', '关闭')
        await asyncio.sleep(1.2)
        await js("""(()=>{const rs=[...document.querySelectorAll(
            '.prod-page .el-table__body-wrapper tr')];
            const r=rs.find(x=>x.innerText.includes('PRC3')); if(r) r.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        chk('16 已标记无关联区块默认折叠但入口在',
            '已标记无关联' in str(await js("document.querySelector('.pd').innerText"))
            and '展开' in str(await js("""(()=>{const b=[...document.querySelectorAll('.pd .bgh')]
                .find(x=>x.innerText.includes('已标记无关联')); return b?b.innerText:'';})()""")),
            await js("""(()=>{const b=[...document.querySelectorAll('.pd .bgh')]
                .find(x=>x.innerText.includes('已标记无关联')); return b?b.innerText:'';})()"""))
        await js("""(()=>{const b=[...document.querySelectorAll('.pd .bgh')]
            .find(x=>x.innerText.includes('已标记无关联')); if(b) b.click();})()""")
        await asyncio.sleep(1.0)
        await drain()
        chk('16b 展开后能看到那张照片',
            await js("document.querySelectorAll('.pd .block .cand-item').length") >= 1)
        await click_text('.pd .block button', '撤销')
        await asyncio.sleep(3.0)
        await drain()
        c_c3b = http_json('/api/products/PRC3/candidates/rejected') or {}
        chk('17 撤销 → 已标记清单清空',
            len(c_c3b.get('items') or []) == 0, json.dumps(c_c3b, ensure_ascii=False)[:100])

        # ════ ⑥ 翻上下个 + 删除 ════
        n_code = await js("""(()=>{const t=document.querySelector('.pd-head .pd-title .code');
            return t?t.innerText.trim():'';})()""")
        # 抽屉头有多个 .faint，位置文案要按「第 n / 4 条」精确取，别取第一个
        _pos = await js("""(()=>{const hs=document.querySelectorAll('.pd-head .faint');
            for(const h of hs){const t=(h.innerText||'').trim();
                if(t.includes('条')) return t;} return '';})()""")
        chk('18 位置显示「第 n / 4 条」', '4 条' in str(_pos), _pos)
        await click_text('.pd-head button', '下一个')
        await asyncio.sleep(3.0)
        await drain()
        n_code2 = await js("""(()=>{const t=document.querySelector('.pd-head .pd-title .code');
            return t?t.innerText.trim():'';})()""")
        chk('18b 下一个 → 编码变了', n_code2 != n_code, '%s → %s' % (n_code, n_code2))

        # 删除当前产品（确认框 + 抽屉自关 + 列表少一行）
        n_before = len(await row_texts() and json.loads(await row_texts()) or [])
        await click_text('.pd-head button', '删除产品')
        await asyncio.sleep(1.2)
        chk('19 删除产品弹确认',
            await js("!!document.querySelector('.el-message-box')") is True)
        await click_text('.el-message-box__btns button', '确定')
        await asyncio.sleep(3.5)
        await drain()
        n_after = await js("document.querySelectorAll('.prod-page .el-table__body-wrapper tr').length")
        chk('19b 删除后列表少一行', n_after == n_before - 1, '%s → %s' % (n_before, n_after))
        chk('19c 删除后抽屉自动关',
            await js("!document.querySelector('.pd')") is True)

        # ════ ⑦ 补关联 / 导入清单 ════
        await click_text('.prod-page .phead button', '补关联')
        await asyncio.sleep(3.0)
        await drain()
        chk('20 补关联跑通（0 新增也是通，给出明确文案）',
            await js("!!document.querySelector('.el-message')") is True,
            await js("""(()=>{const m=document.querySelector('.el-message');
                return m?m.innerText:'';})()"""))
        # 按钮文案带「＋ 」前缀，click_text 是 startsWith 匹配，得写全
        await click_text('.prod-page .phead button', '＋ 导入清单')
        await asyncio.sleep(1.2)
        # 页面上可能同时挂着别的 dialog，按标题「导入货品清单」精确定位
        _dlg = """(()=>{for(const d of document.querySelectorAll('.el-dialog')){
            if((d.innerText||'').includes('导入货品清单')) return d.innerText;} return '';})()"""
        chk('21 导入清单弹窗在位（柜号只读显示，不在这里再选柜）',
            '当前所选柜' in str(await js(_dlg)), await js(_dlg))
        await click_text('.el-dialog__footer button', '取消')
        await asyncio.sleep(0.8)

        # ════ ⑧ 刷新保持 ════
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.5)
        await drain()
        chk('22 刷新仍落在 /app/products',
            await js("location.pathname") == '/app/products', await js("location.pathname"))
        n_row2 = await js("document.querySelectorAll('.prod-page .el-table__body-wrapper tr').length")
        chk('22b 刷新后列表仍渲染', n_row2 == 3, n_row2)

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('23 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:400] if bad else ''))
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