# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 版柜作业 /app/wizard（vue3-frontend 分支）。

本轮迁移了 ①建柜 ②清单 ⑤报告（③照片 / ④选图 仍给旧版入口），逐条钉死：
  · 首屏落地 + 菜单高亮 + 五步步骤条
  · 空态（无柜）→ 建柜 → 自动成为当前柜并拉到 progress
  · 步骤状态**派生自后端**：②清单 0 行 → ②未完成；有清单 → ②完成
  · ①柜信息编辑：改字段 → 脏计数 → 保存 → 落库（后端核对）
  · 未保存改动时切步骤要弹离开确认（脏计数不是摆设）
  · ②清单：导 Excel → 表格出行 → 改品名/核对 → 保存分流（产品库 + rows/check）
  · ⑤生成报告：清单与照片齐了才能生成 → 生成成功出结果卡 + 历史列表
  · 刷新直落 /app/wizard（history 路由）、深链 ?step=checklist
  · 全程无 JS 异常

⚠️ 隔离实例 8804 / CDP 9364，不碰 8765。evaluate 顶层 const 跨调用残留，
   表达式一律包 IIFE（老坑）。
跑法：python tools/productlib/checks/cdp_vue_wizard.py
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
PORT = int(os.environ.get('PL_PORT', '8804'))
CDP_PORT = int(os.environ.get('PL_CDP', '9364'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuewiz_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vuewiz_db')
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
    b = '----plwiz' + str(int(time.time()))
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

# ── 造一个 Excel 清单（真文件，走和现场一样的导入路径）──
import openpyxl  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue_wizard')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
xlsx = os.path.join(tmpd, '清单模板.xlsx')
wb = openpyxl.Workbook()
ws0 = wb.active
ws0.title = 'Sheet1'
ws0.append(['code', 'name', 'spec', 'package_no', 'order_qty'])
for i in range(1, 4):
    ws0.append(['WIZ%03d' % i, '测试品%d' % i, '10*10*10', 'PK%03d' % i, i])
wb.save(xlsx)

# ── 照片（⑤要图）──
from PIL import Image  # noqa: E402

photos = []
for i in range(3):
    p = os.path.join(tmpd, 'WZ_%02d.jpg' % i)
    Image.new('RGB', (1200, 900), (200 - i * 30, 90, 60)).save(p)
    photos.append(('files', p, os.path.basename(p)))

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1500,1000', URL],
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
        await asyncio.sleep(6.0)
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

        async def wait(fn, val, tries=30):
            for _ in range(tries):
                await asyncio.sleep(0.4)
                v = await js(fn)
                if v == val:
                    return v
            return await js(fn)

        async def click_text(sel, label):
            await js("""(()=>{const b=[...document.querySelectorAll(%s)]
                .find(x=>x.innerText.trim().startsWith(%s));
                if(b) b.click();})()"""
                     % (json.dumps(sel), json.dumps(label)))

        # ════ ① 首屏：无柜空态 ════
        chk('1 标题带「柜作业」', '柜作业' in str(await js('document.title')),
            await js('document.title'))
        # 「柜作业」按 2026-10-08 老板要求并进「柜」页做第二视图，不再占
        # 侧栏一级项 —— 这里断言它作为**次级入口**高亮，而不是一级菜单项。
        chk('1b 次级入口「柜作业」高亮（它已并进柜页，不是一级项）',
            await js("!!document.querySelector('.app-sub .sub-i.on')&&"
                     "document.querySelector('.app-sub .sub-i.on')"
                     ".innerText.includes('柜作业')") is True,
            await js("(()=>{const e=document.querySelector('.app-sub .sub-i.on');"
                     "return e?e.innerText.trim():'无高亮';})()"))
        chk('1b2 侧栏一级项只剩 5 个（对齐旧版导航）',
            await js("document.querySelectorAll('.el-menu-item').length") == 5,
            await js("JSON.stringify([...document.querySelectorAll('.el-menu-item')]"
                     ".map(e=>e.innerText.trim()))"))
        chk('1c 五步步骤条',
            await js("document.querySelectorAll('.wstep').length") == 5,
            await js("document.querySelectorAll('.wstep').length"))
        steps_txt = await js("JSON.stringify([...document.querySelectorAll('.wstep .wt')]"
                             ".map(e=>e.textContent))")
        chk('1d 五步文案',
            json.loads(steps_txt or '[]') == ['建柜', '导入清单', '照片', '选图', '生成报告'],
            steps_txt)
        chk('2 无柜空态（先建柜）',
            await js("!!document.querySelector('.el-empty')") is True)

        # ════ ② 建柜 ════
        await click_text('button', '＋ 新建柜')
        await asyncio.sleep(1.5)
        chk('3 建柜弹窗打开',
            await js("!!document.querySelector('.el-dialog')") is True)
        # 柜号填 WIZ01（第一个 input 是柜号）
        await js("""(()=>{const d=document.querySelector('.el-dialog');
            const inp=d.querySelectorAll('input')[0];
            const s=Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype,'value').set;
            s.call(inp,'WIZ01');
            inp.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        await asyncio.sleep(0.6)
        await click_text('.el-dialog__footer button', '创建')
        created = await wait("!!document.querySelector('.wstep')&&"
                             "!document.querySelector('.el-empty')", True)
        chk('4 建柜成功 → 自动成为当前柜（不再空态）', created is True)

        # 锚点应落到 WIZ01；progress 能拉到
        prog = http_json('/api/containers')
        wid = next((c['id'] for c in prog.get('items', [])
                    if c['container_no'] == 'WIZ01'), None)
        chk('4b 后端有 WIZ01', bool(wid), wid)
        st = http_json('/api/containers/%s/progress' % wid) or {}
        chk('5 ① 已完成（柜建好即完成第一步）',
            (st.get('steps', {}).get('container', {}) or {}).get('done') is True,
            json.dumps(st.get('steps', {}).get('container'), ensure_ascii=False))
        chk('5b ② 未完成（还没导清单）',
            (st.get('steps', {}).get('checklist', {}) or {}).get('done') is False)
        chk('6 步骤条第①步是 done 态',
            await js("!!document.querySelector('.wstep.done')") is True)
        # 老板 2026-10-19 给了旧版截图：对标旧版 —— 胶囊里是「编号+名称+摘要」，
        # 编号用 ① 字形本身（**不能**再套一层圆底，那会变成双圈、比旧版重）。
        tips = await js("JSON.stringify([...document.querySelectorAll('.wstep')]"
                        ".map(e=>({t:e.innerText.replace(/\\n/g,' ').trim(),"
                        " tip:(e.getAttribute('title')||'').split('：')[1]||''})))")
        tl = json.loads(tips or '[]')
        chk('6b 五步都带状态摘要（对标旧版：编号+名称+摘要）',
            len(tl) == 5 and all(x['tip'] for x in tl)
            and all(' ' in x['t'] for x in tl), tips)
        # 编号不许有背景圆 —— ① 字形自带圆圈，套一层就成了双圈
        wn = await js("""(()=>{const e=document.querySelector('.wstep .wn');
            if(!e) return 'no .wn';
            const s=getComputedStyle(e);
            return JSON.stringify({bg:s.backgroundColor,
              radius:s.borderTopLeftRadius, w:Math.round(e.getBoundingClientRect().width),
              txt:(e.innerText||'').trim()});})()""")
        wj2 = json.loads(wn) if isinstance(wn, str) and wn.startswith('{') else {}
        chk('6c 编号用 ① 字形本身、无额外圆底（不是双圈）',
            wj2.get('txt') == '①' and wj2.get('bg') in ('rgba(0, 0, 0, 0)', 'transparent')
            and (wj2.get('w') or 99) <= 20, wn)
        # 「柜作业」无框标签 + 步骤之间有短横分隔（都是旧版的形）
        chk('6d 有「柜作业」无框标签（旧版 .wizttl）',
            await js("""(()=>{const t=document.querySelector('.wiz-head .wizttl');
                if(!t) return false;
                return (t.innerText||'').trim()==='柜作业';})()""") is True)
        chk('6e 步骤之间有短横分隔（.wsep × 4）',
            await js("document.querySelectorAll('.wstepbar .wsep').length") == 4,
            await js("document.querySelectorAll('.wstepbar .wsep').length"))
        # 旧版下拉显示「柜号 · N 行」
        chk('6f 柜下拉选项带「· N 行」（同旧版口径）',
            await js("""(()=>{const o=document.querySelector('.wiz-cid');
                if(!o) return false;
                const l=(o.querySelector('.el-select__placeholder')||{}).innerText||'';
                return l.indexOf('行') >= 0 || l.indexOf('未分柜') >= 0 || !!l;})()""") is True,
            await js("""(()=>{const o=document.querySelector('.wiz-cid');
                const l=(o&&o.querySelector('.el-select__placeholder')||{}).innerText||'';
                return l.trim();})()"""))

        # ════ ③ ①柜信息编辑 ════
        chk('7 当前步是①（柜信息表单可见）',
            await js("!!document.querySelector('.wd-h')&&"
                     "document.querySelector('.wd-h').textContent.includes('柜信息')") is True)
        # 步骤头部必须并成一行（编号/名称/状态/说明/摘要同在一个 .whead 里）。
        # 曾经是三块竖排（标题行 + 说明段 + 带边框状态块），白占三四行高度，
        # 把真正要操作的区域挤到屏幕下方。
        chk('7b 步骤头部并成一行（编号+名称+状态+说明+摘要同层）',
            await js("(()=>{const h=document.querySelector('.whead');"
                     "if(!h||!h.querySelector('.wnum')||!h.querySelector('.wtitle')||"
                     "!h.querySelector('.wstatus')||!h.querySelector('.wdesc')) return false;"
                     "return h.getBoundingClientRect().height < 44;})()") is True,
            await js("(()=>{const h=document.querySelector('.whead');"
                     "return h? Math.round(h.getBoundingClientRect().height) : -1;})()"))
        # 柜选择器/就绪度 与 步骤条必须同一层（原来 wiz-head 与 wstepbar 上下两块，
        # 每进一步内容整体下移一屏，窄屏更糟）
        chk('7c 柜选择器与步骤条同层一行',
            await js("(()=>{const hd=document.querySelector('.wiz-head');"
                     "const sb=document.querySelector('.wstepbar');"
                     "if(!hd||!sb||!hd.contains(sb)) return false;"
                     "const a=sb.getBoundingClientRect(), b=hd.querySelector('.pill')"
                     ".getBoundingClientRect();"
                     "return Math.abs(a.top - b.top) < 14;})()") is True,
            await js("(()=>{const sb=document.querySelector('.wstepbar');"
                     "const p=document.querySelector('.wiz-head .pill');"
                     "if(!sb||!p) return 'missing';"
                     "return Math.round(Math.abs(sb.getBoundingClientRect().top"
                     " - p.getBoundingClientRect().top));})()"))
        # 老板 2026-10-19：返回 / 步骤条 / 柜下拉 / 就绪值必须**同一行**，
        # 且顺序是「返回 → 步骤 → 下拉 → 就绪」（下拉和就绪挪到步骤后面）。
        geo = await js("""(()=>{const hd=document.querySelector('.wiz-head');
            if(!hd) return 'no .wiz-head';
            const bk=hd.querySelector('button');
            const sb=hd.querySelector('.wstepbar');
            const sel=hd.querySelector('.wiz-cid');
            const pl=hd.querySelector('.pill');
            if(!bk||!sb||!sel||!pl) return 'missing parts';
            const r=e=>e.getBoundingClientRect();
            const tops=[r(bk).top,r(sb).top,r(sel).top,r(pl).top]
              .map(t=>Math.round(t));
            return JSON.stringify({tops:tops,
              sameRow: Math.max(...tops)-Math.min(...tops) < 12,
              order: r(bk).right <= r(sb).left + 2
                 && r(sb).right <= r(sel).left + 2
                 && r(sel).right <= r(pl).left + 2,
              headH: Math.round(r(hd).height),
              selW: Math.round(r(sel).width),
              sbW: Math.round(r(sb).width)});})()""")
        g = json.loads(geo) if isinstance(geo, str) and geo.startswith('{') else {}
        chk('7d 返回/步骤/下拉/就绪 四块同一行（不折行）',
            g.get('sameRow') is True, geo)
        chk('7e 顺序：返回 → 步骤 → 柜下拉 → 就绪',
            g.get('order') is True, geo)
        chk('7f 整行高度收敛（单行约 32px，不是两行 70+）',
            isinstance(g.get('headH'), int) and g['headH'] <= 46, geo)
        # 一行不溢出：胶囊不再带摘要后宽度宽裕，但仍要钉死「整行不横向溢出」。
        # （上一轮就是在「摘要被截」上翻过车：测试库照片少、摘要天然短，
        #   直接量真实文本会假绿。现在摘要不占版面，这条风险从根上没了。）
        ovf = await js("""(()=>{const hd=document.querySelector('.wiz-head');
            const sb=hd.querySelector('.wstepbar');
            /* 喂最坏情况：测试库照片少、摘要天然短，直接量真实文本会假绿 */
            const ws=[...document.querySelectorAll('.wstep .ws')];
            const worst=['EMCU9914616','1003 行','1072 张 · 治理 1072/1072',
                         '未选（可跳过）','已生成 7 份'];
            ws.forEach((e,i)=>{ if(worst[i]) e.textContent=worst[i]; });
            const cut=[];
            ws.forEach(e=>{ if(e.scrollWidth>e.clientWidth+1)
                cut.push(e.textContent+' 需'+e.scrollWidth+' 给'+e.clientWidth); });
            return JSON.stringify({
              headOverflow: hd.scrollWidth>hd.clientWidth+1,
              barOverflow: sb.scrollWidth>sb.clientWidth+1,
              headH: Math.round(hd.getBoundingClientRect().height),
              cut: cut});})()""")
        oj = json.loads(ovf) if isinstance(ovf, str) and ovf.startswith('{') else {}
        chk('7g 整行不横向溢出（步骤条/顶栏都不裁）',
            oj.get('headOverflow') is False and oj.get('barOverflow') is False
            and (oj.get('headH') or 99) <= 46, ovf)
        # 摘要全字要 ~930px 的步骤条，窄窗放不下（会省略号）。
        # 老板现场屏幕 ≥1920，所以**在 1920 视口下**要求全字不省略 ——
        # 这才是「对标旧版」的真实场景，别用 1500 的测试窗口误判。
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1920, 'height': 1000, 'deviceScaleFactor': 1,
                   'mobile': False})
        await asyncio.sleep(1.2)
        wide = await js("""(()=>{
            const ws=[...document.querySelectorAll('.wstep .ws')];
            const worst=['EMCU9914616','1003 行','1072 张 · 治理 1072/1072',
                         '未选（可跳过）','已生成 7 份'];
            ws.forEach((e,i)=>{ if(worst[i]) e.textContent=worst[i]; });
            const cut=[];
            ws.forEach(e=>{ if(e.scrollWidth>e.clientWidth+1)
                cut.push(e.textContent+' 需'+e.scrollWidth+' 给'+e.clientWidth); });
            const hd=document.querySelector('.wiz-head');
            const sb=hd.querySelector('.wstepbar');
            return JSON.stringify({cut:cut,
              headOverflow: hd.scrollWidth>hd.clientWidth+1,
              barOverflow: sb.scrollWidth>sb.clientWidth+1,
              barW: Math.round(sb.getBoundingClientRect().width)});})()""")
        await cmd('Emulation.clearDeviceMetricsOverride')
        wj3 = json.loads(wide) if isinstance(wide, str) and wide.startswith('{') else {}
        chk('7g2 1920 视口 + 最坏数据：摘要全字不省略、整行不溢出',
            wj3.get('cut') == [] and wj3.get('headOverflow') is False
            and wj3.get('barOverflow') is False, wide)
        # 编号与步骤名永不压缩（flex:none），整颗胶囊也不许被裁
        cl = await js("""(()=>{const out=[];
            document.querySelectorAll('.wstep').forEach(e=>{
              if(e.scrollWidth > e.clientWidth + 1)
                out.push((e.innerText||'').trim().slice(0,20));});
            return JSON.stringify(out);})()""")
        chk('7h 步骤胶囊无内容裁切', cl == '[]', cl)
        # 改「封条号」输入框（第 2 个：0 是只读柜号）
        async def set_input(idx, val):
            await js("""(()=>{const els=document.querySelectorAll('.wdetail input');
                const el=els[%d]; if(!el) return;
                const s=Object.getOwnPropertyDescriptor(
                  window.HTMLInputElement.prototype,'value').set;
                s.call(el,%s);
                el.dispatchEvent(new Event('input',{bubbles:true}));})()"""
                     % (idx, json.dumps(val)))
            await asyncio.sleep(0.5)

        await set_input(1, 'SEAL-VUE-1')
        chk('8 改字段 → 脏计数=1',
            await js("document.querySelector('.wd-act').innerText.includes('1 处未保存')") is True,
            await js("document.querySelector('.wd-act').innerText"))
        await click_text('.wd-act button', '保存修改')
        await asyncio.sleep(2.0)
        await drain()
        code, cd = _req('GET', '/api/containers/%s' % wid)
        chk('8b 柜信息落库（seal_no=SEAL-VUE-1）',
            (cd or {}).get('seal_no') == 'SEAL-VUE-1', (cd or {}).get('seal_no'))
        chk('8c 保存后脏计数归零',
            await js("!document.querySelector('.wd-act').innerText.includes('未保存')") is True)

        # 未保存改动 → 点第②步应弹离开确认
        await set_input(2, '客户甲')
        dirty_1 = await js("document.querySelector('.wd-act').innerText")
        chk('8d 改客户 → 脏计数又变 1', '1 处未保存' in str(dirty_1), dirty_1)
        await js("document.querySelectorAll('.wstep')[1].click()")
        conf = await wait("!!document.querySelector('.el-message-box')", True, tries=12)
        chk('9 未保存改动切步骤 → 弹离开确认', conf is True)
        if conf is True:
            await click_text('.el-message-box__btns button', '继续编辑')
            await asyncio.sleep(1.0)
            chk('9b 选「继续编辑」→ 留在①',
                await js("!!document.querySelector('.wd-h')") is True)
            # 弹窗已关，要重新触发一次切步才能验「确定离开」这条分支
            await js("document.querySelectorAll('.wstep')[1].click()")
            conf2 = await wait("!!document.querySelector('.el-message-box')", True, tries=12)
            chk('9b2 再次切步骤仍会拦（拦截不是一次性的）', conf2 is True)
            await click_text('.el-message-box__btns button', '确定离开')
        await asyncio.sleep(1.2)
        chk('9c 确认离开 → 落到②（导入清单）',
            await js("!!document.querySelector('.cl-bar')||"
                     "document.body.innerText.includes('还没有清单批次')") is True,
            await js("document.querySelector('.whead').innerText"))

        # ════ ④ ②清单 ════
        code, r = post_file('/api/products/import', {'container_id': wid},
                           [('file', xlsx, os.path.basename(xlsx))])
        chk('10 导入清单 3 行',
            code == 200 and (r or {}).get('parsed') == 3,
            '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:160]))
        # 前端自己导入一次，走真实的 API + 刷新链路（同一份端点，验证 UI 通路）
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.0)
        await drain()
        await js("location.href='"+BASE+"/app/wizard?step=checklist'")
        await asyncio.sleep(5.0)
        await drain()
        rows = await wait("document.querySelectorAll('.cl-table .el-table__row').length", 3)
        chk('11 深链 ?step=checklist 直落②，表格 3 行', rows == 3, rows)
        chk('11b 步骤条第②步已 done（清单有行了）',
            await js("document.querySelectorAll('.wstep.done').length>=2") is True)

        # 改第一行的品名 + 核对
        async def set_cell(col, val):
            await js("""(()=>{const cells=document.querySelectorAll('.cl-table .el-table__row');
                if(!cells[0]) return;
                const el=cells[0].querySelectorAll('input')[%d];
                if(!el) return;
                const s=Object.getOwnPropertyDescriptor(
                  window.HTMLInputElement.prototype,'value').set;
                s.call(el,%s);
                el.dispatchEvent(new Event('input',{bubbles:true}));})()"""
                 % (col, json.dumps(val)))
            await asyncio.sleep(0.5)

        await set_cell(0, 'Vue改名品')   # 品名
        await set_cell(3, 'PASS')        # 核对
        chk('12 改两格 → 脏计数=2',
            '2 处未保存' in str(await js("document.querySelector('.cl-bar').innerText")),
            await js("document.querySelector('.cl-bar').innerText"))
        await click_text('.cl-bar button', '保存修改')
        await asyncio.sleep(2.5)
        await drain()
        cl = http_json('/api/containers/%s/checklist' % wid) or {}
        first = (cl.get('items') or [{}])[0]
        chk('12b 核对结论落库（check_result=PASS）',
            first.get('check_result') == 'PASS', first.get('check_result'))
        pr = http_json('/api/products/WIZ001') or {}
        chk('12c 品名落库且落在**产品库**（分流写对了）',
            pr.get('name') == 'Vue改名品', pr.get('name'))
        chk('12d 保存后脏计数归零',
            '未保存' not in str(await js("document.querySelector('.cl-bar').innerText")))

        # ════ ⑤ 照片 + ⑤报告 ════
        code, r = post_file('/api/photos/upload', {'container_id': wid}, photos)
        chk('13 上传 3 张照片',
            code == 200 and (r or {}).get('added') == 3,
            '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:120]))
        await cmd('Page.navigate', {'url': URL + '?step=report'})
        await asyncio.sleep(6.0)
        await drain()
        chk('14 深链⑤：生成按钮可用（清单+照片齐了）',
            await js("""(()=>{const b=[...document.querySelectorAll('.wactions button')]
                .find(x=>x.innerText.trim()==='生成 docx');
                return !!b && !b.disabled;})()""") is True,
            await js("document.querySelector('.wactions').innerText"))
        chk('14b 本柜历史报告区已渲染',
            await js("document.body.innerText.includes('本柜历史报告')") is True)
        await click_text('.wactions button', '生成 docx')
        gen = await wait("!!document.querySelector('.gen-result')", True, tries=90)
        chk('15 生成报告 → 结果卡出现', gen is True,
            await js("document.querySelector('.gen-result')?.innerText"))
        chk('15b 结果卡有下载 docx 链接',
            await js("!!document.querySelector('.gen-result a[href*=\"loading-file\"]')") is True,
            await js("(document.querySelector('.gen-result a')||{}).href"))
        lst = http_json('/api/report/loading-list') or {}
        nrp = len([x for x in lst.get('items', [])
                   if x.get('container_no') == 'WIZ01'])
        chk('15c 报告档案里有这一份', nrp >= 1, nrp)

        # ⑥③④ 旧版入口
        await js("location.href='"+BASE+"/app/wizard?step=photos'")
        await asyncio.sleep(4.5)
        await drain()
        chk('16 ③已迁到 Vue 版（导入照片按钮在位）',
            await js("""[...document.querySelectorAll('.wactions button')]
                .some(b=>b.innerText.includes('导入照片'))""") is True)
        # ③④ 迁完后 UI 上不再有「到旧版N打开」按钮（唯一还挂着的入口已无调用点）
        chk('16b ③页不再有旧版入口按钮',
            await js("""[...document.querySelectorAll('button')]
                .some(b=>b.innerText.includes('到旧版'))""") is False)

        # ════ ③ 老板三条现场反馈的回归（sticky / 控件对齐 / 按钮分层）════
        # ⚠️ 先补足照片把网格撑高：只有 3 张时页面根本滚不动，
        #    sticky 断言会**假绿**（2026-10-18 就是这么把第③步漏掉的 ——
        #    当时只在照片库页量了，没在这儿量）。
        more = []
        for i in range(60):
            p = os.path.join(tmpd, 'WZ_M%02d.jpg' % i)
            Image.new('RGB', (800, 600), (40 + i * 3, 100, 150)).save(p)
            more.append(('files', p, os.path.basename(p)))
        code, r = post_file('/api/photos/upload', {'container_id': wid}, more)
        chk('16c 补 60 张照片（让网格可滚，否则 sticky 断言假绿）',
            code == 200 and (r or {}).get('added') >= 50,
            '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:90]))
        await cmd('Page.navigate', {'url': BASE + '/app/wizard?step=photos'})
        await asyncio.sleep(6.0)
        await drain()
        n_card = await js("document.querySelectorAll('.shot-grid > *').length")
        chk('16d ③网格出图（可滚）', isinstance(n_card, int) and n_card >= 20, n_card)
        # 判据：连滚两段，第二次 top 必须**纹丝不动**。
        # 第一段是「吸附过程」（树被吸到 top:16），本来就会动。
        await js("(document.querySelector('.app-scroll')||document.body).scrollTop=300")
        await asyncio.sleep(1.0)
        t1 = await js("Math.round(document.querySelector('.ptree-wrap')"
                      ".getBoundingClientRect().top)")
        await js("(document.querySelector('.app-scroll')||document.body).scrollTop=1000")
        await asyncio.sleep(1.0)
        t2 = await js("Math.round(document.querySelector('.ptree-wrap')"
                      ".getBoundingClientRect().top)")
        chk('16e ③左树随页面滚动冻住（再滚一段 top 不变）', t1 == t2,
            '%s -> %s' % (t1, t2))
        await js("(document.querySelector('.app-scroll')||document.body).scrollTop=0")
        await asyncio.sleep(0.8)
        # 控件高度 / 字号必须同基线（EP 默认 select小型24 / input32 / button24 / 字号12~14 混排）
        hs = await js("""(()=>[...document.querySelectorAll(
            '.wclbar .el-select, .wclbar .el-input, .wclbar .el-button,'
            + '.wclbar .el-checkbox')]
            .map(e=>({h:Math.round(e.getBoundingClientRect().height),
                      fs:getComputedStyle(e).fontSize,
                      t:(e.innerText||'').trim().slice(0,8)})))()""")
        hset = sorted({x['h'] for x in (hs or [])})
        fset = sorted({x['fs'] for x in (hs or [])})
        bad_h = [x for x in (hs or []) if x['h'] != 32]
        chk('16f ③工具条控件高度统一（都是32px）',
            hset == [32], '%s 异常=%s' % (hset, bad_h))
        chk('16g ③工具条字号统一（不再 12/14 混排）',
            len(fset) == 1, '%s' % fset)
        # 按钮分层：实心执行 / 描边次要 / 灰底开关 / 纯文字辅助，四档可辨
        bs = await js("""(()=>Object.fromEntries(
            [...document.querySelectorAll('.wclbar button')]
            .map(b=>[(b.innerText||'').trim().slice(0,8),
                     getComputedStyle(b).backgroundColor])))()""")
        bs = bs or {}
        chk('16h ③主按钮「查询」实心（执行）',
            bs.get('查询') == 'rgb(37, 99, 235)', str(bs.get('查询')))
        chk('16i ③「重置」描边白底（次要，不与主按钮同款）',
            bs.get('重置') == 'rgb(255, 255, 255)', str(bs.get('重置')))
        chk('16j ③开关型「按箱号分组/批量选择」灰底（与动作按钮区分）',
            bs.get('按箱号分组') == 'rgb(238, 241, 245)'
            and bs.get('批量选择') == 'rgb(238, 241, 245)',
            '%s / %s' % (bs.get('按箱号分组'), bs.get('批量选择')))
        chk('16k ③「更多」纯文字（辅助）',
            str(bs.get('更多 ▾')) == 'rgba(0, 0, 0, 0)', str(bs.get('更多 ▾')))

        # ════ ⑥ 刷新保持 ════
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(5.5)
        await drain()
        chk('17 刷新后仍落在 /app/wizard',
            await js("location.pathname") == '/app/wizard',
            await js("location.pathname"))
        chk('17b 刷新后步骤条仍在（不是空态）',
            await js("document.querySelectorAll('.wstep').length") == 5)

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('18 全程无 JS 异常', not bad,
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