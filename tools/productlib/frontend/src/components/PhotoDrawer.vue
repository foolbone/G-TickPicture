<template>
  <el-drawer :model-value="true" :size="'78%'" direction="rtl"
             :with-header="false" @close="$emit('close')">
    <div v-loading="loading" class="dw">
      <div class="dw-head">
        <span class="faint file">{{ photo.file || '读取中…' }}</span>
        <span class="spacer"></span>
        <!-- 2026-10-21 老板：OCR/大模型/忽略/无效 按钮从右栏挪到顶部导航行 -->
        <template v-if="photo.id">
          <el-tag v-if="photo.is_invalid" type="danger" size="small">已无效</el-tag>
          <el-tag v-if="photo.photo_ignored" type="warning" size="small">已忽略</el-tag>
          <el-button size="small" :loading="regovBusy === 'ocr'" :disabled="regovBusy !== ''"
                     @click="regovern('ocr')"
                     title="按当前分类强制重跑本地 OCR + 编码匹配（不花多模态额度）">OCR 识别</el-button>
          <el-button size="small" :loading="regovBusy === 'full'" :disabled="regovBusy !== ''"
                     @click="regovern('full')"
                     title="按当前分类跑完整识别链路（花多模态额度）">大模型识别</el-button>
          <el-button size="small" :type="photo.photo_ignored ? '' : 'info'" @click="toggleIgnore">
            {{ photo.photo_ignored ? '恢复忽略' : '本次忽略' }}</el-button>
          <el-button size="small" :type="photo.is_invalid ? 'info' : 'warning'" @click="toggleInvalid">
            {{ photo.is_invalid ? '取消无效标记' : '标记为无效' }}</el-button>
        </template>
        <el-button v-if="has" size="small" :disabled="idx <= 0" @click="$emit('step', -1)">← 上一张</el-button>
        <span v-if="has" class="faint">{{ idx + 1 }} / {{ listLen }}</span>
        <el-button v-if="has" size="small" :disabled="idx < 0 || idx >= listLen - 1" @click="$emit('step', 1)">下一张 →</el-button>
        <el-button size="small" @click="$emit('close')">关闭</el-button>
      </div>

      <div v-if="photo.id" class="dw-cols">
        <!-- 左栏：图 + 来源信息（sticky，右栏滚它不动） -->
        <div class="dw-left">
          <div class="dw-imgwrap" @click="openBig">
            <img :src="photo.view || photo.thumb || photo.full" :alt="photo.file" />
            <div class="dw-zoomhint">点击看大图</div>
          </div>
          <div class="dw-src">
            <span class="dw-fname" :title="photo.file">{{ photo.file }}</span>
            <el-tag size="small">{{ containerNo || '未标柜号' }}</el-tag>
            <span v-if="photo.batch && photo.batch.name" class="faint">{{ photo.batch.name }}</span>
            <el-tag v-if="photo.carton_no" size="small" type="success">箱号 {{ photo.carton_no }}</el-tag>
            <span class="faint" :title="'EXIF/文件时间：' + (photo.taken_at || '无')">
              {{ fmtTaken(photo.taken_at, { full: true }) }}
              <template v-if="gapTxt"> · 距上一张 {{ gapTxt }}</template>
              · {{ photo.size_mb }} MB
            </span>
          </div>
          <!-- 同产品编码的其他照片：大图正下方（2026-10-19 需求），
               2026-10-20 老板再要求「小一点、只放最近几个、可展开」——
               历史各批次可能几十张，全铺开会把大图挤出首屏。 -->
          <div v-if="siblings.length" class="dw-sibs">
            <div class="faint sib-h">同编码其他照片 · 最近 {{ sibHead.length }}/{{ siblings.length }} 张</div>
            <div class="dw-sibgrid">
              <div v-for="s in sibHead" :key="s.photo_id" class="dw-sib"
                   :title="s.file" @click="viewOther(s)">
                <el-tag size="small" class="dw-sibkind">{{ kindName(s.photo_kind) }}</el-tag>
                <el-tag v-if="stdSrcIds.has(s.photo_id)" size="small" type="success" class="dw-sibstd"
                        title="这张照片已制作标准图，导出报告时采用">标准图</el-tag>
                <img :src="s.thumb" />
                <div class="gshot-t faint">{{ fmtTaken(s.taken_at) }}</div>
                <div class="dw-sibf faint">{{ s.file }}</div>
              </div>
            </div>
            <el-collapse v-if="sibRest.length" class="dw-sibmore">
              <el-collapse-item :title="'展开更早的 ' + sibRest.length + ' 张'" name="sibrest">
                <div class="dw-sibgrid">
                  <div v-for="s in sibRest" :key="s.photo_id" class="dw-sib"
                       :title="s.file" @click="viewOther(s)">
                    <el-tag size="small" class="dw-sibkind">{{ kindName(s.photo_kind) }}</el-tag>
                    <el-tag v-if="stdSrcIds.has(s.photo_id)" size="small" type="success" class="dw-sibstd"
                            title="这张照片已制作标准图，导出报告时采用">标准图</el-tag>
                    <img :src="s.thumb" />
                    <div class="gshot-t faint">{{ fmtTaken(s.taken_at) }}</div>
                    <div class="dw-sibf faint">{{ s.file }}</div>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>

        <!-- 右栏：先看「这是什么」（分类/用途/处理动作），再给「关联」。
             2026-10-20 老板：关联产品从置顶挪到识别按钮下方。 -->
        <div class="dw-right">
          <!-- ① 分类（模型不一定准，人工可改；改动会触发重识别） -->
          <div class="kv">
            <span class="k">分类</span>
            <el-select :model-value="photo.photo_kind || 'unknown'" size="small" style="width:170px"
                       @change="changeKind">
              <el-option v-for="k in KIND_KEYS" :key="k" :label="KIND_LABELS[k]" :value="k" />
            </el-select>
            <span class="faint">{{ kindConfTxt }}</span>
          </div>

          <!-- ① 用途 + 监装细分（仅监装照有细分） -->
          <div class="kv">
            <span class="k">用途</span>
            <el-select :model-value="photo.photo_usage || ''" size="small" style="width:140px"
                       @change="changeUsage">
              <el-option label="未分类" value="" />
              <el-option v-for="u in USAGES" :key="u" :label="u + '照片'" :value="u" />
            </el-select>
          </div>
          <div v-if="photo.photo_usage === '监装'" class="kv">
            <span class="k">监装细分</span>
            <el-select :model-value="photo.supervision_tag || ''" size="small" style="width:170px"
                       @change="changeSuptag">
              <el-option label="未标注" value="" />
              <el-option v-for="k in SUPTAG_KEYS" :key="k" :label="SUPTAGS[k]" :value="k" />
            </el-select>
            <!-- 模型建议**不自动生效**：有建议才显示，附置信度与「采用建议」 -->
            <template v-if="sugTag">
              <el-tag v-if="sugConfirmed" type="success" size="small">已确认</el-tag>
              <template v-else>
                <el-tag size="small">{{ SUPTAGS[sugTag] }}</el-tag>
                <span class="faint">置信 {{ sugConf }}%<template v-if="sugConf < 60">（偏低，建议核对）</template></span>
                <el-button size="small" text type="primary" @click="acceptAi">采用建议</el-button>
              </template>
            </template>
            <span v-else class="faint">无模型建议</span>
          </div>

          <!-- ② 就地操作按钮已挪到顶部导航行（2026-10-21 老板） -->

          <!-- ②' 关联产品（2026-10-20 老板：从置顶移到识别按钮下方 ——
               先看「这是什么、要不要处理」再给关联。手输 + 已关联 + 建议候选合成一块，
               已关联的照片也有手输入口（旧版只在未关联时给，想加第二个编码没地方输）。 -->
          <div v-if="isProduct || links.length" class="dsec dw-topsec">
            <h4>关联产品<span class="sub">输入编码后回车，可输后几位联想</span></h4>
            <div class="row" style="gap:6px">
              <CodeSuggest v-model="manualCode" placeholder="产品编码" style="flex:1"
                           @pick="(c) => doLink(photo.id, c)" @enter="doLink(photo.id, manualCode)" />
              <el-button size="small" type="primary" @click="doLink(photo.id, manualCode)">关联</el-button>
            </div>
            <div v-for="l in links" :key="l.code_norm" class="linkrow">
              <span class="c">{{ l.code_norm }}</span>
              <span class="muted">{{ l.name }}</span>
              <span class="src">{{ l.source }} · {{ l.created_by }}</span>
              <el-button size="small" text type="danger" @click="unlink(l.code_norm)">解除</el-button>
            </div>
            <div v-if="!links.length" class="faint" style="margin-top:4px">
              尚未关联 —— 用上方输入框，或点下面的建议编码。
            </div>
            <!-- 建议关联：只有「产品图 + 还没关联」才请求（已关联的别再刷候选，
                 那是在诱导重复关联） -->
            <template v-if="isProduct && !links.length">
              <div v-if="candLoading" class="faint" style="margin-top:6px">读取中…</div>
              <div v-else-if="!cands.length" class="faint" style="margin-top:6px">
                没有候选编码 —— 这张照片没读出可匹配的编码，用上方输入框手输。
              </div>
              <div v-for="c in cands" :key="c.code" class="linkrow">
                <el-tag :type="c.fuzzy ? 'warning' : 'primary'" effect="plain" class="cand-chip"
                        @click="doLink(photo.id, c.code)">{{ c.code }}</el-tag>
                <span class="muted">{{ c.name }}</span>
                <span class="faint">{{ c.why }}{{ c.fuzzy ? ' · 模糊需核对' : '' }}</span>
              </div>
            </template>
          </div>
          <div v-else class="dsec">
            <div class="faint">
              只有产品图（有编码 / 无编码）才需要关联产品 —— 上方分类改判为产品图后，这里会出现关联入口。
            </div>
          </div>

          <!-- ②' 同组连拍 · 可能的全景图（懒加载，与有没有关联产品无关） -->
          <div v-if="showPano" class="dsec">
            <h4>同组连拍 · 可能的全景图<span class="sub">同一件货？勾选后可一并关联</span></h4>
            <div v-if="pano.length" class="dw-pano-bar">
              <el-checkbox v-model="panoAll" @change="syncPano">全选</el-checkbox>
              <el-button size="small" :disabled="!panoChecked.length" @click="linkPano">
                {{ panoChecked.length ? '关联选中（' + panoChecked.length + '）到产品' : '关联选中到产品' }}</el-button>
              <CodeSuggest v-model="panoCode" placeholder="产品编码" class="pano-code" />
            </div>
            <div v-if="pano.length" class="dw-pano">
              <div v-for="s in pano" :key="s.photo_id" class="pano-item">
                <el-checkbox v-model="panoSel" :value="s.photo_id" />
                <img :src="s.thumb" :title="s.file + '（点击看大图）'" @click="viewOther(s)" />
                <div class="pano-info">
                  <el-tag v-if="s.source === 'group'" type="success" size="small">同组连拍</el-tag>
                  <el-tag v-else size="small">可能的全景图</el-tag>
                  <span class="faint">{{ kindName(s.photo_kind) }}</span>
                  <el-tag v-if="s.used_by > 0" type="warning" size="small" title="整托盘常装多件货">已用于 {{ s.used_by }} 个产品</el-tag>
                  <div class="pano-sub faint">{{ s.file }} · {{ fmtTaken(s.taken_at) }}</div>
                  <!-- 推荐依据（2026-10-19）：把「凭什么推这张」写在脸上 -->
                  <div v-if="s.reason" class="pano-why">依据：{{ s.reason }}</div>
                </div>
                <el-button size="small" @click="doLink(s.photo_id, s.code || firstCode)">确认为同一产品</el-button>
              </div>
            </div>
            <div v-else class="faint">没有同组连拍或邻近照片。</div>
          </div>

          <!-- 以下低频内容折进「更多」（2026-10-20 老板：初始一屏不滚动） -->
          <el-collapse class="dw-more">
            <el-collapse-item title="更多（标准图 / 文件信息 / 识别细节）" name="more">

          <!-- ③ 标准图：裁剪后入产品库，导出时优先采用 —— 只有产品图才有意义 -->
          <div v-if="isProduct" class="dsec">
            <div class="row" style="gap:8px">
              <el-button size="small" @click="stdEditor = true">制作标准图</el-button>
              <span class="faint">裁剪后入产品库，导出时优先采用</span>
            </div>
            <template v-if="firstCode">
              <div v-if="stdLoading" class="faint" style="margin-top:8px">读取该产品的标准图…</div>
              <div v-else-if="!stdList.length" class="faint" style="margin-top:8px">
                该产品还没有标准图 —— 用「制作标准图」裁剪保存后，即成为当前生效版。
              </div>
              <div v-else style="margin-top:8px">
                <div class="faint" style="margin-bottom:4px">标准图版本（最新为当前生效，导出时采用）：</div>
                <div v-for="s in stdList" :key="s.id" class="stdrow">
                  <img :src="'/std-img/' + s.id" alt="" />
                  <div class="inf">
                    <el-tag v-if="isCurStd(s)" size="small" type="success">当前生效</el-tag>
                    <el-tag v-else size="small">历史</el-tag>
                    <el-tag v-if="s.src_photo_id === String(props.pid)" size="small">本图</el-tag>
                    <span class="faint">{{ s.width || '?' }}×{{ s.height || '?' }}
                      · {{ (s.created_at || '').slice(0, 10) }}</span>
                  </div>
                  <el-button size="small" text type="danger" @click="delStd(s.id)">删除</el-button>
                </div>
              </div>
            </template>
            <div v-else class="faint" style="margin-top:4px">
              这张照片还没关联产品 —— 先关联，保存的标准图才知道挂给谁。
            </div>
          </div>

          <!-- ④ 文件与分类信息（低频） -->
          <div class="kv"><span class="k">文件</span>{{ photo.file }}</div>
          <div class="kv">
            <span class="k">分类</span>
            <el-tag size="small" :type="photo.is_invalid ? 'info' : ''">{{ kindName(photo.photo_kind) }}</el-tag>
            <span v-if="photo.kind_conf" class="faint">置信 {{ Number(photo.kind_conf).toFixed(2) }}</span>
            <span v-if="photo.vision_model" class="faint">· {{ photo.vision_model }}</span>
            <el-tag v-if="photo.govern_state && photo.govern_state !== 'done'" size="small"
                    :type="photo.govern_state === 'failed' ? 'danger' : 'info'">{{ photo.govern_state }}</el-tag>
          </div>

          <!-- ⑤ 识别细节：已在「更多」里，不再自己套一层（嵌套要点两次） -->
          <div class="dsec">
            <h4>识别细节（编码 / OCR / 描述 / 标签提取）</h4>
              <div class="dsec">
                <h4>大模型提取到的编码{{ codes.length ? '' : '（无）' }}</h4>
                <div v-if="codes.length">
                  <el-tag v-for="c in codes" :key="c" size="small"
                          :type="linkedSet.has(c) ? 'success' : ''">{{ c }}{{ linkedSet.has(c) ? ' ✓' : '' }}</el-tag>
                </div>
                <div v-else class="faint">
                  <template v-if="photo.photo_kind === 'packing_list'">
                    这是物料清单（参考文档），上面的编码见下方「OCR 文本」，作为参考<b>不自动关联</b>产品。
                  </template>
                  <template v-else>这张照片没有读到编码。</template>
                </div>
              </div>
              <div class="dsec">
                <h4>OCR 文本（前 8 条，高到低）</h4>
                <div v-if="tokens.length">
                  <el-tag v-for="(t, i) in tokens" :key="i" size="small" class="ocr-chip">
                    {{ t.raw_text }} <span class="faint">{{ Math.round((t.confidence || 0) * 100) }}%</span>
                  </el-tag>
                </div>
                <div v-else class="faint">
                  <template v-if="needOcr && photo.govern_state === 'done'">
                    这张治理过但没有 OCR 文本 —— 早期治理时可能没跑/没跑成。点上方「重新识别」补跑本地 OCR（不花多模态额度）。
                  </template>
                  <template v-else>无 OCR 文本（画面上可能确实没有文字）。</template>
                </div>
              </div>
              <div class="dsec">
                <h4>大模型描述</h4>
                <div v-if="photo.vision_desc" class="muted">{{ photo.vision_desc }}</div>
                <div v-else class="faint">无描述（未治理 / 未配多模态）。</div>
              </div>
              <div v-if="metaEntries.length" class="dsec">
                <h4>标签提取的产品信息</h4>
                <div class="kv meta-grid">
                  <template v-for="[k, label] in metaEntries" :key="k">
                    <span class="k">{{ label }}</span><span>{{ vmeta[k] }}</span>
                  </template>
                </div>
                <el-button v-if="links.length" size="small" @click="applyMeta">应用到产品「{{ firstCode }}」</el-button>
                <div v-else class="faint">这张照片还没关联产品 —— 先关联，再把标签信息填过去。</div>
              </div>
          </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </div>
  </el-drawer>

  <PhotoViewer v-if="bigSrc" :src="bigSrc" :pid="bigPid" :cap="bigCap" :taken-at="bigTaken"
                @close="bigSrc = ''" @detail="onViewerDetail" />

  <StandardEditor v-if="stdEditor" :pid="props.pid" :kind="photo.photo_kind || 'unknown'"
                  :def-code="firstCode" @close="stdEditor = false" @saved="onStdSaved" />
