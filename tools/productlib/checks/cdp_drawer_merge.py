# -*- coding: utf-8 -*-
"""CDP 实跑：照片详情抽屉「同组连拍 · 可能的全景图」合并块（2026-10-18）。

老板原话：「同组连拍照片可以合并至上方的『可能的全景图』，保留一个就可以，
规则进行融合，并显示文件名和文件时间或拍摄时间。并在关联后，显示同产品
编码的其他图片，做辅助判断参考。」

锁死五件事（全部读真实 DOM，不看代码）：
  1 「识别细节」里**不再有**独立的「同组连拍照片」区块（真合并，不是换个位置）；
  2 合并块存在，且同时出现两种来源标签（同组连拍 / 可能的全景图）；
  3 每条候选都显示**文件名 + 时间到秒**；
  4 勾选后「关联选中」按钮解禁并显示条数（批量关联入口没在合并中丢掉）；
  5 关联后出现「同产品编码（…）的其他照片」参考块。
全程无 JS 异常。

用法：PL_PORT=8792 python -m tools.productlib.checks.cdp_drawer_merge
（必须打隔离端口 —— 打 8765 会打到老板正在用的旧进程，假绿）
"""
import asyncio, json, os, re, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('PL_PORT', '8765'))
URL = 'http://127.0.0.1:%d/' % PORT
DBPORT = 9352
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_drawer_merge')

fails = []
SEC = re.compile(r'\b([01]\d|2[0-3]):[0-5]\d:[0-5]\d\b')


def log(*a):
    print(*a, flush=True)


