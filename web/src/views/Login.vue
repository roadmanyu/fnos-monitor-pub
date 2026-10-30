<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, setToken } from '../api/client'
import { activeProfile } from '../nas/profiles'

const router = useRouter()
const targetLabel = computed(() => {
  const p = activeProfile()
  return p?.baseUrl ? `${p.name} · ${p.baseUrl}` : `${p?.name || '本机'} · 当前站点`
})
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
  <div class="login-shell">
    <form class="card login-card" @submit.prevent="submit">
      <div class="login-brand">
        <span class="brand-mark lg">飞</span>
        <div>
          <h1>飞牛监控</h1>
          <p class="muted">{{ targetLabel }}</p>
        </div>
      </div>
      <label>
        用户名
        <input v-model="username" autocomplete="username" />
      </label>
      <label>
        密码
        <input v-model="password" type="password" autocomplete="current-password" />
      </label>
      <p v-if="error" class="err">{{ error }}</p>
      <button class="btn" type="submit" :disabled="loading">{{ loading ? '登录中…' : '登录' }}</button>
      <p class="muted hint">默认账号见 README。请在 NAS 上修改 config.yaml。</p>
    </form>
  </div>
</template>

<style scoped>
.login-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 28px 16px;
}

.login-card {
  width: min(420px, 100%);
  display: grid;
  gap: 14px;
  padding: 28px 26px 22px;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 6px;
}

.brand-mark.lg {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  font-size: 1.25rem;
}

label {
  display: grid;
  gap: 6px;
  font-size: 0.82rem;
  font-weight: 650;
  color: var(--muted);
}

.err {
  margin: 0;
  color: var(--crit);
  font-size: 0.9rem;
}

.hint { margin: 0; font-size: 0.8rem; }
</style>
