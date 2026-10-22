<template>
  <div class="w-photos">
    <!-- 治理面板：2026-10-21 改成由 **Wizard 持有抽屉**（本组件只管列表）。
         之前把 el-drawer 放在这里、用 prop 传 v-model，实测点击后抽屉 DOM 在
         但宽高为 0（Element Plus 的 drawer 在父层容器里不展开），点了没反应。 -->

    <div class="prow">
      <div class="ptree-wrap">
        <PhotoTree :f="f" show-pending :pending-n="pend ? pend.items.length : null"
                   @change="reload" />
      </div>

      <div class="pmain">
        <!-- 工具条：左边缩小范围（筛选），右边对结果做事（工具） -->
        <div class="wclbar">
          <span class="tgrp">
            <el-select v-model="f.state" placeholder="全部治理状态" clearable size="small"
                       style="width:130px" @change="reload">
              <el-option label="待治理" value="pending" />
              <el-option label="已治理" value="done" />
              <el-option label="已跳过" value="skipped" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-input v-model="f.q" placeholder="搜编码 / 文件名 / 描述" clearable
                      size="small" style="width:210px"
                      @keyup.enter="reload" @clear="reload" />
            <el-checkbox v-model="unlinkedBox" @change="reload">只看待关联</el-checkbox>
            <el-select v-model="f.todo" placeholder="全部待办" clearable size="small"
                       style="width:140px" @change="reload">
              <el-option label="待确认关联" value="cand" />
              <el-option label="新产品确认" value="newprod" />
            </el-select>
            <!-- 按钮分层：整条工具条只留一个实心主按钮（查询 = 执行），
                 重置描边，「按箱号分组/批量选择」是**开关态**（选中即primary），
                 「更多」纯文字。原先全是同款灰按钮，扫一眼分不出作用。 -->
            <el-button type="primary" size="small" @click="reload">查询</el-button>
            <el-button size="small" @click="resetFiltersLocal">重置</el-button>
          </span>
          <span class="spacer"></span>
          <span class="tgrp tgrp-tool">
            <el-button size="small" class="tgl-btn"
                       :type="cartonMode ? 'primary' : ''" @click="toggleCarton">
              按箱号分组
            </el-button>
            <el-button size="small" class="tgl-btn"
                       :type="s.on ? 'primary' : ''" @click="s.on = !s.on">
              {{ s.on ? '退出选择' : '批量选择' }}
            </el-button>
            <el-dropdown @command="onMore">
              <el-button size="small" text>更多 ▾</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="clean">清单 / 包装清理</el-dropdown-item>
                  <el-dropdown-item command="dup">重复图片</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </span>
        </div>

        <!-- 五档选项卡：常驻不藏（待关联/已忽略/无效是要去干活的入口） -->
        <el-tabs v-model="tab" class="ptabs">
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

        <div ref="gridEl" v-loading="loading" class="grid-body">
          <!-- 网格 -->
          <div v-if="!cartonMode" class="shot-grid compact">
            <div v-for="p in items" :key="p.id" class="shot-wrap">
              <PhotoCard :photo="p" :selected="s.on && s.ids.has(String(p.id))"
                        :flags="flags[p.id] || []" :prev-taken="prevTaken(p.id)" compact
                        @click="onCardClick(p.id)" />
              <!-- 待确认视图：给待办卡片补细分操作行（数据源与树上计数同一份） -->
              <div v-if="f.pending && pendMap[String(p.id)]" class="supact">
                <div class="supact-row">
                  <span v-if="supOf(p.id).ai_tag" class="tag acc">
                    建议 {{ labelOf(supOf(p.id).ai_tag) }}
                    {{ supOf(p.id).ai_conf != null
                       ? ' · ' + Math.round(supOf(p.id).ai_conf * 100) + '%' : '' }}
                  </span>
                  <span v-else class="faint">无建议</span>
                  <el-button v-if="supOf(p.id).usage !== '监装'" size="small" text
                             @click="markSup(p.id)">标为监装</el-button>
                </div>
                <div class="supact-row">
                  <el-select :model-value="supOf(p.id).tag || ''" size="small"
                             style="flex:1;min-width:0" @change="setSupTag(p.id, $event)">
                    <el-option label="未标注" value="" />
                    <el-option v-for="(lb, k) in supLabels" :key="k" :label="lb" :value="k" />
                  </el-select>
                  <el-button size="small" :disabled="!canAccept(p.id)"
                             @click="acceptAi(p.id)">采用</el-button>
                </div>
              </div>
            </div>
          </div>

          <!-- 箱号分组：与五档共用同一份筛选 -->
          <el-collapse v-else v-model="openGroups">
            <el-collapse-item v-for="g in groups" :key="g.key" :name="g.key">
              <template #title>
                <div class="ghead">
                  <img class="gcover" :src="g.cover_thumb" alt="" />
                  <div class="ginfo">
                    <div class="gtitle">
                      <span class="gcount">{{ g.count }} 张</span>
                      <span class="gtime">{{ g.carton_no || '未标注箱号' }}</span>
                    </div>
                    <div class="gsum">
                      <el-tag v-for="(n, k) in g.kinds" :key="k" size="small"
                              :class="kindCls(k)">{{ kindName(k) }}{{ n > 1 ? '×' + n : '' }}</el-tag>
                      <el-tag v-for="c in (g.codes || []).slice(0, 4)" :key="c" size="small"
                              effect="plain">{{ c }}</el-tag>
                      <el-tag v-for="c in (g.linked_codes || []).slice(0, 3)" :key="'l' + c"
                              size="small" type="success">已关联 {{ c }}</el-tag>
                    </div>
                  </div>
                </div>
              </template>
              <div class="shot-grid compact">
                <PhotoCard v-for="(p, i) in g.photos" :key="p.id" :photo="p"
                          :selected="s.on && s.ids.has(String(p.id))"
                          :flags="flags[p.id] || []"
                          :prev-taken="i ? g.photos[i - 1].taken_at : ''" compact
                          @click="onCardClick(p.id)" />
              </div>
            </el-collapse-item>
          </el-collapse>

          <el-empty v-if="!loading && !items.length && !groups.length"
                    description="本柜还没有符合条件的照片 —— 先在上面「＋ 导入照片」" />
        </div>

        <!-- 页码分页（2026-10-20 老板）：不要「加载更多」，一屏一页、翻页不纵滚 -->
        <div v-if="total" class="more-row pager-row">
          <el-pagination
            layout="total, prev, pager, next, jumper"
            v-model:current-page="page"
            :total="total"
            :page-size="limitNow()"
            :pager-count="7"
            background
            small />
        </div>
      </div>
    </div>

    <!-- 批量条 -->
    <div v-if="s.on" class="selbar">
      <span class="faint">已选 <b>{{ s.ids.size }}</b> 张</span>
      <el-button size="small" @click="bulkInvalid(1)">标记无效</el-button>
      <el-button size="small" text @click="bulkInvalid(0)">取消无效</el-button>
      <el-button size="small" @click="bulkIgnore(1)">本次忽略</el-button>
      <el-button size="small" text @click="bulkIgnore(0)">恢复忽略</el-button>
      <el-select v-model="bulkKind" size="small" placeholder="改判分类…" style="width:150px">
        <el-option v-for="k in KIND_KEYS" :key="k" :label="KIND_LABELS[k]" :value="k" />
      </el-select>
      <el-button size="small" type="primary" :disabled="!bulkKind" @click="applyKind">应用改判</el-button>
      <el-button size="small" @click="selectAllFiltered">全选筛选结果</el-button>
      <el-button size="small" text @click="selClear(s)">清除已选</el-button>
      <span class="spacer"></span>
      <el-button size="small" @click="selSetMode(false, s)">退出选择</el-button>
    </div>

    <PhotoDrawer v-if="drawerPid" :pid="drawerPid" :list="drawerList"
                 @close="drawerPid = ''" @step="drawerStep" @goto="openDrawer" />

    <!-- 清单/包装清理 -->
    <el-dialog v-model="cleanVisible" title="清理清单 / 包装照" width="760px">
      <div v-if="cleanErr" class="err">{{ cleanErr }}</div>
      <template v-else-if="clean">
        <p>
          识别到 <b>{{ clean.total }}</b> 张没关联过的<b>清单 / 包装</b>照
          <span v-if="clean.linked_n">（另有 {{ clean.linked_n }} 张已关联过，不在名单）</span>。
          确认后批量标记为<b>无效</b> —— 只做标记不删文件，在「无效图片」档可随时撤销。
        </p>
        <div class="dupgrid">
          <div v-for="p in clean.preview || []" :key="p.id" class="dupcell">
            <img loading="lazy" :src="p.thumb" :title="p.file" />
            <span class="tag">{{ kindName(p.photo_kind) }}</span>
          </div>
        </div>
        <p v-if="clean.total > (clean.preview || []).length" class="faint">
          仅预览前 {{ (clean.preview || []).length }} 张，确认时全部 {{ clean.total }} 张一并标记。
        </p>
      </template>
      <template #footer>
        <el-button @click="cleanVisible = false">取消</el-button>
        <el-button type="danger" :loading="busy2" :disabled="!clean || !clean.total"
                   @click="doClean">全部标为无效</el-button>
      </template>
    </el-dialog>

    <!-- 重复图片 -->
    <el-dialog v-model="dupVisible" title="重复图片" width="880px">
      <div v-if="dupErr" class="err">{{ dupErr }}</div>
      <template v-else-if="dup">
        <p>每组左边是<b>建议保留</b>的一张（已关联的优先），勾选的重复张将标记为<b>无效</b>。</p>
        <div v-for="(g, gi) in dup.groups || []" :key="gi" class="duprow">
          <div class="dupcell keep">
            <img loading="lazy" :src="g.keep.thumb" :title="g.keep.file" />
            <span class="tag ok">建议保留{{ g.keep.linked ? ' · 已关联' : '' }}</span>
          </div>
          <div v-for="o in g.others" :key="o.id" class="dupcell">
            <el-checkbox v-model="dupPicked" :label="String(o.id)">
              <img loading="lazy" :src="o.thumb" :title="o.file" />
            </el-checkbox>
            <span class="tag">{{ kindName(o.photo_kind) || '未分类' }}</span>
          </div>
        </div>
        <p v-if="dup.remaining" class="faint">
          ⚠️ 还有 {{ dup.remaining }} 张指纹未算完，稍后再点一次能找出更多。
        </p>
      </template>
      <template #footer>
        <el-button @click="dupVisible = false">取消</el-button>
        <el-button type="danger" :loading="busy2" :disabled="!dupPicked.length" @click="doDup">
          把勾选的标为无效（{{ dupPicked.length }}）
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/* StepPhotos.vue —— ③照片：导入 → 治理 → 浏览（本组件管浏览与治理操作）
 *
 * 与照片库页共用 PhotoTree / PhotoCard / PhotoDrawer 三件套与筛选语义，
 * 但**持有自己一份 filters 与 sel 单例**（makeFilters/makeSel）：
 * ③固定一个柜、还多一维「待确认细分」，共用会把照片库的筛选与勾选弄脏。
 *
 * 🔴 数字同源照旧：徽章（/api/photos/linkstate）与列表（/api/photos）传同一份
 *    筛选；徽章请求不阻塞网格（冷算扫全库候选，曾让首屏白等 4 秒），
 *    没回来先显示「—」，不许渲染成 0。
 * 🔴 请求序列守卫：连续两次加载谁新谁赢（旧响应会把新结果盖掉）。
 *
 * 待确认细分（监装照细分的人工确认）：数据源只有
 * /api/containers/{cid}/supervision-pending 一份 —— 树上计数、卡片操作行、
 * 「全部采用建议」按钮都从它出，前端不重算第二套。 */
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, post, patch } from '../../api.js'
import { bus, makeFilters, makeSel, selClear, selSetMode } from '../../lib/photosStore.js'
import { qs, KIND_LABELS, KIND_KEYS, kindName, kindCls } from '../../lib/core.js'
import PhotoTree from '../PhotoTree.vue'
import PhotoCard from '../PhotoCard.vue'
import PhotoDrawer from '../PhotoDrawer.vue'
import GovPanel from './GovPanel.vue'

