/** 消息气泡：用户/助手消息 + 来源引用折叠 + 推理轨迹折叠 + 回答反馈。 */
<script setup>
import { computed, inject, nextTick, ref } from 'vue'
import { api } from '@/api'

const props = defineProps({
  message: { type: Object, required: true },
})

const toast = inject('toast')
const feedback = ref(props.message.feedback || null)
const shared = ref(!!props.message.feedback_shared)
const note = ref(props.message.feedback_note || null)
const noteDraft = ref('')
const noteOpen = ref(false)
const noteInput = ref(null)
const fbBusy = ref(false)

function fmtScore(v) {
  return v == null ? '—' : v
}

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : d.toLocaleString('zh-CN', { hour12: false })
}

/** 轻量 Markdown 渲染：只转义 HTML 并处理加粗/行内代码，符号不再裸露 */
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

const rendered = computed(() => {
  let s = escapeHtml(props.message.content || '')
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  return s
})

async function toggleFeedback(value) {
  if (fbBusy.value || !props.message.id) return
  fbBusy.value = true
  try {
    const next = feedback.value === value ? null : value // 再点一次取消
    const res = await api.sendFeedback(props.message.id, next)
    feedback.value = res.feedback
    props.message.feedback = res.feedback
    const label = res.feedback === 'up' ? '已标记为有用' : res.feedback === 'down' ? '已标记为没用' : '已取消反馈'
    if (toast) toast(label, res.feedback ? 'ok' : 'info')
  } catch (e) {
    if (toast) toast('反馈失败：' + e.message, 'error')
  } finally {
    fbBusy.value = false
  }
}

/** 隐私开关：只有用户明确勾选，管理员端才可见该条反馈与对话 */
async function toggleShared() {
  if (fbBusy.value || !props.message.id) return
  fbBusy.value = true
  try {
    const next = !shared.value
    const res = await api.shareFeedback(props.message.id, next)
    shared.value = res.shared
    props.message.feedback_shared = res.shared
    if (toast) toast(next ? '已授权管理员查看此对话' : '已取消授权', next ? 'ok' : 'info')
  } catch (e) {
    if (toast) toast('操作失败：' + e.message, 'error')
  } finally {
    fbBusy.value = false
  }
}

/** 反馈意见：平滑展开输入，回车或点提交保存；空内容则清除 */
function openNote() {
  noteDraft.value = note.value || ''
  noteOpen.value = true
  nextTick(() => {
    if (noteInput.value) noteInput.value.focus()
  })
}

function cancelNote() {
  noteOpen.value = false
  noteDraft.value = note.value || ''
}

async function saveNote() {
  if (fbBusy.value || !props.message.id) return
  fbBusy.value = true
  try {
    const text = noteDraft.value.trim()
    const res = await api.saveFeedbackNote(props.message.id, text)
    note.value = res.note || null
    props.message.feedback_note = res.note || null
    noteOpen.value = false
    if (toast) toast(text ? '意见已保存' : '已清除意见', text ? 'ok' : 'info')
  } catch (e) {
    if (toast) toast('保存失败：' + e.message, 'error')
  } finally {
    fbBusy.value = false
  }
}

async function clearNote() {
  if (fbBusy.value || !props.message.id) return
  fbBusy.value = true
  try {
    const res = await api.saveFeedbackNote(props.message.id, '')
    note.value = null
    props.message.feedback_note = null
    noteOpen.value = false
    if (toast) toast('已清除意见', 'info')
  } catch (e) {
    if (toast) toast('操作失败：' + e.message, 'error')
  } finally {
    fbBusy.value = false
  }
}
</script>

