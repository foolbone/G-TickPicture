<template>
  <div>
    <div v-if="!batches.length" class="faint">
      这个柜还没有清单批次 —— 在上面点「选择 Excel 导入」。
    </div>
    <template v-else>
      <div class="cl-bar">
        <el-select v-model="wiz.clBatch" size="small" style="width:240px" @change="onBatch">
          <el-option v-for="b in batches" :key="b.id" :value="b.id"
                     :label="(b.name || b.id) + '（' + (b.rows || 0) + ' 行）'" />
        </el-select>
        <span class="faint">全柜 {{ detail.row_total || 0 }} 行 · 未核对 {{ detail.row_unchecked || 0 }}</span>
        <span class="spacer"></span>
        <el-button size="small" type="primary" :disabled="!dirtyCount" :loading="saving"
                   @click="save">保存修改</el-button>
        <el-button size="small" :disabled="!dirtyCount" @click="reset">还原</el-button>
        <span class="faint">{{ dirtyCount ? ('有 ' + dirtyCount + ' 处未保存') : '' }}</span>
      </div>

      <el-table v-if="total" :data="pageRows" size="small" border stripe class="cl-table">
        <el-table-column prop="seq" label="#" width="52" />
        <el-table-column label="编码" width="170">
          <template #default="{ row }"><span class="ro" :title="row.code">{{ row.code }}</span></template>
        </el-table-column>
        <el-table-column label="品名" min-width="150">
          <template #default="{ row }">
            <el-input :model-value="cell(row, 'name')" @update:model-value="setCell(row, 'name', $event)"
                      size="small" placeholder="未填写"
                      :class="{ dirty: isDirty(row, 'name') }" />
          </template>
        </el-table-column>
        <el-table-column label="规格" width="150">
          <template #default="{ row }">
            <el-input :model-value="cell(row, 'spec')" @update:model-value="setCell(row, 'spec', $event)"
                      size="small" placeholder="—"
                      :class="{ dirty: isDirty(row, 'spec') }" />
          </template>
        </el-table-column>
        <el-table-column label="箱号" width="110">
          <template #default="{ row }"><span class="faint">{{ row.package_no || '—' }}</span></template>
        </el-table-column>
        <el-table-column label="Order" width="80">
          <template #default="{ row }"><span class="faint">{{ row.order_qty || '' }}</span></template>
        </el-table-column>
        <el-table-column label="Loading" width="96">
          <template #default="{ row }">
            <el-input :model-value="cell(row, 'loading_qty')" @update:model-value="setCell(row, 'loading_qty', $event)"
                      size="small" placeholder="—"
                      :class="{ dirty: isDirty(row, 'loading_qty') }" />
          </template>
        </el-table-column>
        <el-table-column label="核对" width="100">
          <template #default="{ row }">
            <el-input :model-value="cell(row, 'check_result')" @update:model-value="setCell(row, 'check_result', $event)"
                      size="small" placeholder="未核对"
                      :class="{ dirty: isDirty(row, 'check_result') }" />
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="faint">这个批次没有行快照（旧清单导入，重导一次即可生成）。</div>

      <div v-if="total" class="cl-pager">
        <el-button size="small" :disabled="wiz.clPage <= 0" @click="wiz.clPage--">‹ 上一页</el-button>
        <span class="faint">第 {{ wiz.clPage + 1 }} / {{ pages }} 页 · 本批 {{ total }} 行</span>
        <el-button size="small" :disabled="wiz.clPage >= pages - 1" @click="wiz.clPage++">下一页 ›</el-button>
      </div>

      <div class="cl-note faint">
        品名 / 规格保存后写入<b>产品库</b>的产品主记录 —— 和「产品库」页改的是同一份；
        Loading / 核对保存后写入本批次的<b>人工核对结论</b>（留空 = 未核对，
        报告沿用清单预填值，不会替你猜 PASS）。
      </div>
    </template>
  </div>
</template>

<script setup>
/* StepChecklist.vue —— ② 导入清单 / 清单内容可查看可编辑
 *
 * 每页 50 行（1000+ 行的柜不能一次渲染）。编辑缓冲 edits[seq][field]，
 * 脏判断只比当前页可见的行 —— 翻页不会丢改动（缓冲是全局的）。
 *
 * 保存时按字段分流：name/spec → 产品库（唯一真源），loading_qty/check_result
 * → 本批次人工核对结论（端点一次写两个字段，要一起带）。 */
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { wiz, CL_PAGE } from '../../lib/wizardStore.js'
import { loadChecklistRows, saveChecklistEdits } from '../../lib/checklist.js'

