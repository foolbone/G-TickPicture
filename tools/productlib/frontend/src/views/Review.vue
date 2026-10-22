<template>
  <div class="review-page">
    <el-card shadow="never">
      <template #header>
        <div class="phead">
          <h2>新产品确认<span class="sub">照片里读出、但产品库里没有的编码</span></h2>
          <span class="spacer"></span>
          <el-select v-model="batch" placeholder="全部批次" clearable style="width:260px"
                     @change="load">
            <el-option v-for="b in batches" :key="b.id" :value="b.id"
                       :label="(b.container_no ? '【' + b.container_no + '】' : '') + (b.name || b.id)
                              + '（' + (b.unique || b.item_count || 0) + ' 张）'" />
          </el-select>
          <el-tag size="small" type="info">候选 {{ items.length }}</el-tag>
          <el-button size="small" @click="batchAll">全部确认入库</el-button>
          <el-button size="small" @click="load">刷新候选</el-button>
        </div>

        <!-- 批量条：勾选后出现（没有勾选就占位，页面高度不跳） -->
        <div class="batchbar" :class="{ on: !!picked.length }">
          <span class="faint">共 {{ items.length }} 个候选，已选 {{ picked.length }}</span>
          <span class="spacer"></span>
          <el-button size="small" :disabled="!picked.length" @click="batchConfirm">确认选中</el-button>
          <el-button size="small" :disabled="!picked.length" @click="batchIgnore">忽略选中</el-button>
        </div>

        <div class="faint hint">
          这些编码不在已导入清单中，<b>不会进本柜报告</b> —— 本柜优先处理「待确认关联」；
          对应清单在后续柜导入时会自动关联这些照片，不急。
          <template v-if="ignored">已忽略 {{ ignored }} 个候选编码（忽略后不再出现）。</template>
        </div>
      </template>

      <div v-loading="loading">
        <div v-for="p in items" :key="p.code" class="dccard" :data-code="p.code">
          <div class="row">
            <el-checkbox :model-value="picked.includes(p.code)"
                         @change="(v) => togglePick(p.code, v)" />
            <el-tag size="small" :type="confType(p.confidence)">
              置信 {{ Math.round(p.confidence * 100) }}%
            </el-tag>
            <el-tag size="small">{{ srcName(p.sources) }}</el-tag>
            <el-tag size="small" type="info">{{ p.photo_count }} 张照片</el-tag>
            <span class="code">{{ p.raw }}</span>
            <span v-if="p.raw !== p.code" class="faint">归一 {{ p.code }}</span>
            <span class="spacer"></span>
            <el-button size="small" @click="toggleEdit(p.code)">确认入库</el-button>
            <el-tooltip placement="top"
                        content="永久忽略这个编码（之后任何照片读出它都不再出现）">
              <el-button size="small" text @click="ignoreOne(p.code)">忽略编码</el-button>
            </el-tooltip>
            <el-tooltip placement="top"
                        content="本次忽略：这些照片退出关联队列，新产品先不入库；可在照片库「已忽略」档恢复，后续柜导入同一编码时会自动关联">
              <el-button size="small" text @click="skipOne(p)">本次忽略</el-button>
            </el-tooltip>
          </div>

          <div class="thumbs">
            <figure v-for="id in p.photo_ids.slice(0, 8)" :key="id" class="thumb-w"
                    :title="(p.photo_times || {})[id] || '无 EXIF 时间'">
              <img class="thumb" :src="'/thumb/' + id" :alt="id" @click="view(id, p)" />
              <figcaption>{{ fmtTaken((p.photo_times || {})[id], { clock: true }) }}</figcaption>
            </figure>
          </div>

          <!-- 入库表单：展开后填品名/规格，语义与旧版 dc-edit 一致 -->
          <div v-if="editing === p.code" class="edit">
            <span class="faint">确认写入产品库：</span>
            <span class="code">{{ p.code }}</span>
            <el-input v-model="form.name" placeholder="品名（选填，建议填）" style="width:220px" />
            <el-input v-model="form.spec" placeholder="规格（选填）" style="width:200px" />
            <el-button size="small" type="primary" @click="save(p)">保存入库</el-button>
            <el-button size="small" text @click="editing = ''">取消</el-button>
          </div>
        </div>

        <el-empty v-if="!loading && !items.length"
                  description="没有新产品候选 —— 照片里读出的编码都已在产品库，或这个批次还没跑治理">
          <el-button size="small" type="primary" @click="$router.push('/wizard')">去跑治理</el-button>
        </el-empty>
      </div>
    </el-card>

    <PhotoViewer v-if="viewerSrc" :src="viewerSrc" :pid="viewerPid"
                 :cap="viewerCap" :taken-at="viewerTaken" @close="viewerSrc = ''" />
  </div>
