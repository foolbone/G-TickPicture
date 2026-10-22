# Web 端开发须知（Vue 3 改造分支）

> 写于 2026-10-20 深夜，给后续接手 web 端开发的人/agent 看。
> 定位：**先读这一份就能动手改代码**，不必重读 400KB 前端源码。
> 细节真源仍在：`.workbuddy/memory/MEMORY.md`（铁律）、`README.md`（App 端与工具链）、
> `tools/productlib/frontend/README.md`（Vue 工程）。

---

## 0. 一句话现状

仓库里同时活着**两套 web 前端**，共用同一套 `/api/*` 与同一个 SQLite：

| 入口 | 代码 | 状态 |
|---|---|---|
| `http://127.0.0.1:8765/` | `tools/productlib/web/`（`index.html` + `static/js/*.js`，原生 ES module，18 个文件） | **线上仍是它**，功能最全，界面老 |
| `http://127.0.0.1:8765/app/` | `tools/productlib/frontend/`（Vue 3 + Vite + Element Plus）→ 构建到 `web-app-dist/` | **改造分支主体**，九页已全迁完，细节仍在追平旧版 |

当前分支 **`vue3-frontend`**（`main` 未合并）。tag 规则：App 端 `v0.x`，productlib `pl-v0.x`。

**改 web 端 = 改 `frontend/src/**` 然后 `npm run build`**；除非明确要修旧版。
两套都要动的功能（如"抽屉大图空白"那种 CSS bug）记得**两边各改一处**。

---

## 1. 现在就能用的地址与进程

