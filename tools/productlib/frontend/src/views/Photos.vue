<template>
  <div class="photos-page">
    <!-- 标题行：导入照片是「写」，治理在柜作业③ -->
    <el-card shadow="never" class="head-card">
      <div class="phead">
        <h2>照片库<span class="sub">按柜 / 批次浏览与打标；导入与治理在「柜作业③」</span></h2>
        <!-- 照片/批次两个视图（批次不占顶层导航，对齐旧版 #tab-batches 一页两段） -->
        <el-radio-group v-model="pv" size="small" class="pvgroup">
          <el-radio-button label="photos">照片</el-radio-button>
          <el-radio-button label="batches">批次</el-radio-button>
        </el-radio-group>
        <span class="spacer"></span>
        <el-button size="small" @click="importVisible = true">＋ 导入照片</el-button>
        <el-button size="small" text @click="introOpen = !introOpen">
          {{ introOpen ? '收起 ▴' : '说明 ▾' }}
        </el-button>
      </div>
      <div v-if="introOpen" class="faint intro">
        导入时自动识别两种格式：① 标准采集格式 <code>.../预检/{箱号}/照片.jpg</code>
        → 记录箱号、按照片目录分批次；② 普通照片目录 → 整目录一个批次。
        两者都做 MD5 去重、按 EXIF 时间分组。
        <br /><b>柜号一律以「当前柜」为准</b>（在「柜作业」右上角切换），照片目录叫什么名字不影响归属
        （程序不会拿目录名当柜号，也不会自动建柜）。
      </div>
    </el-card>

    <!-- 批次视图：与照片视图同页切换（表体是 BatchTable，与 /app/batches 共用一份） -->
    <el-card v-if="pv === 'batches'" shadow="never">
      <BatchTable ref="btRef" :container-id="filters.container_id"
                  @view="onBatchView" @governed="onBatchGoverned" />
    </el-card>

    <template v-else>
    <!-- 左树右图：树与网格必须在同一 flex 容器里 -->
    <div class="prow">
      <el-card shadow="never" class="tree-card">
        <PhotoTree @change="reload" />
      </el-card>

      <div class="pmain">
        <el-card shadow="never">
          <template #header>
            <div class="toolbar">
              <el-select v-model="filters.container_id" placeholder="全部柜" clearable
                         style="width:160px" @change="reload">
                <el-option v-for="c in opts.containers" :key="c.id"
                           :label="c.container_no" :value="c.id" />
              </el-select>
              <el-select v-model="filters.batch" placeholder="全部批次" clearable
                         style="width:230px" @change="reload">
                <el-option v-for="b in opts.batches" :key="b.id" :value="b.id"
                           :label="(b.container_no ? '【' + b.container_no + '】' : '') + (b.name || b.id) + '（' + b.unique + '）'" />
              </el-select>
              <el-select v-model="filters.state" placeholder="全部状态" clearable
                         style="width:130px" @change="reload">
                <el-option label="待治理" value="pending" />
                <el-option label="已治理" value="done" />
                <el-option label="已跳过（场景照）" value="skipped" />
                <el-option label="失败" value="failed" />
              </el-select>
              <el-select v-model="filters.invalid" style="width:130px" @change="reload">
                <el-option label="排除无效" value="hide" />
                <el-option label="仅看无效" value="only" />
                <el-option label="含无效全部" value="all" />
              </el-select>
              <el-checkbox v-model="unlinkedBox" @change="reload">只看待关联</el-checkbox>
              <el-select v-model="filters.todo" placeholder="全部待办" clearable
                         style="width:140px" @change="reload">
                <el-option label="待确认关联" value="cand" />
                <el-option label="新产品确认" value="newprod" />
              </el-select>
              <!-- 上面那个「新产品确认」只是筛出**待办照片**；真正确认入库在
                   独立审核页。没有这个按钮，用户会在两个「新产品确认」之间猜。
                   text 型= 纯跳转，不与同行的筛选动作抢主按钮。 -->
              <el-button size="small" text @click="router.push('/review')">
                去审核入库 →
              </el-button>
              <el-input v-model="filters.q" placeholder="搜编码 / 描述 / 文件名" clearable
                        style="width:220px" @keyup.enter="reload" @clear="reload" />
              <!-- 按钮分层：整页只留一个实心主按钮（筛选 = 执行），