</template>

<script setup>
/* PhotoDrawer.vue —— 照片详情抽屉（对应旧版 drawer.js openDrawer）
 *
 * 布局：左图右信息（左栏 sticky，右栏滚动）。
 * 右栏按**使用频率**排序：分类/用途/监装细分（高频）→ 已关联/建议关联 → 文件信息
 *   → 识别细节（低频，折叠）。
 *
 * 🔴 2026-10-17 老板规则「只有产品需要关联」：只有产品图（label 有编码 /
 *    product 无编码）才出现关联产品相关内容，且与上方「分类」下拉联动 ——
 *    在 Vue 里这是 v-if 的自然结果（旧版要整体重绘才能跟随）。
 *
 * ⚠️ 关联/解除/改判后：清掉本页缓存 → 重新拉详情 → 广播 photos:changed，
 *    让背后的列表、树、徽章重算（数字同源）。不发 wizard:refresh（旧版教训：
 *    它带 advance 语义，会把柜作业③推到④）。 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, post, patch, del } from '../api.js'
import { bus } from '../lib/photosStore.js'
import {
  KIND_LABELS, KIND_KEYS, SUPTAGS, SUPTAG_KEYS, USAGES,
  kindName, fmtTaken, fmtGap, diffSec, jparse,
} from '../lib/core.js'
import PhotoViewer from './PhotoViewer.vue'
import StandardEditor from './StandardEditor.vue'
import CodeSuggest from './CodeSuggest.vue'

const props = defineProps({
  pid: { type: String, required: true },
  list: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'step', 'goto'])

const photo = ref({})
/* 标签提取字段 → 中文名（有序，报告与 UI 都按这个序） */
const META_KEYS = [['name', '品名'], ['spec', '规格'], ['brand', '品牌'],
  ['material', '材质'], ['unit', '单位'], ['category', '类别']]