| 端口 | 是什么 | 备注 |
|---|---|---|
| 8765 | **源码开发实例**，`mode=dev`，数据 `D:\G-TickPicture\productlib\data` | 改 `.py` 要重启；改 Vue 要重新 build |
| 8766 | 冻结（PyInstaller）验证包，**0.18.0**，数据在 `D:\集刻产品库_验证测试版\` | 不是最新代码，别拿它验新功能 |
| 5175 | `npm run dev` 的 Vite（**通常没起**） | 起了就能热更新，`/api` 等代理到 8765 |

启动源码服务：

```powershell
cd D:\G-TickPicture
python -m tools.productlib.server --port 8765 --no-browser
# 或换数据目录：--data D:\某目录   或 $env:PL_HOME='D:\某目录'
```

`/api/ping` 是身份核验端点（版本 + 数据目录 + `mode`）。**端口被占时 server 会自动 +1 换端口**，
所以判断"页面坏了"之前先 `ping` 一下看的到底是不是产品库。

> ⚠️ **8765 这个 dev 服务会自己挂掉**（实测过 `10061` 连接被拒）。
> `cdp_*` 脚本突然全红时，**先 `ping` 服务，再怀疑代码**。
> 另：`cdp_old_wizard.py` / `cdp_vue_wiz_paging.py` 必须先清 `http_proxy`，否则 502。

### 本机工具链

| 项 | 实际值 | 备注 |
|---|---|---|
| Python | `3.13.5` @ `C:\Python313` | **无 venv、全仓库无 `requirements.txt` / `pyproject.toml`**，依赖装全局。事实依赖清单 = `build_portable.py` 的 `REQUIRED`（fastapi/uvicorn/PIL/docx/openpyxl/xlrd/numpy/lxml/cv2/onnxruntime/PyInstaller） |
| Node / npm | `v24.3.0` / `11.4.2` | `frontend/node_modules` 已装（`.bin/vite` 在） |
| 另一个 Python | `C:\Users\Bone\.workbuddy\binaries\python\versions\3.13.12` | `build_portable.py` 优先用它 |
| Flutter | `D:\dev\flutter` | 只影响 App 端；agent 跑 `flutter` 必须包 `tools\run_unsandboxed.ps1` |

---

## 2. 三层代码地图

```
tools/productlib/
├─ server.py        只做装配：FastAPI 实例、/static 挂载、include_router、CLI、端口探测、启动即自动升级
├─ deps.py          Web 共享依赖：路径常量、每请求 sqlite 连接、多任务治理注册表、_photo_out 输出结构
├─ routes/          15 个业务域路由（pages stats containers progress products photos govern
│                   review discover merge report standard settings app）
├─ store.py         ★ 288KB 数据层，唯一写库入口（含 link() 这个"关联唯一写入口"）
├─ pipeline.py      治理管道（分类 → 分路 → 融合 → 关联）
├─ schema.py        建表 DDL + 字段规范 + 分类/部类枚举 + 数量解析
├─ vision.py        多模态 provider（可插拔；无 key 自动降级）
├─ report_gen.py    装柜报告 .docx 生成（python-docx，A4，每页 6 图）
├─ paths.py         路径唯一真源（冻结/开发两种模式、PL_HOME/PL_DB）
├─ upgrade.py       启动前自动迁移（只 ADD COLUMN/建表建索引，不改旧数据）
├─ cli.py / selftest.py
├─ web/             ★ 旧前端（现场在跑的那个）
├─ frontend/        ★ 新前端源码（Vue 3）
├─ web-app-dist/    新前端构建产物（**入库**，现场/打包不需要 Node）
├─ checks/          65 个常驻校验脚本（静态核对 + CDP 浏览器实跑）
└─ tests/           33 个测试/实验脚本
```

依赖方向单向：`server → routes → deps → {store, pipeline, schema, paths}`。
`paths/schema/store/pipeline/vision/upgrade/cli/deps` **必须能在没有 FastAPI 时 import**
（cli、selftest 也要用），写新模块别破坏这条。

### 数据层 12 张表（`schema.py`）

`products`（编码主档，`code_norm` 是主键）· `containers`（柜）· `batches`（清单/照片批次，挂柜）·
`photos`（照片，字段最多）· `ocr_tokens` · `links`（**编码↔照片关联，唯一写入口是 `store.link()`**）·
`runs` · `discover_ignore` · `cand_reject` · `product_batch` · `standard_images` · `checklist_rows`。

连接参数（`store.connect()`）：`timeout=30`、`Row` factory、WAL、`busy_timeout=30000`、
`synchronous=NORMAL`，并注册 SQL 函数 `pl_time_trusted`（时间可信度，与 `time_trustworthy` 同源）。
**没有版本号表** —— `needs_migration()` 靠结构探测（缺表/列/索引），所以迁移必须幂等。

---

## 3. 新前端（Vue 3）结构

```
frontend/src/
├─ main.js        挂 ElementPlus(zh-cn) + 全量图标 + router
├─ App.vue        外壳：el-aside(216/56px) + el-main>.app-scroll>router-view（无全局顶栏）
├─ router.js      createWebHistory('/app/')，/ → /containers，* → /containers
├─ api.js         ★ 唯一 fetch 封装（api/post/patch/put/del/upload），错误统一 ElMessage
├─ styles.css     ★ 设计系统：旧色板 --pl-* 重映射到 Element Plus 变量，全站唯一真源
├─ lib/
│   ├─ core.js        纯函数：KIND_LABELS/SUPTAGS/格式化（**文案与旧版逐字一致**）
│   ├─ photosStore.js anchor(柜锚点) + bus(事件总线) + filters/sel 单例 + opts
│   ├─ productsStore.js 产品列表状态（筛选/页码/选中）
│   ├─ wizardStore.js  柜作业五步状态（全部派生自后端 progress）
│   └─ checklist.js    清单行读取/保存（两个写落点分开）
├─ views/         9 个页面
└─ components/    17 个组件（含 wizard/ 五个 Step）
```

### 页面 ↔ 路由

| 路由 | 组件 | 干什么 |
|---|---|---|
| `/containers` | Containers.vue | 柜列表 + **同页第二视图「柜作业」** |
| `/photos` | Photos.vue | 照片库：紧凑/详情/分组/关联四视图 + 同页「批次」二视图 |
| `/products` | Products.vue | 产品库表 + 右滑抽屉（照片/候选/标准图/补关联） |
| `/review` | Review.vue | 新产品确认（候选卡、批量入库、两种忽略） |
| `/report` | Report.vue | 报告档案（已生成 docx 的下载/删除） |
| `/settings` | Settings.vue | 多模态、落盘目录、字段规范、分类字典、已跳过照片 |
| `/home` | Home.vue | 概览（品牌区点进，不占一级菜单） |
| `/wizard` | Wizard.vue | 柜作业五步壳（①建柜 ②清单 ③照片 ④选图 ⑤报告） |
| `/batches` | Batches.vue | 照片批次（薄壳 + BatchTable） |

一级菜单只有 5 项（柜/产品库/照片库/报告档案/设置），另有三项「常用入口」：
照片批次、新产品确认、柜作业（直接进）。**别往一级菜单加东西**，先问。

### 复用组件矩阵（改一处要想到这些调用点）

- `PhotoCard` ← Photos、StepPhotos、ProductDrawer
- `PhotoDrawer` ← Photos、StepPhotos、StepPicks
- `PhotoTree` ← Photos、StepPhotos（`:f` 传自己的 filters 实例）
- `PhotoViewer` ← Review、StepPicks、PhotoDrawer、ProductDrawer、ContainerDetailDrawer
- `BatchTable` ← Photos、Batches；`ImportPhotosDialog` ← Photos、Wizard
- `ImportChecklistDialog` ← Products、Wizard；`ContainerDetailDrawer` ← Containers
- `ProductDrawer` ← Products；`GovPanel` ← StepPhotos（抽屉内）

### Element Plus 使用约定

- 页面壳：`el-card shadow="never"` + `#header .phead`（h2 + `.sub` 说明 + `.spacer` + 右侧动作）
- 筛选：`.toolbar` 一行控件 + chips 行（`el-tag closable` + 「全清」）
- 表格：`el-table size="small"`；抽屉：`el-drawer :with-header="false"` 自绘头部
- 确认一律 `ElMessageBox.confirm`，结果提示 `ElMessage`，加载 `v-loading`
- 分页：`el-pagination small background`；分段：`el-radio-group size=small`
- 目录选择用自建 `DirPicker`（后端 `/api/browse`），不要 `input type=file`

