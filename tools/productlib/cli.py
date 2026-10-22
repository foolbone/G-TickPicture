# -*- coding: utf-8 -*-
"""
cli.py -- 产品库命令行入口（网页之外的另一条路）

    python -m tools.productlib.cli stats
    python -m tools.productlib.cli import-checklist doc/PIDU9352234/数量检查-PIDU9352234.xls
    python -m tools.productlib.cli import-photos  doc/PIDU9352234
    python -m tools.productlib.cli govern                 # 全量
    python -m tools.productlib.cli govern --limit 20      # 先试 20 张
    python -m tools.productlib.cli link  <编码> <照片文件名片段>
    python -m tools.productlib.cli show  <编码>           # 第 5 条：看某产品的所有照片

大批量照片建议走这里，不走网页上传（不经过浏览器，不占内存）。
"""
import argparse
import json
import os
import sys

_BOOTSTRAP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

from tools.productlib import paths, pipeline, store, vision  # noqa: E402

ROOT = paths.app_root()


def _con():
    return store.connect()


def cmd_stats(a):
    c = _con()
    s = store.stats(c)
    s['vision'] = 'enabled' if vision.enabled() else 'NOT configured (degraded)'
    print(json.dumps(s, ensure_ascii=False, indent=2))
    c.close()


def cmd_import_checklist(a):
    c = _con()
    r = store.import_checklist_file(c, a.path, replace=a.replace)
    print('[ OK ] 解析 %d 条 → 新增 %d / 合并 %d / 跳过 %d'
          % (r['parsed'], r['added'], r['updated'], len(r['errors'])))
    if r['errors']:
        for e in r['errors'][:10]:
            print('  [WARN] 第 %d 行「%s」：%s'
                  % (e['line'], e['code'], '；'.join(e['errors'])))
    print('[ OK ] 产品库现有 %d 个产品' %
          c.execute('SELECT COUNT(*) FROM products').fetchone()[0])
    c.close()


def cmd_import_photos(a):
    c = _con()
    r = store.add_photos(c, a.folder, batch_name=a.name)
    print('[ OK ] 扫描 %d 张 → 新增 %d / 库内已存在跳过 %d'
          % (r['stats']['total_files'], r['added'], r['skipped']))
    print('[ OK ] MD5 重复 %d 张（不重复治理，跟随原图）'
          % r['stats']['dup_files'])
    print('[ OK ] 图片库现有 %d 张' %
          c.execute('SELECT COUNT(*) FROM photos').fetchone()[0])
    c.close()


def cmd_govern(a):
    c = _con()

    def prog(done, total, fname, linked):
        if done % 20 == 0 or done == total:
            print('   [%d/%d] 已关联 %d 条 · %s' % (done, total, linked, fname))

    r = pipeline.govern_all(c, limit=a.limit, use_vision=not a.no_vision,
                            use_ocr=not a.no_ocr, progress=prog)
    print('[ OK ] 治理 %d 张：ok=%d failed=%d 跳过(场景)=%d'
          % (r['done'], r['ok'], r['failed'], r['skipped']))
    print('[ OK ] 自动关联 %d 条（OCR 缓存命中 %d / %d，用时 %.1fs）'
          % (r['linked'], r['ocr_from_cache'], r['done'], r['seconds']))
    s = store.stats(c)
    print('[ OK ] 覆盖：%d/%d 个产品有照片；还有 %d 张未关联'
          % (s['with_photos'], s['products'], s['unlinked']))
    c.close()


def cmd_relink(a):
    """补关联：把已治理但没关联上的照片，用当前产品库重匹配一遍。

    照片先于清单导入时自动关联会全部落空（索引建自 products 表）。
    清单导入时已自动触发一次；这里用于手工兜底或改了编码后重算。
    """
    c = _con()
    r = pipeline.relink_due_to_checklist(c, limit=a.limit)
    print('[ OK ] 扫描 %d 张候选照片，%d 张有命中，写入 %d 条关联'
          % (r['scanned'], r['candidates'], r['written']))
    s = store.stats(c)
    print('[ OK ] 覆盖：%d/%d 个产品有照片；还有 %d 张未关联'
          % (s['with_photos'], s['products'], s['unlinked']))
    c.close()