const loading = ref(false)
const cands = ref([])
const candLoading = ref(false)
const pano = ref([])
const siblings = ref([])
const panoSel = ref([])
const panoAll = ref(false)
const panoCode = ref('')
const manualCode = ref('')
/* 重新识别两档（'ocr' 本地免费 / 'full' 花多模态额度）；'' = 空闲，两按钮互斥 */
const regovBusy = ref('')
const bigSrc = ref('')
const bigPid = ref('')
const bigCap = ref('')
const bigTaken = ref('')
/* 标准图：抽屉内「制作标准图」入口 + 该产品标准图版本列表 */
const stdEditor = ref(false)
const stdList = ref([])
const stdLoading = ref(false)

const idx = computed(() => props.list.indexOf(props.pid))
const has = computed(() => props.list.length > 1)
const listLen = computed(() => props.list.length)

const kind = computed(() => photo.value.photo_kind || 'unknown')
const isProduct = computed(() => kind.value === 'label' || kind.value === 'product')
const links = computed(() => photo.value.links || [])
const firstCode = computed(() => (links.value.length ? links.value[0].code_norm : ''))
const linkedSet = computed(() => new Set(links.value.map((l) => l.code_norm)))
// 同产品编码参考图：按时间倒序，**只铺最近 8 张**，更早的折起来
// （2026-10-20 老板要求；排序在这层做，后端不保证 siblings 的次序）。
const sibSorted = computed(() => siblings.value.slice().sort(
  (a, b) => String(b.taken_at || '').localeCompare(String(a.taken_at || ''))))