---

## 4. 设计系统（改样式前必读）

`styles.css` 把旧版色板**原样搬成 `--pl-*`，再整体重映射到 `--el-*`**：

```css
--pl-bg #f4f6f9   --pl-panel #fff   --pl-line #e6e9ee
--pl-text #1f2733 --pl-muted #647084 --pl-faint #95a0b1
--pl-brand #2563eb --pl-brand-ink #1d4ed8 --pl-brand-soft #eaf1ff
--pl-radius 10px  --pl-radius-sm 7px
--k-label/product/packaging/packing_list/scene/unknown（六分类色，+soft）
--el-component-size: 32px     /* 控件高度锁死，small 也给 32 */
```

**为什么不用 EP 默认主题**：旧版是"暖灰底 + 微阴影 + 10px 圆角 + 克制品牌蓝"。
只换组件不换色板，现场一眼就觉得是另一个系统。所以**只覆写变量，不逐页写样式**。

已知坑（都踩过）：
- 控件高度不统一 → 一条工具条上四种高度 = "控件没对齐"。锁 32px。
- 滚动容器只能放在 `.app-scroll`，不能放 `.app-main`。
- 向导页 `el-card` / `.el-card__body` 必须 `overflow: visible`，否则 sticky 失效。
- **flex 容器包 img 会裂开**：容器高度取 img"未限高"的 hypothetical size → 图下空一大段。
  wrap 用 `display:block; line-height:0` + img `margin:0 auto`，别用 flex 猜高度。
- 折叠侧栏要把 `li` 与 trigger 四边 padding 全清掉。

---

## 5. 数据口径铁律（违反会静默出错数据）

这些不是风格问题，是正确性。改任何查询/计数/文案前先对一遍。

1. **关联只能经 `store.link()` 写**。Web 层不得直接 `INSERT links`；
   App 侧同理只有 `AssignService` 能写 `itemId`。
2. **数字同源**：列表、徽章、树、角标、stats 必须共用同一份 WHERE
   （`photo_where_sql` / `_UNLINKED_SQL` / `_container_filter_sql` / `_cand_filter_sql`）。
   前端同理：**徽章与列表用同一份 filters**，不许各自算。
3. **facet 计数必须排除自身维度**（2026-10-19 事故）：数用途时只带 kind，数分类时只带 usage。
   否则"选了一个之后其他项全消失"→ 表现为多选框只能选一个。
4. **待关联口径**：只有 `label`/`product` 两类进待关联（真源 `schema.LINKABLE_KINDS`），
   再叠加 `usage<>'监装'` 与 `photo_ignored=0`。**UI 文案是「待关联」不是「未关联」**。
5. **自动关联只认 exact（逐字符相等）**。prefix/edit1/edit2 一律进人工工作台 ——
   错关联比没关联危险得多。
