<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api/client'

const data = ref({ filesystems: [], smart: [] })
const detail = ref(null)
const err = ref('')

async function load() {
  try {
    data.value = await api('/disks')
  } catch (e) {
    err.value = e.message
  }
}

async function openSmart(id) {
  try {
    detail.value = await api(`/disks/${id}/smart`)
  } catch (e) {
    err.value = e.message
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2>磁盘</h2>
    <p v-if="err" style="color:var(--crit)">{{ err }}</p>
    <div class="card">
      <h3>容量</h3>
      <table>
        <thead><tr><th>挂载</th><th>设备</th><th>使用率</th></tr></thead>
        <tbody>
          <tr v-for="fs in data.filesystems" :key="fs.id">
            <td>{{ fs.mount }}</td>
            <td class="muted">{{ fs.device }}</td>
            <td>{{ fs.used_pct }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>SMART</h3>
      <table>
        <thead><tr><th>盘</th><th>型号</th><th>健康</th><th>温度</th><th>通电</th><th></th></tr></thead>
        <tbody>
          <tr v-for="d in data.smart" :key="d.id">
            <td>{{ d.id }}</td>
            <td class="muted">{{ d.model || '—' }}</td>
            <td>
              <span v-if="d.skipped_standby" class="badge muted">standby</span>
              <span v-else class="badge" :class="d.healthy === false ? 'crit' : 'ok'">
                {{ d.healthy === false ? '异常' : '正常' }}
              </span>
            </td>
            <td>{{ d.temp_c != null ? d.temp_c + '°C' : '—' }}</td>
            <td>{{ d.power_on_hours ?? '—' }} h</td>
            <td><button class="btn ghost" @click="openSmart(d.id)">详情</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="detail" class="card" style="margin-top:16px">
      <h3>{{ detail.id }} 属性</h3>
      <p class="muted">更新 {{ detail.raw_updated_ts }}</p>
      <table>
        <thead><tr><th>ID</th><th>名称</th><th>RAW</th><th>Worst</th></tr></thead>
        <tbody>
          <tr v-for="a in detail.attrs" :key="a.id + a.name">
            <td>{{ a.id }}</td><td>{{ a.name }}</td><td>{{ a.raw }}</td><td>{{ a.worst }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!(detail.attrs || []).length" class="muted">无属性（可能为 mock / standby）</p>
      <button class="btn ghost" style="margin-top:8px" @click="detail=null">关闭</button>
    </div>
  </div>
</template>
