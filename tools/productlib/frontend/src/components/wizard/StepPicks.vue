<template>
  <div class="w-picks">
    <div class="wd-h">
      给报告挑用图
      <span class="faint">一个编码可多张；不选则按编码自动取一张</span>
    </div>

    <el-radio-group v-model="tab" size="small" class="ptab-seg" @change="onTab">
      <el-radio-button label="pre">预检照片（编码核对）</el-radio-button>
      <el-radio-button label="sup">监装照片（柜况④ / 卡车⑦）</el-radio-button>
    </el-radio-group>

    <!-- ⚠️ 两块用 v-show（保留检索结果，切回来不重跑）。代价：隐藏块仍在 DOM 里，
         自动化按 .wcai-shot 取元素会命中看不见的那块 —— 所以各带一个块级 class。 -->
    <div v-show="tab === 'pre'" class="wpane-pre">
      <!-- 柜级统计条：数字全部由后端 progress.steps.picks.stats 下发，
           前端只显示、不在本地另算一套（算两套必然漂移）。 -->
      <div v-if="!stats" class="faint">这个柜还没有清单编码 —— 先到②导入清单。</div>
      <div v-else class="wpstat">
        <div class="wpstat-row">
          <span class="wpstat-c"><b>{{ stats.codes_total }}</b><em>清单编码（种）</em></span>
          <span class="wpstat-c ok"><b>{{ stats.with_photo }}</b><em>有照片·命中（种）</em></span>
          <span class="wpstat-c" :class="stats.missing ? 'warn' : 'ok'">
            <b>{{ stats.missing }}</b><em>缺口（种）</em></span>
          <span class="wpstat-rate">命中占比 <b>{{ stats.hit_rate }}%</b></span>
          <!-- 「已采用」是唯一客户端状态，单独一格，采用/清空后要跟着变 -->
          <span class="wpstat-c"><b :class="{ ok: pickN }">{{ codeN }}</b><em>已采用（{{ pickN }} 张）</em></span>
          <span class="spacer"></span>
          <el-button size="small" text @click="moreOn = !moreOn">
            {{ moreOn ? '其他指标 ▴' : '其他指标 ▾' }}
          </el-button>
        </div>
        <div class="wpstat-bar" :title="'命中 ' + stats.with_photo + ' / 清单 ' + stats.codes_total">
          <i :style="{ width: stats.hit_rate + '%' }"></i>
        </div>
        <div v-if="moreOn" class="wpstat-row">
          <span class="wpstat-c"><b>{{ stats.in_lib }}</b><em>产品库已有（种）</em></span>
          <span class="wpstat-c"><b>{{ stats.photo_total }}</b><em>本柜照片（张）</em></span>
          <span class="wpstat-c ok"><b>{{ stats.photo_linked }}</b><em>其中已关联·命中（张）</em></span>
          <span class="wpstat-c std"><b>{{ stats.std_photos }}</b><em>其中标准图（张）</em></span>
          <span class="faint">本柜全量口径；下面列表是本次检索的范围，两者可能不同。</span>
        </div>
      </div>

      <div class="row">
        <span class="faint">{{ pickTip }}</span>
        <el-tag v-if="stats && !codes.length" type="warning" size="small">
          先完成②导入清单，才能挑核对照
        </el-tag>
      </div>

      <div class="wclbar" v-if="rp">
        <span class="faint">
          命中 {{ hitN }} · 缺口 {{ missN }} · 已采用 {{ pickN }} 张
        </span>
        <span class="spacer"></span>
        <span class="faint">自动选图</span>
        <el-select v-model="strategy" size="small" style="width:260px" @change="onStrategy">
          <el-option v-for="s in strategies" :key="s.key" :label="s.label" :value="s.key" />
        </el-select>
        <el-button size="small" :disabled="!recN" @click="adoptAll">
          全部采用建议图{{ recN ? '（' + recN + '）' : '' }}
        </el-button>
        <el-button size="small" text :disabled="!pickN" @click="clearPicks">清空采用</el-button>
      </div>

      <div v-loading="looking" class="wcai-list">
        <div v-for="it in hitItems" :key="it.code_norm" class="wcai-item">
          <div class="wcai-head">
            <b class="code">{{ it.code }}</b>
            <span class="faint">{{ it.photo_count || 0 }} 张可用</span>
            <el-button size="small" text :disabled="!recOf(it)" @click="adoptOne(it)">采用建议图</el-button>
          </div>
          <div class="wcai-shots">
            <div v-for="p in (it.photos || [])" :key="p.photo_id"
                 class="wcai-shot" :class="{ pick: isPick(it.code_norm, p.photo_id) }"
                 :title="shotTitle(it, p)"
                 @click="togglePick(it.code_norm, p.photo_id)">
              <img loading="lazy" :src="'/thumb/' + p.photo_id" :alt="it.code" />
              <!-- 「看大图」独立角标：点图片本身仍是采用/取消（肌肉记忆不能改） -->
              <span class="wcai-zoom" title="看大图"
                    @click.stop="zoom(p.photo_id, it.code || it.code_norm, p.taken_at)">⤢</span>
              <span v-if="isPick(it.code_norm, p.photo_id)" class="rec mine">✓</span>
              <span v-else-if="p.recommended" class="rec"
                    title="后端按当前策略推荐的这一张">建议</span>
            </div>
          </div>
        </div>
        <el-empty v-if="!looking && !hitItems.length"
                  description="没有命中的编码 —— 先在③导入照片，或换个自动选图策略再试" />
      </div>
    </div>

    <!-- ════ 监装照片（柜况④ / 卡车⑦）════ -->
    <div v-show="tab === 'sup'" class="wpane-sup">
      <div class="wd-h">
        监装照片
        <span class="faint">柜况④每类可挑多张 · 卡车⑦点选进报告；不动 = 自动取</span>
        <span class="spacer"></span>
        <el-button size="small" :disabled="!supTouched()" @click="resetSupAll">恢复自动</el-button>
      </div>
      <div class="faint" v-if="supErr">{{ supErr }}</div>
      <div v-else-if="supGroups && !supGroups.total" class="faint">
        本柜还没有已确认细分的监装照片。到<b>③照片</b>的「待确认细分」里给监装照打细分
        （或采用模型建议），确认完这里就能按柜况④ / 卡车⑦挑图。
      </div>
      <div v-else-if="!supGroups" class="faint">读取监装照片…</div>
      <div v-else class="wcai-list">
        <div v-for="g in supGroups.groups.filter((x) => x.items.length)" :key="g.tag"
             class="wcai-item">
          <div class="wcai-head">
            <b class="code">{{ g.label }}</b>
            <span class="faint">
              {{ g.kind === 'cond' ? '报告④（每类可多张）' : '报告⑦' }} · {{ g.items.length }} 张
            </span>
          </div>
          <div class="wcai-shots">
            <div v-for="(p, i) in g.items" :key="p.photo_id"
                 class="wcai-shot" :class="{ pick: isSupPick(g.kind, g.tag, p.photo_id) }"
                 :title="g.kind === 'cond'
                   ? '加入/移出报告④「' + g.label + '」（可多张）' : '加入/移出报告⑦'"
                 @click="toggleSup(g.kind, g.tag, p.photo_id)">
              <img loading="lazy" :src="'/thumb/' + p.photo_id" :alt="g.label" />
              <span class="wcai-zoom" title="看大图"
                    @click.stop="zoom(p.photo_id, g.label, p.taken_at)">⤢</span>
              <!-- cond 组第一张 = 最新 = 后端不点时的自动值 -->
              <span v-if="isSupPick(g.kind, g.tag, p.photo_id)" class="rec mine">
                ✓{{ g.kind === 'cond' ? '④' : '⑦' }}</span>
              <span v-else-if="g.kind === 'cond' && i === 0" class="rec">自动</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <PhotoViewer v-if="viewerSrc" :src="viewerSrc" :cap="viewerCap" :taken="viewerTaken"
                 :pid="viewerPid" @close="viewerSrc = ''" @detail="openDrawer" />
    <PhotoDrawer v-if="drawerPid" :pid="drawerPid" @close="drawerPid = ''" />
  </div>