6. **AI 监装细分永不静默生效**：只写 `sup_tag_ai*`，报告只认人工 `supervision_tag`。
7. **绝不自动填 PASS**；数量解析失败返回 `None`，不得当 0。
8. **柜作业时长绝不能取全柜 MIN/MAX(taken_at)**：按 `(batch_id, group_idx)` 作业段算，
   净时长取段区间**并集**（相加会超过全程）；零散判据只看"单段>12h"。
9. **时间可信度**：`time_src='filename'` 对 App 采集是可信的（快门时刻），
   对微信命名/mtime 才放宽。判断显示秒差必须走 `time_trustworthy()` / `pl_time_trusted`。
10. **柜号解析**：`container_id → containers.container_no` 权威，`batches.container_no` 老库兜底，
    两路命中取 max **不相加**。
11. **`group_idx` 只在 batch 内有效**，查询必须同时限定 `batch_id`。
12. **导入必须带 `container_id`**；柜号只认界面选的柜，**目录名不建柜**。
13. **路由顺序**：字面量端点必须排在 `{pid}`/`{cid}` 之前（FastAPI 按注册顺序匹配）。
    新端点还要登记到 `checks/routes.py`。
14. **重活端点必须是同步 `def`**（FastAPI 会丢线程池），不要 `async` 里阻塞。
15. **迁移幂等**：`ADD COLUMN` 先探测；禁止重跑裸 `ALTER`。
16. **缓存 key 禁用内置 `hash()`**（进程随机），用 `hashlib`。
17. **路径**：照片 `path` 是"相对导入根"形态，判断文件是否存在必须走
    `store.resolve_photo_path(con, pid, path)`，裸 `os.path.exists` 会把 249 张全判缺失。

---

## 6. 验证体系（改完必须跑）

```powershell
cd D:\G-TickPicture

# ── A. 静态核对（秒级，不需要起服务）────────────────────────
python -m tools.productlib.checks.routes        # 后端路由集合完整、能 import（实测 PASS）
python -m tools.productlib.checks.esm_syntax    # 旧版 ES module 语法（19/19）
python -m tools.productlib.checks.web_contract  # 前端 id ↔ API 端点 ↔ node --check 三维核对
python -m tools.productlib.checks.esm_graph     # 导入导出/循环依赖（**有既有噪音**）

# ── B. 单元测试（不是 pytest！是一堆裸 assert 脚本）──────────
python -m tools.productlib.tests.units          # 失败 = AssertionError + 非 0 退出
#   其余：tests\<name>.py 直接 python -m tools.productlib.tests.<name>
```

> `esm_graph` 的"未定义标识符/循环依赖"报错是**既有噪音**（`isFinite`、`onPick`、
> `requestIdleCallback` 等），以 `git stash` 前后对照为准，别当成自己改坏了。
>
> `tests/` **不是 pytest 用例**：没有 `test_` 函数、没有 `__main__`，就是顶层 `assert` + print 的脚本，
> 全局装了 pytest 也收集不到 0 个用例。跑法见上。
>
> ⚠️ `esm_syntax` / `web_contract` / 部分 `tests` 会往 `tempfile.mkdtemp()` 目录里拷文件。
> 在**受限沙箱**里新建目录拿不到写权限 → 必报 `PermissionError`（不是脚本坏了）。
> 这两条要在**普通终端**或用完全权限跑。

```powershell
# ── C. CDP 浏览器实跑（最像人眼的验证）──────────────────────
# 会自己起 headless Edge（--headless=new --remote-debugging-port=93xx）
# 环境变量：PL_PORT（目标端口，默认 8765）、PL_CDP（调试端口，默认 9337）
python -m tools.productlib.checks.cdp_regress            # 全量回归 —— 不自起服务！
python -m tools.productlib.checks.cdp_vue_containers     # 新前端逐页断言（Vue 版一整套）
python -m tools.productlib.checks.cdp_paging             # 页码分页
python -m tools.productlib.checks.cdp_old_wizard         # 旧版柜作业③（15 张/页）
python -m tools.productlib.checks.cdp_vue_portable       # 打包版上的 /app/ 冒烟
```