const props = defineProps({
  cid: { type: String, required: true },
})
const emit = defineEmits(['changed', 'picked'])

/* 五档：与照片库同一份定义（③的口径是「这柜的照片都在什么状态」） */
const TABS = [
  { key: '', label: '全部' },
  { key: 'linked', label: '已关联' },
  { key: 'unlinked', label: '待关联', hint: '产品图片还没关联到任何产品；包装/清单/场景等非产品照不进此列' },
  { key: 'ignored', label: '已忽略', hint: '本次忽略的照片，可在这里恢复' },
  { key: 'invalid', label: '无效图片', hint: '已标记无效的照片 —— 清理/重复图确认的落脚点，可撤销' },
]
const PAGE = 18            // 固定每页18张（2026-10-21 老板标注：6列×3行，显示分页、不要滚动条）
const CARTON_PAGE = 30

/* ③ 自己一份筛选与勾选 */
const f = makeFilters({ container_id: props.cid, invalid: 'hide' })
const s = makeSel()

const items = ref([])
const groups = ref([])
const counts = ref({})
const flags = ref({})
const openGroups = ref([])
const tab = ref('')
const cartonMode = ref(false)
const loading = ref(false)
/* 页码分页（2026-10-20 老板）：每页张数按视口高度算，保证一屏装下、不纵滚。
   原来固定 60 张一页 → 要滚很久才翻一次页，一屏只看到几张。 */
