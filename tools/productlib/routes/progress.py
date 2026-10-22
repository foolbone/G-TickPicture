# -*- coding: utf-8 -*-
"""作业向导进度：五步就绪度唯一数据源。零 schema 改动。

前端作业向导页（wizard.js）唯一的数据接口：一次返回五步的完成度与
关键数字（复用具象聚合 container_detail / 批次治理统计 / 报告文件扫描），
数字与柜详情页、报告生成器同源，不各算各的。
"""
from fastapi import APIRouter, HTTPException

from tools.productlib.deps import con
from tools.productlib import store

router = APIRouter()


@router.get('/api/containers/{cid}/progress')
def api_container_progress(cid: str):
    """柜的向导进度。

    🔴 柜不存在要接住，别让它冒成 500（2026-10-07 老板在全新环境用绿色包撞到）。
    柜号是**这个库里的**东西，而前端锚点 `localStorage['plCid']` 按 origin 存、
    **跨库共用** —— 换机器 / 换库后照样会被读出来，于是这里把「柜不存在」
    抛成 500，整页变成「读取向导进度失败：Internal Server Error」，
    用户既看不懂也不知道该干什么。

    用 **400 而不是 404**：前端已经用 404 表示「后端没这个端点、服务进程是旧的」，
    这里再回 404 会让那句提示抢走真因。同 `containers.py` 的 `_err()` 一致。
    """
    c = con()
    try:
        return store.container_progress(c, cid)
    except store.ContainerError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()
