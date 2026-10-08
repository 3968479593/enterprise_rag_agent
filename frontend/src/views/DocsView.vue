<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import { api, uploadFile } from '@/api'

const toast = inject('toast')
const docs = ref([])
const uploading = ref(false)
const fileInput = ref(null)
const dragOver = ref(false)

const ACCEPT = '.txt,.md,.pdf,.docx,.csv,.json'

const count = computed(() => docs.value.length)

async function loadDocs() {
  try {
    docs.value = await api.listDocuments()
  } catch (e) {
    toast('加载文档失败：' + e.message, 'error')
  }
}

async function doUpload(file) {
  if (!file) return
  uploading.value = true
  try {
    const j = await uploadFile(file)
    toast(`已入库 ${j.filename}（${j.chunk_count} 块）`, 'ok')
    await loadDocs()
  } catch (e) {
    toast('上传失败：' + e.message, 'error')
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onFileChange(e) {
  if (e.target.files.length) doUpload(e.target.files[0])
}

function onDrop(e) {
  e.preventDefault()
  dragOver.value = false
  if (e.dataTransfer.files.length) doUpload(e.dataTransfer.files[0])
}

async function deleteDoc(id, filename) {
  if (!confirm(`确认删除「${filename}」及其全部切块？此操作不可撤销。`)) return
  try {
    await api.deleteDocument(id)
    toast('文档已删除', 'ok')
    await loadDocs()
  } catch (e) {
    toast('删除失败：' + e.message, 'error')
  }
}

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(loadDocs)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1 class="page-title">文档管理</h1>
        <p class="page-sub">支持 txt / md / pdf / docx / csv / json，上传后自动切块并向量化入库。</p>
      </div>
      <span class="hint">共 {{ count }} 份</span>
    </div>

    <div
      class="drop-zone"
      :class="{ drag: dragOver }"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop="onDrop"
      @click="fileInput.click()"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 16V5M7 9l5-5 5 5M5 19h14" />
      </svg>
      <div class="dz-title">{{ uploading ? '上传中…' : '点击选择文件，或将文件拖拽到此处' }}</div>
      <div class="hint">单个文件不超过 20MB</div>
      <input
        ref="fileInput"
        type="file"
        :accept="ACCEPT"
        style="display: none"
        :disabled="uploading"
        @change="onFileChange"
      />
    </div>

    <div class="card" style="margin-top: 18px">
      <div class="card-h"><h2>知识库文档</h2></div>
      <div class="table-wrap">
        <table class="tbl">
          <thead>
            <tr>
              <th>文件名</th>
              <th>类型</th>
              <th>状态</th>
              <th>切块数</th>
              <th>字符数</th>
              <th>上传时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in docs" :key="d.id">
              <td style="max-width: 300px">
                <div class="fname" :title="d.filename">{{ d.filename }}</div>
                <div v-if="d.error" class="hint" style="font-size: 11px; color: var(--danger)">
                  {{ String(d.error).slice(0, 80) }}
                </div>
              </td>
              <td><span class="badge plain">{{ d.source_type }}</span></td>
              <td>
                <span class="badge" :class="d.status === 'ingested' ? 'ok' : d.status === 'failed' ? 'fail' : 'pending'">
                  {{ d.status === 'ingested' ? '已入库' : d.status === 'failed' ? '失败' : '处理中' }}
                </span>
              </td>
              <td class="mono">{{ d.chunk_count }}</td>
              <td class="mono">{{ d.meta && d.meta.char_count != null ? d.meta.char_count : '—' }}</td>
              <td class="hint">{{ fmtTime(d.created_at) }}</td>
              <td>
                <button class="btn danger" style="padding: 5px 12px; font-size: 12.5px" @click="deleteDoc(d.id, d.filename)">
                  删除
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!docs.length" class="empty">还没有文档。上传第一份知识库文件开始使用。</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.drop-zone {
  border: 2px dashed #cdd5e0; border-radius: var(--radius); padding: 34px 18px;
  text-align: center; cursor: pointer; background: var(--surface);
  transition: border-color .15s, background .15s;
}
.drop-zone.drag { border-color: var(--accent); background: var(--accent-weak); }
.drop-zone svg { width: 30px; height: 30px; color: var(--ink-3); margin-bottom: 8px; }
.dz-title { font-size: 14px; font-weight: 500; margin-bottom: 4px; }

.fname { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
