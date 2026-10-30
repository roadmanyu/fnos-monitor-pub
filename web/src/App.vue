<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearToken, getToken } from './api/client'

const route = useRoute()
const router = useRouter()
const showNav = computed(() => route.path !== '/login' && !!getToken())

function logout() {
  clearToken()
  router.push('/login')
}
</script>

<template>
  <nav v-if="showNav" class="nav">
    <div class="brand">
      <span class="brand-mark">飞</span>
      <span>飞牛监控</span>
    </div>
    <div class="nav-links">
      <router-link to="/">概览</router-link>
      <router-link to="/disks">磁盘</router-link>
      <router-link to="/docker">Docker</router-link>
      <router-link to="/alerts">告警</router-link>
      <router-link to="/settings">设置</router-link>
    </div>
    <button class="btn ghost" type="button" @click="logout">退出</button>
  </nav>
  <router-view />
</template>
