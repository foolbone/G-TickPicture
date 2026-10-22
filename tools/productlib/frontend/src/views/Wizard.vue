<template>
  <div class="wizard-page">
    <!-- 脏柜锚点的持久提示：不能只靠 toast —— 自愈会清空锚点触发递归
         loadProgress 把提示冲掉，而 toast 几秒就没了。提示要具体到可操作。 -->
    <el-alert v-if="wiz.anchorWarn" type="warning" :closable="true" class="anchor-warn"
              :title="wiz.anchorWarn" @close="wiz.anchorWarn = ''" />

    <el-card shadow="never">
      <template #header>
        <!-- 顶栏对标旧版（老板 2026-10-19 给了旧版截图）：
             ←柜列表(描边按钮) │ 柜作业(无框标签) │ ①..⑤ 胶囊(编号+名称+摘要)
             │ …… │ [柜号 · N 行] │ 就绪 x%
             逐项对齐：① 编号用 ① **字形本身**（自带圆圈，旧版就是纯文字，
             新版之前多套了一层圆底 → 变成双圈，看着重）；
             ② 胶囊全圆角 pill、13px、padding 4px 12px；
             ③ 步骤之间有短横分隔（新版之前去掉了）；
             ④ 下拉选项带「· N 行」（口径同旧版 containers.js）；
             ⑤ 完成=淡绿整颗+绿编号、当前=白底蓝框蓝字、被挡=淡显。 -->
        <div class="wiz-head">
          <!-- 双视图模式下由柜页显示；独立 /app/wizard 路由时自己跳回柜页 -->
          <el-button v-if="showBack" size="small" @click="$emit('back-to-list')">
            ← 柜列表
          </el-button>
          <el-button v-else size="small" @click="$router.push('/containers')">← 柜列表</el-button>
          <span class="wizttl">柜作业</span>
          <!-- 步骤条：状态派生自后端 progress，不落 localStorage 记账 -->
          <div class="wstepbar">
            <template v-for="(key, i) in STEPS" :key="key">
              <div class="wstep" :class="stepCls(key)" @click="goto(key)"
                   :title="META[key].name + '：' + stepState(key).summary">
                <span class="wn">{{ META[key].n }}</span>
                <span class="wt">{{ META[key].name }}</span>
                <span class="ws">{{ stepState(key).summary }}</span>
              </div>
              <div v-if="i < STEPS.length - 1" class="wsep"></div>
            </template>
          </div>
          <span class="spacer"></span>
          <el-select :model-value="cid" placeholder="选择柜…" filterable size="small"
                     class="wiz-cid" title="当前柜 —— 切换它，下面五步整套换成这个柜的作业"
                     @change="onSwitchCid">
            <!-- 下拉文案与旧版一致：柜号 · 清单行数（无行数就不加尾巴） -->
            <el-option v-for="c in opts.containers" :key="c.id" :value="c.id"
                       :label="(c.container_no || '（未分柜）')
                         + (c.checklist_rows ? ' · ' + c.checklist_rows + ' 行' : '')" />
          </el-select>
          <span class="pill">{{ pct }}</span>
        </div>
      </template>

      <!-- 未选柜 -->
      <el-empty v-if="!cid" description="先建一个柜（或选一个已有柜），全流程都挂在它下面">
        <el-button type="primary" @click="newVisible = true">＋ 新建柜</el-button>
        <el-button @click="switching = true">选择已有柜</el-button>
      </el-empty>

      <!-- 读不到进度：「还没查完」不等于「没问题」—— 渲染成错误态 + 重试 -->
      <div v-else-if="!wiz.prog" class="wcard err">
        <div class="whead"><b>读不到向导进度</b></div>
        <div class="faint">{{ wiz.loadErr || '读取中…' }}</div>
        <div class="row" style="margin-top:12px">
          <el-button size="small" @click="reload">重试</el-button>
          <el-button size="small" text @click="switching = true">换个柜</el-button>
        </div>
      </div>

      <!-- 当前步：标题、说明、状态摘要**并成一行**（原来是三块竖排，
           占掉三四行高度，真正要操作的区域被挤到屏幕下方）。
           说明文字超宽就省略号截断（全文挂 title，鼠标悬停可见）。 -->
      <div v-else class="wcard">
        <!-- 治理抽屉（2026-10-21）：由 Wizard 直接持有 —— 放进 StepPhotos 里用
             prop 传 v-model 时点击打不开（DOM 在但宽高 0）。 -->
        <el-drawer v-model="govOpen" title="照片治理（分类 → 读码 → 关联）"
                   size="min(620px, 92vw)" direction="rtl">
          <GovPanel v-if="govOpen" :cid="cid" @done="onPhotosChanged" />
        </el-drawer>
        <div class="whead" :title="META[active].desc">
          <span class="wnum">{{ META[active].n }}</span>
          <b class="wtitle">{{ META[active].name }}</b>
          <el-tag v-if="stepState(active).done" type="success" size="small">已完成</el-tag>
          <el-tag v-else size="small">待办</el-tag>
          <span class="wdesc">{{ META[active].desc }}</span>
          <span class="wstatus">
            <template v-if="active === 'container'">
              <el-tag v-if="missingMeta.length" type="warning" size="small">
                缺：{{ missingMeta.map((m) => META_LABELS[m] || m).join('、') }}
              </el-tag>
              <el-tag v-else type="success" size="small">柜信息完整</el-tag>
            </template>
            <template v-else-if="active === 'checklist'">
              <el-tag size="small">清单行 {{ S.checklist.row_total }}</el-tag>
              <el-tag v-if="S.checklist.row_unchecked" type="warning" size="small">
                未核对 {{ S.checklist.row_unchecked }}
              </el-tag>
              <el-tag v-else type="success" size="small">已核对</el-tag>
              <span class="faint">批次 {{ S.checklist.batches }}</span>
            </template>
            <template v-else-if="active === 'photos'">
              <el-tag size="small">照片 {{ S.photos.total }} 张</el-tag>
              <span class="faint">批次 {{ S.photos.batches }} · 监装 {{ S.photos.supervision }}</span>
              <el-tag :type="S.govern.done ? 'success' : 'info'" size="small">
                已治理 {{ S.govern.done_cnt }}/{{ S.govern.total }}</el-tag>
              <el-tag v-if="S.govern.pending" type="warning" size="small">待治理 {{ S.govern.pending }}</el-tag>
              <el-tag v-if="S.govern.failed" type="danger" size="small">失败 {{ S.govern.failed }}</el-tag>
              <span class="faint">已关联 {{ S.govern.linked }}</span>
            </template>
            <template v-else-if="active === 'picks'">
              <el-tag v-if="pickCount()" type="success" size="small">已选 {{ pickCount() }} 张</el-tag>
              <span v-else class="faint">未选 —— 可跳过，报告会按编码自动取图</span>
              <el-tag v-if="pickStats && pickStats.codes_total"
                      :type="pickStats.missing ? 'warning' : 'success'" size="small">
                命中 {{ pickStats.with_photo }}/{{ pickStats.codes_total }}（{{ pickStats.hit_rate }}%）· 缺口 {{ pickStats.missing }}
              </el-tag>
            </template>
            <template v-else-if="active === 'report'">
              <el-tag size="small">{{ S.report.summary }}</el-tag>
            </template>
            </span>
          <!-- 2026-10-20 老板：步骤操作钮全部并进标题行末尾（导入照片 / 治理 / 资产库），
               原来要么散落在内容区上方、要么没有，白占一整行高度。 -->
          <span v-if="active === 'photos'" class="wbtns">
            <el-button size="small" @click="govOpen = true" type="warning"
                       title="照片治理（分类 → 读码 → 关联），点开右侧抽屉">照片治理</el-button>
            <el-button size="small" type="primary" @click="impPhVisible = true">＋ 导入照片</el-button>
          </span>
        </div>

        <div class="wdetail">
          <StepContainer v-if="active === 'container'" ref="stepContainer"
                         :detail="detail" :cid="cid" @saved="reload" />
          <StepChecklist v-else-if="active === 'checklist'" ref="stepChecklist"
                         :detail="detail" :cid="cid"
                         @dirty-change="clDirty = $event" @saved="reload" />
          <StepPhotos v-else-if="active === 'photos'" ref="stepPhotos" :cid="cid"
                      @changed="onPhotosChanged" />
          <StepPicks v-else-if="active === 'picks'" ref="stepPicks" :cid="cid"
                     :stats="pickStats" @picked="onPicked" />
          <StepReport v-else ref="stepReport" :cid="cid" :container-no="detail.container_no"
                      @generated="reload" />
        </div>

        <div class="wactions">
          <!-- 2026-10-21 老板：①建柜步骤底部的「新建柜/切换柜/最近柜」整行删掉
               （新建柜走柜列表入口，切换柜走右上角下拉）；
               ③照片步骤底部的「导入照片/查看资产」也删掉（顶部已有）。 -->
          <template v-if="active === 'checklist'">
            <el-button type="primary" @click="impClVisible = true">选择 Excel 导入</el-button>
            <el-button size="small" tag="a" href="/api/products/template" target="_blank">下载模板</el-button>
            <div class="revlink"><a href="#" @click.prevent="$router.push('/products')">查看资产 → 产品库</a></div>
          </template>
          <template v-else-if="active === 'picks'">
            <el-button v-if="S.checklist.row_total === 0" disabled type="primary">先完成②导入清单</el-button>
            <el-button v-else @click="relookup">重新检索</el-button>
            <div class="revlink"><a href="#" @click.prevent="$router.push('/products')">查看资产 → 产品库</a></div>
          </template>
          <template v-else-if="active === 'report'">
            <el-button v-if="!canGen" disabled type="primary">{{ genReason }}</el-button>
            <el-button v-else type="primary" @click="doGen">生成 docx</el-button>
            <div class="revlink"><a href="#" @click.prevent="$router.push('/report')">查看资产 → 报告档案</a></div>
          </template>
        </div>
      </div>
    </el-card>

    <!-- 建柜 -->
    <el-dialog v-model="newVisible" title="新建柜" width="520px">
      <div v-if="prefillHint" class="faint" style="margin-bottom:8px">{{ prefillHint }}</div>
      <el-form label-width="90px">
        <el-form-item label="柜号 *" required>
          <el-input v-model="nc.container_no" placeholder="如 EMCU9914616" maxlength="40" />
        </el-form-item>
        <el-form-item label="封条号">
          <el-input v-model="nc.seal_no" placeholder="可后补，会进报告 General Information" />
        </el-form-item>
        <el-form-item v-for="[k, lb] in PREFILL" :key="k" :label="lb">
          <el-input v-model="nc[k]" :placeholder="recentVals[k] || '可后补'" />
        </el-form-item>
        <el-form-item label="到柜时间">
          <el-input v-model="nc.arrival_at" placeholder="2026-09-27 09:12" />
        </el-form-item>
        <el-form-item label="离柜时间">
          <el-input v-model="nc.departure_at" placeholder="2026-09-27 18:40" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createContainer">创建</el-button>
      </template>
    </el-dialog>

    <!-- 导入清单（与产品库页共用一份实现） -->
    <ImportChecklistDialog v-model="impClVisible" @done="reload" />

    <!-- 导入照片（与照片库页共用一份实现） -->
    <ImportPhotosDialog v-model="impPhVisible" :cid="cid" @done="reload" />
  </div>
