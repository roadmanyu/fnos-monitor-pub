<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api/client'

const items = ref([])
const rules = ref(null)
const severity = ref('')
const err = ref('')

async function load() {
  try {
    const q = severity.value ? `?severity=${severity.value}` : ''
    const [a, r] = await Promise.all([api('/alerts' + q), api('/alerts/rules')])
    items.value = a.items || []
    rules.value = r
    err.value = ''
  } catch (e) {
    err.value = e.message
  }
}

async function ack(id) {
  await api(`/alerts/${id}/ack`, { method: 'POST' })
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2>告警</h2>
    <p v-if="err" style="color:var(--crit)">{{ err }}</p>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <button class="btn" :class="severity===''?'':'ghost'" @click="severity='';load()">全部</button>
      <button class="btn" :class="severity==='warning'?'':'ghost'" @click="severity='warning';load()">警告</button>
      <button class="btn" :class="severity==='critical'?'':'ghost'" @click="severity='critical';load()">紧急</button>
    </div>
    <div class="card">
      <div v-for="a in items" :key="a.id" style="padding:10px 0;border-bottom:1px solid var(--border)">
        <div>
          <span class="badge" :class="a.severity==='critical'?'crit':'warn'">{{ a.severity }}</span>
          <strong style="margin-left:6px">{{ a.title }}</strong>
          <span v-if="a.acked" class="badge muted" style="margin-left:6px">已确认</span>
        </div>
        <div class="muted">{{ a.ts }} · {{ a.message }}</div>
        <button v-if="!a.acked" class="btn ghost" style="margin-top:6px" @click="ack(a.id)">确认</button>
      </div>
      <p v-if="!items.length" class="muted">暂无告警</p>
    </div>
    <div class="card" style="margin-top:16px" v-if="rules">
      <h3>规则说明（只读）</h3>
      <ul>
        <li v-for="d in rules.descriptions" :key="d.id"><code>{{ d.id }}</code> — {{ d.when }}</li>
      </ul>
    </div>
  </div>
</template>