<template>
  <div class="msg" :class="message.role">
    <div class="bubble">
      <div v-if="message.content" class="content" v-html="rendered"></div>
      <div v-else-if="message.streaming" class="content typing">▍</div>

      <div v-if="message.role === 'assistant' && message.id" class="fb-row">
        <button
          class="fb-btn"
          :class="{ on: feedback === 'up' }"
          title="回答有用"
          :disabled="fbBusy"
          @click="toggleFeedback('up')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M7 10v11M3 10h4l4-6a2 2 0 0 1 2 2v4h5a2 2 0 0 1 2 2l-1.5 6a2 2 0 0 1-2 1.6H7" />
          </svg>
          有用
        </button>
        <button
          class="fb-btn"
          :class="{ on: feedback === 'down' }"
          title="回答没用"
          :disabled="fbBusy"
          @click="toggleFeedback('down')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M17 14V3M21 14h-4l-4 6a2 2 0 0 1-2-2v-4H6a2 2 0 0 1-2-2l1.5-6a2 2 0 0 1 2-1.6H17" />
          </svg>
          没用
        </button>
        <label v-if="feedback" class="fb-share" :class="{ on: shared }">
          <input type="checkbox" :checked="shared" :disabled="fbBusy" @change="toggleShared" />
          <span>同意管理员查看此对话</span>
        </label>
      </div>

      <!-- 反馈意见：平滑展开，不打断阅读 -->
      <Transition name="note">
        <div v-if="feedback && note && !noteOpen" class="note-view" title="点击编辑意见" @click="openNote">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 6h16v12H7l-3 3V6z" stroke-linejoin="round" />
            <path d="M8 10h8M8 13h5" stroke-linecap="round" />
          </svg>
          <span class="note-view-text">{{ note }}</span>
          <span class="note-view-edit">编辑</span>
          <button class="note-view-del" title="清除意见" @click.stop="clearNote">×</button>
        </div>
      </Transition>
      <Transition name="note">
        <div v-if="feedback && noteOpen" class="note-editor">
          <input
            ref="noteInput"
            v-model="noteDraft"
            class="note-input"
            placeholder="补充意见，帮助改进（可选）"
            maxlength="200"
            @keydown.enter.prevent="saveNote"
          />
          <button class="note-btn" :disabled="fbBusy" @click="saveNote">保存</button>
          <button v-if="noteOpen" class="note-btn ghost" :disabled="fbBusy" @click="cancelNote">取消</button>
        </div>
      </Transition>
      <button v-if="feedback && !note && !noteOpen" class="note-add" @click="openNote">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
        补充意见
      </button>

      <details v-if="message.role === 'assistant' && message.sources && message.sources.length" class="details-fold">
        <summary>来源引用 · {{ message.sources.length }} 条</summary>
        <div class="src-list">
          <div v-for="(s, i) in message.sources" :key="s.chunk_id" class="src-item">
            <span class="src-badge">{{ i + 1 }}</span>
            <div>
              <div class="src-file">{{ s.filename }}</div>
              <div class="src-snip">{{ s.snippet }}</div>
              <div class="src-score">相关度 {{ fmtScore(s.score) }} · {{ fmtTime(message.created_at) }}</div>
            </div>
          </div>
        </div>
      </details>

      <details
        v-if="message.role === 'assistant' && message.trace && message.trace.steps && message.trace.steps.length"
        class="details-fold"
      >
        <summary>推理轨迹 · {{ message.trace.mode === 'agent' ? 'Agent' : '直答' }}</summary>
        <div class="trace">
          <div v-for="(s, i) in message.trace.steps" :key="i" class="trace-step">
            <span v-if="s.type === 'assistant_reply'" class="trace-tag t-thought">Thought</span>
            <span v-else-if="s.type === 'tool_call'" class="trace-tag t-action">Tool · {{ s.tool }}</span>
            {{ s.type === 'tool_call' ? (s.observation || '') : (s.thought != null ? s.thought : s.content) }}
          </div>
        </div>
      </details>
    </div>
  </div>
</template>

