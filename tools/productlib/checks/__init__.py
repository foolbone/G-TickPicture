# -*- coding: utf-8 -*-
"""常驻校验脚本（不是一次性补丁，删了就没有回归能力了）。

用法（仓库根目录执行）：
    python -m tools.productlib.checks.esm_syntax     前端 ES module 语法
    python -m tools.productlib.checks.esm_graph      前端导入导出 / 循环依赖
    python -m tools.productlib.checks.web_contract   前端元素 id 与 API 端点交叉核对
    python -m tools.productlib.checks.routes         后端路由集合与拆分前一致
    python -m tools.productlib.checks.api_smoke      接口冒烟（只读）
    python -m tools.productlib.checks.cdp_regress    浏览器实跑全量回归（需先起服务）
    python -m tools.productlib.checks.cdp_features   抽屉/放大镜/空态/滚动专项
    python -m tools.productlib.checks.cdp_view       分类配色 + 紧凑/详情视图专项
    python -m tools.productlib.checks.cdp_layout     去流程条 + 批次抽屉专项

⚠️ 需要服务的脚本（cdp_*、api_smoke）前必须先起：
    python -m tools.productlib.server --no-browser --port 8765
"""

