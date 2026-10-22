# -*- coding: utf-8 -*-
"""页面入口（SPA 外壳）

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
# 页面
# ═══════════════════════════════════════════════════════════════════

@router.get('/', response_class=HTMLResponse)
def index():
    p = os.path.join(WEB_DIR, 'index.html')
    if not os.path.exists(p):
        return HTMLResponse('<h1>缺少 web/index.html</h1>', status_code=500)
    with open(p, 'r', encoding='utf-8') as f:
        return HTMLResponse(f.read())
