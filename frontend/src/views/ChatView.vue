<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, streamChat } from '@/api'
import MessageBubble from '@/components/MessageBubble.vue'

const toast = inject('toast')
const route = useRoute()
const router = useRouter()
const LAST_CONV_KEY = 'rag_last_conversation' // 记住本标签页最后打开的会话（sessionStorage，刷新保留，多标签页互不串台）
const input = ref('')
const busy = ref(false)
const topK = ref(5)
const useAgent = ref(true)
const streaming = ref(true) // 流式输出开关（默认开；与 Agent 模式互斥）
const msgBox = ref(null)

const conversations = ref([])
const currentConvId = ref(null)
const currentConv = ref(null)

const messages = computed(() => (currentConv.value ? currentConv.value.messages : []))

// Agent 模式多轮推理不适合逐字推送：开启 Agent 时自动关闭流式
watch(useAgent, (v) => {
  if (v && streaming.value) {
    streaming.value = false
    toast('Agent 模式不支持流式，已关闭流式输出', 'warn')
  }
})

function scrollToBottom() {
  requestAnimationFrame(() => {
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
  })
}

async function loadConversations() {
  try {
    conversations.value = await api.listConversations()
  } catch (e) {
    /* 静默失败，不影响主流程 */
  }
}

async function openConversation(id) {
  currentConvId.value = id || null
  currentConv.value = null
  if (id) {
    try {
      currentConv.value = await api.getConversation(id)
      sessionStorage.setItem(LAST_CONV_KEY, id)
    } catch (e) {
      sessionStorage.removeItem(LAST_CONV_KEY) // 会话已删除则清掉记忆，避免下次继续报错
      toast('加载会话失败：' + e.message, 'error')
    }
  }
}

/** 切换会话时同步 URL（支持从历史页跳入、刷新后仍停留在当前会话） */
function switchConversation(id) {
  openConversation(id)
  router.replace({ path: '/chat', query: id ? { conversation_id: id } : {} })
}

function newChat() {
  openConversation(null)
  sessionStorage.removeItem(LAST_CONV_KEY)
  router.replace({ path: '/chat' })
  input.value = ''
}

