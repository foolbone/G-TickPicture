/* checklist.js —— ② 清单的取数与保存（Vue 版）
 *
 * 两个写落点必须分开（别混成一次调用）：
 *   品名 / 规格 → 产品库产品主记录（PATCH /api/products/{code}，唯一真源）
 *   Loading / 核对 → 本批次的**人工核对结论**（POST /api/checklist/rows/check，
 *                     端点一次写两个字段，所以要一起带）
 * 留空 = 未核对，报告沿用清单预填值，不会替你猜 PASS。
 */

/** 拉本柜清单行。默认必须挑**行数最多**的那批，不能挑「最后一个」——
 *  同柜重导会留下一个 0 行的空批次（replace 语义），挑它表格就是空的，
 *  看起来像「清单没导进来」（实测踩过：1003 行的柜默认显示 0 行）。 */
export async function loadChecklistRows(detail, cid, st) {
  const bs = (detail ? detail.batches : []).filter((b) => b.kind === 'checklist')
  if (!bs.length) {
    st.clRows = []
    st.clBatch = ''
    st.clFor = ''
    return []
  }
  if (!st.clBatch || !bs.some((b) => b.id === st.clBatch)) {
    const best = bs.reduce((a, b) => ((b.rows || 0) > (a.rows || 0) ? b : a), bs[0])
    st.clBatch = (best.rows || 0) > 0 ? best.id : bs[bs.length - 1].id
  }
  if (st.clFor === cid + '|' + st.clBatch) return st.clRows   // 已拉过，1000+ 行不便宜
  try {
    const d = await fetch(
      '/api/containers/' + cid + '/checklist?batch=' + encodeURIComponent(st.clBatch))
    const j = await d.json()
    if (!d.ok) throw new Error(j.detail || ('HTTP ' + d.status))
    st.clRows = j.items || []
    st.clPage = 0
    st.clFor = cid + '|' + st.clBatch
  } catch {
    st.clRows = []
  }
  return st.clRows
}

/** 把编辑缓冲区的改动落盘。edits: [{code_norm, name?, spec?}] + rows: [{...}] */
export async function saveChecklistEdits(productEdits, rowEdits) {
  const np = Object.keys(productEdits || {}).length
  if (!np && !(rowEdits || []).length) return { np: 0, nr: 0 }
  for (const cn in productEdits) {
    const r = await fetch('/api/products/' + encodeURIComponent(cn), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(productEdits[cn]),
    })
    if (!r.ok) {
      const j = await r.json().catch(() => ({}))
      throw new Error(j.detail || ('HTTP ' + r.status))
    }
  }
  for (const t of rowEdits || []) {
    const r = await fetch('/api/checklist/rows/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        batch_id: t.batch_id, seq: t.seq,
        check_result: t.check_result, loading_qty: t.loading_qty, by: 'web',
      }),
    })
    if (!r.ok) {
      const j = await r.json().catch(() => ({}))
      throw new Error(j.detail || ('HTTP ' + r.status))
    }
  }
  return { np, nr: (rowEdits || []).length }
}
