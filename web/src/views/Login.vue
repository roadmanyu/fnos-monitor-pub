<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, setToken } from '../api/client'

const router = useRouter()
const username = ref('admin')
const password = ref('admin123')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: username.value, password: password.value })
    })
    setToken(data.access_token)
    router.push('/')
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page" style="max-width:400px;margin-top:10vh">
    <h1>飞牛监控</h1>
    <p class="muted">局域网 NAS 监控 · 默认账号见 README</p>
    <div class="card" style="margin-top:16px;display:grid;gap:12px">
      <label>用户名<input v-model="username" autocomplete="username" /></label>
      <label>密码<input v-model="password" type="password" autocomplete="current-password" /></label>
      <p v-if="error" style="color:var(--crit);margin:0">{{ error }}</p>
      <button class="btn" :disabled="loading" @click="submit">{{ loading ? '登录中…' : '登录' }}</button>
    </div>
  </div>
</template>