重置是描边的次要动作，跳转类是纯文字链接。
                   原来全是灰按钮，扫一眼分不出哪个会改数据、哪个只是跳走。 -->
              <el-button type="primary" @click="reload">筛选</el-button>
              <el-button @click="clearAllFilters">重置</el-button>
              <span class="spacer"></span>
              <span class="faint">{{ totalText }}</span>
              <!-- 保存/复用筛选：筛一组条件要戳七八个控件，
                   反复来回调同一组（比如「本柜待关联」）是常事。
                   text 型 = 辅助功能，不与左侧实心「筛选」抢主操作。 -->
              <el-dropdown trigger="click" @command="onSavedCmd">
                <el-button size="small" text>筛选方案 ▾</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="save">保存当前筛选…</el-dropdown-item>
                    <el-dropdown-item command="clear" divided>清空全部筛选</el-dropdown-item>
                    <el-dropdown-item v-for="(s, i) in savedList" :key="i"
                                      :command="'use:' + i" :divided="i === 0">
                      {{ s.name }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button size="small" class="tgl-btn"
                         :type="sel.on ? 'primary' : 'default'" @click="toggleSelMode">
                {{ sel.on ? '退出选择' : '批量选择' }}</el-button>
              <el-radio-group v-model="view" size="small">
                <el-radio-button label="compact">紧凑</el-radio-button>
                <el-radio-button label="full">详情</el-radio-button>
                <el-radio-button label="group">分组</el-radio-button>
                <el-radio-button label="link">关联</el-radio-button>
              </el-radio-group>
            </div>
            <!-- 筛选标签行：把「当前按什么筛」常显摊开，每个可单独摘掉。
                 筛了七八个下拉时，只看控件是看不出当前值的（占位符只是「全部柜」）。 -->
            <div v-if="fchips.length" class="chips">
              <span class="faint">已按</span>
              <el-tag v-for="c in fchips" :key="c.k" closable size="small" type="info"
                      @close="dropFChip(c.k)">{{ c.t }}</el-tag>
              <el-button size="small" text @click="clearAllFilters">全清</el-button>
            </div>
            <!-- 关联视图才用五档选项卡（其余三档是排版差异）；徽章数字取自后端 COUNT -->
            <el-tabs v-if="view === 'link'" v-model="tab" class="ptabs"
                     @tab-change="onTabChange">
              <el-tab-pane v-for="t in TABS" :key="t.key" :name="t.key || 'all'">
                <template #label>
                  <el-tooltip v-if="t.hint" :content="t.hint" placement="top">
                    <span class="tab-label">
                      {{ t.label }}
                      <el-badge v-if="counts[t.key || 'all'] != null"
                                :value="counts[t.key || 'all']"
                                :type="counts[t.key || 'all'] ? 'primary' : 'info'" />
                      <span v-else class="faint">—</span>
                    </span>
                  </el-tooltip>
                  <span v-else class="tab-label">
                    {{ t.label }}
                    <el-badge v-if="counts[t.key || 'all'] != null"
                              :value="counts[t.key || 'all']"
                              :type="counts[t.key || 'all'] ? 'primary' : 'info'" />
                    <span v-else class="faint">—</span>
                  </span>
                </template>
              </el-tab-pane>
            </el-tabs>
          </template>
        </el-card>

        <!-- 网格 / 分组 -->
        <div ref="gridEl" v-loading="loading" class="grid-body">
          <template v-if="view !== 'group'">
            <div class="shot-grid" :class="{ compact: view === 'compact' }">
              <PhotoCard v-for="p in items" :key="p.id" :photo="p"
                        :selected="selOn && selHas(p.id)" :flags="flags[p.id] || []"
                        :prev-taken="prevTaken(p.id)" :compact="view === 'compact'"
                        @click="onCardClick" />
            </div>
          </template>
          <template v-else>
            <el-collapse v-model="openGroups">
              <el-collapse-item v-for="g in groups" :key="g.key" :name="g.key">
                <template #title>
                  <div class="ghead">
                    <img class="gcover" :src="g.cover_thumb" alt="" />
                    <div class="ginfo">
                      <div class="gtitle">
                        <span class="gcount">{{ g.count }} 张</span>
                        <span class="gtime">{{ groupTime(g) }}</span>
                      </div>
                      <div class="gsum">
                        <el-tag v-for="(n, k) in g.kinds" :key="k" size="small"
                                :class="kindCls(k)">{{ kindName(k) }}{{ n > 1 ? '×' + n : '' }}</el-tag>
                        <el-tag v-for="c in (g.codes || []).slice(0, 4)" :key="c" size="small" effect="plain">{{ c }}</el-tag>
                        <span v-if="(g.codes || []).length > 4" class="faint">+{{ g.codes.length - 4 }}</span>
                        <el-tag v-for="c in (g.linked_codes || []).slice(0, 3)" :key="'l' + c" size="small" type="success">已关联 {{ c }}</el-tag>
                      </div>
                    </div>
                  </div>
                </template>
                <div class="shot-grid compact">
                  <PhotoCard v-for="(p, i) in g.photos" :key="p.id" :photo="p"
                            :selected="selOn && selHas(p.id)" :flags="flags[p.id] || []"
                            :prev-taken="i ? g.photos[i - 1].taken_at : ''" compact
                            @click="onCardClick" />
                </div>
              </el-collapse-item>
            </el-collapse>
          </template>

          <el-empty v-if="!loading && !items.length && !groups.length"
                    description="没有符合条件的照片 —— 在左侧树里换个用途 / 分类，或放宽上面的筛选再试" />
        </div>

        <!-- 页码分页（2026-10-20 老板）：不要「加载更多」，一屏一页，翻页时页面不往下滚 -->
        <div v-if="totalCount" class="more-row pager-row">
          <el-pagination
            layout="total, prev, pager, next, jumper"
            :total="totalCount"
            :page-size="limitNow()"
            :current-page="page"
            :pager-count="7"
            background
            small
            @current-change="goPage" />
        </div>
      </div>
    </div>
    </template>

    <!-- 批量选择操作条：只在选择模式出现 -->
    <div v-if="sel.on" class="selbar">
      <span class="faint">已选 <b>{{ selN }}</b> 张</span>
      <el-button size="small" @click="bulkInvalid(1)">标记无效</el-button>
      <el-button size="small" text @click="bulkInvalid(0)">取消无效</el-button>
      <el-button size="small" @click="bulkIgnore(1)">本次忽略</el-button>
      <el-button size="small" text @click="bulkIgnore(0)">恢复忽略</el-button>
      <el-select v-model="bulkKind" size="small" placeholder="改判分类…" style="width:160px">
        <el-option v-for="k in KIND_KEYS" :key="k" :label="KIND_LABELS[k]" :value="k" />
      </el-select>
      <el-button size="small" type="primary" :disabled="!bulkKind" @click="applyKind">应用改判</el-button>
      <el-button size="small" @click="selectAllFiltered">全选筛选结果</el-button>
      <el-button size="small" text @click="selClear()">清除已选</el-button>
      <span class="spacer"></span>
      <el-button size="small" @click="selSetMode(false)">退出选择</el-button>
    </div>

    <!-- 照片详情抽屉 -->
    <PhotoDrawer v-if="drawerPid" :pid="drawerPid" :list="drawerList"
                 @close="drawerPid = ''" @step="drawerStep" @goto="openDrawer" />

    <!-- 导入照片（与柜作业③共用一份实现） -->
    <ImportPhotosDialog v-model="importVisible" :cid="filters.container_id || anchor.cid"
                        @done="onImported" />
  </div>
</template>

<script setup>
/* Photos.vue —— 照片库页（对应旧版 photos.js + phototree.js + selbatch.js）
 *
 * 四种视图：
 *   紧凑 compact —— 只缩略图 + 分类角标（info 靠 hover 浮出）
 *   详情 full   —— 文件名 / 时间 / 大小常显
 *   分组 group  —— 同货品连拍聚成一组，点开看整组
 *   关联 link   —— 五档选项卡（全部/已关联/待关联/已忽略/无效图片）
 *
 * 🔴 两条铁律照搬旧版：
 *   ① **数字同源**：徽章（/api/photos/linkstate）与列表（/api/photos）传同一份
 *      filters；徽章请求**不阻塞网格**（冷算要扫全库候选，曾让首屏白等 4 秒），
 *      徽章没回来先显示「—」，不许渲染成 0。
 *   ② **请求序列守卫**：连续触发两次加载时两个响应都在飞，谁新谁赢 ——
 *      旧响应会把新结果盖掉（旧版事故：标记无效后列表卡在旧状态）。
 *
 * ⚠️ 五档的「待确认 / 新产品」角标不在列表请求里（冷缓存 6.6s），
 *    渲染后异步补 /api/photo-flags；没到之前不显示（不显示 ≠ 没有）。 */
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, post } from '../api.js'
import {
  filters, opts, sel, bus, anchor,
  loadAllOptions, selIds, selSize, selHas, selToggle, selAddIds, selClear, selSetMode,
} from '../lib/photosStore.js'
import { qs, KIND_LABELS, KIND_KEYS, kindName, kindCls, fmtTaken, fmtGap, diffSec } from '../lib/core.js'
import PhotoCard from '../components/PhotoCard.vue'
import PhotoTree from '../components/PhotoTree.vue'
import PhotoDrawer from '../components/PhotoDrawer.vue'
import ImportPhotosDialog from '../components/ImportPhotosDialog.vue'
import BatchTable from '../components/BatchTable.vue'

