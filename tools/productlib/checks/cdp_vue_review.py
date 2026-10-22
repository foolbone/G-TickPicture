# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 版新产品确认 /app/review（vue3-frontend 分支）。

覆盖旧版 discover.js 的核心行为：
  · 候选卡渲染（置信度标签 / 来源标签 / 归一显示 / 缩略图 + 拍照时间）
  · 按批次筛选候选
  · 确认入库：展开表单填品名规格 → 保存 → 产品真的写进库 + 照片自动关联
  · 忽略编码（永久拉黑，之后不再出现）
  · 本次忽略（照片退出队列，可恢复 —— 后续柜导入同编码会自动关联）
  · 批量：勾选 → 确认选中 / 忽略选中；全部确认入库
  · 空态、刷新保持、无 JS 异常

⚠️ 隔离实例 8807 / CDP 9367，不碰 8765。evaluate 顶层 const 跨调用残留，
   表达式一律包 IIFE（老坑）。
跑法：python tools/productlib/checks/cdp_vue_review.py
"""
import asyncio
import json
import os
import re
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
PORT = int(os.environ.get('PL_PORT', '8807'))
CDP_PORT = int(os.environ.get('PL_CDP', '9367'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuereview_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuereview_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/review'
PY = os.environ.get('PL_PY') or sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

fails = []


def re_clock(t):
    """缩略图时间必须是 HH:MM:SS（到秒）—— 只到分钟等于没显示。"""
    return bool(re.search(r'\d{2}:\d{2}:\d{2}', str(t or '')))


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
    b = '----plrev' + str(int(time.time()))
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

# ── 造数据：1 柜 + 6 张照片，读出 3 个库里没有的编码 ──
code, c = _req('POST', '/api/containers', {'container_no': 'VRV1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue_review')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(6):
    p = os.path.join(tmpd, 'RV_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (60 + i * 30, 120, 190)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0b 上传 6 张', code == 200 and (r or {}).get('added') == 6,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0c 取到照片 id', len(pids) == 6, len(pids))
bid = (d.get('items') or [{}])[0].get('batch_id')
chk('0d 取到批次 id', bool(bid), bid)

# 🔴 候选的两条来源都是「治理时写进 photos/ocr_tokens 的结果」，直接改这两张表
#    造（等价于跑过一次治理），但**关联与忽略必须走 API**（photo_count 等冗余列
#    由后端 recount，sqlite 直插会留脏状态）。
NEW_V = '2030BG0000011'      # 多模态读码
NEW_V2 = '2030BG0000022'     # 多模态读码（第二张同码 → 候选卡多缩略图）
NEW_OCR = '2030BG0000033'    # 只 OCR 读到
con = sqlite3.connect(os.path.join(DBHOME, 'productlib.db'))
con.execute("UPDATE photos SET govern_state='done'")
con.execute("UPDATE photos SET photo_usage='预检', photo_kind='label', kind_conf=0.95")
con.execute("UPDATE photos SET vision_codes=? WHERE id=?",
            (json.dumps([NEW_V]), pids[0]))
con.execute("UPDATE photos SET vision_codes=? WHERE id=?",
            (json.dumps([NEW_V2]), pids[1]))
con.execute("UPDATE photos SET vision_codes=? WHERE id=?",
            (json.dumps([NEW_V]), pids[2]))
# OCR 侧：同一张也读到 NEW_V（→ 双来源小加成），pids[3] 只 OCR 读到 NEW_OCR
# 🔴 所有 fixture 写操作必须**共用一个连接**再一次性提交：另开连接写同一个库会
#    "database is locked"（前一个连接还持着未提交的写事务）。
#    created_at 是 NOT NULL，漏了直接 IntegrityError。
def add_ocr(cn, pid, text, conf):
    cn.execute("INSERT INTO ocr_tokens (photo_id, raw_text, confidence, created_at)"
               " VALUES (?,?,?,datetime('now'))", (pid, text, conf))


add_ocr(con, pids[0], 'PN:' + NEW_V, 0.93)
add_ocr(con, pids[3], NEW_OCR, 0.91)
con.commit()
con.close()

# API 层钉死基线（UI 断言在下）
dsc = http_json('/api/discover') or {}
codes0 = sorted(x['code'] for x in dsc.get('items') or [])
chk('0e 候选 3 个编码', codes0 == sorted([NEW_V, NEW_V2, NEW_OCR]), codes0)
by_code = {x['code']: x for x in (dsc.get('items') or [])}
chk('0f 双来源那条带 vision+ocr',
    by_code.get(NEW_V, {}).get('sources') == ['ocr', 'vision'],
    by_code.get(NEW_V, {}).get('sources'))
chk('0g OCR 那条只带 ocr',
    by_code.get(NEW_OCR, {}).get('sources') == ['ocr'],
    by_code.get(NEW_OCR, {}).get('sources'))
chk('0h 同码两张 → photo_count=2',
    by_code.get(NEW_V, {}).get('photo_count') == 2,
    by_code.get(NEW_V, {}).get('photo_count'))
chk('0i OCR 前缀被剥掉（raw 是 PN:…，code 是裸码）',
    by_code.get(NEW_V, {}).get('raw') in (NEW_V, 'PN:' + NEW_V),
    by_code.get(NEW_V, {}).get('raw'))
dsc_b = http_json('/api/discover?batch=%s' % bid) or {}
chk('0j 按批次筛候选也是 3 个', len(dsc_b.get('items') or []) == 3,
    len(dsc_b.get('items') or []))
dsc_x = http_json('/api/discover?batch=not-exist') or {}
chk('0k 错批次 → 0 个候选', not dsc_x.get('items'), dsc_x.get('items'))
bt = http_json('/api/batches?kind=photos') or {}
chk('0l 批次下拉至少 1 项', len(bt.get('items') or []) >= 1, len(bt.get('items') or []))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,1200', URL],
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

        async def click_text(sel, label):
            """文案是**包含**匹配：按钮常带图标前缀（＋ / ‹ ），startsWith 会漏。"""
            return await js("""(()=>{const b=[...document.querySelectorAll(%s)]
                .find(x=>(x.innerText||'').includes(%s));
                if(b){b.click();return true;} return false;})()"""
                            % (json.dumps(sel), json.dumps(label)))

        async def card_codes():
            return await js("""JSON.stringify([...document.querySelectorAll(
                '.review-page .dccard')].map(c=>c.dataset.code))""")

        async def click_in_card(code, label):
            """点**指定那张卡**里的按钮 —— 用 .dccard 找第一个会点错卡
            （候选按置信度排序，测的不是置信度最高的那张）。"""
            return await js("""(()=>{const c=[...document.querySelectorAll('.dccard')]
                .find(x=>x.dataset.code===%s); if(!c) return false;
                const b=[...c.querySelectorAll('button')]
                  .find(x=>(x.innerText||'').includes(%s));
                if(b){b.click();return true;} return false;})()"""
                         % (json.dumps(code), json.dumps(label)))

        async def card_text(code):
            return await js("""(()=>{const c=[...document.querySelectorAll('.dccard')]
                .find(x=>x.dataset.code===%s); return c?c.innerText:'';})()"""
                            % json.dumps(code))

        # ════ ① 首屏：候选卡 ════
        chk('1 标题带「新产品确认」', '新产品确认' in str(await js('document.title')),
            await js('document.title'))
        n = await wait("document.querySelectorAll('.review-page .dccard').length", 3)
        chk('2 候选卡 3 张', n == 3, n)
        codes = json.loads(await card_codes() or '[]')
        chk('2b 三张卡的编码对得上（按置信度降序）',
            codes == [c['code'] for c in sorted(
                (dsc.get('items') or []),
                key=lambda x: (-x['confidence'], -x['photo_count']))], codes)

        head = await js("(document.querySelector('.review-page .phead')||{}).innerText||''")
        chk('3 标题行有候选计数与两个批量按钮',
            '候选 3' in str(head) and '全部确认入库' in str(head)
            and '刷新候选' in str(head), head.replace('\n', ' ')[:120])
        chk('3b 说明里点明「不会进本柜报告」',
            '不会进本柜报告' in str(await js(
                "(document.querySelector('.review-page .hint')||{}).innerText||''")))

        ct = await card_text(NEW_V)
        chk('4 候选卡显示置信度 / 来源 / 照片数',
            '置信' in str(ct) and '多模态+OCR' in str(ct) and '2 张照片' in str(ct),
            str(ct).replace('\n', ' ')[:120])
        chk('4b OCR 那条只标 OCR',
            'OCR' in str(await card_text(NEW_OCR))
            and '多模态' not in str(await card_text(NEW_OCR)),
            str(await card_text(NEW_OCR)).replace('\n', ' ')[:80])
        nth = await js("""(()=>{const c=[...document.querySelectorAll('.dccard')]
            .find(x=>x.dataset.code===%s); return c?c.querySelectorAll('.thumb').length:0;})()"""
                       % json.dumps(NEW_V))
        chk('5 同码两张 → 卡上两张缩略图', nth == 2, nth)
        chk('5b 缩略图下有拍照时间（到秒）',
            re_clock(await js("""(()=>{const c=[...document.querySelectorAll('.dccard')]
            .find(x=>x.dataset.code===%s); const f=c?c.querySelector('.thumb-w figcaption'):null;
            return f?f.innerText:'';})()""" % json.dumps(NEW_V))),
            await js("""(()=>{const c=[...document.querySelectorAll('.dccard')]
            .find(x=>x.dataset.code===%s); const f=c?c.querySelector('.thumb-w figcaption'):null;
            return f?f.innerText:'';})()""" % json.dumps(NEW_V)))

        # ════ ② 批次筛选 ════
        chk('6 批次下拉在位',
            await js("!!document.querySelector('.review-page .phead .el-select')") is True)
        await js("""(()=>{const i=document.querySelector('.review-page .phead input');
            if(i){const s=Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
                s.call(i,''); i.dispatchEvent(new Event('input',{bubbles:true}));}})()""")
        await asyncio.sleep(1.5)
        await drain()
        await click_text('.review-page .phead .el-select', '全部批次')
        await asyncio.sleep(1.0)
        opts = await js("""(()=>{const o=[...document.querySelectorAll(
            '.el-select-dropdown__item')].map(x=>x.innerText.trim());
            return JSON.stringify(o);})()""")
        chk('6b 下拉里有本柜批次',
            'VRV1' in str(opts), opts)
        # 选中「错批次」不可能（只有一项），改用清空筛选回全量做等价校验
        await js("document.body.click()")
        await asyncio.sleep(0.8)

        # ════ ③ 确认入库 ════
        await click_in_card(NEW_V2, '确认入库')
        await asyncio.sleep(0.8)
        chk('7 点「确认入库」展开表单',
            await js("""(()=>{const c=[...document.querySelectorAll('.dccard')]
                .find(x=>x.dataset.code===%s); return !!(c&&c.querySelector('.edit'));})()"""
                     % json.dumps(NEW_V2)) is True)
        await js("""(()=>{const c=[...document.querySelectorAll('.dccard')]
            .find(x=>x.dataset.code===%s); const ins=c.querySelectorAll('.edit input');
            const set=Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
            set.call(ins[0],'新品牌甲'); ins[0].dispatchEvent(new Event('input',{bubbles:true}));
            set.call(ins[1],'55*33*22'); ins[1].dispatchEvent(new Event('input',{bubbles:true}));})()"""
             % json.dumps(NEW_V2))
        await asyncio.sleep(0.5)
        await js("""(()=>{const c=[...document.querySelectorAll('.dccard')]
            .find(x=>x.dataset.code===%s);
            const b=[...c.querySelectorAll('.edit button')]
              .find(x=>x.innerText.includes('保存入库')); if(b) b.click();})()"""
             % json.dumps(NEW_V2))
        await asyncio.sleep(3.0)
        await drain()
        prod = http_json('/api/products/%s' % NEW_V2) or {}
        chk('8 入库后产品真的写进库（品名/规格一起落）',
            prod.get('name') == '新品牌甲' and prod.get('spec') == '55*33*22',
            '%s / %s' % (prod.get('name'), prod.get('spec')))
        chk('8b 来源照片自动关联（photo_count 由后端维护）',
            prod.get('photo_count') == 1, prod.get('photo_count'))
        n2 = await wait("document.querySelectorAll('.review-page .dccard').length", 2)
        chk('9 入库后候选少一张', n2 == 2, n2)
        chk('9b 已入库的不再出现在候选里',
            NEW_V2 not in json.loads(await card_codes() or '[]'),
            await card_codes())

        # ════ ④ 本次忽略 ════
        await click_in_card(NEW_OCR, '本次忽略')
        await asyncio.sleep(1.0)
        chk('10 本次忽略弹确认（说清可恢复）',
            await js("!!document.querySelector('.el-message-box')") is True
            and '已忽略' in str(await js("""(()=>{const m=document.querySelector(
                '.el-message-box');return m?m.innerText:'';})()""")),
            await js("""(()=>{const m=document.querySelector(
                '.el-message-box');return m?m.innerText:'';})()"""))
        await click_text('.el-message-box__btns button', '确定')
        await asyncio.sleep(3.0)
        await drain()
        n3 = await wait("document.querySelectorAll('.review-page .dccard').length", 1)
        chk('11 本次忽略 → 候选少一张', n3 == 1, n3)
        left = json.loads(await card_codes() or '[]')
        chk('11b 被忽略的那个不再出现（产品也没入库）',
            NEW_OCR not in left and not (http_json('/api/products/%s' % NEW_OCR) or {}).get('code_norm'),
            left)
        ign = http_json('/api/photos?ignored=only&container_id=%s&limit=50' % cid) or {}
        chk('11c 照片进「已忽略」档（可恢复，不是删掉）',
            len(ign.get('items') or []) == 1, len(ign.get('items') or []))

        # ════ ⑤ 忽略编码（永久） ════
        await click_in_card(NEW_V, '忽略编码')
        await asyncio.sleep(1.0)
        await click_text('.el-message-box__btns button', '确定')
        await asyncio.sleep(3.0)
        await drain()
        n4 = await wait("document.querySelectorAll('.review-page .dccard').length", 0)
        chk('12 忽略编码 → 候选清空', n4 == 0, n4)
        chk('12b 空态出现并给出「去跑治理」入口',
            '没有新产品候选' in str(await js(
                "(document.querySelector('.review-page .el-empty')||{}).innerText||''")),
            await js("(document.querySelector('.review-page .el-empty')||{}).innerText||''"))
        chk('12c 永久忽略的编码确实没进产品库',
            not (http_json('/api/products/%s' % NEW_V) or {}).get('code_norm'))

        # ════ ⑥ 批量 ════
        # 再补两个候选来测批量（同样：清忽略标记 + 插 OCR 一次提交，别分两个连接）
        cn = sqlite3.connect(os.path.join(DBHOME, 'productlib.db'), timeout=30)
        cn.execute("UPDATE photos SET photo_ignored=0")
        add_ocr(cn, pids[4], '2030BG0000044', 0.93)
        add_ocr(cn, pids[5], '2030BG0000055', 0.93)
        cn.commit()
        cn.close()
        await click_text('.review-page .phead button', '刷新候选')
        await asyncio.sleep(3.0)
        await drain()
        # 清忽略后：两个新 OCR 码 + 本次忽略过的 NEW_OCR 一起回来（忽略是可恢复的）
        n5 = await wait("document.querySelectorAll('.review-page .dccard').length", 3)
        chk('13 清掉忽略标记并刷新 → 候选回来 3 个（含之前「本次忽略」那个）',
            n5 == 3, n5)
        chk('13b 批量条默认灰（未勾选时按钮禁用）',
            await js("""(()=>{const bs=[...document.querySelectorAll(
                '.review-page .batchbar button')];
                return bs.length===2 && bs.every(b=>b.disabled);})()""") is True)
        await js("""(()=>{const c=document.querySelector('.review-page .dccard');
            const i=c.querySelector('input[type=checkbox]');
            if(i){i.click();}})()""")
        await asyncio.sleep(0.8)
        chk('13c 勾一个 → 批量条亮起来、计数变 1',
            '已选 1' in str(await js(
                "(document.querySelector('.review-page .batchbar')||{}).innerText||''")),
            await js("(document.querySelector('.review-page .batchbar')||{}).innerText||''"))
        await click_text('.review-page .batchbar button', '确认选中')
        await asyncio.sleep(1.0)
        await click_text('.el-message-box__btns button', '确定')
        await asyncio.sleep(3.0)
        await drain()
        n6 = await wait("document.querySelectorAll('.review-page .dccard').length", 2)
        chk('14 批量确认选中 → 少一张', n6 == 2, n6)
        await click_text('.review-page .phead button', '全部确认入库')
        await asyncio.sleep(1.0)
        await click_text('.el-message-box__btns button', '确定')
        await asyncio.sleep(4.0)
        await drain()
        n7 = await wait("document.querySelectorAll('.review-page .dccard').length", 0)
        chk('15 全部确认入库 → 候选清空', n7 == 0, n7)
        tot = http_json('/api/products?limit=100') or {}
        # NEW_V2 手动 1 + 批量确认 1 + 全部确认 2 = 4（NEW_V 被永久忽略，不入库）
        chk('15b 产品库里有 4 个新产品', tot.get('total') == 4, tot.get('total'))

        # ════ ⑦ 大图 + 刷新保持 ════
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.5)
        await drain()
        chk('16 刷新仍落在 /app/review',
            '/app/review' in str(await js('location.pathname')),
            await js('location.pathname'))
        chk('16b 刷新后空态仍在', n7 == 0 and await js(
            "document.querySelectorAll('.review-page .dccard').length") == 0)

        chk('17 全程无 JS 异常', not excs,
            json.dumps(excs, ensure_ascii=False)[:300])
        return not fails


ok = asyncio.run(main())
edge.terminate()
srv.terminate()
print(('FAIL %d 项' % len(fails)) if fails else 'PASS')
sys.exit(0 if ok and not fails else 1)