<style scoped>
.msg { display: flex; margin-bottom: 14px; }
.msg.user { justify-content: flex-end; }
.bubble {
  max-width: 78%; padding: 11px 15px; border-radius: 12px;
  white-space: pre-wrap; word-break: break-word; font-size: 14px;
}
.bubble :deep(strong) { font-weight: 600; }
.bubble :deep(code) {
  font-family: var(--mono); font-size: 12.5px; background: #eef1f6;
  border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px;
}
.typing { color: var(--accent); animation: blink 1s steps(2, start) infinite; }
@keyframes blink { to { visibility: hidden; } }
.msg.user .bubble { background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
.msg.assistant .bubble {
  background: var(--surface); border: 1px solid var(--line); color: var(--ink);
  border-bottom-left-radius: 4px; box-shadow: var(--shadow);
}
.details-fold { margin-top: 9px; border-top: 1px dashed var(--line); padding-top: 8px; }

.fb-row { display: flex; align-items: center; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
.fb-btn {
  display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--line);
  background: #f8fafc; color: var(--ink-3); font-size: 11.5px; border-radius: 6px;
  padding: 2px 8px; cursor: pointer; transition: all .15s;
}
.fb-btn svg { width: 12px; height: 12px; }
.fb-btn:hover { border-color: #c6cfda; color: var(--ink-2); }
.fb-btn.on { background: var(--accent-weak); border-color: var(--accent); color: var(--accent); }
.fb-btn:disabled { opacity: .5; cursor: default; }

.fb-share {
  display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--ink-3);
  cursor: pointer; user-select: none; margin-left: 4px;
}
.fb-share input { accent-color: var(--accent); width: 13px; height: 13px; }
.fb-share:hover { color: var(--ink-2); }
.fb-share.on { color: var(--accent); }

/* ---- 反馈意见（平滑展开） ---- */
.note-view {
  display: flex; align-items: center; gap: 7px; margin-top: 9px;
  background: #f4f7fa; border: 1px solid var(--line); border-radius: 8px;
  padding: 6px 10px; font-size: 12.5px; color: var(--ink-2); cursor: pointer;
  transition: border-color .15s, background .15s; max-width: 560px;
}
.note-view:hover { border-color: #c6cfda; background: #f0f4f8; }
.note-view svg { width: 13px; height: 13px; color: var(--ink-3); flex-shrink: 0; }
.note-view-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note-view-edit { flex-shrink: 0; color: var(--accent); font-size: 11.5px; }
.note-view-del {
  flex-shrink: 0; border: none; background: none; color: var(--ink-3); font-size: 15px;
  cursor: pointer; line-height: 1; padding: 0 2px;
}
.note-view-del:hover { color: var(--danger); }

.note-editor { display: flex; gap: 7px; margin-top: 9px; max-width: 560px; }
.note-input {
  flex: 1; min-width: 0; border: 1px solid var(--line); border-radius: 8px;
  padding: 6px 10px; font-size: 12.5px; background: var(--surface);
  transition: border-color .15s, box-shadow .15s;
}
.note-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(13, 127, 140, .1); }
.note-btn {
  flex-shrink: 0; border: 1px solid var(--accent); background: var(--accent); color: #fff;
  font-size: 12px; border-radius: 7px; padding: 0 13px; cursor: pointer; transition: opacity .15s;
}
.note-btn:hover { opacity: .88; }
.note-btn.ghost { background: none; color: var(--ink-2); border-color: var(--line); }
.note-btn:disabled { opacity: .5; cursor: default; }

.note-add {
  display: inline-flex; align-items: center; gap: 4px; margin-top: 8px;
  border: none; background: none; color: var(--ink-3); font-size: 11.5px;
  cursor: pointer; padding: 2px 4px; border-radius: 5px; transition: color .15s, background .15s;
}
.note-add:hover { color: var(--accent); background: rgba(13, 127, 140, .06); }
.note-add svg { width: 12px; height: 12px; }

.note-enter-active, .note-leave-active { transition: all .22s ease; overflow: hidden; max-height: 52px; }
.note-enter-from, .note-leave-to { max-height: 0; opacity: 0; margin-top: 0; padding-top: 0; }
.details-fold summary {
  cursor: pointer; color: var(--ink-2); font-size: 12.5px; user-select: none;
  list-style: none; display: inline-flex; align-items: center; gap: 6px;
}
.details-fold summary::-webkit-details-marker { display: none; }
.details-fold summary::before {
  content: ""; width: 0; height: 0; border-left: 5px solid var(--ink-3);
  border-top: 4px solid transparent; border-bottom: 4px solid transparent;
  transition: transform .15s;
}
.details-fold[open] summary::before { transform: rotate(90deg); }

.src-list { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.src-item { display: flex; gap: 9px; background: #f6f8fb; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.src-badge { font-family: var(--mono); color: var(--ink-3); font-size: 12px; flex-shrink: 0; padding-top: 1px; }
.src-file { font-size: 12.5px; font-weight: 500; }
.src-snip {
  font-size: 12.5px; color: var(--ink-2);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.src-score { font-size: 11px; color: var(--ink-3); margin-top: 2px; }

.trace { margin-top: 8px; display: flex; flex-direction: column; gap: 5px; }
.trace-step {
  font-size: 12px; padding: 6px 9px; background: #f8fafc; border: 1px solid var(--line);
  border-radius: 6px; color: var(--ink-2); white-space: pre-wrap; word-break: break-word;
}
.trace-tag { display: inline-block; font-size: 10.5px; font-weight: 700; border-radius: 4px; padding: 1px 6px; margin-right: 6px; vertical-align: 1px; }
.trace-tag.t-thought { background: var(--accent-weak); color: var(--accent); }
.trace-tag.t-action { background: var(--warn-weak); color: var(--warn); }

@media (max-width: 860px) {
  .bubble { max-width: 92%; }
}
</style>