const sibHead = computed(() => sibSorted.value.slice(0, 8))
const sibRest = computed(() => sibSorted.value.slice(8))
// 标准图源照片 id 集（2026-10-21 老板反馈修正）：只给**真的被做成标准图的那张
// 源照片**打徽标 —— 产品只有 1 张标准图时，原来按「产品有没有标准图」判断会把
// 同编码所有照片全打上，误导。上传的标准图 src_photo_id 是哨兵值
// （_UPLOADED_），匹配不上任何真实照片，天然被排除。
const stdSrcIds = computed(() => new Set(
  (stdList.value || [])
    .filter((s) => (s.origin || 'crop') === 'crop' && s.src_photo_id)
    .map((s) => s.src_photo_id)))
const codes = computed(() => jparse(photo.value.vision_codes, []))
const tokens = computed(() => (photo.value.tokens || []).filter((t) => (t.raw_text || '').length >= 3))
const vmeta = computed(() => jparse(photo.value.vision_meta, {}))
const metaEntries = computed(() => META_KEYS.filter(([k]) => vmeta.value[k]))
const needOcr = computed(() => ['label', 'packing_list', 'unknown', 'product', 'packaging'].includes(kind.value))
const kindConfTxt = computed(() => photo.value.kind_conf
  ? '模型判定 ' + kindName(kind.value) + ' ' + Math.round(photo.value.kind_conf * 100) + '%（可改）'
  : '人工已确认（或模型未判定）')
