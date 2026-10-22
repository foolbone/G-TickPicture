<template>
  <div class="rep-page">
    <el-card shadow="never">
      <template #header>
        <div class="phead">
          <h2>报告档案<span class="sub">已生成的装柜报告＝资产 —— 按柜检索，上一版可直接再下载</span></h2>
          <span class="spacer"></span>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </template>

      <!-- 概览卡：全量口径 —— 筛选只改下面那张表，不改结论 -->
      <div class="cards">
        <div class="card"><div class="n">{{ all.length }}</div><div class="l">总份数</div></div>
        <div class="card"><div class="n">{{ fmtSize(bytesAll) }}</div><div class="l">占用空间</div></div>
        <div class="card"><div class="n">{{ monthNew }}</div><div class="l">本月新增</div></div>
        <div class="card"><div class="n">{{ containerNos.length }}</div><div class="l">已归档柜数</div></div>
      </div>

      <div class="toolbar">
        <el-select v-model="cid" placeholder="全部柜" clearable style="width:180px"
                   title="按柜号筛选（柜号由后端从文件名解析）">
          <el-option :label="'全部柜（' + containerNos.length + '）'" value="" />
          <el-option v-for="n in containerNos" :key="n" :label="n" :value="n" />
        </el-select>
        <el-input v-model="q" placeholder="搜文件名关键词" clearable style="width:200px"
                  @keyup.enter="render" @clear="render" />
        <el-button size="small" @click="render">筛选</el-button>
        <el-button size="small" text @click="reset">重置</el-button>
        <span class="spacer"></span>
        <span class="faint">{{ totalText }}</span>
      </div>

      <div v-if="fchips.length" class="chips">
        <span class="faint">已按</span>
        <el-tag v-for="c in fchips" :key="c.k" closable size="small" type="info"
                @close="dropChip(c.k)">{{ c.t }}</el-tag>
        <el-button size="small" text @click="reset">全清</el-button>
      </div>

      <div v-loading="loading">
        <el-table :data="items" size="small">
          <el-table-column label="报告文件" min-width="260">
            <template #default="{ row }">
              <span class="nm" :title="row.name">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="柜号" width="140">
            <!-- 柜号只用后端 container_no（按 CNTR#<柜号>- 解析）——
                 前端自己写正则必然与后端漂移 -->
            <template #default="{ row }">
              <el-tag v-if="row.container_no" size="small">{{ row.container_no }}</el-tag>
              <span v-else class="faint">未解析出柜号</span>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="110">
            <template #default="{ row }">{{ fmtSize(row.bytes) }}</template>
          </el-table-column>
          <el-table-column label="生成时间" width="150">
            <template #default="{ row }">
              <span class="faint">{{ (row.mtime || '').replace('T', ' ').slice(0, 16) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button size="small" tag="a" :href="row.download" target="_blank">下载</el-button>
              <el-button size="small" text @click="delOne(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading && !all.length"
                  description="还没有生成过报告 —— 到「柜」页进一个柜作业，第⑤步生成；生成完就会出现在这里" />
        <div v-else-if="!loading && all.length && !items.length" class="faint none">
          没有匹配的报告
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
/* Report.vue —— 报告档案页（对应旧版 report.js + #tab-report）
 *
 * 2026-10-11 精简：三步取材/生成流程整段移除，出报告只走「柜作业⑤」。
 * 这一页只负责档案：概览卡 + 按柜/文件名筛选 + 下载/删除。
 *
 * 🔴 概览卡是**全量口径**（总份数/占用/本月新增/柜数），筛选只改表不改结论 ——
 *    否则用户一筛选，「总份数 12」变成「3」，会以为报告丢了。
 */
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, del } from '../api.js'

const all = ref([])
const cid = ref('')
const q = ref('')
const loading = ref(false)

const fmtSize = (b) => (b >= 1048576
  ? (b / 1048576).toFixed(1) + ' MB'
  : Math.max(1, Math.round(b / 1024)) + ' KB')

const bytesAll = computed(() => all.value.reduce((a, x) => a + (x.bytes || 0), 0))
const containerNos = computed(() =>
  [...new Set(all.value.map((f) => f.container_no).filter(Boolean))].sort())
const monthNew = computed(() => {
  const m = new Date().toISOString().slice(0, 7)
  return all.value.filter((f) => String(f.mtime || '').slice(0, 7) === m).length
})

const items = computed(() => {
  const kw = q.value.trim().toLowerCase()
  return all.value.filter((f) => (!cid.value || f.container_no === cid.value)
    && (!kw || String(f.name || '').toLowerCase().includes(kw)))
})
const totalText = computed(() => (all.value.length
  ? '显示 ' + items.value.length + ' / 共 ' + all.value.length
    + ' 份 · 占用 ' + fmtSize(bytesAll.value)
  : ''))

async function load() {
  loading.value = true
  try {
    const d = await api('/api/report/loading-list')
    all.value = d.items || []
  } catch { all.value = [] } finally { loading.value = false }
}
function render() { /* 筛选是 computed，改值即重算；这里留个语义锚点 */ }
function reset() { cid.value = ''; q.value = '' }

/* 筛选条件常显：两个 clearable 控件筛完看不出当前是什么 */
const fchips = computed(() => {
  const out = []
  if (cid.value) out.push({ k: 'cid', t: '柜号：' + cid.value })
  if (q.value.trim()) out.push({ k: 'q', t: '文件名：' + q.value.trim() })
  return out
})
function dropChip(k) {
  if (k === 'cid') cid.value = ''
  if (k === 'q') q.value = ''
}

async function delOne(f) {
  try {
    await ElMessageBox.confirm('删除已生成的报告？\n\n' + f.name
      + '\n\n删了就没了，需要的话要重新生成（到柜作业⑤按柜重跑一次）。',
      '删除报告', { type: 'warning' })
  } catch { return }
  try {
    await del('/api/report/loading-file?path=' + encodeURIComponent(f.name))
    ElMessage.success('已删除（还能重新生成）')
    await load()
  } catch { /* api() 已弹错 */ }
}

onMounted(load)
</script>

<style scoped>
.rep-page { max-width: 100%; margin: 0 auto; }
.phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.phead h2 { margin: 0; font-size: 17px; }
.phead .sub { margin-left: 10px; font-size: 12px; font-weight: normal;
  color: var(--el-text-color-secondary); }
.phead .spacer, .toolbar .spacer { flex: 1; }
.cards { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.cards .card { border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  padding: 10px 16px; min-width: 110px; }
.cards .card .n { font-size: 20px; font-weight: 600; }
.cards .card .l { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.toolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.chips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px dashed var(--el-border-color-lighter); }
.nm { font-family: ui-monospace, Menlo, Consolas, monospace; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
.none { padding: 18px; text-align: center; }
</style>