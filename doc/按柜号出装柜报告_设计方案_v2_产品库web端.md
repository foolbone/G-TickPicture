# 按柜号输出装柜报告 —— 设计方案 v2（产品库 Web 端实现）

> ⚠️ **本文档已作废（2026-10-05 17:28）**：老板追加「柜号是唯一主线，
> 必须先确定柜号才能进入后续流程」+「照片尺寸/排版方向的处理时机要明确」，
> 新方案见 `doc/产品库柜号主线与装柜报告_设计方案_v3.md`。
> 本文的 8 区块数据源映射、checklist_rows 行快照设计仍被 v3 继承。

> **架构拍板（2026-10-05 老板）**：App 只做照片采集（**零改动**）、
> 产品库做图片与产品治理、**报告生成在产品库 Web 端**。
> 本文取代 v1（`按柜号出装柜报告_设计方案_v0.17.0.md`，App 端方案作废）。
>
> 样例报告：`SZAE-LOADING REPORT-CNTR#EMCU9914616-Sep-27-2026.docx`
> （42MB / 137 页 / 438 图 / WPS 制作，8 区块结构见 v1 附录，本文直接引用）。

---

## 一、架构与数据流

```
┌──────────┐   交付包 ZIP      ┌────────────────────────────────┐
│ 集刻-采集 │ ─────────────────▶│  产品库 productlib（Web 端）    │
│  App     │  预检/{箱号}/     │                                │
│ (零改动) │  监装/            │  ① 照片导入（已有）+ 柜号      │
└──────────┘                   │  ② 治理/关联/治理（已有）      │
                               │  ③ 清单导入（已有）+ 柜号      │
      客户清单 xlsx ──────────▶│  ④ 【新增】装柜报告生成        │
      （文件名=柜号）           │     python-docx → .docx 下载   │
                               └────────────────────────────────┘
```

**为什么这个架构成立 —— 产品库的柜号链路已经通了**（本次盘点确认）：

| 能力 | 现状 | 位置 |
|---|---|---|
| 批次挂柜号 | ✅ `batches.container_no`，清单/照片批次共用 | schema.py |
| 照片导入指定柜号 | ✅ 导入 API 已收 `container_no` | routes/photos.py |
| 清单导入指定柜号 | ✅ 同上 | routes/products.py |
| 按柜号筛检索范围 | ✅ 报告素材页按批次勾选（柜号显示在批次名前） | report.js |
| 产品↔照片关联 | ✅ `links`（自动 + 人工，`store.link()` 唯一写入口） | store.py |
| 产品↔批次多对多 | ✅ `product_batch` | schema.py |
| 照片用途（监装/预检） | ✅ `photos.photo_usage` + 批量/单张标注 API | routes/photos.py |
| 报告素材导出 | ✅ `/api/report/export`（编码→压缩→落盘素材包） | routes/report.py |
| docx 生成库 | ✅ **python-docx 1.2.0 两个运行时都已装** | — |

样例报告与真实清单的对应关系（v1 已论证，结论不变）：
报告 Packing list 表头 = 清单 xlsx 的 A1:F1 一字不差（6/6 文件验证）；
清单文件名就是柜号（5/6 命中）→ **柜号在导入清单那一步就有了**。

---

## 二、差距（全部在产品库侧，共 5 条）

| # | 缺口 | 现状 | 报告要什么 |
|---|---|---|---|
| W1 | **清单行快照没落库** | `import_checklist_file` 只把**合并后**的 products 入库（code_norm 唯一），`parse_checklist` 解析出的**原行 items 直接丢掉** | 区块⑤按清单**原行**出（样例 `216070000001` 连着 3 行 = 3 件） |
| W2 | **Order/Loading Qty 与 Check 列没解析** | `parse_checklist` 只认 code/name/spec/qty/container 五列（qty 只取第一个命中列） | 清单有 `Order Qty` `Loading Qty` `Quantity Check result` 三列，报告全都要 |
| W3 | **柜级元数据缺失** | `batches` 只有 container_no/name/note | 封条号、到柜/离柜时间、Inspector、Inspection Location、柜况 4 图（区块④） |
| W4 | **监装照片无细分类** | `photo_usage` 只有 监装/预检 二值 | 区块④ 要 空柜/柜侧/封条/锁门；区块⑦ 要 卡车头/装柜过程/柜外观 各带固定英文图注 |
| W5 | **docx 报告生成器为零** | `/api/report/export` 只出"素材包"（按编码导照片） | 8 区块完整 docx，文件名 `SZAE-LOADING REPORT-CNTR#<柜号>-<日期>.docx` |