const page = ref(1)
const pageSize = ref(PAGE)
const gridEl = ref(null)
const off = ref(0)

/** 当前视图的每页条数：箱号组视图按「组」算，其余按张。 */
function limitNow() {
  return cartonMode.value ? CARTON_PAGE : pageSize.value
}

/** 一屏能放几张（卡片高从真实 DOM 量，别猜 CSS 常量）。 */
function measurePageSize() {
  // 2026-10-21：固定 PAGE=24，不再动态测量（测量不准导致最后一行空位）
  // 仅在窗口变化时记录列数，不调整 pageSize
  return
}

/** 跳页（1 起）。末页可能因标无效而空 —— 超范围自动夹住。 */
/** 页码变了就重新取（el-pagination 用 v-model 双向绑定；单向 :current-page
 *  时外部改 page 控件不同步 —— 实测点第 2 页看着没反应）。 */
watch(page, () => { load(true) })
const total = ref(0)
const seq = ref(0)
const drawerPid = ref('')
const drawerList = ref([])
const bulkKind = ref('')
const pend = ref(null)
const cleanVisible = ref(false)
const clean = ref(null)
const cleanErr = ref('')
const dupVisible = ref(false)
const dup = ref(null)
const dupErr = ref('')
const dupPicked = ref([])
const busy2 = ref(false)

