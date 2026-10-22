#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
export_kind_dataset.py — 从**活跃库**导出预检四分类训练集
（label/product/packaging/packing_list），供 train_classifier.py --kind 训练

策略（与方案 §4.3 一致）：
- 只取 photo_usage='预检'、is_dup=0、文件存在的照片
- label 1509 张 → 采样 500（避免过多数/训练慢）
- product 382 张 → 采样 300
- packaging 186 张 → 全取
- packing_list 262 张 → 全取
- 80/20 train/val 划分
"""
import sqlite3, os, shutil, random, csv
from pathlib import Path

DB = r'D:\集刻产品库\data\productlib.db'
OUT = Path(r'D:\G-TickPicture\tools\productlib\training\dataset\kind')
VAL_RATIO = 0.2

# 类别 → 采样上限（超出则随机采样）
CLASS_CAP = {
    'label': 500,
    'product': 300,
    'packaging': 200,   # 实际186，全取
    'packing_list': 262,  # 实际262，全取
}


def main():
    random.seed(42)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # 清空旧数据集目录（可能残留开发库导出的文件，必须干净重导）
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    rows = con.execute("""
        SELECT file, path, photo_kind FROM photos
        WHERE photo_usage='预检' AND is_dup=0
          AND photo_kind IN ('label','product','packaging','packing_list')
    """).fetchall()

    by_cls = {c: [] for c in CLASS_CAP}
    for r in rows:
        k = r['photo_kind']
        if k in by_cls and os.path.isfile(r['path']):
            by_cls[k].append((r['file'], r['path']))

    for c in CLASS_CAP:
        cap = CLASS_CAP[c]
        items = by_cls[c]
        if len(items) > cap:
            by_cls[c] = random.sample(items, cap)
        print(f'{c}: 原始={len(items)}, 采样后={len(by_cls[c])}')

    manifest = []
    for cls, items in by_cls.items():
        random.shuffle(items)
        n_val = max(1, int(len(items) * VAL_RATIO))
        splits = {'train': items[n_val:], 'val': items[:n_val]}
        for split, group in splits.items():
            cls_dir = OUT / split / cls
            cls_dir.mkdir(parents=True, exist_ok=True)
            for i, (fname, fpath) in enumerate(group):
                ext = os.path.splitext(fname)[1] or '.jpg'
                dst = cls_dir / f'{cls}_{i:04d}{ext}'
                shutil.copy2(fpath, dst)
                manifest.append({'split': split, 'class': cls,
                                 'src': fpath, 'dst': str(dst)})
            print(f'  {split}/{cls}: {len(group)}')

    con.close()
    with open(OUT.parent / 'manifest_kind.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['split', 'class', 'src', 'dst'])
        w.writeheader()
        w.writerows(manifest)

    print(f'\n完成: {OUT}')
    print(f'总导出: {len(manifest)} 张')


if __name__ == '__main__':
    main()
