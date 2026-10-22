<template>
  <!-- 编码联想输入（对应旧版 drawer.js attachCodeSuggest）
       输入 ≥2 位联想 /api/products/suggest；↑↓ 选择、Enter 选中、Esc 关闭、点选同选中。
       @pick 提供选中回调；不传则选中只填框（如全景编码框）。 -->
  <div class="cs-wrap">
    <el-input :model-value="modelValue" size="small" :placeholder="placeholder" clearable
              @update:model-value="onInput" @keydown="onKey" @blur="onBlur" @focus="onFocus" />
    <div v-if="open && items.length" class="cs-pop">
      <div v-for="(p, i) in items" :key="p.code_norm"
           :class="['cs-item', { cur: i === idx }]"
           @mousedown.prevent="pick(items[i])">
        <span class="c">{{ p.code_norm }}</span>
        <span v-if="p.name" class="n">{{ p.name }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
/* CodeSuggest.vue —— 手输产品编码时的联想下拉。
 *
 * ⚠️ 下拉用 position:absolute 挂在输入框容器内（旧版 fixed + 实时坐标是为了
 *    挂在 body 上避开定位祖先；Vue 组件内部挂靠更稳，不随滚动跑偏）。
 * ⚠️ 每个实例自己的 items/idx/open —— 不会像旧版固定 id 那样两框共用一套。 */
import { ref, watch, onBeforeUnmount } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '手输编码' },
})
const emit = defineEmits(['update:modelValue', 'pick', 'enter'])

const items = ref([])
const idx = ref(-1)
const open = ref(false)
let timer = null
let blurred = false

async function suggest(q) {
  if (q.length < 2) { items.value = []; open.value = false; return }
  try {
    const d = await api('/api/products/suggest?q=' + encodeURIComponent(q))
    items.value = d.items || []
    idx.value = items.value.length ? 0 : -1
    open.value = items.value.length > 0
  } catch { items.value = []; open.value = false }
}

function onInput(v) {
  emit('update:modelValue', v)
  clearTimeout(timer)
  timer = setTimeout(() => suggest((v || '').trim()), 200)
}

function pick(p) {
  if (!p) return
  emit('update:modelValue', p.code_norm)
  emit('pick', p.code_norm)
  close()
}

function close() { open.value = false; idx.value = -1 }

function onKey(e) {
  if (!open.value || !items.value.length) {
    if (e.key === 'Enter') emit('enter')       // 无下拉时回车原样提交（如直接关联）
    return
  }
  if (e.key === 'ArrowDown') { idx.value = Math.min(items.value.length - 1, idx.value + 1); e.preventDefault() }
  else if (e.key === 'ArrowUp') { idx.value = Math.max(0, idx.value - 1); e.preventDefault() }
  else if (e.key === 'Enter') { pick(items.value[idx.value]); e.preventDefault() }
  else if (e.key === 'Escape') { close() }
}

function onBlur() {
  /* 留时间给 mousedown 点选（点选用 preventDown 不抢 blur 顺序） */
  blurred = true
  setTimeout(() => { if (blurred) close() }, 150)
}
function onFocus() { blurred = false }

onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<style scoped>
.cs-wrap { position: relative; }
.cs-pop {
  position: absolute; left: 0; top: calc(100% + 4px); z-index: 30; width: 100%;
  background: #fff; border: 1px solid var(--pl-line); border-radius: 8px;
  box-shadow: var(--pl-shadow-lg); max-height: 220px; overflow: auto;
}
.cs-item { display: flex; align-items: center; gap: 8px; padding: 6px 10px; cursor: pointer; }
.cs-item.cur { background: var(--pl-line-2); }
.cs-item .c { font-weight: 600; font-family: ui-monospace, Menlo, Consolas, monospace; }
.cs-item .n { color: var(--pl-muted); font-size: 12px; }
</style>
