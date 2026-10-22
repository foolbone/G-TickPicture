#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
export_usage_dataset.py — 导出监装/预检二分类训练集

策略：
- 只取 photo_usage 非空、is_dup=0 的照片
- 监装 271 张全取（正样本少）
- 预检采样 800 张（与监装大致 3:1，避免类别极度不平衡）
- 80/20 train/val 划分
- 只导出文件存在的照片
"""
import sqlite3, os, shutil, random, csv
from pathlib import Path

DB = r'D:\集刻产品库\data\productlib.db'
OUT = Path(r'D:\G-TickPicture\tools\productlib\training\dataset_usage')
PRECHECK_SAMPLE = 800  # 预检采样数
VAL_RATIO = 0.2

USAGE_MAP = {'预检': 'precheck', '监装': 'supervision'}


def main():
    random.seed(42)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # 拉数据
    rows = con.execute("""
        SELECT id, file, path, photo_usage FROM photos
        WHERE photo_usage IS NOT NULL AND is_dup=0
    """).fetchall()

    by_cls = {'precheck': [], 'supervision': []}
    for r in rows:
        cls = USAGE_MAP.get(r['photo_usage'])
        if cls and os.path.isfile(r['path']):
            by_cls[cls].append(r)

    print(f'原始: precheck={len(by_cls["precheck"])}, supervision={len(by_cls["supervision"])}')

    # 采样预检到 PRECHECK_SAMPLE
    if len(by_cls['precheck']) > PRECHECK_SAMPLE:
        by_cls['precheck'] = random.sample(by_cls['precheck'], PRECHECK_SAMPLE)
    # 监装全取
    print(f'采样后: precheck={len(by_cls["precheck"])}, supervision={len(by_cls["supervision"])}')

    manifest = []
    for cls, items in by_cls.items():
        random.shuffle(items)
        n_val = max(1, int(len(items) * VAL_RATIO))
        splits = {'train': items[n_val:], 'val': items[:n_val]}

        for split, group in splits.items():
            cls_dir = OUT / split / cls
            cls_dir.mkdir(parents=True, exist_ok=True)
            for i, r in enumerate(group):
                ext = os.path.splitext(r['file'])[1] or '.jpg'
                dst = cls_dir / f'{cls}_{i:04d}{ext}'
                shutil.copy2(r['path'], dst)
                manifest.append({'split': split, 'class': cls,
                                 'photo_id': r['id'], 'src': r['path']})
            print(f'  {split}/{cls}: {len(group)}')

    con.close()

    # manifest
    with open(OUT / 'manifest.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['split', 'class', 'photo_id', 'src'])
        w.writeheader()
        w.writerows(manifest)

    print(f'\n完成: {OUT}')
    print(f'总导出: {len(manifest)} 张')


if __name__ == '__main__':
    main()
