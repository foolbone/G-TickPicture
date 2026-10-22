/* productsStore.js —— 产品库页的跨组件共享状态（对应旧版 products.js 的模块级变量）
 *
 * 为什么单独一个 store：产品列表、详情抽屉、导入对话框三处都要读写
 * 「当前筛选 / 当前页 / 当前选中产品 / 当前页编码顺序」。放进视图里就得
 * 一路 emit 传，漏一处就是两份真相（旧版 pSel/pCodes/pPage 就是这么散开的）。
 *
 * 🔴 数字同源：筛选参数一份（f），列表与候选角标都从它拼 ——
 *    角标说「有 N 张待确认」而列表筛出来是空的，就是这里出了两份。
 *
 * 🔴 编码顺序 pCodes 是「抽屉上一个/下一个」的唯一依据：翻页后必须重取，
 *    否则翻页后抽屉会跳回第一页的产品。
 */
import { reactive, computed } from 'vue'
import { api } from '../api.js'
import { bus } from './photosStore.js'

export const P_PAGE = 50

export const filters = reactive({
  q: '',
  has: '',
  sort: 'gap',
  container: '',
})

export const page = reactive({ idx: 0, total: 0, pages: 1 })

/** 抽屉当前打开的产品编码（空 = 抽屉关着）。 */
export const sel = reactive({ code: '' })

/** 当前页的编码顺序（抽屉翻上下个走它；也是「删除产品」后判断还在不在的依据）。 */
export const pCodes = reactive({ list: [] })

/** 柜号选项（只认产品清单里的柜号 —— 老板 10-05 口径，后端 product_containers 给）。 */
export const containers = reactive({ list: [], loaded: false })

export const rows = reactive({ list: [] })
export const loading = reactive({ list: false })

const seq = { n: 0 }

/** 「待确认」筛选拆成 cand 参数：any=任一 / code=读码候选 / group=同组候选。
 *  两者与列表角标同一份 store.cand_counts()，筛出来的点开一定有东西。 */
export function splitHas(has) {
  const h = has || ''
  if (h.indexOf('cand') !== 0) return { has: h, cand: '' }
  return { has: '', cand: h === 'cand' ? 'any' : (h === 'cand_code' ? 'code' : 'group') }
}

export function listQuery(offset) {
  const { has, cand } = splitHas(filters.has)
  return {
    q: filters.q, has, cand, sort: filters.sort,
    container: filters.container,
    limit: P_PAGE, offset: offset == null ? page.idx * P_PAGE : offset,
  }
}

export function resetPage() { page.idx = 0 }

/** 连续两次加载谁新谁赢 —— 旧响应丢弃（切筛选快时会把新结果盖成旧的）。 */
export async function load(reset) {
  if (reset) page.idx = 0
  const my = ++seq.n
  loading.list = true
  try {
    const d = await api('/api/products?' + new URLSearchParams(
      Object.entries(listQuery()).map(([k, v]) => [k, String(v == null ? '' : v)]),
    ).toString())
    if (my !== seq.n) return
    const items = d.items || []
    rows.list = items
    page.total = d.total || 0
    page.pages = Math.max(1, Math.ceil(page.total / P_PAGE))
    pCodes.list = items.map((r) => r.code_norm)
  } catch {
    if (my === seq.n) rows.list = []
  } finally {
    if (my === seq.n) loading.list = false
  }
}

export async function loadContainers() {
  try {
    const d = await api('/api/products/containers')
    containers.list = d.items || []
    containers.loaded = true
  } catch {
    containers.list = []
    containers.loaded = true
  }
}

/** 打开一个产品：抽屉与列表高亮同步由 sel.code 一处驱动。 */
export function open(code) { sel.code = code || '' }
export function close() { sel.code = '' }

/** 抽屉里翻上下个：走到页边界自动翻页再取。返回是否真的走了。 */
export async function gotoCode(delta) {
  const i = pCodes.list.indexOf(sel.code)
  if (i < 0 || !pCodes.list.length) return false
  let ni = i + delta
  if (ni < 0) {
    if (page.idx <= 0) return 'edge'
    page.idx -= 1
    await load(false)
    ni = pCodes.list.length - 1
  } else if (ni >= pCodes.list.length) {
    if (page.idx >= page.pages - 1) return 'edge'
    page.idx += 1
    await load(false)
    ni = 0
  }
  const code = pCodes.list[ni]
  if (!code) return false
  sel.code = code
  return true
}

export const posText = computed(() => {
  const i = pCodes.list.indexOf(sel.code)
  if (i < 0) return ''
  return '第 ' + (page.idx * P_PAGE + i + 1) + ' / ' + page.total + ' 条'
})
export const canPrev = computed(() => {
  const i = pCodes.list.indexOf(sel.code)
  return i > 0 || page.idx > 0
})
export const canNext = computed(() => {
  const i = pCodes.list.indexOf(sel.code)
  return (i >= 0 && i < pCodes.list.length - 1) || page.idx < page.pages - 1
})

/** 产品增删改后广播：列表、树、徽章、柜作业一起重算。 */
export function changed() { bus.emit('products:changed') }