# -*- coding: utf-8 -*-
"""
server.py -- 产品库 Web 界面（应用装配 + 入口）

启动：
    python -m tools.productlib.server
    python -m tools.productlib.server --port 8765
浏览器打开 http://127.0.0.1:8765

═══════════════════════════════════════════════════════════════════════
结构
═══════════════════════════════════════════════════════════════════════
本文件只做「装配」：建 app、挂静态目录、include 路由包、提供 CLI 入口。
具体接口按业务域放在 routes/ 下：

    routes/pages.py      页面外壳
    routes/stats.py      概览
    routes/products.py   产品清单
    routes/photos.py     照片导入/浏览
    routes/govern.py     治理启停与进度
    routes/review.py     人工关联
    routes/discover.py   发现新产品
    routes/merge.py      合并建议 + 标准库落盘
    routes/report.py     报告素材
    routes/standard.py   标准图
    routes/settings.py   多模态配置

共享的（路径常量 / DB 连接 / 治理后台任务 / 照片输出结构）在 deps.py。

═══════════════════════════════════════════════════════════════════════
设计上的三条硬约束
═══════════════════════════════════════════════════════════════════════
1. 关联只能经 store.link() 写入。Web 层不直接 INSERT links ——
   与 APP 侧「归属只能由 AssignService 写」是同一条原则。
2. 治理跑在后台线程，线程内自建 sqlite 连接（sqlite 连接默认不能跨线程）。
3. 缩略图必缓存。原图 3072x4096，每次现开会把页面拖垮。
"""
import argparse
import os
import sys
import threading
import webbrowser

# 路径统一走 paths.py（打包成 exe 后 __file__ 上溯算法失效）
_BOOTSTRAP_ROOT = getattr(sys, 'frozen', False) and None or \
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BOOTSTRAP_ROOT and _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

from tools.productlib import paths, store, vision  # noqa: E402
from tools.productlib.deps import STATIC_DIR  # noqa: E402
from tools.productlib.routes import api_router  # noqa: E402

ROOT = paths.app_root()

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

APP_VERSION = '0.18.7'
app = FastAPI(title='集刻 产品库', version=APP_VERSION)


@app.get('/api/ping', include_in_schema=False)
def _ping():
    """身份核验：端口上跑的是不是本产品库。

    为什么需要：8765 被别的软件占着时，我们自动换端口，但**老板的浏览器
    可能还开着旧地址**（或书签/收藏指向旧端口），看到的会是那个软件的页面
    或者连接失败 —— 现象是「产品库打不开」，但真实原因是他没看新地址。
    前端与 cmd 都会用这个端点确认「这个端口后面站的是谁」。
    """
    return {'app': '集刻产品库', 'version': APP_VERSION,
            'data_dir': paths.data_dir(), 'mode': 'frozen' if paths.IS_FROZEN else 'dev'}


# 静态文件禁用强缓存 —— 前端 JS/CSS 频繁迭代，浏览器缓存旧文件会导致
# "新功能不起作用"的假象。no-store 表示每次都重新下载。
@app.middleware('http')
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# 前端已拆成外置资源（app.css + js 模块），静态目录必须挂上
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')
app.include_router(api_router)


def _say(msg):
    """启动日志输出。

    ⚠️ 必须 flush：stdout 在管道/重定向时是块缓冲的，不 flush 的话
    **黑窗口里的提示要等缓冲区满才出现** —— 老板看到的是「双击后一片空白，
    以为没反应」，而端口已经换好了。启动提示的价值全在「立刻可见」。
    """
    try:
        print(msg, flush=True)
    except (IOError, ValueError):   # 窗口被关掉等情况，不该因此崩掉
        pass


