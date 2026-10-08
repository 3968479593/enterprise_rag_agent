import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import { getRole, isAuthed } from './api'
import './styles.css'

// 四个视图即四个页面，路由集中在此，不再单独建 router 目录
const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { title: '登录' } },
  { path: '/chat', name: 'chat', component: () => import('@/views/ChatView.vue'), meta: { title: '智能问答' } },
  { path: '/docs', name: 'docs', component: () => import('@/views/DocsView.vue'), meta: { title: '文档管理', adminOnly: true } },
  { path: '/history', name: 'history', component: () => import('@/views/HistoryView.vue'), meta: { title: '会话历史' } },
  { path: '/feedback', name: 'feedback', component: () => import('@/views/FeedbackView.vue'), meta: { title: '反馈管理', adminOnly: true } },
  { path: '/eval', name: 'eval', component: () => import('@/views/EvalView.vue'), meta: { title: '离线评估', adminOnly: true } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 登录守卫：未登录 → /login；普通用户访问管理员页面 → /chat
router.beforeEach((to) => {
  if (to.path === '/login') {
    return isAuthed() ? '/chat' : true
  }
  if (!isAuthed()) return '/login'
  if (to.meta.adminOnly && getRole() !== 'admin') return '/chat'
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 企业文档智能客服` : '企业文档智能客服'
})

createApp(App).use(router).mount('#app')