/* 五档（照片库口径）。⚠️ 待确认/新产品是「待关联」的子集，加起来 ≠ 全部，正常。 */
const TABS = [
  { key: '', label: '全部' },
  { key: 'linked', label: '已关联' },
  { key: 'unlinked', label: '待关联', hint: '产品图片（有编码/无编码）还没关联到任何产品；包装/清单/场景等非产品照不进此列' },
  { key: 'ignored', label: '已忽略', hint: '本次忽略的照片 —— 新产品暂不入库、退出关联队列；可在这里恢复' },
  { key: 'invalid', label: '无效图片', hint: '已标记无效的照片 —— 默认退出各工作队列，可在这里查看与撤销' },
]
const PAGE = 60
const GROUP_PAGE = 30

const router = useRouter()
const items = ref([])
const groups = ref([])
const totalCount = ref(0)
const loading = ref(false)
const flags = ref({})
const counts = ref({})
const view = ref('full')
const tab = ref('')
/* 照片 / 批次 两个同页视图（批次不占顶层导航，对齐旧版 #tab-batches 一页两段） */
const pv = ref('photos')
const btRef = ref(null)
const openGroups = ref([])
const drawerPid = ref('')
const drawerList = ref([])
const introOpen = ref(false)
const importVisible = ref(false)
const bulkKind = ref('')
const seq = ref(0)
/* 页码分页（2026-10-20 老板：不要「加载更多」，用普通翻页，一屏装下不纵滚）。
   page 是当前页码；pageSize 由 measurePageSize() 按网格容器尺寸算出来，
   PAGE 只是量不到时的兜底。抽屉改完内容重载时 page 必须保住（需求10）。 */