</template>

<script setup>
/* Wizard.vue —— 柜作业五步的壳（①建柜 ②清单 ③照片 ④选图 ⑤报告）
 *
 * 状态**派生自后端** /api/containers/{cid}/progress，不落 localStorage 记账 ——
 * 关掉浏览器回来还是那一步。④选图是唯一的客户端步骤，可跳过。
 *
 * 本轮迁移了 ①②⑤（依赖少、可完整交付），③照片 与 ④选图 给旧版入口：
 * 两步耦合治理面板 / 箱号分组 / 清理弹窗 / 检索策略，拆开做不如一起做。
 * 旧版整站仍可用，同库同接口，来回切无缝隙。
 *
 * ⚠️ 离开拦截：①柜信息 与 ②清单 是可编辑的，有未保存改动时切步骤要拦一下
 *   （旧版遍历 DOM 数改动，Vue 下改成子组件 expose dirtyCount —— 两套真源会漂）。 */
import { ref, reactive, computed, watch, onMounted, nextTick, defineExpose } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, post } from '../api.js'
import {
  opts, anchor, bus, loadContainerOptions, loadAllOptions,
} from '../lib/photosStore.js'
import {
  wiz, STEPS, META, stepState, defaultActive, loadProgress,
  resetForContainer, pickCount,
} from '../lib/wizardStore.js'
import StepContainer from '../components/wizard/StepContainer.vue'
import StepChecklist from '../components/wizard/StepChecklist.vue'
import StepPhotos from '../components/wizard/StepPhotos.vue'
import StepPicks from '../components/wizard/StepPicks.vue'
import StepReport from '../components/wizard/StepReport.vue'
import GovPanel from '../components/wizard/GovPanel.vue'
import ImportPhotosDialog from '../components/ImportPhotosDialog.vue'
import ImportChecklistDialog from '../components/ImportChecklistDialog.vue'

