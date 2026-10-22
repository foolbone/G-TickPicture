# 集刻产品库 · Vue 3 前端（改造分支）

Vue 3 + Vite + Element Plus 重写版，挂 `/app/` 前缀与旧版（原生 JS）
**并存**：同一套 `/api/*`，同一个 SQLite，随时可回旧版。

## 开发

```bash
cd tools/productlib/frontend
npm install          # 首次
npm run dev          # http://localhost:5175/app/ —— /api 等已 proxy 到 127.0.0.1:8765
```

后端起一个 8765 实例即可（`PL_HOME=... python -m tools.productlib.server --port 8765`）。

## 构建与部署

```bash
npm run build        # 产物 → ../web-app-dist/（入库，现场/打包不需要 Node）
```

服务端 `routes/app.py` 把 `/app/*` 指到 web-app-dist，history 路由回退
index.html。**打包版**：productlib.spec 已收录 web-app-dist。

## 迁移顺序（每迁一个页面 = 一个提交）

已迁移：柜列表（containers，模式样板：api.js 封装 + el-table + 筛选条）。
待迁：photos（照片库）→ wizard（柜作业五步，体量最大 1814 行，建议
拆五个子组件）→ products → review（审核三段）→ batches（治理面板，
含多任务轮询）→ report / settings / home。

## 约定

- API 一律走 `src/api.js`（错误统一 ElMessage，别散落 fetch）
- 页面放 `src/views/`，可复用块放 `src/components/`
- 旧版入口保留：`/`（原生 JS 版）；新前端菜单里有「返回旧版」
- **改造期间旧版保持可用**——CDP 旧断言不迁移、不修改，等页面切换
  完成后再统一改写对应检查
