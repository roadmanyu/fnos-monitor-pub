<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client'
import { nas, rememberLocalName } from '../nas/profiles'
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
const seriesOn = reactive({ cpu: true, mem: true, load: false, temp: false })
let poll
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
const cores = computed(() => (Array.isArray(host.value?.cpu_cores) ? host.value.cpu_cores : []))
const uptimeText = computed(() => formatUptime(host.value?.uptime_sec))
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
  return {
    has: up.length + down.length > 0,
    up: linePath(up, 320, 72, peak),
    down: linePath(down, 320, 72, peak)
  }
})

const clockText = computed(() => formatClock(now.value, tz.value))
const dateText = computed(() => formatDateLine(now.value, tz.value))

const cpuFrac = computed(() => clampPct(host.value?.cpu_pct) / 100)
const donutC = 2 * Math.PI * 46

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
  const hasCpu = !Number.isNaN(cpu)
  const hasMem = !Number.isNaN(mem)
  if (!hasCpu && !hasMem) return null
  if ((hasCpu && cpu >= 90) || (hasMem && mem >= 90)) return { text: '负载偏高', cls: 'warn' }
  return { text: '负载正常', cls: 'ok' }
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
  return ranked.slice(0, 5).map((c, i) => ({
    ...c,
    rank: i + 1,
    hot: Number(c.cpu_pct) >= 50
  }))
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

const collectStale = computed(() => {
  if (ageSec.value == null) return false
  const interval = Number(meta.value?.collect_interval_sec)
  const limit = Number.isFinite(interval) && interval > 0 ? interval : 30
  return ageSec.value > limit * 2
})

const ageText = computed(() => (ageSec.value == null ? '—' : `${ageSec.value} 秒前更新`))

const healthReady = computed(() => !!snap.value?.ts)
const healthOk = computed(() => (
  healthReady.value && unackedCount.value === 0 && smartFail.value === 0 && dockerDown.value === 0
))

const trend = computed(() => buildTrend(hist.value, seriesOn))

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
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function onDrawerToggle(e) {
  const el = e.target
  if (el.id === 'disk-detail') diskOpen.value = el.open
  if (el.id === 'docker-detail') dockerOpen.value = el.open
  if (el.id === 'alert-detail') alertOpen.value = el.open
}

function rateLabel(value, known) {
  if (!known) return '暂无数据'
  return formatRate(value) || '采集中'
}