</template>

<script setup>
/* StepPicks.vue —— ④选图：给报告挑用图
 *
 * 两块：预检照片（编码核对照）与监装照片（柜况④每类多选 / 卡车⑦多选）。
 *
 * 🔴 编码池全自动：进④自动载清单编码并检索（老板 10-11 去掉了手动按钮）。
 * 🔴 三态语义（10-11 定，写错会让「⑦不要卡车照片」变成自动全选）：
 *   trucks: [] 是「明确一张都不要」，**没动过则不带键**（后端自动取）。
 *   这个「动过没有」由 supTouched()（localStorage 有键）判定，不靠数组空不空。
 * 🔴 统计条数字全部来自后端 progress.steps.picks.stats，前端不重算。
 * 🔴 分组口径（哪些 tag 算柜况、哪些进⑦、tag 中文名）由后端下发，不抄第二份。 */
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { post, api } from '../../api.js'
import {
  wiz, pickCount, condCount, supTouched, savePicks, loadPicks,
  saveSup, loadSup, resetSup, getPickTab, setPickTab,
} from '../../lib/wizardStore.js'
import PhotoViewer from '../PhotoViewer.vue'
import PhotoDrawer from '../PhotoDrawer.vue'

const props = defineProps({
  cid: { type: String, required: true },
  stats: { type: Object, default: null },
})
const emit = defineEmits(['picked'])

