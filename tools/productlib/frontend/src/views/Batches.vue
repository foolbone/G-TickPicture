<template>
  <div class="bat-page">
    <el-card shadow="never">
      <template #header>
        <div class="phead">
          <h2>照片批次<span class="sub">一次导入 = 一个批次；治理与检索都以批次为单位</span></h2>
          <span class="spacer"></span>
          <el-select v-model="cid" placeholder="全部柜" clearable style="width:170px"
                     @change="onCid">
            <el-option v-for="c in containers" :key="c.id" :value="c.id"
                       :label="c.container_no" />
          </el-select>
          <el-button size="small" @click="tabRef && tabRef.load()">刷新</el-button>
          <el-button size="small" type="primary" @click="$router.push('/containers')">
            去导入照片 →
          </el-button>
        </div>
      </template>

      <BatchTable ref="tabRef" :container-id="cid" @view="onView" @governed="onGoverned" />
    </el-card>
  </div>
</template>

<script setup>
/* Batches.vue —— 照片批次的**独立路由页**（/app/batches）
 *
 * 表体在 components/BatchTable.vue —— 照片库页的「批次」子视图用同一份，
 * 不复制第二套治理逻辑（2026-10-08 老板信息架构：批次属照片库，不占顶层导航；
 * 这个路由留着是为了可以直接输地址进来 / 收藏）。
 */
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'
import BatchTable from '../components/BatchTable.vue'

const router = useRouter()
const containers = ref([])
const cid = ref('')
const tabRef = ref(null)

function onCid() { if (tabRef.value) tabRef.value.load() }

/* 「查看」= 回照片库照片视图（批次筛选已在组件里设进 photosStore 单例） */
function onView() { router.push('/photos') }
/* 治理启动后跳柜作业③ —— 进度条要留在用户眼前，
   进度藏在看不见的地方，主观上等于卡死。 */
function onGoverned() { router.push('/containers') }

onMounted(async () => {
  try {
    const d = await api('/api/containers')
    containers.value = d.items || []
  } catch { containers.value = [] }
})
</script>

<style scoped>
.bat-page { max-width: 100%; margin: 0 auto; }
.phead { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.phead h2 { margin: 0; font-size: 17px; }
.phead .sub { margin-left: 10px; font-size: 12px; font-weight: normal;
  color: var(--el-text-color-secondary); }
.phead .spacer { flex: 1; }
</style>
