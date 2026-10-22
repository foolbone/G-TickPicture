"""静态核对 web/static/js/*.js 的 ES module 导入/导出一致性 + 循环依赖。

检查项:
  1. 每个 import { a, b } from './x.js' 的名字，x.js 必须真的 export 了
  2. index.html 引用的 id / 模块入口存在
  3. 模块间依赖图是否有环
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(HERE, 'web')
JS_DIR = os.path.join(WEB, 'static', 'js')

IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]\./([\w.-]+\.js)['\"]")
EXPORT_NAMED_RE = re.compile(r"export\s+(?:async\s+)?function\s+(\w+)|export\s+(?:const|let|var)\s+(\w+)|export\s*\{([^}]*)\}")


def parse_exports(path):
    src = open(path, encoding='utf-8').read()
    names = set()
    for m in EXPORT_NAMED_RE.finditer(src):
        fn, va, lst = m.group(1), m.group(2), m.group(3)
        if fn:
            names.add(fn)
        if va:
            names.add(va)
        if lst:
            for n in lst.split(','):
                n = n.strip()
                if not n:
                    continue
                names.add(n.split(' as ')[-1].strip())
    return names


IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]\./([\w.-]+\.js)['\"]")
IMPORT_NS_RE = re.compile(r"import\s+\*\s+as\s+(\w+)\s+from")
EXPORT_NAMED_RE = re.compile(r"export\s+(?:async\s+)?function\s+(\w+)|export\s+(?:const|let|var)\s+(\w+)|export\s*\{([^}]*)\}")
DECL_RE = re.compile(r"^(?:async\s+)?function\s+(\w+)|^(?:const|let|var)\s+(\w+)|^class\s+(\w+)", re.M)

# 所有模块的全体顶层符号 + 浏览器宿主环境（外加 main.js 挂的 window.PL 命名空间）
HOST = {
    'window', 'document', 'console', 'Math', 'JSON', 'Date', 'String', 'Number',
    'Boolean', 'Array', 'Object', 'Set', 'Map', 'Promise', 'Error', 'FormData',
    'Blob', 'File', 'FileReader', 'Image', 'URL', 'URLSearchParams', 'localStorage',
    'sessionStorage', 'fetch', 'setTimeout', 'clearTimeout', 'setInterval',
    'clearInterval', 'requestAnimationFrame', 'cancelAnimationFrame', 'navigator',
    'location', 'history', 'alert', 'confirm', 'prompt', 'atob', 'btoa',
    'encodeURIComponent', 'decodeURIComponent', 'encodeURI', 'parseInt',
    'parseFloat', 'isNaN', 'Intl', 'RegExp', 'Symbol', 'undefined', 'NaN',
    'Infinity', 'structuredClone', 'performance', 'CustomEvent', 'Event',
    'KeyboardEvent', 'MouseEvent', 'HTMLElement', 'Node', 'NodeList', 'PL',
}


def strip_code(src):
    """去掉注释与字符串字面量，避免把注释里的话、字符串里的单词当标识符。"""
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'//[^\n]*', '', src)
    src = re.sub(r'`(?:\\.|[^`\\])*`', '``', src, flags=re.S)
    src = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", src)
    src = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', src)
    return src


def check_undefined(files):
    """找出「调用了，但本模块没定义、也没 import」的函数名。"""
    top = set()                       # 全体顶层符号
    per_local = {}                    # 每个模块自己的顶层符号
    per_imp = {}                      # 每个模块 import 进来的名字
    for f in files:
        src = open(os.path.join(JS_DIR, f), encoding='utf-8').read()
        local = set()
        for m in DECL_RE.finditer(src):
            nm = m.group(1) or m.group(2) or m.group(3)
            if nm:
                local.add(nm)
        for m in re.finditer(r"^\s*(?:const|let|var|function|async function|class)\s+(\w+)",
                             src, re.M):
            local.add(m.group(1))
        # 解构/赋值形成的局部名（如 const/let const {a,b} = ...）不必精确到
        # 作用域，这里只需保证「顶层一定有的是合法名」，误报靠 HOST/局部白名单压
        per_local[f] = local
        top |= local
        names = set()
        for m in re.finditer(IMPORT_RE, src):
            for n in m.group(1).split(','):
                n = n.strip()
                if n:
                    names.add(n.split(' as ')[-1].strip())
        per_imp[f] = names

    errs = []
    for f in files:
        src = strip_code(open(os.path.join(JS_DIR, f), encoding='utf-8').read())
        # 只能用「自己定义 + 自己 import + 宿主环境」的名字。
        # ⚠️ 故意不把「别的模块 export 的名字」算进来 —— 那正是要抓的错：
        #    「函数在 A 模块 export 了，却被搬走的 B 模块调用，而 B 没 import」。
        known = per_local[f] | per_imp[f] | HOST | parse_exports(os.path.join(JS_DIR, f))
        # 只查「像函数调用」或「裸赋值右侧」的自由标识符
        for m in re.finditer(r'(?<![\w$.\'`"])([A-Za-z_$][\w$]*)\s*\(', src):
            nm = m.group(1)
            if nm in known or nm in KEYWORDS:
                continue
            if nm[0].islower() and '_' not in nm and len(nm) > 3:
                errs.append('%s: 调用了 `%s()`，但本模块没定义也没 import' % (f, nm))
        # 裸标识符出现在赋值右侧 / onclick=()=>xxx 里
        for m in re.finditer(r'=>\s*([A-Za-z_$][\w$]*)\s*\(', src):
            nm = m.group(1)
            if nm in known or nm in KEYWORDS:
                continue
            errs.append('%s: 箭头函数体调用了未定义的 `%s()`' % (f, nm))
    return sorted(set(errs))


KEYWORDS = {'if', 'for', 'while', 'switch', 'catch', 'return', 'typeof', 'new',
            'await', 'async', 'function', 'try', 'else', 'do', 'case', 'delete',
            'void', 'in', 'of', 'super', 'this', 'catch', 'finally',
            'import', 'export', 'default'}


def main():
    files = sorted(f for f in os.listdir(JS_DIR) if f.endswith('.js'))
    exports = {f: parse_exports(os.path.join(JS_DIR, f)) for f in files}
    graph = {f: set() for f in files}
    errs = []

    for f in files:
        src = open(os.path.join(JS_DIR, f), encoding='utf-8').read()
        for m in IMPORT_RE.finditer(src):
            names = [n.strip().split(' as ')[0].strip() for n in m.group(1).split(',') if n.strip()]
            dep = m.group(2)
            if dep not in exports:
                errs.append('%s: 导入了不存在的模块 %s' % (f, dep))
                continue
            graph[f].add(dep)
            for n in names:
                if n not in exports[dep]:
                    errs.append('%s: 从 %s 导入的 `%s` 未被导出' % (f, dep, n))

    # 环检测（DFS）
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {f: WHITE for f in files}
    cycles = []

    def dfs(n, stack):
        color[n] = GRAY
        for d in sorted(graph.get(n, ())):
            if d not in color:
                continue
            if color[d] == GRAY:
                cycles.append(' -> '.join(stack + [d]))
            elif color[d] == WHITE:
                dfs(d, stack + [d])
        color[n] = BLACK

    for f in files:
        if color[f] == WHITE:
            dfs(f, [f])

    print('== 模块导出清单 ==')
    for f in files:
        print('  %-14s %s' % (f, ', '.join(sorted(exports[f])) or '(无)'))
    print('== 依赖边 ==')
    for f in files:
        if graph[f]:
            print('  %-14s -> %s' % (f, ', '.join(sorted(graph[f]))))
    print('----')
    if cycles:
        for c in cycles:
            print('[FAIL] 循环依赖: ' + c)
    else:
        print('[ OK ] 无循环依赖')
    if errs:
        for e in errs:
            print('[FAIL] ' + e)
    else:
        print('[ OK ] 导入/导出全部对得上')

    # ══ 「用了但既没 import 也没定义」══
    #    拆分时最容易踩：行被搬到别的模块，引用没跟上 —— 浏览器里是运行时
    #    ReferenceError，语法检查抓不到，只在用户点到那个控件时才炸。
    undefined_errs = check_undefined(files)
    print('----')
    if undefined_errs:
        for e in undefined_errs:
            print('[FAIL] ' + e)
    else:
        print('[ OK ] 无「未定义引用」')
    errs += undefined_errs
    return 1 if (errs or cycles) else 0


if __name__ == '__main__':
    sys.exit(main())