const props = defineProps({
  detail: { type: Object, required: true },
  cid: { type: String, required: true },
})
const emit = defineEmits(['dirty-change', 'saved'])

const batches = computed(() =>
  (props.detail.batches || []).filter((b) => b.kind === 'checklist'))
const total = computed(() => wiz.clRows.length)
const pages = computed(() => Math.max(1, Math.ceil(total.value / CL_PAGE)))
const pageRows = computed(() => {
  if (wiz.clPage > pages.value - 1) wiz.clPage = pages.value - 1
  return wiz.clRows.slice(wiz.clPage * CL_PAGE, wiz.clPage * CL_PAGE + CL_PAGE)
})

/* edits[seq] = {name, spec, loading_qty, check_result}（只存改过的） */
const edits = reactive({})
const saving = ref(false)

function orig(row, f) {
  const v = row[f]
  return v == null ? '' : String(v)
}
function cell(row, f) {
  const k = String(row.seq)
  if (!edits[k]) edits[k] = {}
  if (!(f in edits[k])) edits[k][f] = orig(row, f)
  return edits[k][f]
}
function setCell(row, f, v) {
  cell(row, f)
  edits[String(row.seq)][f] = v == null ? '' : String(v)
}
function isDirty(row, f) {
  return (edits[String(row.seq)] || {})[f] !== orig(row, f)
}
const dirtyCount = computed(() => {
  let n = 0
  Object.keys(edits).forEach((seq) => {
    const row = wiz.clRows.find((r) => String(r.seq) === seq)
    if (!row) return
    Object.keys(edits[seq]).forEach((f) => {
      if (edits[seq][f] !== orig(row, f)) n++
    })
  })
  return n
})

watch(dirtyCount, (n) => emit('dirty-change', n), { immediate: true })

async function reload() {
  Object.keys(edits).forEach((k) => delete edits[k])
  await loadChecklistRows(props.detail, props.cid, wiz)
}
watch(() => [props.cid, props.detail], reload, { immediate: true })

async function onBatch() {
  wiz.clFor = ''
  Object.keys(edits).forEach((k) => delete edits[k])
  await loadChecklistRows(props.detail, props.cid, wiz)
}

function reset() {
  Object.keys(edits).forEach((k) => delete edits[k])
  /* edits 是 reactive，delete 后 cell() 会从 orig 重新播种；这里再复制一次
     数组是为了强制 table 重算（行是同一批引用，v-model 不会自己回填）。 */
  wiz.clRows = wiz.clRows.slice()
}

async function save() {
  const prods = {}
  const rows = []
  Object.keys(edits).forEach((seq) => {
    const r = wiz.clRows.find((x) => String(x.seq) === seq)
    if (!r) return
    const e = edits[seq]
    /* 品名 / 规格 → 产品库 */
    ;['name', 'spec'].forEach((f) => {
      if (e[f] === orig(r, f)) return
      const cn = r.code_norm || r.code
      if (!cn) return
      if (!prods[cn]) prods[cn] = {}
      prods[cn][f] = (e[f] || '').trim()
    })
    /* Loading / 核对 → 本批次（端点一次写两个，所以先建再补） */
    const lq = e.loading_qty !== undefined && e.loading_qty !== orig(r, 'loading_qty')
    const ck = e.check_result !== undefined && e.check_result !== orig(r, 'check_result')
    if (!lq && !ck) return
    let t = rows.find((x) => x.seq === r.seq)
    if (!t) {
      t = {
        batch_id: r.batch_id, seq: r.seq,
        check_result: r.check_result || '', loading_qty: r.loading_qty || '',
      }
      rows.push(t)
    }
    if (lq) t.loading_qty = (e.loading_qty || '').trim()
    if (ck) t.check_result = (e.check_result || '').trim()
  })
  saving.value = true
  try {
    const r = await saveChecklistEdits(prods, rows)
    ElMessage.success('已保存：' + r.np + ' 个产品字段 / ' + r.nr + ' 行核对')
    Object.keys(edits).forEach((k) => delete edits[k])
    emit('saved')
  } catch (e) {
    ElMessage.error('保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}

defineExpose({ dirtyCount })
</script>

<style scoped>
.cl-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.cl-bar .spacer { flex: 1; }
.cl-table :deep(.el-input__inner) { padding: 0 6px; }
.dirty :deep(.el-input__inner) { border-color: var(--el-color-warning); }
.ro { color: var(--el-text-color-regular); }
.cl-pager { display: flex; align-items: center; gap: 10px; justify-content: center; margin: 10px 0; }
.cl-note { margin-top: 10px; line-height: 1.7; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
