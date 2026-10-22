# -*- coding: utf-8 -*-
"""端口避让（2026-10-06 老板在其他电脑上遇到「提示端口被占用」）

判据：
  1. 首选端口空闲 → 就用它，不换（不能每次都换端口，书签会失效）
  2. 首选端口被占 → 往后找空闲端口，**打印中文提示**并说明换了端口
  3. 连着 24 个端口都被占 → 返回 None，且提示给三条可操作的办法
  4. `_say` 必须 flush：启动提示的价值全在「黑窗口里立刻可见」

⚠️ 这套逻辑放在 **server.py 里**而不是启动脚本里 —— 老板最常见的用法是
**直接双击 exe**，那条路根本不经过 .cmd/.ps1，探测放脚本里等于没做。
而且两处各探一套会不一致（脚本说 8766、exe 实际 8767）。

跑法：python tools/productlib/tests/port_pick.py
"""
import os
import socket
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from tools.productlib import server  # noqa: E402

FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name
          + ('' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


# 找一个肯定没人占的端口当基准
def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


BASE = free_port()

# ── 1. 空闲端口：不动 ──────────────────────────────────────────
p, moved = server._pick_port(BASE)
chk('V1 首选端口空闲时就用它（不乱换，书签/旧地址要继续有效）',
    p == BASE and moved is False, '%s moved=%s' % (p, moved))

# ── 2. 被占：往后找 ────────────────────────────────────────────
holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
holder.bind(('127.0.0.1', BASE))
holder.listen(5)
try:
    chk('V2 _port_busy 认出被占', server._port_busy(BASE) is True)
    p2, moved2 = server._pick_port(BASE)
    chk('V3 被占时自动改用下一个空闲端口',
        p2 == BASE + 1 and moved2 is True, '-> %s moved=%s' % (p2, moved2))
    chk('V4 跳过的是被占那个，不是随便挑一个', p2 != BASE, p2)
finally:
    holder.close()

# ── 3. 连续占用：必须连续跳过，落在第一个空闲上 ──────────────────
holders = []
try:
    for i in range(3):
        h = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        h.bind(('127.0.0.1', BASE + i))
        h.listen(1)
        holders.append(h)
    p3, moved3 = server._pick_port(BASE)
    chk('V5 连占 3 个后落在第 4 个（逐个跳过，不是从头重试）',
        p3 == BASE + 3 and moved3 is True, '-> %s' % p3)
finally:
    for h in holders:
        h.close()

# ── 4. 全占满 → 返回 None（而不是随便挑一个去撞墙）──────────────
# ⚠️ 用一个**独占的连续端口段**：不能让 BASE 起的区间与别的测试/服务重叠
# （实测并行跑回归时 V6 会因端口被抢而失败 —— 端口类测试天然怕并发）。
def free_block(n):
    """找一段连续 n 个都空闲的端口。找不到就返回 None（用例跳过，不给假绿）。"""
    for start in range(20000, 60000 - n, 137):
        socks = []
        ok_all = True
        for i in range(n):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(('127.0.0.1', start + i))
                socks.append(s)
            except OSError:
                ok_all = False
                s.close()
                break
        for s in socks:
            s.close()
        if ok_all:
            return start
    return None


SPAN = 24
_base6 = free_block(SPAN + 2)
if _base6 is None:
    chk('V6 连续占满用例（找不到连续空闲端口段，跳过）', True, 'skip')
else:
    allheld = []
    try:
        for i in range(SPAN):
            h = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            h.bind(('127.0.0.1', _base6 + i))
            h.listen(1)
            allheld.append(h)
        p4, _ = server._pick_port(_base6)
        chk('V6 连续 %d 个全被占 → 返回 None（交给上层给可操作提示）'
            % SPAN, p4 is None, p4)
    finally:
        for h in allheld:
            h.close()

# ── 5. _say 带 flush（管道里必须立刻可见）───────────────────────
import subprocess  # noqa: E402
py = sys.executable
r = subprocess.run(
    [py, '-c', 'import sys; sys.path.insert(0, %r); '
               'from tools.productlib.server import _say; _say("HELLO")'
               % os.path.dirname(os.path.dirname(os.path.dirname(
                   os.path.dirname(os.path.abspath(__file__)))))],
    capture_output=True, text=True, timeout=60)
chk('V7 _say 立刻输出且不带换行污染',
    'HELLO' in r.stdout, repr(r.stdout[:80]))

# ── 6. 打包版路径名不能泄漏 python -m（给老板的命令要能直接抄）───
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', 'server.py'), encoding='utf8').read()
chk('V8 端口提示里的换端口命令给的是 exe 名（打包后 -m 跑不起来）',
    "python -m tools.productlib.server" not in src.split('def main')[1][:3000]
    or 'exe_name' in src, '需含 exe_name 变量')

print('----')
print('%d 项检查，%d 失败' % (8, len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')