def cmd_regroup(a):
    """按拍照时间重算照片分组（去掉旧口径「满 12 张就切一组」）。

    一次连拍十几张是常态，旧口径会把一段连拍切成好几个组，同组推荐因此断开。
    重算只改 group_idx，不动关联、不动文件、不重跑识别。
    先跑 --dry-run 看影响，确认了再真跑。
    """
    c = _con()
    r = store.regroup_photos_by_time(c, batch_id=a.batch, dry_run=a.dry_run,
                                     gap_sec=a.gap or None,
                                     max_per_group=a.max or None,
                                     split_by_dir=not a.no_dir_split)
    mark = '试算' if r['dry_run'] else '已重算'
    print('[ OK ] %s：照片 %d 张 / 批次 %d 个；分组 %d 组 → %d 组（%d 张的组别变了）'
          % (mark, r['photos'], r['batches'], r['groups_before'],
             r['groups_after'], r['changed']))
    print('[ .. ] 切分间隔 %d 秒 · 每组最多 %d 张 · 重算后最大组 %d 张'
          % (r['gap_sec'], r['max_per_group'], r['max_group_size']))
    print('[ .. ] 按文件夹强制切组：%s'
          % ('开' if r.get('split_by_dir') else '关'))
    if r['dry_run']:
        print('[ .. ] 这是试算，没写库。确认无误去掉 --dry-run 再跑一次。')
    c.close()


def cmd_link(a):
    c = _con()
    ph = c.execute('SELECT id,file FROM photos WHERE file LIKE ? LIMIT 1',
                   ('%' + a.photo + '%',)).fetchone()
    if not ph:
        print('[FAIL] 找不到照片：%s' % a.photo)
        return 1
    p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                  (a.code, a.code)).fetchone()
    if not p:
        print('[FAIL] 产品库里没有这个编码：%s' % a.code)
        return 1
    store.link(c, p['code_norm'], ph['id'], source='manual', confidence=1.0,
               evidence='cli 人工关联', created_by=a.by or 'cli')
    print('[ OK ] 已关联 %s ← %s' % (p['code_norm'], ph['file']))
    c.close()


def cmd_show(a):
    """第 5 条：一个产品的所有预检采集图片。"""
    c = _con()
    p = c.execute('SELECT * FROM products WHERE code_norm=? OR code=?',
                  (a.code, a.code)).fetchone()
    if not p:
        print('[FAIL] 产品库里没有这个编码：%s' % a.code)
        return 1
    print('%s  %s  %s' % (p['code'], p['name'] or '', p['spec'] or ''))
    print('-' * 72)
    for s in store.product_photos(c, p['code_norm']):
        print('  %-28s %-12s %-8s %.2f  %s'
              % (s['file'], s['photo_kind'] or '-', s['source'],
                 s['confidence'] or 0, s['taken_at'][:19]))
    c.close()


def main():
    ap = argparse.ArgumentParser(description='集刻 产品库 CLI')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('stats').set_defaults(fn=cmd_stats)

    p = sub.add_parser('import-checklist')
    p.add_argument('path')
    p.add_argument('--replace', action='store_true',
                   help='整体覆盖已有字段（默认合并：新值非空才覆盖）')
    p.set_defaults(fn=cmd_import_checklist)

    p = sub.add_parser('import-photos')
    p.add_argument('folder')
    p.add_argument('--name', default='')
    p.set_defaults(fn=cmd_import_photos)

    p = sub.add_parser('govern')
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--no-vision', action='store_true')
    p.add_argument('--no-ocr', action='store_true')
    p.set_defaults(fn=cmd_govern)

    p = sub.add_parser('relink')
    p.add_argument('--limit', type=int, default=None)
    p.set_defaults(fn=cmd_relink)

    p = sub.add_parser('regroup')
    p.add_argument('--batch', default=None, help='只重算某个批次（默认全部）')
    p.add_argument('--gap', type=int, default=None,
                   help='切分间隔（秒），默认 45')
    p.add_argument('--max', type=int, default=None,
                   help='每组最多几张（安全阀），默认 30')
    p.add_argument('--dry-run', action='store_true', help='只统计，不写库')
    p.add_argument('--no-dir-split', action='store_true',
                   help='不按文件夹强制切组（默认：换文件夹就换一组）')
    p.set_defaults(fn=cmd_regroup)

    p = sub.add_parser('link')
    p.add_argument('code')
    p.add_argument('photo')
    p.add_argument('--by', default='cli')
    p.set_defaults(fn=cmd_link)

    p = sub.add_parser('show')
    p.add_argument('code')
    p.set_defaults(fn=cmd_show)

    a = ap.parse_args()
    return a.fn(a) or 0


if __name__ == '__main__':
    sys.exit(main())