const META_LABELS = { seal_no: '封条号', inspector: 'Inspector', client_name: '客户', location: 'Location' }
const PREFILL = [['client_name', '客户'], ['inspector', 'Inspector'], ['location', 'Location']]
/* 可以带入上次取值的「不常变」字段。
 * ⚠️ 柜号 / 封条号 / 到离柜时间**绝不在内** —— 每次必变，自动带入就是替用户猜。 */

const stepContainer = ref(null)
const stepChecklist = ref(null)
const stepPhotos = ref(null)
const stepPicks = ref(null)
const stepReport = ref(null)
const clDirty = ref(0)
const recent = ref([])
const recentVals = reactive({})
const switching = ref(false)
const newVisible = ref(false)
const creating = ref(false)
const impClVisible = ref(false)
const impPhVisible = ref(false)
/* 治理抽屉（2026-10-20 老板）：治理面板不再占③内容区，改成右侧抽屉，
   由标题行「照片治理」按钮呼出。 */
const govOpen = ref(false)
const nc = reactive({
  container_no: '', seal_no: '', client_name: '', inspector: '',
  location: '', arrival_at: '', departure_at: '',
})
const prefillHint = ref('')

const cid = computed(() => anchor.cid)
const active = computed(() => wiz.active)
const detail = computed(() => wiz.detail || {})
const S = computed(() => (wiz.prog ? wiz.prog.steps : {}))
const pct = computed(() => (wiz.prog ? '就绪 ' + wiz.prog.ready_pct + '%' : '未选柜'))
const missingMeta = computed(() => (S.value.container && S.value.container.meta_missing) || [])
const pickStats = computed(() =>
  (S.value.picks && S.value.picks.stats) || null)