</template>

<script setup>
/* Review.vue —— 新产品确认档（对应旧版 discover.js + #tab-review 的 rt-dc）
 *
 * 只有「发现新产品」一块：合并建议面板旧版 HTML 里已经没有了（revTabs 只剩
 * dc 一个），所以这里也只有一块，不凭空补一个页签。
 *
 * 🔴 三种「不处理」的区别必须在文案里说清，否则用户以为按了就没了：
 *   确认入库 = 写产品库 + 来源照片自动关联；
 *   忽略编码 = 永久拉黑该编码；
 *   本次忽略 = 只把这批照片退出队列（可恢复，后续柜导入同编码会自动关联）。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, post } from '../api.js'
import { fmtTaken } from '../lib/core.js'
import PhotoViewer from '../components/PhotoViewer.vue'

const items = ref([])
const batches = ref([])
const ignored = ref(0)
const batch = ref('')
const loading = ref(false)
const picked = ref([])
const editing = ref('')
const form = reactive({ name: '', spec: '' })

const viewerSrc = ref('')
const viewerPid = ref('')
const viewerCap = ref('')
const viewerTaken = ref('')

const confType = (c) => (c >= 0.85 ? 'success' : c >= 0.7 ? 'warning' : 'danger')
const srcName = (s) => {
  const a = s || []
  return a.includes('vision') && a.includes('ocr')
    ? '多模态+OCR' : (a.includes('vision') ? '多模态读码' : 'OCR')
}

async function load() {
  loading.value = true
  try {
    const url = '/api/discover' + (batch.value ? '?batch=' + encodeURIComponent(batch.value) : '')
    const d = await api(url)
    items.value = d.items || []
    ignored.value = d.ignored || 0
    picked.value = picked.value.filter((c) => items.value.some((x) => x.code === c))
    editing.value = ''
  } catch (e) { /* api() 已弹错 */ } finally { loading.value = false }
}

async function loadBatches() {
  try {
    const d = await api('/api/batches?kind=photos')
    batches.value = d.items || []
  } catch { /* 静默：筛选框空着也能用 */ }
}

function togglePick(code, v) {
  const i = picked.value.indexOf(code)
  if (v && i < 0) picked.value = [...picked.value, code]
  if (!v && i >= 0) picked.value = picked.value.filter((x) => x !== code)
}

function toggleEdit(code) {
  if (editing.value === code) { editing.value = ''; return }
  editing.value = code
  form.name = ''
  form.spec = ''
}

async function save(p) {
  try {
    const r = await post('/api/products/from-photo', {
      code: p.code, name: form.name.trim(), spec: form.spec.trim(),
      photo_ids: p.photo_ids || [], by: 'user',
    })
    ElMessage.success('已入库 ' + p.code + '，自动关联 ' + r.linked + ' 张来源照片')
    editing.value = ''
    await load()
  } catch { /* api() 已弹错 */ }
}

async function ignoreOne(code) {
  try {
    await ElMessageBox.confirm('忽略编码 ' + code + '？之后不再出现在发现列表。', '忽略编码',
      { type: 'warning' })
  } catch { return }
  try {
    await post('/api/discover/ignore', { code })
    await load()
  } catch { /* api() 已弹错 */ }
}

