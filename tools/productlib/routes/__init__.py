# -*- coding: utf-8 -*-
"""按业务域拆分的 FastAPI 路由包。

include 顺序沿用原 server.py 的声明顺序 —— 有字面量路径
（/api/photos/skipped）必须排在路径参数（/api/photos/{pid}）之前，
否则会被参数路由吃掉。新增模块时务必插在正确位置。
"""
from fastapi import APIRouter

from tools.productlib.routes import pages
from tools.productlib.routes import stats
from tools.productlib.routes import containers
from tools.productlib.routes import progress
from tools.productlib.routes import products
from tools.productlib.routes import photos
from tools.productlib.routes import govern
from tools.productlib.routes import review
from tools.productlib.routes import discover
from tools.productlib.routes import merge
from tools.productlib.routes import report
from tools.productlib.routes import standard
from tools.productlib.routes import settings

api_router = APIRouter()

api_router.include_router(pages.router)
api_router.include_router(stats.router)
# ⚠️ containers 必须排在 products/photos 之前：它注册了
# `/api/containers/{cid}` 这样的路径参数路由，虽然前缀不同不会互相吃掉，
# 但「柜是第一步」的语义上它也该先装载。
api_router.include_router(containers.router)
api_router.include_router(progress.router)
api_router.include_router(products.router)
api_router.include_router(photos.router)
api_router.include_router(govern.router)
api_router.include_router(review.router)
api_router.include_router(discover.router)
api_router.include_router(merge.router)
api_router.include_router(report.router)
api_router.include_router(standard.router)
api_router.include_router(settings.router)
# Vue 3 新前端（/app/ 前缀，2026-10-18 改造分支）—— 字面量路径，放最后无妨
from tools.productlib.routes import app as app_frontend  # noqa: E402
api_router.include_router(app_frontend.router)
