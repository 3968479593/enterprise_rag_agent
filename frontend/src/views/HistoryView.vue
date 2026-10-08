<script setup>
import { inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'

const toast = inject('toast')
const router = useRouter()
const conversations = ref([])
const keyword = ref('')
let searchTimer = null

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : d.toLocaleString('zh-CN', { hour12: false })
}

async function loadHistory() {
  try {
    conversations.value = await api.listConversations(keyword.value.trim())
  } catch (e) {
    toast('加载会话列表失败：' + e.message, 'error')
  }
}

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadHistory, 300) // 输入防抖
}

function clearSearch() {
  keyword.value = ''
  loadHistory()
}

function continueChat(id) {
  router.push({ path: '/chat', query: { conversation_id: id } })
}

async function deleteHistory(id) {
  if (!confirm('确认删除该会话？')) return
  try {
    await api.deleteConversation(id)
    toast('会话已删除', 'ok')
    await loadHistory()
  } catch (e) {
    toast('删除失败：' + e.message, 'error')
  }
}

onMounted(loadHistory)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1 class="page-title">会话历史</h1>
        <p class="page-sub">点击会话即可进入「智能问答」继续对话，历史消息与来源引用完整保留。</p>
      </div>
    </div>

    <div class="card his-card">
      <div class="card-h">
        <h2>会话列表</h2>
        <div class="search-box">
          <input v-model="keyword" class="input" placeholder="搜索会话标题…" @input="onSearch" />
          <button v-if="keyword" class="search-clear" title="清除" @click="clearSearch">×</button>
        </div>
        <span class="hint">{{ conversations.length }} 个会话</span>
      </div>
      <div class="his-items">
        <div v-if="!conversations.length" class="empty">还没有会话，去「智能问答」发起第一轮提问。</div>
        <div v-for="c in conversations" :key="c.id" class="his-item" @click="continueChat(c.id)">
          <div class="his-main">
            <div class="his-title">{{ c.title }}</div>
            <div class="his-meta">{{ c.message_count }} 条消息 · {{ fmtTime(c.updated_at) }}</div>
          </div>
          <div class="his-actions">
            <button class="btn sm" @click.stop="continueChat(c.id)">继续对话</button>
            <button class="his-del" title="删除" @click.stop="deleteHistory(c.id)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.his-card { max-height: calc(100vh - 190px); display: flex; flex-direction: column; }
.his-items { overflow-y: auto; padding: 8px; }

.search-box { position: relative; display: flex; align-items: center; margin-left: auto; }
.search-box .input { width: 200px; padding: 6px 26px 6px 10px; font-size: 12.5px; }
.search-clear { position: absolute; right: 6px; border: none; background: none; color: var(--ink-3); font-size: 15px; cursor: pointer; line-height: 1; }

.his-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 8px; cursor: pointer; margin-bottom: 2px; transition: background .12s; }
.his-item:hover { background: #f3f6fa; }
.his-main { flex: 1; min-width: 0; }
.his-title { font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.his-meta { font-size: 11.5px; color: var(--ink-3); margin-top: 3px; }

.his-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.his-del { border: none; background: none; color: var(--ink-3); font-size: 12px; cursor: pointer; padding: 4px 8px; border-radius: 5px; }
.his-del:hover { color: var(--danger); background: var(--danger-weak); }
</style>