onMounted(() => {
  load()
  poll = setInterval(load, 30000)
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
onUnmounted(() => {
  clearInterval(poll)
  clearInterval(clock)
})

const TREND_SERIES = [
  { key: 'cpu', color: '#2ec9c0' },
  { key: 'mem', color: '#f062b0' },
  { key: 'load', color: '#f5b14a' },
  { key: 'temp', color: '#f08a3a' }
]

function buildTrend(series, enabled) {
  const w = 320
  const h = 112
  const paths = []
  for (const spec of TREND_SERIES) {
    if (!enabled[spec.key]) continue
    const values = (series[spec.key] || [])
      .map((p) => Number(p.value))
      .filter((v) => !Number.isNaN(v))
    if (!values.length) continue
    const d = linePath(values, w, h, trendDomain(spec.key, values))
    if (d) paths.push({ key: spec.key, color: spec.color, d })
  }
  const first = paths[0]
  return {
    has: paths.length > 0,
    paths,
    area: first ? `${first.d} L ${w} ${h} L 0 ${h} Z` : '',
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
  if (!n) return ''
  if (n === 1) {
    const y = yOf(values[0]).toFixed(1)
    return `M0 ${y} L${w} ${y}`
  }
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
      <section class="card mod span-3">
        <header class="mod-head">
          <span class="mid">M01</span>
          <span class="mod-title">系统</span>
        </header>
        <div class="date">{{ dateText }}</div>
        <div class="clock">{{ clockText }}</div>
        <div class="subhero">
          <template v-if="cpuTemp != null">
            <b>{{ cpuTemp }}°C</b>
            <span>CPU 温度</span>
          </template>
          <span v-else class="muted">CPU 温度 —</span>
        </div>
        <div class="node-line">
          <div>
            <div class="k">NODE</div>
            <div class="node-name">{{ meta?.hostname || '—' }}</div>
          </div>
          <div class="pills">
            <span class="pill" :class="snap?.ts ? 'ok' : 'muted'">
              <i class="dot"></i>{{ snap?.ts ? '在线' : '离线' }}
            </span>
            <span v-if="meta?.mock_mode" class="pill warn">模拟数据</span>
          </div>
        </div>
        <div class="facts">
          <div class="fact">
            <span>内存</span>
            <b>{{ formatBytes(host.mem_used_bytes) }} / {{ formatBytes(host.mem_total_bytes) }}</b>
          </div>
          <div class="fact">
            <span>负载</span>
            <b>{{ host.load1 ?? '—' }} · 5m {{ host.load5 ?? '—' }}</b>
          </div>
          <div v-if="uptimeText" class="fact">
            <span>运行</span>
            <b>{{ uptimeText }}</b>
          </div>
          <div class="fact">
            <span>更新</span>
            <b class="age" :class="{ stale: collectStale }" :title="formatTs(meta?.last_collect_ts || snap?.ts, tz)">{{ ageText }}</b>
          </div>
          <div class="fact">
            <span>版本</span>
            <b>{{ meta?.app_version || '—' }}</b>
          </div>
        </div>
      </section>

      <section class="card mod span-3">
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
          <div class="seg cpu" :style="{ '--p': clampPct(host.cpu_pct) + '%' }"></div>
        </div>
        <div class="metric">
          <div class="metric-top">
            <span>MEMORY</span>
            <b>{{ formatBytes(host.mem_used_bytes, 1) }} <em>{{ formatPct(host.mem_used_pct, 0) }}%</em></b>
          </div>
          <div class="seg mem" :style="{ '--p': clampPct(host.mem_used_pct) + '%' }"></div>
        </div>
        <div class="metric">
          <div class="metric-top">
            <span>SWAP</span>
            <b v-if="swapKnown && host.swap_total_bytes > 0">
              {{ formatBytes(host.swap_used_bytes) }}
              <em class="swap-em">{{ formatPct(host.swap_used_pct, 0) }}%</em>
            </b>
            <b v-else-if="swapKnown" class="na">无交换分区</b>
            <b v-else class="na">暂无数据</b>
          </div>
          <div class="seg swap" :style="{ '--p': (swapKnown ? clampPct(host.swap_used_pct) : 0) + '%' }"></div>
        </div>
      </section>

      <section class="card mod span-3">
        <header class="mod-head">
          <span class="mid">M03</span>
          <span class="mod-title">趋势</span>
          <span class="pill muted head-pill push">近 1 小时</span>
        </header>
        <div v-if="trend.has" class="trend-wrap">
          <svg viewBox="0 0 320 112" class="trend" preserveAspectRatio="none">
            <line v-for="i in 3" :key="i" x1="0" :y1="i * 28" x2="320" :y2="i * 28" stroke="#eef1f4" />
            <path v-if="trend.area" :d="trend.area" :fill="trend.areaColor" fill-opacity="0.16" stroke="none" />
            <path
              v-for="p in trend.paths"
              :key="p.key"
              :d="p.d"
              fill="none"
              :stroke="p.color"
              stroke-width="2.2"
              vector-effect="non-scaling-stroke"
            />
          </svg>
        </div>
        <div v-else class="empty">暂无趋势数据</div>
        <div class="legend">
          <button type="button" class="chip" :class="{ on: seriesOn.cpu }" @click="seriesOn.cpu = !seriesOn.cpu">
            <i class="swatch cpu"></i>CPU {{ formatPct(host.cpu_pct) }}%
          </button>
          <button type="button" class="chip" :class="{ on: seriesOn.mem }" @click="seriesOn.mem = !seriesOn.mem">
            <i class="swatch mem"></i>内存 {{ formatPct(host.mem_used_pct) }}%
          </button>
          <button type="button" class="chip" :class="{ on: seriesOn.load }" @click="seriesOn.load = !seriesOn.load">
            <i class="swatch load"></i>负载 {{ host.load1 ?? '—' }}
          </button>
          <button type="button" class="chip" :class="{ on: seriesOn.temp }" @click="seriesOn.temp = !seriesOn.temp">
            <i class="swatch temp"></i>温度 {{ cpuTemp != null ? cpuTemp + '°C' : '—' }}
          </button>
        </div>
        <p v-if="seriesOn.load || seriesOn.temp" class="scale-note">负载、温度按各自刻度绘制，不与百分比共用一轴。</p>
      </section>

      <section class="card mod span-3">
        <header class="mod-head">
          <span class="mid">M04</span>
          <span class="mod-title">网络</span>
        </header>
        <div class="net-stats">
          <div>
            <div class="k">↑ 上传</div>
            <div class="net-v">{{ rateLabel(host.net_up_bps, netKnown) }}</div>
          </div>
          <div>
            <div class="k">↓ 下载</div>
            <div class="net-v">{{ rateLabel(host.net_down_bps, netKnown) }}</div>
          </div>
        </div>
        <svg v-if="netTrend.has" viewBox="0 0 320 72" class="net-svg" preserveAspectRatio="none">
          <path :d="netTrend.down" fill="none" stroke="#8b7cf6" stroke-width="2" vector-effect="non-scaling-stroke" />
          <path :d="netTrend.up" fill="none" stroke="#5b8def" stroke-width="2" vector-effect="non-scaling-stroke" />
        </svg>
        <div v-else class="empty grow">{{ netKnown ? '采集中' : '暂无数据' }}</div>
      </section>

      <section class="card mod span-4">
        <header class="mod-head">
          <span class="mid">M05</span>
          <span class="mod-title">CPU</span>
          <span v-if="tempState" class="pill head-pill push" :class="tempState.cls">
            <i class="dot"></i>{{ tempState.text }}
          </span>
        </header>
        <div class="cpu-body">
          <div class="donut-wrap">
            <svg viewBox="0 0 120 120" class="donut">
              <circle cx="60" cy="60" r="46" fill="none" stroke="#eef1f4" stroke-width="10" />
              <circle
                cx="60" cy="60" r="46" fill="none"
                stroke="#2ec9c0" stroke-width="10" stroke-linecap="round"
                :stroke-dasharray="donutC"
                :stroke-dashoffset="donutC * (1 - cpuFrac)"
                transform="rotate(-90 60 60)"
              />
            </svg>
            <div class="donut-label">
              <strong>{{ host.cpu_pct == null ? '—' : formatPct(host.cpu_pct, Number(host.cpu_pct) < 10 ? 1 : 0) + '%' }}</strong>
              <span>整机</span>
            </div>
          </div>
          <div class="cpu-side">
            <div v-if="cpuTemp != null" class="cpu-temp">{{ cpuTemp }}°C</div>
            <div class="load-pills">
              <span>1m {{ host.load1 ?? '—' }}</span>
              <span>5m {{ host.load5 ?? '—' }}</span>
            </div>
            <div v-if="cores.length > 1" class="core-row">
              <span v-for="(c, i) in cores.slice(0, 8)" :key="i" class="core" :title="'核心 ' + i">
                <i :style="{ height: clampPct(c) + '%' }"></i>{{ Math.round(c) }}
              </span>
              <span v-if="cores.length > 8" class="muted">+{{ cores.length - 8 }}</span>
            </div>
            <button
              type="button"
              class="fold"
              :disabled="!otherTemps.length"
              @click="tempsOpen = !tempsOpen"
            >
              其它温度 {{ otherTemps.length ? otherTemps.length : '暂无数据' }}
              <span v-if="otherTemps.length">{{ tempsOpen ? '收起' : '展开' }}</span>
            </button>
            <ul v-if="tempsOpen && otherTemps.length" class="temp-list">
              <li v-for="t in otherTemps" :key="t.key">
                <span>{{ t.key }}</span>
                <b>{{ t.value }}°C</b>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section class="card mod span-8">
        <header class="mod-head">
          <span class="mid">M10</span>
          <span class="mod-title">健康</span>
          <span v-if="healthReady" class="pill head-pill push" :class="healthOk ? 'ok' : 'warn'">
            <i class="dot"></i>{{ healthOk ? '全部正常' : '有问题' }}
          </span>
        </header>
        <div class="health-row">
          <a class="health-cell" href="#alert-detail" @click.prevent="openDrawer('alert-detail')">
            <div class="k">未确认告警</div>
            <b :class="{ bad: unackedCount > 0 }">{{ healthReady ? unackedCount : '—' }}</b>
          </a>
          <a class="health-cell" href="#disk-detail" @click.prevent="openDrawer('disk-detail')">
            <div class="k">SMART 失败</div>
            <b :class="{ bad: smartFail > 0 }">{{ healthReady ? smartFail : '—' }}</b>
          </a>
          <a class="health-cell" href="#docker-detail" @click.prevent="openDrawer('docker-detail')">
            <div class="k">容器未运行</div>
            <b :class="{ warn: dockerDown > 0 }">{{ healthReady ? dockerDown : '—' }}</b>
          </a>
        </div>
      </section>

      <section class="card mod span-7">
        <header class="mod-head">
          <span class="mid">M07</span>
          <span class="mod-title">Docker</span>
          <a class="mod-link push" href="#docker-detail" @click.prevent="openDrawer('docker-detail')">全部</a>
        </header>
        <div class="sum-row">
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
        <div class="top-switch">
          <span class="k">资源 Top</span>
          <button type="button" class="chip" :class="{ on: topMetric === 'cpu' }" @click="topMetric = 'cpu'">按 CPU</button>
          <button type="button" class="chip" :class="{ on: topMetric === 'mem' }" @click="topMetric = 'mem'">按内存</button>
        </div>
        <div v-if="topContainers.length" class="ctr-list">
          <div class="ctr ctr-head">
            <span></span><span></span><span></span>
            <span class="stat">CPU</span>
            <span class="stat">MEM</span>
          </div>
          <div
            v-for="c in topContainers"
            :key="c.id"
            class="ctr"
            :class="{ hot: c.hot }"
            :title="c.image || c.status"
          >
            <span class="rank">{{ c.rank }}</span>
            <i class="ctr-dot" :class="ctrDot(c.state)"></i>
            <span class="name">{{ c.name }}</span>
            <span class="stat">{{ c.cpu_pct != null ? formatPct(c.cpu_pct) + '%' : '—' }}</span>
            <span class="stat">{{ formatMemShort(c.mem_usage_bytes) }}</span>
          </div>
        </div>
        <div v-else class="empty">暂无数据</div>
      </section>

      <section class="card mod span-5">
        <header class="mod-head">
          <span class="mid">M08</span>
          <span class="mod-title">存储池</span>
          <span class="io-note push">{{ diskIoText || '按使用率 · 读写暂无数据' }}</span>
          <a class="mod-link" href="#disk-detail" @click.prevent="openDrawer('disk-detail')">全部</a>
        </header>
        <div v-if="filesystems.length" class="pool-row">
          <div v-for="fs in filesystems" :key="fs.id" class="pool">
            <div class="pool-name">{{ fs.mount }}</div>
            <div class="pool-fig">
              <b>{{ formatBytes(fs.used_bytes) }}</b>
              <span>/ {{ formatBytes(fs.total_bytes) }}</span>
            </div>
            <div class="seg sm" :class="barColor(fs.used_pct)" :style="{ '--p': clampPct(fs.used_pct) + '%' }"></div>
            <div class="pool-pct" :class="barColor(fs.used_pct)">{{ formatPct(fs.used_pct, 0) }}%</div>
          </div>
        </div>
        <div v-else class="empty">暂无挂载数据</div>
      </section>

      <section class="card mod span-12">
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
      </section>
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
.seg.teal { --bar: #3dcec6; }
.seg.warn { --bar: #f5b14a; }
.seg.crit { --bar: #fb7185; }
.seg.sm { height: 8px; }

.trend-wrap { flex: 1; min-height: 120px; }
.trend { width: 100%; height: 128px; display: block; }
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
.chip.on { background: #e7f6f4; color: var(--teal-ink); }
.scale-note { margin: 0; color: #9aa3b2; font-size: 0.72rem; }
.age.stale {
  color: #b45309;
  background: var(--warn-bg);
  border-radius: 999px;
  padding: 2px 8px;
}

.net-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.net-svg { width: 100%; height: 72px; display: block; margin-top: 6px; }
.net-v {
  margin-top: 2px;
  font-size: 1.2rem;
  font-weight: 650;
  letter-spacing: -0.03em;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
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

.cpu-body {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}
.donut-wrap { position: relative; width: 132px; height: 132px; flex: none; }
.donut { width: 132px; height: 132px; }
.donut-label {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  align-content: center;
  text-align: center;
}
.donut-label strong {
  font-size: 1.35rem;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}
.donut-label span { color: var(--muted); font-size: 0.75rem; }
.cpu-side { display: grid; gap: 8px; min-width: 0; }
.cpu-temp {
  font-size: 1.8rem;
  font-weight: 700;
  letter-spacing: -0.04em;
  color: #f08a3a;
  font-variant-numeric: tabular-nums;
}
.load-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.load-pills span {
  background: #f4f6f8;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 0.8rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.core-row { display: flex; gap: 6px; align-items: flex-end; flex-wrap: wrap; }
.core {
  width: 22px;
  height: 36px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  font-size: 0.62rem;
  color: #607086;
  font-variant-numeric: tabular-nums;
}
.core i {
  display: block;
  width: 8px;
  background: #3dcec6;
  border-radius: 99px;
  margin-bottom: 2px;
  min-height: 2px;
}
.fold {
  justify-self: start;
  border: 0;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0;
  cursor: pointer;
}
.fold:disabled { cursor: default; }
.fold span { margin-left: 6px; color: var(--teal-ink); }
.temp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.temp-list li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 0.78rem;
}
.temp-list span { color: var(--muted); overflow: hidden; text-overflow: ellipsis; }
.temp-list b { font-variant-numeric: tabular-nums; }
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
.sum-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.sum {
  background: #f6f8fa;
  border-radius: 14px;
  padding: 8px 12px;
}
.sum b {
  display: block;
  font-size: 1.55rem;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
}
.sum span { color: var(--muted); font-size: 0.75rem; font-weight: 700; }
.sum.stop b { color: var(--crit); }
.top-switch { display: flex; align-items: center; gap: 8px; }
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
  overflow: auto;
  max-height: 280px;
  margin: 0 -4px;
  padding-right: 4px;
}
.ctr {
  display: grid;
  grid-template-columns: 18px 12px minmax(0, 1fr) 64px 56px;
  gap: 8px;
  align-items: center;
  padding: 5px 2px;
  font-size: 0.92rem;
  border-radius: 8px;
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
.stat {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #4b5568;
  font-size: 0.84rem;
}

.pool-row { display: flex; flex-wrap: wrap; gap: 14px 18px; }
.pool { flex: 1 1 150px; min-width: 140px; display: grid; gap: 4px; }
.pool-name { font-weight: 700; }
.pool-fig { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.pool-fig b { font-size: 1.05rem; font-variant-numeric: tabular-nums; }
.pool-fig span, .pool-pct { color: var(--muted); font-size: 0.82rem; }
.pool-pct.warn { color: #b45309; font-weight: 800; }
.pool-pct.crit { color: var(--crit); font-weight: 800; }

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

@media (max-width: 1100px) {
  .span-3, .span-4 { grid-column: span 6; }
  .span-5, .span-7, .span-8, .span-12 { grid-column: span 12; }
  .health-sum { text-align: left; }
}

@media (max-width: 720px) {
  .span-3, .span-4, .span-5, .span-7, .span-8, .span-12 { grid-column: span 12; }
  .clock { font-size: 2.3rem; }
  .health-row, .sum-row { grid-template-columns: 1fr; }
}
</style>
