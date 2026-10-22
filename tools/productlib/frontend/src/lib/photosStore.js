/* photosStore.js —— 照片页的跨组件共享状态（Vue 版）
 *
 * 对应旧版 selbatch.js + photos.js 里的模块级单例：
 *   - 勾选集合 sel：跨「加载更多」保留，以 photo id 为准；
 *   - 筛选真源 filters：树与工具栏改的是同一份（不再像旧版那样树改隐藏下拉的值）；
 *   - 事件总线 bus：photos:changed（旧版 window 事件）—— 抽屉/批量动作改动后
 *     列表、树、徽章统一重算。
 *
 * ⚠️ 数字同源铁律照旧：徽章（linkstate）与列表（photos）传的是**同一份 filters**，
 *    徽章与「共 N 张」不允许各算各的。
 */
import { reactive, ref } from 'vue'
import { api } from '../api.js'

/* ── 全局柜锚点（旧版 core.js getCid/setCid）──
 * 只落 localStorage['plCid']，全站唯一真相源。柜作业/报告共用。
 *
 * ⚠️ **必须是 ref，不能是普通模块变量**：视图里到处是
 *    `computed(() => anchor.cid)`，若 _cid 是普通变量，computed 没有任何
 *    响应式依赖 → 首次求值后永久缓存，setCid 之后界面**永远不更新**
 *    （实测：建柜成功、后端 progress 也拉到了，页面却还停在「先建一个柜」空态）。
 *    订阅者回调只负责副作用（重拉数据），重渲染得靠这个 ref。 */
const CID_KEY = 'plCid'
let _init = ''
try { _init = localStorage.getItem(CID_KEY) || '' } catch { _init = '' }
const _cid = ref(_init)
const cidSubs = new Set()
export const anchor = {
  get cid() { return _cid.value },
  setCid(id) {
    const v = id || ''
    _cid.value = v
    try {
      if (v) localStorage.setItem(CID_KEY, v)
      else localStorage.removeItem(CID_KEY)
    } catch { /* 隐私模式 */ }
    cidSubs.forEach((fn) => { try { fn(v) } catch { /* 单个订阅者坏掉不阻塞 */ } })
  },
  onChange(fn) {
    cidSubs.add(fn)
    return () => cidSubs.delete(fn)
  },
}

/* ── 事件总线 ── */
const handlers = new Map()
export const bus = {
  on(evt, fn) {
    if (!handlers.has(evt)) handlers.set(evt, new Set())
    handlers.get(evt).add(fn)
    return () => handlers.get(evt).delete(fn)
  },
  emit(evt, payload) {
    (handlers.get(evt) || []).forEach((fn) => {
      try { fn(payload) } catch (e) { console.error(e) }
    })
  },
}

/* ── 筛选状态（真源）：工具栏下拉 + 左侧树改的都是它 ──
 * 工厂 + 单例两份：照片库页用导出的 filters 单例；柜作业③要用**自己一份**
 * （那边固定一个柜、还多一维「待确认细分」，共用会把照片库的筛选弄脏）。
 * 所以做成工厂，两处各自持一份，形状相同。 */
export function makeFilters(extra) {
  return reactive(Object.assign({
    container_id: '',
    batch: '',
    state: '',
    usage: '',
    kind: '',
    invalid: 'hide',   // hide / only / all
    unlinked: 0,
    todo: '',
    q: '',
    pending: 0,        // ③柜作业专用：待确认细分（后端 pending=1）
  }, extra || {}))
}
export const filters = makeFilters()

export function resetFilters() {
  Object.assign(filters, {
    container_id: '', batch: '', state: '', usage: '', kind: '',
    invalid: 'hide', unlinked: 0, todo: '', q: '', pending: 0,
  })
}

/* ── 勾选集合（选择模式）──
 * 同上：工厂 + 单例。st 参数缺省 = 照片库那份。 */
export function makeSel() {
  return reactive({ on: false, ids: new Set(), version: 0 })
}
export const sel = makeSel()
export const selIds = (st) => [...(st || sel).ids]
export const selSize = (st) => (st || sel).ids.size
export const selHas = (id, st) => (st || sel).ids.has(id)
export function selToggle(id, st) {
  const s = st || sel
  if (s.ids.has(id)) s.ids.delete(id)
  else s.ids.add(id)
  /* Set 原地 mutate 不触发 reactive 依赖 → 手动通知计数（Vue3 里
   * reactive(new Set) 确实能追到 add/delete，但为稳妥统一 bump 一下版本号） */
  s.version = (s.version || 0) + 1
}
export function selAddIds(ids, st) {
  const s = st || sel
  ;(ids || []).forEach((id) => { if (id) s.ids.add(id) })
  s.version = (s.version || 0) + 1
}
export function selClear(st) {
  const s = st || sel
  s.ids.clear()
  s.version = (s.version || 0) + 1
}
export function selSetMode(on, st) {
  const s = st || sel
  s.on = !!on
  if (!s.on) selClear(s)
}

/* ── 下拉数据（分类/批次/柜/治理信息）── */
export const opts = reactive({ kinds: {}, batches: [], containers: [] })

export async function loadFieldOptions() {
  try {
    const d = await api('/api/fields')
    opts.kinds = d.kinds || {}
  } catch { /* 分类下拉拿不到不阻塞列表 */ }
}

export async function loadBatchOptions() {
  try {
    const d = await api('/api/batches')
    opts.batches = d.items || []
  } catch { opts.batches = [] }
}

export async function loadContainerOptions() {
  try {
    const d = await api('/api/containers')
    opts.containers = (d.items || []).filter((c) => c.container_no !== '_UNCATEGORIZED')
  } catch { opts.containers = [] }
}

/** 页面进入时拉齐三份下拉（并行，互不阻塞）。 */
export function loadAllOptions() {
  return Promise.all([loadFieldOptions(), loadBatchOptions(), loadContainerOptions()])
}
