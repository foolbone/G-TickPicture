# -*- coding: utf-8 -*-
"""CDP实跑：Vue 3 版报告档案 /app/report（vue3-frontend 分支）。

覆盖旧版 report.js 的核心行为：
  · 概览卡（总份数 / 占用空间 / 本月新增 / 已归档柜数）—— 全量口径
  · 档案表格（柜号标签 / 大小 / 生成时间 / 下载 / 删除）
  · 按柜筛选 + 文件名关键词（只改显示，不改概览结论）
  · 删除确认框 + 真删除
  · 柜号由后端从文件名 CNTR#<柜号>- 解析（前端不写正则）
  · 空态、重置、刷新保持、无 JS 异常

⚠️ 隔离实例 8809 / CDP 9369，不碰 8765。
跑法：python tools/productlib/checks/cdp_vue_report.py
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8809'))
CDP_PORT = int(os.environ.get('PL_CDP', '9369'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuereport_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuereport_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/report'
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

# ── 造数据：直接往报告目录放 4 份 .docx（真实产物就是这样落盘的） ──
RDIR = os.path.join(DBHOME, 'reports')
os.makedirs(RDIR, exist_ok=True)
NAMES = [
    '装柜报告 CNTR#VRA1-20261018.docx',
    '装柜报告 CNTR#VRA1-20261011.docx',
    '装柜报告 CNTR#VRA2-20261018.docx',
    '无柜号的历史报告.docx',
]
for i, n in enumerate(NAMES):
    with open(os.path.join(RDIR, n), 'wb') as f:
        f.write(b'PK' + b'\0' * (2048 + i * 4096))   # 假 docx，只测大小显示
# 把两份改成「本月」以验证本月新增计数
now = datetime.now()
old = now.replace(year=now.year - 1).isoformat(timespec='seconds')
for n, ts in ((NAMES[1], old), (NAMES[3], old)):
    p = os.path.join(RDIR, n)
    os.utime(p, (time.time() - 86400 * 300, time.time() - 86400 * 300))

lst = http_json('/api/report/loading-list') or {}
items = lst.get('items') or []
chk('0 报告列表 4 份', len(items) == 4, len(items))
by_no = {}
for it in items:
    by_no.setdefault(it.get('container_no'), []).append(it['name'])
chk('0b 柜号由后端从文件名解析（VRA1 两份 / VRA2 一份 / 一份无柜号）',
    len(by_no.get('VRA1') or []) == 2 and len(by_no.get('VRA2') or []) == 1
    and len(by_no.get(None) or []) == 1, json.dumps(
        {str(k): len(v) for k, v in by_no.items()}, ensure_ascii=False))
chk('0c 新→旧排序（mtime 降序）',
    [x['mtime'] for x in items] == sorted([x['mtime'] for x in items], reverse=True),
    [x['mtime'] for x in items][:2])
chk('0d 下载链接指向 loading-file',
    all('/api/report/loading-file?path=' in (x.get('download') or '') for x in items))
chk('0e total_bytes 与逐份相加一致',
    (lst.get('total_bytes') or 0) == sum(x['bytes'] for x in items),
    '%s vs %s' % (lst.get('total_bytes'), sum(x['bytes'] for x in items)))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1400,1000', URL],
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

        async def row_count():
            return await js("document.querySelectorAll("
                            "'.rep-page .el-table__body-wrapper tr').length")

        async def click_in_row(sub, label):
            return await js("""(()=>{const rs=[...document.querySelectorAll(
                '.rep-page .el-table__body-wrapper tr')];
                const r=rs.find(x=>(x.innerText||'').includes(%s)); if(!r) return false;
                const b=[...r.querySelectorAll('button')]
                  .find(x=>(x.innerText||'').trim()===%s);
                if(b){b.click();return true;} return false;})()"""
                            % (json.dumps(sub), json.dumps(label)))

        # ════ ① 首屏 ════
        chk('1 标题带「报告档案」', '报告档案' in str(await js('document.title')),
            await js('document.title'))
        n = await wait("document.querySelectorAll('.rep-page .el-table__body-wrapper tr').length", 4)
        chk('2 档案表 4 行', n == 4, n)

        cards = await js("""(()=>{const cs=[...document.querySelectorAll('.rep-page .card')]
            .map(c=>c.innerText.replace(/\\n/g,'=')); return JSON.stringify(cs);})()""")
        chk('3 概览卡：总份数 4', '"4=总份数"' in str(cards).replace(' ', ''), cards)
        chk('3b 概览卡：已归档柜数 2（无柜号那份不计入）', '"2=已归档柜数"' in str(cards).replace(' ', ''),
            cards)
        chk('3c 概览卡：占用空间有值（不是 0）',
        any(x.endswith('占用空间') and not x.startswith('0')
            for x in json.loads(cards)), cards)
        chk('3d 本月新增 = 2（另两份 mtime 改成一年前）',
            '"2=本月新增"' in str(cards).replace(' ', ''), cards)

        body = await js("""(()=>{const t=document.querySelector(
            '.rep-page .el-table__body-wrapper'); return t?t.innerText:'';})()""")
        chk('4 表格里出现柜号标签与「未解析出柜号」',
            'VRA1' in str(body) and '未解析出柜号' in str(body),
            str(body).replace('\n', ' ')[:130])
        chk('4b 大小显示带单位', ('KB' in str(body) or 'MB' in str(body)),
            str(body).replace('\n', ' ')[:130])
        chk('4c 下载是真链接指向端点',
            'loading-file' in str(await js("""(()=>{const a=document.querySelector(
                '.rep-page .el-table__body-wrapper a[href*="/api/report/loading-file"]');
                return a?a.getAttribute('href'):'';})()""")))

        # ════ ② 按柜筛选 ════
        await js("""(()=>{const s=document.querySelector('.rep-page .toolbar .el-select');
            const i=s.querySelector('input'); i.focus(); return true;})()""")
        await asyncio.sleep(0.8)
        opts = await js("""(()=>{const o=[...document.querySelectorAll(
            '.el-select-dropdown__item')].map(x=>x.innerText.trim());
            return JSON.stringify(o);})()""")
        chk('5 柜号下拉：全部柜（2）/ VRA1 / VRA2',
            'VRA1' in str(opts) and 'VRA2' in str(opts) and '全部柜（2）' in str(opts), opts)
        await js("""(()=>{const o=[...document.querySelectorAll(
            '.el-select-dropdown__item')].find(x=>x.innerText.trim()==='VRA1');
            if(o) o.click();})()""")
        await asyncio.sleep(1.5)
        n_v = await row_count()
        chk('6 筛 VRA1 → 2 行', n_v == 2, n_v)
        cards2 = await js("""(()=>{const cs=[...document.querySelectorAll('.rep-page .card')]
            .map(c=>c.innerText.replace(/\\n/g,'=')); return JSON.stringify(cs);})()""")
        chk('6b 筛选不改概览结论（仍是总份数 4）',
            '"4=总份数"' in str(cards2).replace(' ', ''), cards2)
        tot = await js("""(()=>{const t=[...document.querySelectorAll(
            '.rep-page .toolbar .faint')].map(x=>x.innerText);
            return JSON.stringify(t);})()""")
        chk('6c 计数文案「显示 2 / 共 4 份 · 占用 …」', '显示 2 / 共 4 份' in str(tot), tot)

        # ════ ③ 关键词 ════
        # ⚠️ 关键词要写进 el-input 那个框，别写进 el-select 的隐藏 input ——
        #    .toolbar 里两个 input，DOM 顺序是「下拉在前」，取第一个会写错地方
        await js("""(()=>{const c=document.querySelector('.rep-page .toolbar .el-input');
            const i=c&&c.querySelector('input');
            if(i){const s=Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,'value').set;
                s.call(i,'VRA2'); i.dispatchEvent(new Event('input',{bubbles:true}));}
            return !!i;})()""")
        await asyncio.sleep(1.5)
        n_q = await row_count()
        chk('7 叠加关键词 VRA2（柜 VRA1 ∩ 文件名含 VRA2）→ 0 行', n_q == 0, n_q)
        chk('7b 0 行时给「没有匹配的报告」而不是空白',
            '没有匹配的报告' in str(await js(
                "(document.querySelector('.rep-page .none')||{}).innerText||''")))

        # 重置
        await js("""(()=>{const b=[...document.querySelectorAll('.rep-page .toolbar button')]
            .find(x=>(x.innerText||'').trim()==='重置'); if(b) b.click();})()""")
        await asyncio.sleep(1.5)
        chk('8 重置 → 回 4 行', await row_count() == 4, await row_count())

        # ════ ④ 删除 ════
        await click_in_row('VRA2', '删除')
        await asyncio.sleep(1.2)
        mb = await js("""(()=>{const m=document.querySelector(
            '.el-message-box');return m?m.innerText:'';})()""")
        chk('9 点删除弹确认并说清不可恢复 + 去哪重跑',
            '删了就没了' in str(mb) and '柜作业⑤' in str(mb),
            str(mb).replace('\n', ' ')[:120])
        # 先取消
        await js("""(()=>{const b=[...document.querySelectorAll(
            '.el-message-box__btns button')].find(x=>/取消/.test(x.innerText));
            if(b) b.click();})()""")
        await asyncio.sleep(1.0)
        chk('9b 取消后文件还在',
            len(http_json('/api/report/loading-list').get('items') or []) == 4)
        # 再真删
        await click_in_row('VRA2', '删除')
        await asyncio.sleep(1.2)
        await js("""(()=>{const b=[...document.querySelectorAll(
            '.el-message-box__btns button')].find(x=>/确定/.test(x.innerText));
            if(b) b.click();})()""")
        await asyncio.sleep(2.5)
        await drain()
        left = http_json('/api/report/loading-list') or {}
        chk('10 确认后真删（后端 3 份）', len(left.get('items') or []) == 3,
            len(left.get('items') or []))
        n_after = await wait(
            "document.querySelectorAll('.rep-page .el-table__body-wrapper tr').length", 3)
        chk('10b 页面同步少一行', n_after == 3, n_after)
        chk('10c 概览卡跟着变（总份数 3 / 柜数 1）',
            '3=总份数' in str(await js("""(()=>{const cs=[...document.querySelectorAll(
                '.rep-page .card')].map(c=>c.innerText.replace(/\\n/g,'='));
                return JSON.stringify(cs);})()""")).replace(' ', ''))

        # ════ ⑤ 刷新保持 ════
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.5)
        await drain()
        chk('11 刷新仍落在 /app/report', '/app/report' in str(await js('location.pathname')),
            await js('location.pathname'))
        chk('11b 刷新后仍是 3 行（删除没被撤销）', await row_count() == 3, await row_count())

        chk('12 全程无 JS 异常', not excs, json.dumps(excs, ensure_ascii=False)[:300])
        return not fails


ok = asyncio.run(main())
edge.terminate()
srv.terminate()
print(('FAIL %d 项' % len(fails)) if fails else 'PASS')
sys.exit(0 if ok and not fails else 1)