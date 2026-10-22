# -*- coding: utf-8 -*-
"""
pc_ocr_probe.py -- PP-OCRv6 桌面预演探针

目的：在真机验证之前，用 PC 上的 ONNX Runtime 完全复刻
OnnxPpOcrEngine.kt 的前/后处理，跑真实照片，验证：
  1) 前处理参数（det: BGR+ImageNet mean/std；rec: (x/255-0.5)/0.5 + 中灰补边）
  2) 字典布局（0=blank, 1..18708=keys, 18709=space）
  3) DBPostProcess 逻辑（thresh 0.2 / box_thresh 0.45 / unclip 1.4）
  4) 得到真实识别率基线（打印体装箱单 vs 手写标识卡）

与 Kotlin 的有意一致处：
  - det 按总像素缩到 ~700_000（有意偏离官方 736/min）
  - 轴对齐裁剪（不做透视矫正）
  - 不做方向分类（四方向实验单独量化其代价）

用法：
  python pc_ocr_probe.py --limit 6     # 抽样调试
  python pc_ocr_probe.py --full        # 全量 249 张（慢，后台跑）
"""
import argparse
import json
import math
import os


# ---------------- 模型目录：多路径探测（绝不能硬编码绝对路径）----------------
# 🔴 2026-10-06 事故：这里原是 `ASSETS = r"D:\G-TickPicture\app\android\..."`，
#    换一台电脑（尤其跑打包版）该路径不存在 → import 时 InferenceSession 直接抛
#    FileNotFoundError → 治理里每张照片都 failed，且用户只看到"失败率很高"，
#    看不到任何可操作线索。**开发机的绝对路径不能出现在任何产品代码里。**
def _find_assets():
    """按优先级找 PP-OCR 模型目录。返回第一个存在的；都不存在则给出可操作提示。

    优先级（覆盖开发 / 打包 / 拷贝到任意位置三种形态）：
      1. 环境变量 PL_OCR_ASSETS        —— 显式指定，最高优先
      2. 打包版：<exe 同级>/ocr         —— build_portable.py 放的位置
      3. 打包版：sys._MEIPASS/ocr      —— spec 的 datas 收进去的位置
      4. 仓库内 app/android/.../assets/ppocr  —— 开发态（相对本文件上溯）
      5. exe 同级 data/ocr             —— 用户手动放了模型的兜底
    """
    import sys
    cands = []
    env = (os.environ.get('PL_OCR_ASSETS') or '').strip()
    if env:
        cands.append(env)
    frozen = bool(getattr(sys, 'frozen', False))
    if frozen:
        base = os.path.dirname(os.path.abspath(sys.executable))
        cands.append(os.path.join(base, 'ocr'))
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            cands.append(os.path.join(meipass, 'ocr'))
        cands.append(os.path.join(base, 'data', 'ocr'))
    here = os.path.dirname(os.path.abspath(__file__))          # <仓库根>/tools
    cands.append(os.path.join(
        os.path.dirname(here), 'app', 'android', 'app', 'src', 'main',
        'assets', 'ppocr'))
    cands.append(os.path.join(here, 'ppocr_assets'))           # 就近放一份的兜底

    for d in cands:
        if d and os.path.isfile(os.path.join(d, 'det.onnx')) \
                and os.path.isfile(os.path.join(d, 'rec.onnx')) \
                and os.path.isfile(os.path.join(d, 'keys.txt')):
            return os.path.abspath(d)
    raise FileNotFoundError(
        '找不到 PP-OCR 模型（需要 det.onnx / rec.onnx / keys.txt 三个文件）。\n'
        '已找过：\n  ' + '\n  '.join(cands) + '\n'
        '解决办法（任选一个）：\n'
        '  1) 把整个模型目录复制到产品库 exe 同级的 ocr\\ 目录下\n'
        '  2) 设环境变量 PL_OCR_ASSETS 指向模型目录\n'
        '  3) 不想用本地 OCR：在「预检照片库 → 治理」里不勾 OCR，只用视觉 API')


ASSETS = _find_assets()
import sys
import time

# 🔴 numpy / cv2 / onnxruntime 是**可选的重型依赖**（opencv 约 60MB、onnxruntime 约
#    15MB、numpy 约 30MB）。历史上曾只把 cv2/onnxruntime 包进 try，`import numpy`
#    却留在外面 —— 10-19 事故：后端 python 缺 numpy → import 直接 ModuleNotFoundError
#    冒泡 → 调用方 try/except 一吞，治理静默"读不出编码"，用户只看到"无OCR文本"，
#    完全不知道是环境缺包。这里把 numpy 一并软失败：
#    缺任意一个 → OCR_AVAILABLE=False + OCR_MISSING 说明原因，由调用方报给用户
#    （铁律：失败必须给原因）。
try:
    import numpy as np
    import cv2
    import onnxruntime as ort
    OCR_AVAILABLE = True
    OCR_MISSING = ''
