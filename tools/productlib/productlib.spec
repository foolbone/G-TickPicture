# -*- mode: python ; coding: utf-8 -*-
"""productlib.spec —— PyInstaller 打包配置（2026-10-06）

目标：把产品库打成**免安装绿色包**，拷到别的 Windows 电脑上双击就能用
（对方机器不需要装 Python）。

构建：
    pyinstaller tools/productlib.spec --noconfirm
产物：
    dist/集刻产品库/集刻产品库.exe

关键决策（都是踩过才知道的）
───────────────────────────────────────────────────────────────
1. **onedir 而不是 onefile**
   onefile 每次启动都把 numpy/Pillow/lxml 打包解压到临时目录，冷启动 10~20 秒，
   而且杀毒软件对「自解压 exe」误报率高。onedir 启动 1~2 秒，代价是目录大一些
   （约 250MB），拷机时打个 zip 就行。
2. **datas 收 web/**
   冻结后 web 落在 `sys._MEIPASS/web`（paths.web_dir 的冻结分支），
   所以这里必须把 `tools/productlib/web` 映射到 `web`（去掉两级前缀）。
3. **hiddenimports 收 tools.productlib.\***
   routes/__init__.py 是动态 include_router，PyInstaller 的静态分析可能漏；
   显式列出所有子模块更稳（漏一个 = 那个功能页整块 404）。
4. **build_library 作为顶层模块**
   store.py 里是 `import build_library as BL`（非包导入），必须显式告诉
   PyInstaller 它在 tools/ 下。
5. **excludes 排掉用不到的大包**
   torch/tkinter/matplotlib 这些是科学计算/绘图栈，本项目一个都不用，
   不排掉光它们就是几百 MB。

⚠️ 数据（数据库/照片/报告）**不进包**：落在 exe 同级 data/（paths.data_dir），
用户拷走目录就能带走数据；换机器时把 data/ 一起拷过去即可。
"""
import os

# PyInstaller 的 spec 里 __file__ 指向本 spec 文件本身
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
REPO_ROOT = os.path.dirname(os.path.dirname(SPEC_DIR))
TOOLS_DIR = os.path.join(REPO_ROOT, 'tools')
PL_DIR = os.path.join(TOOLS_DIR, 'productlib')

# ── 前端资源：源码 tools/productlib/web → 包内 web ────────────────
datas = [
    (os.path.join(PL_DIR, 'web'), 'web'),
    # ── Vue 3 新前端构建产物（2026-10-18 改造分支）─────────────
    # routes/app.py 按同层 web-app-dist/ 服务 /app/ 前缀。
    # 🔴 源码在 frontend/（需 Node 构建）；产物入库后打包无需 Node。
    #    产物不存在时（未构建）跳过，不阻断打包。
    *([(os.path.join(PL_DIR, 'web-app-dist'), 'web-app-dist')]
      if os.path.isdir(os.path.join(PL_DIR, 'web-app-dist')) else []),
    # ── 本地小模型（2026-10-17 补）──────────────────────────────
    # usage_cls.onnx + usage_labels.json = govern_classifier 用途二分类。
    # 🔴 不收 = 打包版小模型静默失效、每张监装照都降级打大模型 API。
    #    paths.models_dir() 冻结分支按 _MEIPASS/models 找，键名必须是 'models'。
    #    usage_cls.pth（训练中间权重）刻意不进 datas —— onnx 已含全部推理所需。
    (os.path.join(PL_DIR, 'models'), 'models'),
]

# ── PP-OCR 模型（2026-10-06 补）────────────────────────────────
# 🔴 不收进来 = 打包版的治理 OCR 100% 失败、编码读不出来。30MB 值得。
#    位置对齐 pc_ocr_probe._find_assets() 的优先级 2/3（exe 同级 / _MEIPASS）。
_OCR_SRC = os.path.join(REPO_ROOT, 'app', 'android', 'app', 'src', 'main',
                        'assets', 'ppocr')
if os.path.isdir(_OCR_SRC):
    datas.append((_OCR_SRC, 'ocr'))
else:
    raise SystemExit(
        '找不到 OCR 模型目录：%s\n'
        '它从 app/android 的 assets 借用的。没有它，打包版的图片治理'
        '无法读出编码（OCR 整段不可用）。' % _OCR_SRC)

# ── 源码模块：productlib 包全量收（动态路由 + 少列一个就整页 404）──
hiddenimports = [
    'tools.productlib.paths',
    'tools.productlib.schema',
    'tools.productlib.store',
    'tools.productlib.pipeline',
    'tools.productlib.report_gen',
    'tools.productlib.vision',
    'tools.productlib.deps',
    'tools.productlib.upgrade',      # exe --upgrade 子命令要用
    'build_library',                       # store.py 里的顶层非包导入
    'uvicorn.logging',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on',
    # 报表/表格/图片
    'docx', 'docx.shared', 'docx.oxml.ns',
    'openpyxl', 'openpyxl.cell._writer',
    'xlrd',
    'PIL.Image', 'PIL.ImageOps', 'PIL.ImageFile', 'PIL.JpegImagePlugin',
    'PIL.PngImagePlugin', 'PIL.TiffImagePlugin', 'PIL.WebPImagePlugin',
    'lxml', 'lxml.etree', 'lxml._elementpath',
]

excludes = [
    # 科学计算/绘图栈：本项目一个都不用，排掉省几百 MB
    'torch', 'torchvision', 'tensorflow', 'jax', 'matplotlib', 'scipy',
    'pandas', 'IPython', 'jupyter', 'notebook',
    # GUI 栈：这是 Web 服务，不需要 tkinter/Qt
    'tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    # 开发工具
    'pytest', 'setuptools', 'pip', 'wheel', 'pyinstaller',
    'sqlite3.test', 'unittest',
    # 多模态 API 客户端用 requests 就够，不需要这些
    'anthropic', 'openai',
]

a = Analysis(
    [os.path.join(TOOLS_DIR, 'productlib', 'run_server.py')],
    pathex=[REPO_ROOT, TOOLS_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='集刻产品库',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # ⚠️ 不要开 UPX：被杀软误报重，且出问题时无法排查
    console=True,            # 要 console：老板能看到「数据存哪」的启动日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,               # 有图标再填 .ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='集刻产品库',
)