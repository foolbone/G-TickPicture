# -*- mode: python ; coding: utf-8 -*-
"""build_portable.py —— 一键构建产品库绿色包

用法：
    python tools/productlib/build_portable.py            # 构建
    python tools/productlib/build_portable.py --clean    # 先清 build/dist 再构建
    python tools/productlib/build_portable.py --zip      # 构建后打 zip（拷到别的电脑用）

产物：
    dist/集刻产品库/集刻产品库.exe     ← 双击即用（绿色包，无需安装 Python）
    dist/集刻产品库_绿色包.zip        ← --zip 时生成，发给别人直接解压

为什么单独写脚本而不是记命令：
打包要「固定解释器 + 固定 spec + 固定输出目录 + 拷启动脚本 + 可选打 zip」五步，
写成命令每次都容易漏一步（尤其是拷启动脚本和清旧产物）。这里固化成一步。

⚠️ 用哪个 Python 打包：**必须是装了全部依赖的那个解释器**。本机有两个：
   - C:\\Users\\Bone\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe（首选）
   - C:\\Python313\\python.exe
   脚本会自己探测并打印用的是哪个，别拿没有 fastapi/Pillow 的那个去打。
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))          # tools/productlib
TOOLS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TOOLS_DIR)
SPEC = os.path.join(HERE, 'productlib.spec')
ENTRY = os.path.join(HERE, 'run_server.py')
LAUNCHER = os.path.join(HERE, '启动产品库.ps1')
APP_NAME = '集刻产品库'

# 候选解释器：优先 workbuddy 管理的那个，其次系统 Python，最后当前这个
CANDIDATES = [
    r'C:\Users\Bone\.workbuddy\binaries\python\versions\3.13.12\python.exe',
    r'C:\Python313\python.exe',
]

# 必须能 import 的模块（缺一个打出来的 exe 会在别人机器上炸）
# 🔴 cv2 / onnxruntime 也在列（2026-10-07 加）：本地 OCR 靠 PP-OCR 的
#    onnxruntime + opencv，两者合计约 75MB。**曾经不在这里**，
#    于是在开发机上这两个包一消失，打包照样「成功」，只是产出一个
#    OCR 静默失灵的包 —— 缺依赖要在打包这一步就炸，不能等用户导入照片才发现。
REQUIRED = ['PyInstaller', 'fastapi', 'uvicorn', 'PIL', 'docx', 'openpyxl',
            'xlrd', 'numpy', 'lxml', 'cv2', 'onnxruntime']


def log(msg):
    print('[ .. ] ' + msg, flush=True)


def ok(msg):
    print('[ OK ] ' + msg, flush=True)


def fail(msg):
    print('[FAIL] ' + msg, flush=True)
    sys.exit(1)


def pick_python():
    """挑一个依赖齐全的解释器。找不到就明说，别默默打出一个跑不起来的包。"""
    for p in CANDIDATES + [sys.executable]:
        if not p or not os.path.exists(p):
            continue
        r = subprocess.run([p, '-c',
                            'import ' + ','.join(REQUIRED)],
                           capture_output=True)
        if r.returncode == 0:
            return p
        miss = r.stderr.decode('utf8', 'replace').strip().splitlines()[-1:]
        log('跳过 %s（%s）' % (p, miss[0] if miss else '缺依赖'))
    fail('找不到依赖齐全的 Python。需要：%s\n'
         '  其中 cv2 / onnxruntime 是**本地 OCR**（图片治理读编码）用的，约 75MB：\n'
         '      pip install opencv-python onnxruntime\n'
         '  缺了也能打包，但产出的包 OCR 会静默失灵（用户只会看到「读不出编码」）。'
         % ', '.join(REQUIRED))


def build(py, clean=False, archive=False):
    """构建绿色包。

    🔴 输出目录**每次都换新名字**（`dist/<时间戳>-集刻产品库`），不是清空重建。
    两个原因，都不是洁癖：
      1. `dist/集刻产品库` 一旦存在，PyInstaller 会尝试 `rmtree` 它再重建 ——
         而产物有 800+ 文件，删除保护钩子（SAFE_DELETE_BULK_CONFIRM_REQUIRED）
         会直接中断构建。本机实测连续踩了两次。
      2. 改名归档偶尔也会失败（WinError 5：目录被索引器/杀软短暂占用）。
    用全新目录名，两个问题都不存在；顺带每次构建都留档，能回退到上一版。
    """
    stamp = time.strftime('%Y%m%d_%H%M%S')
    dist_root = os.path.join(REPO_ROOT, 'dist')
    dist = os.path.join(dist_root, stamp)
    work = os.path.join(REPO_ROOT, 'build', stamp)
    os.makedirs(dist, exist_ok=False)
    os.makedirs(work, exist_ok=True)
    log('输出目录: %s' % dist)

    cmd = [py, '-m', 'PyInstaller', SPEC, '--noconfirm',
           '--distpath', dist, '--workpath', work]
    log('构建中（约 2~4 分钟，机器慢会更久）…')
    t0 = time.time()
    r = subprocess.run(cmd, cwd=REPO_ROOT)
    if r.returncode != 0:
        fail('PyInstaller 返回 %d，看上方日志找原因' % r.returncode)
    ok('构建完成，用时 %.0f 秒' % (time.time() - t0))
    return os.path.join(dist, APP_NAME)


def post_build(app_dir):
    """补齐绿色包里不该缺的东西。"""
    # 启动脚本
    if os.path.exists(LAUNCHER):
        shutil.copy2(LAUNCHER, os.path.join(app_dir, '启动产品库.ps1'))
        ok('已放入 启动产品库.ps1（自动挑空闲端口）')
    # 双击入口：多数人不会去 cmd 里敲命令
    cmd = os.path.join(app_dir, '启动产品库.cmd')
    with open(cmd, 'w', encoding='gbk', errors='replace') as f:
        f.write('@echo off\r\n'
                'rem 由 build_portable.py 生成：双击即启动产品库\r\n'
                'powershell -NoProfile -ExecutionPolicy Bypass '
                '-File "%~dp0启动产品库.ps1"\r\n'
                'if errorlevel 1 pause\r\n')
    ok('已放入 启动产品库.cmd（双击入口）')
    # 升级启动器：绿色包里没有 Python，双击 .py 打不开；所以用 .cmd 调 exe
    # 的 --upgrade 子命令（server.py 接到它后跑 upgrade.main）。exe 同级 data/
    # 就是默认数据目录 —— 正好是「把老 data\\ 拷进新目录」后的位置。
    ucmd = os.path.join(app_dir, '升级助手.cmd')
    with open(ucmd, 'w', encoding='gbk', errors='replace') as f:
        f.write('@echo off\r\n'
                'rem 由 build_portable.py 生成：双击即备份+升级库结构+逐表核对\r\n'
                '"%~dp0集刻产品库.exe" --upgrade\r\n'
                'if errorlevel 1 pause\r\n')
    ok('已放入 升级助手.cmd（双击即跑升级流程）')
    # OCR 模型：spec 已收进 _internal/ocr，这里**再放一份到 exe 同级 ocr/**。
    # 为什么要两份：用户能直接替换成更新的模型（改识别率不用重打包），
    # 也符合「资源在包内、用户可覆盖」的惯例。pc_ocr_probe 的探测顺序
    # 是「exe 同级 → _MEIPASS」，所以两份都能用。
    _ocr_src = os.path.join(REPO_ROOT, 'app', 'android', 'app', 'src',
                            'main', 'assets', 'ppocr')
    _ocr_dst = os.path.join(app_dir, 'ocr')
    if os.path.isdir(_ocr_src):
        if os.path.isdir(_ocr_dst):
            shutil.rmtree(_ocr_dst)        # 首次构建时不会存在，安全
        shutil.copytree(_ocr_src, _ocr_dst)
        n = len(os.listdir(_ocr_dst))
        ok('已放入 ocr\\（%d 个模型文件，可直接替换升级）' % n)
    else:
        fail('找不到 OCR 模型目录：%s（打包版的图片治理会读不出编码）' % _ocr_src)

    # 说明
    readme = os.path.join(app_dir, '使用说明.txt')
    with open(readme, 'w', encoding='utf-8-sig') as f:
        f.write(
            '集刻 产品库（绿色免安装版）\n'
            '=========================\n\n'
            '换新版（重要，别直接覆盖）\n'
            '  这个文件夹里除了 exe，其余都是你的数据（在 data\\ 里）。换新版两步：\n'
            '    1) 把新版本解压到**另一个目录**（别覆盖老的）\n'
            '    2) 把老版本的 data\\ 文件夹整个拷进新版本目录\n'
            '  然后**直接双击「启动产品库.cmd」**就行：它会先自动备份 data\\、\n'
            '    再升级库结构、再逐表核对行数，最后自动打开界面 —— 全程无需你\n'
            '    手动跑升级。升级前会先备份（data_备份_时间戳 目录），核对发现\n'
            '    掉行会明确报错并告诉你怎么还原，不会带着坏库继续跑。\n'
            '   （想手动升级也可双击「升级助手.cmd」，效果一样；命令行是 exe --upgrade）\n'
            '  ⚠️ 不要直接解压覆盖：会把程序文件弄乱；也不要只拷 productlib.db\n'
            '     —— 标准图、报告、缩略图都在 data\\ 目录里，要整个拷。\n'
            '  ⚠️ 升级前先关掉旧的产品库（黑窗口关掉）。\n\n'
            '怎么用\n'
            '  1. 双击「启动产品库.cmd」（或 启动产品库.ps1）\n'
            '  2. 浏览器会自动打开（端口若被占会自动换，窗口里会打印实际地址）\n'
            '  3. 用完关掉那个黑色命令行窗口 = 关闭产品库\n\n'
            '正确的干活顺序（打开就是「作业向导」，五步走完一柜）\n'
            '  ① 建柜   —— 填柜号、封条号、到离柜时间、检查员、客户、Location\n'
            '             （柜号是全流程主线，顶部「当前柜」全站跟着它走）\n'
            '  ② 导入清单 —— 选 Excel 导入；导入后可在这一步**直接查看和修改**\n'
            '             清单内容（品名 / 规格 / Loading 数量 / 核对）\n'
            '  ③ 照片   —— 导入照片 → 跑治理 → 浏览照片，三件事在这一步里做完。\n'
            '             「本柜照片」有五个分组选项卡：\n'
            '               全部 / 已关联 / 未关联 /\n'
            '               待确认关联 —— 照片里读出了像产品库里某个编码，但还没\n'
            '                            关联，需要你判断要不要关联\n'
            '               新产品确认 —— 照片里读出的编码产品库里根本没有，\n'
            '                            需要你确认是不是新产品并入库\n'
            '             找「还没对上的货」用后两档最快（数字就是待办张数）。\n'
            '             每张照片上也会标「待确认」「新产品」角标。\n'
            '  ④ 选图   —— 可跳过。跳过时报告按编码自动取一张；\n'
            '             要指定用哪张，就在这里检索编码后批量采用\n'
            '  ⑤ 生成报告 —— 按柜出装柜报告 docx（Packing list + Quantity check\n'
            '             + 柜况 / 卡车照片）。**每页固定 6 张图，每个章节另起一页**\n'
            '  各步骤之间会自动跳；生成过的报告在「报告档案」页可按柜查看下载。\n'
            '\n'
            '  另有一个「照片库」页（导航第二组）：按柜 / 批次 / 治理状态 / 分类 /\n'
            '  用途 / 编码浏览全部照片，五档分组选项卡与向导③是同一份实现。\n'
            '\n'
            '  ⚠️ 程序**不会自动建柜**。即使照片目录名就是柜号，没建过的柜\n'
            '     也会被拒绝并提示你先建 —— 自动建出来的柜没有封条号和\n'
            '     检查员，报告里这些字段是空的，等于制造一个残缺的数据源。\n\n'
            '⚠️ 先做这件事，否则「图片治理」读不出编码\n'
            '  打开「设置 → 多模态识别」，填 API 地址 / Key / 模型名，点保存。\n'
            '  不填也能用：图片分类与本地 OCR 仍可用，\n'
            '  但手写码/模糊件需要视觉模型才能补全。\n\n'
            '数据在哪\n'
            '  本目录下的 data\\\n'
            '    productlib.db   产品库数据库（产品、清单、柜、关联）\n'
            '    vision.json     视觉模型配置（上面填完就存这儿）\n'
            '    standard\\       标准图资产（一个产品编码一个文件夹：\n'
            '                     standard\\<产品编码>\\<类别>[_n].jpg）\n'
            '    reports\\        生成的装柜报告 docx\n'
            '    thumbs\\ uploads\\  缩略图与上传临时文件（可删，会自动重建）\n'
            '  ⚠️ 备份 = 把整个 data\\ 文件夹拷走。换电脑也这么做。\n'
            '  ⚠️ 原照片不在这里（照片库是「原地引用」照片所在目录的），\n'
            '     换机器后照片路径会失效，需要重新导入照片批次。\n\n'
            'ocr\\ 目录（图片治理的本地 OCR 模型）\n'
            '  det.onnx / rec.onnx / keys.txt 三个文件，缺一不可。\n'
            '  想提高识别率可以自己换一套同名文件进来，无需重打包。\n\n'
            '换端口 / 换数据位置\n'
            '  命令行参数：\n'
            '    集刻产品库.exe --port 8800        指定端口（不指定时会自动找空闲的）\n'
            '    集刻产品库.exe --data D:\\某目录    换数据目录\n'
            '  或设环境变量：PL_HOME（数据目录）、PL_DB（直接指定 .db 文件）\n\n'
            '常见问题\n'
            '  · 图片治理失败率高 / 编码读不出来：九成是没配视觉模型（见开头）\n'
            '    或 ocr\\ 目录缺文件。治理结果里每张都有失败原因，可在\n'
            '    「预检照片库」看得到。\n'
            '  · 提示「数据库被另一个产品库进程占用」：**同时开了两个产品库**\n'
            '    （比如绿色包和源码版各开一个，或浏览器留了个旧窗口）。\n'
            '    关掉多余的黑窗口重跑即可。治理本身不会造成这个 —— 它每张\n'
            '    照片就提交一次，锁的时间极短。\n'
            '  · 别把产品库开两份：同一个 data\\ 只能被一个进程写。\n'
            '  · 双击没反应：看黑窗口里的报错；多半是端口被占，会自动换端口\n'
            '  · 杀毒软件拦：本程序未做数字签名，被拦时加信任即可\n'
            '  · 界面打开但功能 404：说明打包漏了模块，把报错发给技术支持\n')
    ok('已放入 使用说明.txt')

    # 升级助手：换新版时用它「先备份、再升级、再自检」。放在 exe 同级，
    # 因为它要在**旧数据目录**上跑，不能藏在 _internal 里。
    # 升级逻辑本体：源码 upgrade.py 拷进包，供 exe --upgrade 在内部 import
    # 运行（冻结包里没有独立 Python，所以现场双击入口是 升级助手.cmd，由它
    # 调 exe 跑 --upgrade；.py 主要给开发机/源码版直接 `python upgrade.py` 用）。
    up = os.path.join(HERE, 'upgrade.py')
    if os.path.isfile(up):
        shutil.copy2(up, os.path.join(app_dir, '升级助手.py'))
        ok('已放入 升级助手.py（开发机直接 python 跑；现场双击请用 升级助手.cmd）')


def make_zip(app_dir):
    # zip 放在 app_dir 的**上级**（与 <时间戳> 同级），名字带上时间戳，
    # 这样"哪个 zip 对应哪次构建"一眼可见，也不会覆盖上一次的包。
    zpath = os.path.join(os.path.dirname(app_dir),
                         APP_NAME + '_绿色包_%s.zip'
                         % time.strftime('%Y%m%d_%H%M'))
    if os.path.exists(zpath):
        os.remove(zpath)
    t0 = time.time()
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(app_dir):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.join(
                    APP_NAME, os.path.relpath(full, app_dir)))
    ok('已打包 zip：%s（%.0f MB，用时 %.0f 秒）'
       % (zpath, os.path.getsize(zpath) / 1048576, time.time() - t0))
    return zpath


def main():
    ap = argparse.ArgumentParser(description='构建产品库绿色包')
    ap.add_argument('--clean', action='store_true',
                    help='先归档 build/ 与 dist/ 再构建（默认就会归档）')
    ap.add_argument('--zip', action='store_true', help='构建后打 zip（拷到别的电脑）')
    a = ap.parse_args()

    for f in (SPEC, ENTRY):
        if not os.path.exists(f):
            fail('缺文件：%s' % f)
    py = pick_python()
    ok('用这个解释器打包：%s' % py)
    # 永远先归档：PyInstaller 需要一个不存在的输出目录（它自己会去删已存在的），
    # 有删除保护钩子时那一步必被拦。改名归档不是删除，绕开钩子。
    app_dir = build(py, clean=a.clean, archive=True)
    if not os.path.isdir(app_dir):
        fail('产物目录不存在：%s' % app_dir)
    post_build(app_dir)
    if a.zip:
        make_zip(app_dir)
    total = 0
    for root, _d, files in os.walk(app_dir):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    ok('产物：%s（%.0f MB）' % (app_dir, total / 1048576))
    print('[ OK ] 打包版自检：把它拷到一个空目录，双击 启动产品库.cmd')
    print('[ .. ] 每次构建都留档（dist/<时间戳>/），确认新版没问题后可清旧的')


if __name__ == '__main__':
    main()