except ImportError as _e:                     # noqa: BLE001
    np = None
    cv2 = None
    ort = None
    OCR_AVAILABLE = False
    OCR_MISSING = ('本地 OCR 不可用：缺少 %s。'
                   '装上即可（或在治理时不勾 OCR，只用多模态视觉识别）：'
                   'pip install %s'
                   % (_e.name or '依赖',
                      'numpy opencv-python onnxruntime'))

# ---------------- 常量（与 OnnxPpOcrEngine.kt 逐项一致） ----------------
# ⚠️ ASSETS 已在上面的 _find_assets() 里定死（多路径探测）。
#    这里**绝不能再写死绝对路径** —— 曾经两份并存，后一份把探测结果覆盖回去，
#    换电脑照样 100% 失败（2026-10-06，G1c 断言抓到的）。
DET_TARGET_PIXELS = 700_000
BIN_THRESHOLD = 0.2
BOX_THRESHOLD = 0.45
UNCLIP_RATIO = 1.4
MAX_CANDIDATES = 3000
REC_H = 48
REC_W = 320
MIN_BOX_PX = 8.0
MIN_ASPECT = 0.33
MAX_ASPECT = 40.0
NMS_IOU = 0.5
if OCR_AVAILABLE:
    DET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)  # 按 BGR 序施加
    DET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    # ---------------- 模型与字典 ----------------
    # 🔴 线程数上限 4（2026-10-17）：曾经 = 核数-1，治理一跑就把整机吃满
    #    （实测 8 核机器 6 核满转近 3 小时），前端每个请求（缩略图/列表）都
    #    排队变慢 —— 「整个系统都很慢」的元凶。OCR 不是独占进程，服务进程
    #    还要伺候 Web 请求，最多给 4 个推理线程。
    sess_opt = ort.SessionOptions()
    sess_opt.intra_op_num_threads = max(2, min(4, (os.cpu_count() or 4) - 1))
    det_sess = ort.InferenceSession(
        os.path.join(ASSETS, "det.onnx"), sess_opt, providers=["CPUExecutionProvider"])
    rec_sess = ort.InferenceSession(
        os.path.join(ASSETS, "rec.onnx"), sess_opt, providers=["CPUExecutionProvider"])
    DET_IN = det_sess.get_inputs()[0].name
    REC_IN = rec_sess.get_inputs()[0].name

    keys = [""]  # 下标 0 = CTC blank 占位
    with open(os.path.join(ASSETS, "keys.txt"), "r", encoding="utf-8") as f:
        for line in f:  # 只去行尾 \r\n，绝不能 strip()（U+3000 陷阱）
            keys.append(line.rstrip("\r\n"))
    keys.append(" ")  # 下标 18709 = 半角空格
    NCLS = rec_sess.get_outputs()[0].shape[-1]
    assert len(keys) == NCLS, "字典 %d != rec 输出维度 %d" % (len(keys), NCLS)
    print("模型就绪: det=%s rec 输出末维=%d 字典=%d (1+N+1)"
          % (det_sess.get_outputs()[0].shape, NCLS, len(keys)))
else:
    # 依赖缺失：给调用方/函数一个可读的"不可用"状态，避免 NameError。
    DET_MEAN = DET_STD = None
    det_sess = rec_sess = None
    DET_IN = REC_IN = None
    keys = []
    NCLS = 0


# ---------------- det：前处理 ----------------
def det_input(img_bgr):
    h, w = img_bgr.shape[:2]
    npix = h * w
    scale = 1.0
    if npix > DET_TARGET_PIXELS:
        scale = math.sqrt(DET_TARGET_PIXELS / npix)
    # 必须 roundup 到 32 的倍数：det 内部 U-Net 跳连 Add 要求上采样特征图
    # 与 skip 严格对齐（官方 DetResizeForTest 也有同样的 roundup 逻辑）。
    # 坑：4 对齐不够 —— 61x62 时 Add.178 直接 61-by-62 广播崩。
    nw = max(32, int(math.ceil(w * scale / 32.0)) * 32)
    nh = max(32, int(math.ceil(h * scale / 32.0)) * 32)
    small = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x = small.astype(np.float32) / 255.0
    # PaddleOCR 怪癖：img_mode=BGR 时 normalize 不翻转通道，mean[0]=0.485
    # 直接施加在 B 通道上（与 Kotlin detInput 的 b-DET_MEAN[0] 一致）
    x = (x - DET_MEAN) / DET_STD
    x = x.transpose(2, 0, 1)[None]  # CHW
    return x, small


