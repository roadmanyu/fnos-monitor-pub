/** 趋势图滑动窗口：最近 3 分钟的真实采样，不补假点。 */
export const TREND_WINDOW_MS = 3 * 60 * 1000

export function pointTime(point) {
  if (point == null) return NaN
  if (Number.isFinite(point.t)) return point.t
  const parsed = Date.parse(point.ts)
  return Number.isFinite(parsed) ? parsed : NaN
}

export function mergeSeries(existing, incoming, now = Date.now(), windowMs = TREND_WINDOW_MS) {
  const map = new Map()
  for (const point of [...(existing || []), ...(incoming || [])]) {
    const t = pointTime(point)
    if (point?.value == null || point.value === '') continue
    const value = Number(point.value)
    if (!Number.isFinite(t) || !Number.isFinite(value)) continue
    map.set(t, { ts: point.ts || new Date(t).toISOString(), t, value })
  }
  const min = now - windowMs
  return [...map.values()]
    .filter((point) => point.t >= min && point.t <= now + 1500)
    .sort((a, b) => a.t - b.t)
}

export function mergeHist(base, extra, now = Date.now()) {
  const keys = ['cpu', 'mem', 'load', 'temp', 'up', 'down']
  const next = {}
  for (const key of keys) {
    next[key] = mergeSeries(base?.[key], extra?.[key], now)
  }
  return next
}

function usablePoints(points, nowMs, windowMs) {
  const start = nowMs - windowMs
  const rows = []
  for (const point of points || []) {
    const t = pointTime(point)
    if (point?.value == null || point.value === '') continue
    const value = Number(point.value)
    if (!Number.isFinite(t) || !Number.isFinite(value)) continue
    if (t < start || t > nowMs + 1500) continue
    rows.push({ t, value })
  }
  rows.sort((a, b) => a.t - b.t)
  return { start, rows }
}

export function linePathTimed(points, w, h, domainMax, nowMs, windowMs = TREND_WINDOW_MS) {
  const { start, rows } = usablePoints(points, nowMs, windowMs)
  if (rows.length < 2) return ''
  const max = domainMax > 0 ? domainMax : 1
  const yOf = (value) => h - (Math.max(0, Math.min(max, value)) / max) * (h - 10) - 4
  const xOf = (t) => Math.max(0, Math.min(w, ((t - start) / windowMs) * w))
  return rows
    .map((point, index) => `${index ? 'L' : 'M'}${xOf(point.t).toFixed(1)} ${yOf(point.value).toFixed(1)}`)
    .join(' ')
}

export function areaUnder(d, points, w, h, nowMs, windowMs = TREND_WINDOW_MS) {
  if (!d) return ''
  const { start, rows } = usablePoints(points, nowMs, windowMs)
  if (rows.length < 2) return ''
  const xOf = (t) => Math.max(0, Math.min(w, ((t - start) / windowMs) * w))
  const yBase = h - 4
  const x1 = xOf(rows[0].t)
  const x2 = xOf(rows[rows.length - 1].t)
  return `${d} L ${x2.toFixed(1)} ${yBase.toFixed(1)} L ${x1.toFixed(1)} ${yBase.toFixed(1)} Z`
}
