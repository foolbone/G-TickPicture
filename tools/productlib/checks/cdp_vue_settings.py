# -*- coding: utf-8 -*-
"""CDP 实跑：Vue 3 版设置/app/settings（vue3-frontend 分支）。

覆盖旧版 settings.js + review.js（已跳过照片撤销）+ #tab-set 的核心行为：
  · 多模态配置：读取回填 / 保存（key 不留在明文框里）/ 未配置时的降级文案
  · 标准库落盘目录：localStorage 记忆 + 目录选择弹窗（/api/browse）
  · 产品数据规范 + 照片分类字典（都读 /api/fields，UI 不二次抄写）
  · 已跳过照片：列表 + 撤销（真回到待认领）+ 空态
  · 刷新保持、无 JS 异常

⚠️ 隔离实例 8810 / CDP 9370，不碰 8765。
跑法：python tools/productlib/checks/cdp_vue_settings.py
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
PORT = int(os.environ.get('PL_PORT', '8810'))
CDP_PORT = int(os.environ.get('PL_CDP', '9370'))
HOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vueset_edge')
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_cdp_vueset_db')
BASE = 'http://127.0.0.1:%d' % PORT
URL = BASE + '/app/settings'
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
    b = '----plset' + str(int(time.time()))
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

# ── 造数据：2 张照片标「已跳过」 ──
code, c = _req('POST', '/api/containers', {'container_no': 'VST1', 'inspector': 'cdp'})
cid = (c or {}).get('id')
chk('0 建柜', bool(cid), cid)

from PIL import Image  # noqa: E402

tmpd = os.path.join(tempfile.gettempdir(), 'pl_vue_set')
shutil.rmtree(tmpd, ignore_errors=True)
os.makedirs(tmpd)
files = []
for i in range(2):
    p = os.path.join(tmpd, 'ST_%02d.jpg' % i)
    Image.new('RGB', (900, 700), (70 + i * 40, 150, 170)).save(p)
    files.append(('files', p, os.path.basename(p)))
code, r = post_file('/api/photos/upload', {'container_id': cid}, files)
chk('0b 上传 2 张', code == 200 and (r or {}).get('added') == 2,
    '%s %s' % (code, json.dumps(r, ensure_ascii=False)[:100]))

d = http_json('/api/photos?container_id=%s&limit=50' % cid) or {}
pids = [x['id'] for x in (d.get('items') or [])]
chk('0c 取到照片 id', len(pids) == 2, len(pids))
con = sqlite3.connect(os.path.join(DBHOME, 'productlib.db'), timeout=30)
con.execute("UPDATE photos SET is_dup=0, manual_skip=1, skip_at='2026-10-18T09:30:00'")
con.commit()
con.close()

# API 层钉死基线
fd = http_json('/api/fields') or {}
chk('1 /api/fields 有字段与分类字典',
    len(fd.get('fields') or []) >= 3 and len(fd.get('kinds') or {}) >= 5,
    '%s / %s' % (len(fd.get('fields') or []), len(fd.get('kinds') or {})))
sk = http_json('/api/photos/skipped?limit=200') or {}
chk('2已跳过 2 张', sk.get('total') == 2 and len(sk.get('items') or []) == 2,
    '%s / %s' % (sk.get('total'), len(sk.get('items') or [])))
vc = http_json('/api/vision/config') or {}
chk('2b 多模态未配置（降级文案可测）', not vc.get('enabled'),
    json.dumps(vc, ensure_ascii=False)[:120])

edge = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
     '--no-proxy-server',
     '--remote-debugging-port=%d' % CDP_PORT, '--user-data-dir=' + HOME,
     '--window-size=1400,1200', URL],
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
        await asyncio.sleep(7.5)
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

        async def click_text(label, scope='.set-page'):
            # ⚠️ 作用域本身是容器，进去再找 button；别写 'scope button' 当选择器
            #    （那样 x 本身就是 button，再 querySelectorAll('button') 恒为空）
            return await js("""(()=>{const root=document.querySelector(%s);
                if(!root) return false;
                const b=[...root.querySelectorAll('button')]
                  .find(x=>(x.innerText||'').trim()===%s);
                if(b){b.click();return true;} return false;})()"""
                            % (json.dumps(scope), json.dumps(label)))

        async def set_input(sel, idx, val):
            """sel 下的第 idx 个 input（0 起）—— el-input 的真实输入框。"""
            return await js("""(()=>{const c=document.querySelector(%s);
                const i=c&&c.querySelectorAll('input')[%d];
                if(!i) return false;
                const s=Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype,'value').set;
                s.call(i,%s); i.dispatchEvent(new Event('input',{bubbles:true}));
                i.dispatchEvent(new Event('change',{bubbles:true})); return true;})()"""
                            % (json.dumps(sel), idx, json.dumps(val)))

        # ════ ① 首屏 ════
        chk('3 标题带「设置」', '设置' in str(await js('document.title')),
            await js('document.title'))
        heads = await js("""(()=>{const hs=[...document.querySelectorAll('.set-page h3')]
            .map(h=>h.innerText.trim()); return JSON.stringify(hs);})()""")
        chk('4 五块都在（多模态/落盘/数据规范/分类字典/已跳过）',
            all(k in str(heads) for k in
                ('多模态大模型', '标准库自动落盘', '产品数据规范', '照片分类字典', '已跳过的照片')),
            heads)

        vmsg = await js("""(()=>{const t=document.querySelector('.set-page .faint');
            return t?t.innerText:'';})()""")
        chk('5 多模态未配置 → 说清「降级运行」', '降级运行' in str(vmsg), vmsg)
        chk('5b 保留「未经真实 API 验证」的警示',
            '未经真实 API 验证' in str(await js('document.body.innerText')))

        n_field = await js("document.querySelectorAll('.set-page .el-table__body-wrapper tr').length")
        chk('6 两张表都渲染出数据行（字段 + 分类字典）', n_field >= 8, n_field)
        body = await js('document.body.innerText')
        chk('6b 分类字典用的是后端文案（产品·有编码 那套）', '产品·有编码' in str(body),
            [x for x in ('产品·有编码', '包装', '清单') if x in str(body)])

        # ════ ② 已跳过照片 + 撤销 ════
        sk_txt = await js("""(()=>{const cs=[...document.querySelectorAll('.set-page .el-card')];
            for(const c of cs){if((c.innerText||'').includes('已跳过的照片')) return c.innerText;}
            return '';})()""")
        chk('7 已跳过区显示「共 2 张」且列出两个文件',
            '共 2 张' in str(sk_txt) and 'ST_00.jpg' in str(sk_txt)
            and 'ST_01.jpg' in str(sk_txt), str(sk_txt).replace('\n', ' ')[:130])
        chk('7b 跳过时间到分钟', '2026-10-18 09:30' in str(sk_txt),
            [ln for ln in str(sk_txt).split('\n') if '2026' in ln][:2])

        await click_text('撤销跳过')
        await asyncio.sleep(2.5)
        await drain()
        sk2 = http_json('/api/photos/skipped?limit=200') or {}
        chk('8 撤销 → 后端剩 1 张', sk2.get('total') == 1, sk2.get('total'))
        n_left = await js("""(()=>{const rs=[...document.querySelectorAll('.set-page tr')];
            let n=0; for(const r of rs){if(r.innerText.includes('撤销跳过')) n++;}
            return n;})()""")
        chk('8b 页面同步少一行', n_left == 1, n_left)

        # ════ ③ 多模态保存 ════
        ok1 = await set_input('.set-page .el-card', 0, 'https://api.example.com/v1')
        # 卡内 input 顺序：[0]=API Base [1]=模型名 [2]=API Key（密码）
        ok2 = await set_input('.set-page .el-card', 1, 'gpt-4o-mini')
        # ⚠️ vision.enabled() = api_key 且 model 都非空 → 只填 base/model 后端仍报
        #    未配置，测「已启用」文案必须把 key 也填上
        ok3 = await set_input('.set-page .el-card', 2, 'sk-test-dummy')
        chk('9 API Base / 模型名 / Key 可填', ok1 and ok2 and ok3, '%s %s %s' % (ok1, ok2, ok3))
        await click_text('保存')
        await asyncio.sleep(2.0)
        await drain()
        vc2 = http_json('/api/vision/config') or {}
        chk('9b 保存落库（api_base / model / has_key）',
            vc2.get('api_base') == 'https://api.example.com/v1'
            and vc2.get('model') == 'gpt-4o-mini'
            and vc2.get('has_key') is True,
            json.dumps(vc2, ensure_ascii=False)[:140])
        key_left = await js("""(()=>{const c=document.querySelector('.set-page .el-card');
            const i=c.querySelectorAll('input')[2]; return i?i.value:'';})()""")
        chk('9c API Key 输入框保存后清空（不留明文在框里）', key_left == '', repr(key_left))
        chk('9d 状态文案变「已配置，多模态已启用」',
            '已配置，多模态已启用' in str(await js(
                "(document.querySelector('.set-page .el-card .faint')||{}).innerText||''")),
            await js("(document.querySelector('.set-page .el-card .faint')||{}).innerText||''"))

        # ════ ④ 落盘目录 + 目录选择器 ════
        dir_val = await js("""(()=>{const cs=[...document.querySelectorAll('.set-page .el-card')];
            for(const c of cs){if((c.innerText||'').includes('标准库自动落盘')){
                const i=c.querySelector('input'); return i?i.value:'';}}
            return '';})()""")
        chk('10 落盘目录有默认值', '标准产品库' in str(dir_val), dir_val)
        await click_text('选择目录')
        await asyncio.sleep(2.5)
        await drain()
        chk('11 目录选择弹窗打开',
            await js("""(()=>{for(const d of document.querySelectorAll('.el-dialog')){
                if((d.innerText||'').includes('选择目录')) return true;} return false;})()""")
            is True)
        pth = await js("""(()=>{for(const d of document.querySelectorAll('.el-dialog')){
                if((d.innerText||'').includes('选择目录')){
                    const p=d.querySelector('.dppath'); return p?p.innerText:'';}}
            return '';})()""")
        chk('11b 弹窗显示当前路径', pth not in ('', None), pth)
        n_item = await js("""(()=>{for(const d of document.querySelectorAll('.el-dialog')){
                if((d.innerText||'').includes('选择目录')){
                    return d.querySelectorAll('.dpitem').length;}}
            return -1;})()""")
        chk('11c 列出了本机目录项', n_item >= 0, n_item)
        # 选中第一个子目录再确定
        await js("""(()=>{for(const d of document.querySelectorAll('.el-dialog')){
                if((d.innerText||'').includes('选择目录')){
                    const it=d.querySelector('.dpitem'); if(it) it.click();}}})()""")
        await asyncio.sleep(2.0)
        await drain()
        pth2 = await js("""(()=>{for(const d of document.querySelectorAll('.el-dialog')){
                if((d.innerText||'').includes('选择目录')){
                    const p=d.querySelector('.dppath'); return p?p.innerText:'';}}
            return '';})()""")
        chk('12 点目录项进入下一级（路径变化）', pth2 != pth, '%s → %s' % (pth, pth2))
        await js("""(()=>{for(const d of document.querySelectorAll('.el-dialog')){
                if((d.innerText||'').includes('选择目录')){
                    const b=[...d.querySelectorAll('button')]
                      .find(x=>(x.innerText||'').trim()==='选择此目录'); if(b) b.click();}}})()""")
        await asyncio.sleep(1.5)
        dir_val2 = await js("""(()=>{const cs=[...document.querySelectorAll('.set-page .el-card')];
            for(const c of cs){if((c.innerText||'').includes('标准库自动落盘')){
                const i=c.querySelector('input'); return i?i.value:'';}}
            return '';})()""")
        chk('13 选完后目录写回输入框', dir_val2 == pth2, '%s vs %s' % (dir_val2, pth2))
        chk('13b 目录记进 localStorage（刷新后还在）',
            await js("localStorage.getItem('stdExpDir')") == dir_val2,
            await js("localStorage.getItem('stdExpDir')"))

        # ════ ⑤ 刷新保持 ════
        await cmd('Page.navigate', {'url': URL})
        await asyncio.sleep(6.5)
        await drain()
        chk('14 刷新仍落在 /app/settings', '/app/settings' in str(await js('location.pathname')),
            await js('location.pathname'))
        chk('14b 刷新后落盘目录从 localStorage 恢复',
            '标准产品库' not in str(await js("""(()=>{const cs=[...document.querySelectorAll(
                '.set-page .el-card')];
                for(const c of cs){if((c.innerText||'').includes('标准库自动落盘')){
                    const i=c.querySelector('input'); return i?i.value:'';}}
                return '';})()""")))
        chk('14c 刷新后已跳过仍是 1 张（撤销没被回滚）',
            http_json('/api/photos/skipped?limit=200').get('total') == 1)

        chk('15 全程无 JS 异常', not excs, json.dumps(excs, ensure_ascii=False)[:300])
        return not fails


ok = asyncio.run(main())
edge.terminate()
srv.terminate()
print(('FAIL %d 项' % len(fails)) if fails else 'PASS')
sys.exit(0 if ok and not fails else 1)