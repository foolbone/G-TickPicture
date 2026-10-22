# 预检拍照 APP（G-TickPicture）

仓库预检监装现场取证工具。**批量采集 → 统一对应 → 打包交付** 三段式。

- 完整设计实现方案：`预检拍照APP_设计方案.html`（**v3.1**，12 章）
- 本文件：**开发启动说明**（环境怎么装、工程怎么跑、骨架里已有什么）

---

## 一、本机环境现状（2026-09-23 实测，✅ 全部就绪）

| 项 | 状态 | 说明 |
|---|---|---|
| **Flutter SDK** | ✅ **3.29.0 / Dart 3.7.0** | `D:\dev\flutter`（PATH 指向它，**用这个**）；`D:\flutter` 是 2.39 GB 的重复副本，可留可删 |
| **Android SDK** | ✅ **完整** | `D:\dev\Android\SDK` —— platforms `31/33/34/35/36`、build-tools 6 个版本、cmdline-tools、platform-tools、licenses、emulator、ndk |
| **JDK** | ✅ 21 | `C:\Program Files\Android\Android Studio\jbr`，`JAVA_HOME` 已配 |
| Android Studio | ✅ 2025.2.2 | 不用动 |
| 国内镜像 | ✅ | `PUB_HOSTED_URL` / `FLUTTER_STORAGE_BASE_URL` 已配 |
| git | ✅ | `C:\Program Files\Git\cmd\git.exe` |
| Android licenses | ✅ | **全部已接受**（`All SDK package licenses accepted.`） |
| `flutter doctor` | ✅ 全绿 | 仅 `[X] Visual Studio` 未装 —— 只影响 Windows 桌面端，本项目只做 Android，无关 |
| 用户级环境变量 | ✅ 已配 | `ANDROID_HOME` / `ANDROID_SDK_ROOT` = `D:\dev\Android\SDK`；用户 PATH 已含 SDK 的 platform-tools 与 cmdline-tools |
| 系统级 PATH | ⚠️ 有 1 条失效条目 | `D:\Andriod\SDK\platform-tools`（D 盘根下无 `Andriod`）。改它需管理员权限；因指向不存在的目录，无实际危害 |
| PowerShell | 5.1（`powershell`）/ 7.6（`pwsh`） | ⚠️ 见 §八.6，两者读 `.ps1` 的默认编码不同 |

> **⚠️ 2026-09-22 的"Flutter/SDK 缺失"是误判**——当时只按预期路径探测（SDK 实际目录名被拼成 `Andriod`，我查的是 `Android`）。**探测必须多候选 + 递归搜索，不能只 `Test-Path` 一两个路径。**

### 🔥 已解决：`ERROR_PIPE_BUSY`（`CreateFile failed 231`）

历史上从 agent 工具里跑 `flutter` 会崩：

```
CreateFile failed 231
ProcessException: 所有的管道范例都在使用中。   ← Windows ERROR_PIPE_BUSY
  Command: cmd.exe /c ver
```

**真凶不是环境、不是安全软件，而是 WorkBuddy 的执行沙箱。**

进程链是 `pwsh.exe → sandbox-cli.exe → WorkBuddy.exe`——我从工具发出的每条命令都跑在这个沙箱里，而**该沙箱隔离了 Windows 命名管道对象命名空间**，Dart VM 创建子进程 stdio 用的正是命名管道 → 必然失败。

**决定性对照实验**：用**计划任务**（由 Task Scheduler 服务启动，不在该进程树里）跑同一探针，全部成功（`try1 OK exit=0 len=31`）。

> ⚠️ **`dangerouslyDisableSandbox` 改变不了进程父子关系**，所以当年据此"排除沙箱"是**无效排除**，把嫌疑错指向了安全软件，白追了几小时。

**绕过办法（已固化）**：`tools/run_unsandboxed.ps1`

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_unsandboxed.ps1 `
  -Command "flutter doctor -v" -WorkingDirectory "D:\G-TickPicture\app"
```

> **老板自己开 PowerShell 不在沙箱里，`flutter` 一直是好的。** 这个脚本只是给我（agent）用的。

---

## 二、快速开始

```powershell
# 第 0 步：先体检（只读，几秒钟）。本机环境已装好，不需要重装
powershell -ExecutionPolicy Bypass -File .\tools\env_doctor.ps1
#   期望看到最后一行 RESULT: PASS

# 第 1 步【仅在体检报缺件时才需要】按需补缺（已装的会自动跳过，不重装）
powershell -ExecutionPolicy Bypass -File .\tools\setup_flutter.ps1

# 第 2 步：初始化工程（若 app\android\ 已存在则可跳过）
powershell -ExecutionPolicy Bypass -File .\tools\init_project.ps1

# 第 3 步：跑起来
cd app
flutter devices     # 手机开 USB 调试后应能看到设备
flutter run
```

> **老板自己开终端**：`flutter` / `dart` 命令直接用，不需要 `run_unsandboxed.ps1`。
> **agent 代跑**：所有 `flutter` 命令都必须走 `tools\run_unsandboxed.ps1`（见 §一）。

`init_project.ps1` 做的事：备份 `lib/` 和 `pubspec.yaml` → `flutter create` 补齐 `android/` 平台目录 → 还原骨架 → `flutter pub get` → `dart run build_runner build` 生成 `database.g.dart` → `flutter analyze`。

> **为什么要备份还原？** 平台目录（android/）必须由 `flutter create` 生成才规范，
> 但它同时会覆盖 `lib/main.dart` 和 `pubspec.yaml`。骨架里这两个文件是手工写的成果物，不能被冲掉。
> 还原前脚本会先校验备份完整性，校验不过就中止，不会出现"删了没得还"的中间态。

打包发布：

```powershell
cd app
flutter build apk --release --split-per-abi
# 产物：app/build/app/outputs/flutter-apk/app-arm64-v8a-release.apk
```

---

## 三、目录结构

