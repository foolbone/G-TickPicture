<template>
  <div class="prod-page">
    <el-card shadow="never">
      <template #header>
        <div class="phead">
          <h2>产品库<span class="sub">跨柜复用的产品资产 —— 导入入口在「柜作业②」</span></h2>
          <span class="spacer"></span>
          <el-button size="small" @click="impVisible = true">＋ 导入清单</el-button>
          <el-button size="small" tag="a" href="/api/products/template" target="_blank">模板</el-button>
          <el-tooltip placement="bottom-end">
            <template #content>
              把已拍照但还没关联上的货品，用当前产品清单重新匹配一次。<br />
              照片先于清单导入时自动关联会落空，用这个补回来。<br />
              不重跑识别、不调多模态，只用已存的识别结果重新匹配。
            </template>
            <el-button size="small" :loading="relinkBusy" @click="relink">补关联</el-button>
          </el-tooltip>
        </div>
        <div class="toolbar">
          <el-input v-model="filters.q" placeholder="搜编码 / 品名（回车搜索）" clearable
                    style="width:240px" @keyup.enter="search" @clear="search" />
          <el-select v-model="filters.container" placeholder="全部柜号" clearable
                     style="width:210px" @change="search">
            <el-option v-for="c in containers.list" :key="c.container_no" :value="c.container_no"
                       :label="(c.label || c.container_no) + '（' + c.products + ' 件）'" />
          </el-select>
          <el-select v-model="filters.has" style="width:150px" @change="search">
            <el-option label="全部状态" value="" />
            <el-option label="有照片" value="yes" />
            <el-option label="无照片" value="no" />
            <el-option label="无标准图" value="nostd" />
            <el-option label="有待确认照片" value="cand" />
            <el-option label="有读码候选" value="cand_code" />
            <el-option label="有同组候选" value="cand_group" />
          </el-select>
          <el-select v-model="filters.sort" style="width:150px" @change="search">
            <el-option label="缺口优先" value="gap" />
            <el-option label="按编码" value="code" />
            <el-option label="待确认多的排前" value="cand" />
          </el-select>
          <span class="spacer"></span>
          <span class="faint">{{ pageText }}</span>
        </div>

        <!-- 筛选标签行：三个下拉都是「选一个」，不看选中值根本不知道现在筛着什么 -->
        <div v-if="fchips.length" class="chips">
          <span class="faint">已按</span>
          <el-tag v-for="c in fchips" :key="c.k" closable size="small" type="info"
                  @close="dropChip(c.k)">{{ c.t }}</el-tag>
          <el-button size="small" text @click="clearChips">全清</el-button>
        </div>
      </template>

      <div v-loading="loading.list">
        <el-table :data="rows.list" :row-class-name="rowCls" size="small" @row-click="onRow">
          <el-table-column label="编码" width="160">
            <template #default="{ row }">
              <span class="code" :title="row.code">{{ row.code }}</span>
            </template>
          </el-table-column>
          <el-table-column label="品名" min-width="140">
            <template #default="{ row }">
              <span v-if="row.name" :title="row.name">{{ row.name }}</span>
              <span v-else class="faint">未命名</span>
            </template>
          </el-table-column>
          <el-table-column label="规格" width="140">
            <template #default="{ row }">
              <span v-if="row.spec" class="faint" :title="row.spec">{{ row.spec }}</span>
              <span v-else class="faint dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="照片" width="70" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.photo_count > 0" size="small" type="success">{{ row.photo_count }}张</el-tag>
              <span v-else class="faint dim">0</span>
            </template>
          </el-table-column>
          <el-table-column label="待确认" width="150">
            <!-- 读码（照片里真读出这个编码，强证据）与同组（跟已关联照片同段连拍，
                 需人工判断）分开显示 —— 两类证据强度完全不同。与详情候选区同源，
                 标了点开一定有，不会出现「标了 N 张、一张没有」。 -->
            <template #default="{ row }">
              <el-tooltip v-if="row.cand_code" content="照片里读出这个编码、还没关联（强证据，优先确认）"
                          placement="top">
                <el-tag size="small" type="warning">读码 {{ row.cand_code }}</el-tag>
              </el-tooltip>
              <el-tooltip v-if="row.cand_group" content="与已关联照片同一段连拍、还没确认（需人工判断）"
                          placement="top">
                <el-tag size="small">同组 {{ row.cand_group }}</el-tag>
              </el-tooltip>
              <span v-if="!row.cand_code && !row.cand_group" class="faint dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="标准图" width="76" align="center">
            <template #default="{ row }">
              <el-tooltip v-if="row.has_standard" content="已制作标准图，导出时优先采用" placement="top">
                <el-tag size="small" type="success">标</el-tag>
              </el-tooltip>
              <span v-else class="faint dim" title="还没做标准图">—</span>
            </template>
          </el-table-column>
          <el-table-column label="柜号" width="100">
            <template #default="{ row }">
              <span v-if="row.container_list" class="faint" :title="row.container_list">
                {{ firstCn(row) }}
              </span>
              <span v-else class="faint dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="来源柜" width="120"
                           tooltip="第一次被哪个柜的清单带进来">
            <template #default="{ row }">
              <span v-if="row.source_container_no" class="faint">{{ row.source_container_no }}</span>
              <span v-else class="faint dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="被引用" width="90" align="center"
                           tooltip="被多少个柜的清单引用（跨柜复用）">
            <template #default="{ row }">
              <span v-if="(row.used_by || []).length" class="faint">
                {{ row.used_by.length }} 柜
              </span>
              <span v-else class="faint dim">—</span>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!loading.list && !rows.list.length"
                  description="没有匹配的产品 —— 换个关键词试试，或先把产品清单导入进来">
          <el-button size="small" type="primary" @click="impVisible = true">导入产品清单</el-button>
        </el-empty>
      </div>

      <div class="pager">
        <el-button size="small" :disabled="page.idx <= 0" @click="gotoPage(-1)">‹ 上一页</el-button>
        <span class="faint">{{ pageText }}</span>
        <el-button size="small" :disabled="page.idx >= page.pages - 1" @click="gotoPage(1)">下一页 ›</el-button>
      </div>
    </el-card>

    <ProductDrawer v-if="sel.code" :code="sel.code" @close="sel.code = ''" @step="onStep" />

    <ImportChecklistDialog v-model="impVisible" @done="onImported" />
  </div>
