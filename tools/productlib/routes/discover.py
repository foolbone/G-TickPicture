# -*- coding: utf-8 -*-
"""发现新产品：候选/建产品/忽略

由 server.py 按业务域切出，逻辑未改。
"""
import json
import os
import shutil
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# deps 放最前：它负责 sys.path 引导
from tools.productlib.deps import (  # noqa: F401
    DATA_DIR, ROOT, THUMB_DIR, UPLOAD_DIR, WEB_DIR,
    _GOVERN, _LOCK, _photo_out, _run_govern, con,
)
from tools.productlib import pipeline, schema, store, vision

router = APIRouter()

# ═══════════════════════════════════════════════════════════════════
# 第 6 条：发现新产品（照片读出 → 人工确认 → 入产品库）
# ═══════════════════════════════════════════════════════════════════

@router.get('/api/discover')
def api_discover(ocr_min_conf: float = 0.85, min_conf: float = 0.60,
                 batch: str = ''):
    """候选新产品列表：照片里读出、库内没有的疑似编码，按置信度降序。

    候选基于已治理照片（vision_codes / ocr_tokens）。
    batch：可选，按照片批次筛选（柜号批次），空=全部批次。
    列表为空时多半是还没治理或都已在库 —— 先去「照片与治理」跑治理。
    """
    c = con()
    try:
        items = store.discovered_products(c, ocr_min_conf=ocr_min_conf,
                                          min_conf=min_conf,
                                          batch_id=batch or None)
        return {'items': items, 'ignored': store.count_ignored(c)}
    finally:
        c.close()


@router.post('/api/products/from-photo')
def api_product_from_photo(payload: dict):
    """确认候选为新产品：写 products + 来源照片自动建 links（source=auto_vision）。"""
    code = (payload.get('code') or '').strip()
    if not code:
        raise HTTPException(400, '编码不能为空')
    c = con()
    try:
        r = store.confirm_product(c, code,
                                  name=payload.get('name') or '',
                                  spec=payload.get('spec') or '',
                                  photo_ids=payload.get('photo_ids') or [],
                                  by=payload.get('by') or 'user')
        return r
    except store.ProductError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post('/api/discover/ignore')
def api_discover_ignore(payload: dict):
    """忽略一个候选（拉黑，之后不再出现在发现列表）。"""
    code = (payload.get('code') or '').strip()
    if not code:
        raise HTTPException(400, '编码不能为空')
    c = con()
    try:
        store.ignore_discovery(c, code)
        return {'ok': True}
    finally:
        c.close()
