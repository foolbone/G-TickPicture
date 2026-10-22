<template>
  <div class="batch-table">
    <div class="toolbar">
      <el-input v-model="iq" placeholder="搜批次名 / 批次 ID" clearable style="width:220px"
                @keyup.enter="reload" @clear="reload" />
      <el-select v-model="istate" style="width:130px" @change="reload">
        <el-option label="全部状态" value="" />
        <el-option label="待治理" value="pending" />
        <el-option label="已完成" value="done" />
        <el-option label="有失败" value="failed" />
      </el-select>
      <!-- 筛选标签行：条件常显可撤，别让人猜「现在筛着什么」 -->
      <template v-if="chips.length">
        <el-tag v-for="c in chips" :key="c.k" closable size="small" type="info"
                @close="dropChip(c.k)">{{ c.t }}</el-tag>
      </template>
      <span class="spacer"></span>
      <span class="faint">{{ filtered.length }} / {{ rows.length }} 个批次</span>
    </div>

    <div v-loading="loading">
      <el-table :data="filtered" size="small">
        <el-table-column label="批次" min-width="200">
          <template #default="{ row }">
            <div>{{ row.name || row.id }}</div>
            <div class="faint mono">{{ row.id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="柜号" width="100">
          <template #default="{ row }">
            <span v-if="row.container_no">{{ row.container_no }}</span>
            <span v-else class="faint dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="导入时间" width="150">
          <template #default="{ row }">
            <span class="faint">{{ (row.created_at || '').replace('T', ' ').slice(0, 16) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="照片（唯一/重复）" width="130">
          <template #default="{ row }">
            {{ row.unique }} <span class="faint">/ {{ row.total }}</span>
          </template>
        </el-table-column>
        <el-table-column label="治理进度" width="190">
          <template #default="{ row }">
            <el-tag v-if="isDone(row)" size="small" type="success">完成</el-tag>
            <el-tag v-else size="small" :type="row.pending ? 'warning' : 'info'">
              {{ doneOf(row) }}/{{ row.unique }}
            </el-tag>
            <el-tag v-if="row.failed" size="small" type="danger">失败 {{ row.failed }}</el-tag>
            <el-progress :percentage="pctOf(row)" :stroke-width="6"
                         :show-text="false" style="margin-top:4px" />
          </template>
        </el-table-column>
        <el-table-column label="已关联" width="80" align="center">
          <template #default="{ row }">
            <span v-if="row.linked">{{ row.linked }}</span>
            <span v-else class="faint dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text @click="viewBatch(row)">查看</el-button>
            <el-button size="small" :disabled="!row.pending" @click="gov(row, 'gov')">
              治理
            </el-button>
            <el-button v-if="row.failed" size="small" text @click="gov(row, 'retry')">
              重试失败
            </el-button>
            <el-button size="small" text @click="gov(row, 'reset')">重跑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!loading && !rows.length" class="none">
        <el-empty :description="emptyText" />
      </div>
      <div v-else-if="!loading && rows.length && !filtered.length" class="faint none">
        没有匹配的批次 —— 清掉上面的筛选标签试试
      </div>
    </div>
  </div>
</template>

<script setup>
/* BatchTable.vue —— 批次表（照片库页的「批次」子视图 + 独立 /batches 路由共用）
 *
 * 从旧 Batches.vue 抽出来：标题行/空态行动按钮由**宿主页**决定
 * （照片库页的批次是它的第二个视图，独立路由页才有「去导入照片」按钮），
 * 表体逻辑（治理三动作、查看=跳照片库并带上批次筛选）保持一份不复制。
 */
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, post } from '../api.js'
import { qs } from '../lib/core.js'
import { filters } from '../lib/photosStore.js'

const props = defineProps({
  containerId: { type: String, default: '' },
  emptyText: { type: String, default: '还没有照片批次 —— 一次导入即成为一个批次' },
})
const emit = defineEmits(['view', 'governed'])

const rows = ref([])
const loading = ref(false)
const iq = ref('')
const istate = ref('')

const isDone = (b) => b.unique > 0 && !b.pending && !b.failed
const doneOf = (b) => b.unique - b.pending - b.failed
const pctOf = (b) => (b.unique ? Math.round((doneOf(b) / b.unique) * 100) : 0)

const filtered = computed(() => {
  const kw = iq.value.trim().toLowerCase()
  return rows.value.filter((b) => {
    if (istate.value === 'pending' && !b.pending) return false
    if (istate.value === 'done' && !isDone(b)) return false
    if (istate.value === 'failed' && !b.failed) return false
    if (!kw) return true
    return ((b.name || '') + ' ' + b.id).toLowerCase().includes(kw)
  })
})

const chips = computed(() => {
  const out = []
  if (iq.value.trim()) out.push({ k: 'q', t: '关键词：' + iq.value.trim() })
  if (istate.value) {
    out.push({ k: 'state', t: { pending: '待治理', done: '已完成', failed: '有失败' }[istate.value] })
  }
  return out
})
function dropChip(k) {
  if (k === 'q') iq.value = ''
  if (k === 'state') istate.value = ''
}
function reload() { load() }

/* 请求序列守卫：watch(containerId) 与 onMounted 可能都触发，
   两次响应到达顺序不定 —— 慢的那次会把新结果覆盖成旧结果。 */
let seq = 0
async function load() {
  const me = ++seq
  loading.value = true
  try {
    const d = await api('/api/batches' + (props.containerId ? '?' + qs({ container_id: props.containerId }) : ''))
    if (me !== seq) return          // 已有更新的请求在飞，丢弃本次
    rows.value = d.items || []
  } catch { if (me === seq) rows.value = [] }
  finally { if (me === seq) loading.value = false }
}

/* 「查看」= 回照片库照片视图并把这个批次设成筛选条件
   （照片库的筛选真源在 photosStore 单例，改了同页立即生效，无需路由参数）。 */
function viewBatch(b) {
  filters.batch = b.id
  emit('view', b)
}

/* 行内治理：三种动作共用一个端点，只是三个布尔位不同 */
async function gov(b, mode) {
  const n = mode === 'reset' ? b.unique : (mode === 'retry' ? b.failed : b.pending)
  if (!n) {
    ElMessage.warning(mode === 'reset' ? '该批次没有照片'
      : (mode === 'retry' ? '该批次没有失败的照片' : '该批次没有待治理照片'))
    return
  }
  const nm = '批次「' + (b.name || b.id) + '」'
  if (mode === 'reset') {
    try {
      await ElMessageBox.confirm('把' + nm + '的 ' + n + ' 张照片重置为待治理并重跑？\n'
        + '该批次的自动关联会清掉重算；人工关联不受影响。', '重跑', { type: 'warning' })
    } catch { return }
  } else if (mode === 'retry') {
    try {
      await ElMessageBox.confirm('重试' + nm + '的 ' + n + ' 张失败照片？\n'
        + '只重跑失败的，已完成 / 已跳过的不动；不会清掉任何关联。', '重试失败',
        { type: 'warning' })
    } catch { return }
  }
  try {
    const r = await post('/api/govern', {
      batch_id: b.id,
      reset: mode === 'reset',
      retry_failed: mode === 'retry',
      use_vision: true,
      use_ocr: true,
    })
    if (!r.started) { ElMessage.error(r.reason || '无法启动'); return }
    ElMessage.success((mode === 'reset' ? '重新治理' : mode === 'retry' ? '重试失败' : '治理')
      + '已启动：' + nm + '（' + n + ' 张）')
    emit('governed', { batch: b, mode })
    await load()
  } catch (e) { ElMessage.error('启动失败：' + e.message) }
}

watch(() => props.containerId, load)
/* ⚠️ 首次加载必须挂 onMounted，不能在 setup 里直接调 load()：
      setup 阶段组件还没挂载，此时发的请求与父组件自己的首屏请求并发，
      两次响应到达顺序不定 → 「按柜筛选后表格先显示旧数据再被覆盖」，
      表现为筛选像是没生效/延迟生效。 */
onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 10px;
  padding-bottom: 10px; border-bottom: 1px solid var(--el-border-color-lighter); }
.toolbar .spacer { flex: 1; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
.dim { opacity: .45; }
.none { padding: 8px; }
</style>
