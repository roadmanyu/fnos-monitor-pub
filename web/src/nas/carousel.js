/** 多 NAS 轮播。纯函数，方便测间隔、暂停和空闲后续播。 */

export const DEFAULT_CAROUSEL = {
  enabled: false,
  intervalSec: 20,
  idleSec: 45,
  kiosk: false
}

export function clampInt(value, min, max, fallback) {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.min(max, Math.max(min, Math.round(number)))
}

export function normalizeCarousel(raw) {
  const src = raw && typeof raw === 'object' ? raw : {}
  return {
    enabled: !!src.enabled,
    intervalSec: clampInt(src.intervalSec, 5, 600, DEFAULT_CAROUSEL.intervalSec),
    idleSec: clampInt(src.idleSec, 5, 600, DEFAULT_CAROUSEL.idleSec),
    kiosk: !!src.kiosk
  }
}

export function nextProfileId(profiles, activeId) {
  if (!profiles || profiles.length < 2) return activeId || ''
  const index = profiles.findIndex((profile) => profile.id === activeId)
  const next = profiles[(index + 1) % profiles.length]
  return next?.id || profiles[0].id
}

/**
 * 暂停期间不切。空闲结束后从暂停结束的时刻再等满一个间隔，避免刚松手就跳走。
 */
export function shouldAdvance({ enabled, count, now, lastAdvanceAt, intervalMs, pausedUntil = 0 }) {
  if (!enabled || count < 2 || !(intervalMs > 0)) return false
  if (now < pausedUntil) return false
  const anchor = Math.max(Number(lastAdvanceAt) || 0, Number(pausedUntil) || 0)
  return now - anchor >= intervalMs
}

export function noteInteraction(now, idleMs) {
  return now + Math.max(0, idleMs)
}
