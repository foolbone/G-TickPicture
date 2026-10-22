# -*- coding: utf-8 -*-
"""
verify_library.py -- 产品库完整性自检（纯 ASCII 输出，便于 5.1 控制台查看）

建库工具一旦写错，最糟的后果是**静默写入假绑定** —— 库里有一条
"编码 X ↔ 照片 Y" 的记录，但那条记录根本不成立，将来召回时被当成
证据用出去。

这个脚本只做**只读断言**，不修任何东西，输出可机读的 RESULT 行。

用法：
  python tools/verify_library.py --db library/library.db
  python tools/verify_library.py --db library/library.db --csv-dir library

断言清单：
  A1  photos 表与磁盘文件一一对应（不存在的文件 = 库指向了空气）
  A2  bindings 的 code_norm 全部在 products 里（悬空绑定）
  A3  bindings 的 photo_file 全部在 photos 里（悬空引用）
  A4  C_adjacent 不得计入 products.photo_count（时序推断不是证据）
  A5  同一 (code_norm, photo_file) 不重复
  A6  编码归一化幂等：normalize(normalize(x)) == normalize(x)
  A7  对照表 CSV 的行数 >= products 行数（每个编码都要出现）
  A8  A/B 级绑定的照片必须存在且非重复文件
"""
import argparse
import csv
import os
import re
import sqlite3
import sys

RESULTS = []


def check(code, ok, msg, detail=None):
    RESULTS.append((code, ok, msg, detail))
    tag = 'PASS' if ok else 'FAIL'
    line = '[%s] %-4s %s' % (tag, code, msg)
    print(line)
    if detail and not ok:
        for d in detail[:10]:
            print('        - %s' % d)
        if len(detail) > 10:
            print('        ... and %d more' % (len(detail) - 10))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--csv-dir', default=None)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print('FAIL: db not found: %s' % args.db)
        return 2
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    q = lambda s, *a: con.execute(s, a).fetchall()

    print('=' * 60)
    print('library verify: %s' % args.db)
    print('=' * 60)

    products = q('SELECT * FROM products')
    photos = q('SELECT * FROM photos')
    bindings = q('SELECT * FROM bindings')
    print('products=%d photos=%d bindings=%d' % (len(products), len(photos), len(bindings)))
    print('-' * 60)

    prod_set = {p['code_norm'] for p in products}
    photo_set = {p['file'] for p in photos}

    # A1 照片文件是否真的在磁盘上
    missing = [p['file'] for p in photos if not os.path.exists(p['path'])]
    check('A1', not missing,
          'every indexed photo exists on disk (%d checked)' % len(photos), missing)

    # A2 悬空绑定：code_norm 不在 products
    dangling_code = sorted({b['code_norm'] for b in bindings} - prod_set)
    check('A2', not dangling_code,
          'no binding points to an unknown code', dangling_code)

    # A3 悬空绑定：photo_file 不在 photos
    dangling_photo = sorted({b['photo_file'] for b in bindings} - photo_set)
    check('A3', not dangling_photo,
          'no binding points to an unknown photo', dangling_photo)

    # A4 C_adjacent 不得计入 photo_count
    counted = {p['code_norm']: p['photo_count'] for p in products}
    expected = {}
    for b in bindings:
        if b['strength'] == 'C_adjacent':
            continue
        expected[b['code_norm']] = expected.get(b['code_norm'], 0) + 1
    bad_count = ['%s: db=%s real=%s' % (k, counted.get(k, 0), v)
                 for k, v in expected.items() if counted.get(k, 0) != v]
    bad_count += ['%s: db=%s real=0' % (k, v) for k, v in counted.items()
                  if v and k not in expected]
    check('A4', not bad_count,
          'photo_count excludes C_adjacent (evidence-only rule)', bad_count)

    # A5 绑定唯一
    seen = {}
    dup = []
    for b in bindings:
        k = (b['code_norm'], b['photo_file'])
        if k in seen:
            dup.append('%s | %s' % k)
        seen[k] = 1
    check('A5', not dup, 'no duplicate (code, photo) binding', dup)

    # A6 归一化幂等
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_library as B
    non_idem = []
    for p in products:
        n1 = B.normalize(p['code'])
        n2 = B.normalize(n1)
        if n1 != n2:
            non_idem.append('%s -> %s -> %s' % (p['code'], n1, n2))
        if n1 != p['code_norm']:
            non_idem.append('stored mismatch: %s stored=%s recomputed=%s'
                            % (p['code'], p['code_norm'], n1))
    check('A6', not non_idem, 'code normalization is idempotent and stored consistently',
          non_idem)

    # A7 对照表覆盖全部编码
    if args.csv_dir:
        p_csv = os.path.join(args.csv_dir, '_编码对照表.csv')
        if os.path.exists(p_csv):
            with open(p_csv, 'r', encoding='utf-8-sig', newline='') as f:
                rows = list(csv.reader(f))
            body = [r for r in rows[1:] if r and r[0]]
            csv_codes = {B.normalize(r[0]) for r in body}
            miss = sorted(prod_set - csv_codes)
            check('A7', not miss,
                  'cross-reference CSV covers every product (%d rows)' % len(body), miss)
        else:
            check('A7', False, 'cross-reference CSV not found: %s' % p_csv)

    # A8 A/B 级绑定的照片必须存在且非重复
    dup_files = {p['file'] for p in photos if p['is_dup']}
    bad = []
    for b in bindings:
        if b['strength'] == 'C_adjacent':
            continue
        if b['photo_file'] not in photo_set:
            bad.append('%s | %s (missing photo)' % (b['code_norm'], b['photo_file']))
        elif b['photo_file'] in dup_files:
            bad.append('%s | %s (is a duplicate file)' % (b['code_norm'], b['photo_file']))
    check('A8', not bad,
          'A/B bindings reference real, non-duplicate photos', bad)

    con.close()
    print('-' * 60)
    failed = [r for r in RESULTS if not r[1]]
    if failed:
        print('RESULT: FAIL (%d)' % len(failed))
        return 1
    print('RESULT: PASS (%d checks)' % len(RESULTS))
    return 0


if __name__ == '__main__':
    sys.exit(main())
