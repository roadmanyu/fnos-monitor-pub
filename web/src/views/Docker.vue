<script setup>
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { api } from '../api/client'

defineProps({ embedded: { type: Boolean, default: false } })

const containers = ref([])
const filter = ref('all')
const err = ref('')
let timer

const filtered = computed(() => {
  if (filter.value === 'running') return containers.value.filter(c => c.state === 'running')
  return containers.value
})

async function load() {
  try {
    const r = await api('/docker/containers')
    containers.value = r.containers || []
    err.value = ''
  } catch (e) {
    err.value = e.message
  }
}

onMounted(() => { load(); timer = setInterval(load, 30000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div :class="embedded ? 'embed' : 'page'">
    <h2 v-if="!embedded">Docker</h2>
    <p v-if="err" style="color:var(--crit)">{{ err }}</p>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <button class="btn" :class="filter==='all'?'':'ghost'" @click="filter='all'">全部</button>
      <button class="btn" :class="filter==='running'?'':'ghost'" @click="filter='running'">运行中</button>
    </div>
    <div class="card table-card">
      <table>
        <thead>
          <tr><th>名称</th><th>状态</th><th>镜像</th><th>重启</th><th>CPU</th><th>内存</th></tr>
        </thead>
        <tbody>
          <tr v-for="c in filtered" :key="c.id">
            <td>{{ c.name }}</td>
            <td>
              <span class="badge" :class="c.state==='running'?'ok':c.state==='exited'?'crit':'muted'">{{ c.state }}</span>
            </td>
            <td class="muted">{{ c.image }}</td>
            <td>{{ c.restart_count }}</td>
            <td>{{ c.cpu_pct != null ? c.cpu_pct + '%' : '—' }}</td>
            <td>{{ c.mem_usage_bytes != null ? (c.mem_usage_bytes/1024/1024).toFixed(0) + ' MB' : '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!filtered.length" class="muted">无容器</p>
    </div>
  </div>
</template>
