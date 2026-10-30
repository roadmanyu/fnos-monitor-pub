/** Display helpers. Values come from the API; missing data stays an em dash. */

export function formatPct(v, digits = 1) {
  const n = Number(v)
  if (v == null || v === '' || Number.isNaN(n)) return '—'
  return n.toFixed(digits)
}

export function clampPct(v) {
  const n = Number(v)
  if (Number.isNaN(n)) return 0
  return Math.min(100, Math.max(0, n))
}

export function formatBytes(n, digits = 1) {
  if (n == null || n === '' || Number.isNaN(Number(n))) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let v = Number(n)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  const d = i === 0 || v >= 100 ? 0 : digits
  return `${v.toFixed(d)} ${units[i]}`
}

/** Compact container memory, e.g. 300M / 1.2G. */
export function formatMemShort(n) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const v = Number(n)
  if (v >= 1024 ** 3) {
    const g = v / 1024 ** 3
    const text = g >= 10 ? g.toFixed(1) : g.toFixed(2)
    return `${text.replace(/\.?0+$/, '')}G`
  }
  if (v >= 1024 ** 2) return `${Math.round(v / 1024 ** 2)}M`
  if (v >= 1024) return `${Math.round(v / 1024)}K`
  return `${Math.round(v)}B`
}

export function formatClock(date, timeZone = 'Asia/Shanghai') {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23'
  }).format(date)
}

export function formatDateLine(date, timeZone = 'Asia/Shanghai') {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'long'
  }).formatToParts(date)
  const get = (type) => parts.find((p) => p.type === type)?.value || ''
  return `${get('year')}/${get('month')}/${get('day')} ${get('weekday')}`
}

export function formatTs(iso, timeZone = 'Asia/Shanghai') {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23'
  }).format(d)
}
