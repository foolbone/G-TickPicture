# -*- coding: utf-8 -*-
"""给培训 PPT 抓真实截图（对着 8765 真实库跑）。

用法：python tools/productlib/checks/shot_for_ppt.py <输出目录>
产物：<输出目录>/NN_名称.png，按拍摄顺序编号，方便排版时对号入座。

⚠️ 为什么用真浏览器截图而不是示意图：培训 PPT 里「按钮长什么样、
点完跳到哪」是最难讲清楚的部分，示意图讲不了一屏就能说清的东西。
本脚本对着**老板真实库**跑，所有截图都是真实界面。
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time

import websockets

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = int(os.environ.get('SHOT_PORT', '8765'))
URL = 'http://127.0.0.1:%d/' % PORT
CDP_PORT = int(os.environ.get('SHOT_CDP', '9361'))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'ppt_shots')

os.makedirs(OUT, exist_ok=True)
fails = []


def chk(name, ok, info=''):
    print(('[ OK ] ' if ok else '[FAIL] ') + name + (('  ' + str(info)) if info else ''),
          flush=True)
    if not ok:
        fails.append(name)


import urllib.request  # noqa: E402

PROFILE = os.path.join(os.environ.get('TEMP', '/tmp'), 'pl_ppt_shot_profile')
import shutil  # noqa: E402
shutil.rmtree(PROFILE, ignore_errors=True)

# ⚠️ 必须自己起 Edge：只连调试端口是不行的，没浏览器进程就没有 CDP 端点。
edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + PROFILE,
     '--window-size=1600,1000', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def http_json(path, retries=40):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(
                    'http://127.0.0.1:%d%s' % (CDP_PORT, path), timeout=3) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


# (文件名, 说明) —— 顺序即拍摄顺序
SHOTS = [
    ('01_柜列表', '柜列表页：全部柜 + 每行的柜作业入口'),
    ('02_新建柜', '新建柜模态'),
    ('03_柜作业_建柜', '柜作业①建柜'),
    ('04_柜作业_导清单', '柜作业②导入清单'),
    ('05_柜作业_照片', '柜作业③照片（治理面板）'),
    ('06_治理面板', '照片治理面板：分类→读码→关联'),
    ('07_柜作业_选图', '柜作业④选图'),
    ('08_柜作业_报告', '柜作业⑤生成报告'),
    ('09_产品库', '产品库列表 + 柜号筛选'),
    ('10_产品详情', '产品详情抽屉'),
    ('11_照片库', '照片库：五档选项卡'),
    ('12_照片抽屉', '照片详情抽屉（监装细分/模型建议）'),
    ('13_报告档案', '报告档案列表'),
    ('14_设置', '设置页（多模态模型配置）'),
    ('15_监装细分', '监装照片详情：监装细分 + 模型建议'),
]


async def main():
    if not http_json('/json/version'):
        print('[FAIL] 调试端口未就绪')
        return False
    page = next((t for t in (http_json('/json/list') or [])
                 if t.get('type') == 'page'), None)
    if not page:
        print('[FAIL] 找不到 page')
        return False

    async with websockets.connect(page['webSocketDebuggerUrl'],
                                  max_size=None) as ws:
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
                    m = json.loads(await asyncio.wait_for(ws.recv(), 0.2))
                    if m.get('method') == 'Runtime.exceptionThrown':
                        excs.append(m['params'])
            except asyncio.TimeoutError:
                pass

        await cmd('Runtime.enable')
        await cmd('Page.enable')
        await cmd('Emulation.setDeviceMetricsOverride',
                  {'width': 1600, 'height': 1000, 'deviceScaleFactor': 1,
                   'mobile': False})
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(4.5)
        await drain()

        async def js(expr):
            r = await cmd('Runtime.evaluate', {'expression': expr,
                                               'returnByValue': True,
                                               'awaitPromise': True})
            return (r.get('result') or {}).get('value')

        async def wait(sec=1.5):
            await asyncio.sleep(sec)
            await drain()

        async def shot(name, note, keep_modal=False):
            # 🔴 拍之前先把所有浮层关干净 —— 模态、抽屉、遮罩。
            #    我第一版只关'.modal-overlay'，结果**产品详情抽屉**（用的是
            #    #drawer，不是 #pdClose）一直开着，后面 3 张截图全蒙着它，
            #    拍出来「标题写照片库、图里是产品详情」。
            #    这里两层保险：先按 Esc（走真实关闭逻辑），再强制摘 class。
            # 🔴 拍之前把所有浮层关干净。
            #    判据用「有没有 .on 类」，**不要用 display** ——
            #    抽屉类浮层隐藏靠 transform:translateX(100%)，display 始终可见，
            #    用 display 判永远判不出「开着」。
            #    而且元素不止一套：产品详情是 #pDetail/#pMask（不是 #drawer，
            #    我第一版按 #drawer 找，结果产品抽屉一直关不掉，
            #    后面 3 张图全蒙着它 —— 标题写照片库、图里是产品详情）。
            OPENERS = ('.modal-overlay,#drawer.on,#pDetail.on,#bDrawer.on,'
                       '#ctDrawer.on,#mask.on,#pMask.on,#bMask.on,#ctMask.on')
            CLOSERS = ('#drawer,#pDetail,#pDetailMask,#bDrawer,#ctDrawer,'
                       '#mask,#pMask,#bMask,#ctMask,.modal-overlay')
            CHECK = """(()=>{const L=document.querySelectorAll('%s');
                return L.length? 'on' : 'none';})()""" % OPENERS

            async def esc():
                for _ in range(2):
                    await cmd('Input.dispatchKeyEvent',
                              {'type': 'keyDown', 'key': 'Escape', 'code': 'Escape',
                               'windowsVirtualKeyCode': 27, 'nativeVirtualKeyCode': 27})
                    await cmd('Input.dispatchKeyEvent',
                              {'type': 'keyUp', 'key': 'Escape', 'code': 'Escape',
                               'windowsVirtualKeyCode': 27, 'nativeVirtualKeyCode': 27})
                    await asyncio.sleep(0.6)

            stuck = await js(CHECK)
            if stuck != 'none' and not keep_modal:
                await esc()
                # 兜底：Esc 没关掉的（带 confirmLeave 的会拦）直接摘 class
                await js("""(()=>{for(const e of document.querySelectorAll('%s')){
                    e.classList.remove('on');} return 1;})()""" % CLOSERS)
                await asyncio.sleep(0.6)
                still = await js(CHECK)
                chk('  · 关掉残留浮层（%s）' % name, still == 'none', still)
            r = await cmd('Page.captureScreenshot', {'format': 'png'})
            p = os.path.join(OUT, name + '.png')
            with open(p, 'wb') as f:
                f.write(base64.b64decode(r['data']))
            ok = os.path.exists(p) and os.path.getsize(p) > 8000
            chk('截图 %s（%s）' % (name, note), ok,
                '%d KB' % (os.path.getsize(p) // 1024) if ok else '文件异常')
            return ok

        # 选一个数据最全的柜
        cid = await js("""(()=>{const s=document.querySelector('#globalCid');
            if(!s||s.options.length<2) return '';
            // 挑清单行最多的那个柜（截图更有内容）
            let best='', n=-1;
            for(const o of s.options){ if(!o.value) continue;
              const t=(o.textContent||'');
              const m=t.match(/(\\d+)\\s*行/); const v=m?+m[1]:0;
              if(v>n){n=v;best=o.value;} }
            s.value=best||s.options[1].value;
            s.dispatchEvent(new Event('change',{bubbles:true}));
            return s.value;})()""")
        chk('选定当前柜', bool(cid), cid)
        await wait(2.5)

        # 01 柜列表
        await js("go('containers')")
        await wait(2.5)
        await shot(SHOTS[0][0], SHOTS[0][1])

        # 02 新建柜模态
        await js("document.querySelector('#cNew').click()")
        await wait(1.5)
        # 🔴 keep_modal=True：这页要拍的就是「新建柜」弹窗本身。
        #    守卫若在拍摄前先Escape，弹窗就被关掉了，拍到的成了柜列表 ——
        #    我第一版就这样拍出一张「标题写新建柜、图里是列表」的图。
        await shot(SHOTS[1][0], SHOTS[1][1], keep_modal=True)
        await cmd('Input.dispatchKeyEvent',
                  {'type': 'keyDown', 'key': 'Escape', 'code': 'Escape',
                   'windowsVirtualKeyCode': 27, 'nativeVirtualKeyCode': 27})
        await cmd('Input.dispatchKeyEvent',
                  {'type': 'keyUp', 'key': 'Escape', 'code': 'Escape',
                   'windowsVirtualKeyCode': 27, 'nativeVirtualKeyCode': 27})
        await wait(1.2)

        # 进柜作业
        await js("enterWizard('')")
        await wait(2.5)

        # 🔴 步骤 → 截图的映射**写死**，不用 SHOTS[i+2] 这种算术：
        #    ③照片那一步要多拍一张治理面板并 continue，下标就全错位了
        #    （我第一版就因此漏拍「⑤生成报告」、把治理面板拍了两遍）。
        STEP_SHOT = {'container': 2, 'checklist': 3, 'picks': 6, 'report': 7}
        for key, idx in STEP_SHOT.items():
            await js("""(()=>{const s=document.querySelector('#wizBar .wstep[data-step="%s"]');
                if(s) s.click();})()""" % key)
            await wait(2.2)
            await shot(SHOTS[idx][0], SHOTS[idx][1])

        # ③照片步：作业页 + 展开后的治理面板，各拍一张
        await js("""(()=>{const s=document.querySelector('#wizBar .wstep[data-step=photos]');
            if(s) s.click();})()""")
        await wait(2.2)
        await shot(SHOTS[4][0], SHOTS[4][1])
        await js("""(()=>{const h=document.querySelector('#govHead');
            if(h) h.click();})()""")
        await wait(1.8)
        await shot(SHOTS[5][0], SHOTS[5][1])
        await js("""(()=>{const h=document.querySelector('#govHead');
            if(h) h.click();})()""")
        await wait(1.0)

        # 09 产品库
        await js("go('products')")
        await wait(3.0)
        await shot(SHOTS[8][0], SHOTS[8][1])

        # 10 产品详情抽屉
        await js("""(()=>{const r=document.querySelector('#pBody tr');
            if(r) r.click();})()""")
        await wait(2.5)
        await shot(SHOTS[9][0], SHOTS[9][1])
        await js("""(()=>{for(const id of ['#pdClose','#pdMask']){
            const e=document.querySelector(id); if(e){e.click(); return;}}
            const m=document.querySelector('#mask'); if(m) m.click();})()""")
        await wait(1.2)

        # 11 照片库
        await js("go('batches')")
        await wait(3.5)
        await shot(SHOTS[10][0], SHOTS[10][1])

        # 12 照片详情抽屉
        await js("""(()=>{const r=document.querySelector('#shots .shot, #pShots .shot, #pShots > *');
            if(r) r.click();})()""")
        await wait(2.8)
        await shot(SHOTS[11][0], SHOTS[11][1])
        await js("""(()=>{const m=document.querySelector('#mask');
            if(m) m.click();})()""")
        await wait(1.0)

        # 13 报告档案
        await js("go('report')")
        await wait(3.0)
        await shot(SHOTS[12][0], SHOTS[12][1])

        # 14 设置
        await js("go('set')")
        await wait(2.5)
        await shot(SHOTS[13][0], SHOTS[13][1])

        # 15 监装照片详情（监装细分 + 模型建议）
        # ⚠️ 两个坑：
        #  ①必须挑**用途=监装**的照片 —— 监装细分那一行只在监装照上显示，
        #    预检/未分类的照打开是隐藏的；
        #  ②断言要查**可见性**，不能只查存在（`!!el` 对 display:none 的元素
        #    也返回 true —— 我第一版就栽在这，拍了张没有细分的照片）。
        # 这里直接用接口取 id 再 openDrawer，不靠列表点（列表点会点到上一张）。
        pid = await js("""(async()=>{const r=await fetch('/api/photos?usage='
            + encodeURIComponent('监装') + '&limit=1');
            const j=await r.json(); const it=j.items||[];
            return it.length? it[0].id : '';})()""")
        chk('取到一张监装照片', bool(pid), pid)
        if pid:
            await js("(async()=>{const m=await import('/static/js/drawer.js');"
                     "m.setDrawerList([%r]); await m.openDrawer(%r);})()" % (pid, pid))
            await wait(3.0)
            sup = await js("""(()=>{const r=document.querySelector('#dwSuptagRow');
                if(!r) return {none:true};
                return {disp:getComputedStyle(r).display,
                        txt:r.textContent.replace(/\\s+/g,' ').trim().slice(0,60)};})()""")
            chk('「监装细分」行**可见**（不是存在但隐藏）',
                sup.get('disp') not in ('none', None), sup)
            # keep_modal=True：这页要拍的就是照片抽屉本身
        await shot(SHOTS[14][0], SHOTS[14][1], keep_modal=True)

        chk('全程无 JS 异常', not excs,
            [e.get('exception', {}).get('description', '')[:120]
             for e in excs][:3])
        return True


ok = False
try:
    ok = asyncio.run(main())
finally:
    try:
        edge.terminate(); edge.wait(timeout=8)
    except Exception:
        edge.kill()
    shutil.rmtree(PROFILE, ignore_errors=True)

print()
print('输出目录:', OUT)
print('PASS' if (ok and not fails) else 'FAIL: ' + '; '.join(fails))
sys.exit(0 if (ok and not fails) else 1)