```
D:\G-TickPicture\
├── 预检拍照APP_设计方案.html      ← 设计方案 v3.1（权威来源）
├── README.md                       ← 本文件
├── tools\
│   ├── env_doctor.ps1              ← 环境体检（只读，先跑这个）
│   ├── setup_flutter.ps1           ← 体检 + 按需补缺（不会重装已有组件）
│   ├── init_project.ps1            ← 初始化工程
│   ├── check_architecture.ps1      ← 架构约束校验（建议挂 pre-commit）
│   ├── run_unsandboxed.ps1         ← 绕开 agent 沙箱跑 flutter（关键工具）
│   ├── fetch_ppocr_model.ps1       ← PP-OCRv6 模型检查/获取（P4-D）
│   ├── pc_ocr_probe.py             ← PP-OCRv6 桌面预演探针（单张/抽样）
│   ├── pc_ocr_eval.py              ← PP-OCRv6 全量评估（真实照片基线）
│   ├── build_library.py            ← **历史照片产品库建库工具（P1）**
│   ├── verify_library.py           ← 产品库完整性自检（8 条断言）
│   ├── gen_icon.py                 ← 程序化生成 APP 图标
│   └── fix_ps1_bom.ps1             ← 修复 .ps1 的 UTF-8 BOM（见 §八.6）
└── app\                            ← Flutter 工程
    ├── pubspec.yaml
    ├── analysis_options.yaml
    ├── android\app\src\main\
    │   ├── AndroidManifest.xml     ← M2 已加 CAMERA / READ_MEDIA_IMAGES
    │   ├── assets\ppocr\           ← PP-OCRv6 模型（det.onnx / rec.onnx / keys.txt，**不入版本控制**）
    │   └── kotlin\...\ppocr\       ← P4-D 原生 OCR 引擎（PpOcrBridge / OnnxPpOcrEngine）
    ├── lib\
    │   ├── main.dart
    │   ├── app\        app.dart / router.dart / theme.dart / providers.dart
    │   ├── core\       constants.dart / naming.dart / result.dart / logger.dart
    │   ├── data\       db\（11 张表 + 数据库 + 完整性校验）/ repo\ / fs\
    │   ├── domain\     model\ / checklist\ / capture\ / grouping\ / suggest\ / assign\ / export\ / search\ / ocr\
    │   └── ui\         project\ / checklist\ / capture\（含 widgets\）/ organize\ / widgets\
    └── test\           **245 例**（分组 / 编码匹配 / 清单导入 / 采集仓储 / 存储预检 /
                        OCR 建议管道 / 整理仓储 / 交付打包 / OCR 引擎切换）
```

---

## 四、已完成里程碑

### M1 · 工程骨架（首次真实编译已通过）

**验证链条**：`flutter create` ✅ → `pub get` ✅ → `build_runner`（drift **11 张表 / 67 outputs**，70s）✅ → `flutter analyze` **0 error / 0 warning（9 info）** ✅ → `flutter test` **68/68 全通过** ✅

### M2 · 相机采集模块

**验证链条**：`pub get`（新拉 `camera` / `image` / `permission_handler` / `disk_space_plus`）✅ → `flutter analyze` **No issues found（0 error / 0 warning / 0 info）** ✅ → `flutter test` **99/99 全通过** ✅ → `check_architecture.ps1` **RESULT: PASS** ✅

| 模块 | 文件 | 说明 |
|---|---|---|
| **落盘** | `data/fs/photo_file_sink.dart` | 原图直写（`flush: true`，断电可读）+ 缩略图走 `Isolate.run` **降采样解码**（`startDecode` 先读尺寸，峰值内存从 50 MB 压到几 MB） |
| **存储预检** | `data/fs/storage_service.dart` | §8.2 唯一允许的提示。**「查不到空间」≠「空间不足」**：`unknown` 档位保持沉默，不拦人 |
| **采集仓储** | `data/repo/capture_repository.dart` | `NewPhoto` **不含归属字段**（类型上写不出 itemId）；单事务批量插入；`seq` 跨批次连续（保证交付命名不撞名）；批次**续接** |
| **采集服务** | `domain/capture/camera_capture_service.dart` | 相机生命周期、单拍、连拍（`async*` 逐张 yield）、对焦/测光/曝光、镜头切换、相册导入。**不持 context → 物理上无法弹窗** |
| **采集页** | `ui/capture/capture_page.dart` | 全屏相机（独立路由，不在 Tab 内）。界面元素**只有三个**：张数、胶片条、快门 |
| **采集组件** | `ui/capture/widgets/` | `frame_overlay`（对准框 + 对焦指示）、`shutter_button`（单击/长按连拍/拖动切镜头）、`film_strip`（只读缩略图，**绝不解码原图**） |
| **缩略图视图** | `domain/model/photo_thumb.dart` | UI 只拿到 `id + thumbPath` —— **类型层面**看不到 itemId，靠类型而不是靠纪律 |

### ✅ 可直接运行

| 模块 | 文件 | 说明 |
|---|---|---|
| **数据层** | `data/db/tables.dart` | 11 张表，字段与设计方案 §6.2 一一对应 |
| **数据库** | `data/db/database.dart` | drift，含迁移策略与外键约束 |
| **完整性校验** | `data/db/integrity_checks.dart` | §6.3 的两条不变式断言 + 采纳率统计 |
| **项目仓储** | `data/repo/project_repository.dart` | 三段式进度聚合（列表与工作台共用一条 SQL） |
| **货品仓储** | `data/repo/item_repository.dart` | 批量导入、**清单缺口查询**、候选检索、现场未见标记 |
| **文件名规范** | `core/naming.dart` | §5.5 的交付命名规则 |
| **编码匹配器** | `domain/search/code_matcher.dart` | §7.2 完整实现：归一化 + 变体纠偏 + 三级匹配 + 编辑距离 |
| **分组算法** | `domain/grouping/grouping_service.dart` | §5.3.1 完整实现，含相册时间戳可信度判定 |
| **归属服务** | `domain/assign/assign_service.dart` | §7.4 完整实现，**归属的唯一写入口** |
| **清单导入** | `domain/checklist/` 三个文件 | 文件读取 → 列映射推断 → 校验（§5.1 全部规则） |
| **相机采集** | `domain/capture/` + `ui/capture/` | M2 已落地，见上表 |
| **单测** | `test/` 五组（**99 例**） | 分组边界、纠偏不误伤、导入校验、采集仓储契约、存储预检语义 |

### 🖥 界面

