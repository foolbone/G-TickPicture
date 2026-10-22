<template>
  <div class="set-page">
    <!-- ① 多模态大模型 -->
    <el-card shadow="never">
      <template #header>
        <div class="phead">
          <h3>多模态大模型<span class="sub">选配 —— 没配也能用，只是分类退化为启发式</span></h3>
        </div>
      </template>
      <div class="row">
        <el-input v-model="vBase" placeholder="API Base，如 https://api.openai.com/v1" />
        <el-input v-model="vModel" placeholder="模型名，如 gpt-4o-mini" style="width:260px" />
      </div>
      <div class="row" style="margin-top:8px">
        <el-input v-model="vKey" type="password" placeholder="API Key" show-password />
        <el-button type="primary" :loading="saving" @click="saveVision">保存</el-button>
        <el-button :loading="testing" @click="testVision">拿一张照片试调</el-button>
      </div>
      <div class="faint" style="margin-top:8px">{{ vMsg }}</div>
      <div class="faint warn">
        ⚠ 本机没有视觉模型 API key，这条调用路径<b>未经真实 API 验证</b>。配好 key 后请先点「试调」。
      </div>
    </el-card>

    <!-- ② 标准库自动落盘 -->
    <el-card shadow="never">
      <template #header>
        <div class="phead">
          <h3>标准库自动落盘<span class="sub">系统自动完成，无需手动操作</span></h3>
        </div>
      </template>
      <div class="row">
        <el-input v-model="stdExpDir" placeholder="落盘目录" @change="saveDir" />
        <el-button @click="dirOpen = true">选择目录</el-button>
        <el-button type="primary" :loading="exporting" @click="exportStd">立即落盘</el-button>
      </div>
      <div class="faint" style="margin-top:8px">
        <template v-if="stdMsg">
          已落盘 <b>{{ stdMsg.products }}</b> 个产品 / <b>{{ stdMsg.photos }}</b> 张照片 →
          <b>{{ stdMsg.dir }}</b>
          <template v-if="stdMsg.missing">（{{ stdMsg.missing }} 张源文件缺失已跳过）</template>
        </template>
      </div>
      <div class="faint" style="margin-top:4px">
        每次治理完成后系统自动将已确认产品的照片复制到上方目录，命名：
        {产品编码}_{标识卡|产品|包装}[_n].jpg，附 standard_index.csv 对照表。做过标准图的产品导出标准图。
      </div>
    </el-card>

    <!-- ③ 产品数据规范 -->
    <el-card shadow="never">
      <template #header><div class="phead"><h3>产品数据规范<span class="sub">直接读自 schema</span></h3></div></template>
      <el-table :data="fields" size="small">
        <el-table-column label="字段" width="130">
          <template #default="{ row }"><span class="code">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column label="中文名" width="100" prop="label" />
        <el-table-column label="必填" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.required" size="small" type="danger">必填</el-tag>
            <span v-else class="faint">选填</span>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="200" prop="desc" />
      </el-table>
    </el-card>

    <!-- ④ 照片分类字典 -->
    <el-card shadow="never">
      <template #header><div class="phead"><h3>照片分类字典</h3></div></template>
      <el-table :data="kindRows" size="small">
        <el-table-column label="分类" width="170">
          <template #default="{ row }"><span class="code">{{ row.k }}</span></template>
        </el-table-column>
        <el-table-column label="含义" prop="label" />
      </el-table>
    </el-card>

    <!-- ⑤ 已跳过的照片（撤销入口） -->
    <el-card shadow="never">
      <template #header>
        <div class="phead">
          <h3>已跳过的照片
            <span class="sub">人工标注时点了「跳过」的 —— 可撤销，撤销后回到待认领队列</span>
          </h3>
          <span class="spacer"></span>
          <span class="faint">{{ skTotal ? '共 ' + skTotal + ' 张' : '' }}</span>
          <el-button size="small" @click="loadSkipped">刷新</el-button>
        </div>
      </template>
      <el-table :data="skipped" size="small">
        <el-table-column label="文件" min-width="240" prop="file" />
        <el-table-column label="跳过时间" width="160">
          <template #default="{ row }">
            <span class="faint">{{ (row.skip_at || '').replace('T', ' ').slice(0, 16) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button size="small" text @click="unskip(row)">撤销跳过</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!loadingSk && !skipped.length" class="faint none">
        🚫 还没有跳过任何照片 —— 在照片详情里点「跳过」，决定会被记住
      </div>
    </el-card>

    <DirPicker :model-value="dirOpen" @update:model-value="dirOpen = $event"
               @pick="onDirPicked" />
  </div>
</template>

<script setup>
/* Settings.vue —— 设置页（对应旧版 settings.js + review.js 的跳过撤销 + #tab-set）
 *
 * 五块：多模态配置 / 标准库落盘 / 产品数据规范 / 分类字典 / 已跳过照片撤销。
 * 「已跳过照片」在旧版是 review.js 管的（历史上多模态确认页撤掉后挪到设置），
 * 这里是它唯一的撤销入口 —— 跳过的照片不会自己回来。
 */
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api, post } from '../api.js'
import DirPicker from '../components/DirPicker.vue'

/* 标准库落盘目录记在 localStorage（是本机偏好，不是业务数据） */
const STD_EXP_DEFAULT = 'D:\\G-TickPicture\\标准产品库'
const dirOpen = ref(false)
const loadDir = () => {
  try { return localStorage.getItem('stdExpDir') || STD_EXP_DEFAULT } catch { return STD_EXP_DEFAULT }
}
const stdExpDir = ref(loadDir())
const saveDir = () => {
  try { localStorage.setItem('stdExpDir', stdExpDir.value) } catch { /* 隐私模式 */ }
}
const onDirPicked = (p) => { stdExpDir.value = p; saveDir() }

const stdMsg = ref(null)
const exporting = ref(false)

const vBase = ref('')
const vModel = ref('')
const vKey = ref('')
const vMsg = ref('')
const saving = ref(false)
const testing = ref(false)

const fields = ref([])
const kindRows = ref([])
const skipped = ref([])
const skTotal = ref(0)
const loadingSk = ref(false)

const kindDict = ref({})

async function loadFields() {
  try {
    const d = await api('/api/fields')
    fields.value = d.fields || []
    kindDict.value = d.kinds || {}
    kindRows.value = Object.keys(kindDict.value).map((k) => ({ k, label: kindDict.value[k] }))
  } catch { fields.value = []; kindRows.value = [] }
}

async function loadVision() {
  try {
    const v = await api('/api/vision/config')
    vBase.value = v.api_base
    vModel.value = v.model
    vMsg.value = v.enabled
      ? '已配置' + (v.has_key ? '（key 已保存）' : '')
      : '未配置 —— 治理会降级运行'
  } catch { /* 读不到就留空，不挡页面 */ }
}

async function saveVision() {
  saving.value = true
  try {
    const r = await post('/api/vision/config', {
      api_base: vBase.value.trim(), api_key: vKey.value.trim(), model: vModel.value.trim(),
    })
    ElMessage.success('已保存')
    vMsg.value = r.enabled ? '已配置，多模态已启用' : '未配置 —— 治理会降级运行'
    vKey.value = ''                      // key 不留在明文输入框里
  } catch { /* api() 已弹错 */ } finally { saving.value = false }
}

async function testVision() {
  testing.value = true
  ElMessage.info('调用中…')
  try {
    const r = await post('/api/vision/test', {})
    ElMessage.success('调用成功（' + r.seconds + 's）：' + JSON.stringify(r.classify))
  } catch (e) {
    ElMessage.error('调用失败：' + e.message)
  } finally { testing.value = false }
}

async function exportStd() {
  const dir = stdExpDir.value.trim()
  if (!dir) { ElMessage.warning('先填落盘目录'); return }
  saveDir()
  exporting.value = true
  try {
    const r = await post('/api/export/standard', { dir })
    stdMsg.value = r
    ElMessage.success('落盘完成：' + r.photos + ' 张照片')
  } catch (e) {
    ElMessage.error('落盘失败：' + e.message)
  } finally { exporting.value = false }
}

async function loadSkipped() {
  loadingSk.value = true
  try {
    const d = await api('/api/photos/skipped?limit=200')
    skipped.value = d.items || []
    skTotal.value = d.total || 0
  } catch { skipped.value = [] } finally { loadingSk.value = false }
}

async function unskip(p) {
  try {
    await post('/api/photos/skip', { photo_id: p.id, skip: false })
    ElMessage.success('已撤销 —— 照片回到待认领队列')
    await loadSkipped()
  } catch { /* api() 已弹错 */ }
}

onMounted(async () => {
  await loadFields()
  await loadVision()
  await loadSkipped()
})
</script>

<style scoped>
.set-page { max-width: 1400px; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.phead h3 { margin: 0; font-size: 15px; }
.phead .sub { margin-left: 10px; font-size: 12px; font-weight: normal;
  color: var(--el-text-color-secondary); }
.phead .spacer { flex: 1; }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.code { font-family: ui-monospace, Menlo, Consolas, monospace; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
.faint.warn { margin-top: 6px; }
.none { padding: 20px; text-align: center; }
</style>