CDP 坑（踩过很多次）：`Page.reload` 默认**不清 ES module 缓存** → 用随机端口 +
`ignoreCache` + `Network.setCacheDisabled`；`/json/list` 第一个 page 可能不是目标页，
必须按 URL 挑；模块作用域里的函数不挂 `window`，`Runtime.evaluate` 调它会静默
`ReferenceError` → **改点 UI 按钮，别直接调函数**；Edge 要带 `--no-proxy-server`。

```powershell
# ── D. 端到端自检（独立测试库，25 条断言）────────────────────
python -m tools.productlib.selftest --limit 20    # 默认
python -m tools.productlib.selftest --full
```

`selftest` 用 `productlib\data\selftest.db`，**每次先删除重建**（会写仓库目录），依赖 `doc\PIDU9352234`。
已知：`--full` 有 3 项因**素材不配套**失败（S2c 已修，剩 S5a/S10a 与素材相关），非代码坏了；
且 `S5b/S5c/S5d` 在 0 条记录时是**空断言**，当前没有保护力。

```powershell
# ── E. 新前端构建 + 冒烟 ──────────────────────────────────
cd tools\productlib\frontend
npm run build          # 产物 → ../web-app-dist/（约 20~25s）
cd ..\..\..
python -m tools.productlib.checks.cdp_vue_portable   # 打包版上的 /app/ 冒烟
```

**构建产物必须一起提交**（`web-app-dist/` 入库），否则现场/打包版拿到的还是旧前端。
打包时 `productlib.spec` 对 `web-app-dist` 是**条件收录**（目录不存在就静默跳过）→
**`/app/` 会整站 404 而打包照样成功**。打绿色包之前先 `npm run build`。

---

## 7. 发版（productlib）

```powershell
# 1. 改版本号（唯一真源）
#    tools/productlib/server.py:59  APP_VERSION = '0.18.1'
# 2. 打包绿色包
python tools\productlib\build_portable.py --clean      # → dist\<时间戳>\集刻产品库\
# 3. 改 checks\pkg_verify.py 第 22 行的 EXE 路径指向新包，然后实测打包版
python -m tools.productlib.checks.pkg_verify
# 4. 提交 + 打 tag（productlib 无远端，轻量 tag 本地打即可）
git commit -m "feat(productlib): 发版 pl-v0.18.2（0.18.1 -> 0.18.2）"
git tag pl-v0.18.2
```

- **`pkg_verify.py` 硬编码 exe 路径，每次发版必须改**，否则测的是上一次的包。
- **源码测试全绿 ≠ 打包版能跑**（裸连接 `row_factory` 事故）→ 现场发版必须实测打包版。
- `git add tools/productlib` 这种**宽目录会把几百个调试垃圾扫进暂存区**
  （`frontend/_*.py`、`det_crop_grid_*.png`、`frontend_85_*.txt`）。
  **提交前必须 `git diff --cached --name-only` 核对**，用显式文件清单。
- 提交信息：`<type>(<scope>): <一句话>`，正文回答**为什么**（不是改了什么）。

---

## 8. 当前在飞、还没提交的改动

`git status` 显示这批工作是**未提交**的（2026-10-20 晚 ~ 10-21 00:18），跑之前先看清。
tag 还停在 `v0.24.9` / `pl-v0.18.1`，这批改动一条都没提交。

| 文件 | 内容 |
|---|---|
| `frontend/src/views/Photos.vue` | 需求 9：**「加载更多」改页码分页** + 按视口量算每页条数 + 末页越界保护 |
| `frontend/src/components/wizard/StepPhotos.vue` | 同上（③照片），治理面板改成右侧 `el-drawer` |
| `frontend/src/views/Wizard.vue` | 步骤操作钮并进标题行（照片治理 / ＋导入照片） |
| `frontend/src/views/Containers.vue` | 柜列表加**序号列** |
| `web/*`（旧版） | 同一批需求的旧版实现：`photos.js`/`wizard.js`/`app.css`/`index.html` |
| `store.py` | 修「选图里同一张图出现两次」：`_dedup_same_shot()` 在 `report_lookup` 最外层去重 |
| `web-app-dist/*` | 00:17 重新构建的产物（与源码同步） |

### 上一轮的结论（别重复踩）

- **步骤条折叠功能已被老板否掉并撤销**（旧版 `#wizFold` + 面包屑、新版同款全部删掉），
  别再"优化"回去。旧版③的步骤说明 `.whint` 与「查看资产 → 照片库」链接也被要求删掉。
