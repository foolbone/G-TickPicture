# -*- coding: utf-8 -*-
"""dHash 区分度抽样验证（2026-10-18，为「视觉相似度进候选打分」做先导）。

问题：微信图没有 EXIF、顺序=导入序≠拍摄序，纯顺序邻居推不准。
假设：**同件货的连拍长得像**（同主色/纹理），可以用感知哈希（dHash，纯 PIL
实现，64-bit 汉明距离）给候选加分。加之前先拿真库验证这个假设：

  A 组内对：同一 (batch_id, group_idx) 里随机照片的两两 dHash 距离
            —— 期望小（长得像）
  B 组间对：同批次但不同组的照片对 —— 期望明显更大
  C 邻域对：import_seq 相邻但不同组的照片对 —— 这是现在打分误推的重灾区

判据（先验约定，验证前写死，不许看完数据再编）：
  · A 的 P90 ≤ B 的 P50   →  组内确实显著更像，dHash 可作排序信号
  · A P90 与 B P50 之间的间隔里选阈值 T（如 18/64）：
      组内对距离 ≤ T 的比例 = 召回率（不漏），组间对 ≤ T 的比例 = 误推率
  · 邻域对（C）的分布若与 B 相近，说明「相邻即同货」确实不成立，
    dHash 加分正好补这个洞。

样本：随机抽 60 组（每组 ≤5 张，控制 PIL 解码量），全部走 thumbs 缩略图
（360px，全覆盖，view 是惰性生成的覆盖不全）。

用法：
  python -m tools.productlib.checks.dhash_probe
输出：三组分布（min/P50/P90）+ 按约定阈值的召回/误推率 + 结论。
只读库与图片，不写任何东西。
"""
import os
import random
import sqlite3
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from tools.productlib import paths  # noqa: E402

N_GROUPS = 60
PER_GROUP = 5
T = 18          # 预设阈值：64-bit 汉明距离 ≤ 18 视为「像」


def dhash(path, hash_size=8):
    """dHash：缩到 (hash_size+1)×hash_size 灰度，横相邻比大小 → 64 bit。
    只依赖 PIL，无 numpy 依赖（打包环境里保持零新增依赖）。"""
    img = Image.open(path).convert('L')
    img = img.resize((hash_size + 1, hash_size), Image.LANCZOS)
    px = list(img.getdata())
    bits = []
    for row in range(hash_size):
        base = row * (hash_size + 1)
        for col in range(hash_size):
            bits.append(1 if px[base + col] > px[base + col + 1] else 0)
    v = 0
    for b in bits:
        v = (v << 1) | b
    return v


def hamming(a, b):
    return bin(a ^ b).count('1')

def pct(sorted_vals, p):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(len(sorted_vals) * p))
    return sorted_vals[i]


def dist_stats(name, vals):
    vals = sorted(vals)
    print('  %s  n=%d  min=%s  P50=%s  P90=%s  P99=%s' % (
        name, len(vals), vals[0] if vals else '-',
        pct(vals, 0.5), pct(vals, 0.9), pct(vals, 0.99)))
    return vals


