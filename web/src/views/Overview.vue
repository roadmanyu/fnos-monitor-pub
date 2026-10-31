<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client'
import { activeProfile, nas, rememberLocalName } from '../nas/profiles'
import Alerts from './Alerts.vue'
import Disks from './Disks.vue'
import Docker from './Docker.vue'
import {
  clampPct,
  formatBytes,
  formatClock,
  formatDateLine,
  formatMemShort,
  formatPct,
  formatRate,
  formatTs,
  formatUptime
} from '../utils/format'

const snap = ref(null)
const meta = ref(null)
const hist = ref({ cpu: [], mem: [], load: [], temp: [], up: [], down: [] })
const route = useRoute()
const diskOpen = ref(false)
const dockerOpen = ref(false)
const alertOpen = ref(false)
const alerts = ref([])
const containers = ref([])
const err = ref('')
const now = ref(new Date())
const tempsOpen = ref(false)
const topMetric = ref('cpu')
const seriesOn = reactive({ cpu: true, mem: true })
const trendMode = ref('percent')
let poll
let pollDelay = 0
let clock

const tz = computed(() => meta.value?.timezone_display || 'Asia/Shanghai')
const host = computed(() => snap.value?.host || {})
const filesystems = computed(() => {
  return [...(snap.value?.filesystems || [])].sort(
    (a, b) => (Number(b.used_pct) || 0) - (Number(a.used_pct) || 0)
  )
})
const disks = computed(() => snap.value?.disks_smart_summary || [])
const cpuTemp = computed(() => host.value?.temps_c?.cpu ?? null)
const cores = computed(() => {
  const raw = host.value?.cpu_cores
  if (!Array.isArray(raw)) return []
  return raw.map((c) => {
    if (c != null && typeof c === 'object') {
      return {
        pct: c.pct == null ? null : Number(c.pct),
        freq: c.freq_mhz == null ? null : Number(c.freq_mhz),
        freqMax: c.freq_max_mhz == null ? null : Number(c.freq_max_mhz),
        temp: c.temp_c == null ? null : Number(c.temp_c)
      }
    }
    const n = Number(c)
    return { pct: Number.isNaN(n) ? null : n, freq: null, freqMax: null, temp: null }
  })
})
const deskLayout = ref(false)
const uptimeText = computed(() => formatUptime(host.value?.uptime_sec))
const heroName = computed(() => activeProfile()?.name || meta.value?.hostname || '—')
const heroHost = computed(() => {
  const tab = activeProfile()?.name
  const hostName = meta.value?.hostname
  if (tab && hostName && tab !== hostName) return hostName
  return ''
})
const hostStatus = computed(() => {
  if (!snap.value?.ts) return { text: '离线', cls: 'muted' }
  if (meta.value?.mock_mode) return { text: '模拟数据', cls: 'warn' }
  if (collectStale.value) return { text: '采集延迟', cls: 'warn' }
  return { text: '在线', cls: 'ok' }
})
const swapKnown = computed(() => host.value?.swap_total_bytes != null)
const netKnown = computed(() => host.value && Object.prototype.hasOwnProperty.call(host.value, 'net_up_bps'))
const diskIoText = computed(() => {
  const h = host.value || {}
  if (!Object.prototype.hasOwnProperty.call(h, 'disk_read_bps')) return ''
  const read = formatRate(h.disk_read_bps)
  const write = formatRate(h.disk_write_bps)
  if (!read && !write) return '读写 采集中'
  return `读 ${read || '—'} · 写 ${write || '—'}`
})
const netTrend = computed(() => {
  const up = (hist.value.up || []).map((p) => Number(p.value)).filter((v) => !Number.isNaN(v))
  const down = (hist.value.down || []).map((p) => Number(p.value)).filter((v) => !Number.isNaN(v))
  const peak = Math.max(1, ...up, ...down)
  const upPath = up.length >= 2 ? linePath(up, 320, 80, peak) : ''
  const downPath = down.length >= 2 ? linePath(down, 320, 80, peak) : ''
  return { has: !!(upPath || downPath), up: upPath, down: downPath }
})

const netPace = computed(() => {
  if (!netKnown.value) return null
  const up = host.value?.net_up_bps
  const down = host.value?.net_down_bps
  if (up == null && down == null) return null
  const sum = (Number(up) || 0) + (Number(down) || 0)
  return sum >= 2048 ? '传输中' : '空闲'
})

const netChartText = computed(() => {
  if (!netKnown.value) return '暂无网速'
  if (!netTrend.value.has) return '采集中'
  return ''
})

const clockText = computed(() => formatClock(now.value, tz.value))
const dateText = computed(() => formatDateLine(now.value, tz.value))

const freqScale = computed(() => {
  const maxes = cores.value.map((c) => Number(c.freqMax)).filter((n) => n > 0)
  if (maxes.length) return Math.max(...maxes)
  const curs = cores.value.map((c) => Number(c.freq)).filter((n) => n > 0)
  return curs.length ? Math.max(...curs) : null
})

const coreGrid = computed(() => {
  const n = cores.value.length
  if (!n) return { cols: 1, rows: 1 }
  const cols = deskLayout.value
    ? (n <= 4 ? n : n <= 6 ? 3 : n <= 12 ? 4 : Math.min(6, Math.ceil(Math.sqrt(n))))
    : Math.min(2, n)
  return { cols, rows: Math.ceil(n / cols) }
})

const tempState = computed(() => {
  const t = cpuTemp.value
  if (t == null) return null
  if (Number(t) >= 85) return { text: '温度偏高', cls: 'warn' }
  if (Number(t) >= 70) return { text: '温度偏暖', cls: 'warn' }
  return { text: '温度正常', cls: 'ok' }
})

const loadState = computed(() => {
  if (!snap.value?.ts) return null
  const cpu = Number(host.value?.cpu_pct)
  const mem = Number(host.value?.mem_used_pct)
  const swap = Number(host.value?.swap_used_pct)
  const hasCpu = !Number.isNaN(cpu)
  const hasMem = !Number.isNaN(mem)
  const hasSwap = Number(host.value?.swap_total_bytes) > 0 && !Number.isNaN(swap)
  if (!hasCpu && !hasMem && !hasSwap) return null
  if ((hasCpu && cpu >= 90) || (hasMem && mem >= 90) || (hasSwap && swap >= 90)) {
    return { text: '负载偏高', cls: 'warn' }
  }
  return { text: '负载正常', cls: 'ok' }
})

function usageTone(pct) {
  const n = Number(pct)
  if (Number.isNaN(n)) return ''
  if (n >= 90) return 'hot'
  if (n >= 70) return 'warm'
  return ''
}

function ctrMemPct(c) {
  const used = Number(c?.mem_usage_bytes)
  const limit = Number(c?.mem_limit_bytes)
  if (!Number.isFinite(used) || !Number.isFinite(limit) || limit <= 0) return 0
  return clampPct((used / limit) * 100)
}

const coreCount = computed(() => {
  const n = host.value?.cpu_cores?.length
  return n > 0 ? n : 1
})

const loadBarPct = computed(() => {
  const load = Number(host.value?.load1)
  if (Number.isNaN(load)) return 0
  return clampPct((load / coreCount.value) * 100)
})

const powerBarPct = computed(() => {
  const watts = Number(host.value?.power_watts)
  const rated = Number(meta.value?.power_rated_watts)
  if (!Number.isFinite(watts) || !Number.isFinite(rated) || rated <= 0) return 0
  return clampPct((watts / rated) * 100)
})

const diskSumBps = computed(() => {
  const read = host.value?.disk_read_bps
  const write = host.value?.disk_write_bps
  if (read == null && write == null) return null
  return (Number(read) || 0) + (Number(write) || 0)
})

const diskBarPct = computed(() => {
  const sum = diskSumBps.value
  if (sum == null) return 0
  const cap = Number(meta.value?.disk_bps_cap)
  const peak = Number(host.value?.disk_bps_peak)
  const denom = cap > 0 ? cap : Math.max(peak || 0, sum, 1)
  return clampPct((sum / denom) * 100)
})

const diskTotalText = computed(() => {
  const text = formatRate(diskSumBps.value)
  return text || (diskSumBps.value == null ? '采集中' : '—')
})

const diskSplitText = computed(() => {
  const read = formatRate(host.value?.disk_read_bps)
  const write = formatRate(host.value?.disk_write_bps)
  if (!read && !write) return ''
  return `读 ${read || '—'} · 写 ${write || '—'}`
})

