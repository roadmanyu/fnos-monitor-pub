<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api/client'
import {
  clampPct,
  formatBytes,
  formatClock,
  formatDateLine,
  formatMemShort,
  formatPct,
  formatTs
} from '../utils/format'

const snap = ref(null)
const meta = ref(null)
const cpuHist = ref([])
const memHist = ref([])
const alerts = ref([])
const containers = ref([])
const err = ref('')
const now = ref(new Date())
let poll
let clock

const tz = computed(() => meta.value?.timezone_display || 'Asia/Shanghai')
const host = computed(() => snap.value?.host || {})
const filesystems = computed(() => snap.value?.filesystems || [])
const disks = computed(() => snap.value?.disks_smart_summary || [])
const cpuTemp = computed(() => host.value?.temps_c?.cpu ?? null)

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

const sortedContainers = computed(() => {
  return [...containers.value].sort((a, b) => {
    const ar = (a.state || '').toLowerCase() === 'running' ? 0 : 1
    const br = (b.state || '').toLowerCase() === 'running' ? 0 : 1
    if (ar !== br) return ar - br
    return String(a.name || '').localeCompare(String(b.name || ''))
  })
})

const dockerAllOk = computed(() => {
  if (!containers.value.length) return null
  return containers.value.every((c) => (c.state || '').toLowerCase() === 'running')
})

const trend = computed(() => buildTrend(cpuHist.value, memHist.value))

