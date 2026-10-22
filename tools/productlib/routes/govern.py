# -*- coding: utf-8 -*-
"""治理：启动与进度

由 server.py 按业务域切出，逻辑未改。
"""
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# deps 放最前：它负责 sys.path 引导
from tools.productlib.deps import (  # noqa: F401
    DATA_DIR, ROOT, THUMB_DIR, UPLOAD_DIR, WEB_DIR,
    _GOVERN, _GOVERN_STOP, _LOCK, _photo_out, con,
    govern_start, govern_status, govern_stop,
)
from tools.productlib import pipeline, schema, store, vision

router = APIRouter()

# ═══════════════════════════════════════════════════════════════════
# 治理（2026-10-18 起多任务：不同批次可并行，全量任务独占）
# ═══════════════════════════════════════════════════════════════════

@router.post('/api/govern')
def api_govern(payload: dict):
    """启动后台治理。轮询 /api/govern/status 看进度。

    body: {limit, use_vision, use_ocr, reset, batch_id, retry_failed, skip_linked}
    [batch_id]：只治理该批次（新批次导入后的常规用法）。
    [reset]=True：把范围内照片重置为待治理再跑（配好多模态后想重新分类时用）。
    [retry_failed]=True：只把范围内失败的照片重置为待治理再跑，不清关联。
    [skip_linked]=True（2026-10-18 老板需求，reset 时有效）：跳过已关联的
    照片 —— 不重置、不清其自动关联、不重跑。
    并行规则（2026-10-18 老板需求 4）：不同批次可同时治理；全量任务
    （不带 batch_id）独占 —— 它覆盖所有照片，与任何任务都冲突。
    """
    limit = payload.get('limit') or None
    use_vision = bool(payload.get('use_vision', True))
    use_ocr = bool(payload.get('use_ocr', True))
    reset = bool(payload.get('reset', False))
    retry_failed = bool(payload.get('retry_failed', False))
    skip_linked = bool(payload.get('skip_linked', False))
    batch_id = (payload.get('batch_id') or '').strip() or None
    r = govern_start(limit=limit, use_vision=use_vision, use_ocr=use_ocr,
                     reset=reset, batch_id=batch_id, retry_failed=retry_failed,
                     skip_linked=skip_linked)
    if not r.get('started'):
        return r
    return {'started': True, 'limit': limit, 'use_vision': use_vision,
            'use_ocr': use_ocr, 'reset': reset, 'retry_failed': retry_failed,
            'batch_id': batch_id, 'vision_enabled': vision.enabled()}


@router.get('/api/govern/status')
def api_govern_status():
    return govern_status()


@router.post('/api/govern/stop')
def api_govern_stop(payload: dict = None):
    """请求停止治理（2026-10-17；2026-10-18 支持多任务）。

    body 可选 {batch_id}：给了只停该批次任务；不给停全部。
    协作式：置位停止信号后，govern_all 在下一张照片前退出。
    当前这一张（最多几秒的 OCR + 一次大模型调用）跑完就收，
    已治理的保留，剩下的保持 pending 下次接着跑。
    没有任务在跑时返回 ok=False（无害）。
    """
    bid = ((payload or {}).get('batch_id') or '').strip() or None
    r = govern_stop(bid)
    if not r.get('stopped'):
        return {'ok': False, 'reason': '没有治理任务在跑'}
    return {'ok': True, 'stopping': True, 'stopped': r['stopped']}


# ═══════════════════════════════════════════════════════════════════
# OCR 补跑（2026-10-15 需求4：先小模型全量铺底，大模型补充校正）
# ═══════════════════════════════════════════════════════════════════

# 与 _GOVERN 分开记账：补跑是纯本地小模型，可以和「重治理」共存与否要
# 明确判断，不能共用一个 running 位互相看不见。
_OCRBF = {'running': False, 'done': 0, 'total': 0, 'linked': 0,
          'file': '', 'error': None,
          'started': ''}


@router.post('/api/govern/ocr-backfill')
def api_ocr_backfill(payload: dict):
    """给「治理过但没有 OCR token」的照片补跑本地 OCR（后台线程）。

    body: {container_id?, batch_id?} —— 都不给 = 全库补。
    可重复执行：已有 token 的自动跳过，中断了再点一次接着跑。
    轮询 /api/govern/ocr-backfill/status 看进度。
    """
    with _LOCK:
        if _OCRBF['running']:
            return {'started': False, 'reason': '已有 OCR 补跑在跑'}
        _running = [t['name'] for t in govern_tasks() if t.get('running')]
        if _running:
            return {'started': False,
                    'reason': '已有治理任务在跑（%s），先等它完成' % '、'.join(_running)}
        _OCRBF.update(running=True, done=0, total=0, linked=0, file='',
                      error=None,
                      started=datetime.now().isoformat(timespec='seconds'))
    cid = (payload.get('container_id') or '').strip()
    bid = (payload.get('batch_id') or '').strip()
    t = threading.Thread(target=_run_ocrbf, args=(cid, bid), daemon=True)
    try:
        t.start()
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            _OCRBF.update(running=False, error='启动失败：%s' % str(e)[:200])
        raise HTTPException(status_code=500, detail='OCR 补跑线程启动失败')
    return {'started': True, 'container_id': cid, 'batch_id': bid}


def _run_ocrbf(cid, bid):
    c = None
    try:
        c = store.connect()

        def prog(done, total, fname, linked):
            with _LOCK:
                _OCRBF.update(done=done, total=total, file=fname, linked=linked)

        res = pipeline.ocr_backfill(c, container_id=cid, batch_id=bid,
                                    progress=prog)
        with _LOCK:
            _OCRBF.update(running=False, done=res['done'], total=res['total'],
                          linked=res['linked'], file='')
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            _OCRBF.update(running=False, error=str(e)[:500])
    finally:
        if c:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass


@router.get('/api/govern/ocr-backfill/status')
def api_ocrbf_status():
    with _LOCK:
        return dict(_OCRBF)
