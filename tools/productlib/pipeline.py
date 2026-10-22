# -*- coding: utf-8 -*-
"""
pipeline.py -- 治理管道与自动关联（第 2、3 条）

═══════════════════════════════════════════════════════════════════════
管道顺序：为什么要先分类
═══════════════════════════════════════════════════════════════════════
实测 249 张真实照片：86% 有文字，但**只有 4.2% 命中产品编码**。
其余文字是车牌、集装箱号、公司名 —— 与产品无关。

不分类就全跑 OCR，等于把 96% 的算力喂给噪声。所以：

  ① 分类（多模态优先，无 key 时降级）
  ② 分路：
       scene（无产品信息）  → 标记 skipped，**不跑 OCR**
       packing_list        → 跑 OCR 提取参考文字，但**不关联产品**（物料清单是多编码文档）
       label / unknown     → 跑 OCR 精确读码，命中则自动关联
       product / packaging → 多模态出描述（无码，靠语义）
  ③ 融合关联：OCR 编码 → 多模态编码 → 语义提示
  ④ 高置信自动关联，低置信与无信号的进人工工作台
  ⑤ 物料清单 / 车辆 / 车牌等照片（NO_LINK_KINDS）**绝不写关联** ——
     只提取内容用于展示，关联由人决定，但这几类本就不该关联（见 schema.NO_LINK_KINDS）

═══════════════════════════════════════════════════════════════════════
降级：没配多模态 API 时
═══════════════════════════════════════════════════════════════════════
拿不到分类能力 → **全部跑 OCR**，再用 OCR 结果反推分类：
  命中编码 → packing_list/label；有文字无编码 → unknown；无文字 → scene。
功能完整，只是省算力的收益没了、无码照片拿不到描述。
**不配 key 不等于不能用。**
"""
import hashlib
import json
import os
import threading
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_library as BL  # noqa: E402

from . import schema, store, vision, govern_classifier  # noqa: E402

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'productlib', 'data')

# ═══════════════════════════════════════════════════════════════════
# OCR 缓存
# ═══════════════════════════════════════════════════════════════════
# 实测：249 张照片全量 OCR ≈ 700s；有缓存二次运行 ≈ 5s。
# 治理是必然要反复调的（阈值、分路规则、纠偏表），不缓存等于每次付 12 分钟。
# 与 build_library.run_ocr 用同一种 JSON 结构，两边缓存可以互相复用。

OCR_CACHE_PATH = os.path.join(DATA_DIR, '_ocr_cache.json')

# P1 已经用 pc_ocr_probe 跑过同一批照片 —— 直接认它的缓存，不重跑
LEGACY_CACHE_PATHS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'library', '_ocr_cache.json'),
]

_OCR_CACHE = {}
# 并行治理（2026-10-18）：多任务线程共享此缓存 dict —— 所有读写拿锁。
# 最坏情况是某条新缓存晚一轮落盘（下轮重跑时重新 OCR），不丢识别数据。
_OCR_LOCK = threading.Lock()


def load_ocr_cache():
    """合并自身缓存 + 历史缓存。自身优先（更新的为准）。"""
    global _OCR_CACHE
    merged = {}
    for p in list(LEGACY_CACHE_PATHS) + [OCR_CACHE_PATH]:
        if not os.path.exists(p):
            continue
        try:
            with open(p, 'r', encoding='utf-8') as f:
                for r in json.load(f):
                    if r.get('error'):
                        continue
                    merged[r['file']] = r
        except Exception:  # noqa: BLE001  缓存坏了就当没有，不阻塞治理
            continue
    with _OCR_LOCK:
        _OCR_CACHE = merged
    return len(merged)


def save_ocr_cache():
    with _OCR_LOCK:
        return _save_ocr_cache_locked()


def _save_ocr_cache_locked():
    os.makedirs(DATA_DIR, exist_ok=True)
    dump = []
    for k, v in _OCR_CACHE.items():
        d = dict(v)          # 缓存条目自带 file 键，不能直接 dict(file=k, **v)
        d['file'] = k
        dump.append(d)
    with open(OCR_CACHE_PATH, 'w', encoding='utf-8') as f:
        # 2026-10-09 性能：这函数在治理里**每 25 张被调用一次**，而它做的却是
        # 全量重写 —— 是 O(缓存总量) 的活，缓存越大、调用越频繁，浪费越明显。
        #   ① 去掉 indent=1：缓存文件不需要给人读，格式化输出在这里纯属白烧 CPU；
        #   ② 去掉 sorted()：字典顺序对缓存没有意义（Python dict 本就有稳定插入序）。
        # 彻底解法是迁进 SQLite 表做增量写入（见性能优化方案 P1-B），本次先降开销。
        json.dump(dump, f, ensure_ascii=False, separators=(',', ':'))
    return len(dump)


# ═══════════════════════════════════════════════════════════════════
# ① 分类
# ═══════════════════════════════════════════════════════════════════

# ＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝
# 视觉分类缓存（2026-10-09 性能）
# ＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝
# 🔴 「治理是必然要反复调的（阈值 / 分路规则 / 纠偏表）」—— 这句话原本就写在
#    OCR_CACHE 的注释里，但那条正确的判断**只覆盖了 OCR**：classify 对每张照片
#    都会发一次多模态 HTTP，却从来没有缓存过。结果就是每轮重跑治理都要为全部
#    照片重新付一遍网络时间与 API 费用，哪怕用户只是调了一下 conf>=0.5 这种阈值。
#
#    缓存是安全的：`_call()` 里设了 `temperature=0`（vision.py:152），同一张图
#    配同一套 prompt，结果是稳定的 —— 重跑也只是拿回同一个答案。
#
#    key = 文件路径 + 模型 + prompt 内容哈希 + 文件(体积, mtime)，四项缺一不可：
#      · 模型 / prompt 变了会自动失效。**漏任一项 = 换模型后静默用旧结果**；
#      · prompt 记的是**内容哈希**而不是手写版本号，避免「改了 prompt 忘了 bump」
#        这种迟早会出的事故；
#      · 带文件体积与 mtime 是兜底：同路径若真换了内容，至少会自动重跑
#        （宁可多花一次请求，也不要用错结果）。
#      ⚠️ 必须用 hashlib 而非内置 hash()：后者对 str 每次进程随机
#         （PYTHONHASHSEED），会让 key 每次启动都不同 → 缓存永远不命中。
_VISION_CACHE_PATH = os.path.join(DATA_DIR, '_vision_cache.json')
_VISION_CACHE = {}
_VISION_CACHE_LOADED = False


def _classify_prompt_ver():
    """当前 CLASSIFY_PROMPT 的稳定指纹。只要 prompt 改了，缓存自动全部失效。"""
    return hashlib.sha1(
        getattr(vision, 'CLASSIFY_PROMPT', '').encode('utf-8')).hexdigest()[:12]


def _vision_key(path, model):
    try:
        st = os.stat(path)
        ident = '%d_%d' % (st.st_size, int(st.st_mtime))
    except OSError:
        ident = 'nostat'
    return '%s|%s|%s|%s' % (path, model, _classify_prompt_ver(), ident)


def load_vision_cache():
    """第一次用到时才读盘 —— 别在 import 阶段白读一个会越来越大的 JSON。"""
    global _VISION_CACHE, _VISION_CACHE_LOADED
    if _VISION_CACHE_LOADED:
        return len(_VISION_CACHE)
    _VISION_CACHE_LOADED = True
    if not os.path.exists(_VISION_CACHE_PATH):
        return 0
    try:
        with open(_VISION_CACHE_PATH, 'r', encoding='utf-8') as f:
            _VISION_CACHE.update(json.load(f))
    except Exception:  # noqa: BLE001  缓存坏了就当没有，不该挡住治理
        _VISION_CACHE = {}
    return len(_VISION_CACHE)


