# -*- coding: utf-8 -*-
"""人工关联：待办队列/候选/建链与解链

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
# 第 4 条：人工关联
# ═══════════════════════════════════════════════════════════════════

@router.get('/api/workbench')
def api_workbench(limit: int = 24, offset: int = 0):
    """人工关联工作台：未关联照片 + 每张的候选产品。
    物料清单/场景照（NO_LINK_KINDS）不进工作台 —— 它们本就不关联产品。"""
    c = con()
    try:
        rows = store.unlinked_photos(c, limit=limit, offset=offset,
                                     exclude_kinds=schema.NO_LINK_KINDS)
        items = []
        for r in rows:
            d = _photo_out(c, r)
            d['candidates'] = _candidates_for(c, r)
            items.append(d)
        total = store.stats(c)['unlinked']
        return {'total': total, 'items': items}
    finally:
        c.close()


def _candidates_for(c, photo, include_semantic=False, min_score=None):
    """「建议关联」的候选。**只给编码类、且够确信的**。

    2026-10-02 改（老板要求）：
      · **去掉语义候选**。它靠大模型描述与品名的词面重合打分，
        上限压在 SCORE_SEMANTIC(0.60) 以下，实际给出的是噪声 ——
        真实库里 products 的 spec/brand/unit 几乎全空，匹配出的是
        "看起来像"而不是"就是它"。建议列表里堆一堆错的，比不给更糟。
      · **低于 CAND_MIN_SCORE 的编码候选也不给**。宁可让老板手输，
        也不要他从一堆低分里挑。

    保留 fuzzy 标记：OCR 可能读错（edit1/edit2），这类要显示但**明确标注
    需核对** —— 自动关联不认它，人也不能被它骗。

    [include_semantic]=True 可临时恢复语义候选（调试/对比用，默认关）。
    物料清单/场景照（NO_LINK_KINDS）直接返回空 —— 它们不进人工关联流程。
    """
    if not isinstance(photo, dict):
        photo = dict(photo)  # 调用方有时传 sqlite3.Row，统一成 dict
    if photo.get('photo_kind') in schema.NO_LINK_KINDS:
        return []
    min_score = schema.CAND_MIN_SCORE if min_score is None else min_score
    out = []
    try:
        import build_library as BL
        idx = BL.CodeIndex([(r['code'], r['name'], r['spec'])
                            for r in c.execute('SELECT code,name,spec FROM products')])
        seen = set()

        def add(code, name, score, why, raw, fuzzy):
            # 门槛：低于 CAND_MIN_SCORE 一律不进建议列表
            if score < min_score or code in seen:
                return
            seen.add(code)
            out.append({'code': code, 'name': name, 'score': round(score, 3),
                        'why': why, 'raw': raw, 'fuzzy': fuzzy})

        # 1) 多模态读出的编码（label/装箱单类）
        try:
            vc = photo.get('vision_codes')
            if vc and vc not in ('', '[]'):
                codes = json.loads(vc) if isinstance(vc, str) else vc
                for cc in codes:
                    m = idx.best(str(cc), 0.95)
                    if m:
                        add(m[0], m[1], m[2], '多模态读出「%s」' % cc, cc, m[3] != 'exact')
        except Exception:  # noqa: BLE001
            pass

        # 2) OCR token 命中
        for t in c.execute('SELECT raw_text,confidence FROM ocr_tokens'
                           ' WHERE photo_id=? ORDER BY confidence DESC LIMIT 40',
                           (photo['id'],)):
            txt = (t['raw_text'] or '').strip()
            if len(txt) < BL.MATCH_MIN_TOKEN_LEN:
                continue
            m = idx.best(txt, float(t['confidence'] or 0))
            if m:
                add(m[0], m[1], m[2], 'OCR 命中「%s」（%s）' % (txt[:30], m[3]), txt, m[3] != 'exact')

        # 3) 语义候选 —— 默认关闭，见 docstring
        if include_semantic:
            for cnd in pipeline.semantic_candidates(c, photo.get('vision_desc'), limit=6):
                if cnd['code'] not in seen and cnd['score'] >= min_score:
                    add(cnd['code'], cnd['name'], cnd['score'], cnd['why'], '', True)
    except Exception:  # noqa: BLE001
        pass
    out.sort(key=lambda x: (-(0 if x.get('fuzzy') else 1), -x.get('score', 0)))
    return out[:12]


@router.get('/api/photos/{pid}/candidates')
def api_candidates(pid: str):
    c = con()
    try:
        r = c.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
        if not r:
            raise HTTPException(404, '照片不存在')
        return {'items': _candidates_for(c, r)}
    finally:
        c.close()


@router.get('/api/search-products')
def api_search_products(q: str = '', limit: int = 20):
    """人工关联时手输编码/品名检索。"""
    c = con()
    try:
        rows = store.list_products(c, keyword=q or None, limit=limit)
        return {'items': [dict(r) for r in rows]}
    finally:
        c.close()


@router.post('/api/links')
def api_link(payload: dict):
    """建立关联 —— 唯一入口 store.link()。

    支持单张（photo_id）或批量（photo_ids 数组，如同组连拍照片一键关联）。
    """
    code = (payload.get('code') or '').strip()
    pids = payload.get('photo_ids') or []
    pid = (payload.get('photo_id') or '').strip()
    if pid:
        pids = [pid]
    if not code or not pids:
        raise HTTPException(400, 'code 与 photo_id/photo_ids 都不能为空')
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        if not p:
            raise HTTPException(400, '产品库里没有这个编码：%s（先导入清单或手工补录）' % code)
        n = 0
        for pid_ in pids:
            pid_ = str(pid_).strip()
            if not pid_:
                continue
            if not c.execute('SELECT id FROM photos WHERE id=?', (pid_,)).fetchone():
                continue
            store.link(c, p['code_norm'], pid_, source='manual', confidence=1.0,
                       evidence=payload.get('evidence') or '人工关联',
                       created_by=payload.get('by') or 'user')
            n += 1
        return {'ok': True, 'linked': n}
    finally:
        c.close()


@router.delete('/api/links')
def api_unlink(payload: dict):
    code = (payload.get('code') or '').strip()
    pid = (payload.get('photo_id') or '').strip()
    c = con()
    try:
        p = c.execute('SELECT code_norm FROM products WHERE code_norm=? OR code=?',
                      (code, code)).fetchone()
        cn = p['code_norm'] if p else code
        n = store.unlink(c, cn, pid)
        return {'ok': True, 'removed': n}
    finally:
        c.close()
