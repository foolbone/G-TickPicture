# -*- coding: utf-8 -*-
"""paths.py —— 路径与运行模式解析（**唯一真源**）

2026-10-06 为「打包成可分发程序」抽出来的。此前路径散在各处、各算一遍：
  deps.py   ROOT = 仓库根（从 __file__ 上溯三级）
  server.py ROOT = 同上（重复第二遍）
  cli.py    ROOT = 同上（重复第三遍）
  store.py  DATA_DIR / STANDARD_DIR / DEFAULT_DB
打包成 exe 后 `__file__` 在临时解包目录里、仓库根本不存在 —— 三处算法全部失效。
所以统一到本文件：**先判断运行模式，再解析路径**。

三种模式（优先级从高到低）
─────────────────────────────────────────────────────────────
1. 冻结（PyInstaller 打包出的 exe）
   - 资源（web/index.html、web/static/*、schema 模板）在 `sys._MEIPASS`
   - 数据（数据库、缩略图、标准图、报告）在 **exe 同级 data/**  ← 可写、用户看得见
2. 环境变量优先
   - PL_HOME 指定数据根目录
   - PL_DB   直接指定 .db 文件路径
3. 开发（本仓库）
   - 仓库根 = 从本文件上溯三级；数据在 <仓库根>/productlib/data

⚠️ 为什么要能改数据目录：打包的程序默认会落在 exe 旁边，但如果目标机器把
程序放进了 Program Files 或只读介质上，写库会失败。留一个环境变量逃生口
（PL_HOME / PL_DB），比「装到用户目录下某个固定位置」这种假设可靠。
"""
import os
import sys

IS_FROZEN = bool(getattr(sys, 'frozen', False))          # PyInstaller 运行时为 True


def _repo_root():
    """开发模式下的仓库根（本文件在 <仓库根>/tools/productlib/paths.py）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def app_root():
    """程序所在目录（exe 冻结时 = exe 目录；开发时 = 仓库根）。"""
    if IS_FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return _repo_root()


def resource_root():
    """只读资源根（web/ 目录的父目录）。

    冻结时静态文件被打进 `sys._MEIPASS`（PyInstaller 的解包目录，随 exe 生命周期
    存在，不能往里写）。开发时就是仓库根。
    """
    if IS_FROZEN:
        return getattr(sys, '_MEIPASS', app_root())
    return _repo_root()


def data_dir():
    """可写数据根目录。优先级：PL_HOME > 冻结时 exe 同级 data/ > 开发时仓库内。"""
    env = (os.environ.get('PL_HOME') or '').strip()
    if env:
        return os.path.abspath(env)
    if IS_FROZEN:
        return os.path.join(app_root(), 'data')
    return os.path.join(_repo_root(), 'productlib', 'data')


def web_dir():
    """web 目录（index.html 与 static/）。

    ⚠️ 冻结与开发**结构不同**，不能共用一条拼接：
      开发：<仓库根>/tools/productlib/web
      冻结：打包 spec 把 web/ 收到 _MEIPASS/web（见 productlib.spec 的 datas），
            多套一层 tools/productlib 是源码布局的产物，exe 里没有。
    """
    if IS_FROZEN:
        return os.path.join(resource_root(), 'web')
    return os.path.join(_repo_root(), 'tools', 'productlib', 'web')


def static_dir():
    return os.path.join(web_dir(), 'static')


def models_dir():
    """本地小模型目录（govern_classifier 的 ONNX）。

    与 web_dir 同款双分支：
      开发：tools/productlib/models
      冻结：打包 spec 把 models/ 收到 _MEIPASS/models（2026-10-17 补——
            曾经没收，打包版小模型静默失效、全部降级大模型）。
    """
    if IS_FROZEN:
        return os.path.join(resource_root(), 'models')
    return os.path.join(_repo_root(), 'tools', 'productlib', 'models')


def upload_dir():
    return os.path.join(data_dir(), 'uploads')


def thumb_dir():
    return os.path.join(data_dir(), 'thumbs')


def view_dir():
    """详情页/抽屉用的「预览图」缓存目录（长边受限的缩放版，非原图）。

    为什么要有它：抽屉主区原本直接取原图（/img/<id>），真实库单张 3.8~21MB，
    冷加载实测 4.5s —— 左右切换一张卡一次。预览图约 200~400KB，差一个数量级。
    """
    return os.path.join(data_dir(), 'view')


def standard_dir():
    """标准图资产目录（标准产品库上传/裁剪的图）。"""
    return os.path.join(data_dir(), 'standard')


def reports_dir():
    """装柜报告输出目录。"""
    return os.path.join(data_dir(), 'reports')


def db_path():
    """主库文件路径。PL_DB 可直接指定（e2e 隔离库、多项目并行走这条）。"""
    env = (os.environ.get('PL_DB') or '').strip()
    if env:
        return os.path.abspath(env)
    return os.path.join(data_dir(), 'productlib.db')


def ensure_dirs():
    """建好所有可写目录。**幂等**（makedirs exist_ok）。"""
    for d in (data_dir(), upload_dir(), thumb_dir(), view_dir(),
              standard_dir(), reports_dir()):
        os.makedirs(d, exist_ok=True)
    return data_dir()


def describe():
    """给人看的当前路径快照（启动时打印，老板一眼知道数据存哪了）。"""
    return {
        'mode': 'frozen(打包程序)' if IS_FROZEN else 'dev(源码)',
        'app_root': app_root(),
        'resource_root': resource_root(),
        'data_dir': data_dir(),
        'web_dir': web_dir(),
        'db': db_path(),
    }


if __name__ == '__main__':
    import json
    print(json.dumps(describe(), ensure_ascii=False, indent=2))