const page = ref(1)
const pageSize = ref(PAGE)
const gridEl = ref(null)

/** 当前视图的每页条数：分组视图按「组」算，其余按张。 */
function limitNow() {
  return view.value === 'group' ? GROUP_PAGE : pageSize.value
}
/** 页码 → offset（后端 /api/photos 与 /api/photos/groups 都吃 offset）。 */
function offsetNow() {
  return (page.value - 1) * limitNow()
}

/** 按网格容器可用高度 / 一张卡片的实际高度算「一屏能放几张」。
 *  容器没渲染出来时退回兜底值，不猜 CSS 常量（卡片高度随缩放/主题变）。 */
function measurePageSize() {
  const el = gridEl.value
  if (!el || !el.clientWidth) return
  const gap = 10                                    // 与 .shot-grid 的 gap 一致
  // 可用高度 = 视口 - 网格容器顶边 - 底部页码行/边距。
  // 别用 el.clientHeight：.grid-body 只有 min-height:200，量不出「还能放几行」。
  const availH = Math.max(200,
    window.innerHeight - el.getBoundingClientRect().top - 96)
  const card = el.querySelector('.shot, .gcard, .pcard')
  const cardH = card ? card.getBoundingClientRect().height : 170
  if (!cardH) return
  const cols = Math.max(1, Math.floor((el.clientWidth + gap) / (150 + gap)))
  const rows = Math.max(2, Math.floor((availH + gap) / (cardH + gap)))
  const n = cols * rows
  if (n > 0 && n !== pageSize.value) pageSize.value = n
}

try { view.value = localStorage.getItem('shotView') || 'full' } catch { view.value = 'full' }
watch(view, (v) => {
  try { localStorage.setItem('shotView', v) } catch { /* 隐私模式 */ }
  /* 换视图要重拉：分组视图打的是 /api/photos/groups（与网格不同接口），
   * 关联视图还要重置档位。不重拉的话切到分组会是一片空白。 */
  tab.value = ''
  items.value = []
  groups.value = []
  load(true)
})

const unlinkedBox = computed({
  get: () => !!filters.unlinked,
  set: (v) => { filters.unlinked = v ? 1 : 0 },
})
const shown = computed(() => (view.value === 'group' ? groups.value.length : items.value.length))
const totalText = computed(() => {
  const n = counts.value.all
  if (n == null) return '共 … 张'
  return '共 ' + n + ' 张'
})
const selN = computed(() => { sel.version; return selSize() })
const selOn = computed(() => sel.on)