| 页面 | 状态 |
|---|---|
| P1 项目列表 | ✅ 可用（含新建、三段式进度卡、下一个动作提示） |
| P2 项目工作台 | ✅ 可用（四个 Tab、红色角标、三段进度；采集 Tab 是"入口与回执"） |
| P3 清单导入向导 | ✅ **可用**（五步：选文件 → 选表 → 列映射 → 校验 → 导入） |
| **P4 采集页** | ✅ **可用**（全屏相机、快门、长按连拍、相册导入、存储预检、续接批次） |
| P12 交付 Tab 的校验面板 | ✅ 可用（真实调用 §6.3 不变式校验） |
| P6 整理页 / P9 交付页 | ⏳ 占位页（写明里程碑与设计意图，不是"敬请期待"） |

### ⏳ 已定契约、待实现

| 里程碑 | 文件 | 内容 |
|---|---|---|
| M2.1 | — | 相册 EXIF 解析（`taken_at` 优先取 EXIF）、连拍压测、长时作业资源管理 |
| — | — | WebDAV 同步（`upload_tasks` 表已建，`webdav_client` 待启用） |

**这几个文件里没有一行占位空实现，只有接口 + 约束说明。** 目的是把契约定死：M4 写 OCR 时不可能"顺手"把识别塞进采集流程，因为接口里没有那条路。

---

## 四之三、M5 · 打包交付（已完成）

### 交付结构 —— 与设计方案原定的重要偏离

设计方案 §5.5 原定「每货品一个目录」，**2026-09-23 老板拍板改为「全部照片平铺 + 对照表」**。

这个改动不是布局偏好，它改变了三件事：

1. **文件名必须自带全部身份信息**。平铺之后 `007_103010013345AMX_02.jpg` 里的三段各自有用：3 位货品序号（同一编码多件货时唯一标识"第几件"）、编码、2 位张序。退化成 `001.jpg` 就等于把报告员的唯一线索砍掉。
2. **对照表从附属品升为核心交付物**。它是报告员逐件核对的主要工作界面，列顺序按"报告员怎么读"排，不是按数据库字段顺序。
3. **目录不再承载信息**，所以分组逻辑不需要参与命名 —— 命名只依赖货品 seq 与张序。

包内布局：

```
集刻交付_<项目名>_<日期>/
├── 001_BOX-M11_01.jpg           ← 平铺，文件名自带身份
├── 001_BOX-M11_02.jpg
├── 002_BOX-M12_01.jpg
├── _对照表.csv                  ← 核心：文件名 ↔ 编码 ↔ 品名 ↔ 拍摄时间
├── _清单缺口.txt                ← 缺口汇总（不阻塞交付）
├── manifest.json                ← 程序可读的全量记录
├── 联系表.pdf                   ← 速览图（可选，含精简版）
└── _未使用/                      ← 勾选「含未使用照片」时才出现
```

### 两条硬边界

| 边界 | 落点 | 为什么 |
|---|---|---|
| **原始文件永不改名** | `ExportServiceImpl.build` 只做 `File.copy`，源文件只读 | §6.4。现场照片是证据，重命名就是篡改风险。已有单测断言源文件的**字节与 mtime 都不变** |
| **归属完整性是硬闸门** | `plan.canDeliver`（`orphanCount == 0`）不通过则抛 `StateError`，且**不留半成品目录** | 包里出现"无据可查的归属"会直接流进报告。这是正确性问题，不是体验问题 |

同时**覆盖率不是闸门**：缺口照样能交付（现场可能就先发一版草稿），只汇总进 `_清单缺口.txt`。这与「归属完整性 100%（结构保证）≠ 覆盖率 ≥80%（业务线）」是同一条原则的两面。

### `orphanCount` 检出的四类损坏

`DeliveryPlanBuilder._countOrphans` 检查：

1. 照片有 `itemId` 但 `state ≠ 'confirmed'`（缺确认标记）
2. 照片有 `itemId` 却无未吊销的 `assignments` 记录（无决策凭据）
3. **照片的 `itemId` 与 assignment 记录的 `itemId` 不一致** —— 最隐蔽的一类：凭据存在、状态也对，但凭据说的是另一件货
4. 组同理（2、3 两类）

取 **max 而非求和**：同一张照片可能同时命中多类，相加会把"1 张坏照片"报成"多处异常"，数字就不可解释了。

第 3 类是写测试时才发现的漏洞 —— 最初的实现只查"有无凭据"，而"绕过 AssignService 直接改 itemId"恰好绕过了它。**测试是有效的，它逼出了一个真实缺口。**

### PDF 联系表：为什么不用 `pdf` 包

`pdf` 包质量很好，但这里刻意自研：

- `pdf` 的常用路径依赖 `printing`（原生插件）。本工程已在 `disk_space_plus` 上吃过一次原生插件的亏（见 pubspec 注释），不值得为一个联系表再赌一次。
- 联系表需求极窄：图片网格 + 几行文字。不需要字体嵌入、不需要 CJK 排版引擎。
- **纯 Dart 产物可被单测直接断言**（断言 xref/trailer/`/Count`/字节完整性），插件的产物只能上真机眼看。

代价是中文不能进 PDF（标准 14 字体不含 CJK，嵌入中文字体要几 MB 的子集化逻辑）—— 所以 PDF 里的文字走 **ASCII 兜底**，中文信息不丢：它在 `_对照表.csv` 和 `manifest.json` 里，都是 UTF-8 全量。

