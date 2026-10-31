<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearToken, getToken } from './api/client'
import { nas, probeProfile, setActive, tabState } from './nas/profiles'

const route = useRoute()
const router = useRouter()
const authed = computed(() => !!getToken())
const showNav = computed(() => route.path !== '/login' && authed.value)

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
  if (!getToken()) router.push('/login')
  else if (route.path === '/login') router.push('/')
}

function probeTabs() {
  nas.profiles.forEach((p) => { probeProfile(p) })
}

onMounted(probeTabs)
watch(() => nas.profiles.map((p) => `${p.id}:${p.baseUrl}`).join('|'), probeTabs)

function logout() {
  clearToken()
  router.push('/login')
}
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
        <span class="tab-name">{{ p.name }}</span>
        <span class="tab-state">{{ tabText(p.id) }}</span>
      </button>
      <router-link class="nas-tab add" to="/settings#add-nas">+ 添加</router-link>
    </div>
    <div class="nav-links">
      <router-link class="nav-home" to="/">总览</router-link>
      <router-link to="/settings">设置</router-link>
    </div>
    <button class="btn ghost" type="button" @click="logout">退出</button>
  </nav>
  <router-view />
</template>
