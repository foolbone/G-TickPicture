# -*- coding: utf-8 -*-
"""合并建议 + 标准库落盘

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
# 第 7 条：合并建议 + 标准库落盘
# ═══════════════════════════════════════════════════════════════════

@router.get('/api/merge-suggestions')
def api_merge_suggestions():
    """合并建议：照片读出编码 ↔ 库内产品匹配、但照片尚未关联，按产品聚合。"""
    c = con()
    try:
        return {'items': store.merge_suggestions(c)}
    finally:
        c.close()


@router.post('/api/merge/confirm')
def api_merge_confirm(payload: dict):
    """人工确认合并：照片批量关联到产品（source=manual，可追溯）。"""
    code = (payload.get('code') or '').strip()
    photo_ids = payload.get('photo_ids') or []
    if not code or not photo_ids:
        raise HTTPException(400, 'code 与 photo_ids 都不能为空')
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在：%s' % code)
        return store.confirm_merge(c, p['code_norm'], photo_ids,
                                   by=payload.get('by') or 'user')
    finally:
        c.close()


@router.post('/api/export/standard')
def api_export_standard(payload: dict):
    """标准库落盘：confirmed 产品的关联照片复制到指定目录（编码_类别 命名 + CSV）。"""
    out_dir = (payload.get('dir') or '').strip()
    if not out_dir:
        raise HTTPException(400, '请填写导出目录')
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        raise HTTPException(400, '该路径不是目录：%s' % out_dir)
    c = con()
    try:
        return store.export_standard(c, out_dir)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '导出失败：%s' % e)
    finally:
        c.close()
