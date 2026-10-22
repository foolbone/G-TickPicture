# -*- coding: utf-8 -*-
"""校验 server.py 拆包后：路由集合与拆分前完全一致，且全部 import 正常。"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 拆分前 server.py 里登记的全部路由（从原文件逐行抄下来的 (方法, 路径)）
BEFORE = [
    ('GET', '/'),
    ('GET', '/api/stats'),
    ('GET', '/api/products'),
    ('GET', '/api/products/{code}'),
    ('GET', '/api/products/{code}/photos'),
    ('POST', '/api/products/import'),
    ('POST', '/api/products'),
    ('PATCH', '/api/products/{code}'),
    ('POST', '/api/photos/skip'),
    ('GET', '/api/photos/skipped'),
    ('GET', '/api/fields'),
    ('POST', '/api/photos/import-folder'),
    ('POST', '/api/photos/upload'),
    ('GET', '/api/photos'),
    ('GET', '/api/batches'),
    ('GET', '/api/photos/{pid}'),
    ('GET', '/thumb/{pid}'),
    ('GET', '/img/{pid}'),
    ('POST', '/api/govern'),
    ('GET', '/api/govern/status'),
    ('POST', '/api/govern/stop'),
    ('POST', '/api/govern/ocr-backfill'),
    ('GET', '/api/govern/ocr-backfill/status'),
    ('GET', '/api/workbench'),
    ('GET', '/api/photos/{pid}/candidates'),
    ('GET', '/api/search-products'),
    ('POST', '/api/links'),
    ('DELETE', '/api/links'),
    ('GET', '/api/discover'),
    ('POST', '/api/products/from-photo'),
    ('POST', '/api/discover/ignore'),
    ('GET', '/api/merge-suggestions'),
    ('POST', '/api/merge/confirm'),
    ('POST', '/api/export/standard'),
    ('POST', '/api/report/lookup'),
    ('POST', '/api/report/export'),
    ('POST', '/api/report/codes-from-file'),
    ('POST', '/api/standard-images'),
    ('POST', '/api/standard-images/upload'),   # products.js 上传标准图（多文件）
    ('GET', '/api/standard-images'),
    ('GET', '/api/ping'),                     # 启动脚本/前端核对「这个端口后面站的是谁」
    ('GET', '/std-img/{sid}'),
    ('DELETE', '/api/standard-images/{sid}'),
    ('GET', '/api/vision/config'),
    ('POST', '/api/vision/config'),
    ('POST', '/api/vision/test'),
]

# ═══════════════════════════════════════════════════════════════════
# 拆包后新增的路由 —— **必须登记**（方法, 路径, 前端在哪儿用）
#
# 为什么要登记而不是「多出来就 FAIL」：
#   这个检查的本意是**防丢**（拆包时别把路由弄丢），不是「禁止加功能」。
#   原来的写法（多出的路由 = FAIL）让它变成了「加任何端点都会红」——
#   于是 10-05 之后它长期挂着 2 条 FAIL，没人再敢看它，红灯反而变成噪音。
#   改成登记制：新增端点写清前端落点才放行；**没登记的**仍然 FAIL，
#   那才是真问题（幽灵端点：后端有、前端无，永远没人调）。
ADDED = {
    # ── 柜号主线（2026-10-05 v3）──
    ('GET', '/api/containers'): '柜页 web/static/js/containers.js（柜列表）',
    ('POST', '/api/containers'): '柜页（新建柜）',
    ('GET', '/api/containers/{cid}'): '柜详情（聚合面板）',
    ('PUT', '/api/containers/{cid}'): '柜详情（编辑柜信息）',
    ('POST', '/api/containers/{cid}/reassign'): '柜详情（未分柜批次改挂）',
    ('GET', '/api/containers/{cid}/checklist'): '柜详情（核对清单表）',
    ('GET', '/api/containers/{cid}/supervision-photos'):
        'wizard.js ④选图（监装照片分组候选：柜况④/卡车⑦人工指定）',
    ('GET', '/api/containers/{cid}/supervision-pending'):
        'wizard.js ③治理（监装照片细分确认待办：AI 建议不自动生效）',
    ('GET', '/api/containers/{cid}/progress'): '作业向导 web/static/js/wizard.js（五步就绪度）',
    # 建柜表单默认值：记住上次输入的客户/Inspector/Location（10-09 加端点时漏登记）
    ('GET', '/api/containers/form-defaults'):
        'containers.js 建柜弹窗（预填上次输入 + 历史值下拉）',
    ('POST', '/api/checklist/rows/check'): '柜详情（人工核对 Loading Qty / 结论）',
    ('POST', '/api/photos/supervision-tag'): '照片页监装筛选（批量打标签）',
    ('GET', '/api/photos/supervision-tags'): '照片页监装筛选（标签字典与计数）',
    ('POST', '/api/photos/supervision-tag/accept-ai'):
        '照片详情抽屉 drawer.js（采用大模型给的监装细分建议）',
    # ── 10-05 已存在但当时漏登记的（历史欠账，本次补齐）──
    ('GET', '/api/products/containers'): 'products.js（柜号下拉）',
    ('GET', '/api/products/suggest'):
        '照片详情抽屉 drawer.js（关联编码输入联想，2026-10-19）',
    # Vue 3 新前端（2026-10-18 改造分支）：/app/ 托管 web-app-dist 静态资源
    ('GET', '/app/{rest:path}'):
        'routes/app.py（Vue3 新前端入口，web-app-dist/ 静态托管）',
    ('GET', '/api/products/template'): 'products.js（导入模板）',
    ('GET', '/api/products/{code}/candidates'): 'products.js（详情候选）',
    ('GET', '/api/products/{code}/candidates/rejected'): 'products.js（已否决区）',
    ('POST', '/api/products/{code}/candidates/reject'): 'products.js（标记无关联）',
    ('POST', '/api/products/{code}/candidates/unreject'): 'products.js（撤销否决）',
    ('DELETE', '/api/products/{code}'): 'products.js（删产品）',
    ('POST', '/api/products/relink'): 'products.js（补关联）',
    ('GET', '/api/checklist-batches'): 'report.js（按柜号加载清单）',
    ('GET', '/api/batches/{bid}/products'): 'report.js',
    ('GET', '/api/photos/groups'): 'photos.js（分组聚类视图）',
    ('GET', '/api/photos/linkstate'): 'photos.js / wizard.js（五档分组计数，选项卡徽章）',
    ('GET', '/api/photos/facets'): 'phototree.js（左侧树形筛选的用途/分类计数，2026-10-14）',
    ('GET', '/api/photos/carton-groups'): 'wizard.js（③按箱号分组展示，2026-10-14）',
    ('GET', '/api/photo-flags'): 'photos.js / wizard.js（卡片「待确认 / 新产品」角标，异步补）',
    ('POST', '/api/photos/regroup'): 'photos.js（按时序重算分组）',
    ('POST', '/api/photos/invalid'): 'photos.js（批量标记/撤销无效照片，2026-10-12）',
    ('POST', '/api/photos/ignore'):
        'photos.js / drawer.js / wizard.js（批量标记/恢复本次忽略，2026-10-18）',
    ('POST', '/api/photos/kind'): 'drawer.js / photos.js（人工改照片分类，2026-10-15）',
    ('POST', '/api/photos/{pid}/regovern'):
        'drawer.js（改判即重治：按人工分类重跑读码链路，2026-10-15）',
    ('GET', '/api/photos/auto-invalid'):
        'wizard.js ③「清单/包装清理」模态（系统识别+确认批量无效，2026-10-15）',
    ('GET', '/api/photos/dups'):
        'wizard.js ③「重复图片」模态（dHash 相似重复分组，2026-10-15）',
    ('GET', '/api/photos/{pid}/panoramas'):
        'drawer.js「可能的全景图」段（确认归入同一产品，2026-10-15）',
    ('POST', '/api/govern/ocr-backfill'):
        'batches.js 治理面板「OCR 补跑」（存量零 token 照片补提编码，2026-10-15）',
    ('GET', '/api/govern/ocr-backfill/status'):
        'batches.js 治理面板（补跑进度轮询，2026-10-15）',
    ('POST', '/api/photos/import-auto'): 'photos.js（自动识别格式导入）',
    ('POST', '/api/photos/import-standard'): 'photos.js（标准格式导入）',
    ('PATCH', '/api/photos/{pid}/usage'): 'photos.js（单张标用途）',
    ('POST', '/api/batches/{bid}/usage'): 'batches.js（整批标用途）',
    ('GET', '/api/browse'): 'dirpicker.js（目录选择）',
    # ── 装柜报告 docx（v3 P3 已完成，前端区块 P4 待接）──
    ('GET', '/api/report/loading-preview'): 'report.js 报告中心①选柜就绪度',
    ('POST', '/api/report/loading-docx'): 'report.js 报告中心③生成',
    ('GET', '/api/report/loading-file'): '报告中心③④下载链接',
    ('DELETE', '/api/report/loading-file'): '报告中心④删除已生成报告',
    ('GET', '/api/report/loading-list'): '报告中心④已生成报告列表',
    ('GET', '/api/report/templates'): 'report.js 抬头模板下拉（P4 待接）',
}

fails = []


def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond:
        fails.append(name)


def main():
    from tools.productlib.server import app
    builtin = ('/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc')
    after = []
    for r in app.routes:
        methods = getattr(r, 'methods', None)
        if not methods or r.path in builtin:
            continue  # 静态挂载 / FastAPI 自带文档
        for m in sorted(methods):
            if m in ('HEAD', 'OPTIONS'):
                continue
            after.append((m, r.path))

    a, b = set(after), set(BEFORE)
    miss = sorted(b - a)
    extra = sorted(a - b)
    chk('无丢失的路由', not miss, miss)
    unlisted = [e for e in extra if e not in ADDED]
    chk('新增路由都已登记落点（防幽灵端点）', not unlisted, unlisted)
    print('[INFO] 核心 %d + 已登记新增 %d = 实际 %d'
          % (len(b), len(set(extra) & set(ADDED)), len(after)))
    stale = sorted(set(ADDED) - a)
    if stale:
        print('[WARN] 登记了但实际不存在（该端点已删/改名）：%s' % stale)

    # 关键顺序：字面量路径必须早于路径参数
    order = [r.path for r in app.routes if getattr(r, 'methods', None)]
    chk('/api/photos/skipped 早于 /api/photos/{pid}',
        order.index('/api/photos/skipped') < order.index('/api/photos/{pid}'),
        '%d < %d' % (order.index('/api/photos/skipped'), order.index('/api/photos/{pid}')))
    chk('/api/photos/auto-invalid 早于 /api/photos/{pid}',
        order.index('/api/photos/auto-invalid') < order.index('/api/photos/{pid}'),
        '字面量端点被 {pid} 吞掉 = 永远拿到照片详情的形状')
    chk('/api/photos/dups 早于 /api/photos/{pid}',
        order.index('/api/photos/dups') < order.index('/api/photos/{pid}'),
        '同上')
    chk('/api/containers/{cid}/checklist 早于 /api/containers/{cid}',
        _lt(order, '/api/containers/{cid}/checklist', '/api/containers/{cid}')
        if '/api/containers/{cid}/checklist' in order else True,
        '字面量子路径必须先于路径参数，否则被吃掉')

    # deps 能被独立 import（cli / selftest 也要用）
    import importlib
    for m in ('deps', 'routes.pages', 'routes.stats', 'routes.containers',
              'routes.products', 'routes.photos',
              'routes.govern', 'routes.review', 'routes.discover', 'routes.merge',
              'routes.report', 'routes.standard', 'routes.settings'):
        try:
            importlib.import_module('tools.productlib.' + m)
            chk('import tools.productlib.%s' % m, True)
        except Exception as e:
            chk('import tools.productlib.%s' % m, False, '%s: %s' % (type(e).__name__, e))

    print('----')
    print('FAIL %d' % len(fails))
    for f in fails:
        print('  - ' + f)
    return len(fails) == 0


def _lt(order, a, b):
    return order.index(a) < order.index(b)


if __name__ == '__main__':
    sys.exit(0 if main() else 1)