/* ── 筛选可解释性 + 筛选方案 ──
 *
 * 筛选条上有七八个控件，筛完只看控件**看不出当前是什么条件**
 * （下拉占位符一律是「全部柜/全部批次」）。所以把条件摊成一行标签，
 * 每个可单独摘掉 —— 摘一个只清那一个并立刻重拉，不用手动从头重设。
 *
 * ⚠️ `invalid` 三态有默认值（hide），不是「没选」→ 清它要显式回默认值，
 *    不能当成空值跳过，否则「全清」之后列表还带着旧口径。
 */
const FKEYS = ['container_id', 'batch', 'state', 'kind', 'usage', 'todo', 'q']
const F_LABELS = {
  container_id: '柜', batch: '批次', state: '治理状态', kind: '分类',
  usage: '用途', todo: '待办', q: '关键词',
}
const INVALID_LABELS = { hide: '排除无效', only: '仅看无效', all: '含无效全部' }
/* 下拉值 → 标签文案（筛选标签行要显示人话，不是 pending/done） */
const STATE_LABELS = {
  state: { pending: '待治理', done: '已治理', skipped: '已跳过', failed: '失败' },
  todo: { cand: '待确认关联', newprod: '新产品确认' },
}
/* 默认值：不进标签行，否则「打开页面就是排除无效」会显示成一条已按条件 */
const DEFAULTS = { invalid: 'hide', unlinked: 0 }

const fchips = computed(() => {
  const out = []
  for (const k of FKEYS) {
    const v = filters[k]
    if (v === '' || v == null) continue
    let t = String(v)
    if (k === 'container_id') {
      const c = opts.containers.find((x) => x.id === v)
      t = '柜 ' + (c ? c.container_no : v)
    } else if (k === 'batch') {
      const b = opts.batches.find((x) => x.id === v)
      t = '批次 ' + (b ? (b.name || b.id) : v)
    } else if (k === 'kind') {
      // 多选（2026-10-19）：值是逗号分隔集合 —— 一项显示名称，多项显示项数，
      // 别把 "label,scene" 这种内部串直接摊给用户。
      const ks = String(v).split(',').filter(Boolean)
      t = ks.length > 1 ? F_LABELS[k] + ' ' + ks.length + ' 项'
        : F_LABELS[k] + ' ' + kindName(ks[0] || v)
    } else if (k === 'usage') {
      const us = String(v).split(',').filter(Boolean)
      t = us.length > 1 ? F_LABELS[k] + ' ' + us.length + ' 项'
        : F_LABELS[k] + '：' + (us[0] || v)
    } else if (k === 'state' || k === 'todo') {
      t = F_LABELS[k] + ' ' + STATE_LABELS[k][v]
    } else {
      t = F_LABELS[k] + '：' + t
    }
    out.push({ k, t })
  }
  if (filters.unlinked) out.push({ k: 'unlinked', t: '只看待关联' })
  if (filters.invalid && filters.invalid !== DEFAULTS.invalid) {
    out.push({ k: 'invalid', t: INVALID_LABELS[filters.invalid] || filters.invalid })
  }
  return out
})

function dropFChip(k) {
  if (k === 'unlinked') filters.unlinked = 0
  else if (k === 'invalid') filters.invalid = DEFAULTS.invalid
  else filters[k] = ''
  tab.value = ''            // 关联视图的档位属于 filters 的一部分，跟着重置
  items.value = []
  groups.value = []
  load(true)
}
function clearAllFilters() {
  for (const k of FKEYS) filters[k] = ''
  filters.unlinked = 0
  filters.invalid = DEFAULTS.invalid
  tab.value = ''
  items.value = []
  groups.value = []
  load(true)
}

/* 筛选方案：存 localStorage（不上后端 —— 个人视图偏好，不是业务数据）。
   最多 8 条，存满了从头覆盖（先进先出），避免无上限堆积。 */
const SAVED_KEY = 'plPhotoFilters'
const savedList = ref([])
try { savedList.value = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]') } catch { savedList.value = [] }

function snapshot() {
  const o = {}
  for (const k of FKEYS) o[k] = filters[k] || ''
  o.unlinked = filters.unlinked || 0
  o.invalid = filters.invalid || DEFAULTS.invalid
  return o
}
function persistSaved() {
  try { localStorage.setItem(SAVED_KEY, JSON.stringify(savedList.value)) } catch { /* 隐私模式 */ }
}

