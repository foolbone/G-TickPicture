# -*- coding: utf-8 -*-
"""柜（container）—— 一等实体，2026-10-05 v3

为什么单独一个路由模块：柜是**流程的第一步**（先建柜，才能导清单/导照片/出报告），
它自己的 CRUD 与「详情聚合面板」构成柜详情页的全部数据源。
批次页降级为本模块的附属视图（批次挂在柜下）。

闸门设计：导入类接口（清单 / 照片）在本模块之外（products.py / photos.py），
但它们统一要求 container_id —— 缺失一律 400「请先选择柜」。
"""
import json
import os
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from tools.productlib.deps import (  # noqa: F401
    DATA_DIR, ROOT, THUMB_DIR, UPLOAD_DIR, WEB_DIR,
    _GOVERN, _LOCK, _photo_out, _run_govern, con,
)
from tools.productlib import schema, store

router = APIRouter()


def _err(e):
    """store.ContainerError → 400（其余异常 → 500 由 FastAPI 兜）。"""
    if isinstance(e, store.ContainerError):
        raise HTTPException(400, str(e))
    raise e


@router.get('/api/containers')
def api_containers(q: str = '', date_from: str = '', date_to: str = ''):
    """柜列表 + 每柜的清单行数/照片数/监装数。柜页的数据源。

    [date_from/date_to]（2026-10-18）：按作业日期（柜内照片拍摄日期）
    筛选柜 —— 老板需求 3。
    """
    c = con()
    try:
        items = store.list_containers(c, keyword=(q or '').strip(),
                                      date_from=(date_from or '').strip(),
                                      date_to=(date_to or '').strip())
        return {'items': items,
                'tags': schema.SUPERVISION_TAGS,
                'condition_tags': list(schema.CONTAINER_CONDITION_TAGS),
                'truck_tags': list(schema.TRUCK_PICTURE_TAGS)}
    finally:
        c.close()


@router.post('/api/containers')
def api_create_container(payload: dict):
    """建柜。柜号唯一，重复直接 400（不静默合并 —— 两个同名柜会毁掉报告归属）。"""
    c = con()
    try:
        # container_no 已经作位置参数传了，不能再混进 **kwargs，
        # 否则 Python 抛「got multiple values for argument」—— UI 建柜带
        # 封条号/客户名时必炸（e2e 实测抓到）。
        fields = {k: v for k, v in (payload or {}).items() if k != 'container_no'}
        return store.create_container(
            c, (payload.get('container_no') or '').strip(), **fields)
    except store.ContainerError as e:
        _err(e)
    finally:
        c.close()


@router.get('/api/containers/form-defaults')
def api_container_form_defaults():
    """建柜表单的预填值（客户 / Inspector / Location 等不常变的字段）。

    ⚠️ **路由顺序**：必须声明在 `/api/containers/{cid}` **之前** ——
    FastAPI 按注册顺序匹配，放在后面会被 `{cid}` 当成柜号吃掉，
    报「柜不存在」（这类坑本项目踩过，别再踩）。
    """
    c = con()
    try:
        return store.container_form_defaults(c)
    finally:
        c.close()


@router.get('/api/containers/{cid}/checklist')
def api_container_checklist(cid: str, batch: str = ''):
    """柜下清单行快照（报告 Packing list 的原始数据，柜详情页核对表用）。"""
    c = con()
    try:
        d = store.container_detail(c, cid)
        rows = []
        for b in d['batches']:
            if b['kind'] != 'checklist':
                continue
            if batch and b['id'] != batch:
                continue
            for r in store.checklist_rows_of(c, b['id']):
                r['batch_id'] = b['id']
                r['batch_name'] = b['name']
                rows.append(r)
        return {'items': rows, 'row_total': d['row_total'],
                'row_unchecked': d['row_unchecked']}
    except store.ContainerError as e:
        _err(e)
    finally:
        c.close()


@router.get('/api/containers/{cid}/supervision-photos')
def api_container_supervision_photos(cid: str):
    """④选图的「监装照片」候选：本柜监装照按 tag 分组（柜况④/卡车⑦）。

    柜详情接口里的 condition_photos 只有「每 tag 自动取的最新一张」，
    老板要在选图步骤**看见并换掉**它们 —— 这里给全量候选。
    """
    c = con()
    try:
        return store.supervision_photos_of(c, cid)
    except store.ContainerError as e:
        _err(e)
    finally:
        c.close()


@router.get('/api/containers/{cid}/supervision-pending')
def api_container_supervision_pending(cid: str):
    """③治理的「监装照片 · 细分确认」待办：没确认细分 / 用途未标但有建议。"""
    c = con()
    try:
        return store.supervision_pending_of(c, cid)
    except store.ContainerError as e:
        _err(e)
    finally:
        c.close()


@router.get('/api/containers/{cid}')
def api_container_detail(cid: str):
    """柜详情聚合面板：元数据 + 批次 + 行数 + 照片统计 + 柜况候选图。

    报告页与柜详情页共用这份数据（数字不会两处漂）。
    """
    c = con()
    try:
        d = store.container_detail(c, cid)
        d['tags'] = schema.SUPERVISION_TAGS
        return d
    except store.ContainerError as e:
        _err(e)
    finally:
        c.close()


@router.put('/api/containers/{cid}')
def api_update_container(cid: str, payload: dict):
    """改柜元数据（封条号/到离柜/Inspector/Location/Product/Client/REMARKS）。"""
    c = con()
    try:
        return store.update_container(c, cid, **payload)
    except store.ContainerError as e:
        _err(e)
    finally:
        c.close()


@router.post('/api/containers/{cid}/reassign')
def api_reassign(cid: str, payload: dict):
    """把批次改挂到本柜（迁移产生的「未分柜」补柜号后用）。"""
    c = con()
    try:
        out = []
        for bid in (payload.get('batch_ids') or []):
            out.append(store.assign_batch_container(c, bid, cid))
        return {'moved': out}
    except store.ContainerError as e:
        _err(e)
    finally:
        c.close()


@router.post('/api/checklist/rows/check')
def api_set_check_result(payload: dict):
    """人工核对结论（Loading Qty / Quantity Check result）。

    ⚠️ 只写人工结论，绝不自动填 PASS —— 机器能判的只有"有没有照片"，
    那是覆盖率不是数量核对结论。空 = 未核对 → 报告沿用清单预填值。
    """
    c = con()
    try:
        return store.set_row_check(
            c, (payload.get('batch_id') or '').strip(), payload.get('seq'),
            (payload.get('check_result') or '').strip(),
            loading_qty=payload.get('loading_qty'),
            by=payload.get('by') or 'user')
    except store.ContainerError as e:
        _err(e)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()
