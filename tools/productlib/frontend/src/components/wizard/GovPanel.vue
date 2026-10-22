<template>
  <div class="gov">
    <div class="gov-head" @click="fold = !fold">
      <b>跑治理</b>
      <span class="faint">{{ anyRunning ? '治理中…' : hint }}</span>
      <span class="spacer"></span>
      <el-button v-if="!fold" size="small" text>收起 ▴</el-button>
      <el-button v-else size="small" text>展开 ▾</el-button>
    </div>

    <div v-show="!fold" class="gov-body">
      <div class="gov-bar">
        <span class="faint">范围</span>
        <el-select v-model="batchId" size="small" style="width:240px" clearable
                   placeholder="全部照片">
          <el-option v-for="b in batches" :key="b.id" :label="b.name || b.id" :value="b.id" />
        </el-select>
        <span class="faint">上限</span>
        <el-input v-model="limit" size="small" style="width:80px" placeholder="不限" />
        <el-checkbox v-model="useVision" size="small">使用多模态</el-checkbox>
        <el-checkbox v-model="useOcr" size="small">使用本地 OCR</el-checkbox>
        <span class="spacer"></span>
        <el-button v-if="!anyRunning" size="small" type="primary" :loading="starting" @click="run">
          开始
        </el-button>
        <el-button v-else size="small" type="danger" @click="stop">停止</el-button>
      </div>

      <el-progress v-if="anyRunning" :percentage="pct" :stroke-width="10" />
      <div class="gov-text faint">{{ statusText }}</div>

      <!-- 失败诊断：只报「失败 N 张」等于把排查成本全推给用户。
           面板在任务完成那一刻渲染一次就够，但**刷新后要能恢复** ——
           status.tasks 里留着完整的 result，直接重渲染。 -->
      <div v-if="errBox" class="gov-err">
        <div class="gov-err-h err">{{ errBox.head }}</div>
        <ul class="gov-err-list">
          <li v-for="(e, i) in errBox.list" :key="i">
            <b>{{ e.kind }}</b> × {{ e.count }}
            <div v-if="e.act" class="act">→ {{ e.act }}</div>
          </li>
        </ul>
        <details v-if="errBox.samples.length" class="gov-samples">
          <summary>看失败的样例照片（{{ errBox.samples.length }}）</summary>
          <ul class="gov-err-list">
            <li v-for="(sp, i) in errBox.samples" :key="'s' + i">
              <b>{{ String(sp[1] || '').split('/').pop() }}</b>
              <div class="act">{{ sp[2] }}</div>
              <div v-if="actOf(sp[0])" class="act">→ {{ actOf(sp[0]) }}</div>
            </li>
          </ul>
        </details>
        <div v-if="errBox.hints.length" class="act" v-for="(h, i) in errBox.hints" :key="'h' + i">
          {{ h }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
/* GovPanel.vue —— ③的治理面板（导入照片后跑识别 + 自动关联）
 *
 * 多任务（2026-10-18 老板需求 4）：不同批次可并行治理，status.tasks 每任务一行，
 * 进度条聚合运行中任务，完成报告按任务逐个提示（用任务签名去重，避免每秒轮询重复弹）。
 *
 * ⚠️「运行中把开始换成停止」：治理吃满 CPU，用户必须能随时叫停，
 *    而不是只能等或杀进程（停止是协作式的：当前这张跑完就收）。
 *
 * ⚠️ 失败必须说清「为什么失败、怎么解决」，并给出样例照片 ——
 *    只报「失败 N 张」等于让用户自己猜是哪几张（2026-10-18 老板反馈）。 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, post } from '../../api.js'

const props = defineProps({
  cid: { type: String, default: '' },
})
const emit = defineEmits(['done'])

/* 每类失败原因 → 下一步动作（照旧版那份行动指引，别让人自己猜） */
const ACT = {
  '视觉模型不可用（去「设置」配 API）': '去「设置 → 多模态识别」填 API 地址 / Key / 模型名，保存后点「重试失败」。',
  'OCR 模型加载失败（检查 ocr 目录）': '确认程序目录下有 ocr\\ 文件夹，里面有 det.onnx / rec.onnx / keys.txt 三个文件。',
  '文件/模型缺失（照片路径或 ocr 目录）': '照片是「原地引用」的 —— 换电脑后原路径失效了。请把照片拷到本机后，重新导入该照片批次。',
  '图片读不出（文件损坏或格式不支持）': '这些图打不开或格式怪（HEIC/RAW 之类）。转成 jpg 再导入。',
  '网络/接口超时（视觉 API 不通）': '视觉模型接口不通：检查网络 / Key 余额 / 模型名是否正确。不需要视觉模型就取消「使用多模态」勾选。',
  '数据库被另一个产品库进程占用': '多半是同时开了两个产品库（绿色包 + 源码版，或浏览器开着旧窗口）。关掉多余的那个黑窗口，重新跑一次即可。治理本身不会造成这个 —— 它每处理一张就提交一次，锁的时间极短。',
}
const actOf = (kind) => ACT[kind] || ''

const fold = ref(true)
const batchId = ref('')
const batches = ref([])
const limit = ref('')
const useVision = ref(true)
const useOcr = ref(true)
const starting = ref(false)
const status = ref(null)
/* 待治理/共 N 张、多模态是否启用来自 /api/stats —— govern/status 里没有这两个字段 */
const stats = ref(null)
const errBox = ref(null)
/* 任务签名去重：key@started —— 完成提示只弹一次 */
const seen = new Set()
let timer = null
let hadRunning = false

const tasks = computed(() => (status.value && status.value.tasks) || [])
const running = computed(() => tasks.value.filter((t) => t.running))
const anyRunning = computed(() => running.value.length > 0)
const pct = computed(() => {
  let d = 0, tot = 0
  running.value.forEach((t) => { d += t.done || 0; tot += t.total || 0 })
  return tot ? Math.round((d / tot) * 100) : 0
})
const hint = computed(() => {
  if (!stats.value) return ''
  const p = stats.value.pending
  const all = stats.value.photos
  return '待治理 ' + p + ' / 共 ' + all + ' 张'
    + (stats.value.vision_enabled
      ? ' · 多模态已启用（' + (stats.value.vision_model || '') + '）'
      : ' · 多模态未配置（降级运行）')
})
const statusText = computed(() => {
  const ts = tasks.value
    .filter((t) => t.running || t.result || t.error)
    .slice(-6)
    .map((t) => {
      const label = '[' + (t.batch_id ? (t.name || t.batch_id) : '全部照片') + '] '
      if (t.running) {
        const p = t.total ? Math.round((t.done / t.total) * 100) : 0
        return label + '治理中 ' + t.done + '/' + t.total + '（' + p + '%）· 当前：' + (t.file || '')
      }
      if (t.error) return label + '失败：' + t.error
      if (t.result) {
        return label + '完成：治理 ' + t.result.done + ' 张，自动关联 ' + t.result.linked
          + ' 条，跳过 ' + t.result.skipped + ' 张，耗时 ' + t.result.seconds + ' 秒'
          + (t.result.stopped ? '（已按停止请求收尾）' : '')
      }
      return ''
    }).filter(Boolean)
  return ts.length ? ts.join('　|　') : '未开始'
})

async function loadBatches() {
  try {
    const d = await api('/api/batches')
    batches.value = (d.items || []).filter((b) => !props.cid || b.container_id === props.cid)
  } catch { batches.value = [] }
}

function buildErrBox(r) {
  if (!r || !r.failed) return null
  const errs = r.errors || []
  if (!errs.length) {
    return {
      head: '失败 ' + r.failed + ' 张（没有拿到失败原因，可能是进程被强制关闭）',
      list: [], samples: [], hints: [],
    }
  }
  const hints = []
  if (r.vision_on === false) hints.push('提示：当前未启用视觉模型 —— 手写码 / 模糊件读不出来就是这个原因。')
  if (r.ocr_on === false) hints.push('提示：当前未勾选本地 OCR —— 标识卡上的编码读不出来就是这个原因。')
  return {
    head: '失败 ' + r.failed + ' 张，按原因分：',
    list: errs.map((e) => ({
      kind: String(e.kind || '').replace(/^其它：/, ''),
      count: e.count,
      act: actOf(e.kind),
    })),
    samples: r.error_samples || [],
    hints,
  }
}

/** 进来时正在跑 → 展开面板让进度可见；没在跑但上次有失败 → 恢复诊断面板。 */
async function resume() {
  try {
    const s = await api('/api/govern/status')
    status.value = s
    const ts = (s && s.tasks) || []
    /* 进来时正在跑 → 展开面板让进度可见（进度条藏起来主观上等于卡死） */
    if ((s && s.running) || ts.some((t) => t.running)) {
      fold.value = false
      poll()
      return
    }
    const last = ts.length ? ts[ts.length - 1] : null
    if (last && last.result && last.result.failed) {
      errBox.value = buildErrBox(last.result)
      fold.value = false
    } else if (last && last.error) {
      errBox.value = {
        head: '最近一次治理整体失败：' + last.error, list: [], samples: [], hints: [],
      }
      fold.value = false
    }
  } catch { /* 读不到状态不挡页面 */ }
}

async function poll() {
  if (timer) return
  timer = setInterval(tick, 1000)
  tick()
}

async function tick() {
  let s
  try {
    s = await api('/api/govern/status')
  } catch {
    clearInterval(timer); timer = null; return
  }
  status.value = s
  const ts = (s && s.tasks) || []
  const runningNow = ts.filter((t) => t.running)
  if (runningNow.length) hadRunning = true
  /* 运行中先藏上一轮的失败面板（完成时按新结果重渲染） */
  if (runningNow.length) errBox.value = null
  ts.forEach((t) => {
    const sig = t.key + '@' + (t.started || '')
    if (t.running || (!t.result && !t.error) || seen.has(sig)) return
    seen.add(sig)
    const nm = t.batch_id ? t.name : '全部照片'
    if (t.error) {
      ElMessage.error('治理失败（' + nm + '）：' + t.error)
    } else if (t.result) {
      if (t.result.stopped) ElMessage.success('治理已停止（' + nm + '）：已治理的保留，剩下的下次接着跑')
      else if (t.result.done === 0) ElMessage.info('「' + nm + '」没有待治理的照片（全部已治理过）')
      else ElMessage.success('治理完成（' + nm + '）：' + t.result.done + ' 张，自动关联 '
        + t.result.linked + ' 条')
      errBox.value = buildErrBox(t.result)
    }
  })
  if (!runningNow.length && hadRunning) {
    clearInterval(timer); timer = null
    hadRunning = false
    loadStats()
    emit('done')
  }
}

async function run() {
  starting.value = true
  try {
    const r = await post('/api/govern', {
      limit: parseInt(limit.value, 10) || null,
      batch_id: batchId.value || '',
      use_vision: useVision.value,
      use_ocr: useOcr.value,
    })
    if (!r.started) { ElMessage.error(r.reason || '无法启动'); return }
    fold.value = false
    poll()
  } catch (e) {
    ElMessage.error('启动失败：' + e.message)
  } finally {
    starting.value = false
  }
}

async function stop() {
  try {
    const r = await post('/api/govern/stop')
    if (!r.ok) { ElMessage.error(r.reason || '无法停止'); return }
    ElMessage.info('已请求停止，等当前这张跑完就收')
  } catch (e) { ElMessage.error('停止失败：' + e.message) }
}

onMounted(async () => {
  await loadBatches()
  await resume()
})
onBeforeUnmount(() => { if (timer) { clearInterval(timer); timer = null } })
watch(() => props.cid, loadBatches)

/* 统计（待治理 N / 共 M）随治理完成刷新 */
async function loadStats() {
  try {
    stats.value = await api('/api/stats')
  } catch { /* 统计读不到不影响治理 */ }
}
onMounted(loadStats)

defineExpose({ reload: async () => { await loadBatches(); await loadStats(); await resume() } })
</script>

<style scoped>
.gov { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; margin-bottom: 10px; }
.gov-head { display: flex; align-items: center; gap: 8px; padding: 8px 10px; cursor: pointer; }
.gov-head .spacer { flex: 1; }
.gov-body { padding: 0 10px 10px; display: flex; flex-direction: column; gap: 8px; }
.gov-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.gov-bar .spacer { flex: 1; }
.gov-text { font-size: 12px; line-height: 1.7; }
.gov-err { border: 1px solid var(--el-color-danger-light-7); background: var(--el-color-danger-light-9);
  border-radius: 6px; padding: 8px 10px; font-size: 12px; }
.gov-err-h { font-weight: 600; margin-bottom: 6px; }
.gov-err-h.err { color: var(--el-color-danger); }
.gov-err-list { margin: 0; padding-left: 18px; line-height: 1.8; }
.gov-err-list .act { color: var(--el-text-color-secondary); }
.gov-samples summary { cursor: pointer; margin-top: 6px; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>