const containerNo = computed(() => (photo.value.batch && photo.value.batch.container_no) || photo.value.container_no || '')
const gapTxt = computed(() => {
  const gp = (photo.value.group_photos || []).slice()
    .sort((a, b) => String(a.taken_at || '').localeCompare(String(b.taken_at || '')))
  const i = gp.findIndex((x) => x.id === photo.value.id)
  const prev = i > 0 ? gp[i - 1].taken_at : photo.value.prev_taken_at
  return fmtGap(diffSec(prev, photo.value.taken_at))
})
const sugTag = computed(() =>
  photo.value.sup_tag_ai && SUPTAG_KEYS.includes(photo.value.sup_tag_ai) ? photo.value.sup_tag_ai : null)
const sugConf = computed(() => Math.round((photo.value.sup_tag_ai_conf || 0) * 100))
const sugConfirmed = computed(() => !!photo.value.sup_tag_confirmed)
const showPano = computed(() => links.value.length > 0 || (photo.value.group_photos || []).length > 0)
const panoChecked = computed(() => panoSel.value)

async function load(pid) {
  loading.value = true
  try {
    photo.value = await api('/api/photos/' + pid)
    cands.value = []; candLoading.value = false
    pano.value = []; siblings.value = []; panoSel.value = []; panoAll.value = false
    panoCode.value = firstCode.value
    manualCode.value = ''
    /* 关联已存在 / 有同组照片 → 懒加载同组连拍与全景图（与有没有关联无关） */
    if (showPano.value) loadPano(pid)
    /* 建议关联：仅产品图且尚未关联 —— 不请求就别占往返 */
    if (isProduct.value && !links.value.length) loadCands(pid)
    /* 预取相邻两张（详情 + 图片本身）→ 左右切换秒开 */
    ;[-1, 1].forEach((d) => {
      const nid = props.list[idx.value + d]
      if (nid) new Image().src = `/thumb/${nid}`
    })
  } catch (e) {
    ElMessage.error('打开失败：' + e.message)
  } finally {
    loading.value = false
  }
}

