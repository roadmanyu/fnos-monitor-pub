const TOKEN_KEY = 'fnos_monitor_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`/api/v1${path}`, { ...options, headers })
  if (res.status === 401) {
    clearToken()
    if (!path.includes('/auth/login')) {
      window.location.hash = '#/login'
    }
  }
  const text = await res.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { message: text } }
  if (!res.ok) {
    const msg = data?.detail?.message || data?.message || res.statusText
    throw new Error(msg)
  }
  return data
}