def save_vision_cache():
    if not _VISION_CACHE:
        return 0
    os.makedirs(DATA_DIR, exist_ok=True)
    # 与 OCR 缓存同理：这是全量重写，别在它上面做格式化/排序这种纯浪费
    with open(_VISION_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(_VISION_CACHE, f, ensure_ascii=False, separators=(',', ':'))
    return len(_VISION_CACHE)


def classify(con, photo, use_vision=True, ocr_text=None):
    """给一张照片定类。返回 (kind, conf, reason, model, usage, sup_tag, sup_conf, sup_reason)。

    ocr_text: 本地 PaddleOCR 提取的文字片段（多行字符串），拼进大模型分类 prompt
              辅助判断 label/packing_list 等类别（2026-10-19 老板指令）。

    小模型（ONNX）定位为「辅助分流」而非「权威定类」（2026-10-19 老板指令：
    数据集标注尚不准，**准确性优先级最高**）：
      · 监装照：粗粒度分流，错分代价小（监装不读码不关联），高置信才本地定 scene
      · 预检照：是读码/关联的关键节点，错一个分类就漏一组码 —— **一律走大模型 classify()**
        小模型 kind 结果只作诊断日志，不直接写 kind
    任一级小模型不可用/低置信 → 回退大模型 classify()。
    """
    # ── 小模型二分类（本地 ONNX，零成本）──
    sm = govern_classifier.classify_usage(photo['path'])
    if sm:
        usage_sm, conf_sm = sm
        # 高置信监装 → 本地定类为 scene（阈值 0.90，保守；监装照不参与关联，错分代价小）
        if usage_sm == '监装' and conf_sm >= 0.90:
            return ('scene', conf_sm, '小模型监装分流', 'onnx_usage',
                    '监装', None, 0.0, '')

    if use_vision and vision.enabled():
        model = vision.load_config().get('model', 'vision')
        path = photo['path']
        load_vision_cache()
        vkey = _vision_key(path, model)
        hit = _VISION_CACHE.get(vkey)
        if hit:
            # 缓存里存的是 JSON list，还原成调用方要的 8 元组
            kind, conf, reason, usage, sup_tag, sup_conf, sup_reason = hit
            # 如果小模型有高置信 usage 且与大模型一致，信任小模型结果
            if sm and sm[0] == usage and sm[1] >= 0.80:
                usage = sm[0]
            return (kind, conf, reason, model,
                    usage, sup_tag, sup_conf, sup_reason)
        # 🔴 把本地 OCR 文本拼进大模型分类 prompt（辅助 label/packing_list 判断）
        r = vision.classify(path, ocr_text=ocr_text)
        if r:
            _VISION_CACHE[vkey] = list(r)
            kind, conf, reason, usage, sup_tag, sup_conf, sup_reason = r
            # 小模型高置信时覆盖 usage（本地模型更稳）
            if sm and sm[1] >= 0.80:
                usage = sm[0]
            return (kind, conf, reason, model,
                    usage, sup_tag, sup_conf, sup_reason)
    # 降级：本地无分类能力，先返回 unknown（由 OCR 结果反推，见 govern_one）
    usage_fb = sm[0] if sm else None
    return 'unknown', 0.0, 'no-vision', None, usage_fb, None, 0.0, ''


# ═══════════════════════════════════════════════════════════════════
# 标签区域裁剪（2026-10-17）：PaddleOCR det 框 → 聚出标签区 → 裁剪放大
# ═══════════════════════════════════════════════════════════════════
#
# 动机（老板需求）：标签在整张照片里往往只占一小块，整图缩到 1024 发给
# 视觉模型，标签上的小字（编码/品名/规格）容易漏读。det 框聚出文字密集
# 的区域，裁出来放大后再给视觉模型 / 二次 OCR —— 小字变清晰。
#
# 口径（克制，宁缺勿滥）：
#   · 只对 label / unknown 两类做（最依赖读码的两类；product/packaging
#     的主体是产品本体，裁剪反而可能把产品裁掉）
#   · 全部文本框的并集外接矩形 + 12% 边距；面积占原图 ≤45% 才算「明确
#     标签区」—— 文字满图（清单照）不裁，整图就是文档
#   · 区域太小（宽或高 <160px）不值得发，跳过
#   · 聚不出来就不裁，一切按原整图路径走（可回退，零风险）

LABEL_REGION_MAX_AREA = 0.5
LABEL_REGION_PAD = 0.3
# 多方向 det（0°+逆时针90°）合并后检测框已覆盖完整标签，只需小 pad 兜底，
# 无需大 pad 去补 det 漏检——大 pad 反而会让区域膨胀超面积上限。
LABEL_REGION_PAD_MULTI = 0.15
LABEL_REGION_MIN_PX = 160


def label_region(boxes, img_w, img_h, pad=None):
    """从 det 框聚出标签区域。boxes=[[x0,y0,x1,y1],...]（原图坐标）。

    返回 (rx0, ry0, rx1, ry1) 或 None（聚不出有效区域）。
    纯函数 —— 便于单测，不碰图像。
    """
    pts = [b for b in (boxes or []) if len(b) == 4]
    if not pts:
        return None
    x0 = max(0, min(int(b[0]) for b in pts))
    y0 = max(0, min(int(b[1]) for b in pts))
    x1 = min(img_w, max(int(b[2]) for b in pts))
    y1 = min(img_h, max(int(b[3]) for b in pts))
    if x1 <= x0 or y1 <= y0:
        return None
    pad = LABEL_REGION_PAD if pad is None else pad
    pw = int((x1 - x0) * pad)
    ph = int((y1 - y0) * pad)
    rx0, ry0 = max(0, x0 - pw), max(0, y0 - ph)
    rx1, ry1 = min(img_w, x1 + pw), min(img_h, y1 + ph)
    area = (rx1 - rx0) * (ry1 - ry0)
    if area > img_w * img_h * LABEL_REGION_MAX_AREA:
        return None
    if (rx1 - rx0) < LABEL_REGION_MIN_PX or (ry1 - ry0) < LABEL_REGION_MIN_PX:
        return None
    return (rx0, ry0, rx1, ry1)


def _main_cluster(boxes, img_w, img_h, pad_ratio=LABEL_REGION_PAD_MULTI,
                  max_area_ratio=0.5):
    """多方向 det 合并框的「主簇」过滤：迭代剥掉离群框，把包围盒压回主标签区。

    背景（2026-10-20）：多方向 det 会把旋转图里标签之外的噪声文字也检出来，
    合并框包围盒可能远超主标签（甚至 > MAX_AREA 上限）→ label_region 返回 None，
    或裁剪含大量背景。这里每次移除一个「使 pad 后包围盒面积减少最多」的框
    （即离主区最远的孤立框），直到包围盒面积 ≤ max_area_ratio*图面积 或只剩一个框。
    竖排标签字段本来横跨标签宽，只要包围盒不超上限就不剥，保证字段完整。
    纯函数，不碰图像。
    """
    if not boxes:
        return boxes
    best = [list(b[:4]) for b in boxes if len(b) >= 4]
    if len(best) <= 1:
        return best
    cap = img_w * img_h * max_area_ratio

    def box_area(pts):
        x0 = min(int(b[0]) for b in pts); y0 = min(int(b[1]) for b in pts)
        x1 = max(int(b[2]) for b in pts); y1 = max(int(b[3]) for b in pts)
        pw = int((x1 - x0) * pad_ratio); ph = int((y1 - y0) * pad_ratio)
        return (x1 - x0 + 2 * pw) * (y1 - y0 + 2 * ph)

    while len(best) > 1:
        if box_area(best) <= cap:
            break
        # 找移除后面积减少最多的框
        best_i, best_delta = 0, -1
        for i in range(len(best)):
            sub = best[:i] + best[i + 1:]
            delta = box_area(best) - box_area(sub)
            if delta > best_delta:
                best_delta, best_i = delta, i
        best.pop(best_i)
    return best


def _label_crop_ocr(con, photo, texts, kind, det_boxes=None, use_multi=False):
    """标签区域二次 OCR（本地，零 API 成本）。

    texts 带框坐标（run_photo 新格式）→ 聚区域 → 裁剪落临时 jpg →
    再跑一遍 PaddleOCR（放大图上小字更清晰）→ 新文本并入返回。
    只对 label/unknown 调用；任何异常静默降级返回原 texts ——
    裁剪增强是锦上添花，绝不能让它把治理搞挂。

    2026-10-19 增强（老板要求）：**识别文本为空 ≠ 检测框为空**。
    texts 一个框都没有、但 det_boxes 存在时，用检测框直接聚标签区
    —— 解决「OCR 识别出了框坐标但 rec 全空 / 或没出文本」导致标签区
    裁剪被跳过的漏网（整图缩 1024 后小标签读不出码的根因之一）。

    2026-10-20 增强：**det 漏检竖排标签字段**。det 模型对旋转 90° 的小字
    标签召回弱（如竖排 label 只在 0° 检出右半、漏左半 PNUM/PNAME），导致
    聚类区只含标签一部分 → 裁剪把标签裁掉一块。use_multi=True 时改用
    多方向 det（0°+逆时针90°）合并框聚区，配小 pad —— 框已覆盖完整标签。
    """
    boxes = [t.get('box') for t in texts if t.get('box')]
    if use_multi:
        # 多方向 det 合并框优先：能覆盖完整标签（含竖排字段）
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import pc_ocr_probe as P
        multi_boxes = P.det_boxes_multi(photo['path'], dirs=(0, 2))
        if multi_boxes:
            boxes = [list(b[:4]) for b in multi_boxes if len(b) >= 4]
    elif not boxes and det_boxes:
        # rec 文本为空但检测框在：拿 det 框（原图坐标 [x0,y0,x1,y1,...]）聚区
        boxes = [list(b[:4]) for b in det_boxes if len(b) >= 4]
    if not boxes:
        return texts, None
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(photo['path']) as im:
            W, H = im.size
            if use_multi and len(boxes) > 1:
                # 多方向合并框可能含旋转图里的离群噪声 → 主簇过滤压回标签区
                boxes = _main_cluster(boxes, W, H)
            pad = LABEL_REGION_PAD_MULTI if use_multi else None
            reg = label_region(boxes, W, H, pad=pad)
            if reg is None:
                return texts, None
            crop = im.convert('RGB').crop(reg)
            # 放大到短边 ~1280：det/rec 在大图上读小字更稳（原图区域可能只有几百 px）
            w, h = crop.size
            scale = max(1.0, 1280.0 / min(w, h))
            if scale > 1.0:
                crop = crop.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    except Exception:
        return texts, None
    import tempfile
    fd, crop_path = tempfile.mkstemp(prefix='pl_label_', suffix='.jpg')
    os.close(fd)
    try:
        crop.save(crop_path, format='JPEG', quality=90)
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import pc_ocr_probe as P
        P.FOUR_DIR_CONF = BL.FOUR_DIR_CONF
        r = P.run_photo(crop_path)
        got = r.get('texts', [])
        seen = {t.get('t', '') for t in texts}
        merged = list(texts)
        added = 0
        for t in got:
            s = t.get('t', '')
            if s and s not in seen:          # 与整图 OCR 去重
                merged.append({'t': s, 'c': t.get('c', 0.0)})
                seen.add(s)
                added += 1
        if added:
            con.execute('DELETE FROM ocr_tokens WHERE photo_id=?',
                        (photo['id'],))
            store.add_tokens(con, photo['id'],
                             [{'t': t.get('t', ''), 'c': t.get('c', 0.0)}
                              for t in merged])
        return merged, crop
    except Exception:
        return texts, None
    finally:
        try:
            os.remove(crop_path)
        except OSError:
            pass


def _vision_tile_codes(path, tiles=2):
    """读码兜底：把原图 tiles×tiles 切块，每块单独问视觉模型读码。

    2026-10-18 老板实测：标签/合格证贴在货上只占画面一小块，整图缩到
    VISION_LONG_EDGE=1024 后标签上的字只剩几十像素，整图读码漏读。
    切块后每块独立缩到 1024 —— 标签所在块的字被放大约 tiles 倍，
    可读性显著提升。只对「OCR + 整图视觉都没码」的照片调用（成本控制）。
    返回 list[list[str]]（每块的 codes），模型不可用/异常返回 []。
    """
    try:
        from PIL import Image, ImageOps
        from concurrent.futures import ThreadPoolExecutor
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as im0:
            im0 = ImageOps.exif_transpose(im0)
            im = im0.convert('RGB')
            W, H = im.size
            if W < vision.VISION_LONG_EDGE // 2 or H < vision.VISION_LONG_EDGE // 2:
                return []          # 原图本来就小，切了更糊
            boxes = []
            for ty in range(tiles):
                for tx in range(tiles):
                    boxes.append((W * tx // tiles, H * ty // tiles,
                                  W * (tx + 1) // tiles, H * (ty + 1) // tiles))
            # 4 块并发问模型（2026-10-18 提速）：每块是一次完整的 API 调用
            #（缩图+上传+等回复 5~10s），串行要 4 倍时间——纯 IO 等待，
            # 并发零额外成本。API 限速时 describe 自带重试兜底。
            def _ask(box):
                try:
                    d = vision.describe(None, expect_codes=True,
                                        image=im.crop(box))
                    return list(d[0]) if (d and d[0]) else []
                except Exception:  # noqa: BLE001
                    return []
            with ThreadPoolExecutor(max_workers=len(boxes)) as pool:
                return [r for r in pool.map(_ask, boxes) if r]
    except Exception:
        return []


def _kind_from_ocr(hit_count, text_count, box_count):
    """用 OCR 结果反推分类（降级路径）。"""
    if hit_count > 0:
        # 命中多个编码 = 装箱单；命中 1 个 = 标识卡
        return 'packing_list' if hit_count >= 2 else 'label'
    if text_count == 0:
        return 'scene'      # 一个字都没有 → 大概率纯外观/场景
    return 'unknown'        # 有文字但没编码 → 说不准


# ═══════════════════════════════════════════════════════════════════
# ② + ③ 治理单张
# ═══════════════════════════════════════════════════════════════════

def govern_one(con, photo, index, use_vision=True, use_ocr=True):
    """治理一张照片并产出关联候选。

    返回 dict：{kind, hits:[(code,score,mode,evidence)], vision_codes, desc}

    流水线顺序（2026-10-19 调整）：
      1. 基础 OCR（拿文字片段，缓存命中则零成本）
      2. 大模型 classify（把 OCR 文本拼进 prompt，辅助 label/packing_list 判断）
      3. 如果 kind ∈ {label, unknown} → 标签区域裁剪放大再 OCR 一次（增强读码）
      4. 编码匹配 + 关联候选
    """
    out = {'kind': None, 'hits': [], 'vision_codes': [], 'desc': None}

    # ── 第一步：基础 OCR（先跑，文本喂给大模型分类）──
    # OCR 是本地小模型，便宜且稳。所有分类都跑（scene 也不例外），token 全部落库。
    ocr_texts = []
    raw_texts = []      # 基础 OCR 拿到的原始文字列表
    det_boxes = []      # 基础 OCR 的检测框（识别文本空 ≠ 检测框空，2026-10-19）
    crop_im = None      # 标签区域裁剪图（标签增强 OCR 后才有；给视觉模型用）
    if use_ocr:
        cached = _OCR_CACHE.get(photo['file'])
        try:
            if cached is not None:
                raw_texts = cached.get('texts', [])
                det_boxes = cached.get('det_boxes', [])
                out['ocr_cached'] = True
            else:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                import pc_ocr_probe as P
                P.FOUR_DIR_CONF = BL.FOUR_DIR_CONF
                r = P.run_photo(photo['path'], four_dir=True)
                raw_texts = r.get('texts', [])
                det_boxes = r.get('det_boxes', [])
                with _OCR_LOCK:
                    _OCR_CACHE[photo['file']] = {
                        'texts': raw_texts, 'boxes': r.get('boxes', 0),
                        'det_boxes': det_boxes,
                        'det_s': r.get('det_s', 0), 'rec_s': r.get('rec_s', 0)}
                out['ocr_cached'] = False
            ocr_texts = [{'t': t.get('t', ''), 'c': t.get('c', 0.0)}
                         for t in raw_texts]
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            try:
                import pc_ocr_probe as _P
                if not getattr(_P, 'OCR_AVAILABLE', True):
                    msg = _P.OCR_MISSING
            except Exception:  # noqa: BLE001
                pass
            store.set_govern(con, photo['id'], 'failed', kind=None, error=msg[:200])
            return out

    # ── 第二步：分类（把 OCR 文本拼进大模型 prompt，辅助 label/packing_list 判断）──
    # sup_tag 是监装细分的**建议**（不是定论）：同一趟视觉调用顺带问出来，不额外花钱。
    ocr_snippet = '\n'.join(t.get('t', '') for t in ocr_texts if t.get('t'))
    (kind, conf, reason, model, usage,
     sup_tag, sup_conf, sup_reason) = classify(con, photo, use_vision,
                                              ocr_text=ocr_snippet)
    out['kind'] = kind
    out['kind_conf'] = conf
    out['model'] = model
    out['usage'] = usage
    out['sup_tag'] = sup_tag

    # ── 第三步：标签区域二次 OCR（仅 label/unknown，小字增强）──
    # det 框聚出标签区域 → 裁剪放大 → 再跑一遍本地 OCR。
    # 裁出的区域图同时留给视觉模型（下文 describe 用区域图替代整图）。
    # 2026-10-19：触发条件从 `raw_texts` 放宽为 `(raw_texts or det_boxes)` ——
    # 识别文本为空但检测框存在（rec 空 ≠ det 空）也要聚区放大，否则整图缩
    # 1024 后小标签读不出码（老板实测漏读的根因）。
    if use_ocr and kind in ('label', 'unknown') and (raw_texts or det_boxes):
        try:
            # 检测框稀疏（≤8）时疑似漏检竖排/旋转标签字段 → 多方向 det 补全聚区，
            # 避免裁剪只含标签一部分（2026-10-20 误裁修复）
            use_multi = len(det_boxes) <= 8
            merged, crop_im = _label_crop_ocr(con, photo, raw_texts, kind, det_boxes,
                                              use_multi=use_multi)
            if merged != raw_texts:
                ocr_texts = [{'t': t.get('t', ''), 'c': t.get('c', 0.0)}
                             for t in merged]
        except Exception:
            crop_im = None  # 增强失败不挡治理

    # OCR token 落库（缓存命中时不重复写）
    if use_ocr:
        has = con.execute('SELECT 1 FROM ocr_tokens WHERE photo_id=? LIMIT 1',
                          (photo['id'],)).fetchone()
        if not has:
            store.add_tokens(con, photo['id'], ocr_texts)

    # ── OCR 编码匹配（只认精确匹配才自动写；模糊码进人工工作台）──
    # 只有产品图（LINKABLE_KINDS=label/product）写关联（2026-10-17 老板规则
    # 「只有产品需要关联」，白名单取代旧黑名单）。
    # OCR 仍然对其他类跑（存 token 供展示）。
    hit_codes = set()
    for t in ocr_texts:
        r = _match_token(index, t.get('t'), t.get('c'))
        if r and kind in schema.LINKABLE_KINDS:
            code, score, mode = r
            if code not in hit_codes:
                hit_codes.add(code)
                out['hits'].append((code, score, mode,
                                    'OCR:%s「%s」' % (mode, (t.get('t') or '')[:40])))

    # ── 多模态：补手写码 + 描述 ──
    # 只有"像标签"的类（标识卡/未知）才请求读码；
    # 产品/外包装本体照上没有标签，模型会脑补编码，干脆不请求（expect_codes=False）。
    # packing_list 是参考文档，OCR 已能提文字，不必再花一次视觉 API，且不关联 → 跳过视觉。
    # scene 低置信时也会走到附近，但被下面的 kind 条件排除 —— 它没有「读码」语义。
    if use_vision and vision.enabled() and kind in ('label', 'unknown', 'product', 'packaging'):
        expect_codes = kind in ('label', 'unknown')
        # 🔴 标签区域图优先（2026-10-17 老板需求）：label/unknown 且 OCR 检测
        # 聚出了标签区域时，把裁剪放大图发给视觉模型 —— 标签小字读得更准。
        # 无区域时照旧发整图；product/packaging 的主体是产品本体，不裁。
        _d_img = crop_im if (expect_codes and crop_im is not None) else None
        d = vision.describe(photo['path'], expect_codes=expect_codes,
                            image=_d_img)
        if d:
            codes, desc, has_product, vmeta = d
            if _d_img is not None:
                vmeta = dict(vmeta or {}, label_crop=1)   # 诊断：这次读的是裁剪区
            out['vision_codes'] = codes
            out['desc'] = desc
            out['vision_has_product'] = has_product
            out['vision_meta'] = vmeta
            model = vision.load_config().get('model', 'vision')
            for c in codes:
                m = index.best(c, 0.95)
                if m:
                    code, _n, score, mode = m
                    if mode == 'exact' and score >= 0.5 and code not in hit_codes:
                        hit_codes.add(code)
                        out['hits'].append((code, score, mode,
                                            'VISION:%s「%s」' % (mode, c)))
                    # 非 exact：不自动写，_candidates_for 会把它作为人工候选呈现

    # ── 读码兜底：切块重读（2026-10-18 老板实测：合格证/标签贴在产品照上
    #    只占画面一小块，整图缩到 1024 后标签字只剩几十像素，整图读码
    #    漏读）── 触发条件克制：label/unknown（最依赖读码的两类）且
    #    OCR + 首次视觉都没给出任何码时才做，2×2 切块各读一次。
    #    成本：仅无码照片多花 4 次调用；有码的一张不切。
    #    ⚠️ 条件不能引用 expect_codes（它在上面视觉 if 块内定义，scene/
    #    packing_list 不进那块会 NameError —— 2026-10-18 现场治理 32 张
    #    失败的根因），直接判 kind：
    if (use_vision and vision.enabled()
            and kind in ('label', 'unknown')
            and not out['hits'] and not out.get('vision_codes')):
        for tile_codes in _vision_tile_codes(photo['path']):
            for c in tile_codes:
                m = index.best(c, 0.95)
                if m:
                    code, _n, score, mode = m
                    if mode == 'exact' and score >= 0.5 and code not in hit_codes:
                        hit_codes.add(code)
                        out['hits'].append((code, score, mode,
                                            'VISION-TILE:%s「%s」' % (mode, c)))
            # 非 exact 的瓦片码也留档（供 _candidates_for 做人工候选）
            if tile_codes:
                prev = out.get('vision_codes') or []
                out['vision_codes'] = list(dict.fromkeys(prev + list(tile_codes)))

    # ── 降级时：用 OCR 结果反推分类 ──
    if kind == 'unknown' or conf == 0.0:
        kind = _kind_from_ocr(len(out['hits']), len(ocr_texts), 0)
        out['kind'] = kind

    # 高置信场景照 → 'skipped' 口径不变（统计/筛选不漂），但 token 已在上面
    # 全量落库 —— 「跳过」跳的只是视觉读码与关联，不再是「什么都没做」。
    state = 'skipped' if (kind in schema.SKIP_KINDS and conf >= 0.85) else 'done'
    store.set_govern(con, photo['id'], state, kind=kind, kind_conf=conf,
                     desc=out['desc'] or reason, codes=out['vision_codes'],
                     model=model, meta=out.get('vision_meta'), usage=out.get('usage'),
                     sup_tag=sup_tag, sup_tag_conf=sup_conf,
                     sup_tag_reason=sup_reason)
    return out


def regovern_one(con, photo, kind, index, regen='full'):
    """人工改判后按新分类重跑「读码链路」（2026-10-15 需求1：分类准确性保障）。

    与 govern_one 的本质区别：**不重新分类** —— 人刚拍板的 kind 就是权威，
    模型无权翻案。重跑的是这个分类下该做的动作：
      OCR（scene 除外）→ token 匹配 → 视觉读码（label/unknown 才要码）
      → 精确命中自动关联（NO_LINK_KINDS 照旧不写）。
    这条链路是把「分类错 → 编码丢 → 关联不上」变成「人纠错 → 机器补码」
    的闭环：模型判错的图，人工改一个下拉框，编码和候选就回来了。

    容错：OCR 环境坏了（缺 cv2 等）只降级不炸 —— 已有 token 照样匹配，
    视觉照样跑，否则一次依赖故障就把人工的改判卡死。

    regen（2026-10-19 老板要求：抽屉里拆成两个按钮）：
      'full' —— 完整链路（默认）：OCR + 视觉读码/描述，花多模态额度；
                库里已有 token 直接复用（重治是高频小操作）。
      'ocr'  —— 只跑本地 OCR，一分钱不花：**强制重跑**（先清旧 token，
                老板点它就是要重新提文字，复用旧 token 等于没点），
                然后照常 token 匹配 + 自动关联；视觉段整段跳过，
                vision_codes/desc/model 全部保留原值不动。
    """
    out = {'kind': kind, 'hits': [], 'vision_codes': [], 'links_added': 0,
           'tokens_n': 0, 'ocr_ok': True}
    pid = photo['id']

    # ⚠️ ocr_texts 必须预置：下面 except 分支降级时不会赋值，
    #    没有这个初值后面 len(ocr_texts) 就是 UnboundLocalError，
    #    报「cannot access local variable 'ocr_texts'」—— 用户只看到「重新识别失败」。
    ocr_texts = []
    det_boxes = []   # OCR 检测框（识别文本空 ≠ 检测框空，2026-10-19）
    crop_im = None   # 标签区裁剪放大图（给视觉替代整图，小标签读码）
    # ── OCR：mode='ocr' 强制重跑（先清旧 token）；'full' 复用已有 token ──
    # 全量口径（2026-10-15 需求4）：scene 也跑 —— token 铺底不挑分类。
    have = con.execute(
        'SELECT raw_text,confidence FROM ocr_tokens WHERE photo_id=?',
        (pid,)).fetchall()
    if regen == 'ocr':
        con.execute('DELETE FROM ocr_tokens WHERE photo_id=?', (pid,))
        have = []
    if have:
        ocr_texts = [{'t': r['raw_text'], 'c': r['confidence']} for r in have]
    else:
        try:
            sys.path.insert(0, os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
            import pc_ocr_probe as P
            P.FOUR_DIR_CONF = BL.FOUR_DIR_CONF
            r = P.run_photo(photo['path'], four_dir=True)
            texts = r.get('texts', [])
            det_boxes = r.get('det_boxes', [])
            ocr_texts = [{'t': t.get('t', ''), 'c': t.get('c', 0.0)}
                         for t in texts]
            if ocr_texts:
                store.add_tokens(con, pid, ocr_texts)
        except Exception as e:  # noqa: BLE001  降级：token 匹配跳过，视觉照走
            out['ocr_ok'] = False
            out['ocr_error'] = str(e)[:160]
    out['tokens_n'] = len(ocr_texts)

    # ── 标签区裁剪放大（fix A，2026-10-19）：label/unknown 且文本空但检测框在时，
    #    用 det 框聚标签区、裁剪放大；crop 给下方视觉替代整图 —— 小标签整图缩
    #    1024 后读不出码的根因。失败静默回退整图。──
    if regen == 'full' and kind in ('label', 'unknown') and (ocr_texts or det_boxes):
        try:
            use_multi = len(det_boxes) <= 8
            _merged, crop_im = _label_crop_ocr(con, photo, ocr_texts, kind, det_boxes,
                                               use_multi=use_multi)
        except Exception:
            crop_im = None

    # ── token 匹配（口径与 govern_one 一致：精确命中才进 hits）──
    hit_codes = set()
    for t in ocr_texts:
        r = _match_token(index, t.get('t'), t.get('c'))
        if r and kind in schema.LINKABLE_KINDS:
            code, score, mode = r
            if code not in hit_codes:
                hit_codes.add(code)
                out['hits'].append((code, score, mode,
                                    'OCR:%s「%s」' % (mode, (t.get('t') or '')[:40])))

    # ── 视觉读码 + 描述（与 govern_one 同一套口径）──
    # mode='ocr' 整段跳过：本地 OCR 不该顺带花钱，vision 字段全保留原值。
    model = None
    if regen != 'ocr' and vision.enabled() and kind in ('label', 'unknown', 'product', 'packaging'):
        model = vision.load_config().get('model', 'vision')
        expect_codes = kind in ('label', 'unknown')
        # 标签区裁剪放大图优先（fix A）：label/unknown 聚出区域时用放大图替代整图
        _d_img = crop_im if (expect_codes and crop_im is not None) else None
        d = vision.describe(photo['path'], expect_codes=expect_codes, image=_d_img)
        if d:
            codes, desc, has_product, vmeta = d
            out['vision_codes'] = codes
            out['desc'] = desc
            for c in codes:
                m = index.best(c, 0.95)
                if m:
                    code, _n, score, mode = m
                    if (mode == 'exact' and score >= 0.5
                            and code not in hit_codes
                            and kind in schema.LINKABLE_KINDS):
                        hit_codes.add(code)
                        out['hits'].append((code, score, mode,
                                            'VISION:%s「%s」' % (mode, c)))

    # ── 自动关联（只有产品图写；阈值/否决逻辑都在 apply_auto_links）──
    if kind in schema.LINKABLE_KINDS and out['hits']:
        out['links_added'] = apply_auto_links(con, pid, out['hits'])

    # ── 写回。人工改判的 kind 原样写回（set_govern 会覆写 photo_kind）；
    #     desc 保留原描述 —— 治理描述是模型对画面的陈述，跟分类无关。
    #     ⚠️ mode='ocr' 没跑视觉，vision_codes 保留原值（set_govern 的 codes
    #     是覆写语义，传空列表会把原读码结果清没 —— ocr_backfill 同坑）。
    prev = con.execute('SELECT vision_desc,vision_model,vision_codes '
                       'FROM photos WHERE id=?', (pid,)).fetchone()
    if regen == 'ocr':
        prev_codes = None
        if prev and prev['vision_codes'] and prev['vision_codes'] not in ('', '[]'):
            try:
                prev_codes = (json.loads(prev['vision_codes'])
                              if isinstance(prev['vision_codes'], str)
                              else prev['vision_codes'])
            except Exception:  # noqa: BLE001
                prev_codes = None
        out['vision_codes'] = prev_codes or []
    state = 'skipped' if kind == 'scene' else 'done'
    store.set_govern(con, pid, state, kind=kind, kind_conf=None,
                     desc=out.get('desc') or (prev['vision_desc'] if prev else None)
                     or '人工改判后重新识别',
                     codes=out['vision_codes'], model=model or
                     (prev['vision_model'] if prev else None))
    con.commit()
    return out


def ocr_backfill(con, container_id='', batch_id='', progress=None):
    """给「治理过但没有 OCR token」的照片补跑本地 OCR（2026-10-15 需求4）。

    背景：早期治理时 OCR 不可用、或被旧的分类门槛跳过 —— 编码没提出来，
    关联上不去（真实库 2501 张里约 790 张零 token）。只跑**本地小模型**，
    一分钱多模态 API 都不花；跑完按当前产品索引重新匹配：
      精确命中且分类允许 → 自动关联；其余 token 留档供人工候选/抽屉展示。
    可重复执行：已补过（有 token）的自动跳过，中断了再点一次接着跑。

    [progress] fn(done, total, file, linked) —— 后台线程喂进度。
    """
    rows = con.execute(
        'SELECT p.* FROM photos p JOIN batches b ON b.id=p.batch_id '
        "WHERE (?='' OR b.container_id=?) AND (?='' OR p.batch_id=?) "
        'AND NOT EXISTS (SELECT 1 FROM ocr_tokens t WHERE t.photo_id=p.id) '
        'ORDER BY p.batch_id, p.import_seq, p.rowid',
        (container_id or '', container_id or '',
         batch_id or '', batch_id or '')).fetchall()
    # 便携化（2026-10-18）：相对 path 必须解析成绝对再用（同 govern_all）
    rows = [dict(r) for r in rows]
    for r in rows:
        r['path'] = store.resolve_photo_path(con, r['id'], r['path'])
    total = len(rows)
    if progress:
        progress(0, total, '', 0)
    if not total:
        return {'done': 0, 'total': 0, 'linked': 0}
    index = _build_index(con)
    done = linked = 0
    for photo in rows:
        kind = photo['photo_kind'] or 'unknown'
        texts = []
        try:
            sys.path.insert(0, os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
            import pc_ocr_probe as P
            P.FOUR_DIR_CONF = BL.FOUR_DIR_CONF
            r = P.run_photo(photo['path'], four_dir=True)
            texts = [{'t': t.get('t', ''), 'c': t.get('c', 0.0)}
                     for t in (r.get('texts') or [])]
        except Exception:  # noqa: BLE001  单张失败继续跑，别让一张坏图停全场
            pass
        if texts:
            store.add_tokens(con, photo['id'], texts)
        hits = []
        hit_codes = set()
        for t in texts:
            m = _match_token(index, t.get('t'), t.get('c'))
            if m and kind in schema.LINKABLE_KINDS:
                code, score, mode = m
                if code not in hit_codes:
                    hit_codes.add(code)
                    hits.append((code, score, mode,
                                 'OCR:%s「%s」' % (mode, (t.get('t') or '')[:40])))
        if hits and kind in schema.LINKABLE_KINDS:
            linked += apply_auto_links(con, photo['id'], hits)
        done += 1
        if progress:
            progress(done, total, photo['file'], linked)
    con.commit()
    return {'done': done, 'total': total, 'linked': linked}


# ═══════════════════════════════════════════════════════════════════
# ③ 关联
# ═══════════════════════════════════════════════════════════════════

def apply_auto_links(con, photo_id, hits, threshold=None):
    """把治理产出的命中写成关联。

    ⚠️ 只有 ≥ threshold 的才自动写。低于阈值的一律不写 ——
    **宁可留给人工，也不自动建一条可能错的关联**。
    一条错关联比"没有关联"更危险：召回时它会被当成证据用出去。

    ⚠️ 人工标记「无关联」的 (产品, 照片) 对直接跳过（10-05）。
    老板在候选区看过并确认「这张不是这个产品的」之后，**任何**自动
    路径都不许再把它建回来 —— 包括清单重导后的 relink（那会重跑
    replay_hits，命中的是同一批 token，标记会被无声吞掉）。
    人的判断优先于机器的判断；否则「标记无关联」只是个装饰。
    """
    threshold = threshold or schema.AUTO_LINK_THRESHOLD
    rej = store.rejected_pairs(con)
    written = 0
    for code, score, mode, evidence in hits:
        if score < threshold:
            continue
        cn = BL.normalize(code)
        if (cn, photo_id) in rej:
            continue
        source = 'auto_vision' if mode.startswith('VISION') or evidence.startswith('VISION') \
            else 'auto_ocr'
        store.link(con, cn, photo_id, source, confidence=score,
                   evidence=evidence, created_by='system')
        written += 1
    return written


# ═══════════════════════════════════════════════════════════════════
# 补关联（先导照片、后导清单的场景）
# ═══════════════════════════════════════════════════════════════════
#
# ── 为什么需要这一段 ──────────────────────────────────────────────
# 自动关联的匹配靠 CodeIndex，而索引建自 **products 表**。所以导入顺序
# 一旦反了，关联就永久丢失：
#
#   ① 先导照片 → govern_one 拿空的 index 去 best() → 全部 None → 零关联；
#   ② 这时 OCR/多模态的结果**已经落库**（ocr_tokens 逐条 + vision_codes）；
#   ③ 后导清单 → products 有了，但照片 govern_state 已是 'done'，
#      govern_all 的 `WHERE govern_state='pending'` 永远扫不到它们。
#
# 结果：老板看到的是"照片先导、清单后导，一张都没关联上"，
# 而界面上没有任何入口能修 —— 只有重跑治理，而重跑要重调多模态 API。
#
# ── 为什么补关联很便宜 ────────────────────────────────────────────
# 因为**识别结果没丢**，只是没跟新清单重新匹配过。所以这里不碰 OCR、
# 不碰多模态，只把已落库的 token 拿新索引再匹配一遍：
#   1678 张照片 / 9780 条 token，纯 SQLite + 字符串匹配，亚秒级。
#
# ── 纪律与自动关联完全一致 ────────────────────────────────────────
#   · 只认 mode == 'exact'（归一化后完全相等），≥0.5 分，与 govern_one 同口径；
#   · score < AUTO_LINK_THRESHOLD 的不写（宁可留给人工）；
#   · NO_LINK_KINDS（装箱单/场景）不写关联；
#   · 人工关联永不覆盖（INSERT OR REPLACE 只碰 auto_* 自身那条）。

def _build_index(con):
    """从 products 表建编码索引。治理与补关联共用，保证口径一致。"""
    return BL.CodeIndex([
        (r['code'], r['name'], r['spec'])
        for r in con.execute('SELECT code,name,spec FROM products')
    ])


def _match_token(index, txt, conf):
    """单个 token 匹配。返回 (code, score, mode) 或 None。

    口径与 govern_one 的 OCR 段完全一致 —— 抽出来就是为了让
    「首次治理」和「事后补关联」走同一套判定，不各写一份。
    2026-10-18：先剥标签前缀（PN:/NO./编码: 等）再匹配 —— OCR 把
    「PN:203160000002」整串读出时不剥前缀只能落到 prefix 模式，
    而自动关联只认 exact，明明库里有这个码也关联不上（老板实测）。
    """
    txt = store.strip_code_prefix(txt)
    if len(txt) < BL.MATCH_MIN_TOKEN_LEN:
        return None
    c = float(conf or 0.0)
    if c <= 0:
        return None
    m = index.best(txt, c)
    if not m:
        return None
    code, _name, score, mode = m
    # 自动关联只认精确匹配：prefix/edit 是可能的识别偏差，
    # 错关联比没关联危险（召回时它会被当成证据用出去）。
    if mode != 'exact' or score < 0.5:
        return None
    return code, score, mode


def replay_hits(con, index, photo_ids):
    """用**已落库**的 OCR token / 多模态码重新匹配，不重跑识别。

    返回 {photo_id: [(code, score, mode, evidence), ...]}
    """
    out = {}
    for pid in photo_ids:
        kind_row = con.execute(
            'SELECT photo_kind FROM photos WHERE id=?', (pid,)).fetchone()
        kind = (kind_row['photo_kind'] if kind_row else None)
        # 装箱单/场景照：内容照样留着给人看，但绝不写关联
        if kind in schema.NO_LINK_KINDS or kind in schema.SKIP_KINDS:
            continue

        hits = []
        seen = set()
        for t in con.execute(
                'SELECT raw_text,confidence FROM ocr_tokens WHERE photo_id=?',
                (pid,)):
            r = _match_token(index, t['raw_text'], t['confidence'])
            if r and r[0] not in seen:
                seen.add(r[0])
                hits.append((r[0], r[1], r[2],
                             'OCR:exact「%s」' % (t['raw_text'] or '')[:40]))

        # 多模态读出的码同样在 vision_codes 里落库了
        prow = con.execute('SELECT vision_codes FROM photos WHERE id=?',
                           (pid,)).fetchone()
        if prow and prow['vision_codes']:
            try:
                vcodes = json.loads(prow['vision_codes']) or []
            except (ValueError, TypeError):
                vcodes = []
            for vc in vcodes:
                r = _match_token(index, vc, 0.95)
                if r and r[0] not in seen:
                    seen.add(r[0])
                    hits.append((r[0], r[1], r[2], 'VISION:exact「%s」' % vc[:40]))
        if hits:
            out[pid] = hits
    return out


def relink_due_to_checklist(con, progress=None, limit=None):
    """清单导入后，给已治理但没关联上的照片补关联。

    候选范围 = 所有 govern_state='done' 且 is_dup=0 的照片里，
    **还没有任何自动关联**的那些。已有自动关联的不碰（避免重复计算、
    也不覆盖人工关联）。副本靠 inherit_duplicates 继承，不单独补。

    返回 {scanned, candidates, written, replaced}：
      scanned     参与扫描的候选照片数
      candidates  其中匹配出编码的
      written     **净增**的关联条数（DB 实际多出来的行）
      replaced    覆盖掉已有行的次数（同 code+photo 重复命中）
    ⚠️ written 必须是净增而不是写入次数 —— 两份清单里同一个码
      （如 1000000119 与 1000000119.0 归一后相同）会让同一照片
      命中两次，INSERT OR REPLACE 覆盖而不新增。报写入次数会虚高。
    """
    index = _build_index(con)
    if len(index) == 0:
        return {'scanned': 0, 'candidates': 0, 'written': 0, 'replaced': 0}

    sql = ("SELECT id FROM photos WHERE govern_state='done' AND is_dup=0"
           " AND id NOT IN (SELECT photo_id FROM links WHERE source LIKE 'auto_%')"
           " AND id IN (SELECT DISTINCT photo_id FROM ocr_tokens)"
           " ORDER BY taken_at")
    if limit:
        sql += ' LIMIT %d' % int(limit)
    pids = [r['id'] for r in con.execute(sql)]

    if progress and pids:
        progress(len(pids), len(pids), '', 0)
    hits_map = replay_hits(con, index, pids)

    # 写入前先记下已有的 (code_norm, photo_id)，用它算净增
    before = {(r['code_norm'], r['photo_id'])
              for r in con.execute('SELECT code_norm,photo_id FROM links')}

    attempts = 0
    for pid, hits in hits_map.items():
        # apply_auto_links 内部有阈值门槛（≥0.70），
        # 与 govern_all 首次治理时的口径一致。
        attempts += apply_auto_links(con, pid, hits)
    if attempts:
        con.commit()

    after = {(r['code_norm'], r['photo_id'])
             for r in con.execute('SELECT code_norm,photo_id FROM links')}
    written = len(after - before)
    return {'scanned': len(pids), 'candidates': len(hits_map),
            'written': written, 'replaced': attempts - written}


# ═══════════════════════════════════════════════════════════════════
# 语义候选（给人工工作台用，不自动写）
# ═══════════════════════════════════════════════════════════════════

_NUM_TOKEN_RE = re.compile(r'\d+(?:\.\d+)?')


def semantic_candidates(con, desc, limit=8):
    """用多模态描述找候选产品。**只用于人工工作台的建议，绝不自动关联。**

    做法刻意保持简单（不引 embedding 依赖）：
      · 描述里的数字（规格尺寸、型号数字）与产品 spec/name 里的数字重合 → 强
      · 描述里的英文词与品名英文词重合 → 中
      · 中文关键词重合 → 弱

    分数统一压在 schema.SCORE_SEMANTIC 以下，
    所以即使"看起来很像"也不会自动写成关联。
    """
    if not desc:
        return []
    dn = desc.lower()
    desc_nums = set(_NUM_TOKEN_RE.findall(desc))
    # 中文按 2-gram 切（没有分词库，粗粒度但够用）
    desc_grams = {desc[i:i + 2] for i in range(len(desc) - 1)}

    out = []
    for p in con.execute('SELECT * FROM products'):
        score = 0.0
        why = []
        pnums = set(_NUM_TOKEN_RE.findall('%s %s' % (p['name'] or '', p['spec'] or '')))
        if desc_nums and pnums and (desc_nums & pnums):
            score += 0.30
            why.append('规格数字 %s' % ','.join(sorted(desc_nums & pnums)[:3]))
        pname = (p['name'] or '').lower()
        words = [w for w in re.split(r'[^a-z]+', pname) if len(w) >= 3]
        hit_words = [w for w in words if w in dn]
        if hit_words:
            score += 0.20
            why.append('品名词 %s' % ','.join(hit_words[:3]))
        ptext = '%s %s' % (p['name'] or '', p['spec'] or '')
        grams = {ptext[i:i + 2] for i in range(len(ptext) - 1)}
        inter = desc_grams & grams
        if inter:
            score += min(0.15, 0.03 * len(inter))
            why.append('描述重合')
        if score > 0:
            out.append({'code': p['code'], 'name': p['name'],
                        'score': round(min(score, schema.SCORE_SEMANTIC), 3),
                        'why': '；'.join(why)})
    out.sort(key=lambda x: -x['score'])
    return out[:limit]


# ═══════════════════════════════════════════════════════════════════
# 批量跑
# ═══════════════════════════════════════════════════════════════════

def _err_kind(msg):
    """把异常消息归类 —— 治理失败诊断的第一层。

    目的是让「失败 800 张」变成「模型没配 800 张」。分类按**可行动性**：
    每类都对应一个用户能做的动作（配模型 / 补模型文件 / 照片路径失效 / 换图片）。
    """
    m = (msg or '').lower()
    if 'vision' in m or 'api_key' in m or 'visionunavailable' in m:
        return '视觉模型不可用（去「设置」配 API）'
    if 'onnx' in m or 'model' in m or 'providers' in m or 'graph' in m:
        return 'OCR 模型加载失败（检查 ocr 目录）'
    if 'no such file' in m or 'filenotfound' in m or 'cannot find' in m \
            or '找不到' in m or 'asssets' in m:
        return '文件/模型缺失（照片路径或 ocr 目录）'
    if 'decode' in m or 'image' in m or 'pil' in m or 'truncated' in m:
        return '图片读不出（文件损坏或格式不支持）'
    if 'timeout' in m or 'timed out' in m or 'connection' in m:
        return '网络/接口超时（视觉 API 不通）'
    if 'database is locked' in m or 'database table is locked' in m:
        # 2026-10-06 实测：治理**自己不会**造成锁（每张都 commit 短事务）。
        # 真实成因几乎都是**同时开着第二个产品库进程**（绿色包 + 源码版，
        # 或两个浏览器窗口各开了一个服务），两边抢同一个 .db。
        return '数据库被另一个产品库进程占用'
    return '其它：' + (msg or '')[:60]


def govern_all(con, limit=None, use_vision=True, use_ocr=True, progress=None,
               reset=False, batch_id=None, retry_failed=False, stop_event=None,
               skip_linked=False):
    """对 pending 照片跑治理 + 自动关联。

    [batch_id]：只治理该照片批次。批次是新的治理单位 —— 新导一批照片
    只治理这一批，不必把已治理好的历史批次再跑一遍。
    [reset]=True：把范围内唯一照片（is_dup=0）重置为 pending 再跑。
    用途：刚配好多模态、或改了分路/阈值规则后想重算。
    OCR 有缓存所以重跑很快；多模态每次都真调 API —— 249 张 ≈ 500 次调用，
    前端必须在触发前把这个成本告诉用户。
    [retry_failed]=True：只把范围内 govern_state='failed' 的照片重置为
    pending 再跑，**不清自动关联**（失败的照片本来就没产生关联）。
    用途：某批治理时 OCR/视觉 API 抽风导致大量失败，单独重试这部分。
    [stop_event]：threading.Event，置位即「请求停止」（2026-10-17 补——
    此前治理线程没有任何停止入口，一旦误触发全量治理只能杀进程）。
    停止是协作式的：当前这张跑完（已提交的部分保留）就退出，已治理的
    不回滚，剩下保持 pending 下次接着跑。
    [skip_linked]=True（2026-10-18 老板需求，仅 reset 路径生效）：重新治理
    时**跳过已关联的照片** —— 不重置为 pending、不清它们的自动关联、
    不重跑。用途：改了识别规则想重算，但不想动已经关联好的照片
    （重跑有把好关联算丢的风险，且多模态调用是真金白银）。
    """
    index = _build_index(con)
    if len(index) == 0:
        raise ValueError('产品库是空的 —— 请先导入产品清单（第 1 条）')

    cleared = 0
    if reset:
        _skip = ' AND id NOT IN (SELECT photo_id FROM links)' if skip_linked else ''
        if batch_id:
            con.execute("UPDATE photos SET govern_state='pending', govern_error=NULL"
                        ' WHERE is_dup=0 AND batch_id=?' + _skip, (batch_id,))
        else:
            con.execute("UPDATE photos SET govern_state='pending', govern_error=NULL"
                        ' WHERE is_dup=0' + _skip)
        # 重新治理 = 规则可能变了，先把旧规则产生的自动关联清掉重算，
        # 只保留人工关联（老板点的，不动）。
        # ⚠️ 必须带同样的 batch 范围 —— 范围外的 auto links 清了没人重算。
        # skip_linked 时只清 pending 的（被跳过照片的 auto link 保留）——
        # 必须在 UPDATE 之后调：此刻 pending 恰为「本次要重跑的」。
        cleared = store.clear_auto_links(con, batch_id=batch_id,
                                         pending_only=skip_linked)
        con.commit()
    elif retry_failed:
        # 只重试失败：不清关联，不碰 pending/done/skipped
        if batch_id:
            con.execute("UPDATE photos SET govern_state='pending', govern_error=NULL"
                        " WHERE is_dup=0 AND batch_id=? AND govern_state='failed'",
                        (batch_id,))
        else:
            con.execute("UPDATE photos SET govern_state='pending', govern_error=NULL"
                        " WHERE is_dup=0 AND govern_state='failed'")
        con.commit()

    sql = "SELECT * FROM photos WHERE govern_state='pending' AND is_dup=0"
    args = []
    if batch_id:
        sql += ' AND batch_id=?'
        args.append(batch_id)
    if skip_linked:
        # 双保险：pending 里万一混进已关联照片（如治理后人工补挂又置 pending），
        # skip_linked 口径下同样跳过 —— 已关联 = 有归属，不动。
        sql += ' AND id NOT IN (SELECT photo_id FROM links)'
    sql += ' ORDER BY taken_at'
    rows = con.execute(sql, args).fetchall()
    if limit:
        rows = rows[:limit]
    # 🔴 便携化（2026-10-18）：path 可能是相对库根的形态 —— 治理线程里
    # 必须 resolve 成绝对路径再用，否则 open('origin/...') 按进程 cwd 解析
    # 必炸 FileNotFound（现场 130 张失败的根因）。Row 不可变 → 转 dict。
    rows = [dict(r) for r in rows]
    for r in rows:
        r['path'] = store.resolve_photo_path(con, r['id'], r['path'])

    cached_n = load_ocr_cache()
    t0 = time.time()
    done = ok = failed = skipped = linked = 0
    hits_cache = 0
    # 🔴 失败原因分布（2026-10-06）：只有 failed 计数，用户看到「失败 800 张」
    #    完全无从下手。同一类原因会成片重复（模型没配、文件不在、编码没读出），
    #    归类计数 + 抽样本 = 一眼看出是哪一类坏了、坏多少。
    err_kinds = {}          # 归类 -> 次数
    err_samples = []        # 归类 -> 第一条的原始信息（含文件名）
    # 2026-10-09 性能：原来**每张照片都 commit 一次**（叠加当时的 synchronous=FULL
    # 就是每张一次 fsync）。改成 25 张一批，与缓存落盘同节奏。
    # 崩溃时的代价：最多丢最后不足一批的进度 —— 但那些照片的 govern_state 本就
    # 还没提交，会保持 pending，下次治理照常跑完，**不会留下半成品**。
    COMMIT_EVERY = 25
    for i, ph in enumerate(rows, 1):
        if stop_event is not None and stop_event.is_set():
            # 协作式停止：已处理的（含最后不足一批的 commit 在循环尾统一做）
            # 保留，剩下的保持 pending。补一条 progress 让前端立刻看到收尾。
            if progress:
                progress(done, len(rows), '（已停止）', linked)
            break
        try:
            # 2026-10-09 性能：删掉了原先这里的一句
            #     UPDATE photos SET govern_state='running'
            # 全代码库没有任何读取方（grep 'running' 只命中 _GOVERN 那个内存状态字典），
            # 它是纯浪费的一次写：每张照片多一条 UPDATE、多一次行版本变动。
            out = govern_one(con, ph, index, use_vision=use_vision, use_ocr=use_ocr)
            if out.get('ocr_cached'):
                hits_cache += 1
            if out.get('kind') in schema.SKIP_KINDS:
                skipped += 1
            elif out.get('kind') in schema.NO_LINK_KINDS:
                # 参考文档 / 场景照：内容照样提取，但绝不写关联（用户明确要求）。
                # 即便上面漏网产生了 hits，这里也兜底不调用 apply_auto_links。
                pass
            else:
                linked += apply_auto_links(con, ph['id'], out.get('hits', []))
            ok += 1
        except Exception as e:  # noqa: BLE001
            msg = str(e)[:200]
            store.set_govern(con, ph['id'], 'failed', error=msg)
            failed += 1
            k = _err_kind(msg)
            err_kinds[k] = err_kinds.get(k, 0) + 1
            if len(err_samples) < 8 or err_samples and err_samples[-1][0] != k:
                err_samples.append([k, ph['file'], msg[:120]])
        done += 1
        if done % COMMIT_EVERY == 0:
            # 批量提交 + 中途落盘 —— 治理跑到一半被 Ctrl-C，不至于白跑
            con.commit()
            save_ocr_cache()
            save_vision_cache()
        if progress:
            progress(done, len(rows), ph['file'], linked)
    # 收尾：不足一批的尾巴别丢
    con.commit()
    save_ocr_cache()
    save_vision_cache()

    # 重复文件跟随原图：不单独治理，直接继承原图的关联
    inherit_duplicates(con)

    return {
        'total': len(rows), 'done': done, 'ok': ok, 'failed': failed,
        'skipped': skipped, 'linked': linked, 'cleared_auto': cleared,
        'ocr_from_cache': hits_cache, 'ocr_cache_size': cached_n,
        'seconds': round(time.time() - t0, 1),
        'stopped': bool(stop_event is not None and stop_event.is_set()),
        # 失败诊断（2026-10-06）：不给它就只能对着「失败 N 张」干瞪眼
        'errors': [{'kind': k, 'count': n}
                   for k, n in sorted(err_kinds.items(), key=lambda x: -x[1])][:8],
        'error_samples': err_samples[:8],
        'vision_on': bool(use_vision and vision.enabled()),
        'ocr_on': bool(use_ocr),
    }


def inherit_duplicates(con):
    """重复文件（MD5 相同）继承原图的关联，不重复治理。

    实测 249 张里有 13 张是 `- 副本`（MD5 逐字节相同）。
    它们不是独立证据，治理两遍纯属浪费，且会让 photo_count 虚高。
    """
    n = 0
    for p in con.execute('SELECT * FROM photos WHERE is_dup=1 AND dup_of IS NOT NULL'):
        src = con.execute('SELECT id FROM photos WHERE file=?', (p['dup_of'],)).fetchone()
        if not src:
            continue
        con.execute("UPDATE photos SET govern_state='done',photo_kind="
                    "(SELECT photo_kind FROM photos WHERE id=?) WHERE id=?",
                    (src['id'], p['id']))
        for l in con.execute('SELECT * FROM links WHERE photo_id=?', (src['id'],)):
            try:
                con.execute('INSERT OR IGNORE INTO links(code_norm,photo_id,source,'
                            'confidence,evidence,created_at,created_by)'
                            ' VALUES (?,?,?,?,?,?,?)',
                            (l['code_norm'], p['id'], l['source'], l['confidence'],
                             '继承重复文件:' + p['dup_of'], store.now_iso(), 'system'))
                n += 1
            except Exception:
                pass
    con.commit()
    store.recalc_product_counts(con)
    return n
