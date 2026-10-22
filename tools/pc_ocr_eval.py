# -*- coding: utf-8 -*-
"""
pc_ocr_eval.py -- 全量跑 249 张真实照片 + 清单编码匹配统计。

指标：
  1) 照片命中率：多少照片至少识别出一个清单编码（-> OCR 建议的可用面）
  2) 清单覆盖率：82 个唯一编码里多少被至少一张照片命中（-> 缺口视图的参考）
  3) 分类统计：装箱单(打印) / 标识卡(手写) / 外观(少字) 分开看
"""
import json
import os
import re
import sys
import time

sys.argv = ["x"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pc_ocr_probe as P  # noqa: E402

import openpyxl  # noqa: E402

PHOTO_DIR = r"D:\G-TickPicture\doc\PIDU9352234"
XLSX = r"D:\G-TickPicture\doc\数量检查-PIDU9352234.xlsx"
OUT = r"C:\Users\Bone\AppData\Local\Temp\gt_ocr_eval_out.json"


def load_codes():
    ws = openpyxl.load_workbook(XLSX, data_only=True).worksheets[0]
    rows = [r for r in ws.iter_rows(values_only=True)][1:]
    codes = set()
    for r in rows:
        if r[1] is None:
            continue
        c = str(r[1]).strip()
        if c:
            codes.add(c)
    return sorted(codes)


def norm(s):
    return re.sub(r"\s+", "", s).upper()


def fix_shape(s):
    # 与 App 的 code_matcher 相同的四条纠偏（O->0 / I->1 / L->1 / S->5）
    return s.replace("O", "0").replace("I", "1").replace("L", "1").replace("S", "5")


def match_texts(texts, codes):
    """返回 (命中的编码集合, 是否命中)"""
    joined = norm(" ".join(t["t"] for t in texts))
    fixed = fix_shape(joined)
    hit = set()
    for c in codes:
        cn = norm(c)
        if cn in joined or cn in fixed or fix_shape(cn) in fixed:
            hit.add(c)
    return hit


def main():
    codes = load_codes()
    print("清单唯一编码: %d" % len(codes))
    files = sorted(f for f in os.listdir(PHOTO_DIR) if f.lower().endswith(".jpg"))
    results = []
    t_all = time.time()
    for i, f in enumerate(files, 1):
        try:
            r = P.run_photo(os.path.join(PHOTO_DIR, f))
        except Exception as e:  # noqa: BLE001
            r = {"file": f, "error": str(e)[:120]}
        r["hits"] = sorted(match_texts(r.get("texts", []), codes)) if "error" not in r else []
        results.append(r)
        nh = len(r["hits"])
        tail = ("HIT:" + ",".join(r["hits"][:3]) + (".." if nh > 3 else "")) if nh else ""
        line = "[%3d/%d] %-40s boxes=%3s" % (i, len(files), r.get("boxes", "-"), "") + " " + tail
        print(line)
        if i % 25 == 0:
            print("   ... 已完成 %d 张，累计 %.0fs" % (i, time.time() - t_all))
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=1)

    ok = [r for r in results if "error" not in r]
    hit_photos = [r for r in ok if r["hits"]]
    all_hits = set()
    for r in hit_photos:
        all_hits.update(r["hits"])
    tot_det = sum(r.get("det_s", 0) for r in ok)
    tot_rec = sum(r.get("rec_s", 0) for r in ok)
    print("=" * 60)
    print("照片总数 %d（解码失败 %d）" % (len(results), len(results) - len(ok)))
    print("照片命中率: %d/%d = %.1f%%" % (len(hit_photos), len(ok), 100.0 * len(hit_photos) / max(1, len(ok))))
    print("清单覆盖率: %d/%d = %.1f%%" % (len(all_hits), len(codes), 100.0 * len(all_hits) / len(codes)))
    print("平均 det=%.2fs rec=%.2fs（每张）" % (tot_det / max(1, len(ok)), tot_rec / max(1, len(ok))))
    print("明细 -> %s" % OUT)
    miss = sorted(set(codes) - all_hits)
    print("未覆盖编码(%d): %s" % (len(miss), ", ".join(miss[:20])))


if __name__ == "__main__":
    main()
