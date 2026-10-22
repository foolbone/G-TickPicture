# -*- coding: utf-8 -*-
"""Web 前端静态体检（三个维度）：

  1. DOM 契约 —— JS 里引用的 $('#id') 必须在 index.html 里真实存在
                 （前端已无内联脚本，所以这里扫 static/js/*.js）
  2. 端点契约 —— 前端 fetch('/api/xxx') 的每一条，后端必须有对应路由
                 （后端已拆成 routes/ 包，所以这里递归扫整个包）
  3. 语法     —— 每个 js 模块交给 node --check 过一遍（ES module 需 .mjs）

⚠️ 前端/后端再拆分时，本脚本必须同步改扫描范围，否则会退化成「0 项检查」的假绿。
"""
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')
HTML = os.path.join(WEB, 'index.html')
JS_DIR = os.path.join(WEB, 'static', 'js')
ROUTES_DIR = os.path.join(ROOT, 'routes')


def _find_node():
    """探测 node —— **别硬编码具体小版本**（10-07 踩过：写死 22.22.2-3，
    workbuddy 升级到 22.22.2-6 后两个静态检查双双 FileNotFoundError，
    报错完全指不到「版本号变了」）。扫目录取最新的一个。"""
    hits = sorted(glob.glob(
        r'C:/Users/Bone/.workbuddy/binaries/node/versions/*/node.exe'))
    return hits[-1] if hits else 'node.exe'


NODE = _find_node()

html = io.open(HTML, encoding='utf-8').read()
js_files = sorted(glob.glob(os.path.join(JS_DIR, '*.js')))

# ── 模块闭包：从 main.js 出发沿 import 边走到全部真实加载的模块 ──
# merge.js 这类「文件还在、但没人 import」的死模块不参与契约核对 ——
# 它引用的 id 后端页面根本没有，把它算进来只会制造永远修不掉的假红。
_by_name = {os.path.basename(f): f for f in js_files}
closure = set()
stack = ['main.js']
while stack:
    cur = stack.pop()
    if cur in closure or cur not in _by_name:
        continue
    closure.add(cur)
    for m in re.finditer(r"""(?:from\s+|import\s+)['"](\./)?([\w.-]+\.js)['"]""",
                         io.open(_by_name[cur], encoding='utf-8').read()):
        stack.append(m.group(2))

js = '\n;\n'.join(io.open(_by_name[m], encoding='utf-8').read() for m in sorted(closure))

# ── 1. id 引用核对 ──
ids = set(re.findall(r'\bid="([^"]+)"', html))
# JS 用 innerHTML 动态生成的节点也算存在；它们同样是「有主」的 id。
# 两处来源：innerHTML 里的 id="xxx" 字面量，以及 dlg.id = 'xxx' 属性赋值。
dyn_ids = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', js))
dyn_ids |= set(re.findall(r"""\.id\s*=\s*['"]([A-Za-z0-9_-]+)['"]""", js))
ids |= dyn_ids
# JS 里动态 createElement 追加的节点不算缺失：只核对 $('#xxx') / getElementById
# ⚠️ 引号要四写全：单引号 / 双引号 / 反引号 —— 少一种就是「0 项检查」的假绿
#   （10-05 探针实证：双引号写法漏检，加了假 id 检查器照样 PASS）。
used = set(re.findall(r"""\$\(\s*['"`]#([A-Za-z0-9_-]+)['"`]""", js))
used |= set(re.findall(r"""\$\$\(\s*['"`]#([A-Za-z0-9_-]+)""", js))
used |= set(re.findall(r"""getElementById\(\s*['"]([A-Za-z0-9_-]+)['"]""", js))
# if($('#x')) 是「探测这个 id 存不存在」，不是「使用」 —— 探测失败的分支本来
# 就设计了空转（如 products.js 的 pSearch）。把它当使用会制造假红。
used -= set(re.findall(r"if\s*\(\s*\$\('#([A-Za-z0-9_-]+)'\)\s*\)", js))
# 前缀拼接：'#ctF_'+k 这类截出来的 `ctF_`（_ 结尾）是动态前缀，
# 运行时是 ctF_seal_no 这样的真 id —— 与既有 `-` 结尾的待遇一致。
missing = sorted(u for u in used if u not in ids and not u.endswith('-') and not u.endswith('_'))
print('module closure =', len(closure), '个 |', ', '.join(sorted(closure)))
print('ids in html    =', len(set(re.findall(r'\bid="([^"]+)"', html))),
      '+ js 动态', len(dyn_ids))
print('ids used in js =', len(used))
print('MISSING        :', missing if missing else 'none')

# ── 2. 端点交叉核对 ──
fe = sorted(set(re.findall(r"api\(\s*[`'](/api/[^`']*)", js)))
fe += sorted(set(re.findall(r"api\(\s*'([^']*)'\s*\+", js)))
fe = [re.sub(r'\$\{[^}]*\}', '{}', p.split('?')[0]) for p in fe]
srv = ''
for p in [os.path.join(ROOT, 'server.py')] + sorted(glob.glob(os.path.join(ROUTES_DIR, '*.py'))):
    if os.path.exists(p):
        srv += io.open(p, encoding='utf-8').read()
routes = set()
for m in re.finditer(r"@(?:app|router)\.(get|post|patch|delete|put)\(\s*'([^']+)'", srv):
    routes.add(re.sub(r'\{[^}]*\}', '{}', m.group(2)))


def has_route(p):
    if p in routes:
        return True
    pre = p.rstrip('/')
    return any(r.rstrip('/').startswith(pre) for r in routes)


no_route = sorted(set(p for p in fe if p.startswith('/api/') and not has_route(p)))
print('backend routes =', len(routes))
print('fe endpoints   =', len(set(fe)))
print('NO BACKEND     :', no_route if no_route else 'none')

# ── 3. node --check（逐个模块，ES module 语法需要 .mjs 后缀）──
tmp = tempfile.mkdtemp(prefix='pl_web_')
bad = []
for f in js_files:
    dst = os.path.join(tmp, os.path.basename(f)[:-3] + '.mjs')
    shutil.copyfile(f, dst)
    r = subprocess.run([NODE, '--check', dst], capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode != 0:
        bad.append(os.path.basename(f))
        print('  [FAIL]', os.path.basename(f), (r.stderr or '').strip().splitlines()[:1])
shutil.rmtree(tmp, ignore_errors=True)
print('node --check   :', 'PASS %d/%d' % (len(js_files) - len(bad), len(js_files)), bad or '')

ok = (not missing) and (not no_route) and (not bad) and bool(ids) and bool(used)
print('RESULT:', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
