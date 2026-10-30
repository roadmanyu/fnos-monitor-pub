import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api/client'
import Login from '../views/Login.vue'
import Overview from '../views/Overview.vue'
import Disks from '../views/Disks.vue'
import Docker from '../views/Docker.vue'
import Alerts from '../views/Alerts.vue'
import Settings from '../views/Settings.vue'

const routes = [
  { path: '/login', component: Login, meta: { public: true } },
  { path: '/', component: Overview },
  { path: '/disks', component: Disks },
  { path: '/docker', component: Docker },
  { path: '/alerts', component: Alerts },
  { path: '/settings', component: Settings },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  if (!to.meta.public && !getToken()) return '/login'
  if (to.path === '/login' && getToken()) return '/'
})

export default router