const tab = ref(getPickTab())
const rp = ref(null)
const looking = ref(false)
const moreOn = ref(false)
const strategy = ref(wiz.strategy || 'balanced')
const codes = ref([])
const supGroups = ref(null)
const supErr = ref('')
const viewerSrc = ref('')
const viewerCap = ref('')
const viewerTaken = ref('')
const viewerPid = ref('')
const drawerPid = ref('')

/* 策略清单由后端下发（lookup 返回的 strategies）—— 不在前端抄一份 */
const strategies = computed(() => {
  const l = (rp.value && rp.value.strategies) || wiz.strategies
  return (l && l.length) ? l : [{ key: 'balanced', label: '均衡（标准图 / 最新 / 高清 综合打分）' }]
})
const pickN = computed(() => pickCount() + wiz.trucks.length + condCount())
const codeN = computed(() => Object.keys(wiz.picks).length)
const hitItems = computed(() => ((rp.value && rp.value.items) || []).filter((x) => x.found))
const hitN = computed(() => hitItems.value.length)
const missN = computed(() => ((rp.value && rp.value.items) || []).filter((x) => !x.found).length)
const recN = computed(() => hitItems.value.filter((it) => recOf(it)).length)
const pickTip = computed(() => (pickN.value
  ? '已采用 ' + pickN.value + ' 张，会作为报告⑥的用图'
  : '还没标记采用 —— 不标记也能出报告（按编码自动取图）'))

const isPick = (code, pid) => (wiz.picks[code] || []).map(String).includes(String(pid))
const recOf = (it) => ((it.photos || []).find((p) => p.recommended) || null)
function shotTitle(it, p) {
  const base = isPick(it.code_norm, p.photo_id) ? '取消采用' : '设为报告用图'
  return base + (p.reasons && p.reasons.length ? '：' + p.reasons[0] : '')
}

function togglePick(code, pid) {
  const arr = wiz.picks[code] || (wiz.picks[code] = [])
  const i = arr.map(String).indexOf(String(pid))
  if (i >= 0) arr.splice(i, 1)
  else arr.push(String(pid))
  if (!arr.length) delete wiz.picks[code]
  savePicks()
  emit('picked')
}

function adoptOne(it) {
  const rec = recOf(it)
  if (!rec) return
  wiz.picks[it.code_norm] = [String(rec.photo_id)]
  savePicks()
  emit('picked')
}