附带小缺口：App 交付包的箱号在路径 `预检/{箱号}/` 里，`add_photos` 目前只认 `carton_map`
人工映射，**没有从路径自动提取** → 区块⑥图注 `{编码}-{描述}-{箱号}` 会缺第三段（W1.5，顺手修）。

---

## 三、数据模型改造（全部走 `_migrate` 增量迁移）

### 3.1 新表 `checklist_rows`（W1+W2，核心）

```sql
CREATE TABLE IF NOT EXISTS checklist_rows (
    batch_id     TEXT NOT NULL,          -- 清单批次（batches.id, kind='checklist'）
    seq          INTEGER NOT NULL,       -- 清单内行序（1 起，含同码多行）
    code         TEXT NOT NULL,          -- 原始编码（照抄清单）
    code_norm    TEXT NOT NULL,          -- 归一化（与 products/links 同一口径）
    name         TEXT,                   -- DESCRIPTION
    spec         TEXT,
    package_no   TEXT,                   -- Package Number（箱号，向下填充后的值）
    order_qty    TEXT,                   -- Order Qty（保持文本原样，报告照抄）
    loading_qty  TEXT,                   -- Loading Qty
    check_import TEXT,                   -- 清单里预填的 Quantity Check result（客户值，照抄）
    check_result TEXT,                   -- 核对结论（人工改后覆盖；NULL=沿用 check_import）
    taken_at     TEXT,                   -- 该行被人工核对的时间（留痕）
    taken_by     TEXT,
    PRIMARY KEY (batch_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_clrows_norm ON checklist_rows(code_norm);
```

- `parse_checklist` 扩展：`QTY_HEADER_HINTS` 拆成 `order_qty` / `loading_qty` 两套 hints
  （`orderqty`/`loadingqty` 精确词优先，旧的通用 `qty` 只兜底到 order_qty），
  新增 `check_result` hints（`quantitycheck`/`checkresult`）。
- **数量列存文本不存数字**：清单里 `12`、`12.0`、`"12 PCS"` 都有，照抄最忠实，
  TOTAL 行在生成报告时求和（解析失败的行为按 0 且在报告页黄色提示）。
- `check_result` 语义（铁律 17「还没查完 ≠ 没问题」）：
  清单预填的 PASS 是**客户的值**，照抄不算我们下结论；
  人工核对后写 `check_result`（PASS/FAIL/NOT FOUND）覆盖之；两列都空 → 报告该格留空。
- 重复导入同一柜的清单 → **整批替换**该 batch 的 checklist_rows（清单是权威快照，
  与 `upsert_products(replace=...)` 的既有语义对齐）。

### 3.2 `batches` 加列（W3，柜级元数据）

```sql
ALTER TABLE batches ADD COLUMN seal_no TEXT;            -- 封条号
ALTER TABLE batches ADD COLUMN arrival_at TEXT;         -- 到柜时间
ALTER TABLE batches ADD COLUMN departure_at TEXT;       -- 离柜时间
ALTER TABLE batches ADD COLUMN inspector TEXT;          -- Inspector（默认读 settings）
ALTER TABLE batches ADD COLUMN location TEXT;           -- Inspection Location
ALTER TABLE batches ADD COLUMN report_remark TEXT;      -- REMARKS（区块③）
```

只加在 `kind='photos'` **或** `kind='checklist'` 的批次上都行——
**柜 = 清单批次与照片批次通过 container_no 对齐**（现状已有），
编辑入口统一按"柜"聚合（见 4.1）。柜况 4 图**不存 batches**，见 3.3。

### 3.3 `photos` 加列（W4，监装细分类）

```sql
ALTER TABLE photos ADD COLUMN supervision_tag TEXT;
-- empty_container / container_side / container_seal /
-- container_lock / truck_head / loading_process / other
-- 仅 photo_usage='监装' 时有意义；NULL = 未细分
CREATE INDEX IF NOT EXISTS idx_photos_suptag ON photos(supervision_tag);
```

柜况 4 图（区块④）的取图规则：**tag 定候选 + 每类一张代表图**——
`empty_container/container_side/container_seal/container_lock` 各自的 tag 里
取**最新一张**为默认代表，柜信息编辑页里可换成同 tag 的其他张。
不建"槽位表"：tag 已经表达了"这张照片是什么"，再加一张槽位表只会造出
两个真相源（同一张图既是 seal 又被槽位引用，改一处漏一处）。

### 3.4 导入增强（W1.5，箱号路径提取）

