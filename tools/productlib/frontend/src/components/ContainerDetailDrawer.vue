<template>
  <!-- 柜详情聚合面板（对应旧版 containers.js openContainer + index.html #ctDrawer）
       一个抽屉里给齐：柜信息编辑 / 就绪度 / 柜况代表图 / 批次列表 / 清单行核对。
       数据吃 /api/containers/{cid} —— 与报告页同源，数字不会漂。 -->
  <el-drawer :model-value="true" size="58%" direction="rtl" :with-header="false"
             @close="emit('close')">
    <div v-loading="loading" class="cd">
      <div class="cd-head">
        <b>{{ title }}</b>
        <span class="faint">{{ sub }}</span>
        <span class="spacer"></span>
        <el-button size="small" @click="emit('report', cid)">出报告</el-button>
        <el-button size="small" @click="load">刷新</el-button>
        <el-button size="small" @click="emit('close')">关闭</el-button>
      </div>

      <div v-if="d" class="cd-body">
        <!-- ① 柜信息（进报告 General Information）：改完显式保存 -->
        <div class="block">
          <h4>柜信息<span class="sub">进报告 General Information</span></h4>
          <div v-for="[k, lb] in META" :key="k" class="kv">
            <span class="k">{{ lb }}</span>
            <el-input v-model="draft[k]" :placeholder="PH[k]" size="small" />
          </div>
          <div class="kv"><span class="k">REMARKS</span>
            <el-input v-model="draft.remark" type="textarea" :rows="2" size="small" placeholder="可后补" />
          </div>
          <div class="row act">
            <el-button size="small" type="primary" :loading="saving" @click="saveMeta">保存柜信息</el-button>
            <span class="faint">{{ saveMsg }}</span>
          </div>
        </div>

        <!-- ② 就绪度 -->
        <div class="block">
          <h4>就绪度</h4>
          <div class="row">
            <el-tag size="small" effect="plain">清单行 {{ d.row_total || 0 }}</el-tag>
            <el-tag v-if="d.row_unchecked" size="small" type="warning">未核对 {{ d.row_unchecked }}</el-tag>
            <el-tag v-else-if="d.row_total" size="small" type="success">清单已核对</el-tag>
            <el-tag v-else size="small" type="warning">还没导清单</el-tag>
            <el-tag size="small" effect="plain">预检照片 {{ ps['预检'] || 0 }} · 监装照片 {{ ps['监装'] || 0 }}</el-tag>
            <el-tag size="small" :type="nCond === 4 ? 'success' : 'warning'">柜况图 {{ nCond }}/4</el-tag>
            <el-tag v-if="st['truck_head']" size="small" type="success">卡车头 1</el-tag>
            <el-tag v-else size="small" type="warning">缺卡车头</el-tag>
          </div>
        </div>

        <!-- ③ 作业时长（2026-10-20 老板需求）：按连拍分组切段，逐段给起止/耗时。
             不对全柜取 MIN/MAX —— 跨 3 天的柜会报出「作业 334 小时」的假结论。 -->
        <div class="block">
          <h4>作业时长<span class="sub">按连拍分组切段；时间取自文件写入时刻的段会标出来</span></h4>
          <div v-if="!d.work" class="faint">这个柜还没有带拍摄时间的照片。</div>
          <template v-else>
            <div class="wsum">
              <span class="wsum-r">{{ workRange(d.work) }}</span>
              <span class="wsum-d">{{ workDur(d.work) }}</span>
              <el-tag v-if="!d.work.trusted" size="small" type="warning">时间取自文件</el-tag>
              <el-tag v-if="d.work.scattered" size="small" type="warning">数据零散</el-tag>
            </div>
            <el-table :data="segsShown" size="small">
              <el-table-column label="作业段" min-width="160">
                <template #default="{ row }">
                  <span class="mono">{{ fmtTaken(row.from, { full: true }) }}</span>
                  <span class="faint"> ~ </span>
                  <span class="mono">{{ fmtTaken(row.to, { clock: true }) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="耗时" width="90" align="right">
                <template #default="{ row }">
                  <span v-if="row.wide" class="faint"
                        title="这一段的时间跨度超过 12 小时，不是连续作业，是数据零散">不可用</span>
                  <span v-else>{{ fmtDur(row.span_sec) || '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="照片" width="70" align="right">
                <template #default="{ row }">{{ row.n }}</template>
              </el-table-column>
              <el-table-column label="时间来源" width="100" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.trusted ? 'success' : 'warning'">
                    {{ row.trusted ? '拍摄时刻' : '文件时刻' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="segMore" class="row act">
              <el-button size="small" text @click="segLimit = 0">展开全部 {{ segTotal }} 段</el-button>
              <span class="faint">默认只显示最近 10 段</span>
            </div>
            <div v-else-if="segTotal > 10" class="faint hint">
              共 {{ segTotal }} 段，只显示最近 {{ segLimit }} 段
              <a class="clink" @click="segLimit = 0">展开全部</a>
            </div>
          </template>
        </div>

        <!-- ④ 柜况代表图（每类最新一张；报告④直接用这些） -->
        <div class="block">
          <h4>柜况代表图<span class="sub">每类取最新一张，在照片详情里给监装照打标签即可换</span></h4>
          <div class="condgrid">
            <div v-for="[tag, lb] in COND" :key="tag" :class="['condslot', { missing: !cond[tag] }]"
                 @click="cond[tag] && openPhoto(cond[tag].id)">
              <template v-if="cond[tag]">
                <img :src="'/thumb/' + cond[tag].id" :alt="lb" />
                <div class="cl">{{ lb }}</div>
              </template>
              <template v-else>
                <div class="cl">{{ lb }}<br /><span class="faint">未打标</span></div>
              </template>
            </div>
          </div>
          <div class="faint hint">打标入口：照片库 → 监装照片详情 → 「监装细分」。</div>
        </div>

        <!-- ④ 批次（清单批次可展开核对行；照片批次跳照片库） -->
        <div class="block">
          <h4>批次（{{ d.batches.length }}）</h4>
          <div v-if="!d.batches.length" class="faint">
            这个柜还没有任何批次 —— 去「照片库」导照片，或「产品库」导清单（记得选柜）。
          </div>
          <el-table v-else :data="d.batches" size="small">
            <el-table-column label="批次" min-width="150">
              <template #default="{ row }">
                <div>{{ row.name || row.id }}</div>
                <div class="faint mono">{{ row.id }}</div>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="70" align="center">
              <template #default="{ row }">
                <el-tag size="small">{{ row.kind === 'checklist' ? '清单' : '照片' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="数量" width="90">
              <template #default="{ row }">
                {{ row.kind === 'checklist' ? (row.rows + ' 行') : (row.stats.uniq + '/' + row.stats.total) }}
              </template>
            </el-table-column>
            <el-table-column label="时间" width="150">
              <template #default="{ row }">
                <span class="faint">{{ (row.created_at || '').replace('T', ' ').slice(0, 16) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110">
              <template #default="{ row }">
                <el-button v-if="row.kind === 'checklist'" size="small" text @click="toggleRows(row)">
                  {{ rowsOpen[row.id] ? '收起核对' : '核对清单' }}</el-button>
                <el-button v-else size="small" text @click="viewBatch(row)">看照片</el-button>
              </template>
            </el-table-column>
            <template #append>
              <tr v-for="r in openedRows" :key="'rows-' + r.batchId">
                <td colspan="5" class="rows-cell">
                  <div v-if="rowLoading[r.batchId]" class="faint">读取行快照…</div>
                  <div v-else-if="!rowItems[r.batchId] || !rowItems[r.batchId].length" class="faint">
                    这个批次没有行快照（旧清单导入，重导一次即可生成）。
                  </div>
                  <template v-else>
                    <el-table :data="rowItems[r.batchId]" size="small" :max-height="420">
                      <el-table-column prop="seq" label="#" width="44" />
                      <el-table-column prop="code" label="编码" width="150" />
                      <el-table-column prop="name" label="品名" min-width="120" />
                      <el-table-column prop="package_no" label="箱号" width="110">
                        <template #default="{ row }"><span class="faint">{{ row.package_no || '' }}</span></template>
                      </el-table-column>
                      <el-table-column prop="order_qty" label="Order" width="60" />
                      <el-table-column prop="loading_qty" label="Loading" width="80" />
                      <el-table-column label="核对" width="110">
                        <template #default="{ row }">
                          <el-input :model-value="row.check_result || ''" size="small" placeholder="PASS/FAIL"
                                    @update:model-value="setCheck(row, $event)" />
                        </template>
                      </el-table-column>
                    </el-table>
                    <div class="row act">
                      <el-button size="small" type="primary" :loading="savingRows"
                                 @click="saveRows(r.batchId)">保存核对结论</el-button>
                      <span class="faint">空的 = 未核对，报告里留空（清单预填的 PASS 只作显示，不算我们核对过）</span>
                    </div>
                  </template>
                </td>
              </tr>
            </template>
          </el-table>
        </div>
      </div>
    </div>

    <!-- 柜况代表图点开大图（对齐旧版 openCondImg：直接盖大图，不进照片库） -->
    <PhotoViewer v-if="viewerSrc" :src="viewerSrc" @close="viewerSrc = ''" />
  </el-drawer>
</template>

<script setup>
/* ContainerDetailDrawer.vue —— 柜详情聚合面板
 *
 * 布局与旧版 #ctDrawer 一致：柜信息 → 就绪度 → 柜况代表图 → 批次（含清单行核对）。
 * 元数据保存走 PUT /api/containers/{cid}（与向导①同一份端点，数字不漂）；
 * 清单行核对 POST /api/checklist/rows/check（只写人工结论，绝不自动填 PASS）。
 */
import { ref, reactive, computed, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, post, put } from '../api.js'
import { filters, bus } from '../lib/photosStore.js'
import { fmtDur, fmtTaken, workRange, workDur } from '../lib/core.js'
import PhotoViewer from './PhotoViewer.vue'

const props = defineProps({ cid: { type: String, required: true } })
const emit = defineEmits(['close', 'report'])

const router = useRouter()

const COND = [
  ['empty_container', '空柜（Empty container）'],
  ['container_side', '柜侧（Container No.）'],
  ['container_seal', '封条（Seal No.）'],
  ['container_lock', '锁门（Locked door）'],
]
const META = [
  ['seal_no', '封条号'], ['arrival_at', '到柜时间'], ['departure_at', '离柜时间'],
  ['inspector', 'Inspector'], ['location', 'Location'], ['product_name', 'Product'],
  ['client_name', 'Client'],
]
const PH = {
  seal_no: 'Seal No.', arrival_at: '2026-09-27 09:12', departure_at: '2026-09-27 18:40',
  inspector: '', location: '', product_name: '', client_name: '',
}

const loading = ref(false)
const d = ref(null)
const draft = reactive({})
const saving = ref(false)
const saveMsg = ref('')
const rowsOpen = reactive({})     // batchId → bool
const rowLoading = reactive({})
const rowItems = reactive({})     // batchId → rows
const checkEdits = reactive({})   // batchId:seq → value
const savingRows = ref(false)
/* 柜况代表图点开大图 */
const viewerSrc = ref('')

const title = computed(() => (d.value && d.value.is_uncategorized ? '（未分柜）' : (d.value && d.value.container_no) || '柜'))
const sub = computed(() => {
  const dd = d.value
  if (!dd) return ''
  return [dd.seal_no ? '封条 ' + dd.seal_no : '', dd.client_name || ''].filter(Boolean).join(' · ')
})
const ps = computed(() => d.value && d.value.photo_stats || {})

/* 作业段明细：默认只铺最近 10 段 —— 后端最多回传 60 段（历史图片那种
   兜底柜有 495 段），全摊开会把抽屉撑到几千行。0 = 展开全部。 */
const segLimit = ref(10)
const segTotal = computed(() => (d.value && d.value.work_segments_total) || 0)
const segsShown = computed(() => {
  const a = (d.value && d.value.work_segments) || []
  return segLimit.value > 0 ? a.slice(-segLimit.value) : a
})
const segMore = computed(() => !segLimit.value && segTotal.value > 10)
const st = computed(() => d.value && d.value.supervision_tags || {})
const cond = computed(() => d.value && d.value.condition_photos || {})
const nCond = computed(() => Object.values(cond.value).filter(Boolean).length)
const openedRows = computed(() => d.value.batches.filter((b) => b.kind === 'checklist' && rowsOpen[b.id]).map((b) => ({ batchId: b.id })))

async function load() {
  loading.value = true
  try {
    d.value = await api('/api/containers/' + props.cid)
    segLimit.value = 10
    Object.keys(draft).forEach((k) => delete draft[k])
    META.forEach(([k]) => { draft[k] = d.value[k] || '' })
    draft.remark = d.value.remark || ''
    saveMsg.value = ''
  } catch (e) {
    ElMessage.error('读取柜详情失败：' + e.message)
  } finally { loading.value = false }
}
watch(() => props.cid, load, { immediate: true })

async function saveMeta() {
  const payload = {}
  META.forEach(([k]) => { payload[k] = (draft[k] || '').trim() || null })
  payload.remark = (draft.remark || '').trim() || null
  saving.value = true
  try {
    await put('/api/containers/' + props.cid, payload)
    saveMsg.value = '已保存'
    Object.assign(d.value, payload)
    setTimeout(() => { saveMsg.value = '' }, 1500)
    emit('saved')
  } catch (e) {
    saveMsg.value = '保存失败：' + e.message
  } finally { saving.value = false }
}

/* ── 清单行核对（行快照直接展开；结论显式保存）── */
async function toggleRows(b) {
  const bid = b.id
  rowsOpen[bid] = !rowsOpen[bid]
  if (rowsOpen[bid] && rowItems[bid] === undefined) {
    rowLoading[bid] = true
    try {
      const r = await api('/api/containers/' + props.cid + '/checklist?batch=' + encodeURIComponent(bid))
      rowItems[bid] = r.items || []
    } catch (e) {
      rowItems[bid] = []
      ElMessage.error('读取失败：' + e.message)
    } finally { rowLoading[bid] = false }
  }
}
function setCheck(row, v) {
  checkEdits[row.batch_id + ':' + row.seq] = v
}
async function saveRows(bid) {
  const items = rowItems[bid] || []
  let n = 0, err = ''
  savingRows.value = true
  try {
    for (const r of items) {
      const key = bid + ':' + r.seq
      const val = (checkEdits[key] !== undefined ? checkEdits[key] : r.check_result || '').trim()
      if (val === (r.check_result || '')) continue
      await post('/api/checklist/rows/check', { batch_id: bid, seq: r.seq, check_result: val })
      r.check_result = val
      delete checkEdits[key]
      n++
    }
    ElMessage.success('已保存 ' + n + ' 行核对结论')
    await load()
  } catch (e) {
    ElMessage.error('保存到第 ' + n + ' 项失败：' + e.message)
  } finally { savingRows.value = false }
}

/* ── 看照片 / 出报告 / 看大图 ── */
function viewBatch(b) {
  filters.batch = b.id
  router.push('/photos')
  emit('close')
}
function openPhoto(pid) {
  /* 柜况图点开看大图（不换页面，对齐旧版 openCondImg） */
  viewerSrc.value = '/view/' + pid
}

/* 抽屉内元数据改了 → 柜页列表刷新（unmount 时退订） */
const offChanged = bus.on('containers:changed', load)
onBeforeUnmount(offChanged)
</script>

<style scoped>
.cd { display: flex; flex-direction: column; height: 100%; }
/* 作业时长汇总行：起止（主）+ 时长（次），后面跟状态标签 */
.wsum { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 8px; }
.wsum-r { font-size: 13px; font-weight: 600; color: var(--el-text-color-primary); }
.wsum-d { font-size: 12px; color: var(--el-text-color-secondary); }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
.cd-head { display: flex; align-items: center; gap: 8px; padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-light); }
.cd-head .spacer { flex: 1; }
.cd-body { flex: 1; overflow: auto; padding: 10px 4px 40px; }
.block { border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  padding: 8px 10px; margin-bottom: 10px; }
.block h4 { margin: 0 0 8px; font-size: 13px; }
.block h4 .sub { margin-left: 8px; font-weight: normal; font-size: 12px;
  color: var(--el-text-color-secondary); }
.kv { display: flex; align-items: center; gap: 8px; margin: 6px 0; flex-wrap: wrap; }
.kv .k { width: 74px; flex: 0 0 74px; color: var(--el-text-color-secondary); font-size: 13px; }
.kv .el-input { flex: 1; min-width: 140px; }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.row.act { margin-top: 6px; }
.condgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; max-width: 520px; }
.condslot { position: relative; border: 1px solid var(--el-border-color-light); border-radius: 8px;
  overflow: hidden; cursor: pointer; background: var(--el-fill-color-lighter); }
.condslot img { width: 100%; height: calc(100% - 22px); object-fit: cover; display: block; min-height: 90px; }
.condslot .cl { font-size: 11px; padding: 3px 6px; background: #fff; border-top: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-regular); }
.condslot.missing { display: flex; align-items: center; justify-content: center; text-align: center;
  padding: 14px; min-height: 90px; }
.condslot.missing .cl { background: none; border: none; }
.hint { margin-top: 6px; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.rows-cell { padding: 8px 10px; background: var(--el-fill-color-lighter); }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
