/**
 * API 封装：所有请求经 Vite 代理转发到后端 :8000。
 * 统一处理 JSON 解析、错误信息提取、登录 token 携带与 401 跳转。
 *
 * 登录态存储策略（解决多标签页串台）：
 * - 主存储用 sessionStorage：每个标签页独立，两个页面可用不同账号互不干扰
 * - 兜底用 localStorage：新开标签页或重开浏览器时恢复上次登录账号
 */
import { ref } from 'vue'

const API = '/api'
// 标签页独立（主）
const SS_TOKEN = 'rag_ss_token'
const SS_ROLE = 'rag_ss_role'
const SS_USER = 'rag_ss_username'
// 持久兜底（恢复用）
const LS_TOKEN = 'rag_auth_token'
const LS_ROLE = 'rag_auth_role'
const LS_USER = 'rag_auth_username'

const sget = (k) => sessionStorage.getItem(k)
const sset = (k, v) => sessionStorage.setItem(k, v)
const sdel = (k) => sessionStorage.removeItem(k)
const lget = (k) => localStorage.getItem(k)

// 模块加载时：本标签页无独立登录态且存在持久兜底 → 恢复（刷新/新标签页仍保持登录）
if (!sget(SS_TOKEN) && lget(LS_TOKEN)) {
  sset(SS_TOKEN, lget(LS_TOKEN))
  sset(SS_ROLE, lget(LS_ROLE) || 'user')
  sset(SS_USER, lget(LS_USER) || '')
}

// 响应式会话状态：登录/注册/登出即时更新，侧栏等界面自动刷新
export const currentRole = ref(sget(SS_ROLE) || '')

export function getToken() {
  return sget(SS_TOKEN)
}
export function getRole() {
  return currentRole.value
}
export function getUsername() {
  return sget(SS_USER)
}
export function isAuthed() {
  return !!getToken()
}
export function saveAuth(token, role, username) {
  // 本标签页独立登录态
  sset(SS_TOKEN, token)
  sset(SS_ROLE, role)
  sset(SS_USER, username || '')
  // 持久兜底：新标签页/重开浏览器恢复
  localStorage.setItem(LS_TOKEN, token)
  localStorage.setItem(LS_ROLE, role)
  localStorage.setItem(LS_USER, username || '')
  currentRole.value = role
}
export function clearAuth() {
  // 只清当前标签页 + 持久兜底（其他在线标签页不受影响）
  sdel(SS_TOKEN)
  sdel(SS_ROLE)
  sdel(SS_USER)
  localStorage.removeItem(LS_TOKEN)
  localStorage.removeItem(LS_ROLE)
  localStorage.removeItem(LS_USER)
  currentRole.value = ''
}

function authHeaders() {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

function gotoLogin() {
  clearAuth()
  if (location.hash !== '#/login') location.hash = '#/login'
}

async function request(path, opts = {}) {
  const resp = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    ...opts,
  })
  let data = {}
  try {
    data = await resp.json()
  } catch (e) {
    /* 非 JSON 响应 */
  }
  if (resp.status === 401) {
    gotoLogin()
    throw new Error(data.detail || '登录已过期，请重新登录')
  }
  if (!resp.ok) {
    const msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || resp.statusText)
    throw new Error(msg)
  }
  return data
}

/** 注册（username + password + 可选管理员注册码） */
export async function register(payload) {
  const data = await request('/auth/register', { method: 'POST', body: JSON.stringify(payload) })
  saveAuth(data.token, data.role, data.username)
  return data
}

/** 登录（用户名 + 密码） */
export async function login(payload) {
  const data = await request('/auth/login', { method: 'POST', body: JSON.stringify(payload) })
  saveAuth(data.token, data.role, data.username)
  return data
}

export function logout() {
  // 通知后端吊销 token（失败不阻塞本地登出）
  const t = getToken()
  if (t) {
    fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: `Bearer ${t}` } }).catch(() => {})
  }
  clearAuth()
  location.hash = '#/login'
}

/** 上传（multipart，不设 Content-Type，让浏览器带 boundary） */
export async function uploadFile(file) {
  const fd = new FormData()
  fd.append('file', file)
  const resp = await fetch(`${API}/documents/upload`, {
    method: 'POST',
    body: fd,
    headers: authHeaders(),
  })
  let data = {}
  try {
    data = await resp.json()
  } catch (e) { /* ignore */ }
  if (resp.status === 401) gotoLogin()
  if (!resp.ok) {
    throw new Error(data.detail || `HTTP ${resp.status}`)
  }
  return data
}

/** 流式问答：POST /chat/stream，SSE 逐事件回调 onEvent({type: start|delta|done|error, ...}) */
export async function streamChat(payload, onEvent) {
  const resp = await fetch(`${API}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
  })
  if (resp.status === 401) gotoLogin()
  if (!resp.ok || !resp.body) {
    let detail = `HTTP ${resp.status}`
    try {
      const d = await resp.json()
      if (d.detail) detail = d.detail
    } catch (e) { /* ignore */ }
    throw new Error(detail)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const line of block.split('\n')) {
        if (!line.startsWith('data:')) continue
        try {
          onEvent(JSON.parse(line.slice(5).trim()))
        } catch (e) { /* 忽略非 JSON 行 */ }
      }
    }
  }
}

/** 回答反馈：value 为 "up" / "down" / null（取消） */
export function sendFeedback(messageId, value) {
  return request(`/chat/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ value }),
  })
}

/** 授权/取消授权管理员查看该条反馈对话（隐私开关，默认不授权） */
export function shareFeedback(messageId, shared) {
  return request(`/chat/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ shared }),
  })
}

/** 保存/清除反馈意见（传空字符串清除） */
export function saveFeedbackNote(messageId, note) {
  return request(`/chat/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}

/** 管理员：反馈列表与统计（kind: "" 全部 / up / down） */
export function listFeedback(kind = '') {
  return request(`/feedback${kind ? `?kind=${kind}` : ''}`)
}

export const api = {
  health: () => fetch('/api/health').then((r) => r.json()),

  // 文档
  listDocuments: () => request('/documents'),
  deleteDocument: (id) => request(`/documents/${id}`, { method: 'DELETE' }),

  // 问答
  sendChat: (payload) => request('/chat', { method: 'POST', body: JSON.stringify(payload) }),
  sendFeedback,
  shareFeedback,
  saveFeedbackNote,

  // 会话
  listConversations: (q = '') => request(`/conversations${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  getConversation: (id) => request(`/conversations/${id}`),
  deleteConversation: (id) => request(`/conversations/${id}`, { method: 'DELETE' }),

  // 评估
  listEvalRuns: () => request('/evaluation/runs'),
  getEvalRun: (id) => request(`/evaluation/runs/${id}`),
  runEvaluation: (payload) => request('/evaluation/run', { method: 'POST', body: JSON.stringify(payload) }),

  // 反馈管理（管理员）
  listFeedback,
}

export default api