const dockerSummary = computed(() => {
  const d = snap.value?.docker || {}
  return {
    running: Number(d.running) || 0,
    stopped: Number(d.stopped) || 0,
    total: Number(d.total) || 0
  }
})

const dockerDown = computed(() => {
  const d = snap.value?.docker
  if (d && d.stopped != null) return Number(d.stopped) || 0
  return containers.value.filter((c) => (c.state || '').toLowerCase() !== 'running').length
})

const topContainers = computed(() => {
  const ranked = [...containers.value].sort((a, b) => {
    if (topMetric.value === 'mem') {
      return (Number(b.mem_usage_bytes) || -1) - (Number(a.mem_usage_bytes) || -1)
    }
    return (Number(b.cpu_pct) || -1) - (Number(a.cpu_pct) || -1)
  })
  return ranked.slice(0, 16).map((c, i) => ({
    ...c,
    rank: i + 1,
    hot: Number(c.cpu_pct) >= 50
  }))
})

const dockerCols = computed(() => {
  const items = topContainers.value
  if (!items.length) return []
  const leftCount = Math.min(8, Math.ceil(items.length / 2))
  const left = items.slice(0, leftCount)
  const right = items.slice(leftCount, 16)
  return right.length ? [left, right] : [left]
})

const recentAlerts = computed(() => alerts.value.slice(0, 5))

const unackedCount = computed(() => alerts.value.filter((a) => !a.acked).length)

const diskRollup = computed(() => {
  let ok = 0
  let fail = 0
  let standby = 0
  let hot = null
  for (const d of disks.value) {
    if (d.skipped_standby) standby += 1
    else if (d.healthy === false) fail += 1
    else if (d.healthy === true) ok += 1
    if (d.temp_c != null && !Number.isNaN(Number(d.temp_c))) {
      const t = Number(d.temp_c)
      if (hot == null || t > hot) hot = t
    }
  }
  return { ok, fail, standby, hot }
})

const smartFail = computed(() => diskRollup.value.fail)

const otherTemps = computed(() => {
  const other = host.value?.temps_c?.other
  if (!other || typeof other !== 'object') return []
  return Object.entries(other)
    .filter(([, v]) => v != null && !Number.isNaN(Number(v)))
    .map(([key, value]) => ({ key, value }))
    .sort((a, b) => a.key.localeCompare(b.key))
})

const ageSec = computed(() => {
  const iso = meta.value?.last_collect_ts || snap.value?.ts
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  return Math.max(0, Math.floor((now.value.getTime() - t) / 1000))
})

const intervalSec = computed(() => {
  const n = Number(meta.value?.collect_interval_sec)
  return Number.isFinite(n) && n > 0 ? n : 2
})

const collectStale = computed(() => {
  if (ageSec.value == null) return false
  return ageSec.value > intervalSec.value * 2
})

const cadenceText = computed(() => `每 ${intervalSec.value} 秒`)

const healthReady = computed(() => !!snap.value?.ts)

const pwmDraft = ref(55)
const pwmHold = ref(false)
const fanBusy = ref(false)
const fanMsg = ref('')
const fanItems = computed(() => (Array.isArray(snap.value?.fans) ? snap.value.fans : []))
const fanControl = computed(() => snap.value?.control || 'off')
const fanWritable = computed(() => fanControl.value === 'ready' && fanItems.value.some((f) => f.controllable))
const fanSlots = computed(() => {
  if (fanItems.value.length) return fanItems.value
  return [
    { id: 'placeholder-cpu', label: 'CPU', rpm: null, mode: 'unknown', pwm_percent: null },
    { id: 'placeholder-case', label: '机箱', rpm: null, mode: 'unknown', pwm_percent: null }
  ]
})
const fanCols = computed(() => {
  const n = fanSlots.value.length
  if (n <= 1) return 1
  if (!deskLayout.value) return Math.min(2, n)
  if (n <= 2) return n
  return n <= 4 ? 2 : 3
})
const fanPill = computed(() => {
  if (!fanItems.value.length) return '暂无'
  if (fanControl.value === 'ready') return `${fanItems.value.length} 路`
  return '只读'
})
const fanMode = computed(() => {
  const modes = fanItems.value.map((f) => f.mode).filter(Boolean)
  if (!modes.length || modes.some((m) => m !== modes[0])) return ''
  return modes[0]
})
const fanPreset = computed(() => {
  if (fanMode.value !== 'manual') return ''
  const known = fanItems.value.find((f) => f.pwm_percent != null)
  if (!known) return ''
  const value = Number(known.pwm_percent)
  if (Math.abs(value - 30) <= 2) return 'silent'
  if (Math.abs(value - 55) <= 2) return 'normal'
  if (Math.abs(value - 85) <= 2) return 'performance'
  return ''
})

const trend = computed(() => buildTrend(hist.value, seriesOn, trendMode.value))

function selectTrend(key) {
  if (key === 'load' || key === 'temp') {
    trendMode.value = trendMode.value === key ? 'percent' : key
    return
  }
  if (trendMode.value !== 'percent') trendMode.value = 'percent'
  seriesOn[key] = !seriesOn[key]
}

const trendCaption = computed(() => {
  if (trendMode.value === 'load') return '负载，按本段峰值'
  if (trendMode.value === 'temp') return '温度 °C'
  return ''
})

async function load() {
  try {
    const [m, s, a] = await Promise.all([
      api('/meta'),
      api('/metrics/snapshot'),
      api('/alerts?limit=200').then((r) => r.items || [])
    ])
    meta.value = m
    snap.value = s
    alerts.value = a
    rememberLocalName(m?.hostname)
    err.value = ''
    armPoll()
  } catch (e) {
    err.value = e.message || '加载失败'
  }
  const [cpu, mem, load, temp, up, down, dock] = await Promise.all([
    safeHist('cpu.pct'),
    safeHist('mem.used_pct'),
    safeHist('load1'),
    safeHist('temp.cpu'),
    safeHist('net.up_bps'),
    safeHist('net.down_bps'),
    safeJson('/docker/containers')
  ])
  hist.value = {
    cpu: cpu ?? hist.value.cpu,
    mem: mem ?? hist.value.mem,
    load: load ?? hist.value.load,
    temp: temp ?? hist.value.temp,
    up: up ?? hist.value.up,
    down: down ?? hist.value.down
  }
  if (dock) containers.value = dock.containers || []
}

async function safeHist(metric) {
  try {
    const r = await api(`/metrics/history?metric=${encodeURIComponent(metric)}&step=60`)
    return r.points || []
  } catch {
    return null
  }
}

async function safeJson(path) {
  try {
    return await api(path)
  } catch {
    return null
  }
}

function poolName(mount) {
  if (mount === '/') return '系统盘'
  return mount || '—'
}

function barColor(pct) {
  const n = Number(pct)
  if (Number.isNaN(n)) return 'teal'
  if (n >= 95) return 'crit'
  if (n >= 85) return 'warn'
  return 'teal'
}

function diskHealth(d) {
  if (d.skipped_standby) return { label: 'STANDBY', cls: 'muted' }
  if (d.healthy === false) return { label: 'FAIL', cls: 'bad' }
  if (d.healthy === true) return { label: 'OK', cls: 'ok' }
  return { label: '—', cls: 'muted' }
}

function ctrDot(state) {
  const s = (state || '').toLowerCase()
  if (s === 'running') return 'run'
  if (s === 'exited' || s === 'dead') return 'stop'
  return ''
}

function resetView() {
  snap.value = null
  meta.value = null
  alerts.value = []
  containers.value = []
  hist.value = { cpu: [], mem: [], load: [], temp: [], up: [], down: [] }
}