</template>

<script setup>
/* Products.vue —— 产品库页（对应旧版 products.js + index.html 的 #tab-products）
 *
 * 结构：列表全宽表格 + 右侧滑出的详情抽屉。左右分栏（表格被压窄）与
 * 上下堆叠（点一下要滚到屏幕另一头）都试过，最终定「抽屉盖上来」。
 *
 * 🔴 待确认角标（读码 / 同组）与「有待确认照片」筛选走**同一份**
 *    store.cand_counts()（后端 cand 参数），所以筛出来的点开一定有东西 ——
 *    不会出现「角标说 N 张，筛出来是空的」。
 *
 * 🔴 请求序列守卫：连续两次加载谁新谁赢 —— 快速切筛选时旧响应会把新结果盖掉。
 */
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { post } from '../api.js'
import {
  filters, rows, loading, page, sel, pCodes, containers,
  load, loadContainers, changed,
} from '../lib/productsStore.js'
import { bus } from '../lib/photosStore.js'
import ProductDrawer from '../components/ProductDrawer.vue'
import ImportChecklistDialog from '../components/ImportChecklistDialog.vue'

const impVisible = ref(false)
const relinkBusy = ref(false)

const pageText = computed(() =>
  '第 ' + (page.idx + 1) + ' / ' + page.pages + ' 页 · 共 ' + page.total + ' 条')
const firstCn = (row) => {
  const s = row.container_list || ''
  return s.split(',')[0] + (s.includes(',') ? '…' : '')
}
const rowCls = ({ row }) => (row.code_norm === sel.code ? 'sel-row' : '')

function search() { load(true) }

