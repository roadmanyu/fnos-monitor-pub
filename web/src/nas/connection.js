/** 给另一台浏览器或平板扫码用的连接串。只含根地址，不含令牌。 */

export function connectionTarget(baseUrl, origin) {
  const base = String(baseUrl || '').trim().replace(/\/$/, '')
  if (base) return base
  return String(origin || '').trim().replace(/\/$/, '')
}
