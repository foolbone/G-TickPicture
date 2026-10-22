<template>
  <el-drawer :model-value="true" size="70%" direction="rtl" :with-header="false"
             @close="onClose">
    <div v-loading="loading" class="pd">
      <!-- 头：编码 + 名称 + 计数 + 位置 + 翻上下个 + 删除 + 关闭 -->
      <div class="pd-head">
        <div class="pd-title">
          <span class="code">{{ code }}</span>
          <span v-if="prod.name" class="muted">{{ prod.name }}</span>
          <span v-if="prod.spec" class="faint">{{ prod.spec }}</span>
          <el-tag v-if="photos.length" type="success" size="small">{{ photos.length }} 张照片</el-tag>
          <el-tag v-if="stdList.length" type="success" size="small">{{ stdList.length }} 张标准图</el-tag>
          <el-tag v-if="candTotal" type="warning" size="small">{{ candTotal }} 张待确认</el-tag>
        </div>
        <span class="spacer"></span>
        <span v-if="posText" class="faint">{{ posText }}</span>
        <el-button size="small" :disabled="!canPrev" @click="step(-1)">← 上一个</el-button>
        <el-button size="small" :disabled="!canNext" @click="step(1)">下一个 →</el-button>
        <el-button size="small" type="danger" plain @click="doDelete">删除产品</el-button>
        <el-button size="small" @click="onClose">关闭</el-button>
      </div>

      <div v-if="code" class="pd-body">
        <!-- ① 来源信息 -->
        <div v-if="prod.origins" class="block">
          <div class="kv"><span class="k">来源</span>
            <el-tag v-if="prod.origins.source_type === 'from_photo'" type="warning" size="small">照片新发现确认</el-tag>
            <el-tag v-else-if="prod.origins.source_type === 'checklist'" type="success" size="small">清单导入</el-tag>
            <el-tag v-else size="small">来源未知</el-tag>
          </div>
          <div class="kv"><span class="k">关联柜号</span>
            <el-tag v-for="c in originContainers" :key="c" size="small" effect="plain">{{ c }}</el-tag>
            <span v-if="!originContainers.length" class="faint">无</span>
          </div>
          <div class="kv"><span class="k">涉及箱号</span>
            <el-tag v-for="c in cartons" :key="c" size="small" effect="plain">{{ c }}</el-tag>
            <span v-if="!cartons.length" class="faint">无</span>
          </div>
        </div>

        <!-- ② 字段编辑：改完点保存（不丢焦即存），有改动时离开要拦一下 -->
        <div class="block pedit">
          <label v-for="f in FIELDS" :key="f[0]" class="pef">
            {{ f[1] }}
            <el-input :model-value="draft[f[0]] || ''" size="small" placeholder="未填写"
                      @update:model-value="setField(f[0], $event)"
                      @keyup.enter="saveFields" />
          </label>
          <el-button size="small" type="primary" :disabled="!dirty" :loading="saving"
                     @click="saveFields">保存修改</el-button>
          <el-button size="small" :disabled="!dirty" @click="resetFields">还原</el-button>
          <span class="faint">{{ dirty ? '有未保存的修改' : (savedTip || '') }}</span>
        </div>

        <!-- ③ 标准图区：手动上传与库内裁剪并存，上传不要求产品在库里有照片 -->
        <div class="block">
          <div class="bgh">
            <el-tag size="small" type="success">标准图</el-tag>
            <span class="faint">上传照片作为该产品的标准图，可多张；导出标准库与报告取材都优先用它</span>
            <span class="spacer"></span>
            <el-select v-model="stdKind" size="small" style="width:130px">
              <el-option v-for="k in STD_KINDS" :key="k" :label="KIND_LABELS[k]" :value="k" />
            </el-select>
            <el-button size="small" :loading="stdBusy" @click="pickStdFiles">上传标准图</el-button>
            <input ref="stdInput" type="file" accept="image/*" multiple hidden @change="onStdFiles" />
          </div>
          <div class="faint" v-if="!stdList.length">还没有标准图 —— 点右上「上传标准图」，或从库内照片「制作标准图」。</div>
          <div v-else class="std-sum faint">
            <template v-if="stdUpN">{{ stdUpN }} 张手动上传</template>
            <template v-if="stdUpN && stdUpN < stdList.length"> · </template>
            {{ stdList.length - stdUpN }} 张裁剪 · 共 {{ stdList.length }} 张（导出时全部采用）
          </div>
          <div class="pstd-grid">
            <div v-for="s in stdList" :key="s.id" class="pstd-cell">
              <img loading="lazy" :src="s.url || '/std-img/' + s.id" alt="" />
              <div class="c1">
                <el-tag size="small" :type="s.origin === 'upload' ? 'success' : ''">
                  {{ s.origin === 'upload' ? '上传' : '裁剪' }}
                </el-tag>
                <el-tag size="small" :class="kindCls(s.kind)" effect="plain">{{ kindName(s.kind) }}</el-tag>
              </div>
              <div class="faint c2" :title="s.orig_name || ''">
                {{ s.width || '?' }}×{{ s.height || '?' }}
                <template v-if="s.origin === 'upload' && s.orig_name"> · {{ s.orig_name }}</template>
              </div>
              <button class="x" title="删除该标准图" @click="delStd(s.id)">×</button>
            </div>
          </div>
        </div>

        <!-- ④ 已关联照片（按批次分组） -->
        <el-empty v-if="!photoGroups.length" :description="emptyText" :image-size="80">
          <el-button size="small" @click="$router.push('/review')">去新产品确认</el-button>
        </el-empty>
        <div v-for="g in photoGroups" :key="g.key" class="block">
          <div class="bgh">{{ g.name }} <span class="faint">· {{ g.items.length }} 张</span></div>
          <div class="shot-grid">
            <PhotoCard v-for="(p, i) in g.items" :key="p.id" :photo="p" compact
                      :prev-taken="i ? g.items[i - 1].taken_at : ''"
                      @click="viewPhoto(p.id)" />
          </div>
        </div>

        <!-- ⑤ 待确认四块并排（原来上下排列时同组那块被推到很下面，老板看不见） -->
        <div v-if="siblings.length || cands.length || panos.length" class="cand-row">
          <div v-if="siblings.length" class="block cand-col sib">
            <div class="bgh">
              <el-tag size="small" type="warning">同组待确认</el-tag>
              <span class="faint">· {{ siblings.length }} 张同组连拍</span>
              <span class="spacer"></span>
              <el-checkbox :model-value="sibAll" :indeterminate="sibChecked.length > 0 && !sibAll"
                           @change="setSibAll($event)">全选</el-checkbox>
              <el-button size="small" :disabled="!sibChecked.length" @click="linkSibs">关联选中</el-button>
            </div>
            <div v-for="g in sibGroups" :key="g.gid" class="sib-group">
              <div class="faint gid">组 {{ g.gid }} · {{ g.items.length }} 张</div>
              <div v-for="(s, i) in g.items" :key="s.photo_id" class="cand-item">
                <el-checkbox :model-value="sibChecked.includes(String(s.photo_id))"
                             @change="toggleSib(String(s.photo_id), $event)" />
                <img class="cand-thumb" loading="lazy" :src="s.thumb" :title="s.file"
                     @click="viewPhoto(s.photo_id)" />
                <div class="cand-info">
                  <div class="crow">
                    <el-tag size="small" type="warning">同组连拍</el-tag>
                    <span class="faint">{{ s.photo_kind ? kindName(s.photo_kind) : '未分类' }}</span>
                  </div>
                  <div class="faint sub">
                    {{ s.file }} · {{ fmtTaken(s.taken_at) }}
                    <template v-if="i"> · {{ fmtGap(diffSec(g.items[i - 1].taken_at, s.taken_at)) }}</template>
                  </div>
                </div>
                <el-button size="small" text @click="linkOne(s.photo_id)">单张关联</el-button>
                <el-button size="small" text type="warning" @click="reject(s.photo_id)">无关联</el-button>
              </div>
            </div>
          </div>

          <div v-if="cands.length" class="block cand-col">
            <div class="bgh">
              可能关联的图片 <span class="faint">· {{ cands.length }} 张候选</span>
              <span class="spacer"></span>
              <el-checkbox :model-value="candAll" :indeterminate="candChecked.length > 0 && !candAll"
                           @change="setCandAll($event)">全选</el-checkbox>
              <el-button size="small" :disabled="!candChecked.length" @click="linkCands">关联选中</el-button>
            </div>
            <div v-for="c in cands" :key="c.photo_id" class="cand-item">
              <el-checkbox :model-value="candChecked.includes(String(c.photo_id))"
                           @change="toggleCand(String(c.photo_id), $event)" />
              <img class="cand-thumb" loading="lazy" :src="c.thumb" :title="c.file"
                   @click="viewPhoto(c.photo_id)" />
              <div class="cand-info">
                <div class="crow">
                  <el-tag size="small" :type="(c.best_match || {}).mode === 'exact' ? 'success' : 'warning'">
                    {{ (c.best_match || {}).mode === 'exact' ? '精确' : '模糊·核对' }}
                  </el-tag>
                  <el-tag size="small" effect="plain">
                    {{ (c.best_match || {}).src === 'vision' ? '多模态读码' : 'OCR' }}
                  </el-tag>
                  <span class="code">读出「{{ (c.best_match || {}).raw || '' }}」</span>
                  <span class="faint">置信 {{ Math.round(((c.best_match || {}).score || 0) * 100) }}%</span>
                </div>
                <div class="faint sub">{{ c.file }} · {{ fmtTaken(c.taken_at) }}</div>
              </div>
              <el-button size="small" text @click="linkOne(c.photo_id)">单张关联</el-button>
              <el-button size="small" text type="warning" @click="reject(c.photo_id)">无关联</el-button>
            </div>
          </div>

          <div v-if="panos.length" class="block cand-col pano">
            <div class="bgh">
              <el-tag size="small" type="primary">可能的全景图</el-tag>
              <span class="faint">· {{ panos.length }} 张待确认 · 这张产品本体照可能还没拍全</span>
            </div>
            <div class="faint phint">
              系统只能按拍照顺序猜，<b>请对着图确认</b>是这一件货的全景 —— 认错了点「无关联」。
            </div>
            <div v-for="s in panos" :key="s.photo_id" class="cand-item">
              <img class="cand-thumb" loading="lazy" :src="s.thumb" :title="s.file"
                   @click="viewPhoto(s.photo_id)" />
              <div class="cand-info">
                <div class="crow">
                  <el-tag v-if="s.same_group" size="small" type="success">同组连拍</el-tag>
                  <el-tag v-else size="small">
                    {{ s.gap_txt ? '间隔 ' + s.gap_txt : '紧邻拍摄' }}
                  </el-tag>
                  <span class="faint">{{ s.photo_kind ? kindName(s.photo_kind) : '未分类' }}</span>
                  <el-tag v-if="(s.used_by || 0) > 0" size="small" type="warning"
                          title="这张全景可能装着不止一件货（整托盘常常如此）">
                    已用于 {{ s.used_by }} 个产品
                  </el-tag>
                </div>
                <div class="faint sub">{{ s.file }}{{ s.gap_txt ? '' : ' · 顺序在近景旁边' }}</div>
              </div>
              <el-button size="small" text @click="linkOne(s.photo_id)">单张关联</el-button>
              <el-button size="small" text type="warning" @click="reject(s.photo_id)">无关联</el-button>
            </div>
          </div>
        </div>

        <!-- ⑥ 已标记无关联：默认折叠但入口一直在 —— 标记可撤销，藏起来等于找不回 -->
        <div v-if="rejs.length" class="block">
          <div class="bgh clickable" @click="rejOpen = !rejOpen">
            <el-tag size="small">已标记无关联</el-tag>
            <span class="faint">· {{ rejs.length }} 张不再出现在待确认里</span>
            <span class="spacer"></span>
            <span class="faint">{{ rejOpen ? '收起' : '展开' }}</span>
          </div>
          <div v-show="rejOpen">
            <div v-for="r in rejs" :key="r.photo_id" class="cand-item">
              <img class="cand-thumb" loading="lazy" :src="r.thumb" :title="r.file"
                   @click="viewPhoto(r.photo_id)" />
              <div class="cand-info">
                <div class="crow">
                  <el-tag size="small">无关联</el-tag>
                  <span class="faint">{{ r.reason || '' }}</span>
                </div>
                <div class="faint sub">{{ r.created_at || '' }}</div>
              </div>
              <el-button size="small" text @click="unreject(r.photo_id)">撤销</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <PhotoViewer v-if="viewerSrc" :src="viewerSrc" :pid="viewerPid" :cap="viewerCap"
                 :taken-at="viewerTaken" @close="viewerSrc = ''" @detail="openDrawer" />
  </el-drawer>
