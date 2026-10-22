# -*- coding: utf-8 -*-
"""Vue 3 新前端（/app/ 前缀）—— 与旧版 index.html 并存。

产物由 frontend/（Vue 3 + Vite + Element Plus 源码）构建到
web-app-dist/（入库，打包直接收录，现场无需 Node）。本路由：
  · /app/            → 回退 web-app-dist/index.html（vue-router history 模式）
  · /app/assets/*    → 静态资源（带 1 年缓存，文件名带 hash）
两套前端的 API 完全同一套 /api/*，无后端分叉。
"""
import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from tools.productlib.deps import WEB_DIR, STATIC_DIR

router = APIRouter()

APP_DIST = os.path.join(os.path.dirname(WEB_DIR), 'web-app-dist')

# content-hash 资源可长期缓存；index.html 不缓存（发版即生效）
_ASSET_HEADERS = {'Cache-Control': 'public, max-age=31536000, immutable'}
_HTML_HEADERS = {'Cache-Control': 'no-cache'}


def _app_file(name):
    return os.path.join(APP_DIST, name)


@router.get('/app/{rest:path}')
def app_frontend(rest: str = ''):
    """服务 Vue 构建产物；非资源路径回退 index.html（history 路由）。"""
    if rest:
        cand = os.path.normpath(os.path.join(APP_DIST, rest))
        # 🔴 防目录穿越：解析后必须仍在 web-app-dist 内
        if cand.startswith(os.path.abspath(APP_DIST)) and os.path.isfile(cand):
            if rest.startswith('assets/'):
                return FileResponse(cand, headers=_ASSET_HEADERS)
            return FileResponse(cand, headers=_HTML_HEADERS)
    idx = _app_file('index.html')
    if os.path.isfile(idx):
        return HTMLResponse(open(idx, encoding='utf-8').read(), headers=_HTML_HEADERS)
    return HTMLResponse(
        '<h3>新前端尚未构建</h3><p>在 tools/productlib/frontend/ 下执行'
        ' <code>npm install &amp;&amp; npm run build</code> 后刷新。</p>', status_code=404)