async function openDrawer(id) {
  await nextTick()
  const el = document.getElementById(id)
  if (!el) return
  el.open = true
  if (!window.matchMedia('(max-width: 720px)').matches) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function syncSheet() {
  const open = diskOpen.value || dockerOpen.value || alertOpen.value
  const narrow = window.matchMedia('(max-width: 720px)').matches
  document.body.classList.toggle('sheet-open', open && narrow)
}

function onDrawerToggle(e) {
  const el = e.target
  if (el.id === 'disk-detail') diskOpen.value = el.open
  if (el.id === 'docker-detail') dockerOpen.value = el.open
  if (el.id === 'alert-detail') alertOpen.value = el.open
  syncSheet()
}

function armPoll() {
  const ms = intervalSec.value * 1000
  if (poll && pollDelay === ms) return
  pollDelay = ms
  clearInterval(poll)
  poll = setInterval(load, ms)
}

function rateLabel(value, known) {
  if (!known) return '—'
  return formatRate(value) || '采集中'
}

function syncDeskLayout() {
  deskLayout.value = window.matchMedia('(min-width: 1200px)').matches
}

onMounted(() => {
  syncDeskLayout()
  window.addEventListener('resize', syncDeskLayout)
  load()
  armPoll()
  clock = setInterval(() => { now.value = new Date() }, 1000)
  if (route.hash) openDrawer(route.hash.slice(1))
})
watch(() => nas.activeId, () => {
  resetView()
  load()
})
watch(() => route.hash, (hash) => {
  if (hash) openDrawer(hash.slice(1))
})
watch(fanItems, (items) => {
  if (pwmHold.value) return
  const known = items.find((f) => f.pwm_percent != null)
  if (known) pwmDraft.value = Math.max(25, Number(known.pwm_percent))
})
onUnmounted(() => {
  clearInterval(poll)
  clearInterval(clock)
  window.removeEventListener('resize', syncDeskLayout)
  document.body.classList.remove('sheet-open')
})

function ringArc(r, frac) {
  const c = 2 * Math.PI * r
  const f = frac == null || Number.isNaN(Number(frac)) ? 0 : Math.min(1, Math.max(0, Number(frac)))
  return { dash: `${c.toFixed(2)} ${c.toFixed(2)}`, offset: (c * (1 - f)).toFixed(2) }
}

function coreArcs(core) {
  const scale = freqScale.value
  const freq = core.freq == null || !scale ? null : Number(core.freq) / scale
  const temp = core.temp == null ? null : Number(core.temp) / 100
  const pct = core.pct == null ? null : clampPct(core.pct) / 100
  return {
    temp: ringArc(48, temp),
    use: ringArc(36, pct),
    freq: ringArc(24, freq)
  }
}

function corePctText(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return `${Math.round(Number(v))}%`
}

function coreFreqText(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  if (n >= 1000) {
    const g = n / 1000
    const digits = g >= 10 ? 0 : 1
    return `${g.toFixed(digits).replace(/\.0$/, '')}G`
  }
  return `${Math.round(n)}M`
}

function coreTempText(v) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return `${Math.round(Number(v))}°`
}

function fanTone(label, index) {
  if (label === 'CPU') return 'cpu'
  if (label === '机箱') return 'case'
  return index % 2 === 0 ? 'cpu' : 'case'
}

function fanReasonText(code) {
  const map = {
    control_disabled: '调速未开启',
    not_writable: '系统未提供可写转速',
    readback_mismatch: '写入后被系统改回，已停用调速',
    mock: '模拟数据，不能调速',
    below_floor: '低于最低转速'
  }
  return map[code] || ''
}

async function postFan(path, body) {
  fanBusy.value = true
  fanMsg.value = ''
  try {
    await api(path, { method: 'POST', body: JSON.stringify(body) })
  } catch (e) {
    fanMsg.value = e.message || '调速失败'
  } finally {
    fanBusy.value = false
    pwmHold.value = false
    await load()
  }
}

async function setFanMode(mode) {
  if (!fanWritable.value || fanBusy.value) return
  const ids = fanItems.value.filter((f) => f.controllable).map((f) => f.id)
  for (const id of ids) {
    await postFan(`/fans/${encodeURIComponent(id)}/mode`, { mode })
  }
}

async function setFanPwm() {
  if (!fanWritable.value || fanBusy.value) return
  const percent = Math.round(Number(pwmDraft.value))
  const ids = fanItems.value.filter((f) => f.controllable).map((f) => f.id)
  for (const id of ids) {
    await postFan(`/fans/${encodeURIComponent(id)}/pwm`, { percent })
  }
}

async function setFanPreset(preset) {
  if (!fanWritable.value || fanBusy.value) return
  await postFan('/fans/preset', { preset })
}

const TREND_DRAW = {
  cpu: { color: '#2ec9c0' },
  mem: { color: '#f062b0' },
  load: { color: '#f5b14a' },
  temp: { color: '#f08a3a' }
}

function buildTrend(series, enabled, mode) {
  const w = 640
  const h = 240
  const keys = mode === 'load' ? ['load'] : mode === 'temp' ? ['temp'] : ['cpu', 'mem'].filter((key) => enabled[key])
  const paths = []
  for (const key of keys) {
    const values = (series[key] || [])
      .map((p) => Number(p.value))
      .filter((v) => !Number.isNaN(v))
    if (values.length < 2) continue
    const domain = trendDomain(key, values)
    const d = linePath(values, w, h, domain)
    if (d) paths.push({ key, color: TREND_DRAW[key].color, d, domain })
  }
  const first = paths[0]
  return {
    has: paths.length > 0,
    paths,
    domain: first?.domain ?? 100,
    area: mode === 'percent' && first ? `${first.d} L ${w} ${h} L 0 ${h} Z` : '',
    areaColor: first?.color || '#2ec9c0'
  }
}

function trendDomain(key, values) {
  const peak = values.reduce((m, v) => Math.max(m, v), 0)
  if (key === 'cpu' || key === 'mem') return 100
  if (key === 'load') return Math.max(1, peak * 1.25)
  return Math.max(100, peak)
}

function linePath(values, w, h, domainMax) {
  const n = values.length
  const max = domainMax > 0 ? domainMax : 1
  const yOf = (v) => h - (Math.max(0, Math.min(max, v)) / max) * (h - 10) - 4
  if (!n || n < 2) return ''
  return values
    .map((v, i) => {
      const x = (i / (n - 1)) * w
      return `${i ? 'L' : 'M'}${x.toFixed(1)} ${yOf(v).toFixed(1)}`
    })
    .join(' ')
}
</script>

