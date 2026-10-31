import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api/client'
import Login from '../views/Login.vue'
import Overview from '../views/Overview.vue'
import Settings from '../views/Settings.vue'

const routes = [
  { path: '/login', component: Login, meta: { public: true } },
  { path: '/', component: Overview },
  { path: '/settings', component: Settings },
  { path: '/disks', redirect: { path: '/', hash: '#disk-detail' } },
  { path: '/docker', redirect: { path: '/', hash: '#docker-detail' } },
  { path: '/alerts', redirect: { path: '/', hash: '#alert-detail' } },
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
