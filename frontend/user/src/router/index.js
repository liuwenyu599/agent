import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { requiresAuth: true } },
  { path: '/chat', name: 'chat', component: () => import('@/views/ChatView.vue'), meta: { requiresAuth: true } },
  { path: '/knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeView.vue'), meta: { requiresAuth: true } },
  { path: '/knowledge/:id', name: 'knowledge-detail', component: () => import('@/views/KnowledgeDetailView.vue'), meta: { requiresAuth: true } },
  { path: '/templates', name: 'templates', component: () => import('@/views/TemplatesView.vue'), meta: { requiresAuth: true } },
  { path: '/template/:id', name: 'template-use', component: () => import('@/views/TemplateView.vue'), meta: { requiresAuth: true } },
  { path: '/admin', name: 'admin', component: () => import('@/views/AdminView.vue'), meta: { requiresAuth: true, requiresAdmin: true } }
]

const router = createRouter({ history: createWebHistory(), routes })

function isAdmin() {
  try {
    const userStr = localStorage.getItem('user')
    if (!userStr || userStr === 'null' || userStr === 'undefined') return false
    const user = JSON.parse(userStr)
    return ['developer', 'knowledge_admin', 'admin'].includes(user?.role)
  } catch { return false }
}

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (!token && to.path !== '/login') { next('/login'); return }
  if (token && to.path === '/login') { next('/dashboard'); return }
  if (to.meta.requiresAuth && !token) { next('/login'); return }
  if (to.meta.requiresAdmin && !isAdmin()) { next('/dashboard'); return }
  next()
})

export default router