/* ── 筛选标签行：条件常显可撤 ──
 * `sort` 有默认值（缺口优先），不是「没选」→ 不进标签行；
 * 否则一进页面就显示「已按 缺口优先」，等于没筛也说筛了。 */
const HAS_LABELS = {
  yes: '有照片', no: '无照片', nostd: '无标准图',
  cand: '有待确认照片', cand_code: '有读码候选', cand_group: '有同组候选',
}
const fchips = computed(() => {
  const out = []
  if (filters.q.trim()) out.push({ k: 'q', t: '关键词：' + filters.q.trim() })
  if (filters.container) out.push({ k: 'container', t: '柜号：' + filters.container })
  if (filters.has) out.push({ k: 'has', t: HAS_LABELS[filters.has] || filters.has })
  return out
})
function dropChip(k) {
  filters[k] = ''
  search()
}
function clearChips() {
  filters.q = ''; filters.container = ''; filters.has = ''
  search()
}

function onRow(row) { sel.code = row.code_norm }

async function gotoPage(d) {
  const ni = page.idx + d
  if (ni < 0 || ni >= page.pages) return
  page.idx = ni
  await load(false)
}

/* 抽屉翻上下个：走到页边界自动翻页。抽屉自己已经问过「有没有未保存改动」。 */
async function onStep(d) {
  const i = pCodes.list.indexOf(sel.code)
  if (i < 0) return
  let ni = i + d
  if (ni < 0) {
    if (page.idx <= 0) { ElMessage.info('已经是第一个'); return }
    page.idx -= 1
    await load(false)
    ni = pCodes.list.length - 1
  } else if (ni >= pCodes.list.length) {
    if (page.idx >= page.pages - 1) { ElMessage.info('已经是最后一个'); return }
    page.idx += 1
    await load(false)
    ni = 0
  }
  const code = pCodes.list[ni]
  if (code) sel.code = code
}

/* 补关联：把已治理但没关联上的照片，用当前产品清单重匹配一次。 */
async function relink() {
  relinkBusy.value = true
  ElMessage.info('正在补关联…')
  try {
    const r = await post('/api/products/relink', {})
    if (r.written > 0) {
      ElMessage.success('补关联完成：新增 ' + r.written + ' 条关联，覆盖 ' + r.candidates + ' 张照片')
      await load(true)
      changed()
    } else if (r.candidates > 0) {
      ElMessage.info('没有新增关联：' + r.candidates + ' 张照片的识别结果已存在或低于阈值')
    } else if (r.scanned > 0) {
      ElMessage.info('没有可补的：' + r.scanned + ' 张候选照片都没匹配上清单编码')
    } else {
      ElMessage.info('没有需要补关联的照片')
    }
  } catch (e) {
    ElMessage.error('补关联失败：' + e.message)
  } finally {
    relinkBusy.value = false
  }
}

async function onImported() {
  await loadContainers()
  await load(true)
  changed()
}

/* 抽屉里改产品/删产品后：列表与其它页（照片库树、柜作业④统计）一起重算 */
bus.on('products:changed', () => { load(false) })

onMounted(async () => {
  if (!containers.loaded) await loadContainers()
  await load(true)
})
</script>

<style scoped>
.prod-page { max-width: 100%; margin: 0 auto; }
.phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.phead h2 { margin: 0; font-size: 17px; }
.phead .sub { margin-left: 10px; font-size: 12px; font-weight: normal;
  color: var(--el-text-color-secondary); }
.phead .spacer { flex: 1; }
.toolbar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.toolbar .spacer { flex: 1; }
.chips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--el-border-color-lighter); }
.code { font-family: ui-monospace, Menlo, Consolas, monospace; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
.dim { opacity: .45; }
.pager { display: flex; align-items: center; gap: 10px; justify-content: flex-end;
  padding-top: 10px; margin-top: 6px; border-top: 1px dashed var(--el-border-color); }
:deep(.el-table__row) { cursor: pointer; }
:deep(.sel-row) { background: var(--el-color-primary-light-9) !important; }
</style>