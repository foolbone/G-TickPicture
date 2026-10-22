<template>
  <!-- 标准图编辑器（对应旧版 standard.js openStdEditor + index.html #stdEd）
       全屏覆盖：裁切 / 旋转 / 放大镜 / 等比，保存后 POST /api/standard-images。
       Esc 关闭；保存成功后可「打开该产品标准图」或跳「在产品库查看」。 -->
  <div class="stdEd">
    <div class="std-top">
      <span class="t">标准图编辑</span>
      <span class="faint sug">{{ sug }}</span>
      <span class="spacer"></span>
      <label class="faint">比例</label>
      <el-select v-model="ratioVal" size="small" style="width:110px" @change="ratioChanged">
        <el-option label="自由" :value="0" />
        <el-option label="1:1" :value="1" />
        <el-option label="4:3" :value="1.3333" />
        <el-option label="3:4" :value="0.75" />
      </el-select>
      <label class="faint">放大镜</label>
      <el-select v-model="zoomLevel" size="small" style="width:110px" @change="zoomChanged">
        <el-option label="2x" :value="2" />
        <el-option label="3x" :value="3" />
        <el-option label="4x" :value="4" />
        <el-option label="关" :value="0" />
      </el-select>
      <el-button size="small" @click="rotate">旋转 90°</el-button>
      <el-button size="small" @click="resetCrop">重置选框</el-button>
      <el-button size="small" type="primary" :loading="saving" @click="save">保存标准图</el-button>
      <el-button size="small" @click="emit('close')">关闭</el-button>
    </div>

    <div class="std-stage" ref="stageRef">
      <canvas ref="canvasRef" @pointermove="onPointerMove" @pointerdown="onPointerDown"
              @pointerup="onPointerUp" @pointercancel="onPointerUp" @pointerleave="zoomHide" />
      <div class="stdZoom" :class="{ on: zoomOn }" ref="zoomRef">
        <canvas ref="zoomCanvasRef" width="160" height="160" />
        <span class="zl">{{ zoomLevel }}x</span>
      </div>
    </div>

    <div class="std-bottom">
      <span class="faint">拖四角 / 边缘调选框，框内拖动移动，框外点击重拉。</span>
      <span class="spacer"></span>
      <span class="muted">产品编码</span>
      <el-input v-model="code" size="small" style="width:210px" placeholder="产品编码" />
      <span class="muted">类别</span>
      <el-select v-model="kind" size="small" style="width:150px">
        <el-option v-for="k in kindKeys" :key="k" :label="kindName(k)" :value="k" />
      </el-select>
      <span class="faint">{{ msg }}</span>
    </div>
  </div>
</template>

<script setup>
/* StandardEditor.vue —— 标准图编辑器
 *
 * 逻辑逐行对旧版 standard.js：
 *   - work 画布：先按旋转角度合成（rotate 后 90/270 会交换宽高）；
 *   - crop 在 work 坐标系，绘制时乘 scale 落到显示画布；
 *   - 选框：8 个手柄拖拽 / 框内拖动 / 框外重拉，等比锁定时钳制宽高；
 *   - 放大镜：跟随光标，从 work 画布采样 160/lv 区域，imageSmoothing 关掉留硬边。
 */
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { api, post } from '../api.js'
import { KIND_LABELS, kindName } from '../lib/core.js'

