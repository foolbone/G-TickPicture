# 集刻-采集 · 版本发布规则

> 适用范围：G-TickPicture（集刻-采集）Android 端。
> 唯一真源：`app/pubspec.yaml` 的 `version:` 字段。
> 发版唯一入口：`tools/release.ps1`。
>
> 本规则 2026-09-29 制定，首个适用版本 **v0.7.0**。

---

## 一、版本号格式

```
version: MAJOR.MINOR.PATCH+BUILD     例：0.7.0+6
```

| 片段 | 去向 | 说明 |
|---|---|---|
| `MAJOR.MINOR.PATCH` | Android `versionName` | 用户可见的版本串 |
| `BUILD` | Android `versionCode` | **必须严格单调递增，永不回退**（Android 装包以此判新旧） |

`app/android/local.properties` 里的 `flutter.versionName/versionCode` 由 Flutter
构建时从 pubspec 自动生成，**不要手改、不要入库**。

## 二、什么时候升哪一位

| 变更类型 | 升位 | 判断口径 | 实例 |
|---|---|---|---|
| 缺陷修复 | **PATCH** | 行为契约不变、不改数据格式 | 相册位置记忆修复（3 个叠加 bug） |
| 新功能 / 性能优化 / 新增模块 / UI 交互变更 | **MINOR** | 加了东西或变快了，老数据照读 | 导入链路优化 + 低配机型设备分级 |
| DB schema 不兼容 / 交付包格式变更 / 需要数据迁移 | **MAJOR** | 老版本装不上或读不了新数据 | `0.x → 1.0.0` 正式上线 |
| 仅文档、注释、测试、脚本 | **不升** | 不打 tag、不发版 | 本文本身 |

- 一次发布含多类变更 → **取最高档**（例：修复 + 性能优化 = MINOR）。
- `BUILD` 只在**发布**时 +1，开发过程中不动。一次发布 = 一次 +1。
- 0.x 阶段允许"快糙猛"：MINOR 不必等攒够，能发就发。

## 三、发版门禁（全绿才允许打 tag）

| # | 检查 | 通过标准 | 命令 |
|---|---|---|---|
| 1 | 静态分析 | `No issues found!` | `flutter analyze` |
| 2 | 全量测试 | `All tests passed`，且**无跳过** | `flutter test` |
| 3 | 架构检查 | `RESULT: PASS` | `tools/check_architecture.ps1` |
| 4 | 发布构建 | `EXIT=0`，并**核对产物时间戳**（见铁律 8） | `flutter build apk --release` |
| 5 | 更新日志 | `CHANGELOG.md` 已有本次条目 | 手写 |
| 6 | 版本号 | pubspec 已升、`BUILD` 递增 | 由脚本完成 |

> ⚠️ 门禁 4 的"核对时间戳"不是形式主义：构建命令可能报成功但产物是上一版
> 的残留。**必须看 APK 的 LastWriteTime 是刚才**。

## 四、发版流程

### 自动（推荐）

```powershell
# 从项目根目录，PowerShell 5.1
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\release.ps1 -Bump minor
```

脚本依次做：算新版本 → 检查工作区干净 → 改 pubspec → 跑门禁 1/2/3 → 构建
→ 产物归档并重命名 → `git commit` + `git tag -a vX.Y.Z`。

常用参数：

| 参数 | 作用 |
|---|---|
| `-Bump patch\|minor\|major\|none` | 升哪一位（默认 `patch`）；`none` = 只重建不升版 |
| `-SkipBuild` | 跳过构建与门禁，只改版本号 + commit + tag（**紧急 tag 用，禁止用于对外发版**） |
| `-SkipGates` | 跳过门禁 1–3，仍构建（**同样禁止用于对外发版**） |
| `-AllowDirty` | 放行"工作区不干净"这道检查（配合 `-CommitPaths` 用，见下） |
| `-CommitPaths 'a,b,c'` | 只把这些路径纳入发布提交（相对仓库根）。**工作区里有别的会话的成果时必用** |
| `-WhatIf` | 预演：打印将执行的动作，不改任何文件。首次用某个 bump 前先跑一遍 |