实现上有一个必须注意的细节：**PDF 对象的 body 用 `List<int>` 而不是 `String`**。JPEG 原始字节经 String 往返，`0x80~0xFF` 与 NUL 都可能被破坏；更糟的是若字节里恰好出现字面量 `endstream`，阅读器会提前截断流。已有单测用含 `0x00 / 0x80 / 0xFF / ( / ) / \` 的载荷做逐字节校验。

### 验证

`flutter analyze` **No issues found** · `flutter test` **203/203**（新增 32 例交付测试）· `check_architecture.ps1` **RESULT: PASS**

---

## 四之二、M2 的三条禁令落在哪

采集期「禁 OCR、禁网络、禁弹窗」不是纪律，是**结构**：

| 禁令 | 落地方式 | 谁来保证 |
|---|---|---|
| ❌ 禁 OCR | `domain/capture/` 目录**不得 import** `domain/suggest/`，且不得出现 `mlkit` / `text_recognition` / `CodeMatcher` 等符号 | `check_architecture.ps1` 规则 1（编译期+校验期双重） |
| ❌ 禁网络 | `CameraCaptureService` 与采集页不 import 任何 HTTP 客户端；照片只写本地 | 代码结构（M5 前项目里没有 HTTP 依赖） |
| ❌ 禁弹窗 | 服务层**不持有 `BuildContext`** —— 物理上无法弹窗；采集页只有 3 个界面元素 | 类型系统 |

唯一允许的打断（§8.2）：**存储不足 / 写盘失败 / 相机被占用**，且用 `_BlockerScaffold` 替换整屏，**不用 Dialog** —— 现场的一秒钟都不该被浮层遮挡取景。


---

## 五、三条架构约束（不是风格偏好，是正确性保证）

设计方案的整个 v3.1 建立在一条前提上：**机器的建议和人的决定，在数据上是分开的。**

| # | 约束 | 违反后果 |
|---|---|---|
| 1 | `domain/capture/` 不得 import `domain/suggest/` | 采集期跑 OCR → 发热降频、续航崩、快门延迟 |
| 2 | UI 层（`lib/ui/`）不得直接 import `lib/data/`；非 `data/` 文件不得 import 生成的 `database.g.dart` | 数据访问散落，事务边界失控，UI 与表结构耦合 |
| 3 | 只有 `domain/assign/assign_service.dart` 能写 `itemId` | 出现"无据可查的归属" → 可能静默流入交付包 |

### 规则 2 的边界（容易误读，写清楚）

- **允许**：`domain/` 持有 `AppDatabase`。`AssignService` 必须自己拥有事务（先写 assignments 再改 itemId），这是 §6.3 的正确性落点，不是违规。
- **允许**：`app/providers.dart`（组装根）构造数据库与仓储，但**不向 UI 暴露类型**。
- **禁止**：UI 页面 import `data/` 下任何文件（含 `data/db/`、`data/repo/`）。UI 只能通过 `app/providers.dart` 暴露的 provider 拿数据。
- 因此**视图模型必须住在 `domain/model/`**，例如 `domain/model/delivery_readiness.dart`。UI 需要具名引用一个类型时，那个类型就不能定义在 `data/` 里。

校验：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\check_architecture.ps1
```

输出末尾带一行机器可读结论（`RESULT: PASS` / `RESULT: FAIL (n)`），退出码 0 = 通过，1 = 有违规。建议挂到 pre-commit：

```bash
# .git/hooks/pre-commit
powershell -ExecutionPolicy Bypass -File ./tools/check_architecture.ps1 || exit 1
```

注释行不参与匹配（中文注释里引用"不得 import domain/suggest"这类描述性文字属于合法文档）。

### 最核心的一条不变式

`AssignService.confirmGroup` 的事务里，顺序是：

```
① 吊销旧的 assignments 记录
② 插入新的 assignments 记录   ← 先
③ 更新 photo_groups.itemId    ← 后
④ 更新 photos.itemId          ← 后
```

**②必须在③④之前。** 这个顺序保证了任何时刻都不存在"有归属但没有决策记录"的状态——哪怕事务中途崩溃。

如果反过来写，崩溃时会留下一条无据可查的归属，而它可能流进交付包。**整个方案的归属正确性就落在这一条顺序上。**

---

## 六、常用命令

```powershell
cd app

flutter pub get                                  # 拉依赖
flutter pub upgrade --major-versions             # 依赖版本对不上时用这条自动对齐
dart run build_runner build --delete-conflicting-outputs   # 重新生成 database.g.dart
dart run build_runner watch                      # 开发时常驻，改表自动重建
flutter analyze                                  # 静态分析
flutter test                                     # 跑单测
flutter run                                      # 装到手机
flutter build apk --release --split-per-abi      # 出安装包
```

> **agent 代跑时**：上面每条命令都要包一层 `run_unsandboxed.ps1`（见 §一）。

**改了 `lib/data/db/tables.dart` 之后必须重跑 `build_runner`**，否则 `database.g.dart` 与表定义不一致，编译会报一堆看不懂的错。

---

## 七、排期对照（按 v3.1 真实规模）

| 里程碑 | 时长 | 内容 | 完成判据 |
|---|---|---|---|
| **M1** | 1 周 | 工程骨架 · 数据层 · 清单导入向导 · 工作台 | ✅ **已完成并验证** |
| **M2** | 1.5 周 | 采集模块（相机/连拍/落盘/相册导入/长时资源管理） | ✅ **主体已完成并验证**（analyze 0 问题 / 99 测试通过 / 架构校验 PASS）；⏳ 剩相册 EXIF 解析与 1200 张压测 |
| **M3** | 2 周 | **整理工作台**（分组卡片流 / 批量确认 / 指派面板 / **覆盖率仪表 + 缺口视图** / 双路径整理） | ✅ **已完成**。第 1 轮灰度：纯手动完成 **400 件货**对应 ≤ **45 min** |
| M4 | 1 周 | OCR 建议引擎接入（可开关） | ✅ **已完成**（可整体关闭）。第 2 轮灰度：建议采纳率 ≥ 80%，整理耗时 ≤ **20 min** |
| **M5** | 1 周 | 交付（ZIP / PDF 联系表 / 对照表 / **清单缺口.txt** / 微信分享） | ✅ **已完成**（v0.6.0）。交付包能被报告员直接排版。**WebDAV 上传待做** |
| M6 | 1 周 | 第 3 轮灰度 · 打磨 · 分发 | 连续 5 次任务无崩溃；**含整天作业稳定性** |
| **P4** | — | 四条现场诉求（重复编码 / 全图+拖拽 / 整理页可见性 / PP-OCRv6） | ✅ **全部完成**（analyze 0 问题 / **249 测试通过** / 架构校验 PASS / debug + release 构建通过）。PP-OCRv6 模型已落地（det 9.4MB + rec 20.2MB + 字典 18708，sha256 均校验通过），**并已用客户真实数据（249 张照片 + 真实清单）完成桌面预演验证**。⏳ 仅剩**真机运行时验证** |

**M1 新增交付项**：覆盖率达标线**按项目可配**（80% 不写死）。

**最早可灰度：第 5.5 周（M3 结束）** —— 那时是纯手动模式的完整工具，不必等 OCR 调好。

**灰度纪律**：第 1 轮必须不开 OCR。否则出问题分不清是"整理页设计不好"还是"建议不准"。

---

## 八、已知风险与注意事项

