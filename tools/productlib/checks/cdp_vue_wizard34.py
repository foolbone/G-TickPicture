# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 版柜作业 ③照片 / ④选图（vue3-frontend 分支）。

覆盖点：
  ③ · 五档选项卡 + 徽章（待关联只算产品图）
  ③ · 左侧树（含「待确认细分」待办维）与往返筛选
  ③ · 治理面板：待治理计数 / 多任务轮询面板在位 / 失败诊断面板可恢复
  ③ · 监装细分待确认：树上计数 + 卡片操作行（标为监装 / 选细分 / 采用建议）
  ③ · 箱号分组（与五档互斥、共用同一份筛选）
  ③ · 批量条：勾选 → 标记无效 → 退出默认列表；改判分类
  ③ · 「更多 ▾」两个低频工具能打开（清理 / 重复图端点通）
  ④ · 统计条数字与后端 stats 同源
  ④ · 自动载编码池 + 检索（/api/report/lookup）
  ④ · 采用标记：点图 → 已选 N 张 → 步骤条摘要跟着变
  ④ · 监装候选：柜况④多选 / 卡车⑦多选；「恢复自动」清键
  ⑤ · picks 三态语义（动过才带键）端到端落到报告生成
  · 全程无 JS 异常

⚠️ 隔离实例 8805 / CDP 9365。evaluate 顶层 const 跨调用残留，表达式包 IIFE。
跑法：python tools/productlib/checks/cdp_vue_wizard34.py
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

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8805'))
CDP_PORT = int(os.environ.get('PL_CDP', '9365'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vue34_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vue34_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/wizard'
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
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:300]}


def post_file(path, fields, files, timeout=600):
    b = '----pl34' + str(int(time.time()))
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
        return e.code, {'raw': e.read().decode('utf8', 'replace')[:300]}


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

# ── 清单（真 Excel）──
import openpyxl  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue34')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
xlsx = os.path.join(tmpd, '清单.xlsx')
wb = openpyxl.Workbook()
ws0 = wb.active
ws0.append(['code', 'name', 'spec', 'package_no', 'order_qty'])
for i in range(1, 4):
    ws0.append(['P34%03d' % i, '测试品%d' % i, '10*10*10', 'CTN-%d' % i, i])
wb.save(xlsx)

# ── 照片：3 监装 + 5 预检产品图 ──
from PIL import Image  # noqa: E402

