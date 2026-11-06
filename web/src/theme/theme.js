/** 主题偏好。与 useColorMode({ storageKey: THEME_KEY }) 使用同一键和原文存储。 */

export const THEME_KEY = 'fnos_theme'
export const THEMES = ['light', 'dark', 'auto']

export function normalizeTheme(value) {
  const text = typeof value === 'string' ? value.trim() : ''
  return THEMES.includes(text) ? text : 'auto'
}

export function readTheme(storage) {
  if (!storage) return 'auto'
  return normalizeTheme(storage.getItem(THEME_KEY))
}

export function writeTheme(value, storage) {
  const next = normalizeTheme(value)
  storage.setItem(THEME_KEY, next)
  return next
}

export function resolvedTheme(pref, systemDark) {
  const mode = normalizeTheme(pref)
  if (mode === 'dark' || mode === 'light') return mode
  return systemDark ? 'dark' : 'light'
}

export function applyTheme(doc, storage, systemDark) {
  const pref = readTheme(storage)
  const resolved = resolvedTheme(pref, systemDark)
  doc.documentElement.setAttribute('data-theme', resolved)
  return { pref, resolved }
}
