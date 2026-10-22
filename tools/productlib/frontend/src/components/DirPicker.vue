<template>
  <el-dialog :model-value="modelValue" title="选择目录" width="600px"
             :close-on-click-modal="true"
             @update:model-value="$emit('update:modelValue', $event)">
    <div class="dpbar">
      <el-button size="small" :disabled="!browse.parent" @click="browsePath(browse.parent)">
        ↑ 上级
      </el-button>
      <span class="faint dppath">{{ browse.current || '（选择盘符）' }}</span>
    </div>
    <div v-loading="browsing" class="dplist">
      <div v-if="!browsing && !browse.items.length" class="faint none">空目录</div>
      <div v-for="it in browse.items" :key="it.path" class="dpitem"
           @click="browsePath(it.path)">
        <span>📁</span>
        <span class="nm">{{ it.name }}</span>
        <span class="faint">进入 ›</span>
      </div>
    </div>
    <template #footer>
      <span class="faint">当前：{{ browse.current || '未选择' }}</span>
      <el-button size="small" @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button size="small" type="primary" :disabled="!browse.current" @click="pickOk">
        选择此目录
      </el-button>
    </template>
  </el-dialog>
</template>

<script>
/* DirPicker.vue —— 本机目录选择弹窗（通过 /api/browse 浏览后端文件系统）
 *
 * 绿色包里没有「打开文件夹」对话框可用，只能走后端浏览 + 逐级进入。
 * 单独抽成组件：设置页的「标准库落盘目录」和柜页的标准库目录都用它。
 *
 * ⚠️ 显隐必须由 props.modelValue 驱动（:model-value + @update:model-value），
 *    自己另开一个局部 v-model 变量弹窗永远不会开。
 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api.js'

export default {
  name: 'DirPicker',
  props: {
    modelValue: { type: Boolean, default: false },
  },
  emits: ['update:modelValue', 'pick'],
  setup(props, { emit }) {
    const browse = ref({ current: '', parent: null, items: [] })
    const browsing = ref(false)

    async function browsePath(path) {
      browsing.value = true
      try {
        const d = await api('/api/browse' + (path ? '?path=' + encodeURIComponent(path) : ''))
        browse.value = { current: d.current || '', parent: d.parent || null, items: d.items || [] }
      } catch (e) {
        ElMessage.error('读取失败：' + e.message)
      } finally { browsing.value = false }
    }
    /* 打开即刷新：上次的浏览结果不该带进这一次 */
    watch(() => props.modelValue, (v) => { if (v) browsePath('') })
    function pickOk() {
      emit('pick', browse.value.current)
      emit('update:modelValue', false)
    }
    return { browse, browsing, browsePath, pickOk }
  },
}
</script>

<style scoped>
.dpbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.dppath { word-break: break-all; }
.dplist { max-height: 320px; overflow-y: auto; border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px; }
.dpitem { display: flex; align-items: center; gap: 10px; padding: 7px 12px; cursor: pointer; }
.dpitem:hover { background: var(--el-color-primary-light-9); }
.dpitem .nm { flex: 1; }
.none { padding: 30px; text-align: center; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>