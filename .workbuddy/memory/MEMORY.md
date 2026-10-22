# 项目：G-TickPicture（集刻-采集）

## 定位与环境
- 仓库预检监装 Android 取证工具（Flutter 3.29 + Riverpod + drift，minSdk26）+ Web 端 productlib（FastAPI+SQLite+PyInstaller 绿色包，tools/productlib/，零 App 发版）。细节看当日 daily log。
- Flutter `D:\dev\flutter`；SDK `D:\dev\Android\SDK`；JDK21；agent 跑 flutter 必走 tools/run_unsandboxed.ps1（EXIT= 行才权威）。
- Python `C:/Users/Bone/.workbuddy/binaries/python/versions/3.13.12/python.exe`；productlib 源码服务 8765。

## 核心原则
- 三段式物理隔离（采集→对应→交付）；采集期零智能；归属 itemId 只 AssignService 写。
- 分组=按批次一组（5min 续接窗口）；原始文件永不改名；措辞禁「现场未见」。
- **App 照片命名 = 连拍判据第一手证据**：`yyyyMMdd_HHmmss_000NN.jpg`（时间戳=快门时刻，末段=会话连拍序号），交付结构 `预检/<箱号>/xxx.jpg`。同件货照片 = 同箱号目录 + 秒级~分钟级时间窗 + 连拍序号相邻。三条硬教训：
  ① `import_seq` 是文件扫描顺序、跨箱号跳跃，禁取「邻居」；按目录键建索引（carton_no > dirname(path)，import_standard_folder 的 file 列只有 basename，靠它判目录=全库同目录）。
  ② 时间窗按文件名形态分档，不看 `time_src` 列——App 命名也是 'filename' 但快门时刻可信（300s），微信命名/mtime 才放宽（1800s）。看秒差用 `time_trustworthy()`。
  ③ k 条上限必须在过滤之后；候选函数带 `anchor`（当前照片）。
- group_idx：import_standard_folder 曾写成自增序号（每张自成一组，连拍功能全死），已改导入后调 `regroup_photos_by_time`（目录强制切组）；改口径后清 `_cand_cache.json`（_cand_stamp 不含 group_idx 维度）。

## 工程铁律（App 端）
0. **进下一层必须 `context.push` 不能 `go`**：go 是替换栈，系统返回直接退 App；返回按钮 `canPop ? pop : go` 兜底。
0b. 交付记录在 `deliveries` 表；「历史交付包」读 `DeliveryRepository.recentByProject`，多卷从文件名 `_第NN卷-共MM卷.zip` 还原；drift 行不外泄 UI（domain/export/delivery_history.dart 纯模型）。
0c. **交付默认不压缩**（ExportOptions.compressPhotos=false，2026-10-20 老板拍板）；改默认值要扫所有相关测试——靠默认值走目标路径的用例会假绿。
1. UI 禁 import data/；采集 NewPhoto 无归属；服务不持 BuildContext。
2. drift：时间 int 毫秒；改表先 build_runner；迁移幂等（PRAGMA 探测）。
3. 拍照流水线：`_capturing` 只锁取帧，落盘/入库走 core/serial_queue.dart；dispose 前 `await _sink.drain()`；失败走 CaptureService.errorStream 禁静默。
4. confirmGroup 先写 assignments 再改 itemId；Value.absent()=跳列、Value(null)=清空。
5. 「按下瞬间干事」用 Listener.onPointerDown（onTapDown 被手势竞技场吞）。
6. 改 Kotlin 先 `gradlew :app:compileReleaseKotlin`；发版中断续跑 `-Bump none`。
7. 性能：批量 IN(...) 分批400；缩略图原生 PerfBridge；写原图走 isolate；build() 禁同步 IO。
8. MediaStore 列名下划线前缀（`_display_name`）；分桶禁 GROUP BY；**selection 禁 SQL 表达式/函数**（真机成功返回却 0 行，v0.21.1）——过滤一律 cursor 遍历内存做，selection 只许「裸列 = ? AND」。

