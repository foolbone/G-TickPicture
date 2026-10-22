<template>
  <div class="page-card ct-page">
    <!-- ① 柜列表视图 -->
    <template v-if="!wizView">
      <el-card shadow="never">
        <template #header>
          <div class="phead">
            <h2>柜<span class="sub">从柜进入「柜作业」—— 建柜 → 清单 → 照片 → 选图 → 报告，五步走完一柜</span></h2>
            <span class="spacer"></span>
            <el-button size="small" @click="load">刷新</el-button>
            <el-button size="small" type="primary" @click="newVisible = true">
              <el-icon><Plus /></el-icon><span>新建柜</span>
            </el-button>
          </div>
        </template>

        <!-- 筛选条：只改显示，不动数据；有独立底色与分隔线 -->
        <div class="toolbar">
          <el-input v-model="q" placeholder="搜柜号 / 封条号" clearable
                    style="width:200px" @keyup.enter="load" @clear="load" />
          <span class="faint">作业日期</span>
          <el-date-picker v-model="dateFrom" type="date" placeholder="从"
                          value-format="YYYY-MM-DD" style="width:140px" @change="load" />
          <span class="faint">至</span>
          <el-date-picker v-model="dateTo" type="date" placeholder="到"
                          value-format="YYYY-MM-DD" style="width:140px" @change="load" />
          <el-button v-if="hasFilter" size="small" text @click="clearFilter">清筛选</el-button>
          <span class="spacer"></span>
          <span class="faint">{{ countText }}</span>
        </div>

        <!-- 筛选结果标签行：条件可单独摘掉（点 × 只清那一个） -->
        <div v-if="chips.length" class="chips">
          <span class="faint">已按</span>
          <el-tag v-for="c in chips" :key="c.k" closable size="small" type="info"
                  @close="dropChip(c.k)">{{ c.t }}</el-tag>
        </div>

        <div v-loading="busy">
          <el-table :data="items" stripe
                    :default-sort="{ prop: 'container_no', order: 'ascending' }">
            <!-- 序号（2026-10-20 老板）：跟随当前排序与筛选，纯视觉定位用 -->
            <el-table-column type="index" label="序号" width="64" align="center" />
            <el-table-column prop="container_no" label="柜号" min-width="150">
              <template #default="{ row }">
                <a v-if="!row.is_uncategorized" class="clink" @click="enterWizard(row)">
                  {{ row.container_no }}
                </a>
                <span v-else class="faint">（未分柜）</span>
              </template>
            </el-table-column>
            <el-table-column prop="seal_no" label="封条号" min-width="110">
              <template #default="{ row }">
                <span :class="{ faint: !row.seal_no }">{{ row.seal_no || '未填' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="checklist_rows" label="清单行" width="90" align="right">
              <template #default="{ row }">
                <span :class="{ faint: !row.checklist_rows }">{{ row.checklist_rows || 0 }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="photos" label="照片" width="80" align="right">
              <template #default="{ row }">{{ row.photos || 0 }}</template>
            </el-table-column>
            <el-table-column prop="supervision" label="监装" width="80" align="right">
              <template #default="{ row }">{{ row.supervision || 0 }}</template>
            </el-table-column>
            <!-- 作业时长（2026-10-20）：起止 + 净作业时长。零散数据不给时长，
                 时间不可靠的挂个警示图标 —— 宁可少说，不能把拷贝耗时说成作业时长。 -->
            <el-table-column label="作业时长" min-width="240">
              <template #default="{ row }">
                <div v-if="row.work" class="wt">
                  <span class="wt-r">{{ workRange(row.work) }}</span>
                  <span class="wt-d">
                    {{ workDur(row.work) }}<template
                      v-if="!row.work.scattered"> · {{ row.work.segments }} 段</template>
                    <el-tooltip v-if="!row.work.trusted" placement="top"
                                content="这个柜的照片时间取自文件写入时刻，不是快门时刻 —— 时长可能只是拷贝耗时">
                      <el-icon class="wt-warn"><WarningFilled /></el-icon>
                    </el-tooltip>
                  </span>
                </div>
                <span v-else class="faint">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="190" fixed="right">
              <template #default="{ row }">
                <el-button v-if="!row.is_uncategorized" size="small" text @click="openDetail(row)">详情</el-button>
                <el-button v-if="!row.is_uncategorized" size="small" type="primary" plain
                           @click="enterWizard(row)">柜作业 →</el-button>
                <span v-else class="faint">—</span>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty :description="hasFilter ? '没有匹配的柜' : '还没有柜 —— 点右上「新建柜」开始'" />
            </template>
          </el-table>
        </div>
      </el-card>
    </template>

    <!-- ② 柜作业视图（同页第二视图，对齐旧版 ctWizView） -->
    <Wizard v-else ref="wizRef" :show-back="true" @back-to-list="exitWizard" />

    <!-- 建柜弹窗：挂在**两个视图之外**，在作业视图下也能建柜
         （旧版顶栏「＋ 新建柜」在作业视图里同样可用）。
         字段对照旧版 openContainerModal —— 封条/客户/Inspector/Location/到离柜时间，
         打开时从 form-defaults 预填上次取值，不常变字段带历史联想。 -->
    <el-dialog v-model="newVisible" title="新建柜" width="460px" @open="loadDefaults">
      <div v-if="prefillHint" class="prefill-hint faint">{{ prefillHint }}</div>
      <el-form label-width="84px">
        <el-form-item label="柜号" required>
          <el-input v-model="nc.container_no" placeholder="集装箱号，如 EMCU9914616" />
        </el-form-item>
        <el-form-item label="封条号">
          <el-input v-model="nc.seal_no" placeholder="Seal No." />
        </el-form-item>
        <el-form-item label="客户">
          <el-autocomplete v-model="nc.client_name" :fetch-suggestions="(q2, cb) => cb(sugg('client_name', q2))"
                           placeholder="可空，后补" clearable />
        </el-form-item>
        <el-form-item label="Inspector">
          <el-autocomplete v-model="nc.inspector" :fetch-suggestions="(q2, cb) => cb(sugg('inspector', q2))"
                           placeholder="可空，后补" clearable />
        </el-form-item>
        <el-form-item label="Location">
          <el-autocomplete v-model="nc.location" :fetch-suggestions="(q2, cb) => cb(sugg('location', q2))"
                           placeholder="可空，后补" clearable />
        </el-form-item>
        <el-form-item label="到柜时间">
          <el-input v-model="nc.arrival_at" placeholder="如 2026-09-27 09:12" />
        </el-form-item>
        <el-form-item label="离柜时间">
          <el-input v-model="nc.departure_at" placeholder="如 2026-09-27 18:40" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createContainer">创建</el-button>
      </template>
    </el-dialog>

    <!-- 柜详情抽屉：就绪度 / 柜况代表图 / 批次列表 / 清单行核对 -->
    <ContainerDetailDrawer v-if="detailCid" :cid="detailCid"
                           @close="detailCid = ''" @saved="load()"
                           @report="openReport" />
  </div>
</template>

<script setup>
/* Containers.vue —— 柜页：柜列表 + 柜作业**同页双视图**
 *
 * ⚠️ 信息架构对齐旧版（2026-10-08 老板要求「作业向导并进柜」）：
 * 五步（建柜→清单→照片→选图→报告）本来就都是一个柜的活，
 * 单独在导航占一项等于让人先猜「我该进哪个 tab 才能干活」。
 * 所以「柜作业」不是侧栏一级项，点柜号即进作业视图。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { Plus, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api, post } from '../api.js'
import { anchor } from '../lib/photosStore.js'
import { fmtDur, fmtTaken, workRange, workDur } from '../lib/core.js'
import Wizard from './Wizard.vue'
import ContainerDetailDrawer from '../components/ContainerDetailDrawer.vue'

const items = ref([])
const busy = ref(false)
const q = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const newVisible = ref(false)
const creating = ref(false)
const wizView = ref(false)
const wizRef = ref(null)
/* 柜详情抽屉 */
const detailCid = ref('')
/* 新建柜完整字段（对照旧版 openContainerModal：封条/客户/Inspector/Location/到离柜时间） */
const nc = ref({ container_no: '', seal_no: '', client_name: '', inspector: '', location: '',
  arrival_at: '', departure_at: '' })
const prefillHint = ref('')
/* 三个「不常变」字段的历史取值（form-defaults.recent，联想用） */
const recentVals = ref({ client_name: [], inspector: [], location: [] })

const hasFilter = computed(() => !!(q.value.trim() || dateFrom.value || dateTo.value))
const countText = computed(() => {
  if (!hasFilter.value) return '共 ' + items.value.length + ' 个柜'
  return '匹配 ' + items.value.length + ' 个柜'
})

/* 筛选标签行：把「当前按什么筛」显式摊开，每个都能单独摘掉。
   旧版筛选是「点了才生效且看不见条件」，这里改成常显可撤。 */
const chips = computed(() => {
  const out = []
  if (q.value.trim()) out.push({ k: 'q', t: '关键词：' + q.value.trim() })
  if (dateFrom.value) out.push({ k: 'from', t: '从 ' + dateFrom.value })
  if (dateTo.value) out.push({ k: 'to', t: '至 ' + dateTo.value })
  return out
})
function dropChip(k) {
  if (k === 'q') q.value = ''
  if (k === 'from') dateFrom.value = ''
  if (k === 'to') dateTo.value = ''
  load()
}
function clearFilter() {
  q.value = ''; dateFrom.value = ''; dateTo.value = ''
  load()
}

async function load() {
  busy.value = true
  try {
    const ps = new URLSearchParams()
    if (q.value.trim()) ps.set('q', q.value.trim())
    if (dateFrom.value) ps.set('date_from', dateFrom.value)
    if (dateTo.value) ps.set('date_to', dateTo.value)
    const s = ps.toString()
    const d = await api('/api/containers' + (s ? '?' + s : ''))
    items.value = d.items || []
  } finally {
    busy.value = false
  }
}

async function createContainer() {
  if (!nc.value.container_no.trim()) return
  creating.value = true
  try {
    const payload = { container_no: nc.value.container_no.trim() }
    for (const k of ['seal_no', 'client_name', 'inspector', 'location', 'arrival_at', 'departure_at'])
      payload[k] = (nc.value[k] || '').trim() || null
    const r = await post('/api/containers', payload)
    newVisible.value = false
    const no = nc.value.container_no.trim()
    nc.value.container_no = ''
    await load()
    ElMessage.success('已建柜 ' + no)
    /* 建完直接进作业 —— 旧版也是这个手势（ctNewGo 按钮），
       让人手动再点一次柜号是白走一趟。 */
    const c = items.value.find((x) => x.container_no === no)
    if (c) enterWizard(c)
  } finally {
    creating.value = false
  }
}

/* ── 建柜预填 + 历史联想（对照旧版 loadDefaults + datalist）── */
async function loadDefaults() {
  prefillHint.value = ''
  try {
    const fd = await api('/api/containers/form-defaults')
    const last = fd.last || {}
    nc.value.container_no = ''
    nc.value.seal_no = last.seal_no || ''
    nc.value.client_name = last.client_name || ''
    nc.value.inspector = last.inspector || ''
    nc.value.location = last.location || ''
    nc.value.arrival_at = last.arrival_at || ''
    nc.value.departure_at = last.departure_at || ''
    recentVals.value = {
      client_name: (fd.recent?.client_name || []).map((v) => ({ value: v })),
      inspector: (fd.recent?.inspector || []).map((v) => ({ value: v })),
      location: (fd.recent?.location || []).map((v) => ({ value: v })),
    }
    const h = []
    if (nc.value.client_name) h.push('客户 ' + nc.value.client_name)
    if (nc.value.inspector) h.push('Inspector ' + nc.value.inspector)
    if (nc.value.location) h.push('Location ' + nc.value.location)
    if (h.length) prefillHint.value = '已带入上次建柜：' + h.join(' · ')
  } catch { /* 预填失败不阻塞建柜 */ }
}
function sugg(field, q2) {
  const list = recentVals.value[field] || []
  if (!q2.trim()) return list
  const w = q2.trim().toLowerCase()
  return list.filter((x) => x.value.toLowerCase().includes(w))
}

/* ── 柜详情抽屉 ── */
function openDetail(row) {
  detailCid.value = row.id
}
/* 抽屉里「出报告」→ 设锚点进柜作业第五步（报告生成） */
function openReport(cid) {
  anchor.setCid(cid)
  detailCid.value = ''
  wizView.value = true
}

/** 进柜作业：先设锚点（Wizard 靠 anchor.cid 认柜），再切视图。 */
function enterWizard(row) {
  if (row.is_uncategorized) return
  anchor.setCid(row.id)
  wizView.value = true
}

/** 切回列表：作业页有未保存改动时先问一次（口径复用 Wizard 的 dirtyCount）。 */
async function exitWizard() {
  if (wizRef.value) {
    const ok = await wizRef.value.confirmLeave()
    if (!ok) return
  }
  wizView.value = false
  await load()
}

/* 别的页面（照片库/批次/向导）改了柜锚点后回到本页 —— 刷新一次列表，
   让「照片/监装」两列跟上后端 recount。 */
anchor.onChange(() => { if (!wizView.value) load() })

onMounted(load)
</script>

<style scoped>
.ct-page { max-width: 100%; margin: 0 auto; }
.phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.phead h2 { margin: 0; font-size: 17px; }
.phead .sub { margin-left: 10px; font-size: 12px; font-weight: normal;
  color: var(--el-text-color-secondary); }
.phead .spacer, .toolbar .spacer { flex: 1; }
.toolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 10px;
  padding-bottom: 10px; border-bottom: 1px solid var(--el-border-color-lighter); }
.chips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.clink { color: var(--el-color-primary); cursor: pointer; font-weight: 600; }
.clink:hover { text-decoration: underline; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
.prefill-hint { margin: -6px 0 10px; font-size: 12px; }
/* 作业时长列：起止一行（主）+ 时长一行（次），行距收紧，别把表格撑高 */
.wt { display: flex; flex-direction: column; gap: 1px; line-height: 1.35; }
.wt-r { font-size: 12px; color: var(--el-text-color-regular); }
.wt-d { font-size: 12px; color: var(--el-text-color-secondary); display: inline-flex;
  align-items: center; gap: 3px; }
.wt-warn { color: var(--el-color-warning); font-size: 13px; }
</style>
