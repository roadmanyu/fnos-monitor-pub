<script setup>
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useColorMode, useFullscreen } from '@vueuse/core'
import {
  LayoutDashboard,
  LogOut,
  Maximize,
  Minimize2,
  Moon,
  Pause,
  Play,
  Plus,
  Server,
  Settings,
  Sun,
  SunMoon
} from 'lucide-vue-next'
import { clearToken, getToken } from './api/client'
import { carousel, patchCarousel } from './nas/carouselStore'
import { nextProfileId, noteInteraction, shouldAdvance } from './nas/carousel'
import { hasToken, nas, probeProfile, setActive, tabState } from './nas/profiles'
import { THEME_KEY } from './theme/theme'

const route = useRoute()
const router = useRouter()
const authed = computed(() => !!getToken())
const showNav = computed(() => route.path !== '/login' && authed.value)
const colorMode = useColorMode({
  attribute: 'data-theme',
  storageKey: THEME_KEY,
  initialValue: 'auto',
  emitAuto: true,
  modes: { light: 'light', dark: 'dark', auto: 'auto' }
})
provide('colorMode', colorMode)

const { isFullscreen, enter, exit } = useFullscreen()
const themeOrder = ['light', 'dark', 'auto']
const themeLabel = computed(() => ({ light: '浅色', dark: '深色', auto: '跟随系统' }[colorMode.value] || '跟随系统'))

let pausedUntil = 0
let lastAdvanceAt = Date.now()
let carouselTimer
let removeInteract

function tabText(id) {
  const state = tabState(id)
  if (state === 'offline') return '离线'
  if (state === 'logged-out') return '未登录'
  return '已登录'
}

function select(id) {
  setActive(id)
  const profile = nas.profiles.find((p) => p.id === id)
  if (profile) probeProfile(profile)
  lastAdvanceAt = Date.now()
  if (!getToken()) router.push('/login')
  else if (route.path === '/login') router.push('/')
}

function probeTabs() {
  nas.profiles.forEach((p) => { probeProfile(p) })
}

function loggedInProfiles() {
  return nas.profiles.filter((profile) => hasToken(profile.id))
}

function bumpPause() {
  if (!carousel.enabled) return
  pausedUntil = noteInteraction(Date.now(), carousel.idleSec * 1000)
}

function tickCarousel() {
  const now = Date.now()
  const candidates = loggedInProfiles()
  if (!shouldAdvance({
    enabled: carousel.enabled && route.path !== '/login' && authed.value,
    count: candidates.length,
    now,
    lastAdvanceAt,
    intervalMs: carousel.intervalSec * 1000,
    pausedUntil
  })) return
  const next = nextProfileId(candidates, nas.activeId)
  if (next && next !== nas.activeId) setActive(next)
  lastAdvanceAt = now
}

async function applyKiosk(on) {
  document.documentElement.classList.toggle('kiosk', on)
  if (on) {
    try { await enter() } catch { /* 老平板没有全屏 API 时仍用铺满布局 */ }
  } else if (isFullscreen.value) {
    try { await exit() } catch { /* 已经退出 */ }
  }
  window.dispatchEvent(new Event('resize'))
}

function setKiosk(on) {
  patchCarousel({ kiosk: on })
}

function toggleCarousel() {
  const next = !carousel.enabled
  patchCarousel({ enabled: next })
  lastAdvanceAt = Date.now()
  if (next) pausedUntil = 0
}

function cycleTheme() {
  const index = themeOrder.indexOf(colorMode.value)
  colorMode.value = themeOrder[(index + 1) % themeOrder.length]
}

function logout() {
  clearToken()
  router.push('/login')
}

onMounted(() => {
  probeTabs()
  applyKiosk(carousel.kiosk)
  const events = ['pointerdown', 'keydown', 'touchstart']
  const onInteract = () => bumpPause()
  events.forEach((name) => window.addEventListener(name, onInteract, { passive: true }))
  removeInteract = () => events.forEach((name) => window.removeEventListener(name, onInteract))
  carouselTimer = setInterval(tickCarousel, 400)
})
watch(() => nas.profiles.map((p) => `${p.id}:${p.baseUrl}`).join('|'), probeTabs)
watch(() => carousel.kiosk, (on) => { applyKiosk(on) }, { flush: 'sync' })
watch(() => colorMode.state, (mode) => {
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', mode === 'dark' ? '#10151c' : '#f3f5f8')
})
onUnmounted(() => {
  clearInterval(carouselTimer)
  removeInteract?.()
})

const pauseTick = ref(0)
let pauseUi
onMounted(() => { pauseUi = setInterval(() => { pauseTick.value += 1 }, 1000) })
onUnmounted(() => clearInterval(pauseUi))
const carouselText = computed(() => {
  void pauseTick.value
  if (!carousel.enabled) return '轮播关'
  if (Date.now() < pausedUntil) return '轮播暂停'
  return `轮播 ${carousel.intervalSec} 秒`
})
</script>

<template>
  <nav v-if="showNav" class="nav">
    <div class="brand">
      <span class="brand-mark">飞</span>
      <span class="brand-name">飞牛监控</span>
    </div>
    <div class="nav-links nas-tabs">
      <button
        v-for="p in nas.profiles"
        :key="p.id"
        type="button"
        class="nas-tab"
        :class="{ on: p.id === nas.activeId, offline: tabState(p.id) === 'offline' }"
        @click="select(p.id)"
      >
        <span class="tab-name"><Server :size="14" /> {{ p.name }}</span>
        <span class="tab-state">{{ tabText(p.id) }}</span>
      </button>
      <router-link class="nas-tab add" to="/settings#nodes"><Plus :size="14" /> 添加</router-link>
    </div>
    <div class="nav-links">
      <button class="btn ghost icon-btn" type="button" :title="carousel.enabled ? '暂停轮播' : '开启轮播'" @click="toggleCarousel">
        <Pause v-if="carousel.enabled" :size="16" />
        <Play v-else :size="16" />
        <span class="btn-label">{{ carouselText }}</span>
      </button>
      <button class="btn ghost icon-btn" type="button" :title="carousel.kiosk ? '退出副屏' : '副屏全屏'" @click="setKiosk(!carousel.kiosk)">
        <Minimize2 v-if="carousel.kiosk" :size="16" />
        <Maximize v-else :size="16" />
      </button>
      <button class="btn ghost icon-btn" type="button" :title="themeLabel" @click="cycleTheme">
        <Sun v-if="colorMode === 'light'" :size="16" />
        <Moon v-else-if="colorMode === 'dark'" :size="16" />
        <SunMoon v-else :size="16" />
      </button>
      <router-link class="nav-home" to="/"><LayoutDashboard :size="16" /> 总览</router-link>
      <router-link to="/settings"><Settings :size="16" /> 设置</router-link>
    </div>
    <button class="btn ghost icon-btn" type="button" @click="logout"><LogOut :size="16" /> <span class="btn-label">退出</span></button>
  </nav>
  <button v-if="carousel.kiosk && showNav" class="kiosk-exit" type="button" @click="setKiosk(false)">退出副屏</button>
  <router-view />
</template>
