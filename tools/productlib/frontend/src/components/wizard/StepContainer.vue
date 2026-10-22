<template>
  <!-- ① 建柜 / 柜信息（可编辑）—— 视觉打磨版：
       卡片化头部（状态 + 缺项提示）→ 柜号身份卡 → 双列字段网格 → 清爽页脚。
       只改观感与结构，快照/dirty/保存逻辑一行不动。 -->
  <div class="sc">
    <!-- 头部：标题 + 状态 + 缺项提示 -->
    <div class="sc-head">
      <div class="sc-title">
        <h3>柜信息</h3>
        <span class="faint">柜号是全流程主线，下面的信息会进报告 General Information</span>
        <span class="spacer"></span>
        <el-tag v-if="!missing.length" type="success" effect="light" size="small">信息已齐 ✓</el-tag>
        <el-tag v-else type="warning" effect="light" size="small">缺 {{ missing.length }} 项</el-tag>
      </div>
      <div v-if="missing.length" class="sc-missing">
        <span class="lb">缺：</span>
        <el-tag v-for="m in missing" :key="m" type="warning" effect="plain" size="small">{{ m }}</el-tag>
        <span class="tip">补齐后报告 General Information 才完整</span>
      </div>
      <div v-else class="sc-missing ok">
        <span class="lb">✓</span> 柜信息已齐，可出报告。
      </div>
    </div>

    <!-- 柜号：身份标识，独立强调 -->
    <div class="sc-id">
      <span class="id">{{ detail.container_no || '（未分柜）' }}</span>
      <span class="faint">柜号 · 身份标识，不可改</span>
    </div>

    <!-- 元数据：双列网格，标签在顶，横向更透气 -->
    <el-form label-position="top" class="sc-form">
      <div class="sc-grid">
        <el-form-item v-for="[k, lb] in META_FIELDS" :key="k" :label="lb" class="sc-item">
          <el-input v-model="draft[k]" placeholder="未填" clearable style="width:100%"
                    :class="{ dirty: dirtyOf(k) }" />
        </el-form-item>
      </div>
      <el-form-item label="备注（REMARKS）" class="sc-item wide">
        <el-input v-model="draft.remark" type="textarea" :rows="2" placeholder="可后补"
                  style="width:100%" />
      </el-form-item>
    </el-form>

    <!-- 页脚：动作 + 未保存提示 -->
    <div class="sc-foot">
      <el-button type="primary" :disabled="!dirtyCount" :loading="saving" @click="save">保存修改</el-button>
      <el-button :disabled="!dirtyCount" @click="reset">还原</el-button>
      <span class="faint dirty-n">{{ dirtyCount ? '有 ' + dirtyCount + ' 处未保存' : '全部已保存' }}</span>
    </div>
  </div>
</template>

<script setup>
/* StepContainer.vue —— ① 建柜 / 柜信息（可编辑）
 *
 * 快照语义：draft 是「进页面时的已保存值」。只有跟快照不同的字段才进 payload，
 * 空串映射成 null（清空）。这样「把某字段清空」也能正确落库。
 *
 * ⚠️ dirtyCount 要暴露给父组件 —— 切步骤时用它决定是否弹离开确认
 *   （旧版是遍历 DOM 数，改成 Vue 后两套真源会漂）。 */
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../api.js'

const props = defineProps({
  detail: { type: Object, required: true },
  cid: { type: String, required: true },
})
const emit = defineEmits(['saved'])

const META_FIELDS = [
  ['seal_no', '封条号'], ['client_name', '客户'], ['inspector', 'Inspector'],
  ['location', 'Location'], ['product_name', 'Product'],
  ['arrival_at', '到达日期（Arrival time）'], ['departure_at', '完成日期（Departure time）'],
]

const draft = reactive({})
const snapshot = ref({})
const saving = ref(false)

function fill() {
  const s = {}
  META_FIELDS.forEach(([k]) => { s[k] = props.detail[k] || '' })
  s.remark = props.detail.remark || ''
  snapshot.value = { ...s }
  Object.keys(draft).forEach((k) => delete draft[k])
  Object.assign(draft, s)
}
watch(() => props.detail, fill, { immediate: true, deep: false })

const dirtyOf = (k) => (draft[k] || '') !== String(snapshot.value[k] || '')
const dirtyCount = computed(() => META_FIELDS.filter(([k]) => dirtyOf(k)).length
  + (dirtyOf('remark') ? 1 : 0))

/* 缺项：为空的元数据（柜号是身份标识，不算缺） */
const missing = computed(() =>
  META_FIELDS.filter(([k]) => !(draft[k] || '').trim()).map(([, lb]) => lb.replace(/（.*/, '')))

