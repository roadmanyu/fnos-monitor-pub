/** 慢刷新：没到间隔就继续用上一份磁盘 / SMART 缓存。 */

export function shouldRefresh(lastAt, now, intervalMs, force) {
  if (force || lastAt == null) return true
  if (!(intervalMs > 0)) return true
  return now - lastAt >= intervalMs
}