## productlib 铁律（Web 端）
- store.py 唯一写入口；路径唯一真源 paths.py；打包 build_portable.py --clean。
- **数字同源**：统计/徽章与列表共用同一 SQL；慢聚合绝不挂列表主查询。
- **facet 计数必须排除自身维度**（2026-10-19）：同一份 WHERE 同时 GROUP BY 用途和分类 → 选了 A 后 A 维度只剩 A 一项，树上其他项消失。数用途只带 kind、数分类只带 usage。
- **async 里 TypeError 是静默的**：rejected promise 不触发 CDP exceptionThrown，表现「列表空、无报错」；结构改字段必须全局搜引用点，取值防御式 `(x || []).length`。
- 柜号解析：container_id→containers.container_no 权威 + batches.container_no 老库兜底；两路命中取 max 不相加。
- 路由：字面量端点排在 `{pid}`/`{cid}` 前；新端点登记 checks/routes.py。
- **部类双口径坑**（v0.22.2）：预检墙查「组」、监装墙查「照片行」——改部类必须组+行同步改（setGroupCategory 事务两写）；改回预检还要摘组（group_id=null）。
- 测试：不写真实库；造 UI 数据必须真生成 jpg；别断言「各柜之和==总数」；**入库按内容 hash 去重——同色 PIL 图只进 1 张，段数/张数断言会假绿**。
- **testWidgets 三坑**：① FakeAsync 不 flush 真实事件循环——IO/drift await 必须包 `tester.runAsync`；② `overrideWithValue` 在 pumpWidget 时封对象，fake 要同对象改内容；③ mock makeThumbs 必须真写非空目标文件。
- **readonly database 报错先探可写性**：强杀 8765 后立刻重启，WAL 恢复窗口首条写报一次 readonly，等几秒即恢复；真只读才持续 500。
- ESM/CDP：静态检查抓不到运行期环 import，必跑 cdp_regress；CDP 打 8765=旧进程假绿，用 PL_PORT 隔离实例。ES module 函数不挂 window，Runtime.evaluate 调用抛 ReferenceError 且被忽略。
- 报告分页每页 6 张（2×3）；**纸型必须显式设 A4**（python-docx 默认 Letter，10-11 事故）。
- 选图（④）：picks 新格式 {codes, trucks, conds}；trucks 缺键=自动、[]=明确留空。
- **柜作业时长**：按 `(batch_id, group_idx)` 作业段算，绝不取全柜 MIN/MAX(taken_at)（EMCU 跨 334h 实为多次作业）；净时长=段区间并集长度；零散判据只看宽段（单段>12h）。文案口径 core.js 的 fmtDur/workRange/workDur。
- 命名：产品库/照片库/柜作业；`标准产品库` 是真实目录名永别改。
- **编码检索**：现场记编码是后几位/中间几位，matchKind 分级 精确>后缀>前缀>包含；匹配在 Dart 侧做，零迁移；归一只在 domain/search/code_norm.dart；最近搜索 SP 10 条。
- **待关联口径**：「只有产品需要关联」——只有产品图（label=0201/product=0202）进待关联；真源 schema.LINKABLE_KINDS 白名单 + usage<>'监装'；八处同源（_UNLINKED_SQL 列表/徽章/树/箱号/工作台/stats/discovered/merge + _cand_filter_sql + pipeline）；UI 显示「待关联」不是「未关联」；未识别（kind=NULL）不进队列。
- 现场升级双击 `升级助手.cmd`。
- **编码形态**：真实库 399/400 是数字+字母混合（2030BG0000098），`_LOOKS_CODE_RE`=`^[1-9][0-9A-Z]{7,17}$`（store/vision 同步）；OCR 读出的前缀（PN:）统一走 `store.strip_code_prefix` 剥。
- **photo_ignored 列 ≠ is_invalid**：忽略只退本次关联队列，后续柜 relink 仍捞回；改队列口径时 _UNLINKED_SQL/_cand_filter_sql/discovered A/B 四处带 `IFNULL(photo_ignored,0)=0`，_cand_stamp/_np_stamp 缓存戳必须含忽略维度；set_photo_ignored 幂等要先查后改。
- 照片库选项卡：全部/已关联/待关联/已忽略/无效图片。
- **分类体系**：photo_usage 01 监装/02 预检/03 其他 → photo_kind 0201–0205 / supervision_tag 0101–0107；键是存储口径永不变，改只改显示文案（core.js KIND_LABELS + drawer.js SUPTAGS）；**编号不上 UI**。
- **性能缓存**：cand_code_map 内存 TTL + 落盘 `_cand_cache.json`，内容戳带逻辑版本号 + photo_usage 维度 + threading 锁；invalidate 同步清盘。预览图慢主成本是 PIL thumbnail 解码大图。
- CSS 陷阱：flex 容器包 img 会裂开——容器高度跟着受限图片走就用 `display:block;line-height:0` + img `margin:0 auto`，改前用 CDP 量盒模型。

