<template>
  <el-dialog :model-value="modelValue" title="导入货品清单" width="520px"
             @update:model-value="$emit('update:modelValue', $event)">
    <p class="faint">
      将导入到<b>当前所选柜</b>。柜号是流程第一步，无柜不导 ——
      在「柜作业」右上角或下面的选择器里选柜。
    </p>
    <el-form label-width="80px">
      <el-form-item label="柜">
        <el-tag v-if="cidName">{{ cidName }}</el-tag>
        <el-tag v-else type="warning">还没选柜</el-tag>
      </el-form-item>
      <el-form-item label="Excel">
        <input type="file" accept=".xls,.xlsx" @change="onPick" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="busy" @click="run">导入</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
/* ImportChecklistDialog.vue —— 导入货品清单（产品库页与柜作业②共用一份）
 *
 * 柜**只读展示**（取自全局锚点）：导入目标以锚点为准，不在这里再选一次柜，
 * 否则「在向导选了 A 柜、在产品库导到 B 柜」这种三份真相的毛病又回来。
 *
 * 🔴 清单导入端点只有一个（POST /api/products/import），旧版曾有个
 *    /api/photos/import-checklist 是不存在的臆造 —— 别再加第二个。
 */
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { upload } from '../api.js'
import { anchor, opts, loadContainerOptions, bus } from '../lib/photosStore.js'

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'done'])

const file = ref(null)
const busy = ref(false)

const cid = computed(() => anchor.cid)
const cidName = computed(() => {
  const c = (opts.containers || []).find((x) => x.id === anchor.cid)
  return c ? c.container_no : (anchor.cid || '')
})

watch(() => props.modelValue, (on) => {
  if (!on) return
  file.value = null
  if (!(opts.containers || []).length) loadContainerOptions()
})

function onPick(e) { file.value = (e.target.files || [])[0] || null }

async function run() {
  if (!cid.value) { ElMessage.warning('请先选择柜'); return }
  if (!file.value) { ElMessage.warning('请选择 Excel 文件（.xls / .xlsx）'); return }
  busy.value = true
  const fd = new FormData()
  fd.append('file', file.value)
  fd.append('container_id', cid.value)
  try {
    const r = await upload('/api/products/import', fd)
    let msg = '清单导入完成：解析 ' + r.parsed + ' 条，新增 ' + r.added + '，合并 ' + r.updated
      + ((r.errors && r.errors.length) ? '，跳过 ' + r.errors.length + ' 行（编码不合规）' : '')
    if (r.relink_error) msg += '。补关联未执行：' + r.relink_error
    else if (r.relink && r.relink.written > 0) msg += '。补关联 +' + r.relink.written + ' 条'
    ElMessage.success(msg)
    emit('update:modelValue', false)
    emit('done')
    bus.emit('checklist:changed')
  } catch (e) {
    ElMessage.error('导入失败：' + e.message)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.faint { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; }
</style>