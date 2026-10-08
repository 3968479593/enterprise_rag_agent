<script setup>
// 根组件：侧栏 + 路由视图 + 全局 Toast（侧栏直接内联，不单独建组件目录）
import { computed, onMounted, onUnmounted, provide, ref } from 'vue'
import { api, currentRole, getUsername, logout } from '@/api'

const serviceOk = ref(false)

const navs = [
  { path: '/chat', label: '智能问答', icon: 'chat' },
  { path: '/docs', label: '文档管理', icon: 'docs', adminOnly: true },
  { path: '/history', label: '会话历史', icon: 'history' },
  { path: '/feedback', label: '反馈管理', icon: 'feedback', adminOnly: true },
  { path: '/eval', label: '离线评估', icon: 'eval', adminOnly: true },
]

// 普通用户只展示问答与历史；管理员展示全部（currentRole 为响应式，登录/登出即时刷新）
const visibleNavs = computed(() => navs.filter((n) => !n.adminOnly || currentRole.value === 'admin'))
const roleName = computed(() => (currentRole.value === 'admin' ? '管理员' : '普通用户'))
const accountLabel = computed(() => {
  const u = getUsername()
  return u ? `${u} · ${roleName.value}` : roleName.value
})

const icons = {
  chat: '<path d="M4 6h16v11H9l-5 4V6z" stroke-linejoin="round"/><path d="M8 10h8M8 13h5" stroke-linecap="round"/>',
  docs: '<path d="M7 3h8l4 4v14H7z" stroke-linejoin="round"/><path d="M15 3v4h4M10 12h6M10 15h6M10 9h2" stroke-linecap="round"/>',
  history: '<path d="M4 12a8 8 0 1 0 2.3-5.7" stroke-linecap="round"/><path d="M4 4v4h4M12 8v4l3 2" stroke-linecap="round" stroke-linejoin="round"/>',
  eval: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M18 6l-2.5 2.5M6 18l2.5-2.5M18 18l-2.5-2.5" stroke-linecap="round"/>',
  feedback: '<path d="M4 5h16v11H9l-5 4V5z" stroke-linejoin="round"/><path d="M8.5 10h.01M12 10h.01M15.5 10h.01" stroke-linecap="round" stroke-width="2.4"/>',
}

const toasts = ref([])
let toastSeq = 0
function toast(msg, type = 'info') {
  const id = ++toastSeq
  toasts.value.push({ id, msg, type })
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }, 3400)
}
provide('toast', toast)

async function checkHealth() {
  try {
    const j = await api.health()
    serviceOk.value = j.status === 'ok'
  } catch (e) {
    serviceOk.value = false
  }
}

let timer = null
onMounted(() => {
  checkHealth()
  timer = setInterval(checkHealth, 20000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">
          <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round">
            <path d="M7 7h10M7 11h10M7 15h6" />
          </svg>
        </div>
        <div>
          <div class="brand-name">企业文档智能客服</div>
          <div class="brand-sub">RAG · Agent · Evaluation</div>
        </div>
      </div>

      <nav class="nav">
        <router-link v-for="n in visibleNavs" :key="n.path" :to="n.path" class="nav-item" active-class="active">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" v-html="icons[n.icon]"></svg>
          <span>{{ n.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-foot">
        <div class="service-pill">
          <span class="dot" :class="{ ok: serviceOk, bad: !serviceOk }"></span>
          <span>{{ serviceOk ? '服务正常 · 知识库在线' : '服务未连接' }}</span>
        </div>
        <div class="account-row">
          <span class="role-badge" :title="accountLabel">{{ accountLabel }}</span>
          <button class="logout" @click="logout">退出登录</button>
        </div>
      </div>
    </aside>

    <main class="main">
      <router-view v-slot="{ Component }">
        <component :is="Component" class="view-fade" />
      </router-view>
    </main>

    <div class="toasts">
      <TransitionGroup name="toast">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">{{ t.msg }}</div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 232px; flex-shrink: 0; background: var(--sidebar); color: var(--sidebar-ink);
  display: flex; flex-direction: column; padding: 20px 14px;
  position: sticky; top: 0; height: 100vh; overflow-y: auto;
}
.brand { display: flex; align-items: center; gap: 10px; padding: 4px 8px 18px; border-bottom: 1px solid rgba(255, 255, 255, .08); margin-bottom: 14px; }
.brand-mark {
  width: 34px; height: 34px; border-radius: 9px; flex-shrink: 0;
  background: linear-gradient(135deg, #0d7f8c, #1aa3a0);
  display: flex; align-items: center; justify-content: center;
}
.brand-mark svg { width: 18px; height: 18px; }
.brand-name { color: #fff; font-size: 15px; font-weight: 700; line-height: 1.2; white-space: nowrap; }
.brand-sub { color: #7c8aa0; font-size: 11px; margin-top: 2px; white-space: nowrap; }

.nav { display: flex; flex-direction: column; gap: 2px; }
.nav-item {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  color: var(--sidebar-ink); font-size: 13.5px; border-radius: 8px;
  text-decoration: none; transition: background .15s, color .15s;
}
.nav-item svg { width: 17px; height: 17px; flex-shrink: 0; opacity: .85; }
.nav-item:hover { background: rgba(255, 255, 255, .06); color: #fff; }
.nav-item.active { background: var(--sidebar-active); color: #fff; }

.sidebar-foot { margin-top: auto; padding-top: 16px; font-size: 12px; color: #7c8aa0; }
.service-pill { display: flex; align-items: center; gap: 7px; padding: 8px 10px; background: rgba(255, 255, 255, .05); border-radius: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--warn); flex-shrink: 0; }
.dot.ok { background: var(--ok); }
.dot.bad { background: var(--danger); }
.account-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px; }
.role-badge {
  font-size: 11px; padding: 3px 10px; border-radius: 999px;
  background: rgba(13, 127, 140, .18); color: #7fd4d8; font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px;
}
.logout { border: 1px solid rgba(255, 255, 255, .14); background: none; color: #9aa8ba; font-size: 11.5px; padding: 3px 10px; border-radius: 6px; cursor: pointer; transition: all .15s; }
.logout:hover { color: #fff; border-color: rgba(255, 255, 255, .32); }

.toast-enter-active, .toast-leave-active { transition: opacity .3s, transform .3s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(-4px); }

@media (max-width: 860px) {
  .sidebar { width: 100%; height: auto; position: static; flex-direction: row; align-items: center; padding: 10px 14px; }
  .brand { border-bottom: none; margin-bottom: 0; padding: 0 10px 0 0; border-right: 1px solid rgba(255, 255, 255, .08); }
  .brand-sub { display: none; }
  .nav { flex-direction: row; flex: 1; overflow-x: auto; }
  .nav-item { white-space: nowrap; }
  .sidebar-foot { margin: 0 0 0 auto; }
  .service-pill { padding: 6px 8px; }
}
</style>