const supLabels = computed(() => (pend.value && pend.value.labels) || {})
const pendMap = computed(() => {
  const m = {}
  ;((pend.value && pend.value.items) || []).forEach((x) => { m[String(x.photo_id)] = x })
  return m
})
const supOf = (pid) => pendMap.value[String(pid)] || {}
const labelOf = (k) => supLabels.value[k] || k
const canAccept = (pid) => {
  const it = supOf(pid)
  return it.usage === '监装' && !!it.ai_tag
}
const adoptableN = computed(() =>
  ((pend.value && pend.value.items) || []).filter((x) => x.usage === '监装' && x.ai_tag).length)

const unlinkedBox = computed({
  get: () => !!f.unlinked,
  set: (v) => { f.unlinked = v ? 1 : 0 },
})
const shown = computed(() => (cartonMode.value ? groups.value.length : items.value.length))
const shownText = computed(() => {
  if (!total.value) return ''
  /* 说清是**当前档**的数字：徽章上是全柜，这里是这一档，两个数不点名会被当成不一致 */
  return '当前档「' + (TABS.find((t) => t.key === tab.value)?.label || '全部') + '」已显示 '
    + shown.value + ' / ' + total.value + (cartonMode.value ? ' 组' : ' 张')
})

function baseQs() {
  return {
    container_id: props.cid, state: f.state, kind: f.kind, usage: f.usage,
    invalid: f.invalid, unlinked: f.unlinked, todo: f.todo, q: f.q,
    pending: f.pending ? 1 : 0,
  }
}
function listQs() {
  const p = Object.assign({}, baseQs(), { flag: tab.value, limit: limitNow(), offset: (page.value - 1) * limitNow() })
  /* 无效 / 已忽略档把「排除」翻成「只看」—— 列表与徽章同一口径 */
  if (tab.value === 'invalid') p.invalid = 'only'
  if (tab.value === 'ignored') p.ignored = 'only'
  return p
}