def main():
    db = sqlite3.connect(paths.db_path())
    db.row_factory = sqlite3.Row
    thumb_dir = paths.thumb_dir()
    # 随机 60 组，每组最多 5 张有 view 预览图的照片
    groups = db.execute(
        'SELECT batch_id, group_idx, COUNT(*) n FROM photos '
        'WHERE group_idx IS NOT NULL AND IFNULL(is_dup,0)=0 '
        'AND IFNULL(is_invalid,0)=0 GROUP BY batch_id, group_idx '
        'HAVING n>=2 ORDER BY RANDOM() LIMIT ?', (N_GROUPS,)).fetchall()
    hashes = {}   # (batch,group) -> [(photo_id, hash)]
    skipped = 0
    for g in groups:
        rows = db.execute(
            'SELECT id FROM photos WHERE batch_id=? AND group_idx=? '
            'AND IFNULL(is_dup,0)=0 AND IFNULL(is_invalid,0)=0 '
            'ORDER BY RANDOM() LIMIT ?', (g['batch_id'], g['group_idx'],
                                          PER_GROUP)).fetchall()
        lst = []
        for r in rows:
            fp = os.path.join(thumb_dir, '%s.jpg' % r['id'])
            if not os.path.exists(fp):
                skipped += 1
                continue
            try:
                lst.append((r['id'], dhash(fp)))
            except Exception:  # noqa: BLE001
                skipped += 1
        if len(lst) >= 2:
            hashes[(g['batch_id'], g['group_idx'])] = lst
    db.close()
    print('样本：%d 组（目标 %d，跳过无预览图 %d 张）' % (
        len(hashes), N_GROUPS, skipped))
    if len(hashes) < 10:
        print('[FAIL] 有效样本太少，结论不可信')
        return 1

    within, between, neigh = [], [], []
    keys = list(hashes.keys())
    for bi, (k, lst) in enumerate(hashes.items()):
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                within.append(hamming(lst[i][1], lst[j][1]))
        # 组间：与下一个抽到的组（同批优先找同批不同组，否则任取）比 2 对
        other = next((k2 for k2 in keys[bi + 1:] if k2[0] == k[0]), None)
        if other is None and bi + 1 < len(keys):
            other = keys[bi + 1]
        if other:
            for a in lst[:2]:
                for b in hashes[other][:2]:
                    between.append(hamming(a[1], b[1]))
    # 邻域对：同批 import_seq 相邻但不同组的照片（模拟现在的误推）
    db = sqlite3.connect(paths.db_path())
    db.row_factory = sqlite3.Row
    for k in keys[:30]:
        rows = db.execute(
            'SELECT id, group_idx, import_seq FROM photos '
            'WHERE batch_id=? AND IFNULL(is_dup,0)=0 AND IFNULL(is_invalid,0)=0 '
            'AND group_idx IS NOT NULL ORDER BY import_seq', (k[0],)).fetchall()
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            if a['group_idx'] == b['group_idx']:
                continue    # 同组相邻不算误推
            fa = os.path.join(thumb_dir, '%s.jpg' % a['id'])
            fb = os.path.join(thumb_dir, '%s.jpg' % b['id'])
            if not (os.path.exists(fa) and os.path.exists(fb)):
                continue
            try:
                neigh.append(hamming(dhash(fa), dhash(fb)))
            except Exception:  # noqa: BLE001
                pass
    db.close()

    print('\n距离分布（0=完全一样，64=完全不同）：')
    w = dist_stats('A 组内对  ', within)
    b = dist_stats('B 组间对  ', between)
    n = dist_stats('C 邻域对(异组相邻)', neigh)

    rec = sum(1 for v in w if v <= T) / max(1, len(w))
    fp_b = sum(1 for v in b if v <= T) / max(1, len(b))
    fp_n = sum(1 for v in n if v <= T) / max(1, len(n))
    print('\n按先验阈值 T=%d/64：' % T)
    print('  A 组内对 ≤T（召回，不遗漏）: %.0f%%' % (rec * 100))
    print('  B 组间对 ≤T（误推，错加分）: %.0f%%' % (fp_b * 100))
    print('  C 邻域对 ≤T（顺序误推的误推率）: %.0f%%' % (fp_n * 100))

    p90w, p50b = pct(w, 0.9), pct(b, 0.5)
    ok = p90w is not None and p50b is not None and p90w <= p50b
    print('\n判据：A P90(%s) ≤ B P50(%s) → %s' % (
        p90w, p50b, '✔ dHash 可作排序信号' if ok else '✘ 区分度不足，放弃'))
    if ok:
        print('建议：候选打分加一项「dHash 距已关联标签照 ≤%d → +%d」'
              '（只排序不加权重太大，因为误推率 %.0f%% 不为零）'
              % (T, 3, fp_b * 100))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())