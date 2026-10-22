# -*- coding: utf-8 -*-
"""
selftest.py -- 产品库端到端自检

    python -m tools.productlib.selftest            # 跑默认样本（真实清单 + 20 张照片）
    python -m tools.productlib.selftest --full     # 全量 249 张

用**独立测试库**（productlib/data/selftest.db），不碰正式库。
每条断言只做只读检查，除了最后一步的关联/撤销会回滚。

覆盖用户提的五条：
  1 清单导入 + 字段规范   → S1
  2 照片导入 + 治理       → S2 S3 S4
  3 自动关联              → S5 S6
  4 人工关联              → S7 S8 S9
  5 按产品看所有照片      → S10
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from tools.productlib import pipeline, schema, store, vision  # noqa: E402

DOC = os.path.join(ROOT, 'doc', 'PIDU9352234')
CHECKLIST = os.path.join(DOC, '数量检查-PIDU9352234.xls')
TEST_DB = os.path.join(ROOT, 'productlib', 'data', 'selftest.db')

PASS, FAIL = [], []


def ok(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print('[%s] %s%s' % (' OK ' if cond else 'FAIL', name,
                         ('  -- ' + detail) if detail else ''))
    return cond


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--full', action='store_true', help='全量 249 张（默认 20 张）')
    ap.add_argument('--limit', type=int, default=20)
    a = ap.parse_args()
    limit = None if a.full else a.limit

    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    con = store.connect(TEST_DB)

    print('=' * 68)
    print('产品库自检   db=%s' % TEST_DB)
    print('多模态：%s' % ('已配置' if vision.enabled() else '未配置 → 走降级路径（本次重点验证）'))
    print('=' * 68)

    # ── 第 1 条 ──────────────────────────────────────────────
    print('\n--- 第 1 条：产品清单导入 ---')
    if not os.path.exists(CHECKLIST):
        print('缺少清单文件：%s' % CHECKLIST)
        return 1
    # 2026-10-05 起 import_checklist_file 必填 container_id（柜是一等实体），
    # 这里一直漏传 → selftest 静默失修跑不过。建个柜再导。
    sel_cid = store.create_container(con, container_no='SELFTEST001',
                                     seal_no='SELFTEST',
                                     inspector='selftest')['id']
    r = store.import_checklist_file(con, CHECKLIST, container_id=sel_cid)
    n_products = con.execute('SELECT COUNT(*) FROM products').fetchone()[0]
    ok('S1a 清单解析出产品', n_products > 0,
       '解析 %d 条 → 新增 %d / 合并 %d / 跳过 %d' %
       (r['parsed'], r['added'], r['updated'], len(r['errors'])))

    bad = con.execute('SELECT COUNT(*) FROM products WHERE code IS NULL OR code=""'
                      ' OR LENGTH(code_norm)<4').fetchone()[0]
    ok('S1b 编码规范（非空 / 归一化后 ≥4 位）', bad == 0, '违规 %d 条' % bad)

    no_num = [p['code'] for p in con.execute('SELECT code FROM products')
              if not any(ch.isdigit() for ch in (p['code'] or ''))]
    ok('S1c 编码必含数字', not no_num, '违规 %s' % no_num[:3])

    # 重复导入 = 合并，不是覆盖
    before = con.execute('SELECT name,spec FROM products WHERE code_norm=?',
                         (con.execute('SELECT code_norm FROM products LIMIT 1')
                          .fetchone()[0],)).fetchone()
    store.import_checklist_file(con, CHECKLIST, container_id=sel_cid)
    after = con.execute('SELECT name,spec FROM products WHERE code_norm=?',
                        (con.execute('SELECT code_norm FROM products LIMIT 1')
                         .fetchone()[0],)).fetchone()
    ok('S1d 重复导入是合并不是覆盖', tuple(before) == tuple(after),
       '第二次导入后产品数仍为 %d' % con.execute('SELECT COUNT(*) FROM products').fetchone()[0])

    # ── 第 2 条 ──────────────────────────────────────────────
    print('\n--- 第 2 条：照片批量导入 ---')
    pr = store.add_photos(con, DOC, batch_name='selftest', container_id=sel_cid)
    n_photos = con.execute('SELECT COUNT(*) FROM photos').fetchone()[0]
    n_dup = con.execute('SELECT COUNT(*) FROM photos WHERE is_dup=1').fetchone()[0]
    ok('S2a 照片入库', n_photos > 0,
       '新增 %d 张（扫描 %d，MD5 重复 %d，分组 %d）' %
       (pr['added'], pr['stats']['total_files'], pr['stats']['dup_files'],
        pr['stats']['group_count']))
    ok('S2b 重复文件被标记而非丢弃', n_dup > 0, 'is_dup=%d' % n_dup)
    # ⚠️ 必须走 store.resolve_photo_path：2026-10-18 便携化把 photos.path 改成
    #    「相对导入根」形态（origin/PIDU.../xxx.jpg），裸 os.path.exists 会相对
    #    CWD 解析 → 249 张全判缺失（假红）。产品自己读图走的就是这个解析。
    missing = [p['file'] for p in con.execute('SELECT id,file,path FROM photos')
               if not os.path.exists(store.resolve_photo_path(
                   con, p['id'], p['path']))]
    ok('S2c 所有照片在磁盘上存在', not missing, '缺失 %d 张 %s' % (len(missing), missing[:2]))

    # ── 治理（降级路径）──────────────────────────────────────
    print('\n--- 治理（%s）---' % ('全量' if limit is None else '前 %d 张' % limit))
    t0 = time.time()
    last = {}

    def prog(done, total, fname, linked):
        last.update(done=done, total=total, linked=linked)
        if done % 20 == 0 or done == total:
            print('   [%d/%d] 已关联 %d 条 · %s' % (done, total, linked, fname))

    g = pipeline.govern_all(con, limit=limit, progress=prog)
    print('   用时 %.1fs · OCR 缓存命中 %d（缓存池 %d）' %
          (g['seconds'], g['ocr_from_cache'], g['ocr_cache_size']))
    ok('S3a 治理跑完不崩', g['done'] > 0,
       'done=%d ok=%d failed=%d skipped=%d' %
       (g['done'], g['ok'], g['failed'], g['skipped']))
    ok('S3b 无治理失败', g['failed'] == 0, 'failed=%d' % g['failed'])
    ok('S3c 降级路径照常产出分类', con.execute(
        'SELECT COUNT(*) FROM photos WHERE photo_kind IS NOT NULL').fetchone()[0] > 0,
       'kind 分布 %s' % json.dumps(store.stats(con)['by_kind'], ensure_ascii=False))
    ok('S3d OCR 缓存生效（避免每次 12 分钟）', g['ocr_from_cache'] > 0 or g['done'] == 0,
       '命中 %d / %d' % (g['ocr_from_cache'], g['done']))

    # ── 第 3 条 ──────────────────────────────────────────────
    print('\n--- 第 3 条：自动关联 ---')
    n_links = con.execute('SELECT COUNT(*) FROM links').fetchone()[0]
    low = con.execute('SELECT COUNT(*) FROM links WHERE source LIKE "auto%"'
                      ' AND confidence < ?', (schema.AUTO_LINK_THRESHOLD,)).fetchone()[0]
    ok('S5a 产出了自动关联', n_links > 0, '关联 %d 条' % n_links)
    ok('S5b 低于阈值的一律不自动关联', low == 0,
       '阈值 %.2f，违规 %d 条' % (schema.AUTO_LINK_THRESHOLD, low))
    dangling = con.execute(
        'SELECT COUNT(*) FROM links l LEFT JOIN products p ON p.code_norm=l.code_norm'
        ' WHERE p.code_norm IS NULL').fetchone()[0]
    ok('S5c 关联不指向不存在的产品', dangling == 0, '悬空 %d 条' % dangling)
    dup_link = con.execute(
        'SELECT COUNT(*) FROM (SELECT code_norm,photo_id FROM links'
        ' GROUP BY code_norm,photo_id HAVING COUNT(*)>1)').fetchone()[0]
    ok('S5d 同一对（编码,照片）不重复关联', dup_link == 0, '重复 %d 组' % dup_link)

    # 幂等：再跑一次（重置状态）不应翻倍
    snap = n_links
    con.execute("UPDATE photos SET govern_state='pending'")
    con.commit()
    g2 = pipeline.govern_all(con, limit=limit)
    n2 = con.execute('SELECT COUNT(*) FROM links').fetchone()[0]
    ok('S6 重复治理不产生重复关联', n2 == snap,
       '第一次 %d → 第二次 %d' % (snap, n2))

    # ── 第 4 条 ──────────────────────────────────────────────
    print('\n--- 第 4 条：人工关联 ---')
    un = store.unlinked_photos(con, limit=5)
    ok('S7a 工作台能取到未关联照片', len(un) > 0, '待关联 %d 张（全库）' %
       store.stats(con)['unlinked'])
    if un:
        ph = un[0]
        try:
            import build_library as BL
            idx = BL.CodeIndex([(r['code'], r['name'], r['spec'])
                                for r in con.execute('SELECT code,name,spec FROM products')])
            out = pipeline.govern_one(con, ph, idx)
            ok('S7b 单张治理可重入', True,
               'kind=%s hits=%d' % (out.get('kind'), len(out.get('hits', []))))
        except Exception as e:  # noqa: BLE001
            ok('S7b 单张治理可重入', False, str(e)[:120])

    code = con.execute('SELECT code_norm FROM products ORDER BY code_norm LIMIT 1').fetchone()[0]
    target = con.execute(
        'SELECT id FROM photos WHERE id NOT IN (SELECT photo_id FROM links WHERE code_norm=?)'
        ' LIMIT 1', (code,)).fetchone()
    if target:
        pid = target['id']
        before_n = con.execute('SELECT photo_count,manual_count FROM products'
                               ' WHERE code_norm=?', (code,)).fetchone()
        store.link(con, code, pid, source='manual', confidence=1.0,
                   evidence='selftest', created_by='tester')
        after_n = con.execute('SELECT photo_count,manual_count FROM products'
                              ' WHERE code_norm=?', (code,)).fetchone()
        ok('S8a 人工关联写入', after_n['photo_count'] == before_n['photo_count'] + 1,
           'photo_count %d → %d' % (before_n['photo_count'], after_n['photo_count']))
        ok('S8b 人工关联计入 manual_count',
           after_n['manual_count'] == before_n['manual_count'] + 1)
        who = con.execute('SELECT created_by,source FROM links WHERE code_norm=? AND photo_id=?',
                          (code, pid)).fetchone()
        ok('S8c 关联记录了是谁认定的', who['created_by'] == 'tester' and who['source'] == 'manual',
           'source=%s by=%s' % (who['source'], who['created_by']))
        n = store.unlink(con, code, pid)
        back = con.execute('SELECT photo_count FROM products WHERE code_norm=?',
                           (code,)).fetchone()[0]
        ok('S8d 撤销关联可回退', n == 1 and back == before_n['photo_count'],
           '删除 %d 条，photo_count 回到 %d' % (n, back))

    # ── 第 5 条 ──────────────────────────────────────────────
    print('\n--- 第 5 条：按产品看所有采集图片 ---')
    row = con.execute('SELECT code_norm FROM products WHERE photo_count>0 LIMIT 1').fetchone()
    if row:
        shots = store.product_photos(con, row['code_norm'])
        exist = sum(1 for s in shots
                    if os.path.exists(store.resolve_photo_path(
                        con, s['id'], s['path'])))
        ok('S10a 能列出某产品的全部照片', len(shots) > 0,
           '%s → %d 张' % (row['code_norm'], len(shots)))
        ok('S10b 列出的照片都在磁盘上', exist == len(shots),
           '%d/%d' % (exist, len(shots)))
        ok('S10c 每张照片都带关联来源', all(s['source'] for s in shots),
           '来源 %s' % json.dumps(sorted({s['source'] for s in shots}),
                                  ensure_ascii=False))
    else:
        ok('S10a 能列出某产品的全部照片', False, '没有任何产品有关联照片')

    # ── 汇总 ────────────────────────────────────────────────
    st = store.stats(con)
    print('\n' + '=' * 68)
    print('RESULT: %s  (%d passed, %d failed)' %
          ('PASS' if not FAIL else 'FAIL', len(PASS), len(FAIL)))
    print('库现状：产品 %d（有照片 %d）· 照片 %d · 关联 %d · 待治理 %d · 未关联 %d' %
          (st['products'], st['with_photos'], st['photos'], st['links'],
           st['pending'], st['unlinked']))
    print('关联来源：%s' % json.dumps(st['by_source'], ensure_ascii=False))
    print('照片分类：%s' % json.dumps(st['by_kind'], ensure_ascii=False))
    print('用时 %.1fs' % (time.time() - t0))
    if FAIL:
        print('失败项：%s' % ', '.join(FAIL))
    print('=' * 68)
    con.close()
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
