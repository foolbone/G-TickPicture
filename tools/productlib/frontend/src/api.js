/* API 封装：与旧版 core.js 的 api/post/patch/del 同一套约定
 * （错误统一弹 ElMessage；JSON body；POST/GET 全走这里，便于以后加拦截）。 */
import { ElMessage } from 'element-plus'

async function request(method, path, payload) {
  const opt = { method, headers: {} }
  if (payload !== undefined) {
    /* 🔴 FormData 必须原样发出去：不能设 Content-Type（boundary 得让浏览器自己
       带），也不能 JSON.stringify。走错这条路的症状是「上传没报错但一张没进来」。 */
    if (typeof FormData !== 'undefined' && payload instanceof FormData) {
      opt.body = payload
    } else {
      opt.headers['Content-Type'] = 'application/json'
      opt.body = JSON.stringify(payload)
    }
  }
  let r
  try {
    r = await fetch(path, opt)
  } catch (e) {
    ElMessage.error('网络错误：' + e.message)
    throw e
  }
  let d = null
  try { d = await r.json() } catch { /* 非 JSON（如 204） */ }
  if (!r.ok) {
    const msg = (d && (d.detail || d.reason || d.message)) || ('HTTP ' + r.status)
    ElMessage.error(String(msg).slice(0, 200))
    const err = new Error(msg)
    err.status = r.status
    err.data = d
    throw err
  }
  return d
}

export const api = (path) => request('GET', path)
export const post = (path, payload) => request('POST', path, payload ?? {})
export const patch = (path, payload) => request('PATCH', path, payload ?? {})
export const put = (path, payload) => request('PUT', path, payload ?? {})
export const del = (path) => request('DELETE', path)
/** 文件上传：body 必须是 FormData（字段名/多文件见各调用处）。 */
export const upload = (path, fd) => request('POST', path, fd)
