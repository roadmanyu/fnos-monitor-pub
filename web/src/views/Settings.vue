<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import {
  hasToken,
  nas,
  normalizeBaseUrl,
  removeProfile,
  setActive,
  setToken,
  upsertProfile
} from '../nas/profiles'

const route = useRoute()
const router = useRouter()
const meta = ref(null)
const channels = ref(null)
const err = ref('')
const form = ref({ name: '', baseUrl: '', username: 'admin', password: '' })
const formErr = ref('')
const formMsg = ref('')
const saving = ref(false)

async function loadPage() {
  try {
    ;[meta.value, channels.value] = await Promise.all([api('/meta'), api('/alerts/channels')])
    err.value = ''
  } catch (e) {
    err.value = e.message
  }
}

function openNas(id) {
  setActive(id)
  router.push(hasToken(id) ? '/' : '/login')
}

async function addNas() {
  formErr.value = ''
  formMsg.value = ''
  let base = ''
  try {
    base = normalizeBaseUrl(form.value.baseUrl)
  } catch {
    formErr.value = '地址需要是 http://局域网IP:8787'
    return
  }
  const id = `nas-${Math.random().toString(36).slice(2, 8)}`
  const profile = upsertProfile({
    id,
    name: (form.value.name || '').trim() || base,
    baseUrl: base
  })
  saving.value = true
  try {
    const res = await fetch(`${base}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: form.value.username,
        password: form.value.password
      })
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      const detail = data?.detail
      const msg = (detail && typeof detail === 'object' ? detail.message : detail) || data?.message || '登录失败'
      throw new Error(typeof msg === 'string' ? msg : '登录失败')
    }
    setToken(data.access_token, profile.id)
    setActive(profile.id)
    form.value.password = ''
    router.push('/')
  } catch (e) {
    formErr.value = `${e.message || '登录失败'}。地址已保存，可稍后从标签进入登录页。`
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadPage()
  if (route.hash === '#add-nas') {
    await nextTick()
    document.getElementById('add-nas')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
})
watch(() => nas.activeId, loadPage)
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
    <div id="add-nas" class="card" style="margin-top:16px">
      <h3>多台 NAS</h3>
      <p class="muted">每台机器各自运行一份监控。这里只保存局域网地址和登录令牌，不会从一台去采集另一台。令牌留在这台浏览器里，不保存密码。</p>
      <div v-for="p in nas.profiles" :key="p.id" class="nas-row">
        <div>
          <b>{{ p.name }}</b>
          <div class="muted">{{ p.baseUrl || '当前站点' }}</div>
        </div>
        <span class="pill" :class="hasToken(p.id) ? 'ok' : 'muted'">{{ hasToken(p.id) ? '已登录' : '未登录' }}</span>
        <button class="btn ghost" type="button" @click="openNas(p.id)">打开</button>
        <button v-if="p.id !== 'local'" class="btn ghost" type="button" @click="removeProfile(p.id)">移除</button>
      </div>
      <form class="add-form" @submit.prevent="addNas">
        <label>显示名<input v-model="form.name" placeholder="客厅" /></label>
        <label>API 地址<input v-model="form.baseUrl" placeholder="http://192.168.1.8:8787" /></label>
        <label>用户名<input v-model="form.username" autocomplete="username" /></label>
        <label>密码<input v-model="form.password" type="password" autocomplete="current-password" /></label>
        <p v-if="formErr" style="color:var(--crit);margin:0">{{ formErr }}</p>
        <p v-if="formMsg" class="muted">{{ formMsg }}</p>
        <button class="btn" type="submit" :disabled="saving">{{ saving ? '登录中…' : '添加并登录' }}</button>
      </form>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>安全提示</h3>
      <p class="muted">当前设计为<strong>仅局域网</strong>访问。请勿将 8787 端口直接映射到公网。</p>
    </div>
  </div>
</template>

<style scoped>
.nas-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.nas-row .muted { font-size: 0.8rem; }
.add-form {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}
.add-form label {
  display: grid;
  gap: 4px;
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--muted);
}
</style>