def _port_busy(port, host='127.0.0.1', timeout=0.3):
    """这个端口有没有被占用。

    判据用「能不能连上」而不是 bind：Windows 上 8765 常被别的软件占着
    （IDE、数据库客户端、各种 HTTP 服务），实测连 0.3s 内能连上就是占用。
    连不上 = 空闲（有一瞬间连不上但其实是半开连接的情况，交给真正 bind 时报错）。
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def _pick_port(preferred, host='127.0.0.1', tries=24):
    """找一个空闲端口：preferred 被占就往后找。

    🔴 为什么要做在 server 里而不是靠外面的 .ps1：老板**直接双击 exe**
    是最常见的启动方式，这条路根本不经过脚本 —— 只在脚本里探测等于没做。
    端口冲突也不是"异常"而是常态（另一台电脑上 8765 很可能已经被别的软件占着）。
    """
    if not _port_busy(preferred, host):
        return preferred, False
    for p in range(preferred + 1, preferred + tries):
        if not _port_busy(p, host):
            return p, True
    return None, True


def main():
    ap = argparse.ArgumentParser(description='集刻 产品库 Web 界面')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--upgrade', action='store_true',
                    help='不启动服务，只跑「备份→升级→自检」然后退出'
                         '（绿色包里没有 Python，靠 exe 自己跑升级流程）')
    ap.add_argument('--dry-run', action='store_true',
                    help='配合 --upgrade：只报告将要做什么，不改任何东西')
    # --data 必须在**解析前**落到 env 再以子进程重启 —— 路径常量在 import 期
    # 就定死，事后 reload 只会造出「库在新目录、缩略图还在旧目录」的半迁移状态。
    ap.add_argument('--data', default='',
                    help='数据目录（默认 exe 同级 data/；打包后用它换库的位置）')
    a = ap.parse_args()

    # ── 升级模式：不启动服务，只跑升级流程（绿色包里没有 Python，
    #    所以 `集刻产品库.exe --upgrade` 必须能自己干这件事）──────────
    if a.upgrade:
        try:
            from tools.productlib import upgrade as _up
        except ImportError:
            _say('[FAIL] 升级模块没打进包里（构建时漏了 upgrade.py）')
            return 2
        argv_up = ['--data', a.data or paths.data_dir()]
        if a.dry_run:
            argv_up.append('--dry-run')
        return _up.main(argv_up) or 0

    if a.data:
        os.environ['PL_HOME'] = os.path.abspath(a.data)
        import subprocess
        argv = [x for x in sys.argv if x != '--data' and not x.startswith(a.data)]
        # ⚠️ 必须去掉 --data 再 exec，否则子进程又看到它 → 又 exec → 无限重启
        _say('[ .. ] 以数据目录 %s 重启…' % os.path.abspath(a.data))
        raise SystemExit(subprocess.call([sys.executable] + argv))

    # ── 启动即无感升级 ──────────────────────────────────────────────────
    # 老板只要「解压新包 → 拷 data\\ → 双击启动产品库.cmd」就完成升级，
    # 不用再单独跑升级助手。关键：只在**确实待迁移**时才备份+迁移+核对
    # （needs_migration 判 False 就直接跳过），否则每次启动都复制一份 data\\
    # 备份会很快塞满磁盘。失败则**拒绝启动**（带着坏库跑比不跑更糟），
    # 并提示用刚做的备份还原。
    try:
        from tools.productlib import upgrade as _up
    except ImportError:
        _say('[FAIL] 升级模块没打进包里（构建时漏了 upgrade.py）')
        return 2
    _dd = a.data or paths.data_dir()
    try:
        res = _up.auto_upgrade(_dd)
    except Exception as _e:
        _say('[FAIL] 启动前自动升级异常：%s' % _e)
        return 3
    if res.get('failed'):
        _say('[FAIL] 库自动升级未通过：%s' % res.get('error', ''))
        if res.get('backup'):
            _say('       请用备份还原：%s' % res['backup'])
        return 3
    if res.get('needed'):
        _say('[ OK ] 已自动升级库结构（升级前已备份到：%s）' % res.get('backup'))

    port, moved = _pick_port(a.port, a.host)
    if port is None:
        # 到这一步已经是极端情况：连着 24 个端口都被占。给能照做的提示，
        # 而不是抛英文的 [Errno 98] Address already in use。
        exe_name = (os.path.basename(sys.argv[0]) if getattr(sys, 'frozen', False)
                    else '集刻产品库.exe')
        _say('')
        _say('[FAIL] 端口 %d ~ %d 都被占用了，没法启动。' % (a.port, a.port + 23))
        _say('[ .. ] 三种办法，任选一个：')
        _say('    1) 关掉占用这些端口的软件（最常见：IDE / 数据库客户端 / 别的服务）')
        _say('    2) 换端口启动：在命令行跑  %s --port 9000' % exe_name)
        _say('    3) 告诉我端口号，我把它改成默认值')
        _say('')
        return 2

    url = 'http://%s:%d/' % (a.host, port)
    p = paths.describe()
    if moved:
        _say('[WARN] 端口 %d 被占用了（多半不是产品库），已自动改用 %d' % (a.port, port))
        _say('[ .. ] 浏览器会打开下面这个地址；旧地址打不开是正常的。')
    _say('[ OK ] 产品库已启动: %s' % url)
    _say('[ OK ] 运行模式: %s' % p['mode'])
    _say('[ OK ] 数据目录: %s' % p['data_dir'])
    _say('[ OK ] db: %s' % store.DEFAULT_DB)
    _say('[ .. ] vision: %s' % ('enabled' if vision.enabled() else 'NOT configured (degraded)'))
    _say('[ .. ] 关掉本窗口 = 关闭产品库')
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    import uvicorn
    try:
        uvicorn.run(app, host=a.host, port=port, log_level='warning')
    except OSError as e:
        # 探测与真正 bind 之间有竞态（别的程序刚好在这瞬间抢了端口）。
        # 英文报错老板看不懂，这里给中文 + 可操作的下一步。
        exe_name = (os.path.basename(sys.argv[0]) if getattr(sys, 'frozen', False)
                    else '集刻产品库.exe')
        _say('')
        _say('[FAIL] 启动失败：端口 %d 绑定失败（%s）' % (port, e))
        _say('[ .. ] 换个端口再试：  %s --port %d' % (exe_name, port + 1))
        _say('')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main() or 0)
