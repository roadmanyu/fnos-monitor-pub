import { reactive } from 'vue'

const STORE_KEY = 'fnos_nas_profiles_v1'
const LEGACY_TOKEN = 'fnos_monitor_token'

function loadState() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || 'null')
    if (raw && Array.isArray(raw.profiles) && raw.profiles.length) {
      return {
        activeId: raw.activeId || raw.profiles[0].id,
        profiles: raw.profiles.map(normalizeProfile)
      }
    }
  } catch {
    /* keep default */
  }
  return {
    activeId: 'local',
    profiles: [{ id: 'local', name: '本机', baseUrl: '' }]
  }
}

function normalizeProfile(p) {
  return {
    id: String(p.id || 'local'),
    name: String(p.name || 'NAS').slice(0, 32),
    baseUrl: String(p.baseUrl || '').replace(/\/$/, '')
  }
}

const initial = loadState()
export const nas = reactive({
  activeId: initial.activeId,
  profiles: initial.profiles,
  tokenTick: 0
})

function persist() {
  localStorage.setItem(STORE_KEY, JSON.stringify({
    activeId: nas.activeId,
    profiles: nas.profiles
  }))
}

function tokenKey(id) {
  return `fnos_token_${id}`
}

if (localStorage.getItem(LEGACY_TOKEN) && !localStorage.getItem(tokenKey('local'))) {
  localStorage.setItem(tokenKey('local'), localStorage.getItem(LEGACY_TOKEN))
}

export function activeProfile() {
  return nas.profiles.find((p) => p.id === nas.activeId) || nas.profiles[0]
}

export function hasToken(id) {
  void nas.tokenTick
  return !!id && !!localStorage.getItem(tokenKey(id))
}

export function getToken() {
  return hasToken(activeProfile()?.id) ? localStorage.getItem(tokenKey(activeProfile().id)) : null
}

export function setToken(token, id = activeProfile()?.id) {
  if (!id) return
  localStorage.setItem(tokenKey(id), token)
  if (id === 'local') localStorage.setItem(LEGACY_TOKEN, token)
  nas.tokenTick += 1
}

export function clearToken(id = activeProfile()?.id) {
  if (!id) return
  localStorage.removeItem(tokenKey(id))
  if (id === 'local') localStorage.removeItem(LEGACY_TOKEN)
  nas.tokenTick += 1
}

export function setActive(id) {
  if (!nas.profiles.some((p) => p.id === id)) return
  nas.activeId = id
  persist()
}

export function upsertProfile(profile) {
  const next = normalizeProfile(profile)
  const idx = nas.profiles.findIndex((p) => p.id === next.id)
  if (idx >= 0) nas.profiles.splice(idx, 1, next)
  else nas.profiles.push(next)
  persist()
  return next
}

export function removeProfile(id) {
  if (id === 'local') return
  localStorage.removeItem(tokenKey(id))
  nas.tokenTick += 1
  nas.profiles = nas.profiles.filter((p) => p.id !== id)
  if (nas.activeId === id) nas.activeId = nas.profiles[0]?.id || 'local'
  persist()
}

/** http(s) origin, optional path prefix, no trailing slash. */
export function normalizeBaseUrl(raw) {
  const u = new URL(String(raw || '').trim())
  if (u.protocol !== 'http:' && u.protocol !== 'https:') {
    throw new Error('仅支持 http 或 https')
  }
  const path = u.pathname.replace(/\/$/, '')
  return u.origin + (path && path !== '/' ? path : '')
}

export function apiRoot(profile = activeProfile()) {
  const base = (profile?.baseUrl || '').replace(/\/$/, '')
  return base ? `${base}/api/v1` : '/api/v1'
}

export function rememberLocalName(hostname) {
  if (!hostname) return
  const local = nas.profiles.find((p) => p.id === 'local')
  if (local && (local.name === '本机' || !local.name)) {
    local.name = String(hostname).slice(0, 32)
    persist()
  }
}
