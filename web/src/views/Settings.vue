<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useClipboard } from '@vueuse/core'
import QRCode from 'qrcode'
import {
  Bell,
  Copy,
  Gauge,
  KeyRound,
  Palette,
  Server,
  SlidersHorizontal
} from 'lucide-vue-next'
import { api } from '../api/client'
import { formatCapacity } from '../utils/capacity'
import { carousel, patchCarousel } from '../nas/carouselStore'
import { connectionTarget } from '../nas/connection'
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

const sections = [
  { id: 'auth', label: '认证', icon: KeyRound },
  { id: 'nodes', label: '节点', icon: Server },
  { id: 'collect', label: '采集', icon: Gauge },
  { id: 'alerts', label: '告警', icon: Bell },
  { id: 'calibration', label: '展示校准', icon: Palette },
  { id: 'advanced', label: '高级', icon: SlidersHorizontal }
]

const route = useRoute()
const router = useRouter()
const colorMode = inject('colorMode', null)
const meta = ref(null)
const channels = ref(null)
const rules = ref([])
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
const capacity = ref({ unit: 'gib', decimals: 1, source: 'config', config_unit: 'gib', config_decimals: 1 })
const diskRows = ref([])
const fanRows = ref([])
const calErr = ref('')
const calMsg = ref('')
const savingCap = ref(false)
const savingDisks = ref(false)
const savingFans = ref(false)
const tuneItems = ref([])
const tuneDraft = ref({})
const tuneErr = ref('')
const tuneMsg = ref('')
const savingTune = ref(false)
const section = ref('auth')
const qrFor = ref({})
const copiedKey = ref('')
const { copy } = useClipboard({ copiedDuring: 1600 })

const ROLE_PRESETS = ['系统盘', '缓存', '外接', 'none']
const MEDIA_PRESETS = ['HDD', 'SSD']
const IFACE_PRESETS = ['SATA', 'SAS', 'NVMe', 'USB']
const SAMPLE_BYTES = 4000787030016
const SAMPLE_LABEL = 4000000000000

const capacityPreview = computed(() => {
  const sample = diskRows.value.find((d) => d.capacity_bytes != null) || null
  const bytes = sample?.capacity_bytes ?? SAMPLE_BYTES
  const label = sample?.label_bytes ?? SAMPLE_LABEL
  return formatCapacity(bytes, capacity.value, label)
})