</template>

<script setup>
/* ProductDrawer.vue —— 产品详情抽屉（对应旧版 products.js openProduct）
 *
 * 布局沿用旧版结论：列表全宽，详情从右侧滑出盖上来 —— 关掉回到列表原位，
 * 翻页 / 搜索 / 滚动位置一个不丢。左右分栏与上下堆叠都试过，都不好用。
 *
 * 🔴 四块待确认（同组 / 读码候选 / 全景图 / 已标记无关联）**并排**：
 *    旧版上下排列时第二块被推到很下面，老板看不见，等于没做。
 *
 * 🔴 字段编辑「改完点保存」而不是失焦即存：改错了没法撤、也不知道存没存。
 *    有未保存改动时关抽屉 / 翻上下个都要先问 —— 无声丢改动比多问一句难受得多。
 *
 * ⚠️ 四路数据并行拉（照片 / 产品 / 候选 / 已标记否决），互不依赖；
 *    候选与否决任何一个失败都不能挡住抽屉打开（旧版用 catch(()=空数组) 兜的）。
 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, post, patch, del, upload } from '../api.js'
/* 翻上下个的**判定与翻页**在父视图（Products.vue）做：它持有列表与页码，
   这里只负责「有没有未保存改动」这一个问题 —— 拦下来就不 emit。 */