# ---------------- det：DBPostProcess（复刻 Kotlin boxesFromProbMap） ----------------
def boxes_from_prob_map(prob, orig_w, orig_h, scale):
    """prob: [H,W] 概率图。返回原图坐标的框列表 [(x0,y0,x1,y1,score)]"""
    binary = (prob >= BIN_THRESHOLD).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    cand = []
    ph, pw = prob.shape
    sx = orig_w / pw
    sy = orig_h / ph
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if bw < MIN_BOX_PX or bh < MIN_BOX_PX:
            continue
        if bw / bh < MIN_ASPECT or bw / bh > MAX_ASPECT:
            continue
        mask = labels[by:by + bh, bx:bx + bw] == i
        score = float(prob[by:by + bh, bx:bx + bw][mask].mean())
        if score < BOX_THRESHOLD:
            continue
        # unclip: 轴对齐四边外扩 d = area*ratio/perimeter
        d = bw * bh * UNCLIP_RATIO / (2.0 * (bw + bh))
        # ⚠️ 概率图坐标 -> 原图坐标是**乘**（sx>1）。写成除法会把所有框
        # 压进左上角一小块（探针首版踩过，Kotlin 端是乘法、正确）。
        x0 = (bx - d) * sx
        y0 = (by - d) * sy
        x1 = (bx + bw + d) * sx
        y1 = (by + bh + d) * sy
        x0 = max(0.0, x0); y0 = max(0.0, y0)
        x1 = min(float(orig_w), x1); y1 = min(float(orig_h), y1)
        cand.append([x0, y0, x1, y1, score, (x1 - x0) * (y1 - y0)])
    cand.sort(key=lambda b: -b[5])
    keep = []
    for b in cand:
        ok = True
        for k in keep:
            iou = iou_of(b, k)
            if iou > NMS_IOU:
                ok = False
                break
        if ok:
            keep.append(b)
        if len(keep) >= MAX_CANDIDATES:
            break
    return keep


def iou_of(a, b):
    ix0 = max(a[0], b[0]); iy0 = max(a[1], b[1])
    ix1 = min(a[2], b[2]); iy1 = min(a[3], b[3])
    iw = max(0.0, ix1 - ix0); ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


# ---------------- rec：前处理 + CTC（复刻 Kotlin recognizeCrop） ----------------
def rec_input(crop_bgr):
    h, w = crop_bgr.shape[:2]
    if h < 2 or w < 2:
        return None
    ratio = w / float(h)
    tw = int(math.ceil(REC_H * ratio))
    tw = max(1, min(REC_W, tw))
    im = cv2.resize(crop_bgr, (tw, REC_H), interpolation=cv2.INTER_LINEAR)
    x = im.astype(np.float32) / 255.0
    x = (x - 0.5) / 0.5
    canvas = np.zeros((REC_H, REC_W, 3), dtype=np.float32)  # 0.0 = 中灰填充
    canvas[:, :tw, :] = x
    return canvas.transpose(2, 0, 1)[None]


def ctc_decode(logits):
    """logits: [T, C]。返回 (text, mean_conf)"""
    ids = logits.argmax(axis=1)
    probs = logits.max(axis=1)
    out = []
    confs = []
    prev = -1
    for t, idx in enumerate(ids):
        if idx != prev and idx != 0:  # 去重 + 去 blank
            out.append(keys[idx])
            confs.append(float(probs[t]))
        prev = idx
    text = "".join(out)
    conf = sum(confs) / len(confs) if confs else 0.0
    return text, conf


def recognize(crop_bgr):
    x = rec_input(crop_bgr)
    if x is None:
        return "", 0.0
    out = rec_sess.run(None, {REC_IN: x})[0][0]  # [T, C]
    return ctc_decode(out)


# rec 是逐框跑的；det 误检多的照片（塑料袋反光）会出几百个框，
# rec 直接爆炸（实测单张 16s）。与将来 Kotlin 端要做的一样：只把
# 面积最大的前 MAX_REC_CROPS 个框送识别。
MAX_REC_CROPS = 40


def rotate(img, code):
    if code == 0:
        return img
    return cv2.rotate(img, code)


