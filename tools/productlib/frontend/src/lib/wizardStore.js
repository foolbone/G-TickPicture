/* wizardStore.js —— 柜作业五步的跨组件共享状态（Vue 版）
 *
 * 对应旧版 wizard.js 的模块级单例。状态**派生自后端**
 * /api/containers/{cid}/progress（不落 localStorage 记账），关掉浏览器回来
 * 还是那一步。④选图是唯一的客户端步骤（后端无对应），可跳过。
 *
 * 换柜时必须整份重置 —— ④的编码池/检索结果、监装候选、清单批次都是**柜的**，
 * 混着上一个柜的数据比空着更危险。
 */
import { reactive } from 'vue'
import { api } from '../api.js'
import { anchor } from './photosStore.js'

export const STEPS = ['container', 'checklist', 'photos', 'picks', 'report']

export const META = {
  container: {
    n: '①', name: '建柜',
    desc: '柜号是全流程主线。下面的柜信息会进报告的 General Information —— 缺项标橙，改完点保存。',
  },
  checklist: {
    n: '②', name: '导入清单',
    desc: '把货品清单（Excel）导入到本柜，并在这里查看 / 修改清单内容（品名·规格·Loading·核对）。',
  },
  photos: {
    n: '③', name: '照片',
    desc: '',
  },
  picks: {
    n: '④', name: '选图',
    desc: '为报告挑用图：每件货的核对照（Quantity check），以及监装照片（柜况④每类一张、卡车⑦多选）。都不选也能出报告 —— 那时按编码/最新照片自动取。',
  },
  report: {
    n: '⑤', name: '生成报告',
    desc: '按柜出装柜报告（Packing list + Quantity check + 柜况 / 卡车照片）。',
  },
}

/* 全局状态（单例，跨组件共享） */
export const wiz = reactive({
  active: 'container',
  prog: null,
  detail: null,
  loadErr: '',
  anchorWarn: '',
  reports: null,
  /* ② 清单表格 */
  clBatch: '',
  clRows: [],
  clPage: 0,
  clFor: '',
  /* ④ 选图 */
  picks: {},           // code_norm -> [photo_id,...]（编码采用）
  trucks: [],          // ⑦ 卡车选中的 photo_id（按点选顺序）
  conds: {},           // ④ tag -> [photo_id,...]（每类可多张）
  codes: [],           // 本柜清单编码池
  lastRp: null,        // 最近一次检索结果
  strategy: 'balanced',
  strategies: [],
  lpFor: '',           // 已为哪个柜自动载过编码+检索过
  genResult: null,     // ⑤ 刚生成的结果卡
})

export const CL_PAGE = 50

/* ── ④ 采用标记按柜存（与报告中心同一口径，刷新 / 切步骤不丢）── */
const PICKS_KEY = (cid) => 'wizPicks:' + cid
const SUP_KEY = (cid) => 'wizPicksSup:' + cid
const PICK_TAB_KEY = (cid) => 'wizPickTab:' + cid

export const pickCount = () =>
  Object.values(wiz.picks).reduce((a, v) => a + (Array.isArray(v) ? v.length : 0), 0)
export const condCount = () =>
  Object.values(wiz.conds).reduce((a, v) => a + (Array.isArray(v) ? v.length : 0), 0)

export function savePicks() {
  try { localStorage.setItem(PICKS_KEY(anchor.cid), JSON.stringify(wiz.picks)) } catch { /* 隐私模式 */ }
}
export function loadPicks() {
  Object.keys(wiz.picks).forEach((k) => delete wiz.picks[k])
  let raw = null
  try { raw = localStorage.getItem(PICKS_KEY(anchor.cid)) } catch { /* 隐私模式 */ }
  if (raw) {
    try { Object.assign(wiz.picks, JSON.parse(raw) || {}) } catch { /* 坏 JSON 当空 */ }
  }
}

/* 监装照片的落盘必须能区分「没动过」（= 后端自动取，不传 trucks/conds 键）
   与「选了又全取消」（= ⑦ 明确留空）：key 存在 = 人工动过。
   2026-10-18 老板规则：柜况细类**不限一张**，conds[tag] = [photo_id,...]；
   旧数据（单 photo_id）load 时归一成 list。 */
export function supTouched() {
  try { return !!localStorage.getItem(SUP_KEY(anchor.cid)) } catch { return false }
}
export function saveSup() {
  try {
    localStorage.setItem(SUP_KEY(anchor.cid),
      JSON.stringify({ trucks: wiz.trucks, conds: wiz.conds }))
  } catch { /* 隐私模式 */ }
}
export function loadSup() {
  wiz.trucks = []
  Object.keys(wiz.conds).forEach((k) => delete wiz.conds[k])
  let raw = null
  try { raw = localStorage.getItem(SUP_KEY(anchor.cid)) } catch { /* 隐私模式 */ }
  if (!raw) return
  try {
    const d = JSON.parse(raw) || {}
    if (Array.isArray(d.trucks)) wiz.trucks = d.trucks.map(String)
    if (d.conds && typeof d.conds === 'object') {
      Object.keys(d.conds).forEach((k) => {
        const v = d.conds[k]
        wiz.conds[k] = Array.isArray(v) ? v.map(String) : (v ? [String(v)] : [])
      })
    }
  } catch { /* 坏 JSON 当空 */ }
}
export function resetSup() {
  wiz.trucks = []
  Object.keys(wiz.conds).forEach((k) => delete wiz.conds[k])
  try { localStorage.removeItem(SUP_KEY(anchor.cid)) } catch { /* 隐私模式 */ }
}
export function getPickTab() {
  try { return localStorage.getItem(PICK_TAB_KEY(anchor.cid)) || 'pre' } catch { return 'pre' }
}
export function setPickTab(t) {
  try { localStorage.setItem(PICK_TAB_KEY(anchor.cid), t === 'sup' ? 'sup' : 'pre') } catch { /* 隐私模式 */ }
}