const canGen = computed(() => S.value.checklist.row_total > 0 && S.value.photos.total > 0)
const genReason = computed(() => {
  const c = S.value.checklist.row_total, p = S.value.photos.total
  if (c === 0 && p === 0) return '先完成②导入清单、③导入照片'
  if (c === 0) return '先完成②导入清单（报告要有 Packing list）'
  if (p === 0) return '先完成③导入照片（报告⑥要有图）'
  return '还不能生成'
})

function stepCls(key) {
  const s = stepState(key)
  const state = s.blocked ? 'blocked' : (s.done ? 'done' : (wiz.active === key ? 'current' : 'todo'))
  return [state, wiz.active === key ? 'cur' : '']
}

/** 未保存改动处数（①表单 + ②表格）。 */
function dirtyCount() {
  const a = stepContainer.value ? stepContainer.value.dirtyCount : 0
  return a + (clDirty.value || 0)
}

async function confirmLeave() {
  const n = dirtyCount()
  if (!n) return true
  try {
    await ElMessageBox.confirm(
      '有未保存的修改（' + n + ' 处）。\n\n离开将丢失这些修改，确定吗？',
      '未保存的修改', { type: 'warning', confirmButtonText: '确定离开', cancelButtonText: '继续编辑' })
    return true
  } catch {
    return false
  }
}