async function adoptAll() {
  const withRec = hitItems.value.filter((it) => recOf(it))
  if (!withRec.length) { ElMessage.warning('这次检索没有带「建议采用」的结果'); return }
  /* 覆盖前必须确认：手动挑过的往往是老板特意选的 */
  if (pickN.value) {
    try {
      await ElMessageBox.confirm(
        '把 ' + withRec.length + ' 个编码全部设为建议图？\n\n会覆盖你已手动指定的 '
        + pickN.value + ' 张用图。', '全部采用建议图', { type: 'warning' })
    } catch { return }
  }
  withRec.forEach((x) => {
    const rec = recOf(x)
    if (rec) wiz.picks[x.code_norm] = [String(rec.photo_id)]
  })
  savePicks()
  emit('picked')
  ElMessage.success('已批量采用 ' + withRec.length + ' 个编码的建议图')
}

async function clearPicks() {
  if (pickN.value) {
    try {
      await ElMessageBox.confirm('清空本柜已选的全部用图？', '清空采用', { type: 'warning' })
    } catch { return }
  }
  Object.keys(wiz.picks).forEach((k) => delete wiz.picks[k])
  savePicks()
  emit('picked')
  ElMessage.success('已清空采用')
}

/* ── 监装候选：柜况④多选 / 卡车⑦多选 ── */
const isSupPick = (kind, tag, pid) => (kind === 'cond'
  ? (wiz.conds[tag] || []).map(String).includes(String(pid))
  : wiz.trucks.map(String).includes(String(pid)))

function toggleSup(kind, tag, pid) {
  const k = String(pid)
  if (kind === 'cond') {
    const arr = wiz.conds[tag] || []
    const i = arr.map(String).indexOf(k)
    if (i >= 0) arr.splice(i, 1)
    else arr.push(k)
    wiz.conds[tag] = arr                 /* 空数组也留着：= 这一类明确一张不要 */
  } else {
    const i = wiz.trucks.map(String).indexOf(k)
    if (i >= 0) wiz.trucks.splice(i, 1)
    else wiz.trucks.push(k)
  }
  saveSup()                              /* 写键 = 「动过」，⑤ 靠它决定传不传 trucks/conds */
  emit('picked')
}

async function resetSupAll() {
  try {
    await ElMessageBox.confirm(
      '清掉监装照片的人工指定？\n\n报告④回到每类最新一张（多选清空），⑦回到全部监装照。',
      '恢复自动', { type: 'warning' })
  } catch { return }
  resetSup()
  loadSupPhotos()
  emit('picked')
  ElMessage.success('监装照片已恢复自动取图')
}

async function loadSupPhotos() {
  if (!props.cid) { supGroups.value = null; return }
  supErr.value = ''
  try {
    supGroups.value = await api('/api/containers/' + props.cid + '/supervision-photos')
  } catch (e) {
    supGroups.value = null
    supErr.value = '读取监装照片失败：' + e.message
  }
}

async function loadCodes() {
  try {
    const d = await api('/api/containers/' + props.cid + '/checklist')
    const seen = new Set()
    codes.value = (d.items || [])
      .filter((r) => r.code_norm && !seen.has(r.code_norm) && seen.add(r.code_norm))
      .map((r) => r.code_norm)
  } catch {
    codes.value = []
  }
}

async function lookup(quiet) {
  if (!codes.value.length) {
    if (!quiet) ElMessage.warning('还没有清单编码 —— 先到②导入清单')
    rp.value = null
    return
  }
  looking.value = true
  try {
    const r = await post('/api/report/lookup', {
      codes: codes.value, container_id: props.cid,
      std_only: false, std_prefer: true, strategy: strategy.value,
    })
    rp.value = r
    if (r.strategies && r.strategies.length) wiz.strategies = r.strategies
    wiz.strategy = strategy.value
    emit('picked')
    if (!quiet) ElMessage.success('命中 ' + r.matched + ' · 缺口 ' + r.missing)
  } catch (e) {
    if (!quiet) ElMessage.error('检索失败：' + e.message)
  } finally {
    looking.value = false
  }
}

