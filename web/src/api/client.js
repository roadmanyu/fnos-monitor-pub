import { apiRoot, clearToken, getToken, setToken } from '../nas/profiles'

export { clearToken, getToken, setToken }

export function isUnreachable(err) {
  if (!err) return false
  if (err.unreachable || err.name === 'AbortError') return true
  const msg = String(err.message || '')
  return msg === 'Failed to fetch' || msg === '无法连接' || msg.includes('NetworkError')
}

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const timeout = options.timeout
  const { timeout: _drop, ...rest } = options
  const ctrl = timeout ? new AbortController() : null
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeout) : null
  let res
  try {
    res = await fetch(`${apiRoot()}${path}`, { ...rest, headers, signal: rest.signal || ctrl?.signal })
  } catch (e) {
    const err = new Error('无法连接')
    err.unreachable = true
    err.cause = e
    throw err
  } finally {
    if (timer) clearTimeout(timer)
  }
  if (res.status === 401) {
    clearToken()
    if (!path.includes('/auth/login') && !location.pathname.startsWith('/login')) {
      location.assign('/login')
    }
  }
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { message: text } }
  if (!res.ok) {
    const detail = data?.detail
    const msg = (detail && typeof detail === 'object' ? detail.message : detail) || data?.message || res.statusText
    throw new Error(typeof msg === 'string' ? msg : res.statusText)
  }
  return data
}
