# -*- coding: utf-8 -*-
"""概览统计

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
# 概览
# ═══════════════════════════════════════════════════════════════════

@router.get('/api/stats')
def api_stats():
    c = con()
    try:
        d = store.stats(c)
        d['vision_enabled'] = vision.enabled()
        d['vision_model'] = (vision.load_config().get('model') or '') if vision.enabled() else ''
        d['threshold'] = schema.AUTO_LINK_THRESHOLD
        return d
    finally:
        c.close()