import { posText, canPrev, canNext, load, changed } from '../lib/productsStore.js'
import { KIND_LABELS, kindName, kindCls, fmtTaken, fmtGap, diffSec } from '../lib/core.js'
import PhotoCard from './PhotoCard.vue'
import PhotoViewer from './PhotoViewer.vue'

const props = defineProps({ code: { type: String, required: true } })
const emit = defineEmits(['close', 'step'])

const FIELDS = [['name', '品名'], ['spec', '规格'], ['material', '材质']]
const STD_KINDS = ['label', 'product', 'packaging', 'unknown']

const loading = ref(false)
const prod = ref({})
const photos = ref([])
const batches = ref([])
const cands = ref([])
const siblings = ref([])
const panos = ref([])
const rejs = ref([])
const stdList = ref([])
const draft = ref({})
const dirty = ref(false)
const saving = ref(false)
const savedTip = ref('')
const stdKind = ref('product')
const stdBusy = ref(false)
const stdInput = ref(null)
const rejOpen = ref(false)
const sibChecked = ref([])
const candChecked = ref([])
const viewerSrc = ref('')
const viewerPid = ref('')
const viewerCap = ref('')
const viewerTaken = ref('')
const gone = ref(false)          // 产品被删 → 关闭不再问未保存改动

const sibAll = computed(() => siblings.value.length > 0
  && sibChecked.value.length === siblings.value.length)