async function goto(key) {
  if (key === wiz.active) return
  if (!(await confirmLeave())) return
  wiz.active = key
  try { localStorage.setItem('plStep', key) } catch { /* 隐私模式 */ }
  await nextTick()
}

async function reload() { await loadProgress(false) }

async function onSwitchCid(id) {
  if (id === cid.value) return
  if (!(await confirmLeave())) { switching.value = false; return }
  anchor.setCid(id)
}

/** 换柜：先等确认通过再改锚点，避免把「已取消」也写进去。 */
async function switchTo(id) {
  if (id === cid.value) return
  if (!(await confirmLeave())) return
  anchor.setCid(id)
}

/* 锚点变化 → 重置柜相关状态 + 重拉（④的编码池/检索结果/监装候选都是柜的） */
let offCid = null
onMounted(async () => {
  offCid = anchor.onChange(() => {
    resetForContainer()
    loadProgress(false)
  })
  await loadAllOptions()
  /* 无柜时自动选第一个（2026-10-19 老板实测「柜作业直接进不起作用」）：
     侧栏「柜作业（直接进）」落到 /app/wizard，localStorage 没存过 cid 就是
     空态「先建一个柜」—— 老板的体感是「点了没反应」。库里明明有柜，
     直接进就该落在最近/第一个柜上，空态只留给「库里真没有柜」。 */
  if (!anchor.cid) {
    // opts.containers 已由 loadContainerOptions 滤掉未分柜，直接取第一个
    const first = (opts.containers || [])[0]
    if (first) anchor.setCid(first.id)
  }
  await loadProgress(false)
  /* 深链：/app/wizard?step=photos 或 localStorage 里的上次步骤 */
  const q = new URLSearchParams(location.search).get('step')
  const saved = (() => { try { return localStorage.getItem('plStep') } catch { return '' } })()
  if (q && STEPS.includes(q)) wiz.active = q
  else if (saved && STEPS.includes(saved)) wiz.active = saved
  else wiz.active = defaultActive()
  await loadProgress(false)
  loadRecent()
})

async function loadRecent() {
  try {
    const d = await api('/api/containers')
    recent.value = (d.items || []).filter((c) => c.container_no !== '_UNCATEGORIZED').slice(0, 5)
  } catch { recent.value = [] }
}

/* 建柜：预填「不常变」字段，提示只列真正填上的（说「已带入客户」而实际只带了
   客户是句假话）。取不到预填值也不能挡住建柜 —— 拿不到就按空处理。 */
watch(newVisible, async (on) => {
  if (!on) return
  let d = { last: {}, recent: {} }
  try { d = await api('/api/containers/form-defaults') } catch { /* 按空处理 */ }
  const last = d.last || {}, rec = d.recent || {}
  Object.keys(nc).forEach((k) => { nc[k] = '' })
  PREFILL.forEach(([k]) => {
    nc[k] = last[k] || ''
    if (rec[k] && rec[k].length) recentVals[k] = rec[k][0]
  })
  const filled = PREFILL.filter((f) => ((last[f[0]] || '') + '').trim())
  prefillHint.value = (d.from_container && filled.length)
    ? '已带入上次建柜（' + d.from_container + '）的 ' + filled.map((f) => f[1]).join(' / ') + '，可修改'
    : ''
})

