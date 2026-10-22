<template>
  <div>
    <div class="wd-h">生成选项</div>
    <div class="gen-opts">
      <el-checkbox v-model="reverse">⑥倒序（对齐样例）</el-checkbox>
      <label class="faint">画质
        <el-select v-model="longEdge" size="small" style="width:130px">
          <el-option label="1200px（推荐）" :value="1200" />
          <el-option label="1600px" :value="1600" />
        </el-select>
      </label>
      <el-checkbox v-model="usePicks"
                   title="④选了图就用它；没选则按编码自动取一张">⑥用④选定的照片</el-checkbox>
    </div>

    <!-- 结果卡由**状态**渲染（旧版塞 DOM 会被重绘冲掉，这里天然不冲） -->
    <el-card v-if="wiz.genResult" shadow="never" class="gen-result">
      <template #header><b>已生成 {{ wiz.genResult.container_no }}</b></template>
      <div class="faint">
        清单 {{ wiz.genResult.summary?.row_total ?? '—' }} 行 ·
        嵌入图片 {{ wiz.genResult.photos }} 张 ·
        {{ (wiz.genResult.bytes / 1048576).toFixed(1) }} MB
      </div>
      <div class="row" style="margin-top:8px">
        <el-button size="small" type="primary" tag="a"
                   :href="wiz.genResult.download" target="_blank">下载 docx</el-button>
      </div>
    </el-card>
    <el-alert v-else-if="genError" type="error" :closable="false" class="gen-result"
              :title="genError" />

    <div style="margin-top:14px">
      <div class="wd-h">本柜历史报告（{{ mine.length }}）</div>
      <div v-if="!wiz.reports" class="faint">读取报告…</div>
      <div v-else-if="!mine.length" class="faint">这个柜还没生成过报告。</div>
      <div v-else class="rep-list">
        <div v-for="f in mine.slice(0, 5)" :key="f.name" class="row">
          <span class="nm" :title="f.name">{{ f.name }}</span>
          <span class="faint">{{ fmtSize(f.bytes) }}</span>
          <span class="faint">{{ (f.mtime || '').replace('T', ' ').slice(0, 16) }}</span>
          <el-button size="small" tag="a" :href="f.download" target="_blank">下载</el-button>
        </div>
        <div v-if="mine.length > 5" class="faint">仅显示 5 份，全部见「报告档案」</div>
      </div>
    </div>
  </div>
</template>

<script setup>
/* StepReport.vue —— ⑤ 生成报告（不含取材）
 *
 * ⚠️ picks 新格式 {codes, trucks, conds}：**只在「真动过」时才带对应键** ——
 *   trucks: [] 是「明确一张都不要」（⑦ 留空），没动过则不带键（后端自动取）。
 *   监装照没动过但编码选了 → 只带 codes，监装照照旧自动。
 *   这套三态语义是 10-11 定的，写错会让老板的「⑦不要卡车照片」变成自动全选。 */
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { post } from '../../api.js'
import { wiz, pickCount, supTouched, loadReports } from '../../lib/wizardStore.js'

const props = defineProps({
  cid: { type: String, required: true },
  containerNo: { type: String, default: '' },
})
const emit = defineEmits(['generated'])

const reverse = ref(true)
const longEdge = ref(1200)
const usePicks = ref(true)
const genError = ref('')

const fmtSize = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB'
  : Math.max(1, Math.round(b / 1024)) + ' KB')

const mine = computed(() => {
  if (!wiz.reports) return []
  return (wiz.reports.items || []).filter((f) => f.container_no === props.containerNo)
})

onMounted(() => { if (!wiz.reports) loadReports() })

async function gen() {
  genError.value = ''
  const sup = supTouched()
  const picks = (usePicks.value && (pickCount() || sup))
    ? Object.assign(
      pickCount() ? { codes: { ...wiz.picks } } : {},
      sup ? { trucks: wiz.trucks.slice(), conds: { ...wiz.conds } } : {})
    : null
  try {
    const r = await post('/api/report/loading-docx', {
      container_id: props.cid,
      reverse: reverse.value,
      long_edge: longEdge.value || 1200,
      picks: picks || undefined,
    })
    wiz.genResult = r
    wiz.reports = null          // 让本柜历史重新拉，否则看不到刚生成的这份
    ElMessage.success('装柜报告已生成（' + r.photos + ' 图）')
    emit('generated')
  } catch (e) {
    genError.value = '生成失败：' + e.message
    ElMessage.error(genError.value)
  }
}

defineExpose({ gen })
watch(() => props.cid, () => { genError.value = '' })
</script>

<style scoped>
.gen-opts { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 10px; }
.gen-result { margin-top: 8px; }
.rep-list .row { display: flex; align-items: center; gap: 10px; padding: 3px 0; }
.rep-list .nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
