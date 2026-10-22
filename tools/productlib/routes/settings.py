# -*- coding: utf-8 -*-
"""多模态（vision）配置与连通性测试

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
# 多模态配置
# ═══════════════════════════════════════════════════════════════════

@router.get('/api/vision/config')
def api_vision_get():
    cfg = vision.load_config()
    return {
        'enabled': vision.enabled(),
        'api_base': cfg.get('api_base') or '',
        'model': cfg.get('model') or '',
        'has_key': bool(cfg.get('api_key')),
    }


@router.post('/api/vision/config')
def api_vision_set(payload: dict):
    vision.save_config(payload.get('api_base', ''), payload.get('api_key', ''),
                       payload.get('model', ''))
    return api_vision_get()


@router.post('/api/vision/test')
def api_vision_test():
    """拿一张照片试调一次 —— 配了 key 之后先跑这个，别直接全量治理。"""
    if not vision.enabled():
        raise HTTPException(400, '未配置 API key')
    c = con()
    try:
        r = c.execute('SELECT path FROM photos WHERE govern_state IN ("done","pending")'
                      ' AND is_dup=0 AND path IS NOT NULL LIMIT 1').fetchone()
    finally:
        c.close()
    if not r:
        raise HTTPException(400, '库里没有可测试的照片')
    t0 = time.time()
    try:
        _full = store.resolve_photo_path(c, r['id'], r['path'])
        cls = vision.classify(_full)
        dsc = vision.describe(_full)
        return {'ok': True, 'seconds': round(time.time() - t0, 1),
                'classify': cls, 'describe': dsc,
                'file': os.path.basename(r['path'])}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '调用失败：%s' % e)
