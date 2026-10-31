<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import {
  hasToken,
  loginProfile,
  nas,
  normalizeBaseUrl,
  removeProfile,
  setActive,
  tabState,
  updateProfile,
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
const editingId = ref('')
const editForm = ref({ name: '', baseUrl: '' })
const editErr = ref('')
const reloginId = ref('')
const reloginForm = ref({ username: 'admin', password: '' })
const reloginErr = ref('')
const reloginBusy = ref(false)

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

function statusText(id) {
  const state = tabState(id)
  if (state === 'offline') return '离线'
  if (state === 'logged-out') return '未登录'
  return '已登录'
}

function startEdit(p) {
  editingId.value = p.id
  editForm.value = { name: p.name, baseUrl: p.baseUrl || '' }
  editErr.value = ''
  reloginId.value = ''
}

function saveEdit(p) {
  editErr.value = ''
  try {
    const urlChanged = updateProfile(p.id, {
      name: editForm.value.name,
      baseUrl: p.id === 'local' ? '' : editForm.value.baseUrl
    })
    editingId.value = ''
    if (urlChanged) {
      formMsg.value = `「${editForm.value.name || p.name}」地址已更改，请重新登录。`
      reloginId.value = p.id
      reloginForm.value = { username: 'admin', password: '' }
    }
  } catch {
    editErr.value = '地址需要是 http://局域网IP:8787'
  }
}

function startRelogin(p) {
  reloginId.value = p.id
  reloginErr.value = ''
  reloginForm.value = { username: 'admin', password: '' }
  editingId.value = ''
}

async function doRelogin(p) {
  reloginErr.value = ''
  reloginBusy.value = true
  try {
    await loginProfile(p, reloginForm.value.username, reloginForm.value.password)
    reloginForm.value.password = ''
    reloginId.value = ''
    setActive(p.id)
    router.push('/')
  } catch (e) {
    reloginErr.value = e.message || '登录失败'
  } finally {
    reloginBusy.value = false
  }
}

function askRemove(p) {
  if (window.confirm(`移除「${p.name}」？这台浏览器里的登录状态会一起清掉。`)) {
    removeProfile(p.id)
  }
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
    await loginProfile(profile, form.value.username, form.value.password)
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
        <span class="pill" :class="tabState(p.id) === 'online' ? 'ok' : 'muted'">{{ statusText(p.id) }}</span>
        <button class="btn ghost" type="button" @click="openNas(p.id)">打开</button>
        <button class="btn ghost" type="button" @click="startEdit(p)">编辑</button>
        <button class="btn ghost" type="button" @click="startRelogin(p)">重新登录</button>
        <button v-if="p.id !== 'local'" class="btn ghost" type="button" @click="askRemove(p)">移除</button>
        <form v-if="editingId === p.id" class="add-form nas-edit" @submit.prevent="saveEdit(p)">
          <label>显示名<input v-model="editForm.name" /></label>
          <label v-if="p.id !== 'local'">API 地址<input v-model="editForm.baseUrl" placeholder="http://192.168.1.8:8787" /></label>
          <p v-if="editErr" style="color:var(--crit);margin:0">{{ editErr }}</p>
          <div class="row-actions">
            <button class="btn" type="submit">保存</button>
            <button class="btn ghost" type="button" @click="editingId = ''">取消</button>
          </div>
        </form>
        <form v-if="reloginId === p.id" class="add-form nas-edit" @submit.prevent="doRelogin(p)">
          <label>用户名<input v-model="reloginForm.username" autocomplete="username" /></label>
          <label>密码<input v-model="reloginForm.password" type="password" autocomplete="current-password" /></label>
          <p v-if="reloginErr" style="color:var(--crit);margin:0">{{ reloginErr }}</p>
          <div class="row-actions">
            <button class="btn" type="submit" :disabled="reloginBusy">{{ reloginBusy ? '登录中…' : '登录' }}</button>
            <button class="btn ghost" type="button" @click="reloginId = ''">取消</button>
          </div>
        </form>
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
.nas-edit { flex: 1 0 100%; }
.row-actions { display: flex; gap: 8px; }
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
