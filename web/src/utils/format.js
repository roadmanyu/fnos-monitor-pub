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

/** Bytes per second, e.g. 12.4 KB/s. Returns null when the sample is missing. */
export function formatRate(bps) {
  if (bps == null || bps === '' || Number.isNaN(Number(bps))) return null
  const n = Number(bps)
  if (n < 1024) return `${n.toFixed(0)} B/s`
  if (n < 1024 * 1024) {
    const kb = n / 1024
    return `${kb.toFixed(kb >= 10 ? 0 : 1)} KB/s`
  }
  const mb = n / 1024 / 1024
  return `${mb.toFixed(mb >= 10 ? 1 : 2)} MB/s`
}

export function formatUptime(sec) {
  if (sec == null || Number.isNaN(Number(sec))) return null
  let s = Math.max(0, Math.floor(Number(sec)))
  const d = Math.floor(s / 86400)
  s %= 86400
  const h = Math.floor(s / 3600)
  s %= 3600
  const m = Math.floor(s / 60)
  if (d > 0) return `${d}天${h}小时`
  if (h > 0) return `${h}小时${m}分`
  return `${m}分`
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