async function onSavedCmd(cmd) {
  if (cmd === 'clear') { clearAllFilters(); return }
  if (cmd === 'save') {
    if (!fchips.value.length) { ElMessage.info('当前没有筛选条件可保存'); return }
    try {
      const { value } = await ElMessageBox.prompt('给这组筛选起个名字', '保存筛选方案', {
        confirmButtonText: '保存', cancelButtonText: '取消',
        inputValidator: (v) => (v && v.trim() ? true : '名字不能为空'),
      })
      const name = value.trim()
      if (savedList.value.some((s) => s.name === name)) {
        ElMessage.warning('已经有叫「' + name + '」的方案了')
        return
      }
      savedList.value = [{ name, f: snapshot() }, ...savedList.value].slice(0, 8)
      persistSaved()
      ElMessage.success('已保存「' + name + '」')
    } catch { /* 用户取消 */ }
    return
  }
  if (cmd.startsWith('use:')) {
    const s = savedList.value[Number(cmd.slice(4))]
    if (!s) return
    for (const k of FKEYS) filters[k] = s.f[k] || ''
    filters.unlinked = s.f.unlinked || 0
    filters.invalid = s.f.invalid || DEFAULTS.invalid
    tab.value = ''
    items.value = []
    groups.value = []
    load(true)
    ElMessage.success('已套用「' + s.name + '」')
  }
}

/** 公共筛选参数（视图/选项卡无关，一份）。 */
function baseQs() {
  return {
    state: filters.state, kind: filters.kind, batch: filters.batch,
    usage: filters.usage, invalid: filters.invalid,
    unlinked: filters.unlinked, todo: filters.todo, q: filters.q,
    container_id: filters.container_id,
  }
}

/* 关联视图的档位参数：无效/已忽略档把「排除」翻成「只看」。 */
function tabQs() {
  const p = Object.assign({}, baseQs(), { flag: tab.value, limit: PAGE, offset: offsetNow() })
  if (tab.value === 'invalid') p.invalid = 'only'
  if (tab.value === 'ignored') p.ignored = 'only'
  return p
}

/** 徽章：不阻塞网格（冷算曾让首屏白等 4 秒）。 */
async function loadCounts(mySeq) {
  try {
    const d = await api('/api/photos/linkstate?' + qs(Object.assign({ pending: 0 }, baseQs())))
    if (mySeq !== seq.value) return          // 已有更新的请求，旧响应丢弃
    counts.value = d || {}
  } catch { /* 徽章失败就不显示，别影响照片本身 */ }
}

/* 角标要看哪些照片：分组视图下 items 为空，要看组内照片。 */
function flagIds() {
  if (view.value !== 'group') return items.value.map((p) => p.id)
  return groups.value.flatMap((g) => (g.photos || []).map((p) => p.id))
}

async function load(reset) {
  const mySeq = ++seq.value
  if (reset) page.value = Math.max(1, page.value)   // 页码由调用方决定，这里不重置
  loading.value = true
  /* ① 徽章与网格并行，徽章只重排选项卡 */
  const pCounts = loadCounts(mySeq)
  let d
  try {
    const path = view.value === 'group' ? '/api/photos/groups' : '/api/photos'
    const params = view.value === 'link' ? tabQs()
      : Object.assign({}, baseQs(), {
        limit: limitNow(), offset: offsetNow(),
      })
    d = await api(path + '?' + qs(params))
  } catch (e) {
    if (mySeq === seq.value) ElMessage.error('读取失败：' + e.message)
    loading.value = false
    return
  }
  if (mySeq !== seq.value) return          // 已有更新的请求，这份旧响应丢弃
  const incoming = d.items || []
  if (view.value === 'group') {
    groups.value = incoming        // 页码分页：每次只取一页，不再追加
    openGroups.value = incoming.slice(0, 3).map((g) => g.key)
  } else {
    items.value = incoming
  }
  totalCount.value = d.total || 0
  // 末页越界保护：照片被删/标无效后，原页码可能已经空了 → 退到最后一页，
  // 否则用户停在一片空白上（需求10 的连带场景）。
  const maxPage = Math.max(1, Math.ceil(totalCount.value / limitNow()))
  if (page.value > maxPage) {
    page.value = maxPage
    loading.value = false
    return load(true)
  }
  loading.value = false
  await nextTick()
  loadFlags()
  await pCounts
}

function loadFlags() {
  const ids = flagIds()
  if (!ids.length) return
  const run = () => {
    api('/api/photo-flags?ids=' + ids.join(',')).then((d) => {
      const tags = Object.entries(d || {})
      if (!tags.length) return
      flags.value = Object.fromEntries(tags.map(([pid, tl]) => [pid, (tl || [])]))
    }).catch(() => { /* 角标失败不画 */ })
  }
  if (typeof requestIdleCallback === 'function') requestIdleCallback(run, { timeout: 2500 })
  else setTimeout(run, 1200)
}

