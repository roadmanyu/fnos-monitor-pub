import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { applyTheme } from './theme/theme'
import './assets/main.css'

applyTheme(
  document,
  localStorage,
  window.matchMedia('(prefers-color-scheme: dark)').matches
)

createApp(App).use(router).mount('#app')
