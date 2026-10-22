# -*- coding: utf-8 -*-
"""run_server.py —— 打包入口（PyInstaller 的 Analysis 目标）

为什么要有这个文件：平时用 `python -m tools.productlib.server` 启动，但打包成
exe 之后没有「仓库根 + 包」这套源码布局，`-m` 跑不起来。这个文件只做三件事：

    1. 把 sys.path 摆正（开发时能找到 tools/，冻结时能找到被收进包的模块）
    2. 冻结时把 web 资源目录指到 sys._MEIPASS/web（paths 已处理）
    3. 调 server.main()

双击 exe 等价于跑这个文件。
"""
import os
import sys


def _fix_sys_path():
    """让 `from tools.productlib...` 在开发与冻结两种形态下都能工作。

    冻结时 PyInstaller 已经把包注册进 sys.meta_path，正常 import 就行；
    这里主要是照顾**开发直跑** `python tools/productlib/run_server.py` 的情形。
    """
    if getattr(sys, 'frozen', False):
        return
    here = os.path.dirname(os.path.abspath(__file__))       # tools/productlib
    tools_dir = os.path.dirname(here)                       # tools
    repo_root = os.path.dirname(tools_dir)                  # 仓库根
    for p in (repo_root, tools_dir):
        if p not in sys.path:
            sys.path.insert(0, p)


def main():
    _fix_sys_path()
    from tools.productlib.server import main as _main
    _main()


if __name__ == '__main__':
    main()