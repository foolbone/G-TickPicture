# -*- coding: utf-8 -*-
"""CDP 实跑：验证 2026-10-04 标准产品页这四项。

  1 列表「N 待关」与详情候选区口径一致（原来装箱单照被算进去，详情却是空的）
  2 抽屉里能快速切换产品（上一个 / 下一个 + 键盘）
  3 字段修改有明确的「保存」按钮，改了没保存要拦
  4 不再出现「N 个批次未拍到」这类提示

只验**能在真实浏览器里判定**的部分；后端口径由 tests + _diag_cand.py 覆盖。
"""
import asyncio, json, os, shutil, subprocess, sys, tempfile, time
import urllib.request
import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
URL = 'http://127.0.0.1:8765/'
PORT = 9339
TMP = os.path.join(tempfile.gettempdir(), 'pl_cdp_ui1004')

fails = []
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


# 先问后端：现在还有哪些产品 cand_count>0（改完后只剩 4 个，且每个在详情里都看得见）
api_prod = http_json('http://127.0.0.1:8765/api/products?limit=600&sort=code',
                     retries=3, timeout=25)
items = (api_prod or {}).get('items') or []
print('后端返回产品数：%d' % len(items))
cand_codes = [r['code'] for r in items if (r.get('cand_count') or 0) > 0]
print('后端 cand_count>0 的产品：%d 个 -> %s' % (len(cand_codes), cand_codes[:6]))

# 一个确定有照片的产品（用来验「点照片开详情」不会被产品抽屉盖住）
api_has = http_json('http://127.0.0.1:8765/api/products?has=yes&limit=1&sort=code',
                    retries=3, timeout=25)
photo_code = ((api_has or {}).get('items') or [{}])[0].get('code', '')
print('用于验照片详情的产品：%s' % photo_code)

shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % PORT, '--user-data-dir=' + TMP,
     '--window-size=1440,2000', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪（Edge 起不来？）'); return False
    page = next((t for t in http_json('/json/list') if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page'); return False

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
                                               'returnByValue': True, 'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        # 进产品页
        await js("document.querySelector('nav button[data-tab=products]').click()")
        await asyncio.sleep(2.5)
        await drain()

        # ═══ 4 不再出现「批次未拍到」 ═══
        noMiss = await js("""(()=>{
            const t=document.body.innerText||'';
            return !t.includes('个批次未拍到') && !t.includes('未拍到');
        })()""")
        chk('4 页面里没有「批次未拍到」字样', noMiss is True, noMiss)

        # ═══ 1 列表「N 待关」与详情候选一致 ═══
        # 取列表里第一个带「待关」角标的行，点开它，详情里必须有候选卡片
        tag = await js("""(()=>{
            const tr=[...document.querySelectorAll('#pBody tr')]
              .find(t=>t.innerText.includes('待关'));
            if(!tr) return null;
            const m=(tr.innerText.match(/(\\d+)待关/)||[])[1];
            return {code:tr.dataset.code, n:parseInt(m||'0')};
        })()""")
        if not tag:
            # 当前页没有带待关的：直接搜后端给的第一个
            if cand_codes:
                await js("(()=>{const q=document.querySelector('#pQ');q.value='%s';"
                         "q.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()"
                         % cand_codes[0])
                await asyncio.sleep(3)
                await drain()
                tag = await js("""(()=>{
                    const tr=document.querySelector('#pBody tr'); if(!tr) return null;
                    const m=(tr.innerText.match(/(\\d+)待关/)||[])[1];
                    return {code:tr.dataset.code, n:parseInt(m||'0')};
                })()""")
        chk('1 列表里能找到带「N 待关」的行', bool(tag), tag)
        if tag:
            await js("document.querySelector('#pBody tr').click()")
            await asyncio.sleep(5)
            await drain()
            candN = await js("""(()=>{
                const items=document.querySelectorAll('#pShots .cand-item').length;
                const sib=document.querySelectorAll('#pShots .sib-check').length;
                return {items, sib, total: items+sib};
            })()""")
            chk('1 详情里确实有候选照片（不再对不上）',
                bool(candN) and candN['total'] > 0, {'列表标': tag['n'], '详情': candN})

        # ═══ 2 上一个 / 下一个 ═══
        await js("document.querySelector('#pQ').value=''")
        await js("document.querySelector('#pQ').dispatchEvent("
                 "new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
        await asyncio.sleep(3)
        await drain()
        await js("document.querySelector('#pBody tr').click()")
        await asyncio.sleep(4)
        await drain()
        c0 = await js("document.querySelector('#pBody tr.sel')?.dataset?.code||''")
        pos0 = await js("document.querySelector('#pPos')?.textContent||''")
        await js("document.querySelector('#pNext').click()")
        await asyncio.sleep(4)
        await drain()
        c1 = await js("document.querySelector('#pBody tr.sel')?.dataset?.code||''")
        pos1 = await js("document.querySelector('#pPos')?.textContent||''")
        chk('2 点「下一个」换到另一个产品', bool(c0) and bool(c1) and c0 != c1,
            {'from': c0, 'to': c1})
        chk('2 列表选中行跟着走', c1 == await js("document.querySelector('#pBody tr.sel')?.dataset?.code||''"), c1)
        chk('2 位置提示有更新', bool(pos0) and pos0 != pos1, {'0': pos0, '1': pos1})
        await js("document.querySelector('#pPrev').click()")
        await asyncio.sleep(4)
        await drain()
        c2 = await js("document.querySelector('#pBody tr.sel')?.dataset?.code||''")
        chk('2 点「上一个」能回去', c2 == c0, {'expect': c0, 'got': c2})
        # 键盘 ↓ 也能切
        await js("document.body.focus()")
        await cmd('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'ArrowDown',
                                             'code': 'ArrowDown', 'windowsVirtualKeyCode': 40})
        await asyncio.sleep(3.5)
        await drain()
        c3 = await js("document.querySelector('#pBody tr.sel')?.dataset?.code||''")
        chk('2 键盘 ↓ 也能切下一个', c3 != c2 and bool(c3), {'from': c2, 'to': c3})

        # ═══ 3 字段保存 ═══
        code = await js("document.querySelector('#pBody tr.sel')?.dataset?.code||''")
        oldName = await js("document.querySelector('#pShots [data-pf=name]')?.value||''")
        dis0 = await js("document.querySelector('#peSave')?.disabled")
        chk('3 没改时「保存」按钮是禁用的', dis0 is True, dis0)
        await js("""(()=>{const i=document.querySelector('#pShots [data-pf=name]');
            i.value='CDP改名测试'; i.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        await asyncio.sleep(0.5)
        dis1 = await js("document.querySelector('#peSave')?.disabled")
        msg1 = await js("document.querySelector('#peMsg')?.textContent||''")
        chk('3 改了之后「保存」按钮亮起', dis1 is False, dis1)
        chk('3 提示「有未保存的修改」', '未保存' in msg1, msg1)
        await js("document.querySelector('#peSave').click()")
        await asyncio.sleep(2.5)
        await drain()
        msg2 = await js("document.querySelector('#peMsg')?.textContent||''")
        chk('3 保存后提示「已保存」', '已保存' in msg2, msg2)
        dis2 = await js("document.querySelector('#peSave')?.disabled")
        chk('3 保存后按钮回到禁用（无未保存改动）', dis2 is True, dis2)
        # 后端真落库了吗 —— 直接问接口，不看前端自说自话
        if code:
            p = http_json('http://127.0.0.1:8765/api/products/' + code, retries=6)
            chk('3 后端 name 真的改了', (p or {}).get('name') == 'CDP改名测试',
                (p or {}).get('name'))
            # 改回去，别把测试数据留在库里
            await js("""(()=>{const i=document.querySelector('#pShots [data-pf=name]');
                i.value=%s; i.dispatchEvent(new Event('input',{bubbles:true}));})()"""
                % json.dumps(oldName))
            await asyncio.sleep(0.4)
            await js("document.querySelector('#peSave').click()")
            await asyncio.sleep(2)
            await drain()
            p2 = http_json('http://127.0.0.1:8765/api/products/' + code, retries=6)
            chk('3 已还原为原品名（不污染数据）', (p2 or {}).get('name') == oldName,
                {'expect': oldName, 'got': (p2 or {}).get('name')})

        # ═══ 5 产品抽屉里点照片 → 照片详情不能被产品抽屉盖住 ═══
        if photo_code:
            await js("(()=>{const q=document.querySelector('#pQ');q.value='%s';"
                     "q.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()"
                     % photo_code)
            await asyncio.sleep(3)
            await drain()
            await js("document.querySelector('#pBody tr')?.click()")
            await asyncio.sleep(4.5)
            await drain()
            await js("(()=>{const s=document.querySelector('#pShots .shot[data-id]');"
                     "if(s){s.click(); return true;} return null;})()")
            await asyncio.sleep(3)
            await drain()
            zid = await js("""(()=>{
                const d=document.querySelector('#drawer'), p=document.querySelector('#pDetail');
                if(!d.classList.contains('on')) return {on:false};
                const zd=parseInt(getComputedStyle(d).zIndex)||0;
                const zp=parseInt(getComputedStyle(p).zIndex)||0;
                const r=d.getBoundingClientRect();
                const x=r.left+Math.round(r.width/2), y=r.top+200;
                const el=document.elementFromPoint(x,y);
                return {on:true, zd, zp, okZ: zd>zp,
                        hit: !!(el && d.contains(el)),
                        tag: el? (el.tagName+'.'+String(el.className).slice(0,24)) : null};
            })()""")
            chk('5 产品抽屉里点照片开得出照片详情', bool(zid) and zid.get('on') is True, zid)
            chk('5 照片详情层级高于产品抽屉', bool(zid) and zid.get('okZ') is True, zid)
            chk('5 照片详情真的可见（该点命中的是它，不是产品抽屉）',
                bool(zid) and zid.get('hit') is True, zid)
            # Esc 应该只关最上面这层
            await js("window.confirm = ()=>true;")
            await cmd('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Escape',
                                                 'code': 'Escape', 'windowsVirtualKeyCode': 27})
            await asyncio.sleep(1.5)
            await drain()
            after = await js("({drawer: document.querySelector('#drawer').classList.contains('on'),"
                             " pdetail: document.querySelector('#pDetail').classList.contains('on')})")
            chk('5 Esc 只关照片详情这层，产品抽屉还在',
                after.get('drawer') is False and after.get('pdetail') is True, after)

        # ═══ 3b 有未保存改动时离开要问 ═══
        if not await js("document.querySelector('#pDetail').classList.contains('on')"):
            await js("document.querySelector('#pBody tr')?.click()")
            await asyncio.sleep(4)
            await drain()
        await js("""(()=>{const i=document.querySelector('#pShots [data-pf=spec]');
            i.value='未保存就跑'; i.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        await asyncio.sleep(0.4)
        # 自动接受 confirm（覆盖 window.confirm 让它返回 false = 用户选「取消」）
        await js("window.confirm = ()=>false;")
        await js("document.querySelector('#pDetailClose').click()")
        await asyncio.sleep(1)
        stillOn = await js("document.querySelector('#pDetail').classList.contains('on')")
        chk('3b 有未保存改动 → 取消时抽屉不关', stillOn is True, stillOn)
        await js("window.confirm = ()=>true;")
        await js("document.querySelector('#pDetailClose').click()")
        await asyncio.sleep(1)
        closed = await js("!document.querySelector('#pDetail').classList.contains('on')")
        chk('3b 确认后抽屉关闭', closed is True, closed)

        # ═══ JS 异常 ═══
        await drain()
        chk('无 JS 运行时异常', len(excs) == 0, [str(e)[:160] for e in excs[:3]])

    print('----')
    print('RESULT: %s  (FAIL %d)' % ('PASS' if not fails else 'FAIL', len(fails)))
    return len(fails) == 0


ok = asyncio.run(main())
proc.terminate()
sys.exit(0 if ok else 1)