def chk(name, cond, info=''):
    log(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


def http_json(url, retries=40, timeout=3, port=None):
    """⚠️ port 不传就用**应用端口**（PL_PORT）；只有 /json/* 这种 CDP 端点
    才显式传 DBPORT。曾经把 /api/stats 也丢给 DBPORT，40 次重试 ×3s
    超时 = 脚本静默卡 3 分钟才报错。"""
    port = DBPORT if (port is None and False) else (port if port is not None else PORT)
    if url.startswith('/json'):
        port = DBPORT
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(retries):
        try:
            with op.open('http://127.0.0.1:%d%s' % (port, url), timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox', '--no-proxy-server',
     '--remote-debugging-port=%d' % DBPORT, '--user-data-dir=' + TMP,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    # 挑一个「有同组照片且已关联产品」的照片 —— 合并块两种来源才都会出现
    pid = None
    for _ in range(40):
        st = http_json('/api/stats')
        if st:
            break
        time.sleep(0.5)
    if not st:
        print('[FAIL] 服务未就绪')
        return False

    import sqlite3
    from tools.productlib import paths
    db = sqlite3.connect(paths.db_path())
    db.row_factory = sqlite3.Row
    # 优先挑「组超过 8 张」的 —— 「展开整组」出口只在组被截断时出现。
    # 同时要求：产品缺全景（pano 引擎才出声 → 「可能的全景图」标签存在）、
    # 编码有其他照片（siblings 参考块才出现）—— 否则 2/5 号断言假红。
    big_conds = (
        ' AND NOT EXISTS (SELECT 1 FROM links l2 JOIN photos p2 ON p2.id=l2.photo_id'
        '   WHERE l2.code_norm IN (SELECT code_norm FROM links WHERE photo_id=p.id)'
        '   AND p2.photo_kind IN (\'product\',\'packaging\')'
        '   AND IFNULL(p2.is_dup,0)=0)'
        ' AND EXISTS (SELECT 1 FROM links l3 JOIN photos p3 ON p3.id=l3.photo_id'
        '   WHERE l3.code_norm IN (SELECT code_norm FROM links WHERE photo_id=p.id)'
        '   AND p3.id!=p.id AND IFNULL(p3.is_dup,0)=0)')
    r = db.execute(
        'SELECT p.id FROM photos p JOIN links l ON l.photo_id=p.id '
        'WHERE p.group_idx IS NOT NULL AND IFNULL(p.is_dup,0)=0 '
        'AND IFNULL(p.is_invalid,0)=0 AND (SELECT COUNT(*) FROM photos q '
        '  WHERE q.batch_id=p.batch_id AND q.group_idx=p.group_idx '
        '  AND IFNULL(q.is_dup,0)=0 AND IFNULL(q.is_invalid,0)=0) > 9 '
        + big_conds +
        ' ORDER BY RANDOM() LIMIT 1').fetchone()
    if not r:
        r = db.execute(
            'SELECT p.id FROM photos p JOIN links l ON l.photo_id=p.id '
            'WHERE p.group_idx IS NOT NULL AND IFNULL(p.is_dup,0)=0 '
            'AND IFNULL(p.is_invalid,0)=0' + big_conds +
            ' ORDER BY RANDOM() LIMIT 1').fetchone()
    if not r:
        print('[SKIP] 库里没有「有同组且已关联」的照片')
        return True
    pid = r['id']
    db.close()
    # 2026-10-19 ±5min 时间窗生效后，pano 来源候选会被过滤掉 —— 2 号断言
    # 「可能的全景图」标签需要**时间窗内真有邻居**的照片。抽样后先调接口
    # 确认，没有 pano 来源就换一张（最多试 10 张）。
    import urllib.request as _uq
    _op = _uq.build_opener(_uq.ProxyHandler({}))
    for _try in range(10):
        try:
            _d = json.load(_op.open(
                'http://127.0.0.1:%d/api/photos/%s/panoramas' % (PORT, pid),
                timeout=10))
            if any(x.get('source') == 'pano' for x in _d.get('items', [])):
                break
        except Exception:  # noqa: BLE001
            pass
        db = sqlite3.connect(paths.db_path())
        db.row_factory = sqlite3.Row
        r = db.execute(
            'SELECT p.id FROM photos p JOIN links l ON l.photo_id=p.id '
            'WHERE p.group_idx IS NOT NULL AND IFNULL(p.is_dup,0)=0 '
            'AND IFNULL(p.is_invalid,0)=0' + big_conds +
            ' ORDER BY RANDOM() LIMIT 1').fetchone()
        db.close()
        if not r:
            break
        pid = r['id']
    print('  目标照片：%s' % pid)

    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

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
        await asyncio.sleep(5)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        async def wait(sel, n=1, tries=25):
            for _ in range(tries):
                await asyncio.sleep(1.0)
                await drain()
                c = await js("document.querySelectorAll('%s').length" % sel)
                if (c or 0) >= n:
                    return c
            return 0

        # 直接开抽屉。⚠️ 必须动态 import() —— window.openDrawer 不存在，
        #    直接调会一片假绿（cdp_sup_tag 记过这个坑）。
        opened = await js("(async()=>{const m=await import('/static/js/drawer.js');"
                          "m.setDrawerList([%s]); await m.openDrawer(%s);"
                          "return typeof m.openDrawer;})()"
                          % (json.dumps(pid), json.dumps(pid)))
        chk('0 drawer.js 模块可 import 且导出 openDrawer', bool(opened), opened)
        await wait('#drawer.on #dwPanoSec', 1)
        await asyncio.sleep(2.5)
        await drain()

        # ① 合并：识别细节里不再有独立同组块
        old = await js("(()=>{const e=document.querySelector('#drawer .dw-more');"
                       "return e? e.innerText:'';})()")
        chk('1 「识别细节」里不再有独立的同组连拍区块',
            '同组连拍照片' not in (old or ''), (old or '')[:60].replace('\n', ' '))

        # ② 合并块存在 + 两种来源标签
        n_item = await js("document.querySelectorAll('#dwPano .pano-item').length")
        chk('2 合并块渲染出候选', (n_item or 0) > 0, '%s 条' % n_item)
        tags = await js("(()=>[...document.querySelectorAll('#dwPano .pano-info .tag')]"
                        ".map(e=>e.innerText.trim()))()")
        chk('2 同来源标签：同组连拍', '同组连拍' in (tags or []), (tags or [])[:6])
        chk('2 另一来源标签：可能的全景图',
            any('可能的全景图' in t for t in (tags or [])), (tags or [])[:6])

        # 2026-10-18 老板反馈「图片太小文件名时间看不清」后拆两行：
        #   .pano-file = 文件名（最多两行换行），.pano-sub = 时间到秒
        files = await js("(()=>[...document.querySelectorAll('#dwPano .pano-file')]"
                         ".map(e=>e.innerText.trim()))()")
        subs = await js("(()=>[...document.querySelectorAll('#dwPano .pano-sub')]"
                        ".map(e=>e.innerText.trim()))()")
        exts = ('.jpg', '.png', '.jpeg', '.heic', '.webp')
        chk('3 每条候选都显示文件名（独立行，可两行换行）',
            bool(files) and len(files) == (n_item or 0)
            and all(any(e in f.lower() for e in exts) for f in files), (files or [])[:3])
        chk('3 每条候选时间到秒（独立行）',
            bool(subs) and len(subs) == (n_item or 0)
            and all(SEC.search(s) for s in subs), (subs or [])[:3])

        # ④ 勾选 → 批量关联按钮解禁并报数
        await js("(()=>{const c=document.querySelector('#dwPano .dwGChk');"
                 "if(c){c.checked=true;c.dispatchEvent(new Event('change'));}return 1})()")
        await asyncio.sleep(0.8)
        btn = await js("(()=>{const b=document.querySelector('#dwPanoLink');"
                       "return b? {t:b.innerText.trim(), dis:b.disabled}:null})()")
        # ⚠️ 按钮文案用的是**全角括号**（中文排版），断言别用半角 '('
        chk('4 勾选后「关联选中」解禁并显示条数',
            bool(btn) and not btn.get('dis') and '（1）' in (btn.get('t') or ''), btn)

        # ⑤ 同编码其他照片（辅助判断参考）
        #    2026-10-20 参考块改成小卡片（.dw-sib，只铺最近 8 张 + 展开更早的），
        #    类名随之一并更新。
        sibs = await js("(()=>[...document.querySelectorAll('#dwSibs .dw-sib')]"
                        ".map(e=>e.innerText.replace(/\\s+/g,' ').trim()))()")
        # ⚠️ 2026-10-21：标题「同编码其他照片」在 2026-10-20 改小卡片时被移进
        #    #dwSibsSec 的 h4，#dwSibs 首行现在是「最近 N/M 张」计数行。
        #    老断言读 #dwSibs 首行找「其他照片」，从改版那天起就必然假红。
        head = await js("(()=>{const e=document.querySelector('#dwSibsSec h4');"
                        "return e? e.innerText:''})()")
        cnt = await js("(()=>{const e=document.querySelector('#dwSibs');"
                       "return e? e.innerText.split('\\n')[0]:''})()")
        chk('5 关联后出现「同产品编码的其他照片」参考块',
            bool(sibs) and '其他照片' in (head or ''),
            ((head or '')[:40] + ' | ' + (cnt or '')[:30]))
        chk('5 参考块每张也带文件名与时间',
            bool(sibs) and all(SEC.search(s) for s in sibs), (sibs or [])[:3])

        # ⑧ 重新识别拆两档（2026-10-19）：OCR 识别（免费）+ 大模型识别（花额度）
        btns = await js("(()=>({ocr:document.querySelector('#dwRegovOcr')?.innerText.trim(),"
                        "full:document.querySelector('#dwRegov')?.innerText.trim(),"
                        "ocrT:document.querySelector('#dwRegovOcr')?.title||'',"
                        "fullT:document.querySelector('#dwRegov')?.title||''}))()")
        chk('8 「OCR 识别」与「大模型识别」两个按钮都在',
            (btns or {}).get('ocr') == 'OCR 识别'
            and (btns or {}).get('full') == '大模型识别', btns)
        chk('8 title 讲清额度差别（OCR 不花额度 / 大模型花）',
            '多模态额度' in (btns or {}).get('ocrT', '')
            and '花多模态额度' in (btns or {}).get('fullT', ''),
            {k: (btns or {}).get(k, '')[:40] for k in ('ocrT', 'fullT')})

        # ⑦ 「不遗漏」出口：组被截断时给「展开整组」，点了就出全组只读网格
        more = await js("(()=>{const b=document.querySelector('#dwGroupMoreBtn');"
                        "const t=document.querySelector('#dwGroupMore');"
                        "return b? {txt:t.innerText.replace(/\\s+/g,' ').trim()} "
                        ": {txt:(t?t.innerText.trim():'')}})()")
        if more and '展开整组' in more.get('txt', ''):
            await js("(()=>{const b=document.querySelector('#dwGroupMoreBtn');"
                     "b&&b.click();return 1})()")
            await asyncio.sleep(1.2)
            await drain()
            n_more = await js("document.querySelectorAll('#dwGroupAllGrid [data-morepid]').length")
            note = await js("(()=>{const e=document.querySelector('#dwGroupAllGrid');"
                            "return e? e.innerText.split('\\n')[0]:''})()")
            chk('7 截断组「展开整组」点开出全组只读网格',
                (n_more or 0) > 0 and '只读' in (note or ''),
                '%d 张 | %s' % (n_more or 0, (note or '')[:50]))
        else:
            chk('7 截断组「展开整组」点开出全组只读网格',
                True, '本组未截断（%s），出口无需出现' % (more or {}).get('txt', '')[:40])

        bad = [e for e in excs if 'favicon' not in json.dumps(e, ensure_ascii=False)]
        chk('6 全程无 JS 异常', not bad,
            (json.dumps(bad[:2], ensure_ascii=False)[:300] if bad else ''))
    return True


try:
    res = asyncio.run(main())
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    print('[FAIL] 脚本异常：%s' % e)
    res = False
finally:
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass

print('----')
print('FAIL %d' % len(fails))
sys.exit(0 if res and not fails else 1)