async function loadCands(pid) {
  candLoading.value = true
  try {
    const d = await api('/api/photos/' + pid + '/candidates')
    cands.value = d.items || []
  } catch {
    cands.value = []
  } finally {
    candLoading.value = false
  }
}

async function loadPano(pid) {
  try {
    const d = await api('/api/photos/' + pid + '/panoramas')
    pano.value = d.items || []
    siblings.value = d.siblings || []
  } catch {
    pano.value = []; siblings.value = []
  }
}

watch(() => props.pid, (v) => { if (v) load(v) }, { immediate: true })

/* ── 就地操作 ── */
function changed() { bus.emit('photos:changed') }

async function reloadSelf() {
  await load(props.pid)
  changed()
}

async function toggleInvalid() {
  const to = photo.value.is_invalid ? 0 : 1
  try {
    await post('/api/photos/invalid', { photo_ids: [props.pid], invalid: to })
    ElMessage.success(to ? '已标记为无效' : '已取消无效标记')
    await reloadSelf()
  } catch (e) { ElMessage.error('操作失败：' + e.message) }
}

async function toggleIgnore() {
  const to = photo.value.photo_ignored ? 0 : 1
  try {
    await post('/api/photos/ignore', { photo_ids: [props.pid], ignored: to })
    ElMessage.success(to ? '已忽略：退出关联队列，可在「已忽略」档恢复' : '已恢复：重新进入关联队列')
    await reloadSelf()
  } catch (e) { ElMessage.error('操作失败：' + e.message) }
}

async function regovern(mode) {
  if (regovBusy.value) return                 // 互斥：一个在跑另一个不能点
  regovBusy.value = mode || 'full'
  const label = mode === 'ocr' ? 'OCR 识别' : '大模型识别'
  try {
    const r = await post('/api/photos/' + props.pid + '/regovern', { mode: mode || 'full' })
    const bits = []
    if ((r.codes || []).length) bits.push('读到 ' + r.codes.length + ' 个编码')
    if (r.tokens_n) bits.push('文字 ' + r.tokens_n + ' 条')
    if (r.links_added) bits.push('自动关联 ' + r.links_added + ' 条')
    if (r.hits_n > r.links_added) bits.push((r.hits_n - r.links_added) + ' 条进待确认')
    ElMessage.success(label + '完成' + (bits.length ? '：' + bits.join('，') : ''))
    await reloadSelf()
  } catch (e) {
    ElMessage.error(label + '失败：' + e.message)
  } finally {
    regovBusy.value = ''
  }
}

async function changeKind(k) {
  try {
    await post('/api/photos/kind', { photo_ids: [props.pid], kind: k })
    ElMessage.success('已改判为「' + kindName(k) + '」')
    await reloadSelf()
    /* 改判即重治：分类判错导致编码没识别的图，改一个下拉框就救回来（异步跑） */
    post('/api/photos/' + props.pid + '/regovern', {}).then(async (r) => {
      const bits = []
      if ((r.codes || []).length) bits.push('读到 ' + r.codes.length + ' 个编码')
      if (r.links_added) bits.push('自动关联 ' + r.links_added + ' 条')
      if (r.hits_n > r.links_added) bits.push((r.hits_n - r.links_added) + ' 条进待确认')
      ElMessage.success('已按「' + kindName(r.kind) + '」重新识别' + (bits.length ? '：' + bits.join('，') : ''))
      await reloadSelf()
    }).catch((e) => ElMessage.error('重新识别失败：' + e.message))
  } catch (e) { ElMessage.error('保存失败：' + e.message) }
}

async function changeUsage(u) {
  try {
    await patch('/api/photos/' + props.pid + '/usage', { usage: u })
    ElMessage.success('已保存')
    await reloadSelf()
  } catch (e) { ElMessage.error('保存失败：' + e.message) }
}

async function changeSuptag(t) {
  try {
    await post('/api/photos/supervision-tag', { photo_ids: [props.pid], tag: t })
    ElMessage.success('已保存')
    await reloadSelf()
  } catch (e) { ElMessage.error('保存失败：' + e.message) }
}

async function acceptAi() {
  try {
    await post('/api/photos/supervision-tag/accept-ai', { photo_ids: [props.pid] })
    await reloadSelf()
  } catch (e) { ElMessage.error('采用失败：' + e.message) }
}

async function doLink(pid, code) {
  code = (code || '').trim()
  if (!code) { ElMessage.warning('先选或输入产品编码'); return }
  try {
    await post('/api/links', { photo_id: pid, code, by: 'web' })
    ElMessage.success('已关联 ' + code)
    await reloadSelf()
  } catch (e) { ElMessage.error('关联失败：' + e.message) }
}

async function unlink(code) {
  try {
    await del('/api/links', { code, photo_id: props.pid })
    ElMessage.success('已解除')
    await reloadSelf()
  } catch (e) { ElMessage.error('解除失败：' + e.message) }
}

