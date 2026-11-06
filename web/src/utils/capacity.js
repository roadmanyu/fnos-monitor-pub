/**
 * 存储容量的唯一口径。总览的存储池、硬盘卡和磁盘详情都走这里。
 * 与 backend/app/calibration.py 的 format_capacity 保持同一套单位和小数。
 *
 * unit:
 * - gib：1024，后缀 KiB/MiB/GiB/TiB
 * - gb：1000，后缀 KB/MB/GB/TB
 * - label：有厂商标称字节时按十进制显示，否则退回 GiB
 */

const UNITS_1024 = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
const UNITS_1000 = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

export function capacityPolicy(raw) {
  const unit = raw?.unit === 'gb' || raw?.unit === 'label' ? raw.unit : 'gib'
  let decimals = Number(raw?.decimals)
  if (!Number.isFinite(decimals)) decimals = 1
  decimals = Math.min(3, Math.max(0, Math.trunc(decimals)))
  return { unit, decimals }
}

function formatByBase(bytes, base, decimals, units) {
  let size = bytes
  let index = 0
  while (size >= base && index < units.length - 1) {
    size /= base
    index += 1
  }
  if (index === 0) return `${Math.round(size)} ${units[0]}`
  return `${size.toFixed(decimals)} ${units[index]}`
}

export function formatCapacity(bytes, policy, labelBytes = null) {
  const { unit, decimals } = capacityPolicy(policy)
  if (bytes == null || bytes === '' || Number.isNaN(Number(bytes))) return '—'
  const size = Number(bytes)
  if (!Number.isFinite(size) || size < 0) return '—'
  if (unit === 'label') {
    const advertised = Number(labelBytes)
    if (labelBytes != null && labelBytes !== '' && Number.isFinite(advertised) && advertised > 0) {
      return formatByBase(advertised, 1000, decimals, UNITS_1000)
    }
    return formatByBase(size, 1024, decimals, UNITS_1024)
  }
  if (unit === 'gb') return formatByBase(size, 1000, decimals, UNITS_1000)
  return formatByBase(size, 1024, decimals, UNITS_1024)
}