const localUrl = computed(() => connectionTarget('', window.location.origin))
const draftUrl = computed(() => {
  try { return normalizeBaseUrl(form.value.baseUrl) } catch { return '' }
})
const tuneGroups = computed(() => {
  const groups = []
  for (const item of tuneItems.value) {
    let group = groups.find((entry) => entry.name === item.group)
    if (!group) {
      group = { name: item.group, items: [] }
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
})

function listedMode(value, presets) {
  if (!value) return ''
  return presets.includes(value) ? value : '__custom__'
}

function mapDisks(items) {
  return (items || []).map((disk) => {
    const role = disk.role_override || ''
    const media = disk.media_override || ''
    const iface = disk.interface_override || ''
    return {
      ...disk,
      visible: disk.visible !== false,
      label: disk.label || '',
      roleMode: listedMode(role, ROLE_PRESETS),
      roleCustom: listedMode(role, ROLE_PRESETS) === '__custom__' ? role : '',
      mediaMode: listedMode(media, MEDIA_PRESETS),
      mediaCustom: listedMode(media, MEDIA_PRESETS) === '__custom__' ? media : '',
      ifaceMode: listedMode(iface, IFACE_PRESETS),
      ifaceCustom: listedMode(iface, IFACE_PRESETS) === '__custom__' ? iface : '',
      sort_order: disk.sort_order || 0
    }
  })
}

function mapFans(items) {
  return (items || []).map((fan) => ({
    ...fan,
    roleMode: fan.role_override || '',
    primary: !!fan.primary,
    excluded: !!fan.excluded
  }))
}

function applyCalibration(payload) {
  capacity.value = {
    unit: payload?.capacity?.unit || 'gib',
    decimals: payload?.capacity?.decimals ?? 1,
    source: payload?.capacity?.source || 'config',
    config_unit: payload?.capacity?.config_unit || 'gib',
    config_decimals: payload?.capacity?.config_decimals ?? 1
  }
  diskRows.value = mapDisks(payload?.disks)
  fanRows.value = mapFans(payload?.fans)
}

function applyTune(payload) {
  tuneItems.value = payload?.items || []
  const draft = {}
  for (const item of tuneItems.value) draft[item.key] = item.value
  tuneDraft.value = draft
}

function picked(mode, custom) {
  if (mode === '__custom__') return (custom || '').trim()
  return mode || ''
}

function setPrimary(key) {
  for (const fan of fanRows.value) {
    fan.primary = fan.channel_key === key && !fan.excluded
  }
}

function sectionFromHash(hash) {
  const id = String(hash || '').replace('#', '')
  if (id === 'add-nas' || id === 'nodes') return 'nodes'
  if (sections.some((item) => item.id === id)) return id
  return 'auth'
}

function openSection(id) {
  section.value = id
  const hash = `#${id}`
  if (route.hash !== hash) router.replace({ hash })
}

function setTheme(value) {
  if (colorMode) colorMode.value = value
}

function profileUrl(profile) {
  return connectionTarget(profile?.baseUrl, localUrl.value)
}

async function refreshQr() {
  const texts = new Set([localUrl.value, draftUrl.value])
  for (const profile of nas.profiles) texts.add(profileUrl(profile))
  const next = { ...qrFor.value }
  await Promise.all([...texts].filter(Boolean).map(async (text) => {
    if (next[text]) return
    next[text] = await QRCode.toDataURL(text, {
      margin: 1,
      width: 168,
      errorCorrectionLevel: 'M',
      color: { dark: '#1c2430', light: '#ffffff' }
    })
  }))
  qrFor.value = next
}

async function copyText(text) {
  copiedKey.value = ''
  try {
    await copy(text)
    copiedKey.value = text
  } catch {
    formErr.value = '复制失败，请手动选择连接串'
  }
}

async function loadPage() {
  try {
    const [info, channelInfo, calibration, tune, ruleInfo] = await Promise.all([
      api('/meta'),
      api('/alerts/channels'),
      api('/calibration'),
      api('/tuning'),
      api('/alerts/rules')
    ])
    meta.value = info
    channels.value = channelInfo
    rules.value = ruleInfo?.descriptions || []
    applyCalibration(calibration)
    applyTune(tune)
    err.value = ''
  } catch (e) {
    err.value = e.message
  }
}

async function saveCapacity() {
  calErr.value = ''
  calMsg.value = ''
  savingCap.value = true
  try {
    const saved = await api('/calibration/capacity', {
      method: 'PUT',
      body: JSON.stringify({ unit: capacity.value.unit, decimals: Number(capacity.value.decimals) })
    })
    capacity.value = { ...capacity.value, ...saved }
    calMsg.value = '容量显示已保存'
  } catch (e) {
    calErr.value = e.message || '保存失败'
  } finally {
    savingCap.value = false
  }
}

async function resetCapacity() {
  calErr.value = ''
  calMsg.value = ''
  savingCap.value = true
  try {
    const saved = await api('/calibration/capacity', { method: 'DELETE' })
    capacity.value = { ...capacity.value, ...saved }
    calMsg.value = '已改回配置文件里的容量默认值'
  } catch (e) {
    calErr.value = e.message || '保存失败'
  } finally {
    savingCap.value = false
  }
}

async function saveDisks() {
  calErr.value = ''
  calMsg.value = ''
  savingDisks.value = true
  try {
    const saved = await api('/calibration/disks', {
      method: 'PUT',
      body: JSON.stringify({
        items: diskRows.value.map((disk) => ({
          identity_key: disk.identity_key,
          serial: disk.serial || '',
          wwn: disk.wwn || '',
          visible: !!disk.visible,
          label: (disk.label || '').trim(),
          role: picked(disk.roleMode, disk.roleCustom),
          media: picked(disk.mediaMode, disk.mediaCustom),
          interface: picked(disk.ifaceMode, disk.ifaceCustom),
          sort_order: Number(disk.sort_order) || 0
        }))
      })
    })
    diskRows.value = mapDisks(saved.disks)
    calMsg.value = '硬盘校准已保存'
  } catch (e) {
    calErr.value = e.message || '保存失败'
  } finally {
    savingDisks.value = false
  }
}

async function saveFans() {
  calErr.value = ''
  calMsg.value = ''
  savingFans.value = true
  try {
    const saved = await api('/calibration/fans', {
      method: 'PUT',
      body: JSON.stringify({
        items: fanRows.value.map((fan) => ({
          channel_key: fan.channel_key,
          fan_id: fan.id || '',
          role: fan.roleMode || '',
          primary: !!fan.primary && !fan.excluded,
          excluded: !!fan.excluded
        }))
      })
    })
    fanRows.value = mapFans(saved.fans)
    calMsg.value = '风扇映射已保存'
  } catch (e) {
    calErr.value = e.message || '保存失败'
  } finally {
    savingFans.value = false
  }
}

async function saveTune() {
  tuneErr.value = ''
  tuneMsg.value = ''
  savingTune.value = true
  try {
    const values = {}
    for (const item of tuneItems.value) {
      const raw = tuneDraft.value[item.key]
      values[item.key] = item.kind === 'bool' ? !!raw : Number(raw)
    }
    applyTune(await api('/tuning', { method: 'PUT', body: JSON.stringify({ values }) }))
    meta.value = await api('/meta')
    tuneMsg.value = '已保存。采集从下一轮开始用新周期，不必重启。'
  } catch (e) {
    tuneErr.value = e.message || '保存失败'
  } finally {
    savingTune.value = false
  }
}

async function resetTune() {
  tuneErr.value = ''
  tuneMsg.value = ''
  savingTune.value = true
  try {
    applyTune(await api('/tuning', { method: 'DELETE' }))
    meta.value = await api('/meta')
    tuneMsg.value = '已改回配置文件里的默认值'
  } catch (e) {
    tuneErr.value = e.message || '保存失败'
  } finally {
    savingTune.value = false
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

function statusClass(id) {
  const state = tabState(id)
  if (state === 'offline') return 'crit'
  if (state === 'online') return 'ok'
  return 'muted'
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
    refreshQr()
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

watch(() => route.hash, (hash) => {
  if (hash) section.value = sectionFromHash(hash)
}, { immediate: true })
watch(() => nas.activeId, loadPage)
watch([localUrl, draftUrl, () => nas.profiles.map((p) => `${p.id}:${p.baseUrl}`).join('|')], refreshQr)
onMounted(async () => {
  await loadPage()
  await refreshQr()
})
</script>

<template>
  <div class="page settings-page">
    <aside class="settings-nav" aria-label="设置分区">
      <button
        v-for="item in sections"
        :key="item.id"
        type="button"
        :class="{ on: section === item.id }"
        @click="openSection(item.id)"
      >
        <component :is="item.icon" :size="16" />
        {{ item.label }}
      </button>
    </aside>
    <div class="settings-main">
      <p v-if="err" style="color:var(--crit)">{{ err }}</p>

      <section v-show="section === 'auth'" id="auth">
        <h2>认证</h2>
        <div class="card">
          <h3>账号</h3>
          <p v-if="meta">版本 {{ meta.app_version }} · API {{ meta.api_version }}</p>
          <p>用户名 <b>{{ meta?.auth_username || 'admin' }}</b></p>
          <p class="muted">只有一个账号。修改用户名、密码哈希或 JWT 密钥请编辑 NAS 上的 <code>config.yaml</code> 后重启容器。网页不能改密码，退出只是清掉这台浏览器里当前节点的令牌。</p>
        </div>
        <div class="card" style="margin-top:16px">
          <h3>安全提示</h3>
          <p class="muted">当前设计为<strong>仅局域网</strong>访问。请勿将 8787 端口直接映射到公网。各节点的令牌分开存在这台浏览器里。</p>
        </div>
      </section>

      <section v-show="section === 'nodes'" id="nodes">
        <h2>节点</h2>
        <div id="add-nas" class="card">
          <h3>多台 NAS</h3>
          <p class="muted">每台机器各自运行一份监控。浏览器直接请求对方的 <code>/api/v1</code>，不经过本机代理。地址和令牌只留在这台浏览器的 localStorage 里，密码不保存。探活超时约 3 秒。</p>
          <div class="qr-card">
            <img v-if="qrFor[localUrl]" :src="qrFor[localUrl]" alt="本机连接二维码" />
            <div class="qr-meta">
              <b class="qr-copy">本机连接串</b>
              <code>{{ localUrl }}</code>
              <p class="muted">二维码只编码根地址，不含令牌。另一台浏览器或平板扫码后，在「添加」里填这个地址并用那台自己的账号登录。</p>
              <button class="btn ghost" type="button" @click="copyText(localUrl)">
                <Copy :size="15" /> {{ copiedKey === localUrl ? '已复制' : '复制连接串' }}
              </button>
            </div>
          </div>
          <div v-for="p in nas.profiles" :key="p.id" class="nas-row">
            <div>
              <b>{{ p.name }}</b>
              <div class="muted">{{ profileUrl(p) }}</div>
            </div>
            <span class="pill" :class="statusClass(p.id)">{{ statusText(p.id) }}</span>
            <button class="btn ghost" type="button" @click="copyText(profileUrl(p))">
              <Copy :size="15" /> {{ copiedKey === profileUrl(p) ? '已复制' : '复制' }}
            </button>
            <button class="btn ghost" type="button" @click="openNas(p.id)">打开</button>
            <button class="btn ghost" type="button" @click="startEdit(p)">编辑</button>
            <button class="btn ghost" type="button" @click="startRelogin(p)">重新登录</button>
            <button v-if="p.id !== 'local'" class="btn ghost" type="button" @click="askRemove(p)">移除</button>
            <div v-if="profileUrl(p) !== localUrl && qrFor[profileUrl(p)]" class="qr-mini">
              <img :src="qrFor[profileUrl(p)]" :alt="p.name + ' 连接二维码'" />
            </div>
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
            <div v-if="draftUrl && qrFor[draftUrl]" class="qr-card">
              <img :src="qrFor[draftUrl]" alt="待添加节点二维码" />
              <div class="qr-meta">
                <b class="qr-copy">待添加的连接串</b>
                <code>{{ draftUrl }}</code>
                <button class="btn ghost" type="button" @click="copyText(draftUrl)">
                  <Copy :size="15" /> {{ copiedKey === draftUrl ? '已复制' : '复制连接串' }}
                </button>
              </div>
            </div>
            <p v-if="formErr" style="color:var(--crit);margin:0">{{ formErr }}</p>
            <p v-if="formMsg" class="muted">{{ formMsg }}</p>
            <button class="btn" type="submit" :disabled="saving">{{ saving ? '登录中…' : '添加并登录' }}</button>
          </form>
        </div>
        <div class="card" style="margin-top:16px">
          <h3>轮播与副屏</h3>
          <p class="muted">在已登录的节点之间自动切换。点按、触摸或按键会暂停，空闲后再等一个完整间隔才继续。全屏给副屏或旧平板用；浏览器不支持全屏时仍然铺满页面。</p>
          <label class="switch"><span>自动轮播</span>
            <input :checked="carousel.enabled" type="checkbox" @change="patchCarousel({ enabled: $event.target.checked })" />
          </label>
          <label class="inline-field">间隔（秒）
            <input :value="carousel.intervalSec" type="number" min="5" max="600" @change="patchCarousel({ intervalSec: $event.target.value })" />
          </label>
          <label class="inline-field">空闲后续播（秒）
            <input :value="carousel.idleSec" type="number" min="5" max="600" @change="patchCarousel({ idleSec: $event.target.value })" />
          </label>
          <label class="switch"><span>副屏全屏</span>
            <input :checked="carousel.kiosk" type="checkbox" @change="patchCarousel({ kiosk: $event.target.checked })" />
          </label>
        </div>
      </section>

      <section v-show="section === 'collect'" id="collect">
        <h2>采集</h2>
        <div class="card">
          <h3>当前周期</h3>
          <p class="muted">总览每 {{ meta?.refresh?.overview_sec ?? 1 }} 秒换主机指标。磁盘和 SMART 的界面更慢，只是换上已经采到的缓存，避免卡片跟着每秒重绘。真正读盘的是下面的采集周期。</p>
          <dl class="kv">
            <div><dt>主机 / Docker / 风扇</dt><dd>每 {{ meta?.collect_interval_sec ?? 1 }} 秒</dd></div>
            <div><dt>总览刷新</dt><dd>每 {{ meta?.refresh?.overview_sec ?? 1 }} 秒</dd></div>
            <div><dt>文件系统采集</dt><dd>每 {{ meta?.fs_interval_sec ?? 60 }} 秒</dd></div>
            <div><dt>磁盘界面刷新</dt><dd>每 {{ meta?.refresh?.disk_sec ?? 60 }} 秒</dd></div>
            <div><dt>SMART 采集</dt><dd>每 {{ meta?.smart_interval_sec ?? 900 }} 秒</dd></div>
            <div><dt>SMART 界面刷新</dt><dd>每 {{ meta?.refresh?.smart_sec ?? 60 }} 秒</dd></div>
            <div><dt>硬盘插拔去抖</dt><dd>{{ meta?.disk_plug_debounce_sec ?? 8 }} 秒</dd></div>
            <div><dt>展示时区</dt><dd>{{ meta?.timezone_display || '—' }}</dd></div>
          </dl>
          <button class="btn" type="button" @click="openSection('advanced')">到高级里修改</button>
        </div>
      </section>

      <section v-show="section === 'alerts'" id="alerts">
        <h2>告警</h2>
        <div class="card">
          <h3>告警通道</h3>
          <p>已配置 {{ channels?.count ?? 0 }} 条 Apprise URL</p>
          <ul>
            <li v-for="(c, i) in (channels?.channels || [])" :key="i">{{ c.type }} · 已配置</li>
          </ul>
          <p class="muted">{{ channels?.note }}</p>
          <p class="muted">支持：{{ (channels?.supported || []).join('、') }}</p>
          <h4>规则</h4>
          <ul>
            <li v-for="rule in rules" :key="rule.id"><code>{{ rule.id }}</code> · {{ rule.when }}</li>
          </ul>
          <p class="muted">阈值和通道只能改 <code>config.yaml</code>，改完重启。这里不提供 Bark。</p>
        </div>
      </section>

      <section v-show="section === 'calibration'" id="calibration">
        <h2>展示校准</h2>
        <div class="card">
          <h3>外观</h3>
          <p class="muted">浅色、深色，或跟随系统。选择记在这台浏览器里。深色保持较高对比，方便副屏扫读。</p>
          <div class="choice">
            <label><input :checked="colorMode === 'light'" type="radio" name="theme" @change="setTheme('light')" /> 浅色</label>
            <label><input :checked="colorMode === 'dark'" type="radio" name="theme" @change="setTheme('dark')" /> 深色</label>
            <label><input :checked="colorMode === 'auto'" type="radio" name="theme" @change="setTheme('auto')" /> 跟随系统</label>
          </div>
        </div>
        <div class="card" style="margin-top:16px">
          <h3>容量、硬盘、风扇</h3>
          <p class="muted">容量的默认值在 <code>config.yaml</code> 的 <code>display.capacity</code>。这里保存后写入本机数据库，立刻生效。硬盘按序列号或 WWN 记住，两项都没有时只按当前盘符记住，换盘符后不会套上。风扇按芯片名和通道号记住。</p>
          <p v-if="calErr" style="color:var(--crit)">{{ calErr }}</p>
          <p v-if="calMsg" class="muted">{{ calMsg }}</p>

          <h4>容量</h4>
          <div class="choice">
            <label><input v-model="capacity.unit" type="radio" value="gib" /> GiB（1024）</label>
            <label><input v-model="capacity.unit" type="radio" value="gb" /> GB（1000）</label>
            <label><input v-model="capacity.unit" type="radio" value="label" /> 标签容量</label>
          </div>
          <label class="inline-field">小数位
            <select v-model.number="capacity.decimals">
              <option :value="0">0</option>
              <option :value="1">1</option>
              <option :value="2">2</option>
              <option :value="3">3</option>
            </select>
          </label>
          <p class="muted">预览 {{ capacityPreview }}。标签容量在读到厂商标称时用十进制，否则退回 GiB。存储池、硬盘卡和磁盘详情共用这一套。</p>
          <p v-if="capacity.source === 'db'" class="muted">当前用的是已保存的值。配置文件默认是 {{ capacity.config_unit }} / {{ capacity.config_decimals }} 位。</p>
          <div class="row-actions">
            <button class="btn" type="button" :disabled="savingCap" @click="saveCapacity">{{ savingCap ? '保存中…' : '保存容量' }}</button>
            <button class="btn ghost" type="button" :disabled="savingCap" @click="resetCapacity">改回配置默认</button>
          </div>

          <h4>硬盘</h4>
          <div v-if="diskRows.length" class="table-card">
            <table class="cal-table">
              <thead>
                <tr>
                  <th>显示</th>
                  <th>识别</th>
                  <th>名称</th>
                  <th>角色</th>
                  <th>介质</th>
                  <th>接口</th>
                  <th>排序</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="disk in diskRows" :key="disk.identity_key">
                  <td><input v-model="disk.visible" type="checkbox" /></td>
                  <td>
                    <div>{{ disk.model || disk.id }}</div>
                    <div class="muted">{{ disk.id }} · {{ disk.serial || '无序列号' }}</div>
                    <div class="muted">{{ disk.identity_stable ? '序列号 / WWN' : '仅盘符，拔插后可能对不上' }}</div>
                    <div v-if="disk.detected_role" class="muted">推断角色 {{ disk.detected_role }}</div>
                  </td>
                  <td><input v-model="disk.label" placeholder="留空用盘符" /></td>
                  <td>
                    <select v-model="disk.roleMode">
                      <option value="">自动</option>
                      <option value="系统盘">系统盘</option>
                      <option value="缓存">缓存</option>
                      <option value="外接">外接</option>
                      <option value="none">不标注</option>
                      <option value="__custom__">池名或存储空间</option>
                    </select>
                    <input v-if="disk.roleMode === '__custom__'" v-model="disk.roleCustom" placeholder="例如 vol1" />
                  </td>
                  <td>
                    <select v-model="disk.mediaMode">
                      <option value="">自动</option>
                      <option value="HDD">HDD</option>
                      <option value="SSD">SSD</option>
                      <option value="__custom__">自定义</option>
                    </select>
                    <input v-if="disk.mediaMode === '__custom__'" v-model="disk.mediaCustom" placeholder="介质" />
                  </td>
                  <td>
                    <select v-model="disk.ifaceMode">
                      <option value="">自动</option>
                      <option value="SATA">SATA</option>
                      <option value="SAS">SAS</option>
                      <option value="NVMe">NVMe</option>
                      <option value="USB">USB</option>
                      <option value="__custom__">自定义</option>
                    </select>
                    <input v-if="disk.ifaceMode === '__custom__'" v-model="disk.ifaceCustom" placeholder="接口" />
                  </td>
                  <td><input v-model.number="disk.sort_order" type="number" min="-999" max="999" /></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted">还没有采集到硬盘。</p>
          <div class="row-actions">
            <button class="btn" type="button" :disabled="savingDisks || !diskRows.length" @click="saveDisks">{{ savingDisks ? '保存中…' : '保存硬盘' }}</button>
          </div>

          <h4>风扇</h4>
          <div v-if="fanRows.length" class="table-card">
            <table class="cal-table">
              <thead>
                <tr>
                  <th>通道</th>
                  <th>角色</th>
                  <th>首页主显示</th>
                  <th>排除</th>
                  <th>调速</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="fan in fanRows" :key="fan.channel_key">
                  <td>
                    <div>{{ fan.raw_label || fan.label || fan.id }}</div>
                    <div class="muted">{{ fan.chip }} · {{ fan.id }}<template v-if="fan.rpm != null"> · {{ fan.rpm }} RPM</template></div>
                  </td>
                  <td>
                    <select v-model="fan.roleMode">
                      <option value="">自动</option>
                      <option value="cpu">CPU</option>
                      <option value="chassis">机箱</option>
                      <option value="other">其它</option>
                    </select>
                  </td>
                  <td>
                    <label class="tick">
                      <input
                        type="radio"
                        name="fan-primary"
                        :checked="fan.primary"
                        :disabled="fan.excluded"
                        @change="setPrimary(fan.channel_key)"
                      />
                      主显示
                    </label>
                  </td>
                  <td><label class="tick"><input v-model="fan.excluded" type="checkbox" @change="fan.excluded && (fan.primary = false)" /> 排除</label></td>
                  <td>{{ fan.controllable ? '可调' : '不可调' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted">还没有采集到风扇。</p>
          <p class="muted">排除的通道不出现在首页。PWM 不可写时首页仍显示「不可调」，这里改映射不会把它变成可调。</p>
          <div class="row-actions">
            <button v-if="fanRows.some((fan) => fan.primary)" class="btn ghost" type="button" @click="setPrimary('')">取消主显示</button>
            <button class="btn" type="button" :disabled="savingFans || !fanRows.length" @click="saveFans">{{ savingFans ? '保存中…' : '保存风扇' }}</button>
          </div>
        </div>
      </section>

      <section v-show="section === 'advanced'" id="advanced">
        <h2>高级</h2>
        <div class="card">
          <h3>采集与刷新</h3>
          <p class="muted">这些项的默认值在 <code>config.yaml</code>。保存后写入本机数据库，优先于配置文件，下一轮采集就生效。Compose 把配置文件只读挂进容器，所以这里不改文件。</p>
          <p v-if="tuneErr" style="color:var(--crit)">{{ tuneErr }}</p>
          <p v-if="tuneMsg" class="muted">{{ tuneMsg }}</p>
          <div v-for="group in tuneGroups" :key="group.name" class="tune-group">
            <h4>{{ group.name }}</h4>
            <div v-for="item in group.items" :key="item.key" class="tune-row">
              <label v-if="item.kind === 'bool'" class="switch">
                <span>{{ item.label }}</span>
                <input v-model="tuneDraft[item.key]" type="checkbox" />
              </label>
              <label v-else class="tune-num">
                <span>{{ item.label }}<template v-if="item.unit">（{{ item.unit }}）</template></span>
                <input v-model.number="tuneDraft[item.key]" type="number" :min="item.min" :max="item.max" :step="item.kind === 'int' ? 1 : 'any'" />
              </label>
              <p class="muted">{{ item.hint }}<template v-if="item.source === 'db'"> 当前覆盖了配置文件的 {{ item.config }}。</template></p>
            </div>
          </div>
          <div class="row-actions">
            <button class="btn" type="button" :disabled="savingTune" @click="saveTune">{{ savingTune ? '保存中…' : '保存高级设置' }}</button>
            <button class="btn ghost" type="button" :disabled="savingTune" @click="resetTune">改回配置默认</button>
          </div>
        </div>
      </section>
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
.qr-mini { flex: 1 0 100%; }
.qr-mini img { width: 96px; height: 96px; background: #fff; border-radius: 8px; }
.row-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.add-form {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}
.add-form label, .tune-num {
  display: grid;
  gap: 4px;
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--muted);
}
h4 { margin: 18px 0 8px; }
.choice {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin: 8px 0;
}
.choice label, .tick {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 650;
  color: var(--ink);
}
.choice input, .tick input { width: auto; }
.inline-field {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 280px;
  margin: 8px 0;
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--muted);
}
.cal-table input, .cal-table select, .tune-num input, .inline-field input, select {
  padding: 6px 8px;
  border-radius: 8px;
  background: var(--input-bg);
  border: 1px solid var(--border);
  color: var(--text);
}
.cal-table input[type="checkbox"],
.cal-table input[type="radio"] { width: auto; }
.cal-table input[type="number"] { width: 5.5rem; }
.cal-table td { vertical-align: top; }
.cal-table .muted { font-size: 0.75rem; }
.row-actions { margin-top: 10px; }
.kv { display: grid; gap: 8px; margin: 12px 0 16px; }
.kv div { display: flex; justify-content: space-between; gap: 12px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; font-weight: 700; }
.tune-group { margin-top: 8px; }
.tune-row { margin-bottom: 12px; }
.tune-num input { max-width: 180px; }
button.btn { display: inline-flex; align-items: center; gap: 6px; }
</style>