<template>
  <div class="page dash">
    <p v-if="err" class="err-banner">{{ err }}</p>
    <p v-else-if="!snap" class="muted">正在加载…</p>

    <div class="modules">
      <section class="card mod span-12 id-card">
        <header class="mod-head">
          <span class="mid">M01</span>
          <span class="mod-title">系统</span>
          <span class="pill head-pill push" :class="hostStatus.cls">
            <i class="dot"></i>{{ hostStatus.text }}
          </span>
        </header>
        <div class="id-body">
        <div class="id-lead">
        <div class="id-hero">
          <div class="id-name">{{ heroName }}</div>
          <div v-if="heroHost" class="id-host">{{ heroHost }}</div>
          <div class="id-fresh">{{ cadenceText }}</div>
        </div>
        <div class="id-clock">
          <span class="id-time">{{ clockText }}</span>
          <span>{{ dateText }}</span>
        </div>
        </div>
        <div class="facts">
          <div class="fact">
            <span>系统</span>
            <b class="clip">{{ host.os || '—' }}<template v-if="host.arch"> · {{ host.arch }}</template></b>
          </div>
          <div class="fact">
            <span>CPU</span>
            <b class="clip" :title="host.cpu_model || ''">{{ host.cpu_model || '—' }}</b>
          </div>
          <div class="fact">
            <span>运行</span>
            <b>{{ uptimeText || '—' }}</b>
          </div>
          <div class="fact">
            <span>局域网</span>
            <b>{{ host.lan_ipv4 || '—' }}</b>
          </div>
          <div class="fact">
            <span>公网</span>
            <b>{{ host.public_ipv4 || '—' }}</b>
          </div>
          <div class="fact">
            <span>GPU</span>
            <b class="clip" :title="host.gpu_model || ''">{{ host.gpu_model || '—' }}</b>
          </div>
        </div>
        </div>
        <div class="id-ver">v{{ meta?.app_version || '—' }}</div>
      </section>

      <section class="card mod span-12 res-card">
        <header class="mod-head">
          <span class="mid">M02</span>
          <span class="mod-title">资源</span>
          <span v-if="loadState" class="pill head-pill push" :class="loadState.cls">
            <i class="dot"></i>{{ loadState.text }}
          </span>
        </header>
        <div class="metric">
          <div class="metric-top">
            <span>CPU</span>
            <b>{{ formatPct(host.cpu_pct) }}%</b>
          </div>
          <div class="seg cpu" :class="usageTone(host.cpu_pct)" :style="{ '--p': clampPct(host.cpu_pct) + '%' }"></div>
        </div>
        <div class="metric">
          <div class="metric-top">
            <span>内存</span>
            <b>{{ formatBytes(host.mem_used_bytes) }} / {{ formatBytes(host.mem_total_bytes) }} <em>{{ formatPct(host.mem_used_pct, 0) }}%</em></b>
          </div>
          <div class="seg mem" :class="usageTone(host.mem_used_pct)" :style="{ '--p': clampPct(host.mem_used_pct) + '%' }"></div>
        </div>
        <div class="metric">
          <div class="metric-top">
            <span>交换</span>
            <b v-if="swapKnown && host.swap_total_bytes > 0">
              {{ formatBytes(host.swap_used_bytes) }} / {{ formatBytes(host.swap_total_bytes) }}
              <em class="swap-em">{{ formatPct(host.swap_used_pct, 0) }}%</em>
            </b>
            <b v-else-if="swapKnown" class="na">无交换分区</b>
            <b v-else class="na">—</b>
          </div>
          <div class="seg swap" :class="usageTone(host.swap_total_bytes > 0 ? host.swap_used_pct : 0)" :style="{ '--p': (swapKnown && host.swap_total_bytes > 0 ? clampPct(host.swap_used_pct) : 0) + '%' }"></div>
        </div>
        <div class="metric">
          <div class="metric-top">
            <span>功耗 <i v-if="host.power_source === 'rapl'" class="est">估算</i></span>
            <b v-if="host.power_watts != null">{{ host.power_watts }} W<em v-if="powerBarPct > 0"> {{ formatPct(powerBarPct, 0) }}%</em></b>
            <b v-else class="na">—</b>
          </div>
          <div class="seg power" :class="usageTone(powerBarPct)" :style="{ '--p': powerBarPct + '%' }"></div>
        </div>
        <div class="metric">
          <div class="metric-top">
            <span>负载</span>
            <b>{{ host.load1 ?? '—' }}<em v-if="host.load1 != null"> {{ formatPct(loadBarPct, 0) }}%</em></b>
          </div>
          <div class="seg loadbar" :class="usageTone(loadBarPct)" :style="{ '--p': loadBarPct + '%' }"></div>
        </div>
        <div class="metric">
          <div class="metric-top">
            <span>磁盘</span>
            <b>{{ diskTotalText }}<em v-if="diskSplitText" class="sub"> {{ diskSplitText }}</em></b>
          </div>
          <div class="seg diskbar" :style="{ '--p': diskBarPct + '%' }"></div>
        </div>
      </section>

      <section class="card mod span-12 trend-card">
        <header class="mod-head">
          <span class="mid">M03</span>
          <span class="mod-title">趋势</span>
          <span class="pill muted head-pill push">近 1 小时</span>
        </header>
        <div v-if="trend.has" class="trend-plot">
          <div v-if="trendMode === 'percent'" class="y-axis" aria-hidden="true">
            <span>100</span>
            <span>0</span>
          </div>
          <svg viewBox="0 0 640 240" class="trend" preserveAspectRatio="none">
            <line x1="0" y1="8" x2="640" y2="8" stroke="#eef1f4" />
            <line x1="0" y1="120" x2="640" y2="120" stroke="#eef1f4" />
            <line x1="0" y1="232" x2="640" y2="232" stroke="#eef1f4" />
            <path v-if="trend.area" :d="trend.area" :fill="trend.areaColor" fill-opacity="0.16" stroke="none" />
            <path
              v-for="p in trend.paths"
              :key="p.key"
              :d="p.d"
              fill="none"
              :stroke="p.color"
              stroke-width="6"
              stroke-linecap="round"
              stroke-linejoin="round"
              vector-effect="non-scaling-stroke"
            />
          </svg>
        </div>
        <div v-else class="trend-empty">暂无趋势</div>
        <div class="x-axis">
          <span>1 小时前</span>
          <span>现在</span>
        </div>
        <p v-if="trendCaption" class="trend-caption">{{ trendCaption }}</p>
        <div class="legend">
          <button type="button" class="chip" :class="{ on: trendMode === 'percent' && seriesOn.cpu }" @click="selectTrend('cpu')">
            <i class="swatch cpu"></i>CPU {{ formatPct(host.cpu_pct) }}%
          </button>
          <button type="button" class="chip" :class="{ on: trendMode === 'percent' && seriesOn.mem }" @click="selectTrend('mem')">
            <i class="swatch mem"></i>内存 {{ formatPct(host.mem_used_pct) }}%
          </button>
          <button type="button" class="chip" :class="{ on: trendMode === 'load' }" @click="selectTrend('load')">
            <i class="swatch load"></i>负载 {{ host.load1 ?? '—' }}
          </button>
          <button type="button" class="chip" :class="{ on: trendMode === 'temp' }" @click="selectTrend('temp')">
            <i class="swatch temp"></i>温度 {{ cpuTemp != null ? cpuTemp + '°C' : '—' }}
          </button>
        </div>
      </section>

      <section class="card mod span-3 net-card">
        <header class="mod-head">
          <span class="mid">M04</span>
          <span class="mod-title">网络</span>
          <span v-if="netPace" class="pill head-pill push" :class="netPace === '传输中' ? 'ok' : 'muted'">
            <i class="dot"></i>{{ netPace }}
          </span>
        </header>
        <div class="net-stats">
          <div>
            <div class="k"><i class="swatch up"></i>上传</div>
            <div class="net-v">{{ rateLabel(host.net_up_bps, netKnown) }}</div>
          </div>
          <div>
            <div class="k"><i class="swatch down"></i>下载</div>
            <div class="net-v">{{ rateLabel(host.net_down_bps, netKnown) }}</div>
          </div>
        </div>
        <div class="net-plot">
          <svg v-if="netTrend.has" viewBox="0 0 320 80" class="net-svg" preserveAspectRatio="none">
            <path :d="netTrend.down" fill="none" stroke="#8b7cf6" stroke-width="4" stroke-linecap="round" vector-effect="non-scaling-stroke" />
            <path :d="netTrend.up" fill="none" stroke="#5b8def" stroke-width="4" stroke-linecap="round" vector-effect="non-scaling-stroke" />
          </svg>
          <div v-else class="net-empty">{{ netChartText }}</div>
          <div class="x-axis net-axis">
            <span>更早</span>
            <span>现在</span>
          </div>
        </div>
      </section>

      <section class="card mod span-4 cpu-card">
        <header class="mod-head">
          <span class="mid">M05</span>
          <span class="mod-title">CPU</span>
          <div class="head-right">
            <span v-if="host.cpu_pct != null" class="cpu-sum">整机 {{ formatPct(host.cpu_pct, 0) }}%</span>
            <button v-if="otherTemps.length" type="button" class="fold" @click="tempsOpen = true">
              其它 {{ otherTemps.length }}
            </button>
            <span v-if="tempState" class="pill head-pill" :class="tempState.cls">
              <i class="dot"></i>{{ tempState.text }}
            </span>
          </div>
        </header>
        <div v-if="cores.length" class="core-grid" :style="{
          gridTemplateColumns: `repeat(${coreGrid.cols}, minmax(0, 1fr))`,
          gridTemplateRows: deskLayout ? `repeat(${coreGrid.rows}, minmax(0, 1fr))` : 'auto'
        }">
          <article v-for="(core, i) in cores" :key="i" class="core-unit">
            <div class="ring-wrap">
              <svg viewBox="0 0 120 120" class="core-svg" :aria-label="'核 ' + i">
                <g fill="none" stroke-linecap="round" transform="rotate(-90 60 60)">
                  <circle cx="60" cy="60" r="48" stroke="#f6e7da" stroke-width="9" />
                  <circle cx="60" cy="60" r="48" stroke="#f08a3a" stroke-width="9" :stroke-dasharray="coreArcs(core).temp.dash" :stroke-dashoffset="coreArcs(core).temp.offset" />
                  <circle cx="60" cy="60" r="36" stroke="#e4ebf8" stroke-width="9" />
                  <circle cx="60" cy="60" r="36" stroke="#5b8def" stroke-width="9" :stroke-dasharray="coreArcs(core).use.dash" :stroke-dashoffset="coreArcs(core).use.offset" />
                  <circle cx="60" cy="60" r="24" stroke="#e3f6f4" stroke-width="9" />
                  <circle cx="60" cy="60" r="24" stroke="#2ec9c0" stroke-width="9" :stroke-dasharray="coreArcs(core).freq.dash" :stroke-dashoffset="coreArcs(core).freq.offset" />
                </g>
              </svg>
              <span class="ring-name">核{{ i }}</span>
            </div>
            <p class="core-line">
              <b class="use">{{ corePctText(core.pct) }}</b>
              <b class="hz">{{ coreFreqText(core.freq) }}</b>
            </p>
            <p class="core-line deg" :class="{ miss: core.temp == null }">{{ coreTempText(core.temp) }}</p>
          </article>
        </div>
        <div v-else class="net-empty">暂无 CPU</div>
      </section>

      <section class="card mod span-3 fan-card">
        <header class="mod-head">
          <span class="mid">M06</span>
          <span class="mod-title">风扇</span>
          <span class="pill head-pill push" :class="fanControl === 'ready' ? 'ok' : 'muted'">
            <i class="dot"></i>{{ fanPill }}
          </span>
        </header>
        <div class="fan-stage">
          <div
            class="fan-grid"
            :style="{ gridTemplateColumns: `repeat(${fanCols}, minmax(0, 1fr))` }"
          >
            <article v-for="(fan, i) in fanSlots" :key="fan.id" class="fan-unit">
              <svg viewBox="0 0 64 64" class="fan-svg" :class="fanTone(fan.label, i)" aria-hidden="true">
                <circle cx="32" cy="32" r="28" fill="currentColor" opacity="0.14" />
                <g fill="currentColor">
                  <ellipse cx="32" cy="16" rx="7" ry="12" />
                  <ellipse cx="32" cy="16" rx="7" ry="12" transform="rotate(120 32 32)" />
                  <ellipse cx="32" cy="16" rx="7" ry="12" transform="rotate(240 32 32)" />
                </g>
                <circle cx="32" cy="32" r="4" fill="#fff" />
              </svg>
              <div class="fan-rpm">{{ fan.rpm == null ? '—' : fan.rpm }}</div>
              <div class="fan-label">{{ fan.label }}<template v-if="fan.rpm != null"> RPM</template></div>
            </article>
          </div>
          <div v-if="!fanItems.length" class="fan-empty">暂无风扇</div>
        </div>
        <div class="fan-ctrl" :class="{ off: !fanWritable }">
          <div class="fan-seg">
            <button type="button" :disabled="!fanWritable || fanBusy" :class="{ on: fanMode === 'auto' }" @click="setFanMode('auto')">自动</button>
            <button type="button" :disabled="!fanWritable || fanBusy" :class="{ on: fanMode === 'manual' }" @click="setFanMode('manual')">手动</button>
          </div>
          <div class="fan-seg">
            <button type="button" :disabled="!fanWritable || fanBusy" :class="{ on: fanPreset === 'silent' }" @click="setFanPreset('silent')">静音</button>
            <button type="button" :disabled="!fanWritable || fanBusy" :class="{ on: fanPreset === 'normal' }" @click="setFanPreset('normal')">标准</button>
            <button type="button" :disabled="!fanWritable || fanBusy" :class="{ on: fanPreset === 'performance' }" @click="setFanPreset('performance')">强劲</button>
          </div>
          <label class="fan-pwm">
            <span>PWM</span>
            <input
              type="range"
              min="25"
              max="100"
              :disabled="!fanWritable || fanBusy"
              v-model.number="pwmDraft"
              @pointerdown="pwmHold = true"
              @change="setFanPwm"
            />
            <b>{{ pwmDraft }}%</b>
          </label>
          <p v-if="fanMsg || fanReasonText(snap?.reason)" class="fan-note">{{ fanMsg || fanReasonText(snap?.reason) }}</p>
        </div>
      </section>

      <section class="card mod span-7 docker-card">
        <header class="mod-head">
          <span class="mid">M07</span>
          <span class="mod-title">Docker</span>
          <div class="top-switch push">
            <button type="button" class="chip" :class="{ on: topMetric === 'cpu' }" @click="topMetric = 'cpu'">按 CPU</button>
            <button type="button" class="chip" :class="{ on: topMetric === 'mem' }" @click="topMetric = 'mem'">按内存</button>
          </div>
          <a class="mod-link" href="#docker-detail" @click.prevent="openDrawer('docker-detail')">全部</a>
        </header>
        <div class="docker-body">
          <div class="docker-sums">
            <div class="sum">
              <b>{{ dockerSummary.running }}</b>
              <span>运行</span>
            </div>
            <div class="sum" :class="{ stop: dockerSummary.stopped > 0 }">
              <b>{{ dockerSummary.stopped }}</b>
              <span>停止</span>
            </div>
            <div class="sum">
              <b>{{ dockerSummary.total }}</b>
              <span>合计</span>
            </div>
          </div>
          <div v-if="dockerCols.length" class="docker-cols">
            <div v-for="(col, ci) in dockerCols" :key="ci" class="ctr-list">
              <div
                v-for="c in col"
                :key="c.id"
                class="ctr"
                :class="{ hot: c.hot }"
                :title="c.image || c.status"
              >
                <i class="ctr-dot" :class="ctrDot(c.state)"></i>
                <span class="name">{{ c.name }}</span>
                <span class="stat meter">
                  <b>{{ c.cpu_pct != null ? formatPct(c.cpu_pct) + '%' : '—' }}</b>
                  <i class="seg sm cpu" :class="c.cpu_pct == null ? '' : usageTone(c.cpu_pct)" :style="{ '--p': (c.cpu_pct == null ? 0 : clampPct(c.cpu_pct)) + '%' }"></i>
                </span>
                <span class="stat meter">
                  <b>{{ formatMemShort(c.mem_usage_bytes) }}</b>
                  <i class="seg sm mem" :class="c.mem_usage_bytes == null ? '' : usageTone(ctrMemPct(c))" :style="{ '--p': ctrMemPct(c) + '%' }"></i>
                </span>
              </div>
            </div>
          </div>
          <div v-else class="docker-empty">暂无容器</div>
        </div>
      </section>

      <section class="card mod span-5 pool-card">
        <header class="mod-head">
          <span class="mid">M08</span>
          <span class="mod-title">存储池</span>
          <span class="io-note push">{{ diskIoText || '读写暂无数据' }}</span>
          <a class="mod-link" href="#disk-detail" @click.prevent="openDrawer('disk-detail')">磁盘详情</a>
        </header>
        <div v-if="filesystems.length" class="pool-row">
          <div v-for="fs in filesystems" :key="fs.id" class="pool">
            <div class="pool-name">
              {{ poolName(fs.mount) }}
              <span v-if="fs.fstype" class="pool-fs">[{{ fs.fstype }}]</span>
            </div>
            <div class="pool-fig">
              <b>{{ formatBytes(fs.used_bytes) }}</b>
              <span>/ {{ formatBytes(fs.total_bytes) }}</span>
            </div>
            <div class="seg" :class="barColor(fs.used_pct)" :style="{ '--p': clampPct(fs.used_pct) + '%' }"></div>
            <div class="pool-pct" :class="barColor(fs.used_pct)">{{ formatPct(fs.used_pct, 0) }}%</div>
          </div>
        </div>
        <div v-else class="pool-empty">暂无存储池</div>
      </section>

      <section class="card mod span-12 disk-card">
        <header class="mod-head">
          <span class="mid">M09</span>
          <span class="mod-title">硬盘</span>
          <span class="health-sum push">
            OK {{ diskRollup.ok }}
            · FAIL <em :class="{ bad: diskRollup.fail > 0 }">{{ diskRollup.fail }}</em>
            · STANDBY {{ diskRollup.standby }}
            · 最热 {{ diskRollup.hot != null ? diskRollup.hot + '°C' : '—' }}
          </span>
        </header>
        <div v-if="disks.length" class="disk-row">
          <article v-for="d in disks" :key="d.id" class="disk">
            <div class="disk-id">{{ d.id }}</div>
            <div class="disk-model">{{ d.model || '—' }}</div>
            <div class="disk-k">TEMP</div>
            <div class="disk-temp">{{ d.temp_c != null ? d.temp_c + '°C' : '—' }}</div>
            <div class="disk-k">HEALTH</div>
            <div class="disk-health" :class="diskHealth(d).cls">{{ diskHealth(d).label }}</div>
            <div v-if="d.power_on_hours != null" class="disk-poh">通电 {{ d.power_on_hours }} h</div>
          </article>
        </div>
        <div v-else class="empty">暂无数据</div>
      </section>

      <section class="card mod span-12 alerts">
        <div class="health-strip">
          <a class="health-cell" href="#alert-detail" @click.prevent="openDrawer('alert-detail')">
            <span class="k">未确认告警</span>
            <b :class="{ bad: unackedCount > 0 }">{{ healthReady ? unackedCount : '—' }}</b>
          </a>
          <a class="health-cell" href="#disk-detail" @click.prevent="openDrawer('disk-detail')">
            <span class="k">硬盘异常</span>
            <b :class="{ bad: smartFail > 0 }">{{ healthReady ? smartFail : '—' }}</b>
          </a>
          <a class="health-cell" href="#docker-detail" @click.prevent="openDrawer('docker-detail')">
            <span class="k">未运行容器</span>
            <b :class="{ warn: dockerDown > 0 }">{{ healthReady ? dockerDown : '—' }}</b>
          </a>
        </div>
        <div class="alert-bar">
        <header class="mod-head">
          <span class="mod-title">最近告警</span>
          <a class="mod-link push" href="#alert-detail" @click.prevent="openDrawer('alert-detail')">全部</a>
        </header>
        <div v-if="recentAlerts.length" class="alert-list">
          <div v-for="a in recentAlerts" :key="a.id" class="alert-row">
            <span class="badge" :class="a.severity === 'critical' ? 'crit' : 'warn'">{{ a.severity }}</span>
            <span class="alert-title">{{ a.title }}</span>
            <span v-if="a.acked" class="badge muted">已确认</span>
            <span class="muted">{{ a.message }}</span>
          </div>
        </div>
        <p v-else class="muted empty-inline">暂无告警</p>
        </div>
      </section>
    </div>

    <div v-if="tempsOpen" class="temp-pop" @click.self="tempsOpen = false">
      <div class="temp-pop-card" role="dialog" aria-label="其它温度">
        <header>
          <strong>其它温度</strong>
          <button type="button" class="fold" @click="tempsOpen = false">关闭</button>
        </header>
        <ul class="temp-list">
          <li v-for="t in otherTemps" :key="t.key">
            <span>{{ t.key }}</span>
            <b>{{ t.value }}°C</b>
          </li>
        </ul>
      </div>
    </div>

    <details id="disk-detail" class="drawer" @toggle="onDrawerToggle">
      <summary>磁盘详情</summary>
      <Disks v-if="diskOpen" embedded />
    </details>
    <details id="docker-detail" class="drawer" @toggle="onDrawerToggle">
      <summary>Docker 详情</summary>
      <Docker v-if="dockerOpen" embedded />
    </details>
    <details id="alert-detail" class="drawer" @toggle="onDrawerToggle">
      <summary>告警详情</summary>
      <Alerts v-if="alertOpen" embedded />
    </details>
  </div>