function reload() { load(true) }
/** 跳页（1 起）。超出范围自动夹住 —— 删照片后末页可能空了。 */
async function goPage(n) {
  const total = totalCount.value || 0
  const maxPage = Math.max(1, Math.ceil(total / limitNow()))
  const target = Math.min(Math.max(1, n | 0), maxPage)
  if (target === page.value && items.value.length) return
  page.value = target
  items.value = []
  groups.value = []
  await load(true)
  // 翻页后回到顶部：否则新一页从中间开始，看着像没换
  try { document.querySelector('.grid-body')?.scrollIntoView({ block: 'start' }) } catch { /* 忽略 */ }
}
function onTabChange() { page.value = 1; items.value = []; groups.value = []; load(true) }

/* 批次治理启动 → 跳柜作业③：进度条要留在用户眼前，
   进度藏在看不见的地方，主观上等于卡死。 */
function onBatchGoverned() { router.push('/containers') }

/* 批次表点「查看」→ 回照片视图。批次筛选已由 BatchTable 写进 photosStore，
   这里除了切视图还得重拉：filters 变了但列表不会自己动，不重拉屏幕上还是上一批照片。 */
function onBatchView() {
  pv.value = 'photos'
  view.value = 'full'
  tab.value = ''
  page.value = 1
  items.value = []
  groups.value = []
  load(true)
}

/** 相邻间隔：网格按 taken_at 排序，用上一张的时间。 */
function prevTaken(id) {
  const i = items.value.findIndex((p) => String(p.id) === String(id))
  return i > 0 ? items.value[i - 1].taken_at : ''
}

function groupTime(g) {
  const f1 = g.taken_from ? fmtTaken(g.taken_from) : ''
  const f2 = g.taken_to ? fmtTaken(g.taken_to) : ''
  if (!f1 && !f2) return ''
  if (f1 === f2) return f1
  const span = (g.taken_from && g.taken_to)
    ? fmtGap(diffSec(g.taken_from, g.taken_to)).replace(/^\+/, '') : ''
  return f1 + ' ~ ' + f2 + (span ? '（跨 ' + span + '）' : '')
}

/* ── 点击：选择模式 = 勾选；否则开详情 ── */
function onCardClick(id) {
  if (sel.on) { selToggle(String(id)); return }
  openDrawer(String(id))
}
function openDrawer(pid) {
  drawerList.value = flagIds()
  drawerPid.value = pid
}
function drawerStep(d) {
  const i = drawerList.value.indexOf(drawerPid.value)
  const n = drawerList.value[i + d]
  if (n) drawerPid.value = n
}

function toggleSelMode() { selSetMode(!sel.on) }

async function selectAllFiltered() {
  /* 全选当前筛选条件下的全部（跨页、含未加载的）—— 口径 = 筛选 + 当前档 */
  const params = Object.assign({}, baseQs(), { flag: tab.value, limit: 5000, offset: 0 })
  if (tab.value === 'invalid') params.invalid = 'only'
  if (tab.value === 'ignored') params.ignored = 'only'
  loading.value = true
  let d
  try {
    d = await api('/api/photos?' + qs(params))
  } catch (e) {
    loading.value = false
    ElMessage.error('读取失败：' + e.message)
    return
  }
  loading.value = false
  const ids = (d.items || []).map((x) => String(x.id))
  if (!ids.length) { ElMessage.warning('当前筛选条件下没有照片'); return }
  selAddIds(ids)
  ElMessage.success('已选中当前筛选结果 ' + ids.length + ' 张（含未加载的页）')
}

async function afterBulk() {
  selClear()
  bulkKind.value = ''
  reload()
  bus.emit('stats:changed')
}

async function bulkInvalid(flag) {
  if (!selSize()) { ElMessage.warning('先勾选照片'); return }
  try {
    const r = await post('/api/photos/invalid', { photo_ids: selIds(), invalid: flag, by: 'web' })
    ElMessage.success((flag ? '已标记 ' : '已取消 ') + r.updated + ' 张无效照片')
    await afterBulk()
  } catch (e) { ElMessage.error('操作失败：' + e.message) }
}

async function bulkIgnore(flag) {
  if (!selSize()) { ElMessage.warning('先勾选照片'); return }
  try {
    const r = await post('/api/photos/ignore', { photo_ids: selIds(), ignored: flag, by: 'web' })
    ElMessage.success((flag ? '已忽略 ' : '已恢复 ') + r.updated + ' 张照片')
    await afterBulk()
  } catch (e) { ElMessage.error('操作失败：' + e.message) }
}

