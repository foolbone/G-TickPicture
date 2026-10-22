# -*- coding: utf-8 -*-
"""
govern_classifier.py — 本地小模型分类器（ONNX）

用途：在大模型 classify() 之前先用本地 MobileNetV2 ONNX 做快速分流，
减少大模型 API 调用次数。小模型失败/未加载时静默降级，不影响主流程。

模型文件：
  tools/productlib/models/usage_cls.onnx      二分类（预检/监装）
  tools/productlib/models/usage_labels.json    类别映射
  tools/productlib/models/kind_cls.onnx       预检四分类（label/product/packaging/packing_list）
  tools/productlib/models/kind_labels.json     类别映射
"""
import json
import os
import threading

from . import paths

_lock = threading.Lock()
_usage_session = None
_usage_labels = None
_usage_loaded = False
_kind_session = None
_kind_labels = None
_kind_loaded = False


def _model_dir():
    # 走 paths.models_dir()：冻结打包版落在 _MEIPASS/models（别拿 __file__ 拼，
    # 冻结后源码目录结构不存在 —— 2026-10-17 打包链路补丁）。
    return paths.models_dir()


def _load_usage():
    """懒加载二分类 ONNX 模型。"""
    global _usage_session, _usage_labels, _usage_loaded
    if _usage_loaded:
        return _usage_session is not None
    with _lock:
        if _usage_loaded:
            return _usage_session is not None
        _usage_loaded = True
        onnx_path = os.path.join(_model_dir(), 'usage_cls.onnx')
        labels_path = os.path.join(_model_dir(), 'usage_labels.json')
        if not os.path.exists(onnx_path):
            return False
        try:
            import onnxruntime as ort
            # 🔴 限 2 线程（2026-10-17）：session 默认用全部核，治理期间与
            #    OCR 推理叠起来整机满转。224×224 的小图分类 2 线程足够快。
            so = ort.SessionOptions()
            so.intra_op_num_threads = 2
            _usage_session = ort.InferenceSession(
                onnx_path, so, providers=['CPUExecutionProvider'])
            with open(labels_path, 'r', encoding='utf-8') as f:
                _usage_labels = json.load(f)['classes']
            return True
        except Exception:
            _usage_session = None
            return False


def classify_usage(image_path):
    """二分类：返回 (usage, conf) 或 None。

    usage: '预检' / '监装'
    conf:  0~1
    模型不可用或推理失败时返回 None（调用方降级到大模型）。
    """
    if not _load_usage():
        return None
    try:
        import numpy as np
        from PIL import Image, ImageFile
        Image.MAX_IMAGE_PIXELS = None
        ImageFile.LOAD_TRUNCATED_IMAGES = True

        # 预处理：resize 224 + ImageNet 归一化
        with Image.open(image_path) as im:
            im = im.convert('RGB').resize((224, 224), Image.LANCZOS)
            arr = np.asarray(im, dtype=np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        arr = arr.transpose(2, 0, 1)[None, ...]  # (1,3,224,224)

        out = _usage_session.run(None, {'input': arr})
        logits = out[0][0]
        # softmax
        e = np.exp(logits - logits.max())
        probs = e / e.sum()
        idx = int(probs.argmax())
        label = _usage_labels[idx]
        # precheck → 预检, supervision → 监装
        usage = '预检' if label == 'precheck' else '监装'
        return usage, float(probs[idx])
    except Exception:
        return None


def _load_kind():
    """懒加载预检四分类 ONNX 模型。"""
    global _kind_session, _kind_labels, _kind_loaded
    if _kind_loaded:
        return _kind_session is not None
    with _lock:
        if _kind_loaded:
            return _kind_session is not None
        _kind_loaded = True
        onnx_path = os.path.join(_model_dir(), 'kind_cls.onnx')
        labels_path = os.path.join(_model_dir(), 'kind_labels.json')
        if not os.path.exists(onnx_path):
            return False
        try:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = 2
            _kind_session = ort.InferenceSession(
                onnx_path, so, providers=['CPUExecutionProvider'])
            with open(labels_path, 'r', encoding='utf-8') as f:
                _kind_labels = json.load(f)['classes']
            return True
        except Exception:
            _kind_session = None
            return False


def classify_kind(image_path):
    """预检四分类：返回 (kind, conf) 或 None。

    kind: 'label' / 'product' / 'packaging' / 'packing_list'
    conf: 0~1
    模型不可用或推理失败时返回 None（调用方降级到大模型）。
    """
    if not _load_kind():
        return None
    try:
        import numpy as np
        from PIL import Image, ImageFile
        Image.MAX_IMAGE_PIXELS = None
        ImageFile.LOAD_TRUNCATED_IMAGES = True

        with Image.open(image_path) as im:
            im = im.convert('RGB').resize((224, 224), Image.LANCZOS)
            arr = np.asarray(im, dtype=np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        arr = arr.transpose(2, 0, 1)[None, ...]

        out = _kind_session.run(None, {'input': arr})
        logits = out[0][0]
        e = np.exp(logits - logits.max())
        probs = e / e.sum()
        idx = int(probs.argmax())
        return _kind_labels[idx], float(probs[idx])
    except Exception:
        return None


def detect_label_region(image_path):
    """用 PaddleOCR DB detector 框出文字区域（标签候选框）。

    返回原图坐标 [(x0,y0,x1,y1,score), ...]，按面积降序。
    未检测到 / 依赖缺失时返回 []（调用方回退整图处理）。
    """
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import pc_ocr_probe as P
        if not getattr(P, 'OCR_AVAILABLE', True):
            return []
        img = cv2_img = P.cv2.imdecode(
            P.np.fromfile(image_path, dtype=P.np.uint8),
            P.cv2.IMREAD_COLOR)
        if img is None:
            return []
        oh, ow = img.shape[:2]
        x, small = P.det_input(img)
        prob = P.det_sess.run(None, {P.DET_IN: x})[0][0, 0]
        boxes = P.boxes_from_prob_map(prob, ow, oh, 1.0)
        # 去掉太小的杂讯框，保留有效文字区域
        keep = []
        for b in boxes:
            x0, y0, x1, y1, sc, _ = b
            if (x1 - x0) < 20 or (y1 - y0) < 8:
                continue
            keep.append([x0, y0, x1, y1, sc])
        return keep
    except Exception:
        return []


def available():
    """返回小模型是否可用（供前端/调试展示）。"""
    return _load_usage() or _load_kind()