# ---------------- 主流程 ----------------
def run_photo(path, four_dir=False):
    if not OCR_AVAILABLE:
        return {"file": os.path.basename(path), "error": OCR_MISSING,
                "texts": [], "boxes": 0, "det_s": 0.0, "rec_s": 0.0}
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"file": os.path.basename(path), "error": "decode"}
    oh, ow = img.shape[:2]
    x, small = det_input(img)
    t0 = time.time()
    prob = det_sess.run(None, {DET_IN: x})[0][0, 0]
    t_det = time.time() - t0
    boxes = boxes_from_prob_map(prob, ow, oh, 1.0)
    boxes = boxes[:MAX_REC_CROPS]  # 已按面积降序
    texts = []
    t_rec = 0.0
    for (x0, y0, x1, y1, sc, _) in boxes:
        ix0, iy0, ix1, iy1 = int(x0), int(y0), int(x1), int(y1)
        crop = img[max(0, iy0):iy1, max(0, ix0):ix1]
        if crop.size == 0:
            continue
        t1 = time.time()
        if four_dir:
            best = ("", 0.0)
            for code in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
                c = rotate(crop, code) if code is not None else crop
                txt, cf = recognize(c)
                if len(txt) * cf > len(best[0]) * best[1]:
                    best = (txt, cf)
            texts.append({"t": best[0], "c": round(best[1], 3), "rot": "4dir",
                          "box": [ix0, iy0, ix1, iy1]})
        else:
            txt, cf = recognize(crop)
            texts.append({"t": txt, "c": round(cf, 3),
                          "box": [ix0, iy0, ix1, iy1]})
        t_rec += time.time() - t1
    return {"file": os.path.basename(path), "boxes": len(boxes),
            "det_s": round(t_det, 3), "rec_s": round(t_rec, 3),
            "texts": texts, "det_boxes": boxes}


def det_boxes_multi(path, dirs=(0, 1, 2)):
    """整图多方向 det 合并：对原图及旋转 ±90° 分别跑文本检测，把旋转图的
    框坐标换算回原图，合并返回（原图坐标系 [x0,y0,x1,y1,score]）。

    背景：det 模型对竖排（旋转 90°）的小字标签文字召回弱（如一张竖排 label
    只在 0° 检出右半 2 框、漏左半 PNUM/PNAME）。把整图旋转 ±90° 再 det 能补
    回竖排字段，合并框后聚类区即可覆盖完整标签，避免裁剪把标签一部分裁掉。

    坐标系换算（cv2.rotate，新图点 (x,y)）：
      ROTATE_90_CLOCKWISE        -> 原图 (y, ow-1-x)
      ROTATE_90_COUNTERCLOCKWISE -> 原图 (oh-1-y, x)
    dirs: 0=原图, 1=顺时针90°, 2=逆时针90°（默认全开）
    """
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return []
    oh, ow = img.shape[:2]
    allb = []
    for d in dirs:
        w = img
        if d == 1:
            w = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif d == 2:
            w = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        wh, ww = w.shape[:2]
        xin, small = det_input(w)
        prob = det_sess.run(None, {DET_IN: xin})[0][0, 0]
        boxes = boxes_from_prob_map(prob, ww, wh, 1.0)
        for (x0, y0, x1, y1, sc, _) in boxes:
            if d == 1:
                px0, py0, px1, py1 = int(y0), ow - 1 - int(x1), int(y1), ow - 1 - int(x0)
            elif d == 2:
                px0, py0, px1, py1 = int(x0), oh - 1 - int(y1), int(x1), oh - 1 - int(y0)
            else:
                px0, py0, px1, py1 = int(x0), int(y0), int(x1), int(y1)
            allb.append([px0, py0, px1, py1, float(sc)])
    return allb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--four-dir", action="store_true", help="四方向 rec 实验（量化不做 Cls 的代价）")
    ap.add_argument("--out", default=r"C:\Users\Bone\AppData\Local\Temp\gt_ocr_probe_out.json")
    args = ap.parse_args()

    files = sorted(os.listdir(r"D:\G-TickPicture\doc\PIDU9352234"))
    files = [f for f in files if f.lower().endswith(".jpg")]
    if not args.full:
        files = files[: args.limit]

    results = []
    t_all = time.time()
    for i, f in enumerate(files, 1):
        r = run_photo(os.path.join(r"D:\G-TickPicture\doc\PIDU9352234", f), args.four_dir)
        results.append(r)
        joined = " | ".join(t["t"] for t in r["texts"] if t["t"])[:150]
        print("[%3d/%d] %-36s boxes=%2d det=%.2fs rec=%.2fs  %s"
              % (i, len(files), r["file"], r.get("boxes", 0),
                 r.get("det_s", 0), r.get("rec_s", 0), joined))
    with open(args.out, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=1)
    print("共 %d 张，总耗时 %.1fs -> %s" % (len(results), time.time() - t_all, args.out))


if __name__ == "__main__":
    main()