function reset() { Object.assign(draft, snapshot.value) }

async function save() {
  const payload = {}
  META_FIELDS.forEach(([k]) => {
    const v = (draft[k] || '').trim()
    if (v !== String(snapshot.value[k] || '')) payload[k] = v || null   // 空串 = 清空
  })
  if ((draft.remark || '').trim() !== String(snapshot.value.remark || '')) {
    payload.remark = (draft.remark || '').trim() || null
  }
  if (!Object.keys(payload).length) return
  saving.value = true
  try {
    const r = await fetch('/api/containers/' + props.cid, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || ('HTTP ' + r.status))
    ElMessage.success('柜信息已保存')
    snapshot.value = JSON.parse(JSON.stringify(draft))
    emit('saved')
  } catch (e) {
    ElMessage.error('保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}

/* 暴露给父组件的「未保存处数」，切步骤时做离开拦截 */
defineExpose({ dirtyCount })
</script>

<style scoped>
/* 表单宽度：宽屏下居中并撑到舒适宽度，避免「表单窄窄一条贴左、右边一大片空白」
   的观感（老板在宽屏上反馈「页面一半是空的」）。窄屏由可用空间自然约束。 */
.sc { width: 100%; max-width: 1100px; margin: 0 auto; }

/* ── 头部 ── */
.sc-head {
  border: 1px solid var(--pl-line); border-radius: var(--pl-radius);
  background: var(--pl-panel); padding: 14px 16px;
  box-shadow: var(--pl-shadow);
}
.sc-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sc-title h3 { margin: 0; font-size: 15px; font-weight: 600; }
.sc-title .spacer { flex: 1; }
.sc-missing { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-top: 10px; font-size: 12px; }
.sc-missing .lb { color: var(--pl-warn); font-weight: 600; }
.sc-missing .tip { color: var(--pl-muted); }
.sc-missing.ok .lb { color: var(--pl-ok); }

/* ── 柜号身份卡 ── */
.sc-id {
  display: flex; align-items: baseline; gap: 12px;
  margin: 14px 0; padding: 14px 16px;
  background: linear-gradient(135deg, var(--pl-brand-soft), #f4f7ff);
  border: 1px solid #dbe7fd; border-radius: var(--pl-radius);
}
.sc-id .id { font-size: 20px; font-weight: 700; letter-spacing: 1px;
  font-family: ui-monospace, Menlo, Consolas, monospace; color: var(--pl-brand-ink); }
.sc-id .faint { margin-left: auto; }

/* ── 表单：双列网格，标签在顶 ── */
.sc-form { margin-top: 4px; }
.sc-grid { display: grid; grid-template-columns: repeat(2, 1fr);
  column-gap: 22px; row-gap: 2px; }
.sc-item :deep(.el-form-item__label) { font-size: 12.5px; color: var(--pl-muted);
  line-height: 1.4; padding-bottom: 4px; }
/* ⚠️ 必须把 .el-input/.el-textarea 根元素撑满：grid 单元格里的 el-form-item 是
   display:flex，.el-form-item__content flex:1，但 el-input 根默认不 100% 撑满，
   会被压成内容宽度（一条窄缝），右侧大片空白。强制 width:100%。
   这组规则写成对任何视口都成立的强约束（width:100% + min-width:0），
   避免个别宽屏/缩放下 el-form-item 内部 flex 高度/宽度错位。 */
.sc-item { width: 100%; min-width: 0; }
.sc-item :deep(.el-form-item__content) { width: 100%; min-width: 0; flex: none; }
.sc-item :deep(.el-input),
.sc-item :deep(.el-textarea) { width: 100% !important; }
.sc-item :deep(.el-input__wrapper), .sc-item :deep(.el-textarea__inner) {
  background: var(--pl-panel-2); }
.sc-item :deep(.el-input__wrapper:hover), .sc-item :deep(.el-textarea__inner:hover) {
  background: var(--pl-panel); }
.sc-item.wide { margin-top: 4px; }
.dirty :deep(.el-input__wrapper) {
  background: var(--pl-warn-soft) !important; box-shadow: 0 0 0 1px var(--pl-warn) inset;
}

/* ── 页脚 ── */
.sc-foot { display: flex; align-items: center; gap: 8px; margin-top: 6px;
  border-top: 1px solid var(--pl-line-2); padding-top: 12px; }
.sc-foot .dirty-n { margin-left: auto; }
.faint { color: var(--pl-muted); font-size: 12px; }
</style>