/** 徽章：不阻塞网格 */
async function loadCounts(mySeq) {
  try {
    const d = await api('/api/photos/linkstate?' + qs(Object.assign({ pending: 0 }, baseQs())))
    if (mySeq !== seq.value) return
    counts.value = d || {}
  } catch { /* 徽章失败不画 */ }
}

function flagIds() {
  if (!cartonMode.value) return items.value.map((p) => String(p.id))
  return groups.value.flatMap((g) => (g.photos || []).map((p) => String(p.id)))
}

async function load(reset) {
  const mySeq = ++seq.value
  if (reset) page.value = Math.max(1, page.value)   // 页码由调用方决定，这里不重置
  loading.value = true
  const pCounts = loadCounts(mySeq)
  let d
  try {
    const path = cartonMode.value ? '/api/photos/carton-groups' : '/api/photos'
    const params = cartonMode.value
      ? Object.assign({}, baseQs(), { limit: limitNow(), offset: (page.value - 1) * limitNow() })
      : listQs()
    d = await api(path + '?' + qs(params))
  } catch (e) {
    if (mySeq === seq.value) ElMessage.error('读取失败：' + e.message)
    loading.value = false
    return
  }
  if (mySeq !== seq.value) return
  const incoming = d.items || []
  if (cartonMode.value) {
    groups.value = incoming        // 页码分页：每页只有一页的量，不再追加
    openGroups.value = incoming.slice(0, 3).map((g) => g.key || g.carton_no)
  } else {
    items.value = incoming
  }
  total.value = d.total || 0
  // 末页越界（照片被标无效后末页空了）→ 退到最后一页
  const maxPage = Math.max(1, Math.ceil(total.value / limitNow()))
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
      if (tags.length) {
        flags.value = Object.fromEntries(tags.map(([pid, tl]) => [pid, tl || []]))
      }
    }).catch(() => { /* 角标失败不画 */ })
  }
  /* 角标要全库模糊匹配 + OCR 聚合，冷缓存 6.6s —— 不能挂在首屏上 */
  if (typeof requestIdleCallback === 'function') requestIdleCallback(run, { timeout: 2500 })
  else setTimeout(run, 1200)
}

function reload() { load(true) }
function resetFiltersLocal() {
  Object.assign(f, {
    state: '', kind: '', usage: '', q: '', todo: '',
    unlinked: 0, invalid: 'hide', pending: 0,
  })
  reload()
}
function toggleCarton() { cartonMode.value = !cartonMode.value }

async function loadPend() {
  if (!props.cid) { pend.value = null; return }
  try {
    pend.value = await api('/api/containers/' + props.cid + '/supervision-pending')
  } catch {
    pend.value = null    /* 读不到就不显示待确认入口，别让整页报错 */
  }
}

function prevTaken(id) {
  const i = items.value.findIndex((p) => String(p.id) === String(id))
  return i > 0 ? items.value[i - 1].taken_at : ''
}

