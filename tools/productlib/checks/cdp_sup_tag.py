# -*- coding: utf-8 -*-
"""CDP 实跑：照片详情抽屉里的「模型建议 + 采用建议」（2026-10-07）。

老板要「监装图片的监装细分，在治理中由大模型分类识别，用户可以确认修改」。

store/路由层已由 tests/sup_tag.py（47 项）锁死；本脚本只验**浏览器里
真的能用**，且专盯只有实跑才暴露的问题：
  1 建议行真的画出来了，且**行是可见的**（不是 display:none 的摆设）；
  2 「采用建议」按钮存在、文案对、点了之后标签真的落上去；
  3 🔴 建议值**绝不能被预填进下拉框** —— 预填等于让机器替人拍板，
     而这张图可能直接被印进交给客户的正式报告；
  4 低置信度有「建议核对」的提示（让人知道该不该信）；
  5 采用后那一行变成「已确认」且按钮消失（不该重复采用）；
  6 全程无 JS 异常（ESM 里 import 到但没导出，静态三检全是绿的）。

⚠️ 铁律（ESM 两个经典假象）：
  · 开头的**前置闸门**：模块内部函数在 window 上取不到，直接
    window.openDrawer 会一片假绿 —— 必须动态 import() 后再调。
  · 读文本用 textContent，`display:none` 的元素 innerText 返回 ''。

⚠️ 破坏面：本脚本**自己起一个隔离实例**（临时 PL_HOME + 独立端口），
   不碰老板正在用的 8765，结束时整个临时目录删掉。
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
PORT = int(os.environ.get('PL_PORT', '8795'))
CDP_PORT = int(os.environ.get('PL_CDP', '9349'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_suptag')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_suptag_db')
URL = 'http://127.0.0.1:%d/' % PORT
PY = os.environ.get('PL_PY') or sys.executable

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name
          + ((' | ' + str(info)) if info else ''), flush=True)
    if not cond:
        fails.append(name)


def http_json(path, retries=40, port=CDP_PORT, timeout=3):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(
                    path if path.startswith('http')
                    else 'http://127.0.0.1:%d%s' % (port, path),
                    timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def api(path, payload=None, port=None):
    url = 'http://127.0.0.1:%d%s' % (port or PORT, path)
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method='POST' if data else 'GET',
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


# ── 造隔离数据：3 张监装照，各带一条不同置信度的建议 ──
# ⚠️ 必须真的生成 jpg：缩略图取不到时照片卡渲染不出来，
#    抽屉打不开的话后面每条断言都会假失败。
shutil.rmtree(HOME, ignore_errors=True)
shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(HOME, exist_ok=True)
# ⚠️ 别用 % 格式化：seed 里有大量 SQL 的 %s / %d，会跟 % 格式化打架
#    （报 not enough arguments for format string）。用 __PLACEHOLDER__ 替换。
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
seed = r'''
import os, sys
sys.path.insert(0, __REPO__)
sys.path.insert(0, __REPO__ + "/tools")
os.environ["PL_HOME"] = __HOME__
from tools.productlib import store, paths
from PIL import Image
c = store.connect(paths.db_path())
c.execute("INSERT INTO containers(id,container_no,seal_no,created_at,updated_at)"
          " VALUES('c1','UETV1234567','SL-9911','2026-10-07','2026-10-07')")
c.execute("INSERT INTO batches(id,name,kind,container_id,container_no,created_at)"
          " VALUES('b1','柜A','photos','c1','UETV1234567','2026-10-07')")
rows = [("u1","container_seal",0.86,"封条号特写"),
        ("u2","empty_container",0.42,"柜内看着是空的但光线暗"),
        ("u3","loading_process",0.91,"正在往柜里搬货")]
for i,(pid,tag,conf,rsn) in enumerate(rows,1):
    fp = os.path.join(__HOME__, pid + ".jpg")
    Image.new("RGB",(400,300),(40*i,60,200-40*i)).save(fp, quality=88)
    c.execute("INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,"
              "width,height,is_dup,group_idx,govern_state,photo_kind,photo_usage,created_at)"
              " VALUES(?,?,?,?,?,?,?,?,?,?,0,0,'done','scene','监装',?)",
              (pid, pid+".jpg", fp, "b1", "2026-10-07T10:0{0}:00".format(i),
               "exif", os.path.getsize(fp), "m"+pid, 400, 300,
               "2026-10-07T10:00:00"))
    store.set_govern(c, pid, "done", kind="scene", kind_conf=0.9, usage="监装",
                     sup_tag=tag, sup_tag_conf=conf, sup_tag_reason=rsn)
c.commit(); c.close()
print("SEEDED", paths.db_path())
'''.replace('__REPO__', repr(REPO)).replace('__HOME__', repr(DBHOME))
r = subprocess.run([PY, '-c', seed], capture_output=True, text=True, timeout=120)
if 'SEEDED' not in r.stdout:
    print('[FAIL] 造数据失败')
    print(r.stdout[-600:])
    print(r.stderr[-900:])
    sys.exit(1)
print('[ OK ] 隔离数据已就绪')

srv = subprocess.Popen(
    [PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
    env={**os.environ, 'PL_HOME': DBHOME},
    cwd=REPO,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1600,2400', URL],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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

        # ── 1 前置闸门：页面与模块真的就绪了吗 ──
        # 铁律：ES module 内部的函数在 window 上取不到，这里必须动态 import。
        boot = await js(
            "(async()=>{try{const m=await import('/static/js/drawer.js');"
            "return {fn:typeof m.openDrawer, set:typeof m.setDrawerList};}"
            "catch(e){return {err:String(e)}}})()")
        chk('1 前置闸门：drawer.js 模块可 import 且导出 openDrawer',
            bool(boot) and boot.get('fn') == 'function', boot)

        pid = 'u2'      # 42% 那张：低置信度，正好验「建议核对」提示
        opened = await js(
            "(async()=>{const m=await import('/static/js/drawer.js');"
            "m.setDrawerList([%r]); await m.openDrawer(%r);"
            "return true;})()" % (pid, pid))
        await asyncio.sleep(1.6)
        await drain()
        chk('2 抽屉真的打开了', opened is True)

        probe = await js(
            "(()=>{const row=document.querySelector('#dwSuptagAiRow');"
            "const btn=document.querySelector('#dwSuptagAccept');"
            "const sel=document.querySelector('#dwSuptag');"
            "return {row:!!row, btn:!!btn,"
            " btnText:btn?btn.textContent.trim():'',"
            " text:row?row.textContent.replace(/\\s+/g,' ').trim():'',"
            " sel:sel?sel.value:null,"
            " disp:row?getComputedStyle(row).display:null};})()")
        chk('3 建议行已渲染', probe['row'], probe)
        chk('4 建议行是可见的（不是 display:none 的摆设）',
            probe['disp'] not in ('none', None), 'display=' + str(probe['disp']))
        chk('5 「采用建议」按钮存在且文案正确',
            probe['btn'] and probe['btnText'] == '采用建议', probe['btnText'])
        chk('6 建议含置信度百分比',
            '42%' in probe['text'], probe['text'])
        chk('7 低置信度明示「建议核对」',
            '核对' in probe['text'], probe['text'])
        chk('8 建议带了一句话依据',
            '光线暗' in probe['text'], probe['text'])
        # 🔴 核心安全断言
        chk('9 🔴 建议值未预填进下拉框（机器不许替人拍板）',
            probe['sel'] == '', '下拉框当前值=%r' % probe['sel'])

        clicked = await js(
            "(async()=>{const b=document.querySelector('#dwSuptagAccept');"
            "if(!b) return {noBtn:true}; b.click();"
            "await new Promise(r=>setTimeout(r,1800));"
            "const sel=document.querySelector('#dwSuptag');"
            "const row=document.querySelector('#dwSuptagAiRow');"
            "return {sel:sel?sel.value:null,"
            " text:row?row.textContent.replace(/\\s+/g,' ').trim():'',"
            " btn:!!document.querySelector('#dwSuptagAccept')};})()")
        chk('10 点「采用建议」后标签真的落上去',
            clicked.get('sel') == 'empty_container', clicked)
        chk('11 采用后该行显示「已确认」',
            '已确认' in (clicked.get('text') or ''), clicked.get('text'))
        chk('12 采用后按钮消失（不该重复采用）',
            clicked.get('btn') is False, clicked)

        # 后端复核：确认写进了报告唯一依据那一列
        d = api('/api/photos/u2')
        chk('13 后端 supervision_tag 已写入（报告只认这一列）',
            d.get('supervision_tag') == 'empty_container', d.get('supervision_tag'))
        chk('14 后端标记为人工已确认',
            d.get('sup_tag_confirmed') == 1, d.get('sup_tag_confirmed'))
        chk('15 待确认数从 3 降到 2',
            api('/api/photos/supervision-tags').get('pending_ai') == 2,
            api('/api/photos/supervision-tags').get('pending_ai'))

        chk('16 全程无 JS 异常', not excs,
            [e.get('exception', {}).get('description', '')[:140]
             for e in excs][:3])
        return True


ok = False
try:
    ok = asyncio.run(main())
finally:
    for p in (edge, srv):
        try:
            p.terminate()
            p.wait(timeout=8)
        except Exception:  # noqa: BLE001
            p.kill()
    shutil.rmtree(HOME, ignore_errors=True)
    shutil.rmtree(DBHOME, ignore_errors=True)

print()
print('PASS' if (ok and not fails) else 'FAIL: ' + ', '.join(fails))
sys.exit(0 if (ok and not fails) else 1)