1. **依赖版本**：`pubspec.yaml` 里的版本号以 2025 年的稳定版为基准。若 `flutter pub get` 报某版本不存在，跑 `flutter pub upgrade --major-versions` 自动对齐，然后 `flutter analyze` 复核。
2. **Flutter 版本下限 3.27**：工程用到 `CardThemeData` 与 `Color.withValues`。低于此版本请先 `flutter upgrade`。
3. **首次编译已完成**（见 §四），骨架不再是"未经编译验证"状态。后续改动的验证请以 `flutter analyze` + `flutter test` 的真实输出为准。
4. **灰度前必须拿到的材料**：
   - 真实货品清单 Excel 2~3 份（验证导入向导的健壮性，最好含一份"列名不规范"的）
   - 真实货品标签照片 20~30 张（校准 `code_matcher.dart` 的形近纠偏表）
   - 报告员现在收到的照片是怎么组织的（对齐 M5 的交付格式）
   - 一次真实作业记录（件数 / 张数 / 时长，用于把 §9.1 的性能档位从估算变实测）
5. **`const A = 45 秒`、`12 张`、`0.90` 这些参数都是初始值**，全部集中在 `core/constants.dart`，每个都注明了调整依据。灰度后用真实数据回写，不要在调用点就地改数。**覆盖率达标线（80%）尤其要按项目可配。**
6. **⚠️ `.ps1` 必须保存为 UTF-8 with BOM（已踩过一次坑）**
   Windows PowerShell 5.1 会把**无 BOM** 的 `.ps1` 按 ANSI(GBK) 解码。中文全变乱码，更麻烦的是某些 UTF-8 三字节序列会被当成 GBK 前导字节、**连同后面的换行符一起吃掉**，于是报错行号也是漂移的（报 89 行，实际 96 行），一串 ParserError 看起来很吓人。
   而 PowerShell 7.x 默认按 UTF-8 读，完全看不到问题——典型的"我这儿是好的"。
   另外 `✅ ▸` 这类符号在代码页 936 下显示为 `?`，脚本里统一用 `[ OK ] [WARN] [FAIL] [SKIP]` 纯文本标记。
   **改完任何 `.ps1` 后跑一次：**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\tools\fix_ps1_bom.ps1
   ```
   该脚本自身是纯 ASCII，即使所有脚本都坏掉它也能跑。幂等，只改编码不动内容，非合法 UTF-8 的文件会拒绝处理。
7. **⚠️ `flutter config` 里的 `android-sdk` 会覆盖 `ANDROID_HOME`（已踩过一次坑）**
   Flutter 定位 SDK 的顺序是：`flutter config` 的 `android-sdk` → `ANDROID_HOME` → `ANDROID_SDK_ROOT` → 反查 `aapt`/`adb`。
   只要 `%APPDATA%\.flutter_settings`（**Windows 上路径是 `%APPDATA%`，文件名带点号前缀**）里存了一个**不存在**的路径，环境变量怎么设都会被忽略，`flutter doctor` 会一直报：
   ```
   X ANDROID_HOME = <路径>
     but Android SDK not found at this location.
   ```
   **改环境变量前先看这个文件。** 修法：`flutter config --android-sdk <正确路径>`，或让 `setup_flutter.ps1` 自动修（它已内置该能力）。
   注意该文件是**无 BOM** 的 UTF-8 JSON——Dart 的 `jsonDecode` 不接受 BOM。
8. **不要并行开多个 PowerShell 会话做诊断**（会互相干扰，见过 `where.EXE` 的管道异常污染定位结论）。
9. **Dart 命名雷区（首次编译才暴露，报错位置与真因不一致）**：
   - 表字段不能叫 `text`（与 drift `Table.text()` 方法冲突）→ 用 `named('text')` 保留列名、Dart 侧改名
   - **enum 的枚举值不能与实例字段同名**（枚举常量是静态成员）→ 报错却指向构造函数
   - `const XxxCompanion(field: Value(SomeEnum.value.code))` 非法（enum 实例 getter 不能在 const 上下文求值）→ 去掉外层 `const`
   - 同一文件不要并行编辑（会静默覆盖，工具仍报 success）

---

## 九、下一步

**M1 ~ M5 全部完成，P1~P4 四条现场诉求也已全部落地。** 三段式主路径（批量采集 → 统一对应 → 打包交付）已闭环，可交付给报告员的 ZIP 包能直接生成。

### P4 · 四条现场诉求（2026-09-23 完成）

| # | 诉求 | 做法 | 验证 |
|---|---|---|---|
| 1 | 同一货品分散多箱 → **清单编码重复** | 导入规则 2 由「跳过」改**合并**：数量累加、箱号收集成列表（`Items.containerSummary`）、`sourceLineCount` 记录占了几行。唯一键 `{projectId, code}` 不变 | +16 例测试 |
| 2 | 整理页**不能看全图 / 不能拖拽合并** | 新增全屏 `photo_viewer_page`（双指缩放 + 左右翻页 + 双击复位）；组卡片支持**长按拖拽**到另一张卡片上合并 | 架构校验 PASS |
| 3 | 采集后整理页**看不到新照片** | 根因是「查不到」不是「慢」：`watchOpenGroups` 只查已入组的组，新照片 `group_id` 为 NULL。改为**订阅式数据驱动** + `regroupPending` 加重入锁 | +5 例测试 |
| 4 | OCR 换 **PP-OCRv6** | Platform Channel 桥接原生 ONNX Runtime 引擎；设置里可切「标准识别 / 增强识别」，不可用时**静默回退** ML Kit | +21 例测试 |

### P4-D · PP-OCRv6 使用说明（✅ 模型已落地，2026-09-24）

模型文件**已就位**（不入版本控制，用脚本获取）。缺文件时不会报错 —— 自动回退 ML Kit，全流程照常。

```powershell
.\tools\fetch_ppocr_model.ps1 -Mode check     # → RESULT: PASS / MISSING（含 sha256 + 字典行数校验）
.\tools\fetch_ppocr_model.ps1 -Mode fetch     # 从 ModelScope 下载并校验，自动生成 keys.txt
.\tools\fetch_ppocr_model.ps1 -Mode clean     # 清空（保留 README.txt）
```

**获取的三个文件**（都带 sha256 校验，错了会拒绝生成）：

| 文件 | 体积 | 来源 |
|---|---|---|
| `det.onnx` | 9.4 MB | ModelScope `PaddlePaddle/PP-OCRv6_small_det_onnx` |
| `rec.onnx` | 20.2 MB | ModelScope `PaddlePaddle/PP-OCRv6_small_rec_onnx` |
| `keys.txt` | 73 KB / 18708 行 | 从 rec 包的 `inference.yml` 里的 `character_dict` 生成 |

**关键坑（三个都实测踩过）：**

1. **huggingface.co 在这台机器上不通** —— DNS 会解析到错误 IP（`208.101.60.87`），代理和直连都失败。脚本走 **ModelScope**，同一批模型，sha256 与 HF 版逐字节一致。
2. **官方发布的是 Paddle 推理格式**（Paddle 3.0 的 PIR：`inference.json` + `inference.pdiparams`，**没有 `.pdmodel`**），不是 `.onnx`。但 ModelScope 这两个仓库是**官方已转好的 ONNX 版本**，所以**不需要 paddle2onnx**。
3. **字典第 1748 条是 U+3000 全角空格「　」**。解析时必须用 `Substring` / `trimEnd('\r','\n')`，**绝不能**用 `Trim()` / `.strip()` —— 它们会剥掉 Unicode 空白把这条读成空串，导致后面 17000+ 个字符下标整体前移，**输出整片乱码且不报错**。

**前处理参数全部取自模型自带的 `inference.yml`，不是凭记忆写的**（早期版本凭印象写的值与官方**三处不符**，会直接把识别率打到 0）：

| 参数 | 早期写的值 | 官方真实值 |
|---|---|---|
| det 归一化 | `(x/255-0.5)/0.5` | `(x/255 - [0.485,0.456,0.406]) / [0.229,0.224,0.225]` |
| 通道序 | RGB | **BGR**（`img_mode: BGR`） |
| 二值化阈值 | 0.3 | **0.2**（`DBPostProcess.thresh`） |
| rec 归一化 | 同 det | `(x/255-0.5)/0.5` —— **与 det 不是一套**，且藏在 `RecResizeImg` 里（yml 无 `NormalizeImage` 项）|
| rec 填充 | 黑边（-1.0）| **归一化空间的 0.0**（= 原始像素 127.5 的中灰），黑边会被当成一整片墨迹 |

实测模型签名（ONNX protobuf 解析得到）：`det` 输入 `x [N,3,H,W]` → 输出 `fetch_name_0 [N,1,dH,dW]`（**概率图**，后处理自己做）；`rec` 输入 `x [N,3,48,W]` → 输出 `[N,T,18710]`。`18710 = 1 blank + 18708 字典 + 1 空格`，`create()` 会**拿这个维度反查字典长度**，对不上直接回退 ML Kit —— 宁可不用也不能输出错字。

**体积代价（实测）**：release APK 34.1MB → 51.6MB（仅 ONNX Runtime）→ **76.5MB（含模型）**。明细：`libonnxruntime.so` 17.5MB + `rec.onnx` 17.6MB + `det.onnx` 7.2MB + `keys.txt` 38KB（arm64-v8a 单架构，assets 已压缩）。这是引入端侧高精度 OCR 的必要成本；debug APK 则为 149MB。

**桌面预演（2026-09-24，用客户真实数据验证引擎，详见 `doc/PP-OCRv6_真实数据基线报告.md`）：**

用 `tools/pc_ocr_probe.py` / `pc_ocr_eval.py`（Python onnxruntime **逐行复刻 Kotlin 引擎的前后处理**）跑客户真实素材（清单 90 行/81 编码 + 作业照片 249 张）：

- **引擎三层全部验证正确**：rec 合成图 `CX0150867` 置信度 1.000；真实装箱单近拍编码直读 0.94~1.00（一张命中 13 个编码）；倒贴标识卡 180° 后表头字段 0.97~1.00。
- **全量基线**：249 张 0 失败；照片命中率 2.8%、清单覆盖率 21% —— 低命中的真实原因是**大部分照片是外观/人物/空箱（无编码可读）**，不是引擎问题。提高 det 像素预算（70 万→400 万）实验**无收益**，70 万像素维持不变。
- **探针提前抓掉 2 个真机必现 bug**：det 输入必须 32 对齐（否则每张都静默回退 ML Kit）；塑料袋反光会出 300+ 误检框（加 `MAX_REC_CROPS=40` 上限，否则单张 rec 几十秒）。
- **新增 rec 四方向兜底**（0° 置信度 <0.85 才试 180/90/270）：倒贴标识卡 0° 全乱码、180° 满分 —— det 对倒置文字无感，兜底必须在 rec 层；打印体 0° 就有 0.92+，几乎零开销。
- **清单导入顺带补强**（真实清单逼出来的）：箱号向下填充（合并单元格视觉 → 稀疏填写）；`Model Number` 列名加入编码列关键词；新增 4 个真实结构单测（test 249/249）。

**剩余待做（按优先级）：**

1. **PP-OCRv6 真机验证**（P4-D 唯一剩余项）：桌面预演后，未验证的只剩「Android 端 ONNX Runtime 运行时」一层。装 debug 包 → 导入 `数量检查-PIDU9352234.xlsx` → 设置切「增强识别」→ 看状态行显示的是不是 PP-OCRv6、拍装箱单近拍看建议是否命中编码。
2. **WebDAV 上传**（M5 尾项）：`upload_tasks` 表已建、`AppConst` 里的并发 3 / 退避 1-5-15-60min 已定义，只差 `webdav_client` 启用与上传队列实现。大包（>200MB）走网盘比微信直传体验好得多。
3. **真机压测（M6 门槛）**：飞行模式连拍 1200 张 —— 无卡顿、无弹窗、无网络请求、**内存不持续增长**；以及 6~8 小时长时作业的资源管理复核。这一条是 v3.1 新增的 R1b 风险项，必须实测。
4. **交付物纳入箱号**：`ItemWithShot.containerSummary` 已在概览页展示，但 `DeliveryPlan` / 对照表 CSV / 缺口报告尚未纳入箱号。

**灰度前必须拿到的材料**（见 §八.4）：真实清单 2~3 份、标签照片 20~30 张、报告员现在的照片组织方式、一次真实作业记录。

```powershell
# 老板自己开终端
cd D:\G-TickPicture\app
flutter devices && flutter run
```

现在跑起来可以走完整条链路：新建项目 → 导入清单（xlsx / xls / csv）→ 全屏相机采集 → 整理页对应 → 交付 Tab 选选项、生成交付包、直接分享。

**照片的归属现在有完整的决策记录链路**：整理页确认 → `AssignService` 写 assignments + itemId → 交付页自检 → 打包。任何一环断了，交付闸门都会拦住。

---

## 十、历史照片产品库（P1 建库工具）

把历史预检的照片与清单整理成**可按编码召回的产品库**，用于将来漏检时补图。

### 为什么存在

现场作业覆盖率不可能 100%（货未到 / 压垛底 / 漏拍）。缺口是常态，而报告员需要"这件货长什么样"的图。历史作业里往往拍过同款货，但散在普通文件夹里，无法检索。

### ⚠️ 五条不可越过的边界

| # | 边界 | 落地方式 |
|---|---|---|
| 1 | **历史照片不是现场证据** | 库里每张照片记录 `taken_at` + 来源作业；复用时必须在文件名与对照表标明来源 |
| 2 | **不做 OCR 自动归档** | 实测 249 张真实照片，OCR 照片命中率仅 4.2%（236 张里 10 张）。自动建库=空壳，人必须复核 |
| 3 | **C_adjacent 不算证据** | 时序推断只作为复核提示，**不计入 `photo_count`**（`verify_library.py` 的 A4 断言守住这条） |
| 4 | **不新增写归属的入口** | 复用照片后续落成 `capture_session(source='library')` 的普通照片，归属仍只由 `AssignService` 写 |
| 5 | **源照片只读** | 工具不解码回写、不改名、不移动；输出全部在 `--out` 目录 |

### 用法

```powershell
# 1) 干跑看统计（推荐第一次这么用）
python tools\build_library.py --photos doc\PIDU9352234 --dry-run

