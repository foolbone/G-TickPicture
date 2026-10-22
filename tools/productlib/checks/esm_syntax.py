"""校验 web/static/js/*.js 的 ES module 语法（node --check 需要 .mjs 扩展名）。

用法:
  python -m tools.productlib._check_esm
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(HERE, 'web', 'static', 'js')


def find_node():
    """探测 node —— **别硬编码具体小版本**。

    🔴 曾把 `versions/22.22.2-3/node.exe` 写死，workbuddy 一升级（→ 22.22.2-6）
       两个静态检查就双双 FileNotFoundError，而报错完全指不到「版本号变了」
       —— 看起来像脚本坏了。改成扫目录取最新的一个。
    """
    import glob as _g
    base = r'C:/Users/Bone/.workbuddy/binaries/node/versions'
    hits = sorted(_g.glob(os.path.join(base, '*', 'node.exe')))
    if hits:
        return hits[-1]
    return 'node.exe'          # 交给 PATH 兜底（找不到时 subprocess 的报错更直白）


NODE = find_node()


def main():
    files = sorted(f for f in os.listdir(JS_DIR) if f.endswith('.js'))
    tmp = tempfile.mkdtemp(prefix='esmchk_')
    ok, bad = [], []
    for f in files:
        src = os.path.join(JS_DIR, f)
        dst = os.path.join(tmp, f[:-3] + '.mjs')
        shutil.copyfile(src, dst)
        r = subprocess.run([NODE, '--check', dst], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode == 0:
            ok.append(f)
            print('[ OK ] %-14s %6d bytes' % (f, os.path.getsize(src)))
        else:
            bad.append(f)
            print('[FAIL] %-14s' % f)
            out = (r.stdout or '') + (r.stderr or '')
            for line in out.strip().splitlines()[:12]:
                print('       ' + line)
    shutil.rmtree(tmp, ignore_errors=True)
    print('----')
    print('PASS %d / FAIL %d / TOTAL %d' % (len(ok), len(bad), len(files)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

