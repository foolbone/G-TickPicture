# -*- coding: utf-8 -*-
"""柜号一律以 web 端选择的柜为准（2026-10-06 老板定口径）

演进：
  v3.0 柜号来自目录名 + 自动建柜  → 老板指正「没建柜却凭空多出柜号」
  v3.1 柜实体必须先由人建（目录名带柜号也不行）
  **v3.2 一切柜号以 web 端输入的柜号为准**；目录名只当"来源目录"，
        仅用于批次命名与去重判断，**绝不用于建柜或挂批次**。

为什么必须这样：目录名一旦与真实柜号不符（App 交付目录、日期、随意命名），
照片会挂到 A 柜而清单在 B 柜，错误静默传播到整份报告。

判据：
  N1 不传 container_id → 拒绝，**不建柜**
  N2 传了 container_id → 照片挂到那个柜，**目录名不参与归属**
  N2b 目录名与柜号不同 → 仍挂所选柜，且返回 dir_mismatch 告知
  N2c 同一柜下多个来源目录 → **都要导进去**（不能按柜号判重吃掉第二个）
  N3 报错文案要说清「为什么不自动建」
  N4 同一来源目录重复导入 → 才是重复（按批次名判重）
  N5 已建的柜不会被改动

跑法：python tools/productlib/tests/container_gate.py
"""
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))       # tools/productlib/tests
_PL = os.path.dirname(_HERE)                              # tools/productlib
_TOOLS = os.path.dirname(_PL)                             # tools
_ROOT = os.path.dirname(_TOOLS)                           # 仓库根
for _p in (_ROOT, _TOOLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.productlib import store                        # noqa: E402
from PIL import Image                                     # noqa: E402

FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name
          + ('' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


tmp = tempfile.mkdtemp(prefix='pl_ctngate_')
con = store.connect(os.path.join(tmp, 't.db'))


def make_std(folder_root, container_no, n=2):
    """造标准采集格式目录：{柜号}/预检/{箱号}/P_xx.jpg"""
    d = os.path.join(folder_root, container_no, '预检', 'Cage-M1')
    os.makedirs(d, exist_ok=True)
    for i in range(n):
        Image.new('RGB', (800, 600), (30 * i, 120, 200)).save(
            os.path.join(d, 'P_%02d.jpg' % i))
    return folder_root


# ── N1 不给 container_id → 拒绝，不建柜 ─────────────────────────
root = make_std(os.path.join(tmp, 'r1'), 'UNKNOWN01', 2)
n_before = con.execute('SELECT COUNT(*) FROM containers').fetchone()[0]
try:
    store.import_standard_folder(con, root)          # 故意不传 container_id
    chk('N1 没选柜被拒（未自动建柜）', False, '竟然导成功了')
except store.ContainerError as e:
    chk('N1 没选柜被拒（未自动建柜）', True)
    msg = str(e)
    chk('N1b 报错说清要先选柜', '选择柜' in msg, msg.splitlines()[0][:60])
    chk('N3 报错说清「程序不认目录名当柜号」',
        '不认目录名' in msg or '不自动建' in msg, msg.splitlines()[0][:70])
n_after = con.execute('SELECT COUNT(*) FROM containers').fetchone()[0]
chk('N1c 柜数量没变（真的没建）', n_before == n_after,
    '%d -> %d' % (n_before, n_after))
chk('N1d 目录名再像柜号也不会被当成柜',
    con.execute("SELECT COUNT(*) FROM containers WHERE container_no='UNKNOWN01'"
                ).fetchone()[0] == 0)

# ── N2 给了 container_id → 一律挂到那个柜，目录名不参与 ────────
c = store.create_container(con, 'REAL01', remark='老板手建的柜')
cid = c['id']
root2 = os.path.join(tmp, 'r2')
make_std(root2, 'TOTALLY_UNRELATED_NAME', 2)      # 目录名故意与柜号毫无关系
make_std(root2, '另一个目录名', 1)                  # 同一柜下第二个来源目录
r2 = store.import_standard_folder(con, root2, container_id=cid)
chk('N2 目录名与柜号无关也照样导进去', r2['added'] == 3,
    'added=%s skipped=%s' % (r2['added'], r2['skipped']))
chk('N2b 返回值给出真实柜号', r2.get('container_no') == 'REAL01',
    r2.get('container_no'))
chk('N2c 目录名不同时返回 dir_mismatch 告知',
    set(r2.get('dir_mismatch') or []) ==
    {'TOTALLY_UNRELATED_NAME', '另一个目录名'}, r2.get('dir_mismatch'))
chk('N2d 照片全挂在所选柜下（目录名一个都没被当成柜）',
    con.execute('SELECT COUNT(*) FROM photos WHERE batch_id IN'
                ' (SELECT id FROM batches WHERE container_id=?)',
                (cid,)).fetchone()[0] == 3)
chk('N2e 只建了老板那一个柜',
    con.execute('SELECT COUNT(*) FROM containers').fetchone()[0] == n_after + 1,
    con.execute('SELECT COUNT(*) FROM containers').fetchone()[0])
chk('N2f 同一柜下两个来源目录都建了批次（不被判重吃掉）',
    con.execute('SELECT COUNT(*) FROM batches WHERE container_id=? AND kind=?',
                (cid, 'photos')).fetchone()[0] == 2,
    con.execute('SELECT COUNT(*) FROM batches WHERE container_id=? AND kind=?',
                (cid, 'photos')).fetchone()[0])
chk('N2g 批次名带来源目录（可追溯照片来自哪个目录）',
    {r[0] for r in con.execute(
        'SELECT name FROM batches WHERE container_id=? AND kind=?',
        (cid, 'photos'))} ==
    {'标准采集-TOTALLY_UNRELATED_NAME', '标准采集-另一个目录名'},
    [r[0] for r in con.execute(
        'SELECT name FROM batches WHERE container_id=? AND kind=?',
        (cid, 'photos'))])

# ── N4/N5 同一来源目录重复导入 → 判重；元数据不动 ───────────────
seal_before = con.execute('SELECT remark, created_at FROM containers WHERE id=?',
                          (cid,)).fetchone()
r = store.import_standard_folder(con, root2, container_id=cid)
chk('N4 同一照片目录重复导入被识别为重复', r.get('added') == 0
    and all(x.get('all_duplicate') for x in r.get('containers', [])),
    'added=%s' % r.get('added'))
n_c = con.execute('SELECT COUNT(*) FROM containers').fetchone()[0]
chk('N4b 没有多建柜', n_c == n_after + 1, '%d' % n_c)
seal_after = con.execute('SELECT remark, created_at FROM containers WHERE id=?',
                         (cid,)).fetchone()
chk('N5 已有柜的元数据未被导入改动',
    tuple(seal_before) == tuple(seal_after),
    '%s -> %s' % (tuple(seal_before), tuple(seal_after)))

# 箱号也被记下来了（报告图注要用）
cartons = {r[0] for r in con.execute(
    'SELECT DISTINCT carton_no FROM photos WHERE batch_id IN'
    ' (SELECT id FROM batches WHERE container_id=?) AND IFNULL(carton_no,"")!=""',
    (cid,))}
chk('N4c 箱号随照片入库', 'Cage-M1' in cartons, cartons)

# ── CLI 用的 _ensure_container 仍能建（迁移/脚本场景没界面）──────
cid2 = store._ensure_container(con, 'CLIONLY', note='脚本建的')
chk('N6 CLI/迁移用的 _ensure_container 保留（无界面场景需要）',
    bool(cid2) and con.execute(
        'SELECT 1 FROM containers WHERE container_no=?',
        ('CLIONLY',)).fetchone() is not None)

con.close()
shutil.rmtree(tmp, ignore_errors=True)

print('----')
print('%d 项检查，%d 失败' % (14, len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')