/* 治理跑完：治理计数、照片角标、徽章、树都变了 —— 一次性重算 */
function onGovDone() {
  loadPend()
  reload()
  emit('changed')
}

function onCardClick(id) {
  if (s.on) {
    const k = String(id)
    if (s.ids.has(k)) s.ids.delete(k)
    else s.ids.add(k)
    s.version++
    return
  }
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

async function selectAllFiltered() {
  const params = Object.assign(baseQs(), { flag: tab.value, limit: 5000, offset: 0 })
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
  ids.forEach((x) => s.ids.add(x))
  s.version++
  ElMessage.success('已选中 ' + ids.length + ' 张（含未加载的页）')
}

async function afterBulk() {
  selClear(s)
  bulkKind.value = ''
  reload()
  emit('changed')
}

async function bulkInvalid(flag) {
  if (!s.ids.size) { ElMessage.warning('先勾选照片'); return }
  try {
    const r = await post('/api/photos/invalid',
      { photo_ids: [...s.ids], invalid: flag, by: 'web' })
    ElMessage.success((flag ? '已标记 ' : '已取消 ') + r.updated + ' 张无效照片')
    await afterBulk()
  } catch (e) { ElMessage.error('操作失败：' + e.message) }
}
async function bulkIgnore(flag) {
  if (!s.ids.size) { ElMessage.warning('先勾选照片'); return }
  try {
    const r = await post('/api/photos/ignore',
      { photo_ids: [...s.ids], ignored: flag, by: 'web' })
    ElMessage.success((flag ? '已忽略 ' : '已恢复 ') + r.updated + ' 张照片')
    await afterBulk()
  } catch (e) { ElMessage.error('操作失败：' + e.message) }
}
async function applyKind() {
  if (!bulkKind.value) { ElMessage.warning('先选要改成哪个分类'); return }
  if (!s.ids.size) { ElMessage.warning('先勾选照片'); return }
  try {
    const r = await post('/api/photos/kind', { photo_ids: [...s.ids], kind: bulkKind.value })
    ElMessage.success('已把 ' + r.updated + ' 张改判为「' + kindName(bulkKind.value) + '」')
    await afterBulk()
  } catch (e) { ElMessage.error('改判失败：' + e.message) }
}

/* ── 监装细分待确认：三个动作，都走既有端点 ── */
async function markSup(pid) {
  try {
    await patch('/api/photos/' + pid + '/usage', { usage: '监装' })
    ElMessage.success('已标为监装照 —— 现在可以确认细分了')
    await supReload()
  } catch (e) { ElMessage.error('标用途失败：' + e.message) }
}
async function setSupTag(pid, tag) {
  try {
    await post('/api/photos/supervision-tag', { photo_ids: [pid], tag })
    ElMessage.success('细分已确认')
    await supReload()
  } catch (e) { ElMessage.error('确认失败：' + e.message) }
}
async function acceptAi(pid) {
  try {
    await post('/api/photos/supervision-tag/accept-ai', { photo_ids: [pid] })
    ElMessage.success('已采用建议：' + labelOf(supOf(pid).ai_tag))
    await supReload()
  } catch (e) { ElMessage.error('采用失败：' + e.message) }
}
async function adoptAllAi() {
  const ids = ((pend.value && pend.value.items) || [])
    .filter((x) => x.usage === '监装' && x.ai_tag).map((x) => String(x.photo_id))
  if (!ids.length) return
  try {
    await ElMessageBox.confirm('把 ' + ids.length + ' 张监装照全部采用模型建议的细分？',
      '批量采用建议', { type: 'warning' })
  } catch { return }
  try {
    await post('/api/photos/supervision-tag/accept-ai', { photo_ids: ids })
    ElMessage.success('已批量采用 ' + ids.length + ' 张建议')
    await supReload()
  } catch (e) { ElMessage.error('批量采用失败：' + e.message) }
}
/* 待办动作后统一刷新：先重拉待办数据，再重筛网格 —— 只刷数据不重筛的话，
   确认过的那张还挂在待确认视图里（旧版 2026-10-14 修过）。 */
async function supReload() {
  await loadPend()
  reload()
  emit('changed')
}

/* ── 低频工具：清理清单/包装照、重复图片 ── */
async function onMore(cmd) {
  if (cmd === 'clean') {
    cleanErr.value = ''
    clean.value = null
    cleanVisible.value = true
    try {
      clean.value = await api('/api/photos/auto-invalid?container_id=' + props.cid)
      if (!clean.value.total) {
        cleanErr.value = '没有识别到待清理的清单 / 包装照'
      }
    } catch (e) { cleanErr.value = '读取失败：' + e.message }
    return
  }
  dupErr.value = ''
  dup.value = null
  dupPicked.value = []
  dupVisible.value = true
  try {
    dup.value = await api('/api/photos/dups?container_id=' + props.cid)
    if (!(dup.value.groups || []).length) {
      dupErr.value = dup.value.remaining
        ? '相似指纹还在计算（剩 ' + dup.value.remaining + ' 张），请稍后再点一次'
        : '没发现相似的重复照片'
    } else {
      /* 默认全勾：建议保留张已由后端定好，其余就是重复的 */
      ;(dup.value.groups || []).forEach((g) => {
        (g.others || []).forEach((o) => dupPicked.value.push(String(o.id)))
      })
    }
  } catch (e) { dupErr.value = '读取失败：' + e.message }
}

async function doClean() {
  busy2.value = true
  let n = 0
  try {
    /* 端点一次限 500 → 分批 */
    for (let i = 0; i < clean.value.ids.length; i += 400) {
      const r = await post('/api/photos/invalid',
        { photo_ids: clean.value.ids.slice(i, i + 400), invalid: true })
      n += r.updated || 0
    }
    ElMessage.success('已把 ' + n + ' 张标为无效')
    cleanVisible.value = false
    reload()
    emit('changed')
  } catch (e) {
    ElMessage.error('操作失败：' + e.message)
  } finally {
    busy2.value = false
  }
}

async function doDup() {
  busy2.value = true
  let n = 0
  try {
    for (let i = 0; i < dupPicked.value.length; i += 400) {
      const r = await post('/api/photos/invalid',
        { photo_ids: dupPicked.value.slice(i, i + 400), invalid: true })
      n += r.updated || 0
    }
    ElMessage.success('已把 ' + n + ' 张重复照片标为无效')
    dupVisible.value = false
    reload()
    emit('changed')
  } catch (e) {
    ElMessage.error('操作失败：' + e.message)
  } finally {
    busy2.value = false
  }
}

watch(() => props.cid, async (id) => {
  f.container_id = id
  f.state = ''; f.kind = ''; f.usage = ''; f.q = ''; f.todo = ''
  f.unlinked = 0; f.invalid = 'hide'; f.pending = 0
  tab.value = ''
  cartonMode.value = false
  selSetMode(false, s)
  items.value = []
  groups.value = []
  await loadPend()
  reload()
})
watch([tab, cartonMode], () => { items.value = []; groups.value = []; reload() })

/* 抽屉里改判/关联/忽略后：列表 + 树 + 徽章统一重算（数字同源）。
   需求10：页码不动，stay 在当前页。 */
const offWizChanged = bus.on('photos:changed', () => { reload(); loadPend() })

onMounted(async () => {
  await loadPend()
  reload()
  await nextTick()
  // ⚠️ 首次是按兜底 PAGE(60) 取的；量出真实「一屏几张」后**必须重取**，
  //    否则列表还是 60 张、分页控件却按 16 算（页码对不上，翻页看着没反应）。
  const before = pageSize.value
  measurePageSize()
  if(pageSize.value !== before){ page.value = 1; load(true) }
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  offWizChanged()
})

function onResize() { measurePageSize() }
</script>

<style scoped>
.w-photos { display: flex; flex-direction: column; gap: 12px; }
.wd-h { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.wd-h .spacer { flex: 1; }
/* 左右两栏：树是**带边框的白卡**、sticky 跟随滚动（原来是一条裸的 210px 列，
   与右侧网格糊在一起，「排版很乱」的主因就是这里 —— 没有边界就分不清区域）。 */
.prow { display: flex; gap: 14px; align-items: flex-start; }
/* 🔴 sticky 元素**自己**不能带 overflow:auto —— 那样 sticky 在自己身上不生效，
   往下滚树就跟着往上滑走（不是「差一点冻住」，是完全没冻）。
   高度约束与内部滚动交给里面的 PhotoTree（见下一行）。 */
.ptree-wrap {
  flex: 0 0 200px; position: sticky; top: 16px; align-self: start;
  background: var(--pl-panel); border: 1px solid var(--pl-line);
  border-radius: 8px; padding: 8px 6px;
  overflow: visible;
}
.ptree-wrap > :deep(*) {
  max-height: calc(100vh - 64px); overflow: auto;
}
.pmain { flex: 1; min-width: 0; }
/* 工具条：与选项卡/网格之间给一条明确的分隔，控件不再悬空 */
.wclbar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding-bottom: 10px; margin-bottom: 8px;
  border-bottom: 1px solid var(--pl-line-2);
}
.wclbar .tgrp { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.wclbar .spacer { flex: 1; }
.ptabs :deep(.el-tabs__header) { margin-bottom: 0; }
.tab-label { display: inline-flex; align-items: center; gap: 6px; }
/* 网格区域：2026-10-21 老板标注「不要滚动条」—— 取消内部限高滚动，
   改成整页自然滚动（18 张/页本来就一屏放得下） */
.grid-body { margin-top: 6px; overflow: visible; }
.shot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
/* 2026-10-21：卡片收窄，每行多列，compact 图片高度 110px */
.shot-grid :deep(.shot.compact img) { height: 110px; }
.shot-grid :deep(.shot.compact .meta) { display: block; font-size: 11px; color: #fff;
  background: rgba(0,0,0,.55); padding: 3px 5px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
/* compact 模式下也显示产品编码（原来被 .shot.compact .codes { display:none } 隐藏） */
.shot-grid :deep(.shot.compact .codes) { display: block; }
.shot-wrap { display: flex; flex-direction: column; }
.more-row { display: flex; align-items: center; gap: 10px; justify-content: center;
  padding: 8px 0; border-top: 1px solid var(--pl-line-2); margin-top: 4px; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; font-weight: normal; }
.err { color: var(--el-color-danger); font-size: 13px; }
.ghead { display: flex; align-items: center; gap: 10px; }
.gcover { width: 56px; height: 56px; object-fit: cover; border-radius: 4px; }
.ginfo { flex: 1; min-width: 0; }
.gtitle { display: flex; gap: 10px; align-items: baseline; }
.gcount { font-weight: 600; }
.gtime { font-size: 12px; color: var(--el-text-color-secondary); }
.gsum { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 2px; }
/* 待确认细分的卡片操作行 */
.supact { margin-top: -4px; }
.supact-row { display: flex; align-items: center; gap: 4px; }
.supact-row .tag.acc { font-size: 11px; color: var(--el-color-primary); }
.selbar {
  position: fixed; left: 216px; right: 16px; bottom: 12px; z-index: 100;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 12px; border-radius: 8px;
  background: var(--el-bg-color-overlay); border: 1px solid var(--el-border-color);
  box-shadow: 0 -2px 10px rgba(0, 0, 0, .08);
}
.selbar .spacer { flex: 1; }
.dupgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 8px; }
.duprow { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter); }
.dupcell { text-align: center; font-size: 11px; }
.dupcell img { width: 96px; height: 72px; object-fit: cover; border-radius: 4px;
  border: 2px solid transparent; }
.dupcell.keep img { border-color: var(--el-color-success); }
.dupcell .tag { display: block; color: var(--el-text-color-secondary); margin-top: 2px; }
.dupcell .tag.ok { color: var(--el-color-success); }
</style>