const candAll = computed(() => cands.value.length > 0
  && candChecked.value.length === cands.value.length)
const stdUpN = computed(() => stdList.value.filter((s) => s.origin === 'upload').length)
// 标题「N 张标准图」用 stdList.length（裁剪+上传总数）。不要再按
// src_photo_id 聚集合数 —— 上传的 src_photo_id 是哨兵值 _UPLOADED_，
// 且一个源照片可存多个版本，集合大小既不是张数也会虚高（2026-10-21）。
const candTotal = computed(() => cands.value.length + siblings.value.length + panos.value.length)
const originContainers = computed(() => {
  const cs = (prod.value.origins && prod.value.origins.containers) || []
  return cs.map((c) => c.container_no || c.name || c.id)
})
const cartons = computed(() =>
  [...new Set(photos.value.map((p) => p.carton_no).filter(Boolean))])
const photoGroups = computed(() => {
  const m = {}
  photos.value.forEach((p) => {
    const k = p.batch_id || '_none'
    ;(m[k] = m[k] || []).push(p)
  })
  return Object.keys(m).map((k) => {
    const b = (batches.value || []).find((x) => x.id === k)
    return {
      key: k,
      name: b ? (b.name || b.id) : (k === '_none' ? '未归属批次' : (k || '')),
      items: m[k],
    }
  })
})
const sibGroups = computed(() => {
  const m = {}
  siblings.value.forEach((s) => {
    const k = s.group_idx == null ? '' : String(s.group_idx)
    ;(m[k] = m[k] || []).push(s)
  })
  return Object.keys(m).map((gid) => ({ gid, items: m[gid] }))
})
const emptyText = computed(() => (candTotal.value
  ? '已关联 0 张照片，上方有候选照片待确认'
  : '这个产品还没有关联到任何照片 —— 在人工标注确认里认领，或确认清单编码与照片上的是否一致'))