/* ── 每步状态：把后端 5 个 steps 映射到 UI 的 5 步 ── */
export function stepState(key) {
  if (!wiz.prog) return { done: false, summary: '—' }
  const P = wiz.prog.steps
  const cid = anchor.cid
  if (!cid && key !== 'container') return { done: false, summary: '未选柜', blocked: true }
  if (key === 'container') return { done: P.container.done, summary: P.container.summary }
  if (key === 'checklist') return { done: P.checklist.done, summary: P.checklist.summary }
  if (key === 'photos') {
    const ph = P.photos, gv = P.govern
    return {
      done: ph.done && gv.done,
      summary: ph.total ? (ph.total + ' 张 · 治理 ' + gv.done_cnt + '/' + gv.total) : '未导入',
    }
  }
  if (key === 'picks') {
    if (P.checklist.row_total === 0) return { done: false, summary: '先完成②', blocked: true }
    const n = pickCount() + wiz.trucks.length + condCount()
    return { done: n > 0, summary: n ? ('已选 ' + n + ' 张') : '未选（可跳过）' }
  }
  if (key === 'report') return { done: P.report.done, summary: P.report.summary }
  return { done: false, summary: '—' }
}

export function defaultActive() {
  if (!wiz.prog) return 'container'
  for (const k of STEPS) if (!stepState(k).done) return k
  return 'report'
}
export const nextStepKey = (k) => {
  const i = STEPS.indexOf(k)
  return STEPS[Math.min(i + 1, STEPS.length - 1)]
}

/** 拉进度 + 柜详情。advance=true 时「这一步真的完成才跳下一步」。
 *
 * ⚠️ 自动跳步不能「导完就跳」—— v6 把「导入照片」与「跑治理」并成一步后，
 * 治理还没跑呢，跳到④等于把老板从治理面板上带走（实测 Photos 已入库
 * 但界面停在④，看不到自己刚导的照片）。
 *
 * ⚠️ 400 +「柜不存在」= **锚点脏了**：localStorage['plCid'] 按 origin 存、
 * 跨库共用，换机器/换库后还指着旧库的柜（老板 10-07 用绿色包在全新环境撞到，
 * 整页 500）。这种就地把锚点清掉并落到第一个柜，不能只弹一句报错。 */
export async function loadProgress(advance) {
  const cid = anchor.cid
  if (!cid) {
    wiz.prog = null
    wiz.detail = null
    wiz.loadErr = ''
    return
  }
  wiz.loadErr = ''
  try {
    wiz.prog = await api('/api/containers/' + cid + '/progress')
  } catch (e) {
    const raw = (e && e.message) ? e.message : String(e)
    wiz.prog = null
    if (/柜不存在/.test(raw)) {
      anchor.setCid('')
      let items = []
      try {
        const d = await api('/api/containers')
        items = (d.items || []).filter((c) => c.container_no !== '_UNCATEGORIZED')
      } catch { /* 拿不到就按空处理，不挡住自愈 */ }
      wiz.anchorWarn = items.length
        ? '上次选的柜在这个库里没有（换机器或换库后，浏览器里还留着旧柜号「' + cid +
          '」），已经帮你切到「' + (items[0].container_no || '（未分柜）') +
          '」。若那柜的货确实要继续做，把老版本的 data\\ 整个拷到这个版本目录即可。'
        : '上次选的柜在这个库里没有（换机器或换库后，浏览器里还留着旧柜号「' + cid +
          '」），而当前这个柜库还没有柜 —— 先到「柜」页新建一个；' +
          '若那柜的货确实要继续做，把老版本的 data\\ 整个拷到这个版本目录即可。'
      return
    }
    wiz.loadErr = /not found|404/i.test(raw)
      ? ('后端没有这个接口（' + raw + '）。多半是服务进程还是旧的 —— ' +
         '路由在进程启动时加载、页面是每次现读的，所以会「界面是新的、接口 404」。重启产品库服务即可。')
      : ('读取向导进度失败：' + raw)
    return
  }
  /* 柜详情（①②③④ 的结果详情都从它出）—— 单独 try：详情挂了不连累进度 */
  try { wiz.detail = await api('/api/containers/' + cid) } catch { wiz.detail = null }
  if (advance && wiz.prog && stepState(wiz.active).done) wiz.active = nextStepKey(wiz.active)
  else if (!wiz.active || !wiz.prog || !wiz.prog.steps[wiz.active]) wiz.active = defaultActive()
}

export async function loadReports() {
  try { wiz.reports = await api('/api/report/loading-list') } catch { wiz.reports = { items: [] } }
}

/** 换柜：把柜相关的状态整份清掉。混着上一个柜的数据比空着更危险。 */
export function resetForContainer() {
  wiz.genResult = null
  wiz.reports = null
  wiz.clBatch = ''
  wiz.clRows = []
  wiz.clFor = ''
  wiz.clPage = 0
  wiz.lpFor = ''
  wiz.lastRp = null
  wiz.codes = []
  loadPicks()
  loadSup()
}

export const CL_PAGE_SIZE = CL_PAGE
