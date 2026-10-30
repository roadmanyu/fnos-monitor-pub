import { apiRoot, clearToken, getToken, setToken } from '../nas/profiles'

export { clearToken, getToken, setToken }

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${apiRoot()}${path}`, { ...options, headers })
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