async function createContainer() {
  const no = (nc.container_no || '').trim()
  if (!no) { ElMessage.warning('柜号不能为空'); return }
  creating.value = true
  try {
    const c = await post('/api/containers', {
      container_no: no,
      seal_no: nc.seal_no.trim() || null,
      client_name: nc.client_name.trim() || null,
      inspector: nc.inspector.trim() || null,
      location: nc.location.trim() || null,
      arrival_at: nc.arrival_at.trim() || null,
      departure_at: nc.departure_at.trim() || null,
    })
    ElMessage.success('柜已创建：' + c.container_no)
    newVisible.value = false
    await loadContainerOptions()
    anchor.setCid(c.id)          // 建完自动设为当前柜，广播给全站
  } catch (e) {
    ElMessage.error('创建失败：' + e.message)
  } finally {
    creating.value = false
  }
}

async function doGen() { if (stepReport.value) await stepReport.value.gen() }
function relookup() {
  if (stepPicks.value) stepPicks.value.reload()
}

/* ③里改了照片（标记无效 / 改判分类 / 导入）→ 步骤条摘要要跟着变，
   但**不跳步**：advance 语义会把③推到④（治理还没跑就带走老板）。 */
function onPhotosChanged() { loadProgress(false) }

/* ④采用/取消选图 → 只刷步骤条「已选 N 张」摘要。 */
function onPicked() { loadProgress(false) }

/* 抽屉里关联 / 改判分类后广播 photos:changed —— 刷进度摘要，不跳步。 */
bus.on('photos:changed', () => { loadProgress(false) })

watch(cid, () => { loadRecent() })

/* 柜页把柜作业做成同页第二视图（对齐旧版 ctListView/ctWizView）——
   切回列表前要问一次「有未保存改动吗」，复用页内那份 dirtyCount 口径。 */
defineExpose({ confirmLeave, dirtyCount })
defineProps({ showBack: { type: Boolean, default: false } })
defineEmits(['back-to-list'])
</script>

<style scoped>
.wizard-page { max-width: 100%; margin: 0 auto; }
/* 标题栏压低（2026-10-21 老板标注「降低这行高度，把空间留给下方图片区域」）：
   el-card 的 header 默认 18px 上下内边距 → 6px，一行少约 24px。
   卡片本体（内容区）内边距不动 —— 那是照片区的可用宽度。 */
.wizard-page :deep(.el-card__header) { padding: 6px 12px; }
.wdetail { border-top: 1px dashed var(--pl-line); padding-top: 12px; }
.anchor-warn { margin-bottom: 10px; }
/* 顶栏**逐项对标旧版**（web/static/app.css .wizbar/.wstepbar/.wstep，
   老板 2026-10-19 直接给了旧版截图）：一行不折、13px、全圆角 pill、
   步骤间短横分隔、编号用 ① 字形本身、摘要灰色跟在名称后。 */
.wiz-head {
  display: flex; align-items: center; gap: 6px;
  flex-wrap: nowrap; min-width: 0;
}
/* 「柜作业」是无框标签（旧版 .wizttl），不是按钮 —— 它只是说明这块是什么 */
.wizttl {
  font-size: 13px; font-weight: 600; color: var(--pl-muted);
  white-space: nowrap; flex: none;
}
.wiz-cid { width: 230px; flex: none; }
/* 就绪度胶囊：旧版是全圆角的浅灰底小胶囊（2026-10-21 竖向 padding 收窄） */
.pill {
  font-size: 12px; background: var(--pl-line-2); color: var(--pl-muted);
  border-radius: 999px; padding: 2px 10px; white-space: nowrap; flex: none;
}
.wstepbar { display: flex; align-items: center; gap: 5px; flex: 0 1 auto; min-width: 0; }
/* 步骤胶囊竖向 padding 4px → 2px：13px 字号不变（旧版对标不能动），
   只把胶囊本身压扁 */