</template>

<style scoped>
.err-banner {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--crit-bg);
  color: var(--crit);
}

.modules {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 14px;
}

.mod {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.span-3 { grid-column: span 3; }
.span-4 { grid-column: span 4; }
.span-5 { grid-column: span 5; }
.span-7 { grid-column: span 7; }
.span-8 { grid-column: span 8; }
.span-12 { grid-column: span 12; }

.mod-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 26px;
}

.mid {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #9aa3b2;
}

.mod-title {
  font-weight: 700;
  letter-spacing: -0.02em;
}

.push { margin-left: auto; }

.mod-link {
  font-size: 0.8rem;
  font-weight: 650;
}

.io-note {
  color: var(--muted);
  font-size: 0.75rem;
  letter-spacing: 0.04em;
}

.date {
  color: var(--muted);
  font-size: 0.86rem;
}

.id-body {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}
.id-card .mod-title { font-size: 1.05rem; }
.id-card .pill { font-size: 0.95rem; padding: 5px 12px; }
.id-hero { display: grid; gap: 4px; }
.id-name {
  font-size: 2.6rem;
  line-height: 1.05;
  font-weight: 700;
  letter-spacing: -0.04em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.id-host { color: var(--muted); font-size: 1.05rem; }
.id-fresh { color: var(--muted); font-size: 1.2rem; font-variant-numeric: tabular-nums; }
.id-fresh.stale { color: #b45309; font-weight: 700; }
.id-clock {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
  color: #607086;
  font-size: 1.05rem;
  font-variant-numeric: tabular-nums;
}
.id-time { font-size: 1.55rem; font-weight: 650; color: var(--ink); letter-spacing: -0.03em; }
.id-card .facts {
  grid-template-columns: 1fr;
  gap: 10px;
}
.id-card .fact {
  flex-direction: row;
  justify-content: space-between;
  align-items: baseline;
  gap: 16px;
}
.id-card .fact span { font-size: 0.95rem; }
.id-card .fact b { font-size: 1.25rem; text-align: right; }
.id-card .fact b.clip { white-space: nowrap; }
.id-ver {
  margin-top: 8px;
  color: #9aa3b2;
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}
.fact b.clip {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.clock {
  font-size: 2.55rem;
  line-height: 1;
  font-weight: 650;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
}

.subhero {
  display: flex;
  align-items: baseline;
  gap: 8px;
  color: #607086;
  font-size: 0.92rem;
}

.subhero b {
  font-size: 1.15rem;
  color: #f08a3a;
}

.node-line {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 8px;
  margin-top: 4px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.k {
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  color: #9aa3b2;
  font-weight: 700;
}

.node-name {
  font-weight: 700;
  font-size: 1.05rem;
}

.pills { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }

.facts { display: grid; gap: 7px; }
.fact {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
}
.fact span { color: #9aa3b2; font-size: 0.75rem; flex: none; }
.fact b {
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  font-size: 0.92rem;
  text-align: right;
}

.metric { display: grid; gap: 6px; }
.metric-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  font-size: 0.78rem;
  letter-spacing: 0.06em;
  color: #8b95a5;
  font-weight: 700;
}
.metric-top b {
  letter-spacing: -0.03em;
  font-size: 1.2rem;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.metric-top em {
  font-style: normal;
  margin-left: 6px;
  color: var(--pink);
  font-size: 0.95rem;
}
.metric-top .na {
  font-size: 0.95rem;
  font-weight: 650;
  color: var(--muted);
  letter-spacing: 0;
}
.swap-em { color: #fb923c; }

.seg {
  height: 12px;
  border-radius: 7px;
  position: relative;
  background: repeating-linear-gradient(90deg, #e3e8ee 0 8px, transparent 8px 11px);
  overflow: hidden;
}
.seg::after {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: var(--p, 0%);
  background: repeating-linear-gradient(90deg, var(--bar, #2ec9c0) 0 8px, transparent 8px 11px);
}
.seg.cpu { --bar: #3dcec6; }
.seg.mem { --bar: #f472b6; }
.seg.swap { --bar: #fb923c; }
.seg.power { --bar: #34d399; }
.seg.loadbar { --bar: #60a5fa; }
.seg.diskbar { --bar: #818cf8; }
.seg.teal { --bar: #3dcec6; }
.seg.warn { --bar: #f5b14a; }
.seg.crit { --bar: #fb7185; }
.seg.warm { --bar: #f5b14a; }
.seg.hot { --bar: #fb7185; }
.seg.sm { height: 8px; }
.est, .metric-top .sub {
  font-style: normal;
  margin-left: 6px;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0;
  color: var(--muted);
}

.trend-plot { display: flex; gap: 8px; align-items: stretch; }
.y-axis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  color: #8b95a5;
  font-size: 1rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  padding: 2px 0;
}
.trend-wrap, .trend-plot { flex: 1; min-height: 200px; }
.trend { width: 100%; height: 200px; display: block; }
.trend-empty {
  min-height: 200px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  background: #f7f8fb;
  color: #5c6775;
  font-size: 1.8rem;
  font-weight: 700;
}
.x-axis {
  display: flex;
  justify-content: space-between;
  color: #6d7886;
  font-size: 1rem;
  font-weight: 700;
}
.trend-caption {
  margin: 0;
  color: #3d4754;
  font-size: 1.15rem;
  font-weight: 700;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 0.8rem;
  color: #607086;
  font-variant-numeric: tabular-nums;
}
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 14px; height: 4px; border-radius: 99px; display: inline-block; }
.swatch.cpu { background: #2ec9c0; }
.swatch.mem { background: #f062b0; }
.swatch.load { background: #f5b14a; }
.swatch.temp { background: #f08a3a; }
.swatch.up { background: #5b8def; }
.swatch.down { background: #8b7cf6; }
.chip {
  border: 0;
  background: #f4f6f8;
  color: #607086;
  border-radius: 999px;
  padding: 4px 10px;
  font: inherit;
  font-weight: 700;
  font-size: 0.78rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.trend-card .chip {
  min-height: 44px;
  padding: 8px 16px;
  font-size: 1.05rem;
}
.chip.on { background: #e7f6f4; color: var(--teal-ink); }
.trend-card .swatch { width: 22px; height: 6px; }
.age.stale {
  color: #b45309;
  background: var(--warn-bg);
  border-radius: 999px;
  padding: 2px 8px;
}

.net-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: end; }
.net-plot { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 6px; }
.net-svg { width: 100%; flex: 1; min-height: 56px; height: auto; display: block; }
.net-card .swatch {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.net-card .k { font-size: 0.92rem; color: #607086; }
.net-empty {
  flex: 1;
  min-height: 64px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: #f7f8fb;
  color: #5c6775;
  font-size: 1.25rem;
  font-weight: 700;
}
.net-axis { font-size: 0.8rem; }
.net-v {
  margin-top: 6px;
  font-size: 1.7rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.net-card .k { display: inline-flex; align-items: center; gap: 6px; letter-spacing: 0.04em; }
.empty {
  flex: 1;
  display: grid;
  place-items: center;
  min-height: 88px;
  border-radius: 14px;
  background:
    linear-gradient(#f7f8fb, #f7f8fb) padding-box,
    repeating-linear-gradient(90deg, transparent, transparent 12px, rgba(140, 150, 170, 0.18) 12px, rgba(140, 150, 170, 0.18) 13px);
  color: #9aa3b2;
  font-size: 0.9rem;
}
.empty.grow { min-height: 120px; }

.cpu-card .head-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.cpu-sum {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.core-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  gap: 6px 8px;
  align-items: stretch;
}
.core-unit {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  container-type: inline-size;
}
.ring-wrap {
  position: relative;
  width: min(100%, 148px);
  aspect-ratio: 1;
  display: grid;
  place-items: center;
}
.core-svg { width: 100%; height: 100%; display: block; }
.ring-name {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 0.72rem;
  font-weight: 700;
  color: #8b95a5;
  pointer-events: none;
}
.core-line {
  margin: 0;
  display: flex;
  justify-content: center;
  gap: 6px;
  max-width: 100%;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  line-height: 1.15;
  font-size: clamp(12px, 18cqw, 16px);
  white-space: nowrap;
}
.core-line .use { color: #3d6fd8; }
.core-line .hz { color: #0f8f88; }
.core-line.deg { color: #e07a2f; font-size: clamp(13px, 20cqw, 18px); }
.core-line.deg.miss { color: #9aa3b2; }
.fold {
  border: 0;
  background: #f4f6f8;
  color: #607086;
  font: inherit;
  font-size: 0.75rem;
  font-weight: 700;
  border-radius: 999px;
  padding: 4px 10px;
  cursor: pointer;
  white-space: nowrap;
}
.temp-pop {
  position: fixed;
  inset: 0;
  z-index: 70;
  background: rgba(28, 36, 48, 0.38);
  display: grid;
  place-items: center;
  padding: 24px;
}
.temp-pop-card {
  width: min(420px, 100%);
  max-height: min(70vh, 480px);
  overflow: auto;
  background: #fff;
  border-radius: 16px;
  padding: 16px 18px 18px;
  box-shadow: var(--shadow);
}
.temp-pop-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.temp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.temp-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.95rem;
}
.temp-list span { color: var(--muted); overflow: hidden; text-overflow: ellipsis; }
.temp-list b { font-variant-numeric: tabular-nums; }
.health-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.alert-bar { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.fan-stage {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: center;
  gap: 2px;
}
.fan-grid { width: 100%; display: grid; gap: 6px; align-items: center; }
.fan-unit { min-width: 0; display: grid; justify-items: center; }
.fan-svg { width: min(72px, 100%); height: auto; }
.fan-svg.cpu { color: #2ec9c0; }
.fan-svg.case { color: #8b7cf6; }
.fan-rpm {
  font-size: 1.55rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.fan-label { color: var(--muted); font-size: 0.75rem; font-weight: 700; }
.fan-empty {
  margin: 0;
  text-align: center;
  font-size: 1.15rem;
  font-weight: 700;
  color: #5c6775;
}
.fan-ctrl { display: grid; gap: 4px; }
.fan-ctrl.off { opacity: 0.55; }
.fan-seg { display: flex; gap: 4px; }
.fan-seg button {
  flex: 1;
  border: 0;
  background: #f4f6f8;
  color: #607086;
  border-radius: 999px;
  font: inherit;
  font-size: 0.75rem;
  font-weight: 700;
  min-height: 28px;
  cursor: pointer;
}
.fan-seg button.on { background: #e7f6f4; color: var(--teal-ink); }
.fan-seg button:disabled { cursor: default; }
.fan-pwm {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  font-weight: 700;
  color: #607086;
}
.fan-pwm input { flex: 1; min-width: 0; accent-color: #2ec9c0; }
.fan-pwm b { font-variant-numeric: tabular-nums; color: var(--ink); min-width: 2.6em; text-align: right; }
.fan-note { margin: 0; font-size: 0.72rem; color: #b45309; line-height: 1.3; }
.health-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.health-cell {
  background: #f6f8fa;
  border-radius: 14px;
  padding: 12px 14px;
  color: inherit;
  display: grid;
  gap: 4px;
}
.health-cell b {
  font-size: 1.7rem;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
}
.health-cell b.bad { color: var(--crit); }
.health-cell b.warn { color: #b45309; }
.docker-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
  align-items: stretch;
}
.docker-sums {
  flex: none;
  width: 72px;
  display: flex;
  flex-direction: column;
  justify-content: space-evenly;
  gap: 4px;
}
.docker-cols {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
  overflow: hidden;
}
.sum {
  background: #f6f8fa;
  border-radius: 14px;
  padding: 6px 10px;
}
.sum b {
  display: block;
  font-size: 1.65rem;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  line-height: 1.05;
}
.sum span { color: var(--muted); font-size: 0.75rem; font-weight: 700; }
.sum.stop b { color: var(--crit); }
.top-switch { display: flex; align-items: center; gap: 6px; flex: none; }
.docker-empty {
  flex: 1;
  min-height: 0;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: #f7f8fb;
  color: #5c6775;
  font-size: 1.25rem;
  font-weight: 700;
}
.health-sum {
  color: #607086;
  font-size: 0.78rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.health-sum em { font-style: normal; }
.health-sum .bad { color: var(--crit); }

.ctr-list {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 1px;
}
.ctr {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) minmax(78px, 1.1fr) minmax(78px, 1.1fr);
  gap: 4px;
  align-items: center;
  padding: 0;
  font-size: 0.78rem;
  border-radius: 6px;
  flex: none;
  line-height: 1.15;
}
.ctr.hot { background: #fff6e8; }
.rank {
  font-size: 0.72rem;
  font-weight: 800;
  color: #9aa3b2;
  text-align: center;
}
.ctr-dot {
  width: 8px;
  height: 8px;
  border-radius: 99px;
  background: #d5dbe3;
}
.ctr-head { color: #9aa3b2; font-size: 0.68rem; letter-spacing: 0.06em; font-weight: 700; }
.ctr-head .stat { color: #9aa3b2; }
.ctr-dot.run { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.16); }
.ctr-dot.stop { background: #fb7185; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stat.meter {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.stat.meter b {
  flex: none;
  min-width: 2.4em;
  text-align: right;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.stat.meter .seg { flex: 1; min-width: 36px; }
.docker-card .seg.sm { height: 8px; }
.stat {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #4b5568;
  font-size: 0.84rem;
}

.pool-card { min-height: 0; }
.pool-row {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-wrap: nowrap;
  align-items: stretch;
  gap: 12px;
  overflow: hidden;
}
.pool {
  flex: 1 1 0;
  min-width: 0;
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  justify-content: space-evenly;
  gap: 4px;
}
.pool-name {
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: clamp(0.72rem, 22cqw, 0.95rem);
}
.pool-fs { color: var(--muted); font-weight: 650; margin-left: 4px; }
.pool-fig {
  display: flex;
  gap: 4px;
  align-items: baseline;
  flex-wrap: nowrap;
  min-width: 0;
}
.pool-fig b {
  font-size: clamp(0.85rem, 32cqw, 1.5rem);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
  line-height: 1.05;
}
.pool-fig span, .pool-pct {
  color: var(--muted);
  font-size: clamp(0.68rem, 16cqw, 0.85rem);
  white-space: nowrap;
}
.pool .seg { height: 9px; }
.pool-pct.warn { color: #b45309; font-weight: 800; }
.pool-pct.crit { color: var(--crit); font-weight: 800; }
.pool-empty {
  flex: 1;
  min-height: 0;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: #f7f8fb;
  color: #5c6775;
  font-size: 1.25rem;
  font-weight: 700;
}
.pool-card .io-note { font-size: 0.92rem; font-weight: 700; color: #3d4754; letter-spacing: 0; }

.disk-row {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 2px;
}
.disk {
  flex: 1 0 128px;
  background: #f6f8fa;
  border-radius: 14px;
  padding: 12px;
  min-width: 128px;
}
.disk-id { font-weight: 750; letter-spacing: -0.02em; }
.disk-model {
  color: var(--muted);
  font-size: 0.75rem;
  min-height: 1.1em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.disk-k {
  margin-top: 8px;
  font-size: 0.66rem;
  letter-spacing: 0.08em;
  color: #9aa3b2;
  font-weight: 700;
}
.disk-temp {
  color: #f08a3a;
  font-weight: 750;
  font-variant-numeric: tabular-nums;
}
.disk-health { font-weight: 800; letter-spacing: 0.04em; font-size: 0.92rem; }
.disk-health.ok { color: #15915f; }
.disk-health.bad { color: var(--crit); }
.disk-health.muted { color: var(--muted); }
.disk-poh { margin-top: 6px; color: var(--muted); font-size: 0.72rem; }

.alert-list { display: grid; gap: 8px; }
.alert-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
}
.alert-title { font-weight: 700; }
.empty-inline { margin: 0; }

@media (min-width: 1200px) {
  .modules {
    flex: 1;
    min-height: 0;
    height: 100%;
    gap: 10px;
    grid-template-rows: minmax(0, 1.2fr) minmax(0, 1.02fr) minmax(0, 0.72fr) 40px;
  }
  .id-card { grid-column: 1 / span 3; grid-row: 1; }
  .res-card { grid-column: 4 / span 3; grid-row: 1; }
  .trend-card { grid-column: 7 / span 3; grid-row: 1; }
  .net-card { grid-column: 10 / span 3; grid-row: 1; }
  .cpu-card { grid-column: 1 / span 4; grid-row: 2; }
  .fan-card { grid-column: 5 / span 3; grid-row: 2; }
  .docker-card { grid-column: 8 / span 5; grid-row: 2; }
  .pool-card { grid-column: 1 / span 7; grid-row: 3; }
  .disk-card { grid-column: 8 / span 5; grid-row: 3; }
  .alerts { grid-column: 1 / -1; grid-row: 4; padding: 6px 14px; gap: 4px; }
  .alerts .alert-list { display: flex; gap: 16px; overflow: hidden; flex-wrap: nowrap; }
  .mod { min-height: 0; height: 100%; overflow: hidden; padding: 12px 14px; gap: 8px; }
  .alerts.mod {
    flex-direction: row;
    align-items: center;
    padding: 0 14px;
    gap: 12px;
  }
  .alerts .health-strip { display: flex; width: auto; flex: none; gap: 10px; }
  .alerts .health-cell {
    display: flex;
    align-items: baseline;
    gap: 4px;
    padding: 0;
    background: transparent;
    border-radius: 0;
  }
  .alerts .health-cell .k { font-size: 0.68rem; }
  .alerts .health-cell b { font-size: 0.95rem; }
  .alert-bar { flex-direction: row; align-items: center; flex: 1; min-width: 0; gap: 8px; }
  .fan-card { justify-content: space-evenly; gap: 4px; }
  .fan-svg { width: min(48px, 72%); }
  .fan-rpm { font-size: 1.25rem; }
  .fan-seg button { min-height: 22px; font-size: 0.68rem; padding: 0 4px; }
  .fan-empty { font-size: 0.95rem; }
  .alerts .mod-head { flex: none; min-height: 0; flex-wrap: nowrap; }
  .alerts .alert-list { flex: 1; min-width: 0; align-items: center; }
  .alerts .alert-row { flex: none; flex-wrap: nowrap; white-space: nowrap; }
  .alerts .alert-title { white-space: nowrap; }
  .alerts .alert-row .muted {
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .id-name { font-size: 1.45rem; }
  .id-fresh { font-size: 0.85rem; }
  .id-clock { margin-top: 4px; padding-top: 4px; font-size: 0.8rem; }
  .id-time { font-size: 1.15rem; }
  .id-body { flex: 1; min-height: 0; align-content: space-evenly; gap: 6px; }
  .id-card .facts { gap: 0; align-content: space-evenly; }
  .id-card .fact { padding: 1px 0; border-bottom: 0; }
  .id-card .fact span { font-size: 0.78rem; }
  .id-card .fact b { font-size: 0.92rem; }
  .id-ver { display: none; }
  .res-card { gap: 0; justify-content: space-evenly; }
  .res-card .metric { gap: 6px; }
  .res-card .seg { height: 9px; }
  .res-card .metric-top, .res-card .metric-top b { font-size: 0.98rem; }
  .trend-card { justify-content: space-evenly; }
  .net-card { justify-content: space-evenly; gap: 10px; }
  .net-card .k { font-size: 0.95rem; }
  .net-v { font-size: 1.65rem; }
  .trend-plot { flex: 1; min-height: 0; }
  .trend-card .trend, .trend-card .trend-empty { height: 100%; min-height: 0; flex: 1; }
  .trend-empty { font-size: 1.25rem; }
  .trend-card .legend { flex-wrap: nowrap; gap: 4px; }
  .trend-card .chip { min-height: 26px; font-size: 0.68rem; padding: 2px 6px; }
  .trend-card .y-axis, .trend-card .x-axis, .trend-card .trend-caption { font-size: 0.75rem; }
  .cpu-card { justify-content: space-evenly; }
  .core-grid { height: 100%; }
  .core-unit { height: 100%; justify-content: space-evenly; }
  .ring-wrap {
    flex: 1 1 auto;
    width: auto;
    height: auto;
    max-width: 100%;
    max-height: calc(100% - 2.4em);
    min-height: 0;
    aspect-ratio: 1;
  }
  .cpu-sum { font-size: 0.72rem; }
  .docker-card { justify-content: space-between; }
  .docker-card .mod-head { flex-wrap: nowrap; }
  .docker-card .sum { padding: 2px 6px; }
  .docker-card .sum b { font-size: 1.5rem; }
  .docker-card .sum span { font-size: 0.68rem; }
  .ctr-list { overflow: hidden; }
  .health-cell { padding: 6px 8px; }
  .health-cell b { font-size: 1.25rem; }
}

@media (min-width: 1200px) and (max-height: 860px) {
  .modules { gap: 10px; }
  .mod { gap: 8px; }
  .empty.grow { min-height: 0; }
}

@media (max-width: 1199px) {
  .span-3, .span-4 { grid-column: span 6; }
  .span-5, .span-7, .span-8, .span-12 { grid-column: span 12; }
  .health-sum { margin-left: 0; text-align: left; }
}

@media (max-width: 720px) {
  .span-3, .span-4, .span-5, .span-7, .span-8, .span-12 { grid-column: span 12; }
  .mid, .io-note { display: none; }
  .id-name { font-size: 2rem; }
  .id-fresh { font-size: 1.05rem; }
  .id-time { font-size: 1.25rem; }
  .id-clock { font-size: 0.95rem; margin-top: 8px; }
  .id-card .fact b { font-size: 1.05rem; }
  .id-card .fact span { font-size: 0.85rem; }
  .clock { font-size: 2.7rem; }
  .trend, .trend-empty { height: 200px; min-height: 200px; }
  .trend-card .chip { min-height: 44px; font-size: 1rem; }
  .net-svg { height: 140px; min-height: 140px; }
  .net-v { font-size: 1.85rem; }
  .net-card .k { font-size: 1.05rem; }
  .net-empty { min-height: 120px; font-size: 1.45rem; }
  .health-cell b, .sum b { font-size: 1.45rem; }
  .health-strip .health-cell { min-height: 44px; align-content: center; }
  .fan-seg button { min-height: 44px; font-size: 0.95rem; }
  .fan-pwm { min-height: 44px; font-size: 0.95rem; }
  .fan-rpm { font-size: 1.8rem; }
  .fan-svg { width: min(96px, 70%); }
  .ring-wrap { width: min(46vw, 168px); }
  .core-line { font-size: 1rem; }
  .core-line.deg { font-size: 1.15rem; }
  .cpu-card .fold { min-height: 44px; padding: 0 14px; }
  .ring-name { font-size: 0.85rem; }
  .docker-card .chip { min-height: 44px; font-size: 0.95rem; padding: 0 12px; }
  .docker-sums { width: 96px; }
  .docker-card .sum b { font-size: 1.55rem; }
  .pool-card .io-note { display: inline; }
  .pool-row { flex-direction: column; overflow: visible; gap: 14px; }
  .pool { flex: none; width: 100%; }
  .pool-fig b { font-size: 1.5rem; }
  .pool-name { font-size: 1rem; }
  .disk { flex-basis: 46%; }
  .health-sum { font-size: 0.85rem; }
}
</style>
