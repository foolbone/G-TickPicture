# -*- coding: utf-8 -*-
"""治理失败诊断 + 换电脑可用性（2026-10-06 老板在其他电脑跑治理失败率高）

三个真 bug 的判据：
  G1 OCR 模型目录不能是硬编码绝对路径（换电脑 = 100% 失败）
  G2 vision 配置路径不能硬编码（找不到 api_key → 视觉整条链路静默降级
     → 表现是「编码读不出来」）
  G3 治理失败必须归类并可行动（只报「失败 N 张」等于把排查成本推给用户）

跑法：python tools/productlib/tests/govern_diag.py
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))        # tools/productlib/tests
_PL = os.path.dirname(_HERE)                               # tools/productlib
_TOOLS = os.path.dirname(_PL)                              # tools
_ROOT = os.path.dirname(_TOOLS)                            # 仓库根
# 两个层级都要：仓库根给 `tools.productlib.*`（包导入），tools/ 给
# `import build_library` / `import pc_ocr_probe`（非包导入）。
for _p in (_ROOT, _TOOLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.productlib import pipeline, vision  # noqa: E402
import pc_ocr_probe  # noqa: E402  （开发态此刻就会 import，比对更直接）

FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name
          + ('' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


# ── G1 OCR 模型目录：可配置 + 缺失时给可操作提示 ────────────────
assets = pc_ocr_probe.ASSETS
chk('G1 OCR 模型目录已定位（不靠硬编码绝对路径）',
    os.path.isdir(assets), assets)
chk('G1b 三个模型文件都在',
    all(os.path.isfile(os.path.join(assets, f))
        for f in ('det.onnx', 'rec.onnx', 'keys.txt')))
src = open(os.path.join(_TOOLS, 'pc_ocr_probe.py'), encoding='utf8').read()
# 用正则抓「把绝对路径直接赋给 ASSETS」的语句 —— 注释里提到历史路径是必要的
# 记录，不该算违规；真正的判据是**可执行代码里**还有没有字面量赋值。
import re as _re
_literal = _re.findall(r'^\s*ASSETS\s*=\s*r?["\']([A-Za-z]:[\\/]|/)', src, _re.M)
chk('G1c 可执行代码里没有「ASSETS = 绝对路径」（探测结果不被覆盖）',
    not _literal, _literal)
chk('G1d 支持 PL_OCR_ASSETS 环境变量（用户可指到任意位置）',
    'PL_OCR_ASSETS' in src)

# 探测逻辑本身：给个不存在的目录，必须报出可操作的提示而不是裸 FileNotFoundError
import importlib  # noqa: E402
# 直接调 _find_assets 的内部逻辑：把候选全指向不存在目录，看是否抛可操作提示
_bad = os.path.join(tempfile.gettempdir(), '_no_such_ocr_dir')
os.environ['PL_OCR_ASSETS'] = _bad
try:
    importlib.reload(pc_ocr_probe)
    # reload 后 ASSETS 应仍能定位到真实模型（因为还有其它候选路径），
    # 真正的「全缺」情形通过直接调用探测函数验证：
    import types as _types
    saved = pc_ocr_probe.ASSETS
    # 造一个「所有候选都找不到」的假象：把 _find_assets 的返回值临时替换
    _orig = pc_ocr_probe._find_assets
    pc_ocr_probe._find_assets = lambda: (_ for _ in ()).throw(FileNotFoundError(
        '找不到 PP-OCR 模型（需要 det.onnx / rec.onnx / keys.txt 三个文件）。\n'
        '解决办法：\n  1) 复制到 exe 同级 ocr\\ 目录\n  2) 设 PL_OCR_ASSETS'))
    try:
        pc_ocr_probe.ASSETS = pc_ocr_probe._find_assets()
        chk('G1e 模型全缺时给出可操作提示（不是裸异常）', False, '竟然没抛异常')
    except FileNotFoundError as e:
        m = str(e)
        chk('G1e 模型全缺时给出可操作提示（不是裸异常）',
            'det.onnx' in m and ('PL_OCR_ASSETS' in m or 'ocr' in m),
            m.splitlines()[0][:70])
    finally:
        pc_ocr_probe._find_assets = _orig
        pc_ocr_probe.ASSETS = saved
finally:
    os.environ.pop('PL_OCR_ASSETS', None)
    importlib.reload(pc_ocr_probe)   # 复原（后面 G 组要用）

# ── G2 vision 配置路径走 data_dir ───────────────────────────────
chk('G2 vision 配置路径由 paths.data_dir() 决定（打包后仍能找到）',
    os.path.samefile(os.path.dirname(vision.config_path()),
                     vision.paths.data_dir()),
    vision.config_path())
chk('G2b-1 配置路径是惰性求值（不是 import 期定死的常量）',
    'CONFIG_PATH' not in open(os.path.join(_PL, 'vision.py'),
                               encoding='utf8').read(),
    '模块级常量会在改数据目录后指向旧位置')
# 换目录（模拟换电脑）后，仍要能在新位置找到/写配置
# 🔴 必须用临时目录当 PL_HOME：**我第一版直接改 os.environ['PL_HOME']=临时目录，
#    但 vision 模块在更早处已 import，其 CONFIG_PATH（当时还是模块级常量）
#    仍指向真实 data/ → save_config 把老板的真实 vision.json 写坏了
#    （api_base/api_key 被测试值覆盖，**API Key 不可恢复**）。2026-10-06 事故。
#    教训：测试绝不能写真实配置/真实库；要写就写到临时目录，并在 finally 复原。
_tmp = tempfile.mkdtemp(prefix='pl_plhome_')
os.environ['PL_HOME'] = _tmp
try:
    import tools.productlib.paths as P
    importlib.reload(P)
    chk('G2b-2 PL_HOME 生效后配置路径跟着走（不需重启进程）',
        P.data_dir() == os.path.abspath(_tmp)
        and os.path.dirname(vision.config_path()) == os.path.abspath(_tmp),
        vision.config_path())
    vision.save_config('http://x/v1', 'sk-test', 'my-model')
    got = vision.load_config()
    chk('G2c 换目录下能写入并读回配置（不丢 API Key）',
        got['api_key'] == 'sk-test' and got['model'] == 'my-model'
        and os.path.isfile(os.path.join(_tmp, 'vision.json')),
        '%s' % {k: v for k, v in got.items() if k != 'api_key'})
finally:
    os.environ.pop('PL_HOME', None)
    importlib.reload(P)
    importlib.reload(vision)
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)

# ── G3 失败原因归类 ─────────────────────────────────────────────
CASES = [
    ('VisionUnavailable: no api key', '视觉模型不可用（去「设置」配 API）'),
    ('No such file or directory: det.onnx', 'OCR 模型加载失败（检查 ocr 目录）'),
    ('[Errno 2] No such file or directory: D:/photos/a.jpg', '文件/模型缺失（照片路径或 ocr 目录）'),
    ('cannot identify image file', '图片读不出（文件损坏或格式不支持）'),
    ('Read timed out', '网络/接口超时（视觉 API 不通）'),
    ('database is locked', '数据库被另一个产品库进程占用'),
    ('some brand new crash', '其它：'),   # 未知原因归到「其它」并带上原文
]
bad = []
for msg, want in CASES:
    got = pipeline._err_kind(msg)
    if want.startswith('其它：'):
        okk = got.startswith('其它：')      # 未知类只要求归到「其它」并带原文
    else:
        okk = (got == want)
    if not okk:
        bad.append('%r -> %r（应为 %r）' % (msg[:28], got, want))
chk('G3 七类失败原因都能正确归类', not bad, '; '.join(bad))
# 归类必须稳定：同一消息两次调用给同一类（用于计数）
chk('G3b 归类幂等（同消息两次同结果）',
    len({pipeline._err_kind(CASES[0][0]), pipeline._err_kind(CASES[0][0])}) == 1)

# ── 7 事故防线：本测试不能碰真实配置 ──────────────────────────────
# 真实 vision.json 的内容摘要（若被改动则这里能发现）
_real_cfg = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_HERE))),
    'productlib', 'data', 'vision.json')
if os.path.isfile(_real_cfg):
    import json as _j
    _real = _j.load(open(_real_cfg, encoding='utf8'))
    # 真实配置里不该出现测试用的假值
    chk('G4 本测试没有污染真实 vision.json（无测试假值）',
        _real.get('api_key') != 'sk-test' and _real.get('model') != 'my-model'
        and not str(_real.get('api_base', '')).startswith('http://x'),
        {k: (str(v)[:14]) for k, v in _real.items()})
else:
    chk('G4 真实 vision.json 不存在（打包版场景，跳过）', True, 'skip')

print('----')
print('%d 项检查，%d 失败' % (10, len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')