> **为什么要有 `-CommitPaths`**：脚本末尾默认是 `git add -A` + 一条
> `chore(release): vX.Y.Z`。这意味着工作区里**任何**未提交改动都会被这条
> 提交吞进去 —— 包括别的会话留下的成果（本仓库的 `tools/productlib/` 经常
> 处于这种状态）。混进去之后，那批改动的来龙去脉就再也说不清了。
> 限定路径后，没被列出的改动会**留在工作区**，脚本还会把它们列出来提醒你。

```powershell
# 工作区里有别的会话的未提交成果时
.\tools\release.ps1 -Bump minor -AllowDirty -CommitPaths 'app,CHANGELOG.md,tools/release.ps1'
#→ 8/8 阶段会 [WARN] 列出未纳入本次提交的剩余改动
```

> 门禁失败中断后直接重跑即可 —— 脚本会比对工作区版本与 `HEAD` 版本，
> 不一致就判定为续跑，**沿用已改的版本号不再升位**（不会把 0.7.0 推成 0.8.0）。

### 手动（脚本不可用时的退路）

1. 改 `app/pubspec.yaml` 的 `version`
2. 补 `CHANGELOG.md`
3. 依次跑门禁 1–4
4. `git add -A && git commit -m "chore(release): v0.7.0"`
5. `git tag -a v0.7.0 -m "v0.7.0"`
6. 产物复制到根目录：`集刻-采集_v0.7.0_release.apk`

## 五、提交信息规范（Conventional Commits 简化版）

```
<type>(<scope>): <一句话说明>

<body>：为什么改（不是改了什么 —— diff 能看出来）
```

`type`：`feat` / `fix` / `perf` / `refactor` / `docs` / `test` / `chore`
`scope` 可选：`capture`、`gallery`、`organize`、`deliver`、`ocr`、`repo`、`ui`、`tools`

正文必须回答**为什么**。踩过坑的修复，要把根因和复现证据写进去 —— 三个月后
没人记得当时为什么这么写。

## 六、分支与标签

- 当前单人开发：**只在一个主分支上线性提交**（现为 `main`）。
- 每个发布点打**附注标签** `vX.Y.Z`，标签即"这个版本的代码快照"。
- 已发布的 tag **不允许移动或删除**。发错了就升一位重发。
- 将来若多人协作：改 `feature/*` 分支 + 合并到主分支后发版，规则不变。

## 七、产物命名与归档

- 构建输出：`app/build/app/outputs/flutter-apk/app-release.apk`
- 归档文件名（项目根目录）：`集刻-采集_v{versionName}_release.apk`
- 归档 APK **不入库**（已在 `.gitignore` 里），只作为交付物存在本地/网盘。
- 需要保留的历史版本请另存到网盘，不要靠 git 存二进制。

## 八、真机验收清单（发版后必做）

桌面验证（analyze/test/构建）证明不了真机可用。每次发版至少过一遍：

- [ ] 装包能启动，无启动崩溃
- [ ] 新建项目 → 相机拍 1 张 → 胶片条出现缩略图
- [ ] 相册导入：选 **50 张以上** 导入，记录耗时与是否卡顿
- [ ] 相册选择：翻到深处 → 退出 → 再进入 → **回到上次那一行**
- [ ] 整理页：对应、改箱号、删除
- [ ] 交付：平铺导出 + CSV，包内能打开
- [ ] 低配机（2–3GB RAM）跑一遍上面第 2、3 条

结果写进 `CHANGELOG.md` 该版本条目下的「真机验收」。

## 九、发版前置：新机器准备

签名密钥**不在仓库里**（`.gitignore` 排除）。新机器首次发版前必须自备：

1. 取回 `keys/upload-keystore.jks`
2. 在 `app/android/` 下建 `key.properties`：

   ```
   storePassword=<密码>
   keyPassword=<密码>
   keyAlias=gt-upload
   storeFile=<本机 jks 绝对路径>
   ```

3. `app/android/local.properties` 由 Flutter 自动生成，无需手建

> ⚠️ `key.properties` 含明文密码，**永远不要提交**。

## 十、回滚

- 代码回滚：`git checkout vX.Y.Z`（只用于定位问题，不要在主分支上 reset 已推送历史）
- 用户侧回滚：Android 不允许降级安装（versionCode 会拦），只能**升一位重发**修复版。
  所以发版前那遍真机验收，比事后回滚便宜得多。
