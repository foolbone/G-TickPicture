# -*- coding: utf-8 -*-
"""upgrade.py —— 产品库升级助手（换绿色包时用）

老板的实际场景：绿色包更新了，老电脑上有一堆数据（产品、照片、柜、关联、
报告、标准图），怕升级时丢东西。

这个脚本做三件事，**顺序不能颠倒**：
    1. 备份   —— 把 data/ 整个目录复制一份带时间戳的副本（出问题能原样还原）
    2. 升级   —— 用当前代码打开库，触发幂等迁移（只加列/建表，绝不改已有数据）
    3. 自检   —— 逐表比对升级前后的行数，任何一张表掉行就报出来

用法：
    # 先干看一遍（只报告将要做什么，不改任何东西）
    python tools/productlib/upgrade.py --data "D:/某电脑/集刻产品库/data" --dry-run

    # 真升级（会自动先备份）
    python tools/productlib/upgrade.py --data "D:/某电脑/集刻产品库/data"

⚠️ 升级前请**关掉产品库**（黑窗口关掉）。开着的时候 SQLite 能并发读，
   但迁移会改表结构，两个进程同时改会互相打架。
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tools.productlib import paths, store, schema  # noqa: E402


def log(msg):
    print('[ .. ] ' + msg, flush=True)


def ok(msg):
    print('[ OK ] ' + msg, flush=True)


def warn(msg):
    print('[WARN] ' + msg, flush=True)


def fail(msg):
    print('[FAIL] ' + msg, flush=True)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
# 1. 备份
# ═══════════════════════════════════════════════════════════════════

def backup(data_dir):
    """把整个 data 目录复制成带时间戳的副本。

    复制**目录**而不是单个 .db：缩略图、标准图、报告、vision.json 都在里面，
    只备 .db 的话还原后照片预览和报告全丢。
    """
    if not os.path.isdir(data_dir):
        fail('数据目录不存在：%s' % data_dir)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(os.path.dirname(os.path.abspath(data_dir)),
                       '%s_备份_%s' % (os.path.basename(os.path.abspath(data_dir)), stamp))
    if os.path.exists(dst):
        fail('备份目标已存在：%s' % dst)
    log('备份 %s → %s' % (data_dir, dst))
    t0 = time.time()
    shutil.copytree(data_dir, dst)
    ok('备份完成，用时 %.0f 秒（%.1f MB）'
       % (time.time() - t0, _dir_mb(dst)))
    return dst


def _dir_mb(d):
    n = 0
    for root, _dd, files in os.walk(d):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n / 1048576


def snapshot(db_path):
    """逐表行数快照（只数行，不看内容 —— 内容比对对 2700 张照片没意义）。"""
    con = sqlite3.connect(db_path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {t: con.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
                for t in tables}
    finally:
        con.close()


# ═══════════════════════════════════════════════════════════════════
# 2. 升级
# ═══════════════════════════════════════════════════════════════════

def upgrade(data_dir):
    """用当前代码直接跑幂等迁移（不依赖 store.connect 的进程内缓存）。

    为什么可以放心：schema.py 里全是 `CREATE TABLE IF NOT EXISTS`，
    store._migrate 里全是 `ALTER TABLE ... ADD COLUMN`（且都有 `_has_col`
    幂等探针）——**没有任何 DROP / DELETE / UPDATE 已有数据**。

    ⚠️ 不用 store.connect：它的迁移受 `_schema_initialized` 缓存保护，
    同进程里若先前 connect 过该库，再次 connect 会跳过迁移。升级必须
    **每次都真跑一遍**迁移（幂等探针保证安全），所以用原始连接显式
    executescript(SCHEMA) + store._migrate。
    """
    db = os.path.join(data_dir, 'productlib.db')
    if not os.path.isfile(db):
        fail('找不到数据库：%s' % db)
    t0 = time.time()
    con = sqlite3.connect(db, timeout=30)
    # 🔴 必须与 store.connect 一样设 row_factory=sqlite3.Row：_migrate 链路上
    #    只要有一处用了命名访问（r['x']），裸连接就会抛
    #    "tuple indices must be integers or slices, not str"，而它抛在**启动
    #    链路**上 —— 服务直接拒启动（2026-10-11 发 v0.7.0 时真实旧库实测踩到：
    #    _migrate_standard_layout 里的 r['file']）。
    #    一行设置给整条迁移链兜底，比逐处改用下标更抗后续新增代码。
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript(schema.SCHEMA)   # CREATE TABLE IF NOT EXISTS（幂等）
        store._migrate(con)                # 增量补列/索引（幂等探针）
        con.commit()
    finally:
        con.close()
    ok('库结构已升级到当前版本，用时 %.2f 秒' % (time.time() - t0))


# ═══════════════════════════════════════════════════════════════════
# 3. 自检
# ═══════════════════════════════════════════════════════════════════

def selfcheck(data_dir, before):
    db = os.path.join(data_dir, 'productlib.db')
    after = snapshot(db)
    print()
    print('%-22s %10s %10s  %s' % ('表', '升级前', '升级后', '结论'))
    lost = []
    for t, n in sorted(before.items()):
        m = after.get(t)
        if m is None:
            print('%-22s %10d %10s  [FAIL] 表不见了' % (t, n, '—'))
            lost.append(t)
        elif m < n:
            print('%-22s %10d %10d  [FAIL] 少了 %d 行' % (t, n, m, n - m))
            lost.append(t)
        else:
            print('%-22s %10d %10d  [ OK ]' % (t, n, m))
    added = sorted(set(after) - set(before))
    if added:
        print()
        print('新增的表: %s' % '、'.join(added))
    print()
    if lost:
        fail('升级丢了数据：%s —— 用刚做的备份还原' % '、'.join(lost))
    ok('逐表行数核对通过：**没有任何一张表掉行**')
    # 报告/标准图这些文件型资产单独确认
    for sub, label in (('standard', '标准图'), ('reports', '装柜报告'),
                       ('uploads', '上传临时文件'), ('thumbs', '缩略图')):
        p = os.path.join(data_dir, sub)
        n = len(os.listdir(p)) if os.path.isdir(p) else 0
        (ok if n else log)('%s: %d 个（%s 子目录）'
                           % (label, n, sub))


# ═══════════════════════════════════════════════════════════════════
# 4. 报告能否打开（升级后最关心的）
# ═══════════════════════════════════════════════════════════════════

def smoke(data_dir):
    """开一次连接 + 查几个关键接口用的数据，确认库不是「建好了但读不了」。"""
    db = os.path.join(data_dir, 'productlib.db')
    con = store.connect(db)
    try:
        n_prod = con.execute('SELECT COUNT(*) FROM products').fetchone()[0]
        n_ph = con.execute('SELECT COUNT(*) FROM photos').fetchone()[0]
        n_c = con.execute('SELECT COUNT(*) FROM containers').fetchone()[0]
        ok('能正常读取：%d 个产品 / %d 张照片 / %d 个柜'
           % (n_prod, n_ph, n_c))
        # 照片路径是否还在（换机器的话这才是真风险）
        gone = con.execute(
            'SELECT COUNT(*) FROM photos WHERE IFNULL(path,\'\')=\'\'').fetchone()[0]
        if gone:
            warn('%d 张照片没有路径记录（换机器后需重新导入照片）' % gone)
        else:
            real = 0
            for r in con.execute('SELECT path FROM photos LIMIT 20'):
                if os.path.exists(r['path']):
                    real += 1
            warn('抽查 20 张照片：%d 张的原路径仍存在。'
                 '换电脑后照片路径会失效，需要把照片拷到本机后重新导入。' % real)
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description='产品库升级助手（先备份，再升级，再自检）')
    ap.add_argument('--data', default='', help='数据目录（含 productlib.db 的那个）')
    ap.add_argument('--dry-run', action='store_true',
                    help='只报告将要做什么，不备份也不改库')
    ap.add_argument('--no-backup', action='store_true',
                    help='⚠️ 跳过备份（不建议；出问题就没得还原了）')
    # argv 允许外部传入（绿色包里由 server.main(['--upgrade']) 调进来）
    a = ap.parse_args(argv)

    data_dir = (a.data or paths.data_dir()).strip()
    if not os.path.isdir(data_dir):
        fail('数据目录不存在：%s' % data_dir)
    db = os.path.join(data_dir, 'productlib.db')

    print('=' * 62)
    print(' 产品库升级助手')
    print('=' * 62)
    print('  数据目录: %s' % data_dir)
    print('  数据库  : %s' % db)
    print('  当前版本: %d 个表定义（%s）'
          % (len([x for x in schema.SCHEMA.split('CREATE TABLE')
                  if x.strip().upper().startswith(('IF NOT EXISTS', 'IF'))]),
             'schema.SCHEMA'))
    print()

    if not os.path.isfile(db):
        fail('找不到数据库文件。若这是**第一次**使用绿色包（还没有数据），'
             '直接双击「启动产品库.cmd」即可，它会自动建库。')

    # 已是最新 → 不备份、不改库（避免每次重跑都复制一份 data\\ 备份）
    if not store.needs_migration(db):
        ok('库结构已是最新，无需升级（不重复备份）。直接启动产品库即可。')
        return 0

    before = snapshot(db)
    ok('升级前已读取基线：%d 张表 / 共 %d 行'
       % (len(before), sum(before.values())))

    if a.dry_run:
        print()
        log('--dry-run：不做任何改动。到此为止。')
        log('去掉 --dry-run 就会先备份再升级。')
        return 0

    print()
    # ── 1 备份 ──
    bak = None
    if a.no_backup:
        warn('跳过了备份（--no-backup）。出问题时没有还原点。')
    else:
        bak = backup(data_dir)

    print()
    # ── 2 升级 ──
    upgrade(data_dir)

    print()
    # ── 3 自检 ──
    selfcheck(data_dir, before)
    print()
    smoke(data_dir)

    print()
    if bak:
        ok('出问题怎么还原：')
        print('       1. 关掉产品库')
        print('       2. 把当前 data 目录改名成 data_坏的（别删）')
        print('       3. 把刚才的备份改名回 data')
        print('       4. 重新双击启动产品库.cmd')
        print('       备份位置：%s' % bak)
    return 0


def auto_upgrade(data_dir, quiet=False):
    """启动即用的「无感升级」入口：只在**确实待迁移**时才备份+迁移+核对。

    老板只要「解压新包 → 拷 data\\ → 双击启动产品库.cmd」就完成升级，
    不用再单独跑升级助手。与 server.main 的正常启动分支集成（见 server.py）。

    返回 dict：
      {'needed': False}                                      —— 已是最新，啥也没做
                                                            （无备份、无打扰）
      {'needed': True, 'backup': 路径, 'failed': False}      —— 已安全升级
      {'needed': True, 'backup': 路径, 'failed': True,
       'error': ...}                                         —— 核对未过，调用方应
                                                            **拒绝启动**（带着坏库跑
                                                            比不跑更糟），并提示用
                                                            backup 还原

    ⚠️ backup 在 migration **之前**做（拷的是迁移前的旧库），还原后一定能
    回到升级前的状态。
    """
    db = os.path.join(data_dir, 'productlib.db')
    if not os.path.isfile(db):
        return {'needed': False}            # 首次使用，connect() 会建全新库
    if not store.needs_migration(db):
        return {'needed': False}            # 已是最新，静默跳过（不备份、不打扰）
    if not quiet:
        log('检测到旧版库结构，启动前自动升级（先备份，再迁移，再核对行数）')
    before = snapshot(db)
    bak = backup(data_dir)                  # 迁移前先备份（关键）
    try:
        upgrade(data_dir)                   # 触发幂等迁移（store.connect 内部跑 _migrate）
        selfcheck(data_dir, before)         # 掉行会 sys.exit(1)
        smoke(data_dir)
    except SystemExit:
        return {'needed': True, 'backup': bak, 'failed': True,
                'error': '升级后逐表核对未通过，请用备份还原后再启动'}
    except Exception as e:                  # 任何意外都不要静默吞掉
        return {'needed': True, 'backup': bak, 'failed': True,
                'error': '升级过程异常：%s' % e}
    return {'needed': True, 'backup': bak, 'failed': False}


if __name__ == '__main__':
    raise SystemExit(main() or 0)