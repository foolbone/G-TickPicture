# -*- coding: utf-8 -*-
"""CDP 实跑：拍照时间全站显示（2026-10-05）。

老板要求：同组连拍照片上显示拍照时间，其他地方只要展示图片的地方都要显示。

锁死七件事（每处都取真实 DOM 文本，不看代码）：
  1 照片库卡片时间**到秒**（旧口径 slice(0,16) 只到分钟，连拍 0~2 秒一张时
    等于没显示 —— 断言里必须出现 ':SS' 的秒段）；
  2 分组视图组头显示 起止时间 + 跨多久；组内卡片显示「距上一张 +Ns」；
  3 照片详情抽屉显示完整时间 + 距上一张间隔；
  4 同组连拍小卡（.gshot-t）每张都有时间，间隔 > 0 的要标出来；
  5 点同组小卡进大图查看器，图注里也有时间；
  6 标准产品详情：已关联照片卡（复用 shotCard）+ 同组候选带间隔；
  7 检索结果卡片时间到秒；发现新产品的缩略图 figcaption 有时间。
全程无 JS 异常。
"""
import asyncio, json, os, re, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9345
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_ui1007')

fails = []
# 到秒：HH:MM:SS（HH 允许 00-23）
SEC = re.compile(r'\b([01]\d|2[0-3]):[0-5]\d:[0-5]\d\b')


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


def http_json(url, retries=40, port=PORT, timeout=3):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url if url.startswith('http')
                                        else 'http://127.0.0.1:%d%s' % (port, url),
                                        timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            time.sleep(0.5)
    return None


shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
     '--window-size=1600,2200', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪')
        return False
    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        _id = [0]

        async def cmd(method, params=None, wait=True):
            _id[0] += 1
            await ws.send(json.dumps({'id': _id[0], 'method': method,
                                      'params': params or {}}))
            if not wait:
                return None
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
        await asyncio.sleep(4)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        async def wait_rows(sel, n=1, tries=30):
            for _ in range(tries):
                await asyncio.sleep(1.0)
                await drain()
                c = await js("document.querySelectorAll('%s').length" % sel)
                if (c or 0) >= n:
                    return c
            return await js("document.querySelectorAll('%s').length" % sel)

        # ═══ 1 照片库卡片时间到秒 ═══
        await js("window.go && window.go('batches')")
        n = await wait_rows('#shots .shot', 1)
        meta = await js("""(()=>[...document.querySelectorAll('#shots .shot .meta.faint')]
            .map(e=>e.innerText.trim()))()""")
        sec_ok = [m for m in (meta or []) if SEC.search(m)]
        chk('1 照片库已加载', (n or 0) > 0, n)
        chk('1 卡片时间到秒（含 HH:MM:SS）', bool(sec_ok),
            (meta or [])[:3] or meta)

        # ═══ 2 分组视图：组头起止 + 组内间隔 ═══
        await js("""(()=>{const b=[...document.querySelectorAll('nav button')]
            .find(x=>x.dataset.tab==='batches');b&&b.click();})()""")
        await asyncio.sleep(2)
        await drain()
        await js("""(()=>{const b=document.querySelector('#shotView button[data-v=group]');
            b&&b.click();})()""")
        await wait_rows('#shots .gcard', 1)
        gt = await js("""(()=>[...document.querySelectorAll('#shots .gtime')]
            .map(e=>e.innerText.trim()))()""")
        span = [t for t in (gt or []) if '跨' in t]
        chk('2 组头显示起止时间', bool([t for t in (gt or []) if SEC.search(t)]), (gt or [])[:2])
        chk('2 组头显示跨多久（跨 2m38s）', bool(span), span[:2])
        # 展开第一组，看组内卡片的间隔
        await js("document.querySelector('#shots .gcard').click()")
        await asyncio.sleep(1.5)
        await drain()
        gaps = await js("""(()=>[...document.querySelectorAll('#shots .gcard.open .shot .meta.faint')]
            .map(e=>e.innerText).filter(t=>/\\+\\d/.test(t)))()""")
        chk('2 组内卡片标出「距上一张 +Ns」', bool(gaps),
            (gaps or [])[:3])

        # ═══ 3 照片详情抽屉：完整时间 + 间隔 ═══
        await js("document.querySelector('#shots .gcard.open .shot').click()")
        await wait_rows('#drawer.on #dwImg', 1)
        src_line = await js("""(()=>{const e=document.querySelector('#drawer .dw-src');
            return e?e.innerText.replace(/\\s+/g,' ').trim():''})()""")
        chk('3 详情显示拍照时间（到秒）', bool(SEC.search(src_line or '')), src_line)
        chk('3 详情带来源（柜号/箱号/大小）', bool(re.search(r'MB', src_line or '')), src_line)

        # ═══ 4 同组连拍小卡 ═══
        gshot = await js("""(()=>[...document.querySelectorAll('#drawer .gshot-t')]
            .map(e=>e.innerText.trim()))()""")
        chk('4 同组小卡每张都有时间到秒',
            bool(gshot) and all(SEC.search(t) for t in gshot), (gshot or [])[:3])
        chk('4 同组小卡标出间隔 +Ns', any('+' in t for t in (gshot or [])), (gshot or [])[:3])
        # ═══ 5 点小卡进大图，图注也有时间 ═══
        # 点同组小卡（点 data-gpid 元素本身，避开 img 冒泡的分支判断）
        # 重试：详情是异步渲染的，偶发点到的瞬间 handler 还没绑上
        for _try in range(3):
            await js("(()=>{const c=document.querySelector('#drawer .shot-card');c&&c.click();})()")
            await asyncio.sleep(2)
            await drain()
            if await js("document.querySelector('#mask')?.classList.contains('on')"):
                break
        await wait_rows('#mask.on', 1, tries=12)
        # ⚠️ 用 textContent 而不是 innerText：innerText 对 display:none 的元素返回 ''，
        #    之前就是这样「假红」的（mask 有开关动画，读到的可能是空串）
        # ⚠️ 立即执行函数末尾的 () 不能漏：漏了返回的是函数本身，CDP 序列化成 {}
        #    -> 断言读到空 dict，看起来像「功能没生效」，其实功能是好的
        cap = await js("(()=>document.querySelector('#maskCap')?.textContent||'')()")
        mask_on = await js("document.querySelector('#mask')?.classList.contains('on')")
        chk('5 大图已打开', bool(mask_on), mask_on)
        dbg = await js("""(()=>({cards:document.querySelectorAll('#drawer .shot-card').length,
            title:(document.querySelector('#drawer .shot-card')||{}).title,
            gt:(document.querySelector('#drawer .gshot-t')||{}).textContent,
            caphtml:document.querySelector('#maskCap').outerHTML.length}))()""")
        chk('5 大图图注含拍照时间', bool(SEC.search(cap or '')),
            {'cap': cap, 'dbg': dbg})
        await js("document.querySelector('#mask .close').click()")
        await asyncio.sleep(1)

        # ═══ 6 标准产品详情：已关联卡 + 同组候选间隔 ═══
        await js("""(()=>{const i=document.querySelector('#pQ');
            if(i){i.value='103006010017BM';i.dispatchEvent(new Event('input'));}
            const b=[...document.querySelectorAll('nav button')]
              .find(x=>x.dataset.tab==='products');b&&b.click();})()""")
        await asyncio.sleep(1)
        await drain()
        await wait_rows('#pBody tr', 1)
        await js("document.querySelector('#pBody tr').click()")
        await wait_rows('#pShots .shot, #pShots .cand-item', 1)
        await asyncio.sleep(6)
        await drain()
        pmeta = await js("""(()=>[...document.querySelectorAll('#pShots .shot .meta.faint')]
            .map(e=>e.innerText))()""")
        chk('6 产品详情已关联照片卡时间到秒',
            bool(pmeta) and all(SEC.search(t) for t in pmeta), (pmeta or [])[:2])
        sib = await js("""(()=>[...document.querySelectorAll('#pShots .cand-item .faint')]
            .map(e=>e.innerText).filter(t=>/\\+\\d/.test(t)))()""")
        chk('6 同组候选带间隔', bool(sib), (sib or [])[:3])

        # ═══ 7 检索结果 + 发现新产品缩略图 ═══
        await js("""(()=>{const c=document.querySelector('#pDetailClose');
            c&&c.click();})()""")
        await asyncio.sleep(1)
        await js("""(()=>{const b=[...document.querySelectorAll('nav button')]
            .find(x=>x.dataset.tab==='report');b&&b.click();})()""")
        await asyncio.sleep(2)
        await drain()
        # 编码要先点「解析文本」进 _rpCodes，再点「开始检索」——
        # 只往 textarea 塞值不点解析，_rpCodes 为空会被 toast 挡掉（静默空结果）
        await js("""(()=>{const t=document.querySelector('#rpText');
            if(!t) return; t.value='103006010017BM\\n1000000119';
            t.dispatchEvent(new Event('input'));
            document.querySelector('#rpParse').click();})()""")
        await asyncio.sleep(1.5)
        await drain()
        n_codes = await js("document.querySelectorAll('#rpCodes .chip').length")
        chk('7 编码已解析进待检列表', (n_codes or 0) > 0, n_codes)
        await js("document.querySelector('#rpGo').click()")
        await wait_rows('#rpResult .rp-shot', 1, tries=25)
        await drain()
        ft = await js("""(()=>[...document.querySelectorAll('#rpResult .rp-shot .ft')]
            .map(e=>e.innerText.trim()))()""")
        rp_txt = await js("(()=>document.querySelector('#rpResult')?.innerText||'')")
        chk('7 检索结果时间到秒', bool(ft) and all(SEC.search(t) for t in ft),
            {'ft': (ft or [])[:2], 'result_head': (rp_txt or '')[:120]})

        await js("""(()=>{const b=[...document.querySelectorAll('nav button')]
            .find(x=>x.dataset.tab==='review');b&&b.click();})()""")
        await asyncio.sleep(2)
        await drain()
        await js("""(()=>{const t=document.querySelector('#rt-wb');t&&t.click();})()""")
        await asyncio.sleep(3)
        await drain()
        caps = await js("""(()=>[...document.querySelectorAll('#dcList .dcthumb-w figcaption')]
            .map(e=>e.innerText.trim()))()""")
        chk('7 发现新产品缩略图带时间到秒',
            bool(caps) and all(SEC.search(t) for t in caps), (caps or [])[:3])

        chk('9 全程无 JS 异常', not excs, excs[:2])
        return True

    return False


try:
    asyncio.run(main())
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print('----')
if fails:
    print('FAIL: ' + ' | '.join(fails))
    sys.exit(1)
print('ALL PASS')