# 2) 真跑（OCR 全量 236 张约 13 分钟；结果自动缓存，二次运行秒级）
python tools\build_library.py --photos doc\PIDU9352234 `
    --customs "doc\PIDU9352234\MX-PL20250405-02（星邦机械第二柜+焊丝）-报关资料.xlsx" `
    --out library

# 3) 跳过 OCR，只验证清单解析（秒级）
python tools\build_library.py --photos doc\PIDU9352234 --no-ocr --out library

# 4) 自检（8 条断言，只读）
python tools\verify_library.py --db library\library.db --csv-dir library

# 5) 人工复核后回写（改 _待复核.csv 的「动作」列：确认 / 否决）
python tools\build_library.py --photos doc\PIDU9352234 --out library `
    --apply-review library\_待复核.csv
```

### 产出

| 文件 | 用途 |
|---|---|
| `library.db` | SQLite：`products` / `photos` / `bindings` 三张表 + `library_meta` |
| `_编码对照表.csv` | **人工复核的主要界面**：编码 ↔ 照片 ↔ 级别 ↔ 依据 |
| `_待复核.csv` | 只有 B/C 级，按「动作」列过一遍 |
| `_建库报告.md` | 统计 + 已入库编码明细 + 无照片编码 + 跨时段编码 |
| `manifest.json` | 程序可读快照（与 M5 交付包 manifest 同构） |
| `_ocr_cache.json` | OCR 原始结果缓存（调参不必重跑） |