/** 导出当前会话为 Markdown */
async function exportCurrent() {
  const conv = currentConv.value
  if (!conv || !conv.id) {
    toast('当前没有可导出的会话', 'warn')
    return
  }
  try {
    const detail = await api.getConversation(conv.id)
    const lines = [`# ${detail.title}`, '', `> 导出时间：${new Date().toLocaleString('zh-CN', { hour12: false })}`, '']
    for (const m of detail.messages) {
      lines.push(m.role === 'user' ? '## 问' : '## 答', '', m.content, '')
      if (m.role === 'assistant' && m.sources && m.sources.length) {
        lines.push('**来源引用**')
        m.sources.forEach((s, i) => lines.push(`${i + 1}. ${s.filename}（相关度 ${s.score}）`))
        lines.push('')
      }
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${(detail.title || '会话').replace(/[\\/:*?"<>|]/g, '_')}.md`
    a.click()
    URL.revokeObjectURL(a.href)
    toast('会话已导出为 Markdown', 'ok')
  } catch (e) {
    toast('导出失败：' + e.message, 'error')
  }
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || busy.value) return
  input.value = ''
  busy.value = true
  if (!currentConv.value) {
    currentConv.value = { id: null, title: '', messages: [] }
  }

  const tmpUser = 'tmp_' + Date.now()
  currentConv.value.messages.push({ id: tmpUser, role: 'user', content: text, sources: null })

  if (streaming.value) {
    // ---- 流式：SSE 逐字渲染 ----
    const tmpAi = 'tmp_ai_' + Date.now()
    currentConv.value.messages.push({ id: tmpAi, role: 'assistant', content: '', sources: null, streaming: true })
    scrollToBottom()
    try {
      await streamChat(
        { message: text, conversation_id: currentConvId.value, top_k: topK.value, use_agent: false },
        (ev) => {
          if (ev.type === 'start') {
            currentConvId.value = ev.conversation_id
            sessionStorage.setItem(LAST_CONV_KEY, ev.conversation_id)
          } else if (ev.type === 'delta') {
            const m = currentConv.value.messages.find((x) => x.id === tmpAi)
            if (m) {
              m.content += ev.content
              scrollToBottom()
            }
          } else if (ev.type === 'done') {
            const m = currentConv.value.messages.find((x) => x.id === tmpAi)
            if (m) {
              m.id = ev.message_id
              m.sources = ev.sources
              m.streaming = false
            }
            currentConv.value.title = currentConv.value.title || text.slice(0, 24)
          } else if (ev.type === 'error') {
            throw new Error(ev.detail || '回答生成失败')
          }
        }
      )
    } catch (e) {
      currentConv.value.messages = currentConv.value.messages.filter((m) => m.id !== tmpAi)
      toast('回答失败：' + e.message, 'error')
    } finally {
      busy.value = false
    }
  } else {
    // ---- 非流式：一次返回 ----
    try {
      const res = await api.sendChat({
        message: text,
        conversation_id: currentConvId.value,
        top_k: topK.value,
        use_agent: useAgent.value,
      })
      const msgs = currentConv.value.messages.filter((m) => m.id !== tmpUser)
      msgs.push({ id: tmpUser, role: 'user', content: text, sources: null })
      msgs.push({ id: res.message_id, role: 'assistant', content: res.answer, sources: res.sources, trace: res.trace })
      currentConvId.value = res.conversation_id
      sessionStorage.setItem(LAST_CONV_KEY, res.conversation_id)
      currentConv.value = { id: res.conversation_id, title: currentConv.value.title || text.slice(0, 24), messages: msgs }
    } catch (e) {
      currentConv.value.messages = currentConv.value.messages.filter((m) => m.id !== tmpUser)
      toast('回答失败：' + e.message, 'error')
    } finally {
      busy.value = false
    }
  }
  await loadConversations()
  scrollToBottom()
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

onMounted(async () => {
  await loadConversations()
  // URL 指定会话优先；没有则恢复本标签页上次打开的会话（sessionStorage，各标签页独立）
  let cid = route.query.conversation_id
  if (!cid) cid = sessionStorage.getItem(LAST_CONV_KEY)
  if (cid) {
    await openConversation(cid)
  }
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1 class="page-title">智能问答</h1>
        <p class="page-sub">检索企业知识库，回答附来源引用；Agent 模式支持工具推理（检索 / 计算 / 时间 / 联网）。</p>
      </div>
      <div class="chat-head-right">
        <span v-if="currentConv && currentConv.title" class="chat-conv-title" :title="currentConv.title">
          {{ currentConv.title }}
        </span>
        <select v-model="currentConvId" class="input chat-sel" @change="switchConversation(currentConvId)">
          <option value="">新对话</option>
          <option v-for="c in conversations" :key="c.id" :value="c.id">
            {{ c.title }} · {{ c.message_count }}条
          </option>
        </select>
        <button class="btn" :disabled="!currentConv || !currentConv.id" title="导出当前会话为 Markdown" @click="exportCurrent">
          导出
        </button>
        <button class="btn" @click="newChat">新对话</button>
      </div>
    </div>

    <div class="card chat-card">
      <div class="chat-messages" ref="msgBox">
        <div v-if="!messages.length" class="empty">
          你好，我是企业知识库助手。<br>上传文档后向我提问，回答会附上来源引用。<br><br>提示：切换到「文档管理」上传知识库文件。
        </div>
        <MessageBubble v-for="m in messages" :key="m.id" :message="m" />
      </div>

      <div class="composer">
        <textarea
          v-model="input"
          class="input"
          placeholder="输入你的问题，Enter 发送，Shift+Enter 换行"
          :disabled="busy"
          @keydown="onKeydown"
        ></textarea>
        <button class="btn primary" :disabled="busy || !input.trim()" @click="sendMessage">
          {{ busy ? '回答中…' : '发送' }}
        </button>
      </div>

      <div class="param-bar card">
        <label class="switch">
          <input v-model="streaming" type="checkbox" />
          <span class="track"></span>
          <span>流式输出</span>
        </label>
        <label class="switch">
          <input v-model="useAgent" type="checkbox" />
          <span class="track"></span>
          <span>Agent 模式（工具推理）</span>
        </label>
        <label class="param">
          <span class="label">检索条数 Top-K</span>
          <select v-model.number="topK" class="input" style="width: 110px">
            <option v-for="k in [3, 5, 8, 10]" :key="k" :value="k">{{ k }}</option>
          </select>
        </label>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-head-right { display: flex; align-items: center; gap: 10px; max-width: 100%; }
.chat-conv-title { font-size: 13px; color: var(--ink-2); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-sel { max-width: 260px; width: auto; }

.chat-card { display: flex; flex-direction: column; min-height: calc(100vh - 210px); }
.chat-messages { flex: 1; overflow-y: auto; padding: 20px; max-height: calc(100vh - 380px); }

.composer { display: flex; gap: 10px; align-items: flex-end; padding: 14px 18px; border-top: 1px solid var(--line); }
.composer textarea { flex: 1; resize: vertical; min-height: 52px; max-height: 160px; }
.composer .btn { height: 44px; flex-shrink: 0; }

.param-bar { display: flex; gap: 20px; flex-wrap: wrap; align-items: center; margin: 14px 18px 18px; padding: 12px 16px; }

.switch { position: relative; display: inline-flex; align-items: center; gap: 9px; cursor: pointer; font-size: 13px; color: var(--ink-2); user-select: none; }
.switch input { position: absolute; opacity: 0; width: 0; height: 0; }
.switch .track {
  width: 36px; height: 20px; border-radius: 999px; background: #d6dce4;
  transition: background .15s; position: relative; flex-shrink: 0;
}
.switch .track::after {
  content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px;
  border-radius: 50%; background: #fff; transition: transform .15s; box-shadow: 0 1px 2px rgba(16, 28, 46, .2);
}
.switch input:checked + .track { background: var(--accent); }
.switch input:checked + .track::after { transform: translateX(16px); }
.switch input:focus-visible + .track { outline: 2px solid var(--accent); outline-offset: 2px; }

.param { display: flex; flex-direction: column; }
.param .label { margin-bottom: 4px; }

@media (max-width: 860px) {
  .chat-messages { max-height: none; }
  .chat-card { min-height: auto; }
}
</style>
