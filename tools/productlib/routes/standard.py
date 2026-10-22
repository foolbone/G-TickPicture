# -*- coding: utf-8 -*-
"""标准图：上传/列表/读取/删除

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
# 第 8 条：标准图（人工裁剪/编辑后的标准格式资产）
# ═══════════════════════════════════════════════════════════════════

@router.post('/api/standard-images')
def api_add_standard_image(payload: dict):
    """保存标准图。body: {code, photo_id, kind, image(base64 JPEG), width, height}"""
    import base64 as b64mod
    code = (payload.get('code') or '').strip()
    photo_id = (payload.get('photo_id') or '').strip()
    b64 = payload.get('image') or ''
    if not code or not photo_id or not b64:
        raise HTTPException(400, 'code / photo_id / image 都不能为空')
    try:
        data = b64mod.b64decode(b64)
    except Exception:
        raise HTTPException(400, 'image 不是合法 base64')
    if len(data) < 100:
        raise HTTPException(400, '图片数据异常（%d 字节）' % len(data))
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在：%s（先入库再挂标准图）' % code)
        if not c.execute('SELECT id FROM photos WHERE id=?', (photo_id,)).fetchone():
            raise HTTPException(404, '源照片不存在')
        return store.add_standard_image(
            c, p['code_norm'], photo_id, payload.get('kind') or 'unknown', data,
            payload.get('width'), payload.get('height'), by=payload.get('by') or 'user')
    finally:
        c.close()


@router.post('/api/standard-images/upload')
def api_upload_standard_images(code: str = Form(...), kind: str = Form('unknown'),
                              files: list[UploadFile] = File(...)):
    """手动上传照片作为该产品的标准图（2026-10-06 老板需求：一个产品可多张）。

    与「制作标准图」的区别：那条路是从**库内已有照片**裁剪/编辑，这条路是直接
    传文件（客户给的图、厂家给的图、库里根本没拍过的件）。

    body: code=产品编码, kind=类别(可留空), files=一个或多个图片文件。
    返回逐个文件的结果：成功的给 {id,file,kind,origin:'upload'}，
    失败的给 {filename, error} —— **一批里一张坏图不阻断其余**。
    """
    code = (code or '').strip()
    if not code:
        raise HTTPException(400, '缺少 code（产品编码）')
    if not files:
        raise HTTPException(400, '没有收到文件')
    if len(files) > 30:
        raise HTTPException(400, '一次最多 30 张，请分批上传')
    if kind not in schema.PHOTO_KINDS:
        kind = 'unknown'
    c = con()
    try:
        p = c.execute('SELECT code_norm, name FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在：%s（先在产品库导入清单，'
                                     '或从新产品确认里入库）' % code)
        cno = p['code_norm']
        ok, bad = [], []
        for f in files:
            fn = os.path.basename(f.filename or '') or 'unnamed'
            try:
                data = f.file.read()
            except Exception as e:  # noqa: BLE001
                bad.append({'filename': fn, 'error': '读取失败：%s' % e})
                continue
            if not data:
                bad.append({'filename': fn, 'error': '文件为空'})
                continue
            r = store.add_standard_upload(c, cno, kind, data, fn,
                                          by='upload:%s' % fn)
            if r.get('error'):
                bad.append({'filename': fn, 'error': r['error']})
            else:
                r['url'] = '/std-img/%s' % r['id']
                ok.append(r)
        total = len(ok) + len(bad)
        # 一个都没成功才算失败 —— 部分成功要如实报出来，不能只说成功
        if not ok:
            raise HTTPException(400, '%d 个文件全部失败：%s'
                                % (len(bad), '；'.join(b['error'] for b in bad[:3])[:240]))
        return {'code_norm': cno, 'uploaded': len(ok), 'failed': len(bad),
                'total': total, 'items': ok, 'errors': bad}
    finally:
        c.close()


@router.get('/api/standard-images')
def api_list_standard_images(code: str = ''):
    if not code:
        raise HTTPException(400, '缺少 code')
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(404, '产品不存在')
        items = []
        for r in store.standard_images(c, p['code_norm']):
            d = dict(r)
            d['origin'] = d.get('origin') or 'crop'   # 老数据 NULL = crop
            d['url'] = '/std-img/%s' % d['id']
            items.append(d)
        return {'items': items,
                'uploaded': sum(1 for i in items if i['origin'] == 'upload')}
    finally:
        c.close()


@router.get('/std-img/{sid}')
def api_std_img(sid: str):
    c = con()
    try:
        r = c.execute('SELECT file FROM standard_images WHERE id=?', (sid,)).fetchone()
    finally:
        c.close()
    if not r or not os.path.exists(r['file']):
        raise HTTPException(404, '标准图不存在')
    return FileResponse(r['file'], media_type='image/jpeg')


@router.delete('/api/standard-images/{sid}')
def api_del_standard_image(sid: str):
    c = con()
    try:
        if not store.delete_standard_image(c, sid):
            raise HTTPException(404, '标准图不存在')
        return {'ok': True}
    finally:
        c.close()