async function loadOne(code) {
  loading.value = true
  gone.value = false
  savedTip.value = ''
  sibChecked.value = []
  candChecked.value = []
  rejOpen.value = false
  const one = (p) => api(p).catch(() => null)
  const [ph, pr, cd, rj] = await Promise.all([
    one('/api/products/' + encodeURIComponent(code) + '/photos'),
    one('/api/products/' + encodeURIComponent(code)),
    one('/api/products/' + encodeURIComponent(code) + '/candidates'),
    /* 已标记无关联的入口必须一直在：标记可撤销，藏起来等于点错一次就找不回 */
    one('/api/products/' + encodeURIComponent(code) + '/candidates/rejected'),
  ])
  photos.value = (ph && ph.items) || []
  batches.value = (ph && ph.batches) || []
  prod.value = pr || {}
  draft.value = { name: pr.name || '', spec: pr.spec || '', material: pr.material || '' }
  dirty.value = false
  const c = cd || {}
  cands.value = c.items || []
  siblings.value = c.group_siblings || []
  panos.value = c.panoramas || []
  rejs.value = (rj && rj.items) || []
  loading.value = false
  await loadStd(code)
}

async function loadStd(code) {
  try {
    const d = await api('/api/standard-images?code=' + encodeURIComponent(code))
    stdList.value = d.items || []
  } catch {
    stdList.value = []
  }
}

watch(() => props.code, (v) => { if (v) loadOne(v) }, { immediate: true })