async function skipOne(p) {
  const ids = p.photo_ids || []
  if (!ids.length) { ElMessage.warning('这个候选没有来源照片'); return }
  try {
    await ElMessageBox.confirm('本次忽略 ' + p.code + ' 的 ' + ids.length + ' 张照片？\n\n'
      + '这些照片会退出关联队列（新产品先不入库），可在照片库「已忽略」档恢复；'
      + '后续柜导入同一编码时会自动关联上。', '本次忽略', { type: 'warning' })
  } catch { return }
  try {
    const r = await post('/api/photos/ignore', { photo_ids: ids, ignored: true, by: 'web' })
    ElMessage.success('已忽略 ' + r.updated + ' 张照片')
    await load()
  } catch { /* api() 已弹错 */ }
}

async function batchConfirm() {
  const codes = [...picked.value]
  if (!codes.length) return ElMessage.warning('先勾选要确认的候选')
  try {
    await ElMessageBox.confirm('把选中的 ' + codes.length + ' 个候选编码确认入库？'
      + '（仍会按各自来源照片自动关联）', '批量确认入库', { type: 'warning' })
  } catch { return }
  await runBatch(codes, '确认')
}

async function batchIgnore() {
  const codes = [...picked.value]
  if (!codes.length) return ElMessage.warning('先勾选要忽略的候选')
  try {
    await ElMessageBox.confirm('忽略选中的 ' + codes.length + ' 个候选？（之后不再出现）',
      '批量忽略', { type: 'warning' })
  } catch { return }
  await runBatch(codes, '忽略')
}

/* 批量逐个发：单个失败不打断整批（跟旧版一致），最后报实数 */
async function runBatch(codes, mode) {
  let ok = 0
  for (const code of codes) {
    const p = items.value.find((x) => x.code === code)
    if (!p) continue
    try {
      if (mode === '确认') {
        await post('/api/products/from-photo',
          { code, name: '', spec: '', photo_ids: p.photo_ids || [], by: 'user' })
      } else {
        await post('/api/discover/ignore', { code })
      }
      ok++
    } catch { /* 跳过单个失败 */ }
  }
  ElMessage.success('已批量' + mode + ' ' + ok + ' / ' + codes.length + ' 个')
  await load()
}

async function batchAll() {
  const codes = items.value.map((x) => x.code)
  if (!codes.length) return
  try {
    await ElMessageBox.confirm('把全部 ' + codes.length + ' 个候选编码确认入库？'
      + '（仍会按各自来源照片自动关联）', '全部确认入库', { type: 'warning' })
  } catch { return }
  await runBatch(codes, '确认')
}

function view(id, p) {
  viewerPid.value = String(id)
  viewerSrc.value = '/img/' + id
  viewerCap.value = p.raw
  viewerTaken.value = (p.photo_times || {})[id] || ''
}

onMounted(async () => {
  await loadBatches()
  await load()
})
</script>

<style scoped>
.review-page { max-width: 100%; margin: 0 auto; }
.phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.phead h2 { margin: 0; font-size: 17px; }
.phead .sub { margin-left: 10px; font-size: 12px; font-weight: normal;
  color: var(--el-text-color-secondary); }
.phead .spacer, .row .spacer, .batchbar .spacer { flex: 1; }
.batchbar { display: flex; align-items: center; gap: 8px; margin-top: 8px;
  padding: 6px 10px; border: 1px dashed var(--el-border-color); border-radius: 4px;
  opacity: .45; transition: opacity .15s; }
.batchbar.on { opacity: 1; border-style: solid; }
.hint { margin-top: 8px; line-height: 1.6; }
.dccard { border: 1px solid var(--el-border-color-lighter); border-radius: 5px;
  padding: 8px 10px; margin-bottom: 8px; }
.dccard .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.thumbs { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.thumb-w { margin: 0; width: 104px; }
.thumb-w .thumb { width: 104px; height: 78px; object-fit: cover; border-radius: 4px;
  cursor: zoom-in; background: var(--el-fill-color); }
.thumb-w figcaption { font-size: 11px; color: var(--el-text-color-secondary);
  text-align: center; margin-top: 2px; }
.edit { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px;
  padding-top: 8px; border-top: 1px dashed var(--el-border-color); }
.code { font-family: ui-monospace, Menlo, Consolas, monospace; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>