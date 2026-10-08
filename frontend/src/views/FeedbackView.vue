<script setup>
/** 反馈管理（仅管理员）：统计 + 列表 + 展开查看完整对话，定位知识库问题。 */
import { inject, onMounted, ref } from 'vue'
import { api } from '@/api'

const toast = inject('toast')
const kind = ref('') // '' 全部 / up 有用 / down 没用
const data = ref({ items: [], stats: { total: 0, up: 0, down: 0 }, doc_down: [] })
const loading = ref(false)
const expanded = ref(null) // 展开的 message_id
const convCache = ref({}) // conversation_id -> 对话详情

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : d.toLocaleString('zh-CN', { hour12: false })
}

function snippet(s, n = 60) {
  return (s || '').length > n ? s.slice(0, n) + '…' : s
}

async function load() {
  loading.value = true
  try {
    data.value = await api.listFeedback(kind.value)
  } catch (e) {
    toast('加载反馈失败：' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

function setKind(k) {
  kind.value = k
  load()
}

async function toggleExpand(item) {
  if (expanded.value === item.message_id) {
    expanded.value = null
    return
  }
  expanded.value = item.message_id
  if (!convCache.value[item.conversation_id]) {
    try {
      convCache.value[item.conversation_id] = await api.getConversation(item.conversation_id)
    } catch (e) {
      toast('对话已删除或无权查看', 'error')
    }
  }
}

const statCards = [
  { key: 'total', label: '总反馈', cls: 'c-total' },
  { key: 'up', label: '有用', cls: 'c-up' },
  { key: 'down', label: '没用', cls: 'c-down' },
]

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1 class="page-title">反馈管理</h1>
        <p class="page-sub">仅展示用户已同意共享的反馈，点「没用」最多的文档说明知识库内容需要优化。</p>
      </div>
    </div>

    <!-- 统计 -->
    <div class="stat-row">
      <div v-for="c in statCards" :key="c.key" class="stat-card" :class="c.cls">
        <div class="stat-num">{{ data.stats[c.key] ?? 0 }}</div>
        <div class="stat-label">{{ c.label }}</div>
      </div>
      <div class="stat-card c-doc">
        <div class="stat-num" style="font-size: 15px">{{ data.doc_down.length }}</div>
        <div class="stat-label">被点没用的文档</div>
      </div>
    </div>

    <!-- 被点"没用"最多的文档 -->
    <div class="card doc-down" v-if="data.doc_down.length">
      <div class="card-h">
        <h2>待优化文档</h2>
        <span class="hint">回答被多次点「没用」，建议核查知识内容</span>
      </div>
      <div class="doc-tags">
        <span v-for="d in data.doc_down" :key="d.filename" class="doc-tag">
          <span class="doc-name" :title="d.filename">{{ d.filename }}</span>
          <span class="doc-count">{{ d.count }} 次</span>
        </span>
      </div>
      <div v-if="!data.doc_down.length" class="empty small">暂无「没用」反馈，知识库状态良好</div>
    </div>

    <!-- 列表 -->
    <div class="card fb-card">
      <div class="card-h">
        <h2>反馈记录</h2>
        <div class="fb-tabs">
          <button v-for="t in [{ k: '', l: '全部' }, { k: 'up', l: '有用' }, { k: 'down', l: '没用' }]" :key="t.k"
            class="tab" :class="{ on: kind === t.k }" @click="setKind(t.k)">{{ t.l }}</button>
        </div>
        <span class="hint">{{ data.items.length }} 条</span>
      </div>

      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!data.items.length" class="empty">还没有反馈记录，去问答页给回答点个有用或没用吧</div>

      <div v-else class="fb-list">
        <div v-for="item in data.items" :key="item.message_id" class="fb-item">
          <div class="fb-head" @click="toggleExpand(item)">
            <span class="fb-badge" :class="item.feedback">{{ item.feedback === 'up' ? '有用' : '没用' }}</span>
            <span class="fb-user" :title="item.username">{{ item.username }}</span>
            <span class="fb-conv" :title="item.conversation_title">{{ item.conversation_title }}</span>
            <span class="fb-snip">{{ snippet(item.content) }}</span>
            <span class="fb-time">{{ fmtTime(item.created_at) }}</span>
            <span class="fb-arrow">{{ expanded === item.message_id ? '收起' : '查看对话' }}</span>
          </div>
          <div v-if="item.note" class="fb-note-line">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 6h16v12H7l-3 3V6z" stroke-linejoin="round" />
            </svg>
            <span class="fb-note-text" :title="item.note">{{ item.note }}</span>
          </div>
          <div v-if="expanded === item.message_id" class="fb-detail">
            <div v-if="convCache[item.conversation_id]" class="conv-box">
              <div v-for="m in convCache[item.conversation_id].messages" :key="m.id"
                class="conv-msg" :class="m.role">
                <span class="conv-role">{{ m.role === 'user' ? '问' : '答' }}</span>
                <div class="conv-body">
                  <div class="conv-content">{{ m.content }}</div>
                  <div v-if="m.role === 'assistant' && m.sources && m.sources.length" class="conv-src">
                    来源：<span v-for="(s, i) in m.sources.slice(0, 3)" :key="i">{{ s.filename }}<i v-if="i < m.sources.slice(0, 3).length - 1">、</i></span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="empty small">对话不可用（已删除或加载失败）</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 18px; }
.stat-card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; box-shadow: var(--shadow); }
.stat-num { font-size: 26px; font-weight: 700; line-height: 1.2; }
.stat-label { font-size: 12px; color: var(--ink-3); margin-top: 3px; }
.c-up .stat-num { color: var(--ok); }
.c-down .stat-num { color: var(--danger); }
.c-doc .stat-num { color: var(--warn); }

.doc-down { margin-bottom: 18px; }
.doc-tags { display: flex; flex-wrap: wrap; gap: 8px; padding: 4px 4px 14px; }
.doc-tag {
  display: inline-flex; align-items: center; gap: 8px; background: #fff8ec;
  border: 1px solid #f3e2bf; border-radius: 999px; padding: 4px 12px; font-size: 12.5px;
}
.doc-name { color: var(--ink-1); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-count { color: var(--warn); font-weight: 600; flex-shrink: 0; }

.fb-card { display: flex; flex-direction: column; max-height: calc(100vh - 330px); }
.fb-list { overflow-y: auto; padding: 6px; }
.fb-item { border-bottom: 1px solid var(--line); }
.fb-item:last-child { border-bottom: none; }
.fb-head { display: flex; align-items: center; gap: 10px; padding: 11px 10px; cursor: pointer; border-radius: 8px; }
.fb-head:hover { background: #f6f8fb; }
.fb-badge { flex-shrink: 0; font-size: 11.5px; font-weight: 600; padding: 2px 9px; border-radius: 999px; }
.fb-badge.up { background: #e6f6ee; color: #18855b; }
.fb-badge.down { background: #fdecec; color: #d33a3a; }
.fb-user { font-weight: 600; font-size: 13px; flex-shrink: 0; max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fb-conv { color: var(--ink-2); font-size: 12.5px; flex-shrink: 0; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fb-snip { flex: 1; color: var(--ink-3); font-size: 12.5px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fb-time { color: var(--ink-3); font-size: 11.5px; flex-shrink: 0; }
.fb-arrow { flex-shrink: 0; color: var(--accent); font-size: 12px; }

.fb-note-line {
  display: flex; align-items: center; gap: 7px; margin: 0 10px 9px 48px;
  background: #f4f7fa; border: 1px solid var(--line); border-radius: 8px;
  padding: 5px 10px; font-size: 12.5px; color: var(--ink-2); max-width: 640px;
}
.fb-note-line svg { width: 13px; height: 13px; color: var(--ink-3); flex-shrink: 0; }
.fb-note-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.fb-detail { padding: 4px 10px 14px 34px; }
.conv-box { border: 1px solid var(--line); border-radius: 10px; background: #fafbfd; padding: 10px 12px; max-height: 420px; overflow-y: auto; }
.conv-msg { display: flex; gap: 10px; padding: 7px 0; }
.conv-role {
  flex-shrink: 0; width: 22px; height: 22px; border-radius: 6px; font-size: 11.5px;
  display: flex; align-items: center; justify-content: center; margin-top: 1px;
}
.conv-msg.user .conv-role { background: #e8f0f1; color: #0d7f8c; }
.conv-msg.assistant .conv-role { background: #eef1f6; color: var(--ink-2); }
.conv-body { flex: 1; min-width: 0; }
.conv-content { font-size: 13px; line-height: 1.7; color: var(--ink-1); white-space: pre-wrap; word-break: break-word; }
.conv-src { margin-top: 4px; font-size: 11.5px; color: var(--ink-3); }

.fb-tabs { display: flex; gap: 4px; margin-left: auto; background: #eef1f6; border-radius: 8px; padding: 3px; }
.fb-tabs .tab { border: none; background: transparent; font-size: 12px; color: var(--ink-2); padding: 4px 12px; border-radius: 6px; cursor: pointer; }
.fb-tabs .tab.on { background: var(--surface); color: var(--accent); font-weight: 600; box-shadow: var(--shadow); }

.empty.small { padding: 16px 10px; font-size: 12.5px; }
@media (max-width: 860px) {
  .stat-row { grid-template-columns: repeat(2, 1fr); }
  .fb-head { flex-wrap: wrap; }
  .fb-snip { flex-basis: 100%; }
}
</style>