- 旧版③已按老板效果图改成 **5 列 × 3 行 = 15 张/页**、卡片 197×120、**文件名叠在图片底部**、
  `docSh 900` 不纵滚。
- 🔴 卡片高度一变，分页容量就跟着变：`st.size` 只在首次算定不重算，
  所以加了"首屏校准"（渲染后按稳定布局再量，更多就重取，最多 2 次）；`reserve` 统一 **120**。
- 🔴 **文件名做成独立一行会让卡片撑到 201 高 → ③的照片直接渲染不出来（n=0，稳定复现）**，
  必须做成**叠底**（`position:absolute;bottom:0`）不占高度。

### 明确的下一步（上一轮留下的）

> **新版 Vue 的卡片尺寸与每页张数还没按效果图调**（旧版已调完）——
> `StepPhotos.vue` / `Photos.vue` 目前仍按原来的卡片比例和视口算法，
> 还没对齐「5×3=15、方卡、文件名叠底」。这是最直接的待办。

另外两条旧账：
- 柜作业③ 旧版整页仍超高 53px（15 张比原来多两行撑的），②清单已不滚。
- 需求 9 里新前端柜作业②的视口分页还没做。

---

## 9. 已确认的问题（实测/读码复核，尚未修）

四条都在 2026-10-21 早上**对着当前源码重新复核过**（上一轮 00:17 的改动没动到这些地方）。

| # | 位置 | 问题 | 证据 |
|---|---|---|---|
| 1 | `frontend/src/components/PhotoDrawer.vue:539` | **新前端「解除关联」必然失败**。`del('/api/links', {code, photo_id})` 的第二个参数被 `api.js:41` 的 `del(path)` 丢掉 → 后端 `DELETE /api/links` 要 JSON body → **422**。旧版 `core.js:37` 的 `del(p,b)` 是带 body 的，所以这是迁移引入的回归 | 实测：无 body → `HTTP 422`；带 body → `200 {"ok":true,"removed":0}`。修法二选一：给 `api.js` 的 `del` 加 payload 参数，或改走 query/单独端点 |
| 2 | `frontend/src/components/wizard/StepPicks.vue:136` | 传给 `PhotoViewer` 的 prop 名是 `:taken`，组件只声明 `takenAt` → **选图页大图不显示拍摄时间** | `PhotoViewer.vue:44` prop 清单 |
| 3 | `frontend/src/components/wizard/StepPhotos.vue:350` | 残留调试代码 `window.__gp` 在累积 | 代码扫描 |
| 4 | `frontend/src/views/Products.vue:267` | `bus.on('products:changed')` **没有退订**（其他页都取了 unsubscribe 并在 `onBeforeUnmount` 调用） | 与 `Photos.vue:706-712` 的写法对照 |
| 5 | `frontend/src/views/Wizard.vue:226-228` | 注释还写着"本轮只迁①②⑤，③④给旧版" —— **已过期**，③④都已实现。别被它误导 |  |

另有一条**不是 bug 但会误导人**：`Photos.vue:522` 的 `if (reset)` 分支不再重置 `page`
（分页改造后语义变了），注释和参数名都还叫 reset。

---

## 10. 开工前的排雷清单

- [ ] 我在改旧版还是新版？**新版只动 `frontend/src/`，改完必须 `npm run build`**
- [ ] 我改的这条 WHERE / 这个计数，是不是还有徽章、树、角标、stats 在用？（数字同源）
- [ ] 我是不是在 UI 里自己算了一遍统计？（不许，一律取后端）
- [ ] 我有没有绕开 `store.link()` 写 `links`？
- [ ] 我改的文案是不是全站唯一真源？（`core.js` 的 `KIND_LABELS`/`SUPTAGS` 两端各一份，后端 `schema` 也要同步）
- [ ] 新端点排在 `{pid}`/`{cid}` 前面了吗？登记到 `checks/routes.py` 了吗？
- [ ] 这段重活是 `async def` 吗？（应改同步 `def`）
- [ ] 我加/改了 `.ps1` 吗？→ 跑 `tools\fix_ps1_bom.ps1`（必须 UTF-8 with BOM）
- [ ] 我跑 `flutter` 命令了吗？→ 必须包 `tools\run_unsandboxed.ps1`
- [ ] 提交前 `git diff --cached --name-only` 核对过了吗？