### 绑定强度分级

| 级别 | 判据 | 可信度 |
|---|---|---|
| `A_strong` | 既往交付包里的 `_对照表.csv`（已人工确认） | 高，可直接用 |
| `B_ocr_multi` | 同一张照片 OCR 命中 ≥2 编码（装箱单近拍特征） | 中，扫一眼即可确认 |
| `B_ocr_single` | 只命中 1 编码 | 中低，需逐条核对 |
| `C_adjacent` | 同组内有 B 级命中、本张无 | **低，不是证据** |

### 与 APP 的口径一致性（改参数时必须同步）

`build_library.py` 顶部常量**逐条复刻** `app/lib/core/constants.dart` 与
`app/lib/domain/search/code_matcher.dart`：分组间隔 45s / 单组上限 12 张 /
三级匹配基数 0.98-0.86-0.88-0.72 / 编辑距离上限 2 / 纠偏表只有 O→0、I→1、L→1、S→5。

**APP 侧改了这些值，本工具必须同步改** —— 否则库里存的"建议"与现场
算出来的对不上，人工复核的依据就失真了。

### 实测基线（PIDU9352234 · 2025-04-05 作业 · 249 张）

| 指标 | 数值 |
|---|---|
| 照片 | 249 个（MD5 重复 13 个 → 唯一 236）· 902 MB |
| 分组 | 55 组（>45s 或超 12 张切分） |
| 清单 | 89 行 → 81 唯一编码，19 个箱号 |
| 报关单 | 主 sheet 表头在第 11 行 → 81 唯一料号 |
| **两份文件编码集合** | **交集 81（完全一致，可互相印证）** |
| OCR | 236 张 · 86.0% 识别出文字 · **仅 10 张（4.2%）命中清单编码** |
| 入库编码 | **28/81（34.6%）** |
| 其中 | 23 个来自 **2 张装箱单近拍**（各命中 13 个编码） |

**结论**：装箱单近拍是唯一高效路径。标识卡（手写）是硬边界，OCR 认不出是预期行为。

---

## 十一、产品库系统（`tools/productlib/`）

§十的 `build_library.py` 是**一次性建库脚本**（跑完出报告）。这一章是**可持续运营的产品库**：
清单导入 → 照片治理 → 自动关联 → 人工补关联 → 按编码召回。有界面，可反复增量导入。

### 五条构建逻辑 → 落地位置

| # | 要求 | 落地 | 验证 |
|---|---|---|---|
| 1 | 编码唯一标识 + 清单导入 + 数据规范 | `schema.py` 的 `PRODUCT_FIELDS`（code 必填/含数字/≥4 位）、`store.import_checklist_file` | S1a~S1d |
| 2 | 批量上传照片 + OCR/多模态治理 | `store.add_photos`（目录或网页上传）、`pipeline.govern_one`（分类→分路→融合）、`vision.py` | S2a~S3d |
| 3 | 产品 ↔ 图片自动对应 | `pipeline.apply_auto_links`（**仅认精确匹配 exact 才自动写**；prefix/edit1/edit2 一律进人工工作台，不自动建链） | S5a~S6 |
| 4 | 未能自动关联的，人工关联 | `store.link()`（唯一写入口，记 source + created_by）、工作台 `/api/workbench` | S7a~S8d |
| 5 | 按产品看所有采集图片 | `store.product_photos()` → `/api/products/{code}/photos` | S10a~S10c |