async function linkPano() {
  const ids = panoSel.value
  if (!ids.length) { ElMessage.warning('先勾选要关联的照片'); return }
  const code = (panoCode.value || firstCode.value || '').trim()
  if (!code) { ElMessage.warning('输入产品编码，或用当前照片已关联的编码'); return }
  try {
    const r = await post('/api/links', {
      photo_ids: ids, code, by: 'web', evidence: '同组连拍/全景批量关联',
    })
    ElMessage.success('已关联 ' + r.linked + ' 张照片到 ' + code)
    await reloadSelf()
  } catch (e) { ElMessage.error('关联失败：' + e.message) }
}

function syncPano(v) { panoSel.value = v ? pano.value.map((s) => s.photo_id) : [] }

async function applyMeta() {
  const code = firstCode.value
  if (!code) { ElMessage.warning('先关联产品'); return }
  try {
    const prod = await api('/api/products/' + encodeURIComponent(code))
    const data = {}
    META_KEYS.forEach(([k]) => { if (vmeta.value[k] && !prod[k]) data[k] = vmeta.value[k] })
    if (!Object.keys(data).length) { ElMessage.warning('产品字段都已有值，无需填充'); return }
    await patch('/api/products/' + encodeURIComponent(code), data)
    const LBL = { name: '品名', spec: '规格', brand: '品牌', material: '材质', unit: '单位', category: '类别' }
    ElMessage.success('已填充：' + Object.keys(data).map((k) => LBL[k] || k).join('、'))
  } catch (e) { ElMessage.error('填充失败：' + e.message) }
}

/* ── 标准图：抽屉内「制作标准图」入口 + 该产品标准图版本列表 ── */
const isCurStd = (s) => stdList.value.length && s.id === stdList.value[stdList.value.length - 1].id

async function loadStd() {
  const cd = firstCode.value
  if (!cd) { stdList.value = []; stdLoading.value = false; return }
  stdLoading.value = true
  try {
    const d = await api('/api/standard-images?code=' + encodeURIComponent(cd))
    stdList.value = d.items || []
  } catch { stdList.value = [] }
  finally { stdLoading.value = false }
}
watch(firstCode, loadStd, { immediate: true })

async function delStd(sid) {
  try {
    await ElMessageBox.confirm('删除这张标准图版本？（只删标准图资产，不动原照片）', '删除标准图',
      { type: 'warning' })
  } catch { return }
  try {
    await del('/api/standard-images/' + sid)
    ElMessage.success('已删除')
    await loadStd()
    changed()
  } catch (e) { ElMessage.error('删除失败：' + e.message) }
}

function onStdSaved() {
  /* 保存后刷新版本列表与照片本身（stdSet 角标 / 版本跟着变） */
  loadStd()
  changed()
}

/* ── 大图 ── */
function openBig() {
  bigPid.value = String(props.pid)
  bigSrc.value = photo.value.full
  bigCap.value = photo.value.file
  bigTaken.value = photo.value.taken_at
}
function viewOther(s) {
  bigPid.value = String(s.photo_id)
  bigSrc.value = s.full || ('/img/' + s.photo_id)
  bigCap.value = s.file
  bigTaken.value = s.taken_at
}
function onViewerDetail(pid) {
  bigSrc.value = ''
  emit('goto', pid)
}

/* Esc 逐层关：大图先关（它在上层），再关抽屉 —— 对应旧版 onEscape prio 50 */
function onKey(e) {
  if (e.key !== 'Escape') return
  if (bigSrc.value) { bigSrc.value = ''; return }
  emit('close')
}
if (typeof window !== 'undefined') window.addEventListener('keydown', onKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

/* ←/→ 在相邻照片间切换（输入框里不抢方向键） */
function onArrow(e) {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  const t = document.activeElement && document.activeElement.tagName
  if (t === 'INPUT' || t === 'TEXTAREA') return
  if (bigSrc.value) return
  e.preventDefault()
  emit('step', e.key === 'ArrowLeft' ? -1 : 1)
}
if (typeof window !== 'undefined') window.addEventListener('keydown', onArrow)
onBeforeUnmount(() => window.removeEventListener('keydown', onArrow))

/* 批量动关联时整包详情作废的等价物：Vue 每次都重取，无需缓存清理。 */
</script>

<style scoped>
.dw { display: flex; flex-direction: column; height: 100%; }
.dw-head { display: flex; align-items: center; gap: 8px; padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-light); }
.dw-head .spacer { flex: 1; }
.dw-head .file { font-size: 13px; }
/* 2026-10-20 老板：初始一屏不滚动 —— 整栏高度受 .dw 约束，左栏图片吃
   「剩下的空间」，而不是固定高度把内容顶出去。 */