.wstep {
  display: flex; align-items: center; gap: 6px; padding: 2px 9px;
  border-radius: 999px; cursor: pointer;
  border: 1px solid var(--pl-line); background: var(--pl-panel-2);
  font-size: 13px; white-space: nowrap; user-select: none;
  transition: border-color .15s, background .15s;
  /* 名字与编号不许压缩，只有摘要可省略号让位（老版 flex-wrap 会整条折行，
     这里改成「一行内压缩」—— 老板明确要求所有内容处于一行）。 */
  flex: 0 1 auto; min-width: 0;
}
.wstep:hover { border-color: var(--pl-brand); }
/* 完成态是淡绿整颗 + 绿编号；当前步白底蓝框蓝字；被前置步骤挡住淡显 */
.wstep.done { background: var(--pl-ok-soft); border-color: #a7e8bd; }
.wstep.cur {
  background: var(--pl-panel); border-color: var(--pl-brand);
  box-shadow: 0 0 0 2px var(--pl-brand-soft);
}
.wstep.cur .wn, .wstep.cur .wt { color: var(--pl-brand); }
.wstep.blocked { opacity: .5; }
/* ⚠️ 编号是 ① ② ③ 字形本身，**自带圆圈** —— 不要再套一层圆底，
   否则变成「圈内还有一圈」，比旧版重得多（这正是之前看着不如旧版的原因之一）。 */
.wn { font-weight: 700; color: var(--pl-muted); flex: none; }
.wt { font-weight: 600; flex: none; }
/* 摘要可省略号让位，编号/名称永远完整；截断时 title 上有全文 */
.ws {
  color: var(--pl-faint); min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.wsep { flex: 0 0 9px; height: 1px; background: var(--pl-line); align-self: center; }

.wcard { padding: 4px 2px; }
.wcard.err { border: 1px solid var(--pl-err); border-radius: 8px; padding: 14px; }
/* 步骤头部：编号 + 名称 + 状态 + 说明 + 数据摘要 全部并到一条横向流。
   2026-10-21 老板：「③照片 · 待办 · 说明文字」这行太高 ——
   ① 强制 nowrap（原来 flex-wrap 在窄屏把摘要折成第二行，整行翻倍到 ~72px）；
   ② 编号 24→20px、标题 15→14px、外间距 6/4 → 2/0。 */
.whead { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap;
  margin-bottom: 2px; padding-bottom: 0; }
.wtitle { font-size: 14px; flex: none; }
/* 编号是淡蓝圆底，不是裸文字 —— 原来只有个「③」，标题行看着像缺了什么 */
.wnum {
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--pl-brand-soft); color: var(--pl-brand);
  font-size: 12px; font-weight: 700;
  display: flex; align-items: center; justify-content: center; flex: none;
}
/* 说明文字：单行 + 省略号（全文在 whead 的 title 上）。原来独占一整行、
   还常常折行，白占两三行高度只为说一句话。 */
.wdesc {
  font-size: 12px; color: var(--pl-muted); min-width: 0;
  flex: 0 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* 数据摘要：跟在说明后面同一行，不再单独占一块带边框的灰底。
   nowrap + min-width:0 —— 窄屏让摘要自己压缩省略，不许把整行顶成两行 */
.wstatus { display: flex; align-items: center; gap: 6px; flex-wrap: nowrap;
  min-width: 0; overflow: hidden; }
/* 2026-10-21：标题行与内容区之间的分隔留白 12 → 6px，一并还给图片区 */
.wdetail { border-top: 1px dashed var(--pl-line); padding-top: 6px;
  flex: 1; min-height: 0; display: flex; flex-direction: column; }
/* 步骤操作按钮推到标题行最右边。
   2026-10-21：默认按钮 32px 高把整行顶起来 —— 压到 26px（仍好点），
   标题行总高 36 → 26px 一档。 */
.wbtns { margin-left: auto; flex: none; display: flex; gap: 8px; }
.wbtns :deep(.el-button) { height: 26px; padding: 0 10px; font-size: 13px; }
.wactions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 14px;
  padding-top: 12px; border-top: 1px dashed var(--pl-line); }
.wrecent { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; width: 100%; }
.revlink { font-size: 12px; }
.wd-h { font-weight: 600; margin-bottom: 10px; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