/* ── 字段编辑 ── */
function setField(k, v) { draft.value = Object.assign({}, draft.value, { [k]: v }); dirty.value = true }
function resetFields() {
  draft.value = { name: prod.value.name || '', spec: prod.value.spec || '', material: prod.value.material || '' }
  dirty.value = false
  savedTip.value = ''
}
async function saveFields() {
  if (!dirty.value || saving.value) return
  const payload = {}
  FIELDS.forEach(([k]) => {
    const v = (draft.value[k] || '').trim()
    if (v !== (prod.value[k] || '')) payload[k] = v
  })
  if (!Object.keys(payload).length) { dirty.value = false; return }
  saving.value = true
  try {
    await patch('/api/products/' + encodeURIComponent(props.code), payload)
    Object.assign(prod.value, payload)
    Object.assign(draft.value, payload)
    dirty.value = false
    savedTip.value = '已保存'
    changed()
    await load(false)          // 列表里的品名/规格同步（不重置页码）
  } catch (e) {
    ElMessage.error('保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}

/** 未保存改动时离开要拦一下 —— 无声丢改动比多问一句难受得多。 */
async function confirmLeave() {
  if (!dirty.value || gone.value) return true
  try {
    await ElMessageBox.confirm('有未保存的字段修改。\n\n离开将丢失这些修改，确定吗？', '未保存的修改',
      { type: 'warning', confirmButtonText: '确定离开', cancelButtonText: '继续编辑' })
    return true
  } catch { return false }
}

async function onClose() {
  if (!(await confirmLeave())) return
  emit('close')
}
async function step(d) {
  if (!(await confirmLeave())) return
  emit('step', d)
}

/* ── 标准图上传 / 删除 ── */
function pickStdFiles() { if (stdInput.value) stdInput.value.click() }
async function onStdFiles(e) {
  const files = Array.from(e.target.files || [])
  if (!files.length) return
  stdBusy.value = true
  const fd = new FormData()
  fd.append('code', props.code)
  fd.append('kind', stdKind.value)
  files.forEach((f) => fd.append('files', f))
  try {
    const r = await upload('/api/standard-images/upload', fd)
    /* 部分成功必须如实说，不能只报成功（铁律：缺口不许渲染成结论态） */
    if (r.failed) {
      ElMessage.warning('成功 ' + r.uploaded + ' 张，失败 ' + r.failed + ' 张（'
        + (r.errors || []).slice(0, 2).map((x) => x.filename + ': ' + x.error).join('；') + '）')
    } else {
      ElMessage.success('已上传 ' + r.uploaded + ' 张标准图')
    }
    await loadStd(props.code)
    changed()
  } catch (ex) {
    ElMessage.error('上传失败：' + ex.message)
  } finally {
    if (stdInput.value) stdInput.value.value = ''   // 清空以便重传同名文件
    stdBusy.value = false
  }
}
async function delStd(sid) {
  try {
    await ElMessageBox.confirm(
      '删除这张标准图？（只删标准图资产，不动原照片；库里没照片的上传图删了就没了）',
      '删除标准图', { type: 'warning' })
  } catch { return }
  try {
    await del('/api/standard-images/' + sid)
    ElMessage.success('已删除标准图')
    await loadStd(props.code)
    changed()
  } catch (e) { ElMessage.error('删除失败：' + e.message) }
}

/* ── 关联 / 标记无关联 ── */
async function linkOne(pid) {
  try {
    await post('/api/links', { photo_id: pid, code: props.code, by: 'web' })
    ElMessage.success('已关联')
    await loadOne(props.code)
    changed()
  } catch (e) { ElMessage.error('关联失败：' + e.message) }
}
async function linkSibs() {
  await linkMany(sibChecked.value, '已批量关联 ', ' 张同组照片')
}
async function linkCands() {
  await linkMany(candChecked.value, '已批量关联 ', ' 张')
}
async function linkMany(ids, okTxt) {
  if (!ids.length) { ElMessage.warning('先勾选'); return }
  try {
    await post('/api/links', { photo_ids: ids, code: props.code, by: 'web' })
    ElMessage.success(okTxt + ids.length)
    await loadOne(props.code)
    changed()
  } catch (e) { ElMessage.error('批量关联失败：' + e.message) }
}
function toggleSib(pid, v) {
  sibChecked.value = v ? [...new Set([...sibChecked.value, pid])] : sibChecked.value.filter((x) => x !== pid)
}
function setSibAll(v) { sibChecked.value = v ? siblings.value.map((s) => String(s.photo_id)) : [] }
function toggleCand(pid, v) {
  candChecked.value = v ? [...new Set([...candChecked.value, pid])] : candChecked.value.filter((x) => x !== pid)
}
function setCandAll(v) { candChecked.value = v ? cands.value.map((s) => String(s.photo_id)) : [] }

/* ⚠️ 必须有确认框：这动作藏起来后找不回（虽可撤销，老板不会想到去展开折叠区），
   误点一次的代价远大于点一下确认。 */
async function reject(pid) {
  try {
    await ElMessageBox.confirm(
      '标记为「无关联」？\n\n之后这张照片不再出现在本产品的待确认列表里。'
      + '只影响本产品 —— 它若是别的产品的候选，仍然照常出现。'
      + '（标记可撤销，在下方「已标记无关联」里能还原）', '标记无关联',
      { type: 'warning' })
  } catch { return }
  try {
    const r = await post('/api/products/' + encodeURIComponent(props.code) + '/candidates/reject',
      { photo_ids: [pid], reason: '人工查看后确认无关联', by: 'web' })
    ElMessage.success(r.marked ? '已标记为无关联' : '这张之前已标记过')
    await loadOne(props.code)
    changed()
  } catch (e) { ElMessage.error('标记失败：' + e.message) }
}
async function unreject(pid) {
  try {
    const r = await post('/api/products/' + encodeURIComponent(props.code) + '/candidates/unreject',
      { photo_ids: [pid], by: 'web' })
    ElMessage.success(r.unmarked ? '已撤销，照片回到待确认' : '这张本来就没有标记')
    await loadOne(props.code)
    changed()
  } catch (e) { ElMessage.error('撤销失败：' + e.message) }
}

/* ── 删除产品 ── */
async function doDelete() {
  try {
    await ElMessageBox.confirm('确定删除产品「' + props.code + '」？\n\n'
      + '将同时删除：关联记录、标准图文件、批次关联。\n原照片不会被删除。', '删除产品',
      { type: 'warning' })
  } catch { return }
  try {
    await del('/api/products/' + encodeURIComponent(props.code))
    ElMessage.success('已删除：' + props.code)
    gone.value = true                 // 产品没了，抽屉直接关（不用问未保存改动）
    changed()
    await load(true)
    emit('close')
  } catch (e) { ElMessage.error('删除失败：' + e.message) }
}

/* ── 看照片：候选缩略图点开走同一个 PhotoViewer ── */
function viewPhoto(pid) {
  viewerPid.value = String(pid)
  viewerSrc.value = '/img/' + pid
}
function openDrawer(pid) { viewerSrc.value = '' }

/* Esc：先关大图，再关抽屉 */
function onKey(e) {
  if (e.key !== 'Escape') return
  if (viewerSrc.value) { viewerSrc.value = ''; return }
  onClose()
}
/* ↑← / ↓→ 翻上下个（输入框里不抢方向键） */
function onArrow(e) {
  if (!['ArrowUp', 'ArrowLeft', 'ArrowDown', 'ArrowRight'].includes(e.key)) return
  const t = document.activeElement && document.activeElement.tagName
  if (t === 'INPUT' || t === 'TEXTAREA') return
  if (viewerSrc.value) return
  e.preventDefault()
  step(e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 1)
}
if (typeof window !== 'undefined') window.addEventListener('keydown', onKey)
if (typeof window !== 'undefined') window.addEventListener('keydown', onArrow)
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('keydown', onArrow)
})

/* 预取左右产品的编码（让翻页不空等） */
watch(() => props.code, () => { dirty.value = false }, { immediate: true })
</script>

<style scoped>
.pd { display: flex; flex-direction: column; height: 100%; }
.pd-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding-bottom: 8px; border-bottom: 1px solid var(--el-border-color-light); }
.pd-head .spacer { flex: 1; }
.pd-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pd-title .code { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 600; }
.pd-body { flex: 1; overflow: auto; padding: 10px 4px 40px; }
.block { border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  padding: 8px 10px; margin-bottom: 10px; }
.block.sib { border-color: var(--el-color-warning-light-5); }
.block.pano { border-color: var(--el-color-primary-light-5); }
.bgh { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; font-size: 13px; }
.bgh .spacer { flex: 1; }
.bgh.clickable { cursor: pointer; }
.kv { display: flex; align-items: center; gap: 6px; margin: 4px 0; font-size: 13px; flex-wrap: wrap; }
.kv .k { width: 62px; flex: 0 0 62px; color: var(--el-text-color-secondary); }
.pedit { display: flex; align-items: flex-end; gap: 8px; flex-wrap: wrap; }
.pef { display: flex; flex-direction: column; gap: 2px; font-size: 12px;
  color: var(--el-text-color-secondary); width: 170px; }