async function applyKind() {
  if (!bulkKind.value) { ElMessage.warning('先选要改成哪个分类'); return }
  if (!selSize()) { ElMessage.warning('先勾选照片'); return }
  try {
    const r = await post('/api/photos/kind', { photo_ids: selIds(), kind: bulkKind.value })
    ElMessage.success('已把 ' + r.updated + ' 张改判为「' + kindName(bulkKind.value) + '」')
    await afterBulk()
  } catch (e) { ElMessage.error('改判失败：' + e.message) }
}

/* ── 导入照片（实现已抽到 ImportPhotosDialog.vue，与柜作业③共用一份）──
async function onImported() {
  await loadAllOptions()
  reload()
  bus.emit('stats:changed')
}

/* 抽屉里改判/关联/忽略后：列表 + 树 + 徽章统一重算（数字同源）。
 * ⚠️ 不发 wizard:refresh —— 它带 advance 语义，会把柜作业③推到④（旧版教训）。 */
const offChanged = bus.on('photos:changed', () => { reload() })

function onResize() { measurePageSize() }

onMounted(async () => {
  await loadAllOptions()
  await load(true)
  await nextTick()
  // 首屏卡片渲染完后按真实卡片高度校准「一屏几张」；变了就重取这一页，
  // 否则按兜底 60 张取回来会撑出滚动条（老板要「一屏装下不往下滚」）。
  const before = pageSize.value
  measurePageSize()
  if (pageSize.value !== before) await load(true)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  offChanged()
})
</script>

<style scoped>
.photos-page { display: flex; flex-direction: column; gap: 12px; }
.head-card :deep(.el-card__body) { padding: 12px 16px; }
.phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.phead h2 { margin: 0; font-size: 17px; }
.phead .sub { margin-left: 10px; font-size: 12px; font-weight: normal;
  color: var(--el-text-color-secondary); }
.phead .spacer { flex: 1; }
.intro { margin-top: 8px; font-size: 12px; line-height: 1.7; }
/* 左树：带边框的白卡 + sticky（与向导第③步、也即旧版 .ptree 同款）。
   裸列没有边界，与右侧网格糊在一起显得排版很乱。
   🔴 sticky 生效条件：① 元素自身**不能**带 overflow（内部切断 sticky 上下文）；
     ② 不能 align-self:stretch 撑满（撑满就没有位移空间，反而完全不粘）；树高 143px、
     网格上千px 时，sticky 行程= min(网格高-树高, 滚动量) 足够粘住。 */
.prow { display: flex; gap: 14px; align-items: flex-start; }
.tree-card {
  flex: 0 0 200px; position: sticky; top: 16px; align-self: start;
  background: var(--pl-panel); border: 1px solid var(--pl-line);
  border-radius: 8px; padding: 8px 6px;
  overflow: visible;
}
.tree-card :deep(.el-card__body) {
  padding: 0; max-height: calc(100vh - 64px); overflow: auto;
}
.pmain { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
/* 工具条与下方选项卡之间一条实线，控件不再悬在半空 */
.toolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  padding-bottom: 10px; border-bottom: 1px solid var(--pl-line-2); }
.chips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin: 8px 0 0; padding-top: 8px; border-top: 1px dashed var(--pl-line); }
.pvgroup { margin-left: 14px; }
.toolbar .spacer { flex: 1; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
.grid-body { min-height: 200px; }
.shot-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px;
}
.shot-grid.compact { grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); }
.more-row { padding: 10px 0 30px; text-align: center; }
.ptabs { margin-top: 8px; }
.ptabs :deep(.el-tabs__header) { margin-bottom: 0; }
.tab-label { display: inline-flex; align-items: center; gap: 6px; }
.ghead { display: flex; align-items: center; gap: 10px; }
.gcover { width: 56px; height: 56px; object-fit: cover; border-radius: 4px; }
.ginfo { flex: 1; min-width: 0; }
.gtitle { display: flex; gap: 10px; align-items: baseline; }
.gcount { font-weight: 600; }
.gtime { font-size: 12px; color: var(--el-text-color-secondary); }
.gsum { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 2px; }

/* 批量选择操作条 */
.selbar {
  position: fixed; left: 216px; right: 16px; bottom: 12px; z-index: 100;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 12px; border-radius: 8px;
  background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color);
  box-shadow: 0 -2px 10px rgba(0, 0, 0, .08);
}
.selbar .spacer { flex: 1; }
</style>