`add_photos`：当照片路径含 `/预检/<目录>/` 段时，自动把 `<目录>` 写进 `carton_no`
（与现有 `carton_map` 参数取并集，人工映射优先）。App 交付包不用改一个字节。

---

## 四、交互设计

### 4.1 柜信息编辑（新页面区块，挂在批次页）

批次页新增「**柜信息**」卡片：按 container_no 聚合显示清单批次 + 照片批次，
点开一个柜 → 编辑封条号 / 到离柜时间 / Inspector / Location / REMARKS +
四张柜况代表图（下拉选该柜下打了对应 tag 的监装照片）。

```
柜 EMCU9914616
  清单批次：MIEU2012616.xlsx（93 行）   照片批次：3 个（共 812 张）
  封条号 [EMCEXE7565]  到柜 [09-16 08:49]  离柜 [09-16 11:27]
  Inspector [Jerry Xu]  Location [Changsha City, Hunan Province, China]
  空柜图 [缩略图 ▾]  柜侧 [▾]  封条 [▾]  锁门 [▾]
```

### 4.2 监装照片打标签（照片页，监装筛选下）

现有 `photo_usage=监装` 的照片网格里，每张加 7 选 1 的标签 chip
（空柜/柜侧/封条/锁门/卡车头/装柜过程/其他），支持多选批量打
（监装照是连拍流，逐张点会点到手断）。默认 `other`。

### 4.3 报告生成（报告页新增「装柜报告」区块，与现有"素材检索"并列）

```
生成装柜报告
  柜号 [EMCU9914616 ▾]（下拉 = 有清单批次的所有柜）
  抬头模板 [SZAE ▾]（JSON 可配：Supplier/联系人/Email/Website/Add）
  照片画质 [1600px / q85 ▾]（复用素材导出的压缩链路）
  ☑ Quantity check 倒序（对齐样例：最后装的先验）   ← 可关
  [预检清单（93 行 · 4 行无照片 · 12 行未核对）]     ← 可展开核对 Loading Qty / 结论
  [ 生成报告 ]
  → 产出：LOADING REPORT-CNTR#EMCU9914616-<日期>.docx（约 XX MB）→ 下载
```

生成前**告知不拦截**（沿用 App 交付"不设检查"的拍板）：
柜况图缺几张、多少行未核对、体积预估——都是黄条提示，点生成照样出。

---

## 五、docx 生成器设计（P3 核心）

### 5.1 技术选型

**python-docx 1.2.0（已装）**。不再手写 OOXML：PC 端内存无压力
（lxml 树 + 图片 blob 常驻 ≈ 200–400MB，生成 42MB 文档在老板电脑上毫无压力；
App 端方案里"流式落盘"的约束在 PC 上不存在）。
表格样式 / 页眉页脚 / 图片尺寸 / 字体都是现成 API。

### 5.2 模块与文件布局

```
tools/productlib/
├── report_gen.py          # 【新增】纯生成器：输入数据字典 → 输出 .docx
│                          #   不碰 db、不碰 HTTP —— 单测直接喂 dict 断言
├── routes/report.py       # 【扩展】POST /api/report/loading-docx
│                          #   组数据（store 查询）→ 调 report_gen → 落盘 → 返回路径
├── store.py               # 【扩展】loading_report_data(con, container_no)
│                          #   一次查全 8 区块所需数据（行快照/柜元数据/照片清单）
└── web/static/js/report.js# 【扩展】装柜报告区块 UI
```

### 5.3 区块 → 数据源映射（实现时的唯一真相）

| 报告区块 | 数据来源 | 口径 |
|---|---|---|
| ① 抬头 | `data/report_templates/<name>.json` | 供应商固定文案，默认内置 SZAE |
| ② 项目信息 | 柜信息（Inspector/Location）+ 报告生成日 | Product/Client 从清单批次名/备注取，可编辑 |
| ③ 柜汇总 | 本柜 `checklist_rows` 汇总 | 单柜文件只一行；多柜时全部列出 |
| ④ General Information | batches 柜元数据 + 4 个 tag 代表图 | 缺图 → 格子写 `Not provided`（**不阻断**） |
| ⑤ Packing list | `checklist_rows` 按 seq 排 | **原行不合并**；TOTAL 行求和；check 取 `check_result ?? check_import` |
| ⑥ Quantity check | 该柜照片批次内 `photo_usage='预检'` 且 `links` 到本柜清单编码的照片 | 图注 `{code}-{name}-{carton_no}`；两列网格；**倒序**（可参数）；无箱号 → 只写前两段 |
| ⑦ Truck picture | `photo_usage='监装'` 且 tag ∈ {truck_head, loading_process, other} | 按 taken_at 升序；图注 = tag 的固定英文文案（Truck head / Loading container view / …） |
| ⑧ 结尾 | 常量 | — |

