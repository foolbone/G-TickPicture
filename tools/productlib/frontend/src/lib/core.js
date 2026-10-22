/* core.js —— 旧版 web/static/js/core.js 中与页面无关的纯函数部分（Vue 版）
 *
 * 只搬「纯逻辑」：分类文案/格式化/ID 构造。
 * DOM 相关（$ / $$ / toast / busy / tab 调度）在 Vue 版由组件与 router 承担。
 * ⚠️ 文案与旧版保持逐字一致 —— 报告、CDP 断言、老板的习惯都按这套字面跑。
 */

/* 分类文案（老板分类表 2026-10-17）：键序 = 编号序（预检 0201→0205）。
 * 编号只定顺序/枚举，UI 文案不带编号。 */
export const KIND_LABELS = {
  label: '产品·有编码',
  product: '产品·无编码',
  packaging: '包装',
  packing_list: '清单',
  unknown: '其他预检',
  scene: '场景（监装照）',
}
export const KIND_KEYS = Object.keys(KIND_LABELS)

/** 监装细分（键序 = 编号序 0101→0107），文案不带编号。 */
export const SUPTAGS = {
  empty_container: '空柜',
  container_side: '柜侧',
  container_seal: '封条',
  container_lock: '锁门',
  truck_head: '卡车头/车牌号',
  loading_process: '装柜过程',
  other: '其他监装照片',
}
export const SUPTAG_KEYS = Object.keys(SUPTAGS)

/** 用途三档（01 监装 / 02 预检 / 03 其他），顺序即编号序。 */
export const USAGES = ['监装', '预检', '其他']

/** 只有这些分类需要关联产品（后端 schema.LINKABLE_KINDS 白名单同源）。
 *  包装 / 清单 / 其他预检 / 场景 / 未识别 一律不进待关联。 */
export const LINKABLE_KINDS = ['label', 'product']

export const kindName = (k) => KIND_LABELS[k] || k || '未分类'
export const kindCls = (k) => 'k-' + (KIND_LABELS[k] ? k : 'unknown')
export const isProductKind = (k) => LINKABLE_KINDS.includes(k)

/** 拍照时间：必须到秒（现场连拍 0~2 秒一张，只到分钟等于没显示）；
 *  缺时间显示「时间未知」而不是留空（留空会被读成"没这信息"）。 */
export function fmtTaken(taken, opt) {
  const o = opt || {}
  const s = String(taken == null ? '' : taken).trim()
  if (!s) return o.blank || '时间未知'
  const m = s.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/)
  if (!m) return s.replace('T', ' ')
  const d = m[1] + '-' + m[2] + '-' + m[3]
  const t = m[4] + ':' + m[5] + ':' + (m[6] || '00')
  if (o.date) return d
  if (o.full) return d + ' ' + t
  if (o.clock) return t
  return m[2] + '-' + m[3] + ' ' + t
}

/** 相邻两张的间隔（秒）：3s = 真的连拍，2min = 其实停过。 */
export function fmtGap(sec) {
  if (sec == null || !isFinite(sec)) return ''
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return '+' + s + 's'
  const m = Math.floor(s / 60)
  if (m < 60) return '+' + m + 'm' + (s % 60 ? s % 60 + 's' : '')
  const h = Math.floor(m / 60)
  return '+' + h + 'h' + (m % 60 ? m % 60 + 'm' : '')
}

/** 时长（秒）→ 人话。作业耗时用：跨天出「2天3小时」，不到 1 分钟出秒。
 *  与 fmtGap 的分工：fmtGap 是「相邻两张的间隔」带 + 号，fmtDur 是
 *  「一整段作业的时长」不带号。 */
export function fmtDur(sec) {
  if (sec == null || !isFinite(sec)) return ''
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return s + '秒'
  const m = Math.floor(s / 60)
  if (m < 60) return m + '分' + (s % 60 ? s % 60 + '秒' : '')
  const h = Math.floor(m / 60)
  if (h < 24) return h + '小时' + (m % 60 ? m % 60 + '分' : '')
  const d = Math.floor(h / 24)
  return d + '天' + (h % 24 ? h % 24 + '小时' : '')
}

/** 柜作业时长（后端 work 汇总）→ 起止区间，如「09-15 20:40 ~ 09-29 19:24」。
 *  两端共用一份，别在各组件里各写一遍。 */
export function workRange(w) {
  if (!w || !w.from || !w.to) return ''
  // 🔴 跨年必须带年份：只显示 MM-DD 会把「2021-08-31 → 2026-10-13」读成
  //    同一年的 8 月到 10 月（真实库那柜跨 5 年，验收时才发现）。
  const y1 = String(w.from).slice(0, 4), y2 = String(w.to).slice(0, 4)
  const o = y1 !== y2 ? { date: true } : null
  return fmtTaken(w.from, o) + ' ~ ' + fmtTaken(w.to, o)
}

/** 柜作业时长（后端 work 汇总）→ 时长文案。
 *  🔴 零散数据（后端 scattered：含跨度异常的段）只给段数不给时长 ——
 *     「历史图片」那种兜底柜能算出 44855 小时，宁可少说也不能把数据
 *     问题说成作业强度。 */
export function workDur(w) {
  if (!w) return ''
  if (w.scattered) return w.segments + ' 段（数据零散，不计时长）'
  const d = fmtDur(w.active_sec)
  return d ? '净作业 ' + d : '时长未知'
}

export function diffSec(a, b) {
  const ta = Date.parse(String(a || '').replace(' ', 'T'))
  const tb = Date.parse(String(b || '').replace(' ', 'T'))
  return isFinite(ta) && isFinite(tb) ? (tb - ta) / 1000 : NaN
}

/** 把可能是 JSON 串的字段解成数组（后端部分字段存文本）。 */
export function jparse(v, dflt) {
  if (v == null || v === '') return dflt
  if (Array.isArray(v)) return v
  if (typeof v === 'object') return v
  try {
    const j = JSON.parse(v)
    return j == null ? dflt : j
  } catch {
    return dflt
  }
}

/** URLSearchParams → 纯对象（fetch 的 query 用；空串键保留，方便后端收 ''）。 */
export function qs(obj) {
  const p = new URLSearchParams()
  Object.keys(obj || {}).forEach((k) => {
    const v = obj[k]
    p.set(k, v == null ? '' : String(v))
  })
  return p.toString()
}