/* 切策略 → 按新策略重算「建议采用」的那一张 */
async function onStrategy(v) {
  strategy.value = v
  await lookup(true)
  const lb = (strategies.value.find((s) => s.key === v) || {}).label || v
  ElMessage.success('已切换为「' + lb + '」，建议图已重算')
}

function onTab(t) {
  setPickTab(t)
  /* 切到监装时顺手重拉候选（③里可能刚确认过细分，候选分组会变） */
  if (t === 'sup') loadSupPhotos()
}

function zoom(pid, cap, taken) {
  viewerPid.value = String(pid)
  viewerSrc.value = '/img/' + pid
  viewerCap.value = cap || ''
  viewerTaken.value = taken || ''
}
function openDrawer(pid) {
  viewerSrc.value = ''
  drawerPid.value = pid
}

/* 每个柜只自动载一次编码池 + 检索一次（避免每次进④都重跑） */
watch(() => props.cid, async (id) => {
  rp.value = null
  supGroups.value = null
  loadPicks()
  loadSup()
  wiz.lpFor = ''
  if (!id) return
  await loadCodes()
  await loadSupPhotos()
  if (wiz.lpFor !== id) {
    wiz.lpFor = id
    await lookup(true)
  }
})

onMounted(async () => {
  loadPicks()
  loadSup()
  await loadCodes()
  await loadSupPhotos()
  wiz.lpFor = props.cid
  await lookup(true)
})

/* 父组件的「重新检索」按钮 */
defineExpose({
  reload: async () => {
    await loadCodes()
    await loadSupPhotos()
    await lookup(true)
  },
})
</script>

<style scoped>
.w-picks { display: flex; flex-direction: column; gap: 8px; }
.wd-h { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.wd-h .spacer { flex: 1; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; font-weight: normal; }
.row { display: flex; align-items: center; gap: 8px; }
.ptab-seg { margin-bottom: 6px; }
/* 柜级统计条 */
.wpstat { margin-bottom: 8px; }
.wpstat-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.wpstat-row .spacer { flex: 1; }
.wpstat-c { display: inline-flex; align-items: baseline; gap: 4px; }
.wpstat-c b { font-size: 17px; }
.wpstat-c em { font-style: normal; font-size: 12px; color: var(--el-text-color-secondary); }
.wpstat-c.ok b { color: var(--el-color-success); }
.wpstat-c.warn b { color: var(--el-color-warning); }
.wpstat-c.std b { color: var(--el-color-primary); }
.wpstat-rate { font-size: 12px; color: var(--el-text-color-secondary); }
.wpstat-bar { height: 6px; background: var(--el-fill-color); border-radius: 3px; margin: 6px 0; }
.wpstat-bar i { display: block; height: 100%; background: var(--el-color-primary); border-radius: 3px; }
.wclbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 6px 0; }
.wclbar .spacer { flex: 1; }
.wcai-list { margin-top: 6px; }
.wcai-item { padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.wcai-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.wcai-head .code { font-family: ui-monospace, Menlo, Consolas, monospace; }
.wcai-shots { display: flex; gap: 8px; flex-wrap: wrap; }
.wcai-shot { position: relative; cursor: pointer; }
.wcai-shot img {
  width: 110px; height: 82px; object-fit: cover; border-radius: 4px;
  border: 2px solid transparent;
}
.wcai-shot.pick img { border-color: var(--el-color-primary); }
.wcai-zoom {
  position: absolute; top: 2px; right: 4px; color: #fff; font-size: 13px;
  text-shadow: 0 1px 3px rgba(0, 0, 0, .7); cursor: zoom-in;
}
.rec {
  position: absolute; left: 2px; bottom: 2px; font-size: 11px;
  background: rgba(0, 0, 0, .6); color: #fff; padding: 0 5px; border-radius: 3px;
}
.rec.mine { background: var(--el-color-primary); }
</style>