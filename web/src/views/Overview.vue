<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api/client'

const snap = ref(null)
const meta = ref(null)
const hist = ref([])
const alerts = ref([])
const err = ref('')
let timer

async function load() {
  try {
    ;[meta.value, snap.value, alerts.value] = await Promise.all([
      api('/meta'),
      api('/metrics/snapshot'),
      api('/alerts?limit=3').then(r => r.items || [])
    ])
    const h = await api('/metrics/history?metric=cpu.pct&step=60')
    hist.value = h.points || []
    err.value = ''
  } catch (e) {
    err.value = e.message
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, 30000)
})
onUnmounted(() => clearInterval(timer))

function pctBar(v) {
  return Math.min(100, Math.max(0, Number(v) || 0))
}
</script>

<template>
  <div class="page">
    <h2>概览</h2>
    <p v-if="err" style="color:var(--crit)">{{ err }}</p>
    <p class="muted" v-if="meta">
      {{ meta.hostname }} · 采集 {{ meta.last_collect_ts || '—' }}
      <span v-if="meta.mock_mode"> · <span class="badge warn">模拟数据</span></span>
    </p>
    <div class="grid" style="margin-top:12px" v-if="snap">
      <div class="card">
        <div class="muted">CPU</div>
        <div style="font-size:1.6rem;font-weight:700">{{ snap.host?.cpu_pct ?? '—' }}%</div>
      </div>
      <div class="card">
        <div class="muted">内存</div>
        <div style="font-size:1.6rem;font-weight:700">{{ snap.host?.mem_used_pct ?? '—' }}%</div>
      </div>
      <div class="card">
        <div class="muted">负载 1m</div>
        <div style="font-size:1.6rem;font-weight:700">{{ snap.host?.load1 ?? '—' }}</div>
      </div>
      <div class="card">
        <div class="muted">CPU 温度</div>
        <div style="font-size:1.6rem;font-weight:700">
          {{ snap.host?.temps_c?.cpu != null ? snap.host.temps_c.cpu + '°C' : '—' }}
        </div>
      </div>
      <div class="card">
        <div class="muted">Docker</div>
        <div style="font-size:1.6rem;font-weight:700">
          {{ snap.docker?.running ?? 0 }}/{{ snap.docker?.total ?? 0 }}
        </div>
        <div class="muted">运行中</div>
      </div>
    </div>

    <div class="card" style="margin-top:16px" v-if="hist.length">
      <div class="muted" style="margin-bottom:8px">CPU 近 1 小时</div>
      <div class="spark">
        <i
          v-for="(p, i) in hist.slice(-60)"
          :key="i"
          :style="{ height: pctBar(p.value) + '%' }"
          :title="p.ts + ' ' + p.value + '%'"
        />
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="muted" style="margin-bottom:8px">磁盘使用</div>
      <div v-for="fs in (snap?.filesystems || [])" :key="fs.id" style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between">
          <span>{{ fs.mount }}</span>
          <span>{{ fs.used_pct }}%</span>
        </div>
        <div style="height:8px;background:#334155;border-radius:4px;overflow:hidden;margin-top:4px">
          <div :style="{ width: pctBar(fs.used_pct) + '%', height: '100%', background: fs.used_pct >= 95 ? 'var(--crit)' : fs.used_pct >= 85 ? 'var(--warn)' : 'var(--accent)' }" />
        </div>
      </div>
      <p v-if="!(snap?.filesystems || []).length" class="muted">暂无挂载数据</p>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="muted" style="margin-bottom:8px">最近告警</div>
      <div v-for="a in alerts" :key="a.id" style="margin-bottom:8px">
        <span class="badge" :class="a.severity === 'critical' ? 'crit' : 'warn'">{{ a.severity }}</span>
        {{ a.title }} — <span class="muted">{{ a.message }}</span>
      </div>
      <p v-if="!alerts.length" class="muted">暂无告警</p>
    </div>
  </div>
</template>