files = []
N = 8
for i in range(N):
    p = os.path.join(tmpd, 'P_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (60 + i * 20, 120, 190)).save(p)
    files.append(('files', p, os.path.basename(p)))

code, c = _req('POST', '/api/containers',
               {'container_no': 'V34', 'seal_no': 'S', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)
code, r = post_file('/api/products/import', {'container_id': cid},
                    [('file', xlsx, os.path.basename(xlsx))])
chk('0b 导入清单 3 行', code == 200 and (r or {}).get('parsed') == 3,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0c 上传 8 张', code == 200 and (r or {}).get('added') == N,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
for pid in pids[:3]:
    _req('PATCH', '/api/photos/%s/usage' % pid, {'usage': '监装'})

import sqlite3  # noqa: E402

con = sqlite3.connect(os.path.join(DBHOME, 'productlib.db'))
con.execute("UPDATE photos SET govern_state='done'")
con.execute("UPDATE photos SET photo_kind='scene' WHERE photo_usage='监装'")
# 用途也要落：只改 kind 不改 usage → 树上算「未分类」，且 picks.stats 命中口径也是按预检算
con.execute("UPDATE photos SET photo_usage='预检' WHERE IFNULL(photo_usage,'')<>'监装'")
con.execute("UPDATE photos SET photo_kind='label' WHERE IFNULL(photo_usage,'')<>'监装'")
con.execute("UPDATE photos SET supervision_tag='container_side' WHERE photo_usage='监装'")
# 前三张监装照：两張给细分（container_seal / truck_head），一张不给（→ 待确认）
# 关键：待确认判定是 sup_tag_confirmed=0，光给 supervision_tag 不算「已确认」，
# 否则三张监装照会全进待办（fixture 口径必须与后端一致）。
con.execute("UPDATE photos SET supervision_tag='container_side' "
            "WHERE photo_usage='监装' AND id=?", (pids[0],))
con.execute("UPDATE photos SET supervision_tag='truck_head' "
            "WHERE photo_usage='监装' AND id=?", (pids[1],))
con.execute("UPDATE photos SET sup_tag_confirmed=1 WHERE id IN (?,?)",
            (pids[0], pids[1]))
con.execute("UPDATE photos SET supervision_tag=NULL, sup_tag_confirmed=0 "
            "WHERE photo_usage='监装' AND id=?", (pids[2],))
con.execute("UPDATE photos SET carton_no='CTN-1' WHERE id=?", (pids[3],))
con.execute("UPDATE photos SET carton_no='CTN-1' WHERE id=?", (pids[4],))
con.execute("UPDATE photos SET vision_codes=? WHERE id=?",
            (json.dumps(['P34001']), pids[3]))
con.execute("UPDATE photos SET vision_codes=? WHERE id=?",
            (json.dumps(['P34002']), pids[4]))
# ④「命中」的真口径是 links（关联），不是 vision_codes（识别线索）——
# stats.with_photo 与 report_lookup 的 found 都走 links，fixture 必须建关联。
import time as _t  # noqa: E402
for code_norm, pid in (('P34001', pids[3]), ('P34002', pids[4])):
    con.execute("INSERT OR REPLACE INTO links"
                " (code_norm, photo_id, source, confidence, created_at)"
                " VALUES (?,?,?,?,?)",
                (code_norm, pid, 'manual', 1.0,
                 _t.strftime('%Y-%m-%dT%H:%M:%S')))
con.commit()
con.close()

# 待确认细分：pids[2]（监装 + 无细分）应进待办
pend = http_json('/api/containers/%s/supervision-pending' % cid) or {}
chk('0d 待确认细分待办 = 1 张', len(pend.get('items') or []) == 1,
    json.dumps(pend, ensure_ascii=False)[:160])

# ③④ 端到端基线：待关联 = 5 张产品图 - 2 张已建关联 = 3
#（监装照不进待关联队列；vision_codes 只是识别线索，不算关联）
ls = http_json('/api/photos/linkstate?container_id=%s' % cid) or {}
chk('0e 待关联=3（只有产品图进队列，且已关联的不算）', ls.get('unlinked') == 3,
    ls.get('unlinked'))
# ④ 命中口径基线：stats.with_photo 必须等于 lookup 的命中数（同源铁律）
st0 = container_picks = ((http_json('/api/containers/%s/progress' % cid) or {})
                         .get('steps', {}).get('picks', {}).get('stats') or {})
chk('0g picks.stats 与命中同源（with_photo=2）', st0.get('with_photo') == 2,
    json.dumps(st0, ensure_ascii=False)[:160])

sup = http_json('/api/containers/%s/supervision-photos' % cid) or {}
grp = {g['tag']: len(g['items']) for g in (sup.get('groups') or [])}
chk('0f 监装候选分组（柜况/卡车都有）', grp.get('container_side') == 1 and grp.get('truck_head') == 1,
    grp)

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
        # 锚点真源 = localStorage['plCid']。测试用 API 建柜，不会顺带落盘，
        # 这里显式写一次再导航，否则深链 ?step=photos 会停在「未选柜」空态。
        await asyncio.sleep(1.0)
        await cmd('Runtime.evaluate',
                  {'expression': "localStorage.setItem('plCid', %s)"
                                 % json.dumps(str(cid))})
        await cmd('Page.navigate', {'url': URL + '?step=photos'})
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

        # ════ ③ 首屏 ════
        print('[DBG] body=', str(await js('document.body.innerText'))[:600], flush=True)
        print('[DBG] path=', await js('location.pathname+location.search'), flush=True)
        # ⚠️ 治理面板 2026-10-21 起搬进了**抽屉**（Wizard 持有 el-drawer，
        #    GovPanel 是 v-if="govOpen"）—— 不开抽屉直接查 .gov 必然是 null
        #    （断言 1/4 曾因此长期假红）。先点「照片治理」开抽屉。
        await click_text('button', '照片治理')
        await wait("!!document.querySelector('.gov')", True)
        chk('1 ③面板已渲染（治理面板 + 照片树）',
            await js("!!document.querySelector('.gov')&&document.querySelectorAll('.ptree-i').length>0") is True)
        n = await wait("document.querySelectorAll('.w-photos .shot').length", N)
        chk('2 ③网格 8 张', n == N, n)
        tabs = await wait("document.querySelectorAll('.w-photos .el-tabs__item').length", 5)
        chk('3 五档选项卡', tabs == 5, tabs)
        # 徽章与 /api/photos/linkstate 同源（不写死数字：上面建了 2 条 links）
        ls0 = http_json('/api/photos/linkstate?container_id=%s' % cid) or {}
        want_badge = str(ls0.get('unlinked'))
        badge = await wait("""(()=>{const t=[...document.querySelectorAll('.w-photos .el-tabs__item')];
            const un=t[2].innerText.replace(/\\D/g,''); return un||'';})()""", want_badge)
        chk('3b 待关联档徽章与 linkstate 同源', badge == want_badge,
            '%s vs 接口 %s' % (badge, want_badge))
        chk('4 治理面板显示待治理计数',
            '待治理' in str(await js("document.querySelector('.gov').innerText")),
            await js("document.querySelector('.gov').innerText"))
        # 关掉抽屉（点遮罩）—— 别挡住后面网格/树上的点击断言
        await js("""(()=>{const m=document.querySelector('.el-overlay');
            if(m) m.click();})()""")
        await wait("!!document.querySelector('.gov')", False)

        # 树：用途计数 + 待确认细分维度
        usage_counts = await js("""(()=>{const out={};
            const secs=document.querySelectorAll('.w-photos .ptree-sec');
            secs[0].querySelectorAll('.ptree-i').forEach(b=>{
              out[b.querySelector('.ptree-l').textContent]=
                b.querySelector('.ptree-n').textContent;});
            return JSON.stringify(out);})()""")
        chk('5 树用途计数（监装3/预检5）',
            json.loads(usage_counts or '{}') == {'监装': '3', '预检': '5'}, usage_counts)
        pend_txt = await js("""(()=>{const b=[...document.querySelectorAll('.w-photos .ptree-i')]
            .find(x=>x.querySelector('.ptree-l').textContent==='待确认细分');
            return b?b.querySelector('.ptree-n').textContent:'';})()""")
        chk('5b 树上有「待确认细分」= 1', pend_txt == '1', pend_txt)

        # 点树「监装」→ 3 张
        await js("""(()=>{const b=[...document.querySelectorAll('.w-photos .ptree-i')]
            .find(x=>x.querySelector('.ptree-l').textContent==='监装'); if(b) b.click();})()""")
        n_sup = await wait("document.querySelectorAll('.w-photos .shot').length", 3)
        chk('6 点「监装」→ 3 张', n_sup == 3, n_sup)
        # 再点取消 → 回 8
        await js("""(()=>{const b=[...document.querySelectorAll('.w-photos .ptree-i')]
            .find(x=>x.querySelector('.ptree-l').textContent==='监装'); if(b) b.click();})()""")
        n_all = await wait("document.querySelectorAll('.w-photos .shot').length", N)
        chk('7 再点取消 → 8 张', n_all == N, n_all)

        # 待确认细分视图：卡片补操作行
        await js("""(()=>{const b=[...document.querySelectorAll('.w-photos .ptree-i')]
            .find(x=>x.querySelector('.ptree-l').textContent==='待确认细分'); if(b) b.click();})()""")
        n_pend = await wait("document.querySelectorAll('.w-photos .shot').length", 1)
        chk('8 点「待确认细分」→ 只出 1 张', n_pend == 1, n_pend)
        chk('8b 该卡片带细分操作行（下拉 + 采用）',
            await js("!!document.querySelector('.w-photos .supact .el-select')"
                     "&&document.body.innerText.includes('采用')") is True)
        # 给它确认细分 → 应退出待办视图
        await js("""(()=>{const sel=document.querySelector('.w-photos .supact .el-select input');
            if(sel) sel.click();})()""")
        await asyncio.sleep(0.8)
        await js("""(()=>{const o=[...document.querySelectorAll('.el-select-dropdown__item')]
            .find(x=>x.textContent.trim().startsWith('锁门')); if(o) o.click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        gone = await wait("document.querySelectorAll('.w-photos .shot').length", 0)
        chk('9 确认细分后退出待确认视图', gone == 0, gone)
        nb = await js("""(()=>{const b=[...document.querySelectorAll('.w-photos .ptree-i')]
            .find(x=>x.querySelector('.ptree-l').textContent==='待确认细分');
            return b?b.querySelector('.ptree-n').textContent:'';})()""")
        chk('9b 树上待确认计数归零', nb == '0', nb)
        con2 = sqlite3.connect(os.path.join(DBHOME, 'productlib.db'))
        tag = con2.execute('SELECT supervision_tag FROM photos WHERE id=?',
                           (pids[2],)).fetchone()[0]
        con2.close()
        chk('9c 细分真落库（container_lock）', tag == 'container_lock', tag)
        # 回全部
        await js("""(()=>{const b=[...document.querySelectorAll('.w-photos .ptree-i')]
            .find(x=>x.querySelector('.ptree-l').textContent==='待确认细分'); if(b) b.click();})()""")
        await asyncio.sleep(2.0)

        # 箱号分组
        await click_text('.w-photos .wclbar button', '按箱号分组')
        n_g = await wait("document.querySelectorAll('.w-photos .el-collapse-item').length", 2)
        chk('10 按箱号分组 → 2 个箱号组（CTN-1 + 未标注）', n_g == 2, n_g)
        await click_text('.w-photos .wclbar button', '按箱号分组')
        n_back = await wait("document.querySelectorAll('.w-photos .shot').length", N)
        chk('11 关掉分组 → 回网格 8 张', n_back == N, n_back)

        # 批量：标记无效
        await click_text('.w-photos .wclbar button', '批量选择')
        chk('12 进入批量模式', await js("!!document.querySelector('.w-photos .selbar')") is True)
        await js("document.querySelector('.w-photos .shot').click()")
        await asyncio.sleep(0.8)
        chk('12b 勾选计数=1',
            await js("(document.querySelector('.w-photos .selbar b')||{}).textContent==='1'") is True)
        await click_text('.w-photos .selbar button', '标记无效')
        await asyncio.sleep(3.0)
        await drain()
        n_after = await js("document.querySelectorAll('.w-photos .shot').length")
        chk('13 标记无效 → 退出默认列表（8 → 7）', n_after == N - 1, n_after)
        await click_text('.w-photos .selbar button', '退出选择')
        await asyncio.sleep(1.0)

        # 批量改判分类
        await click_text('.w-photos .wclbar button', '批量选择')
        await js("document.querySelector('.w-photos .shot').click()")
        await asyncio.sleep(0.6)
        await js("""(()=>{const s=document.querySelector('.w-photos .selbar .el-select input');
            if(s) s.click();})()""")
        await asyncio.sleep(0.8)
        await js("""(()=>{const o=[...document.querySelectorAll('.el-select-dropdown__item')]
            .find(x=>x.textContent.trim()==='包装'); if(o) o.click();})()""")
        await asyncio.sleep(0.8)
        await click_text('.w-photos .selbar button', '应用改判')
        await asyncio.sleep(3.0)
        await drain()
        con3 = sqlite3.connect(os.path.join(DBHOME, 'productlib.db'))
        pk = con3.execute("SELECT COUNT(*) FROM photos WHERE photo_kind='packaging'"
                          ).fetchone()[0]
        con3.close()
        # 断言业务语义「有 1 张被改判为包装」，不写死是哪一张 ——
        # 前一步已把某张标记无效，网格顺序会变，写死 id 就是断言实现细节。
        chk('14 批量改判为「包装」落库', pk == 1, pk)
        await click_text('.w-photos .selbar button', '退出选择')
        await asyncio.sleep(1.0)

        # 更多 ▾：两个低频工具的端点都通
        await click_text('.w-photos .wclbar button', '更多')
        await asyncio.sleep(0.8)
        dups = http_json('/api/photos/dups?container_id=' + cid) or {}
        chk('15 重复图片端点通（本例无重复）',
            'groups' in dups, json.dumps(dups, ensure_ascii=False)[:100])
        ain = http_json('/api/photos/auto-invalid?container_id=' + cid) or {}
        chk('15b 清理清单/包装端点通',
            'total' in ain, json.dumps(ain, ensure_ascii=False)[:100])
        await js("document.body.click()")
        await asyncio.sleep(0.6)

        # ════ ④ 选图 ════
        await js("location.href='" + BASE + "/app/wizard?step=picks'")
        await asyncio.sleep(9.0)
        await drain()
        chk('16 ④两块选项卡',
            await js("document.querySelectorAll('.w-picks .ptab-seg .el-radio-button').length") == 2)
        chk('16b 两块面板都带可区分 class（v-show 隐藏块仍在 DOM）',
            await js("!!document.querySelector('.wpane-pre')&&"
                     "!!document.querySelector('.wpane-sup')") is True)
        stats_txt = await js("(document.querySelector('.w-picks .wpstat')||{}).innerText||''")
        chk('17 统计条显示清单编码 3 种', '3' in str(stats_txt) and '清单编码' in str(stats_txt),
            stats_txt)
        prog = http_json('/api/containers/%s/progress' % cid) or {}
        st = ((prog.get('steps') or {}).get('picks') or {}).get('stats') or {}
        chk('17b 统计条命中数与后端同源（不是 0）',
            str(st.get('with_photo')) in str(stats_txt)
            and st.get('with_photo') not in (0, None)
            and str(st.get('missing')) in str(stats_txt),
            (st.get('with_photo'), st.get('missing'), stats_txt))
        # 自动检索：两张预检照各带一个 vision_codes 编码（P34001/P34002）→ 命中 2
        n_item = await wait("document.querySelectorAll('.wpane-pre .wcai-item').length", 2, tries=40)
        chk('18 自动检索命中 2 个编码', n_item == 2, n_item)
        chk('18b 该编码有可用照片',
            await js("document.querySelectorAll('.wpane-pre .wcai-shot').length>0") is True)

        # 采用一张
        await js("document.querySelector('.wpane-pre .wcai-shot').click()")
        await asyncio.sleep(1.5)
        chk('19 点图 → 采用（出现 pick 态）',
            await js("!!document.querySelector('.wpane-pre .wcai-shot.pick')") is True)
        chk('19b 步骤条摘要变「已选 1 张」',
            '已选 1 张' in str(await js("document.querySelectorAll('.wstep')[3].innerText")),
            await js("document.querySelectorAll('.wstep')[3].innerText"))
        picks_key = await js("JSON.stringify(Object.keys(JSON.parse("
                             "localStorage.getItem('wizPicks:'+'"
                             + cid + "')||'{}')))")
        chk('19c 采用按柜落 localStorage', 'P3400' in str(picks_key),
            picks_key + ' | 全键=' + str(await js(
                "JSON.stringify(Object.keys(localStorage))")))

        # 切监装候选：柜况/卡车多选
        await js("""(()=>{const b=[...document.querySelectorAll('.w-picks .ptab-seg .el-radio-button')]
            .find(x=>x.innerText.includes('监装'));
            if(b) b.querySelector('.el-radio-button__inner').click();})()""")
        await asyncio.sleep(3.0)
        await drain()
        n_sup_item = await wait("document.querySelectorAll('.wpane-sup .wcai-item').length", 2, tries=30)
        chk('20 监装候选 2 组（柜况 + 卡车）', n_sup_item == 2, n_sup_item)
        await js("document.querySelector('.wpane-sup .wcai-shot').click()")
        await asyncio.sleep(1.5)
        chk('20b 柜况点选 → pick 态 + 步骤条计数变 2',
            await js("!!document.querySelector('.wpane-sup .wcai-shot.pick')") is True
            and '已选 2 张' in str(await js("document.querySelectorAll('.wstep')[3].innerText")),
            await js("document.querySelectorAll('.wstep')[3].innerText")
            + ' | sup=' + str(await js(
                "localStorage.getItem('wizPicksSup:" + cid + "')")))
        supkey = await js("localStorage.getItem('wizPicksSup:" + cid + "')")
        chk('20c 监装选图按柜落盘（键存在=动过）', bool(supkey), (supkey or '')[:120])

        # 恢复自动 → 键被清
        await click_text('.w-picks button', '恢复自动')
        await asyncio.sleep(1.0)
        await click_text('.el-message-box__btns button', '确定')
        await asyncio.sleep(2.0)
        chk('21 恢复自动 → sup 键清掉（⑤ 就不带 trucks/conds）',
            await js("!localStorage.getItem('wizPicksSup:" + cid + "')") is True)

        # ════ ⑤ 端到端：picks 生效 ════
        await js("location.href='" + BASE + "/app/wizard?step=report'")
        await asyncio.sleep(6.0)
        await drain()
        await click_text('.wactions button', '生成 docx')
        gen = await wait("!!document.querySelector('.gen-result')", True, tries=90)
        chk('22 带采用标记生成报告成功', gen is True,
            await js("document.querySelector('.gen-result')?.innerText"))
        chk('22b 嵌入了照片（采用生效，不是 0 张）',
            '嵌入图片 0 张' not in str(await js("document.querySelector('.gen-result').innerText")),
            await js("document.querySelector('.gen-result').innerText"))

        # ════ 刷新 ════
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.0)
        await drain()
        chk('23 刷新仍落在 /app/wizard',
            await js("location.pathname") == '/app/wizard', await js("location.pathname"))
        chk('23b 步骤条仍在', await js("document.querySelectorAll('.wstep').length") == 5)

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('24 全程无 JS 异常', not bad,
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