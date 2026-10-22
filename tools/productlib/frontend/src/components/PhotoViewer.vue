<template>
  <div v-if="src" class="viewer" @click.self="close">
    <div class="viewer-bar">
      <span class="faint">{{ cap }}</span>
      <span class="spacer"></span>
      <el-button-group size="small">
        <el-button @click="rot(-90)"><el-icon><RefreshLeft /></el-icon></el-button>
        <el-button @click="rot(90)"><el-icon><RefreshRight /></el-icon></el-button>
        <el-button @click="zoom(-1)"><el-icon><ZoomOut /></el-icon></el-button>
        <el-button @click="zoom(1)"><el-icon><ZoomIn /></el-icon></el-button>
        <el-button @click="reset">1:1</el-button>
      </el-button-group>
      <span class="faint info">{{ angle }}° · {{ Math.round(scale * 100) }}%</span>
      <el-button v-if="pid" size="small" type="primary" @click="toDetail">打开详情</el-button>
      <el-button size="small" @click="close">关闭</el-button>
    </div>
    <div class="viewer-stage"
         @wheel.prevent="onWheel"
         @pointerdown="onDown" @pointermove="onMove"
         @pointerup="onUp" @pointercancel="onUp">
      <img :src="displaySrc" alt="" :style="imgStyle" :class="{ dragging }" />
    </div>
  </div>
</template>

<script setup>
/* PhotoViewer.vue —— 大图查看器：缩放 / 旋转 / 拖动平移
 *
 * 🔴 transform 顺序必须是 translate → rotate → scale：translate 写在最前面
 * 位移量才是**屏幕像素**（拖几像素走几像素）；写在 scale 之后会被缩放倍数放大，
 * 拖一下就飞出屏幕。
 * ⚠️ 钳制位移时 offsetWidth 在图片尚未完成布局时是 0 —— 那时会把两个方向都钳成 0，
 * 表现为「放大了却拖不动」。回退：用 getBoundingClientRect（rect 含 transform，
 * 除以 scale）反推未缩放尺寸；再兜底按窗口比例给个宽裕量（宁可多拖一点）。
 *
 * 加载策略：原图 4MB 冷加载好几秒 —— 先用已缓存的预览图顶上，原图到位再换。 */
import { ref, computed, watch } from 'vue'
import { fmtTaken } from '../lib/core.js'

const props = defineProps({
  src: { type: String, default: '' },
  pid: { type: String, default: '' },
  cap: { type: String, default: '' },
  takenAt: { type: String, default: '' },
})
const emit = defineEmits(['close', 'detail'])

const SCALES = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4]
const angle = ref(0)
const scale = ref(1)
const tx = ref(0)
const ty = ref(0)
const dragging = ref(false)
const rawSrc = ref('')
let sx = 0, sy = 0, ox = 0, oy = 0

const displaySrc = ref('')
const cap = computed(() =>
  props.takenAt ? (props.cap ? props.cap + ' · ' : '') + fmtTaken(props.takenAt, { full: true }) : props.cap)

const imgStyle = computed(() => ({
  transform: `translate(${tx.value}px,${ty.value}px) rotate(${angle.value}deg) scale(${scale.value})`,
}))

watch(() => props.src, (s) => {
  if (!s) { displaySrc.value = ''; rawSrc.value = ''; return }
  const m = String(s).match(/\/img\/([^/?]+)/)
  if (m) {
    displaySrc.value = '/img/' + m[1] + '?w=1600'
    const big = new Image()
    big.onload = () => { if (displaySrc.value !== s) displaySrc.value = s }
    big.src = s
  } else {
    displaySrc.value = s
  }
  rawSrc.value = s
  reset()
}, { immediate: true })

function reset() { angle.value = 0; scale.value = 1; tx.value = 0; ty.value = 0 }
function rot(d) { angle.value = (angle.value + d + 360) % 360; clamp() }
function zoom(d) {
  let i = SCALES.indexOf(scale.value)
  if (i < 0) i = SCALES.indexOf(1)
  i = Math.max(0, Math.min(SCALES.length - 1, i + d))
  scale.value = SCALES[i]
  clamp()
}
function onWheel(e) { zoom(e.deltaY < 0 ? 1 : -1) }

function clamp() {
  const el = document.querySelector('.viewer-stage img')
  if (!el) return
  const r = el.getBoundingClientRect()
  const w = el.offsetWidth || (r.width ? r.width / scale.value : 0)
  const h = el.offsetHeight || (r.height ? r.height / scale.value : 0)
  const swap = angle.value % 180 !== 0
  const ew = (swap ? h : w) * scale.value
  const eh = (swap ? w : h) * scale.value
  const mx = Math.max(Math.round(window.innerWidth * 0.4),
    Math.round((ew - window.innerWidth) / 2 + 60))
  const my = Math.max(Math.round(window.innerHeight * 0.4),
    Math.round((eh - window.innerHeight) / 2 + 60))
  if (tx.value > mx) tx.value = mx
  if (tx.value < -mx) tx.value = -mx
  if (ty.value > my) ty.value = my
  if (ty.value < -my) ty.value = -my
}

function onDown(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return
  dragging.value = true
  sx = e.clientX; sy = e.clientY; ox = tx.value; oy = ty.value
  try { e.target.setPointerCapture(e.pointerId) } catch { /* 某些浏览器无捕获 */ }
}
function onMove(e) {
  if (!dragging.value) return
  tx.value = ox + (e.clientX - sx)
  ty.value = oy + (e.clientY - sy)
  clamp()
}
function onUp(e) {
  dragging.value = false
  try { e.target.releasePointerCapture(e.pointerId) } catch { /* 已释放 */ }
}

function close() { emit('close') }
function toDetail() { emit('detail', props.pid) }
</script>

<style scoped>
.viewer {
  position: fixed; inset: 0; z-index: 3000;
  background: rgba(0, 0, 0, .92); display: flex; flex-direction: column;
}
.viewer-bar {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  color: #eee; font-size: 13px;
}
.viewer-bar .spacer { flex: 1; }
.viewer-stage {
  flex: 1; overflow: hidden; display: flex; align-items: center; justify-content: center;
  touch-action: none; cursor: grab;
}
.viewer-stage img {
  max-width: 90vw; max-height: 88vh; cursor: grab;
  transition: transform .08s linear;
}
.viewer-stage img.dragging { cursor: grabbing; }
.faint { color: #bbb; }
</style>