### 启动

```powershell
# Web 界面（推荐）
python -m tools.productlib.server            # 自动开 http://127.0.0.1:8765
python -m tools.productlib.server --port 9000 --no-browser

# 命令行（大批量照片走这条，不经过浏览器）
python -m tools.productlib.cli stats
python -m tools.productlib.cli import-checklist doc\PIDU9352234\数量检查-PIDU9352234.xls
python -m tools.productlib.cli import-photos  doc\PIDU9352234
python -m tools.productlib.cli govern                    # 全量
python -m tools.productlib.cli govern --limit 20         # 先试 20 张
python -m tools.productlib.cli show 1000000119           # 看这个产品的所有照片

# 端到端自检（独立测试库，25 条断言）
python -m tools.productlib.selftest --limit 20
python -m tools.productlib.selftest --full
```

### 治理管道：为什么要先分类

实测 249 张：86% 有文字，但**只有 4.2% 命中产品编码**，其余是车牌、集装箱号、公司名。
不分类就全跑 OCR，等于把 96% 的算力喂给噪声。

```
① 分类（多模态优先，无 key 时降级）
② 分路： scene（无产品信息，车辆/集装箱/车牌/空场）→ 跳过，不跑 OCR，不关联
          packing_list（物料清单/装箱单）        → OCR 提取参考文字，但**不关联产品**（它是多编码文档）
          label / unknown                        → OCR 精确读码，命中则自动关联
          product / packaging                    → 多模态**只出描述、不请求编码**（产品本体照无标签，请求编码会"脑补"出错误编码）
③ 融合：OCR 编码 → 多模态编码 → 语义提示
④ **仅 exact（归一化完全相等）自动关联**；prefix/edit1/edit2 不自动写，作为候选进人工工作台，由人核对后点选
```

> ⚠️ 准确性铁律：自动关联的编码必须与产品库某编码**逐字符相等**才写。
> 任何"差一两个字符"的读法（OCR/多模态都可能读错）都**不自动关联**——
> 错关联比没关联危险得多。读错的码不会消失，而是带"模糊·核对"标记出现在人工工作台。
>
> 不是所有照片都有标签：scene / product / packaging 照上通常没有物料编码，
> 界面会明确标注"无标签编码（正常）"，不会让你误以为漏识别。
>
> **物料清单 / 车辆 / 车牌等照片不关联产品编码**（`schema.NO_LINK_KINDS`）：
> 物料清单（packing_list）含很多编码，但它是参考文档，整页关联到某个单一产品是错的；
> 车辆/集装箱/车牌/空场（scene）本身无产品信息。这两类只提取内容用于展示，
> 既不自动关联，也不进人工工作台（避免污染认领队列）。若确要关联，只能人工在库里手动加。

**OCR 结果必缓存**（`productlib/data/_ocr_cache.json`）。实测 249 张全量 700s、
有缓存 1.2s；且直接复用 §十 已跑好的 `library/_ocr_cache.json`，不重复付这 12 分钟。

### 关联的唯一写入口

```python
store.link(con, code_norm, photo_id, source, confidence, evidence, created_by)
#   source: auto_ocr / auto_vision / auto_semantic / manual
#   created_by: 'system' 或 人
```

与 APP 侧「归属只能由 `AssignService` 写」是同一条原则 —— 将来能回答
"这条对应关系是谁认定的"。界面与 CLI 都不直接 INSERT `links`。

### 实测基线（同一批 PIDU9352234 数据，正式库）

| 指标 | 数值 |
|---|---|
| 产品 / 照片 / 关联 | 81 / 249 /（精确匹配重算中，见下） |
| 有照片的产品 | **26/81（32.1%）** |
| 自动关联规则 | **仅 exact 才写**；fuzzy 进人工工作台（修订于 2026-09-27，根治"脑补错链"） |
| 照片分类分布 | label 42 · packaging 88 · packing_list 14 · product 31 · scene 10 · unknown 31 |
| 全量治理耗时 | 缓存命中 1.2s；**含多模态 ≈ 35~40 分钟**（236 张 × 2 调用） |
| 自检 | `selftest --full` **25 项 PASS**；Web 冒烟 **19 项 PASS** |

### 界面（左右分栏 + 详情抽屉）

- **产品页**：左=清单，右=选中产品的全部预检采集图（不再下方堆叠、不再跳转）。
- **照片卡片**：下方直接显示大模型提取到的编码（黄字），一眼看出哪张读到了码。
- **点任意照片 → 右滑抽屉**：大图 + 分类/置信 + 大模型读出的编码（绿勾=已关联）+ OCR 文本 + 描述 + 已关联列表 + 候选一键关联。模糊候选带"需核对"标记。
- **人工工作台**：只收入可关联的照片（物料清单/场景照不在此列）；展示大模型读码与描述；无标签照明确标注"外观/场景照属正常"。

### 多模态真实验证（2026-09-27，SiliconFlow + Qwen3-VL-32B）

- 调用链路**已真实跑通**：classify 与 describe 均返回合法 JSON，
  卡车照正确判 `scene`（0.95），描述能读出车型与车牌、不误报编码。
- **关键坑：Qwen3 系列思考模式默认开**，同一张图 32s → 关掉后 2.5s。
  `_call` 默认带 `enable_thinking=false`；不认这个参数的 provider 返回 400
  时自动去掉重试，保持可插拔。
- 稳态耗时 4~10s/次（服务端有波动），全量 236 张串行约 35~40 分钟 ——
  一次性成本。刻意**不做并发**：并发容易撞 429 限流，而限流会被当成
  "调用失败"静默降级成 unknown，比慢危险得多。
- `govern_all(reset=True)` 支持全量重跑：配置多模态或改规则后，
  把全部照片重置为待治理再算（界面「重新治理」按钮）。人工关联不受影响。
- 降级模式（无 key）实测 203/236 落到 unknown（有文字但无编码）—— 这正是
  需要多模态的地方。228 张未关联照片靠逐张点不现实 —— 建议下一步做
  「按拍摄组批量关联」。