.shot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 8px; }
.pstd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 8px; }
.pstd-cell { position: relative; border: 1px solid var(--el-border-color-lighter); border-radius: 4px; padding: 4px; }
.pstd-cell img { width: 100%; height: 80px; object-fit: cover; border-radius: 3px; display: block; }
.pstd-cell .c1 { display: flex; gap: 4px; margin-top: 3px; flex-wrap: wrap; }
.pstd-cell .c2 { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pstd-cell .x { position: absolute; right: 2px; top: 2px; border: none; cursor: pointer;
  background: rgba(0, 0, 0, .5); color: #fff; border-radius: 9px; width: 18px; height: 18px;
  line-height: 1; padding: 0; }
.std-sum { font-size: 12px; margin-bottom: 4px; }
.cand-row { display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.cand-col { flex: 1 1 300px; min-width: 280px; max-height: 420px; overflow: auto; }
.cand-item { display: flex; align-items: center; gap: 6px; padding: 4px 0; }
.cand-thumb { width: 46px; height: 46px; object-fit: cover; border-radius: 4px; cursor: zoom-in; flex: 0 0 46px; }
.cand-info { flex: 1; min-width: 0; }
.cand-info .crow { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.cand-info .crow .code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
.cand-info .sub { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sib-group { margin-top: 6px; }
.sib-group .gid { font-size: 12px; }
.phint { font-size: 12px; margin: 4px 0 6px; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
.muted { color: var(--el-text-color-regular); }
</style>