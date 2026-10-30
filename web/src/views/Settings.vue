<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api/client'

const meta = ref(null)
const channels = ref(null)
const err = ref('')

onMounted(async () => {
  try {
    ;[meta.value, channels.value] = await Promise.all([api('/meta'), api('/alerts/channels')])
  } catch (e) {
    err.value = e.message
  }
})
</script>

<template>
  <div class="page">
    <h2>设置</h2>
    <p v-if="err" style="color:var(--crit)">{{ err }}</p>
    <div class="card">
      <h3>服务</h3>
      <p v-if="meta">版本 {{ meta.app_version }} · API {{ meta.api_version }}</p>
      <p class="muted">采集周期 {{ meta?.collect_interval_sec }}s · 展示时区 {{ meta?.timezone_display }}</p>
      <p class="muted">修改账号/告警通道请编辑 NAS 上的 <code>config.yaml</code> 后重启容器。</p>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>告警通道</h3>
      <p>已配置 {{ channels?.count ?? 0 }} 条 Apprise URL</p>
      <ul>
        <li v-for="(c, i) in (channels?.channels || [])" :key="i">{{ c.type }} · 已配置</li>
      </ul>
      <p class="muted">{{ channels?.note }}</p>
      <p class="muted">支持：{{ (channels?.supported || []).join('、') }}</p>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>安全提示</h3>
      <p class="muted">当前设计为<strong>仅局域网</strong>访问。请勿将 8787 端口直接映射到公网。</p>
    </div>
  </div>
</template>
