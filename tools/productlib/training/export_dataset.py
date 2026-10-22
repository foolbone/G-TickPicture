#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
export_dataset.py — 从 productlib.db 导出标注图片到分类目录

用法:
  python export_dataset.py [--out D:/dataset] [--val-ratio 0.15] [--include-unknown]

输出结构:
  dataset/
    kind/                    ← 照片五分类（label/product/packing_list/packaging）
      train/label/...
      train/product/...
      val/label/...
      val/product/...
    usage/                   ← 用途二分类（precheck/supervision）
      train/precheck/...
      train/supervision/...
      val/precheck/...
      val/supervision/...
    manifest.csv             ← 文件清单+标签元信息
"""
import argparse, os, sqlite3, shutil, random, csv
from pathlib import Path

DB = r'D:\G-TickPicture\productlib\data\productlib.db'

# photo_kind 训练类别（排除 unknown，scene 只有17张太少也排除）
KIND_CLASSES = ['label', 'product', 'packing_list', 'packaging']
# photo_usage 类别映射
USAGE_MAP = {'预检': 'precheck', '监装': 'supervision'}


def export_kind(con, out_dir, val_ratio, include_unknown=False):
    """导出 photo_kind 分类数据集"""
    rows = con.execute("""
        SELECT file, path, photo_kind FROM photos
        WHERE govern_state='done' AND photo_kind IS NOT NULL AND is_dup=0
    """).fetchall()

    # 过滤类别
    valid = set(KIND_CLASSES)
    if include_unknown:
        valid.add('unknown')
    rows = [r for r in rows if r[2] in valid]

    # 按类别分组
    by_cls = {}
    for f, p, k in rows:
        by_cls.setdefault(k, []).append((f, p))

    kind_dir = Path(out_dir) / 'kind'
    manifest = []

    for cls, items in by_cls.items():
        random.shuffle(items)
        n_val = max(1, int(len(items) * val_ratio))
        splits = {'train': items[n_val:], 'val': items[:n_val]}

        for split, group in splits.items():
            cls_dir = kind_dir / split / cls
            cls_dir.mkdir(parents=True, exist_ok=True)
            for i, (fname, fpath) in enumerate(group):
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1] or '.jpg'
                dst = cls_dir / f'{cls}_{i:04d}{ext}'
                shutil.copy2(fpath, dst)
                manifest.append({'split': split, 'class': cls,
                                 'src': fpath, 'dst': str(dst)})

        print(f'  kind/{cls}: {len(items)} (train={len(items)-n_val}, val={n_val})')

    return manifest


def export_usage(con, out_dir, val_ratio):
    """导出 photo_usage 二分类数据集"""
    rows = con.execute("""
        SELECT file, path, photo_usage FROM photos
        WHERE photo_usage IS NOT NULL AND is_dup=0
    """).fetchall()

    by_cls = {}
    for f, p, u in rows:
        cls = USAGE_MAP.get(u)
        if cls:
            by_cls.setdefault(cls, []).append((f, p))

    usage_dir = Path(out_dir) / 'usage'

    for cls, items in by_cls.items():
        random.shuffle(items)
        n_val = max(1, int(len(items) * val_ratio))
        splits = {'train': items[n_val:], 'val': items[:n_val]}

        for split, group in splits.items():
            cls_dir = usage_dir / split / cls
            cls_dir.mkdir(parents=True, exist_ok=True)
            for i, (fname, fpath) in enumerate(group):
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1] or '.jpg'
                dst = cls_dir / f'{cls}_{i:04d}{ext}'
                shutil.copy2(fpath, dst)

        print(f'  usage/{cls}: {len(items)} (train={len(items)-n_val}, val={n_val})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=r'D:\G-TickPicture\tools\productlib\training\dataset',
                    help='输出目录')
    ap.add_argument('--val-ratio', type=float, default=0.15, help='验证集比例')
    ap.add_argument('--include-unknown', action='store_true',
                    help='是否把 unknown 类别也导出（默认不导出）')
    args = ap.parse_args()

    random.seed(42)
    con = sqlite3.connect(DB)

    print('导出 photo_kind 分类数据集...')
    manifest = export_kind(con, args.out, args.val_ratio, args.include_unknown)

    print('\n导出 photo_usage 二分类数据集...')
    export_usage(con, args.out, args.val_ratio)

    # 写 manifest
    mpath = Path(args.out) / 'manifest.csv'
    with open(mpath, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['split', 'class', 'src', 'dst'])
        w.writeheader()
        w.writerows(manifest)

    con.close()
    print(f'\n完成！数据集目录: {args.out}')
    print(f'Manifest: {mpath}')
    print(f'\n训练下一步: python train_classifier.py --kind')


if __name__ == '__main__':
    main()