## App 端系统相机拍照收图（v0.24.17+ v2 架构，feat/system-camera-v2）
- **v2 = 同步契约 + 拉模式**（12~16 的「返回即回 App + native→Dart 反向推送」连续四版真机翻车后推倒重来）：launchSession 相机返回后同步收首批（≤2s）随结果返回；晚到照片 Dart 每 700ms 调 collectLate 拉差集（changed=true 走修复重拷）；连续 3 空轮且 ≥5s 或 30s 上限收口；endCollect 释放上下文（120s 自清兜底）。**无推送、无会话状态机、无广播流**；结局 missed（大概率拍了但 0 收到，必须明说）。
- **媒体库来源免 EOI（v0.24.18）**：IS_PENDING=0 就是 OS 的「已写完」信号；EOI 末 16 字节窗会把「EOI 后带私有数据段」（三星 SEF 尾巴）的 JPEG **永久否决**（真机实锤：快照 1 张连续 4 轮 usable=0）。fs 来源保留 EOI 但尾窗 512 字节。交早了有 changed 修复兜底——**宽容比误杀安全**。
- **collectLate 差集必须含媒体库增量**，不能只看 fs 扫描（相机写到没扫到的目录时晚到永远收不到）。
- **onActivityResult 对称分支的清理必须成对审查（v0.24.18）**：会话分支漏清 pendingResult → 首场之后所有 launch/launchSession 永远 ALREADY_RUNNING，「拍照按钮永远进不去」且 Dart 降级单张也死。
- diag 三数口径「媒体库 可用/快照/fs」+ EOI 豁免张数，随 launchSession/recoverSession 回传落「关于」面板——现场排障截图即可定位。
- ingest：move:false、galleryMirror:false；一次性服务 dispose(awaitDerived:false)；并发上限 3 且前置 startSession（5min resumable = 一批一组）。
- **进程被杀恢复**：收图三要素写原生 SP("syscam_pending")，启动 recoverSession 全量重收，DB 账本 system_capture_shots 按 source_path 过滤防重复。
- **native→Dart 反向 invoke 必须主线程**（v0.24.13 教训，v2 已无推送通道但规则仍在）：FlutterJNI.dispatchPlatformMessage 有 ensureRunningOnMainThread 硬断言；线程前提要落到引擎源码，不能信注释。
- **卓易通（鸿蒙 NEXT 兼容层）不受支持**：相机桥写不进 App 私有目录；现场取证用普通 Android 手机。
- Kotlin 坑：跨线程上下文先捕获成局部变量再清字段；`map[k]?["x"]` 非法（用 .get()）；`val x = try { if (c) continue } catch` 报「if 缺 else」。

## 版本管理
- tools/release.ps1 -Bump（内部已调 run_unsandboxed，外面别再包）；六道门禁；签名密钥不入库。
- **release 中止后重发先回滚 pubspec 到上一版**（中止前已改写，直接重跑会跳号）。
- **构建必须在版本号写入之后**：先手改 pubspec → 构建 → release.ps1 `-Bump none` → 手动归档 APK。先 build 后发版=APK 内部还是旧版本号（踩两次）。
- **-CommitPaths 别用宽目录**；提交前核对 `git diff --cached --name-only`。
- run_unsandboxed 等待逻辑=轮询 OutFile 里任务自写的 `EXIT=` 行；禁用「大小稳定+任务状态」启发式（flutter test 有 224s 静默段会误判）。**计划任务名固定，两个并行调用互相覆盖输出丢失——只能串行。**
- **长任务一律 `run_in_background: true`**：前台跑全量 flutter test 会被 `^C` 杀；PowerShell 工具跑 release.ps1 会被 600s 回收——要么后台，要么门禁手动跑完后 `-SkipGates -SkipBuild` 续跑。
- tag：App 端 v0.x，productlib 用 pl-v 前缀。
- 打包版验证铁律：源码测试全绿 ≠ 打包版能跑；现场发版必须实测打包版。
