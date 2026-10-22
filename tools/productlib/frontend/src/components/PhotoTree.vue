<template>
  <div class="ptree">
    <div v-for="sec in sections" :key="sec.key" class="ptree-sec" :data-sec="sec.key">
      <div class="ptree-t">
        {{ sec.title }}
        <span v-if="selected(sec).length" class="ptree-cnt">{{ selected(sec).length }}</span>
        <button v-if="selected(sec).length" class="ptree-clr"
                :title="'清空本段已选（' + selected(sec).length + ' 项）'"
                @click="clear(sec.key)">清空</button>
      </div>
      <div v-if="!sec.items.length" class="ptree-empty">（没有）</div>
      <button v-for="it in sec.items" :key="sec.key + ':' + it.v" :data-v="it.v"
              class="ptree-i" :class="{ on: isOn(sec, it.v) }"
              :title="it.label + '（' + it.n + ' 张）' + (isOn(sec, it.v) ? ' —— 再点一次取消' : '')"
              @click="pick(sec.key, it.v)">
        <span class="ptree-cb"></span>
        <span class="ptree-l">{{ it.label }}</span>
        <span class="ptree-n" :class="{ zero: !it.n }">{{ it.n }}</span>
      </button>
    </div>
    <!-- ③柜作业专用：待确认细分（监装照的细分没人工确认 / 未标用途但模型给了建议）。
         计数来自 /api/containers/{cid}/supervision-pending，与待办视图同一份集合。 -->
    <div v-if="showPending" class="ptree-sec">
      <div class="ptree-t">待办</div>
      <button class="ptree-i" :class="{ on: f.pending === 1 }"
              title="监装照片还没人工确认细分（再点一次取消）"
              @click="pick('pending', '1')">
        <span class="ptree-l">待确认细分</span>
        <span class="ptree-n" :class="{ zero: !pendingN }">{{ pendingN == null ? '—' : pendingN }}</span>
      </button>
      <div v-if="pendingN === 0" class="ptree-empty">（没有待确认）</div>
    </div>
    <div v-if="loading" class="ptree-empty">计数读取中…</div>
    <div v-else-if="error" class="ptree-empty">计数读取失败</div>
  </div>
</template>

<script setup>
/* PhotoTree.vue —— 照片页左侧「用途 → 分类」树形筛选（③柜作业也复用它）
 *
 * 为什么是树而不是又一排下拉：下拉里看不到「有哪些」，树把用途/分类全集与
 * **当前范围内各有多少张**直接摆出来。计数与列表同源（/api/photos/facets 与
 * /api/photos 共用 photo_where_sql），树上点进去的条数不会对不上。
 *
 * 交叉筛选：选了「监装」后分类计数只算监装照的；选分类后用途计数只算该分类的。
 * 再点一次已选项 = 取消。
 *
 * ⚠️ 筛选真源由 props.f 给（照片库页传默认单例，③柜作业传自己那份）——
 *    这里**直接改它**（旧版是树改隐藏下拉的值，两套状态容易漂）。 */
import { ref, watch, computed } from 'vue'
import { api } from '../api.js'
import { filters } from '../lib/photosStore.js'
import { KIND_LABELS, qs } from '../lib/core.js'

const props = defineProps({
  /* 筛选真源。默认用照片库那份单例 */
  f: { type: Object, default: () => filters },
  /* ③柜作业：显示「待确认细分」这一维 */
  showPending: { type: Boolean, default: false },
  pendingN: { type: Number, default: null },
})
const f = props.f
const emit = defineEmits(['change'])

const loading = ref(false)
const error = ref(false)
const facets = ref({ usage: {}, kind: {} })

/* 用途顺序 = 编号序（01 监装 → 02 预检 → 03 其他 → 未分类收尾），文案不带编号 */
const USAGE_ORDER = ['监装', '预检', '其他', '_unset']
const usageLabel = (u) => (!u || u === '_unset' ? '未分类' : u)
/* facets 把 NULL 归到 '_unset'（后端 IFNULL）—— 显示成「未分类」，别裸露内部键名 */
const kindLabel = (k) => (k === '_unset' ? '未分类' : KIND_LABELS[k] || k || '未识别')