const props = defineProps({
  pid: { type: String, required: true },
  kind: { type: String, default: 'unknown' },
  defCode: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved', 'go-product'])

const KIND_KEYS = ['label', 'product', 'packaging', 'unknown']

const stageRef = ref(null)
const canvasRef = ref(null)
const zoomRef = ref(null)
const zoomCanvasRef = ref(null)

const code = ref(props.defCode || '')
const kind = ref(props.kind || 'unknown')
const ratioVal = ref(0)
const zoomLevel = ref(2)
const saving = ref(false)
const msg = ref('')
const zoomOn = ref(false)

const sug = computed(() => {
  const k = kind.value
  if (k === 'label') return '标识卡类 → 横版 4:3，卡面占满、四边少留背景'
  if (k === 'product') return '产品类 → 1:1 特写，主体居中'
  if (k === 'packaging') return '包装类 → 4:3，含可识别面（唛头 / 标签侧）'
  return '未分类 → 建议先去「预检照片入库」重跑分类，或按 4:3 裁出主体'
})
const kindKeys = KIND_KEYS.filter((k) => k !== 'scene' && k !== 'packing_list')

/* 工作状态（对应旧版 STD 单例） */
const img = ref(null)             // 原始 <img>（naturalWidth/Height）
let work = null                   // 已旋转的源画布
let rot = 0
const crop = reactive({ x: 0, y: 0, w: 0, h: 0 })
let scale = 1
let mode = null                   // 'move' | 'new' | 手柄键
let start = null
let c0 = null

const ratio = () => (Number(ratioVal.value) || 0)

function workCanvas() {
  const im = img.value
  const c = document.createElement('canvas')
  const r = ((rot % 360) + 360) % 360
  const swap = (r === 90 || r === 270)
  c.width = swap ? im.naturalHeight : im.naturalWidth
  c.height = swap ? im.naturalWidth : im.naturalHeight
  const x = c.getContext('2d')
  x.translate(c.width / 2, c.height / 2)
  x.rotate((r * Math.PI) / 180)
  x.drawImage(im, -im.naturalWidth / 2, -im.naturalHeight / 2)
  return c
}

function applyRotation() {
  if (!img.value) return
  work = workCanvas()
  const stage = stageRef.value
  const sc = Math.min(
    (stage.clientWidth * 0.94) / work.width,
    (stage.clientHeight * 0.94) / work.height,
    1,
  )
  scale = sc
  const cv = canvasRef.value
  cv.width = Math.max(1, Math.round(work.width * sc))
  cv.height = Math.max(1, Math.round(work.height * sc))
  resetCrop(true)
  draw()
}

function resetCrop(quiet) {
  if (!work) return
  const W = work.width, H = work.height, r = ratio()
  let w = W * 0.8, h = H * 0.8
  if (r) { if (w / h > r) w = h * r; else h = w / r }
  Object.assign(crop, { x: (W - w) / 2, y: (H - h) / 2, w, h })
  if (!quiet) draw()
}

function clamp(x, y, w, h, W, H, r) {
  w = Math.min(w, W); h = Math.min(h, H)
  if (r) {
    if (w / h > r) w = h * r; else h = w / r
    if (h > H) { h = H; w = h * r }
    if (w > W) { w = W; h = w / r }
  }
  return {
    x: Math.max(0, Math.min(W - w, x)),
    y: Math.max(0, Math.min(H - h, y)),
    w, h,
  }
}

function handles() {
  const c = crop
  return [
    { k: 'nw', x: c.x, y: c.y }, { k: 'n', x: c.x + c.w / 2, y: c.y },
    { k: 'ne', x: c.x + c.w, y: c.y }, { k: 'w', x: c.x, y: c.y + c.h / 2 },
    { k: 'e', x: c.x + c.w, y: c.y + c.h / 2 }, { k: 'sw', x: c.x, y: c.y + c.h },
    { k: 's', x: c.x + c.w / 2, y: c.y + c.h }, { k: 'se', x: c.x + c.w, y: c.y + c.h },
  ]
}

function draw() {
  const cv = canvasRef.value
  if (!cv || !work) return
  const x = cv.getContext('2d')
  x.clearRect(0, 0, cv.width, cv.height)
  x.drawImage(work, 0, 0, cv.width, cv.height)
  const s = scale, c = crop
  x.fillStyle = 'rgba(0,0,0,.55)'
  x.fillRect(0, 0, cv.width, c.y * s)
  x.fillRect(0, (c.y + c.h) * s, cv.width, cv.height - (c.y + c.h) * s)
  x.fillRect(0, c.y * s, c.x * s, c.h * s)
  x.fillRect((c.x + c.w) * s, c.y * s, cv.width - (c.x + c.w) * s, c.h * s)
  x.strokeStyle = '#4da3ff'; x.lineWidth = 1.5
  x.strokeRect(c.x * s, c.y * s, c.w * s, c.h * s)
  x.strokeStyle = 'rgba(255,255,255,.25)'; x.lineWidth = 1
  for (let i = 1; i < 3; i++) {
    x.beginPath(); x.moveTo((c.x + (c.w * i) / 3) * s, c.y * s)
    x.lineTo((c.x + (c.w * i) / 3) * s, (c.y + c.h) * s); x.stroke()
    x.beginPath(); x.moveTo(c.x * s, (c.y + (c.h * i) / 3) * s)
    x.lineTo((c.x + c.w) * s, (c.y + (c.h * i) / 3) * s); x.stroke()
  }
  x.fillStyle = '#fff'
  handles().forEach((h) => x.fillRect(h.x * s - 4, h.y * s - 4, 8, 8))
}

/* ── 放大镜：跟随光标，按倍率从工作画布（已旋转）采样 ── */
function zoomHide() {
  zoomOn.value = false
}
function zoomAt(pt) {
  const box = zoomRef.value
  const lv = Number(zoomLevel.value) || 0
  if (!box || !lv || !work) { zoomHide(); return }
  const zc = zoomCanvasRef.value
  const zx = zc.getContext('2d')
  let vw = Math.min(zc.width / lv, work.width)
  let vh = Math.min(zc.height / lv, work.height)
  let sx = pt.x - vw / 2, sy = pt.y - vh / 2
  sx = Math.max(0, Math.min(work.width - vw, sx))
  sy = Math.max(0, Math.min(work.height - vh, sy))
  zx.imageSmoothingEnabled = false
  zx.clearRect(0, 0, zc.width, zc.height)
  zx.drawImage(work, sx, sy, vw, vh, 0, 0, zc.width, zc.height)
  zx.strokeStyle = 'rgba(77,163,255,.95)'; zx.lineWidth = 1
  zx.beginPath(); zx.moveTo(zc.width / 2, 0); zx.lineTo(zc.width / 2, zc.height); zx.stroke()
  zx.beginPath(); zx.moveTo(0, zc.height / 2); zx.lineTo(zc.width, zc.height / 2); zx.stroke()
  zoomOn.value = true
}

const pos = (e) => {
  const r = canvasRef.value.getBoundingClientRect()
  return { x: (e.clientX - r.left) / scale, y: (e.clientY - r.top) / scale }
}
const hit = (pt) => {
  const s = scale
  for (const h of handles())
    if (Math.abs(pt.x - h.x) < 10 / s && Math.abs(pt.y - h.y) < 10 / s) return h.k
  return null
}

function onPointerMove(e) {
  if (!work) return
  zoomAt(pos(e))
  if (!mode || !work) return
  const pt = pos(e)
  const W = work.width, H = work.height
  const r = ratio()
  if (mode === 'move') {
    Object.assign(crop, clamp(c0.x + pt.x - start.x, c0.y + pt.y - start.y, c0.w, c0.h, W, H, r))
  } else if (mode === 'new') {
    let w = Math.abs(pt.x - start.x), h = Math.abs(pt.y - start.y)
    const cx = (start.x + pt.x) / 2, cy = (start.y + pt.y) / 2
    if (r) { if (w / h > r) w = h * r; else h = w / r }
    w = Math.max(20, w); h = Math.max(20, h)
    Object.assign(crop, clamp(cx - w / 2, cy - h / 2, w, h, W, H, r))
  } else {
    let { x, y, w, h } = c0
    const dx = pt.x - start.x, dy = pt.y - start.y
    if (mode.includes('w')) { x = c0.x + dx; w = c0.w - dx }
    if (mode.includes('e')) { w = c0.w + dx }
    if (mode.includes('n')) { y = c0.y + dy; h = c0.h - dy }
    if (mode.includes('s')) { h = c0.h + dy }
    if (r) {
      if (mode === 'n' || mode === 's') { w = h * r; x = c0.x + (c0.w - w) / 2 }
      else { h = w / r; if (mode === 'n') y = c0.y + (c0.h - h) }
    }
    w = Math.max(20, w); h = Math.max(20, h)
    Object.assign(crop, clamp(x, y, w, h, W, H, r))
  }
  draw()
}

function onPointerDown(e) {
  if (!work) return
  const cv = canvasRef.value
  cv.setPointerCapture(e.pointerId)
  const pt = pos(e)
  const hk = hit(pt)
  mode = hk || ((pt.x > crop.x && pt.x < crop.x + crop.w && pt.y > crop.y && pt.y < crop.y + crop.h) ? 'move' : 'new')
  start = pt
  c0 = { ...crop }
}

function onPointerUp() { mode = null }

function rotate() {
  rot = (rot + 270) % 360
  applyRotation()
}

function ratioChanged() {
  resetCrop()
  draw()
}

function zoomChanged() {
  if (!Number(zoomLevel.value)) zoomHide()
  else if (work) ElMessage.success('放大镜 ' + zoomLevel.value + 'x：把光标移到图上即可')
}

/* ── 加载源图 ── */
onMounted(() => {
  if (!props.pid) return
  const im = new Image()
  im.onload = () => {
    img.value = im
    applyRotation()
  }
  im.onerror = () => {
    ElMessage.error('原图加载失败')
    emit('close')
  }
  im.src = '/img/' + props.pid
})

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
if (typeof window !== 'undefined') window.addEventListener('keydown', onKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

/* ── 保存 ── */
async function save() {
  if (!work) return
  const cd = code.value.trim()
  if (!cd) { ElMessage.warning('先填产品编码'); return }
  const c = crop
  const LONG = 1600
  const sc = Math.min(1, LONG / Math.max(c.w, c.h))
  const out = document.createElement('canvas')
  out.width = Math.max(1, Math.round(c.w * sc))
  out.height = Math.max(1, Math.round(c.h * sc))
  out.getContext('2d').drawImage(work, c.x, c.y, c.w, c.h, 0, 0, out.width, out.height)
  const blob = await new Promise((res) => out.toBlob(res, 'image/jpeg', 0.85))
  const reader = new FileReader()
  reader.onload = async () => {
    saving.value = true
    try {
      const r = await post('/api/standard-images', {
        code: cd,
        photo_id: props.pid,
        kind: kind.value,
        image: reader.result.split(',')[1],
        width: out.width,
        height: out.height,
        by: 'user',
      })
      const sid = (r && r.id) || ''
      msg.value = '已保存（' + out.width + '×' + out.height + '）'
      ElMessage.success('标准图已保存到 ' + cd)
      emit('saved', { sid, code: cd })
      if (sid) emit('go-product', cd)
    } catch (e) {
      ElMessage.error('保存失败：' + e.message)
    } finally {
      saving.value = false
    }
  }
  reader.readAsDataURL(blob)
}
</script>

<style scoped>
.stdEd {
  position: fixed; inset: 0; background: rgba(15, 18, 22, .92); z-index: 100;
  display: flex; flex-direction: column; color: #fff;
}
.std-top, .std-bottom {
  display: flex; align-items: center; gap: 10px; padding: 10px 16px;
  background: #fff; flex-wrap: wrap; color: #1f2733;
}
.std-top .t { font-weight: 600; }
.std-top .sug { font-size: 12px; }
.std-top .spacer, .std-bottom .spacer { flex: 1; }
.std-stage {
  position: relative; flex: 1; display: flex; align-items: center;
  justify-content: center; overflow: hidden; min-height: 0;
}
.std-stage canvas {
  background: #0c0e11; max-width: 94%; max-height: 94%; touch-action: none;
  cursor: crosshair; box-shadow: 0 0 0 1px rgba(255, 255, 255, .12);
}
.stdZoom {
  display: none; position: absolute; right: 14px; bottom: 14px;
  width: 160px; height: 160px; border-radius: 8px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, .25); overflow: hidden;
}
.stdZoom.on { display: block; }
.stdZoom canvas { display: block; }
.stdZoom .zl {
  position: absolute; left: 0; top: 0; background: rgba(0, 0, 0, .6);
  color: #fff; font-size: 11px; padding: 1px 6px;
}
.std-bottom .muted { color: #647084; }
.faint { color: #95a0b1; }
</style>
