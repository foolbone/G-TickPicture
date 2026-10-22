<template>
  <div class="home-page">
    <!-- 概览卡：全量口径，与 /api/stats 同源 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="phead">
          <h2>概览</h2>
          <span class="spacer"></span>
          <span class="faint" :title="visionTitle">
            多模态：{{ s.vision_enabled ? '已启用' : '未配置（降级运行）' }}
          </span>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </template>
      <div v-loading="loading">
        <div class="cards">
          <div class="card"><div class="n">{{ s.products || 0 }}</div><div class="l">产品</div></div>
          <div class="card" :class="covCls">
            <div class="n">{{ s.with_photos || 0 }} / {{ s.products || 0 }}</div>
            <div class="l">有照片的产品</div>
          </div>
          <div class="card"><div class="n">{{ s.photos || 0 }}</div><div class="l">照片</div></div>
          <div class="card" :class="s.pending > 0 ? 'warn' : 'ok'">
            <div class="n">{{ s.pending || 0 }}</div><div class="l">待治理</div>
          </div>
          <div class="card" :class="s.unlinked > 0 ? 'warn' : 'ok'">
            <div class="n">{{ s.unlinked || 0 }}</div><div class="l">待关联</div>
          </div>
          <div class="card"><div class="n">{{ s.links || 0 }}</div><div class="l">关联</div></div>
        </div>
        <div class="faint cov">
          有照片的产品占比 {{ cov }}% —— 覆盖率越低，说明越多产品还没拍到照片
        </div>
      </div>
    </el-card>

    <!-- 快速开始 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="phead">
          <h3>快速开始<span class="sub">按预检作业顺序走完这五步</span></h3>
        </div>
      </template>
      <div class="quick">
        <el-button size="small" @click="go('/wizard')">① 导入预检照片</el-button>
        <el-button size="small" plain @click="go('/wizard')">② 跑治理</el-button>
        <el-button size="small" plain @click="go('/review')">③ 审核入库</el-button>
        <el-button size="small" plain @click="go('/report')">④ 检索匹配</el-button>
        <el-button size="small" plain @click="go('/report')">⑤ 生成报告</el-button>
        <span class="spacer"></span>
        <a class="faint" href="#" @click.prevent="go('/products')">或先维护标准库 →</a>
      </div>
      <div class="faint mt">② 跑治理在「照片批次」页发起；④⑤ 都在「柜作业」向导的第③④步里。</div>
    </el-card>

    <!-- 批次统计 -->
    <el-card shadow="never">
      <template #header>
        <div class="phead">
          <h3>批次统计<span class="sub">每次导入是一个批次，治理与检索都以批次为单位</span></h3>
        </div>
      </template>
      <div v-loading="bLoading">
        <div v-if="batches.length" class="cards">
          <div class="card"><div class="n">{{ batches.length }}</div><div class="l">批次总数</div></div>
          <div class="card" :class="doneN === batches.length ? 'ok' : ''">
            <div class="n">{{ doneN }} / {{ batches.length }}</div><div class="l">已完成</div>
          </div>
          <div class="card" :class="failN > 0 ? 'warn' : 'ok'">
            <div class="n">{{ failN }}</div><div class="l">有失败</div>
          </div>
          <div class="card" :class="linkedSum > 0 ? 'ok' : 'warn'">
            <div class="n">{{ linkedSum }}</div><div class="l">已关联照片</div>
          </div>
        </div>

        <el-table v-if="batches.length" :data="batches" size="small" max-height="240"
                  class="mt">
          <el-table-column label="批次" min-width="200">
            <template #default="{ row }">
              <span class="nm" :title="row.id">{{ row.name || row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column label="导入时间" width="140">
            <template #default="{ row }">
              <span class="faint">{{ (row.created_at || '').replace('T', ' ').slice(0, 16) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="照片（唯一/重复）" width="130">
            <template #default="{ row }">
              {{ row.unique }} <span class="faint">/ {{ row.total }}</span>
            </template>
          </el-table-column>
          <el-table-column label="治理进度" width="180">
            <template #default="{ row }">
              <el-tag v-if="isDone(row)" size="small" type="success">完成</el-tag>
              <el-tag v-else size="small" :type="row.pending ? 'warning' : 'info'">
                {{ doneOf(row) }}/{{ row.unique }}
              </el-tag>
              <el-tag v-if="row.failed" size="small" type="danger" class="ml">失败 {{ row.failed }}</el-tag>
              <el-progress :percentage="progOf(row)" :stroke-width="5" :show-text="false" />
            </template>
          </el-table-column>
          <el-table-column label="已关联" width="80">
            <template #default="{ row }">{{ row.linked || 0 }}</template>
          </el-table-column>
        </el-table>

        <el-empty v-else-if="!bLoading"
                  description="还没有批次 —— 去「柜作业」第①步导入第一批照片" />
      </div>
    </el-card>

    <!-- 系统说明 -->
    <el-card shadow="never" class="mt">
      <template #header>
        <div class="phead">
          <h3>系统说明<span class="sub">这套工具解决什么问题、怎么用</span></h3>
        </div>
      </template>
      <p>
        <b>集刻 · 产品库</b>是预检监装照片的<b>事后治理与复用工具</b>：把现场拍的大量照片自动分类、读码、
        关联到产品编码，形成可检索的产品库，后续同编码的货可以直接复用历史照片，不用重拍。
      </p>
      <div class="flow">
        <div v-for="(s, i) in flow" :key="i" class="fstep">
          <div class="fn">{{ i + 1 }}</div>
          <div class="ft">{{ s.t }}</div>
          <div class="fd">{{ s.d }}</div>
        </div>
      </div>
      <p class="faint mt">
        设计原则：自动关联只认高置信精确匹配，错关联比没关联危险；
        没配多模态 API 时降级为 OCR+启发式，功能变弱但不会不能用。
      </p>
    </el-card>
  </div>
</template>

<script setup>
/* Home.vue —— 概览页：统计卡 + 快速开始 + 批次统计 + 系统说明
 *
 * 口径纪律：概览数字全部来自 /api/stats，**不做前端二次过滤**——
 * 筛选只改显示、不改结论（同报告页）。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'

const router = useRouter()
const s = ref({})
const batches = ref([])
const loading = ref(false)
const bLoading = ref(false)

const flow = [
  { t: '导入照片', d: '目录或网页上传，自动 MD5 去重、按 EXIF 时间分组，一次导入 = 一个批次。' },
  { t: '跑治理', d: '多模态分类（标识卡/产品/包装/清单/场景）→ OCR 读码 → 精确编码自动关联，模糊的进人工。' },
  { t: '人工标注', d: '认领模糊候选、确认新产品、合并裁决；标签上的品名/规格可提取后填充到产品信息。' },
  { t: '产品库', d: '每个产品的历史照片按批次归集，可裁剪标准图，一眼看出哪些批次没拍到。' },
  { t: '检索与报告', d: '粘贴货品编码 → 检索历史照片与标准图 → 导出素材包或整库落盘交付。' },
]

const cov = computed(() => {
  const p = s.value.products || 0
  return p ? Math.round((s.value.with_photos || 0) / p * 100) : 0
})
const covCls = computed(() => (cov.value >= 50 ? 'ok' : 'warn'))

const visionTitle = computed(() => (s.value.vision_enabled
  ? '多模态：已启用（' + s.value.vision_model + '）'
  : '多模态：未配置（降级运行）'))

/* 批次判定与旧版 home.js 同口径：pending/failed 都为 0 且 unique>0 才算完成 */
const isDone = (b) => b.pending === 0 && b.failed === 0 && b.unique > 0
const doneOf = (b) => b.unique - (b.pending || 0) - (b.failed || 0)
const progOf = (b) => (b.unique ? Math.round(doneOf(b) / b.unique * 100) : 0)

const doneN = computed(() => batches.value.filter(isDone).length)
const failN = computed(() => batches.value.filter((b) => (b.failed || 0) > 0).length)
const linkedSum = computed(() => batches.value.reduce((a, b) => a + (b.linked || 0), 0))

function go(path) { router.push(path) }

async function loadBatches() {
  bLoading.value = true
  try {
    const d = await api('/api/batches')
    batches.value = d.items || []
  } catch { /* api() 已弹错 */ } finally { bLoading.value = false }
}

async function load() {
  loading.value = true
  try {
    s.value = await api('/api/stats')
  } catch { s.value = {} } finally { loading.value = false }
  await loadBatches()
}

onMounted(load)
</script>

<style scoped>
.home-page { max-width: 100%; margin: 0 auto; }
.mb { margin-bottom: 12px; }
.mt { margin-top: 12px; }
.ml { margin-left: 6px; }
.phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.phead h2 { margin: 0; font-size: 17px; }
.phead h3 { margin: 0; font-size: 15px; }
.phead .sub { margin-left: 10px; font-size: 12px; font-weight: normal;
  color: var(--el-text-color-secondary); }
.phead .spacer, .quick .spacer { flex: 1; }
.cards { display: flex; gap: 10px; flex-wrap: wrap; }
.cards .card { border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  padding: 10px 16px; min-width: 110px; }
.cards .card .n { font-size: 20px; font-weight: 600; }
.cards .card .l { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.cards .card.ok { border-color: var(--el-color-success-light-5); }
.cards .card.warn { border-color: var(--el-color-warning-light-5); }
.cov { margin-top: 8px; }
.quick { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.flow { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.fstep { flex: 1; min-width: 190px; border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px; padding: 10px 12px; }
.fstep .fn { width: 20px; height: 20px; border-radius: 50%; background: var(--el-color-primary);
  color: #fff; font-size: 12px; text-align: center; line-height: 20px; }
.fstep .ft { font-weight: 600; margin: 6px 0 4px; }
.fstep .fd { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.nm { font-family: ui-monospace, Menlo, Consolas, monospace; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