async function load() {
  try {
    const [m, s, a] = await Promise.all([
      api('/meta'),
      api('/metrics/snapshot'),
      api('/alerts?limit=3').then((r) => r.items || [])
    ])
    meta.value = m
    snap.value = s
    alerts.value = a
    err.value = ''
  } catch (e) {
    err.value = e.message || '加载失败'
  }
  try {
    const [cpu, mem, dock] = await Promise.all([
      api('/metrics/history?metric=cpu.pct&step=60'),
      api('/metrics/history?metric=mem.used_pct&step=60'),
      api('/docker/containers')
    ])
    cpuHist.value = cpu.points || []
    memHist.value = mem.points || []
    containers.value = dock.containers || []
  } catch (e) {
    if (!err.value) err.value = e.message || '加载失败'
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

onMounted(() => {
  load()
  poll = setInterval(load, 30000)
  clock = setInterval(() => { now.value = new Date() }, 1000)
})
onUnmounted(() => {
  clearInterval(poll)
  clearInterval(clock)
})

function buildTrend(cpuPoints, memPoints) {
  const w = 320
  const h = 112
  const memMap = new Map((memPoints || []).map((p) => [p.ts, Number(p.value)]))
  let rows = (cpuPoints || []).map((p) => ({
    cpu: Number(p.value),
    mem: memMap.has(p.ts) ? memMap.get(p.ts) : null
  }))
  if (!rows.length && (memPoints || []).length) {
    rows = memPoints.map((p) => ({ cpu: null, mem: Number(p.value) }))
  }
  const cpuLine = linePath(rows.map((r) => r.cpu), w, h)
  return {
    has: rows.some((r) => r.cpu != null || r.mem != null),
    cpu: cpuLine,
    mem: linePath(rows.map((r) => r.mem), w, h),
    area: cpuLine ? `${cpuLine} L ${w} ${h} L 0 ${h} Z` : ''
  }
}

function linePath(values, w, h) {
  const n = values.length
  const pts = values
    .map((v, i) => ({ v: Number(v), i }))
    .filter((p) => p.v != null && !Number.isNaN(p.v))
  if (!pts.length || !n) return ''
  const yOf = (v) => h - (clampPct(v) / 100) * (h - 10) - 4
  if (pts.length === 1) {
    const y = yOf(pts[0].v).toFixed(1)
    return `M0 ${y} L${w} ${y}`
  }
  return pts
    .map((p) => {
      const x = (p.i / (n - 1)) * w
      return [x, yOf(p.v)]
    })
    .map((c, i) => `${i ? 'L' : 'M'}${c[0].toFixed(1)} ${c[1].toFixed(1)}`)
    .join(' ')
}
</script>

<template>
  <div class="page dash">
    <p v-if="err" class="err-banner">{{ err }}</p>
    <p v-else-if="!snap" class="muted">正在加载…</p>

    <div class="modules">
      <section class="card mod">
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
          <div class="fact">
            <span>采集</span>
            <b>{{ formatTs(meta?.last_collect_ts || snap?.ts, tz) }}</b>
          </div>
          <div class="fact">
            <span>版本</span>
            <b>{{ meta?.app_version || '—' }}</b>
          </div>
        </div>
      </section>

      <section class="card mod">
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
            <b class="na">暂无数据</b>
          </div>
          <div class="seg swap" style="--p: 0%"></div>
        </div>
      </section>

      <section class="card mod">
        <header class="mod-head">
          <span class="mid">M03</span>
          <span class="mod-title">趋势</span>
          <span class="pill muted head-pill push">近 1 小时</span>
        </header>
        <div v-if="trend.has" class="trend-wrap">
          <svg viewBox="0 0 320 112" class="trend" preserveAspectRatio="none">
            <defs>
              <linearGradient id="cpuFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#2ec9c0" stop-opacity="0.32" />
                <stop offset="100%" stop-color="#2ec9c0" stop-opacity="0.02" />
              </linearGradient>
            </defs>
            <line v-for="i in 3" :key="i" x1="0" :y1="i * 28" x2="320" :y2="i * 28" stroke="#eef1f4" />
            <path :d="trend.area" fill="url(#cpuFill)" stroke="none" />
            <path :d="trend.mem" fill="none" stroke="#f062b0" stroke-width="2" vector-effect="non-scaling-stroke" />
            <path :d="trend.cpu" fill="none" stroke="#2ec9c0" stroke-width="2.2" vector-effect="non-scaling-stroke" />
          </svg>
        </div>
        <div v-else class="empty">暂无趋势数据</div>
        <div class="legend">
          <span><i class="swatch cpu"></i>CPU {{ formatPct(host.cpu_pct) }}%</span>
          <span><i class="swatch mem"></i>MEM {{ formatPct(host.mem_used_pct) }}%</span>
        </div>
      </section>

      <section class="card mod">
        <header class="mod-head">
          <span class="mid">M04</span>
          <span class="mod-title">网络</span>
        </header>
        <div class="net-stats">
          <div>
            <div class="k">↑ UPLOAD</div>
            <div class="net-v">—</div>
          </div>
          <div>
            <div class="k">↓ DOWNLOAD</div>
            <div class="net-v">—</div>
          </div>
        </div>
        <div class="empty grow">暂无数据</div>
      </section>

      <section class="card mod">
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
          </div>
        </div>
      </section>

      <section class="card mod">
        <header class="mod-head">
          <span class="mid">M07</span>
          <span class="mod-title">Docker</span>
          <span class="pill muted head-pill push">{{ containers.length }} CTN</span>
          <span v-if="dockerAllOk === true" class="pill ok head-pill"><i class="dot"></i>全部正常</span>
          <span v-else-if="dockerAllOk === false" class="pill warn head-pill">有容器未运行</span>
          <router-link class="mod-link" to="/docker">全部</router-link>
        </header>
        <div v-if="sortedContainers.length" class="ctr-list">
          <div class="ctr ctr-head">
            <span></span><span></span>
            <span class="stat">CPU</span>
            <span class="stat">MEM</span>
          </div>
          <div v-for="c in sortedContainers" :key="c.id" class="ctr" :title="c.image || c.status">
            <i class="ctr-dot" :class="ctrDot(c.state)"></i>
            <span class="name">{{ c.name }}</span>
            <span class="stat">{{ c.cpu_pct != null ? formatPct(c.cpu_pct) + '%' : '—' }}</span>
            <span class="stat">{{ formatMemShort(c.mem_usage_bytes) }}</span>
          </div>
        </div>
        <div v-else class="empty">暂无数据</div>
      </section>

      <section class="card mod">
        <header class="mod-head">
          <span class="mid">M08</span>
          <span class="mod-title">存储池</span>
          <span class="io-note push">读写 暂无数据</span>
          <router-link class="mod-link" to="/disks">全部</router-link>
        </header>
        <div v-if="filesystems.length" class="pool-row">
          <div v-for="fs in filesystems" :key="fs.id" class="pool">
            <div class="pool-name">{{ fs.mount }}</div>
            <div class="pool-fig">
              <b>{{ formatBytes(fs.used_bytes) }}</b>
              <span>/ {{ formatBytes(fs.total_bytes) }}</span>
            </div>
            <div class="seg sm" :class="barColor(fs.used_pct)" :style="{ '--p': clampPct(fs.used_pct) + '%' }"></div>
            <div class="pool-pct">{{ formatPct(fs.used_pct, 0) }}%</div>
          </div>
        </div>
        <div v-else class="empty">暂无挂载数据</div>
      </section>

      <section class="card mod">
        <header class="mod-head">
          <span class="mid">M09</span>
          <span class="mod-title">硬盘</span>
          <span class="pill muted head-pill push">{{ disks.length }} DISKS</span>
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

      <section class="card mod alerts">
        <header class="mod-head">
          <span class="mod-title">最近告警</span>
          <router-link class="mod-link push" to="/alerts">全部</router-link>
        </header>
        <div v-if="alerts.length" class="alert-list">
          <div v-for="a in alerts" :key="a.id" class="alert-row">
            <span class="badge" :class="a.severity === 'critical' ? 'crit' : 'warn'">{{ a.severity }}</span>
            <span class="alert-title">{{ a.title }}</span>
            <span class="muted">{{ a.message }}</span>
          </div>
        </div>
        <p v-else class="muted empty-inline">暂无告警</p>
      </section>
    </div>
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

.modules > .mod:nth-child(1),
.modules > .mod:nth-child(2),
.modules > .mod:nth-child(3),
.modules > .mod:nth-child(4) { grid-column: span 3; }

.modules > .mod:nth-child(5) { grid-column: span 4; }
.modules > .mod:nth-child(6) { grid-column: span 8; }
.modules > .mod:nth-child(7) { grid-column: span 7; }
.modules > .mod:nth-child(8) { grid-column: span 5; }
.modules > .mod:nth-child(9) { grid-column: span 12; }

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

.net-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.net-v {
  margin-top: 2px;
  font-size: 1.7rem;
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

.ctr-list {
  overflow: auto;
  max-height: 280px;
  margin: 0 -4px;
  padding-right: 4px;
}
.ctr {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) 64px 56px;
  gap: 8px;
  align-items: center;
  padding: 5px 2px;
  font-size: 0.92rem;
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
  .modules > .mod:nth-child(1),
  .modules > .mod:nth-child(2),
  .modules > .mod:nth-child(3),
  .modules > .mod:nth-child(4),
  .modules > .mod:nth-child(5) { grid-column: span 6; }
  .modules > .mod:nth-child(6),
  .modules > .mod:nth-child(7),
  .modules > .mod:nth-child(8) { grid-column: span 12; }
}

@media (max-width: 720px) {
  .modules > .mod { grid-column: span 12 !important; }
  .clock { font-size: 2.3rem; }
}
</style>