.dw-cols { display: flex; gap: 16px; padding-top: 10px; flex: 1; min-height: 0; }
.dw-left { width: 46%; flex: 0 0 46%; display: flex; flex-direction: column; min-height: 0; }
/* 2026-10-20 老板：图片和文件名之间不许有空白。
   原来 wrap 是 flex 容器，img 又带 `max-height: min(56vh, 100%)`——那个 100%
   挂在 auto 高度的 wrap 上（循环依赖，解析不出）。flex 撑 wrap 高度时取的是
   img「未限高」的 hypothetical cross size（498 宽→664 高），而 img 本身被
   max-height 压到 504，两者在底部裂开 160px（CDP 实测 slackInWrap=160，
   gapImgToSrc=168），空白全落在图片下方。
   改成 block 容器 + block img：容器高度直接等于图片高度，空白消失；
   水平居中改用 margin:auto（原来靠 justify-content:center）。 */
.dw-imgwrap { position: relative; cursor: zoom-in; flex: 0 0 auto;
  display: block; line-height: 0; }
.dw-imgwrap img { max-width: 100%; width: auto; height: auto;
  max-height: 70vh; margin: 0 auto;
  object-fit: contain; border-radius: 6px; display: block; }
.dw-zoomhint {
  position: absolute; right: 8px; bottom: 8px; background: rgba(0,0,0,.55);
  color: #fff; font-size: 12px; padding: 2px 8px; border-radius: 10px;
}
.dw-src { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-top: 8px; font-size: 12px; }
/* 文件名：来源信息第一条，加粗突出（2026-10-20 老板） */
.dw-src .dw-fname { font-weight: 600; font-size: 13px;
  color: var(--el-text-color-primary); word-break: break-all; }
.dw-right { flex: 1; min-width: 0; overflow: auto; padding-right: 6px; }
.dw-ops { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.kv { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 13px; flex-wrap: wrap; }
.kv .k { width: 56px; color: var(--el-text-color-secondary); flex: 0 0 56px; }
.kv.meta-grid { display: grid; grid-template-columns: 64px 1fr; gap: 4px 8px; }
.kv.meta-grid .k { width: auto; }
.dsec { margin: 14px 0; }
.dsec h4 { margin: 0 0 6px; font-size: 13px; }
.dsec h4 .sub { margin-left: 8px; font-weight: normal; font-size: 12px;
  color: var(--el-text-color-secondary); }
.linkrow { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 13px; flex-wrap: wrap; }
.linkrow .c { font-weight: 600; }
.linkrow .muted { color: var(--el-text-color-regular); }
.linkrow .src { color: var(--el-text-color-secondary); font-size: 12px; }
.cand-chip { cursor: pointer; }
.dw-pano-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.dw-pano { display: flex; flex-direction: column; gap: 10px; max-height: 480px; overflow: auto; }
.pano-item { display: flex; align-items: center; gap: 12px; padding: 10px;
  border: 1px solid var(--el-border-color-lighter); border-radius: 8px; }
.pano-item img { width: 220px; height: 165px; object-fit: cover; border-radius: 6px;
  border: 1px solid var(--el-border-color-lighter); cursor: zoom-in; flex: 0 0 auto; }
.pano-info { flex: 1; min-width: 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.pano-sub { width: 100%; font-size: 13px; font-weight: 600; color: var(--el-text-color-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 同产品编码参考图：小卡片（84px / 64px 高），最近几张 + 展开更早的 */
.dw-sibs { margin-top: 8px; border-top: 1px solid var(--el-border-color-lighter); padding-top: 6px; }
.dw-sibs .sib-h { font-size: 12px; margin-bottom: 4px; }
.dw-sibgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: 6px; }
.dw-sib { position: relative; cursor: zoom-in; line-height: 1.3; }
.dw-sib img { width: 100%; height: 64px; object-fit: cover; border-radius: 4px; }
.dw-sib .dw-sibkind, .dw-sib .dw-sibstd {
  position: absolute; top: 2px; font-size: 10px; height: 16px; padding: 0 3px;
  line-height: 14px; border: none;
}
.dw-sib .dw-sibkind { left: 2px; }
.dw-sib .dw-sibstd { right: 2px; }
.dw-sib .gshot-t { font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dw-sib .dw-sibf { font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dw-sibmore { margin-top: 6px; border-top: none; }
/* 关联产品区：给浅底色和只读信息区分开（现已不在置顶，位于识别按钮下方） */
.dw-topsec { background: var(--el-color-primary-light-9); border-radius: 6px; padding: 10px 12px; }
.dw-topsec h4 { margin: 0 0 6px; }
.dw-more { margin-top: 10px; }
.gshot-t { font-size: 11px; }
.ocr-chip { margin: 0 4px 4px 0; }
.faint { color: var(--el-text-color-secondary); font-size: 12px; }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pano-code { width: 170px; margin-left: auto; }
.stdrow { display: flex; align-items: center; gap: 10px; padding: 5px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter); }
.stdrow img { width: 64px; height: 48px; object-fit: cover; border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter); flex: none; }
.stdrow .inf { flex: 1; font-size: 12px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

</style>