**⑥与⑤的行数天然不等**（样例：1005 行清单 vs 398 张核对照）——
⑥是"有照片的件"，不是"全部件"，与样例行为一致，不造数补齐。

### 5.4 图片处理

复用 `/api/report/export` 已有的压缩链路（`long_edge` 参数，PIL）：
预检/监装照片按 1600px 重采样后嵌入（报告里显示尺寸 ~2.8 inch 宽，
1600px 对应 ~570 DPI，打印绰绰有余）。**原图不动，压缩产物只进 docx**。
438 张 × ~120KB ≈ 50MB 上限，可接受；后续要小再降画质档。

### 5.5 性能与进度

- 生成在**FastAPI 线程池**里跑（`def` 端点自动线程池，不堵事件循环）；
- 数据查询一次完成（`loading_report_data` 内部 `IN(...)` 批量，禁止逐行逐张查——铁律 13②）；
- 大柜（1000 行 + 400 图）预估 30–60 秒：前端显示"生成中…"，
  完成后给下载链接（产物存 `data/reports/`，同柜重复生成覆盖旧文件名加时间戳）。

---

## 六、实施路线（P0→P5，约 5.5 人日）

| 阶段 | 内容 | 交付判据 |
|---|---|---|
| **P0** 解析与建模 0.5d | `parse_checklist` 扩列（order/loading/check）+ `checklist_rows` 表 + `_migrate` 增量 + batches/photos 加列 | 老库无感升级；单测：6 列真实清单全解析 |
| **P1** 导入改造 0.5d | 清单导入落行快照（原行不合并）+ `add_photos` 路径提取箱号 | 导入 MIEU2012616.xlsx → checklist_rows 93 行；App 交付包导入后 carton_no 自动有值 |
| **P2** 柜信息与标签 1d | 柜信息编辑页 + 监装 7 类标签（单张+批量）+ 4 代表图选择 | 真实柜可编辑完整区块④元数据 |
| **P3** docx 生成器 1.5d | `report_gen.py` 8 区块 + 抬头模板 JSON + 图片压缩嵌入 + `/api/report/loading-docx` | 单测：喂固定 dict 断言各区块结构/表头/图注/TOTAL |
| **P4** 报告页 UI 1d | 装柜报告区块（选柜/选项/核对清单/生成/下载） | CDP 实跑全流程 |
| **P5** 验收 1d | 用 9.13 真实清单 + 历史图片出一份报告，与样例逐区块比对；tests + checks 双轨 | 区块/表头/图注/字体格式对齐；全量测试绿 |

**发布负担**：零 App 发版（App 不动），productlib 是内部工具随仓库走。

---

## 七、待老板拍板（3 件，其余已在方案内定了默认值）

| # | 问题 | 默认值 |
|---|---|---|
| Q1 | ⑥ Quantity check **倒序**（样例是从清单尾部往回排）是规矩还是偶然？ | 跟样例倒序，UI 留开关 |
| Q2 | 清单里预填的 `Quantity Check result`（PASS）**照抄**进报告吗？ | 照抄（那是客户清单数据）；人工核对后可覆盖 |
| Q3 | 报告抬头（Supplier 那段）只此一家还是每客户一套？ | 先做 JSON 模板 + 内置 SZAE 默认 |

---

## 八、既有纪律对照（productlib 侧）

- **store.py 唯一写入口**：checklist_rows / 柜元数据 / 标签的写入全部走 store，Web 层禁直接 INSERT（与 links 同一条纪律）。
- **数字同源**：报告页"93 行 · 4 行无照片 · 12 行未核对"与生成器吃**同一份** `loading_report_data`，不各写一份 SQL（铁律 23）。
- **CDP 验收门槛**：报告生成 UI 改动按 `checks/cdp_*.py` 模式实跑浏览器验证（铁律 24：前置闸门/干净端口 8790/`textContent`）。
- **测试双轨**：`tests/`（单测：解析、行快照、生成器数据组装）+ `checks/`（CDP 实跑）。
- **措辞**：缺口/未核对不许渲染成"PASS/无问题"（铁律 17）。
- **App 零改动**：本方案不碰 `app/` 一行；App 交付包结构（`预检/{箱号}/`、`监装/`）就是产品库的输入契约。
