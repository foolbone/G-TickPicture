<template>
  <el-dialog :model-value="modelValue" title="导入照片" width="580px"
             @update:model-value="$emit('update:modelValue', $event)">
    <p class="faint">
      将导入到<b>当前所选柜</b>。支持标准采集格式 <code>.../预检/{箱号}/照片.jpg</code>；
      <b>柜号以这里选的柜为准</b>，目录名不影响归属，程序不会自动建柜。
    </p>
    <el-form label-width="80px">
      <el-form-item label="柜">
        <el-select v-model="cid" placeholder="先选柜" style="width:100%" filterable>
          <el-option v-for="c in opts.containers" :key="c.id"
                     :label="c.container_no" :value="c.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="目录">
        <el-input v-model="folder" placeholder="本机照片目录，如 D:/预检图片" />
      </el-form-item>
      <el-form-item label="或上传">
        <input type="file" multiple accept="image/*" @change="onPickFiles" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="busy" @click="run">导入</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
/* ImportPhotosDialog.vue —— 导入照片对话框（照片库页与柜作业③共用一份）
 *
 * 两种导入路径与两段不同的反馈文案都在这里：
 *   目录 → /api/photos/import-auto（能识别标准采集格式，会报「目录名与柜号不符」）
 *   上传 → /api/photos/upload（多文件 FormData）
 * ⚠️ 柜号以对话框里选的柜为准 —— 目录名叫什么不影响归属，程序不会拿目录名当柜号。 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api, post, upload } from '../api.js'
import { opts, loadContainerOptions } from '../lib/photosStore.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  cid: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'done'])

const folder = ref('')
const files = ref([])
const busy = ref(false)
const cid = ref('')

/* 每次打开重置，并把默认柜设成当前柜 */
watch(() => props.modelValue, (on) => {
  if (!on) return
  cid.value = props.cid || ''
  folder.value = ''
  files.value = []
  if (!opts.containers.length) loadContainerOptions()
})

function onPickFiles(e) { files.value = Array.from(e.target.files || []) }

async function run() {
  const c = cid.value
  if (!c) { ElMessage.warning('请先选择柜'); return }
  const f = folder.value.trim()
  if (!f && !files.value.length) { ElMessage.warning('请填目录，或选择要上传的文件'); return }
  busy.value = true
  try {
    if (f) {
      const r = await post('/api/photos/import-auto', { folder: f, container_id: c })
      if (r.mode === 'standard') {
        const where = r.container_no ? '已挂到柜【' + r.container_no + '】' : ''
        const mis = (r.dir_mismatch || []).length
          ? '。注意：照片目录名 ' + r.dir_mismatch.join('、') + ' 与所选柜号不同，柜号以你选的那个为准'
          : ''
        ElMessage.success('标准采集格式：新增 ' + r.added + ' 张，跳过 ' + r.skipped + '。' + where + mis)
      } else if (r.all_duplicate) {
        ElMessage.warning('全部 ' + r.skipped + ' 张照片均已存在，未创建新批次')
      } else {
        ElMessage.success('导入完成：新增 ' + r.added + ' 张，重复跳过 ' + r.skipped)
      }
    } else {
      const fd = new FormData()
      files.value.forEach((x) => fd.append('files', x))
      fd.append('container_id', c)
      const r = await upload('/api/photos/upload', fd)
      ElMessage.success('上传完成：落盘 ' + r.saved + '，新增 ' + r.added + '，重复跳过 ' + r.skipped)
    }
    emit('update:modelValue', false)
    emit('done')
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