async function load() {
  loading.value = true
  error.value = false
  try {
    facets.value = await api('/api/photos/facets?' + qs({
      container_id: f.container_id,
      batch: f.batch,
      state: f.state,
      q: f.q,
      unlinked: f.unlinked ? 1 : 0,
      invalid: f.invalid,
      kind: f.kind,
      usage: f.usage,
      todo: f.todo,
    }))
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

const sections = computed(() => {
  const usageRank = (v) => {
    const i = USAGE_ORDER.indexOf(v)
    return i < 0 ? 99 : i
  }
  const usageItems = Object.entries(facets.value.usage || {})
    .map(([v, n]) => ({ v, label: usageLabel(v), n }))
    .sort((a, b) => usageRank(a.v) - usageRank(b.v) || b.n - a.n)
  const kindItems = Object.entries(facets.value.kind || {})
    .map(([v, n]) => ({ v, label: kindLabel(v), n }))
    .sort((a, b) => b.n - a.n || a.label.localeCompare(b.label, 'zh'))
  return [
    { key: 'usage', title: '按用途', items: usageItems },
    { key: 'kind', title: '按分类', items: kindItems },
  ]
})

/* 多选（2026-10-19）：f.usage / f.kind 存**逗号分隔**的字符串（后端
   photo_where_sql 走 IN），界面上是 checkbox 集合 —— 点已选 = 移出集合。
   ⚠️ 计数必须排除自身维度（后端已改）：否则选了 A 之后分类段只剩 A 一项，
   用户点不到 B，勾选框再多也等于单选（老板反馈的原话）。 */
const selected = (sec) => (f[sec.key] || '').split(',').filter(Boolean)
const isOn = (sec, v) => selected(sec).includes(v)

function pick(dim, v) {
  if (dim === 'pending') {
    f.pending = f.pending === 1 || f.pending === '1' ? 0 : 1
    emit('change')
    return
  }
  const cur = (f[dim] || '').split(',').filter(Boolean)
  const i = cur.indexOf(v)
  if (i >= 0) cur.splice(i, 1)
  else cur.push(v)
  f[dim] = cur.join(',')
  emit('change')
}

function clear(dim) {
  f[dim] = ''
  emit('change')
}

/* 任一筛选维度变了都要重算计数（交叉筛选）；深链接初始化时也跑一次。 */
watch(() => [f.container_id, f.batch, f.state, f.q,
  f.unlinked, f.invalid, f.todo, f.usage, f.kind],
  () => { load() }, { immediate: true })

defineExpose({ load })
</script>

<style scoped>
.ptree { font-size: 13px; }
.ptree-sec + .ptree-sec { margin-top: 10px; border-top: 1px solid var(--el-border-color-lighter); padding-top: 8px; }
.ptree-t {
  font-size: 12px; font-weight: 600; color: var(--el-text-color-secondary);
  padding: 2px 8px 6px; display: flex; align-items: center; gap: 6px;
}
/* 多选（2026-10-19）：空心方框 + 已选数 + 清空 —— 一眼看出「可以多选」 */
.ptree-cb {
  flex: none; width: 14px; height: 14px; border: 1.5px solid var(--el-text-color-secondary);
  border-radius: 3px; position: relative; background: var(--el-bg-color);
}
.ptree-i.on .ptree-cb { background: var(--el-color-primary); border-color: var(--el-color-primary); }
.ptree-i.on .ptree-cb::after {
  content: ''; position: absolute; left: 3.5px; top: 0.5px; width: 4px; height: 8px;
  border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg);
}
.ptree-cnt {
  font-size: 11px; font-weight: 700; color: #fff; background: var(--el-color-primary);
  border-radius: 9px; padding: 0 6px; line-height: 16px;
}
.ptree-clr {
  margin-left: auto; border: 0; background: none; cursor: pointer; font-size: 11px;
  color: var(--el-text-color-secondary); padding: 0 2px; text-decoration: underline;
}
.ptree-clr:hover { color: var(--el-color-primary); }
.ptree-i {
  display: flex; align-items: center; gap: 6px; width: 100%; text-align: left;
  border: 0; background: none; cursor: pointer; font-size: 13px;
  color: var(--el-text-color-primary); padding: 6px 8px; border-radius: 6px; line-height: 1.3;
}
.ptree-i:hover { background: var(--el-fill-color-light); }
.ptree-i.on { background: var(--el-color-primary-light-9); color: var(--el-color-primary); font-weight: 600; }
.ptree-l { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ptree-n {
  font-size: 11px; background: var(--el-fill-color); color: var(--el-text-color-secondary);
  border-radius: 9px; padding: 1px 7px; font-weight: 600; flex: none;
}
.ptree-i.on .ptree-n { background: var(--el-color-primary); color: #fff; }
/* 计数为 0 时要看得见（「这一类确实没有」与「还没查完」要分得开） */
.ptree-n.zero { background: transparent; color: var(--el-text-color-placeholder); border: 1px dashed var(--el-border-color); }
.ptree-empty { font-size: 12px; color: var(--el-text-color-placeholder); padding: 4px 8px; }
</style>
