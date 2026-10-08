<script setup>
// 离线评估视图：评测表单 + 七维指标卡 + ECharts 柱状图（图表逻辑直接内联，不单独建组件）
import * as echarts from 'echarts'
import { inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '@/api'

const toast = inject('toast')
const runs = ref([])
const runDetail = ref(null)
const running = ref(false)

const evalName = ref('eval')
const evalTopK = ref(5)
const questionsText = ref('公司年假政策是什么？|年假\n加班费怎么计算？|加班')

const METRIC_CARDS = [
  ['命中率 hit@k', 'hit_rate'],
  ['MRR@k', 'mrr'],
  ['精确率 P@k', 'precision_at_k'],
  ['召回率 R@k', 'recall_at_k'],
  ['忠实度', 'faithfulness'],
  ['切题度', 'answer_relevancy'],
  ['平均耗时', 'latency_ms_avg'],
]

const CHART_METRICS = [
  ['hit_rate', '命中率'],
  ['mrr', 'MRR'],
  ['precision_at_k', '精确率'],
  ['recall_at_k', '召回率'],
  ['faithfulness', '忠实度'],
  ['answer_relevancy', '切题度'],
]

const chartEl = ref(null)
let chart = null

function renderChart() {
  if (!chartEl.value) return
  const metrics = (runDetail.value && runDetail.value.metrics) || {}
  const labels = []
  const values = []
  CHART_METRICS.forEach(([key, label]) => {
    if (metrics[key] != null) {
      labels.push(label)
      values.push(Number(metrics[key]))
    }
  })
  if (!labels.length) {
    if (chart) { chart.dispose(); chart = null }
    chartEl.value.innerHTML = '<div class="empty">暂无数值型指标</div>'
    return
  }
  if (!chart) chart = echarts.init(chartEl.value)
  chart.setOption({
    grid: { left: 44, right: 16, top: 24, bottom: 30 },
    tooltip: { trigger: 'axis', valueFormatter: (v) => (typeof v === 'number' ? v.toFixed(3) : v) },
    xAxis: {
      type: 'category', data: labels,
      axisLine: { lineStyle: { color: '#d5dbe4' } },
      axisLabel: { color: '#5c6675', fontSize: 11 },
    },
    yAxis: {
      type: 'value', min: 0, max: 1,
      splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { color: '#8a93a3', fontSize: 10 },
    },
    series: [{
      type: 'bar', data: values, barWidth: '46%',
      itemStyle: { color: '#0d7f8c', borderRadius: [5, 5, 0, 0] },
      label: { show: true, position: 'top', fontSize: 10, color: '#5c6675', formatter: (p) => p.value.toFixed(3) },
    }],
  })
}

function onResize() {
  if (chart) chart.resize()
}

watch(runDetail, renderChart, { deep: true })

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : d.toLocaleString('zh-CN', { hour12: false })
}

function fmtVal(v) {
  if (v == null) return '—'
  return typeof v === 'number' ? v : String(v)
}

async function loadRuns() {
  try {
    runs.value = await api.listEvalRuns()
  } catch (e) {
    toast('加载评估记录失败：' + e.message, 'error')
  }
}

async function runEval() {
  const name = evalName.value.trim() || 'eval'
  const topK = evalTopK.value || 5
  const raw = questionsText.value.trim()
  if (!raw) {
    toast('请先填写评测问题', 'warn')
    return
  }
  const questions = raw
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const i = l.indexOf('|')
      return i > 0
        ? { question: l.slice(0, i).trim(), ground_truth: l.slice(i + 1).trim() }
        : { question: l, ground_truth: '' }
    })

  running.value = true
  try {
    runDetail.value = await api.runEvaluation({ name, top_k: topK, questions })
    toast('评估完成：' + runDetail.value.name, 'ok')
    await loadRuns()
  } catch (e) {
    toast('评估失败：' + e.message, 'error')
  } finally {
    running.value = false
  }
}

async function viewRun(id) {
  try {
    runDetail.value = await api.getEvalRun(id)
  } catch (e) {
    toast('加载评估详情失败：' + e.message, 'error')
  }
}

onMounted(() => {
  loadRuns()
  renderChart()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (chart) { chart.dispose(); chart = null }
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1 class="page-title">离线评估</h1>
        <p class="page-sub">对检索质量做量化评测：命中率 / MRR / 精确率 / 召回率（无需 LLM），忠实度 / 切题度由 LLM 判分。</p>
      </div>
    </div>

    <div class="eval-layout">
      <div class="eval-left">
        <div class="card">
          <div class="card-h"><h2>运行评估</h2></div>
          <div class="card-b eval-form">
            <div class="form-row">
              <div class="field" style="flex: 1">
                <label class="label">任务名称</label>
                <input v-model="evalName" class="input" placeholder="eval" />
              </div>
              <div class="field" style="width: 140px">
                <label class="label">Top-K</label>
                <select v-model.number="evalTopK" class="input">
                  <option v-for="k in [3, 5, 8, 10]" :key="k" :value="k">{{ k }}</option>
                </select>
              </div>
            </div>
            <div class="field">
              <label class="label">评测问题（每行一题，可选「问题 | 标准答案」）</label>
              <textarea v-model="questionsText" class="input" rows="7" style="font-family: var(--mono); font-size: 12.5px"></textarea>
            </div>
            <button class="btn primary" style="width: 100%" :disabled="running" @click="runEval">
              {{ running ? '评估中…' : '开始评估' }}
            </button>
          </div>
        </div>

        <div class="card" style="margin-top: 16px">
          <div class="card-h"><h2>历史记录</h2></div>
          <div class="run-list">
            <div v-if="!runs.length" class="empty">还没有评估记录。填写评测问题后点击「开始评估」。</div>
            <div
              v-for="r in runs"
              :key="r.id"
              class="run-item"
              :class="{ active: runDetail && runDetail.run_id === r.id }"
              @click="viewRun(r.id)"
            >
              <div class="run-row">
                <b>{{ r.name }}</b>
                <span class="hint">{{ r.dataset_size }} 题 · {{ fmtTime(r.created_at) }}</span>
              </div>
              <div class="his-meta">
                hit@k {{ fmtVal(r.metrics && r.metrics.hit_rate) }}
                · MRR {{ fmtVal(r.metrics && r.metrics.mrr) }}
                · 忠实度 {{ fmtVal(r.metrics && r.metrics.faithfulness) }}
                · 平均耗时 {{ r.metrics && r.metrics.latency_ms_avg != null ? r.metrics.latency_ms_avg + 'ms' : '—' }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="card eval-result">
        <div class="card-h">
          <h2>{{ runDetail ? runDetail.name + ' · 评估结果' : '评估结果' }}</h2>
          <span v-if="runDetail" class="hint">{{ runDetail.dataset_size }} 题 · {{ fmtTime(runDetail.created_at) }}</span>
        </div>
        <div class="card-b">
          <div v-if="!runDetail" class="empty">运行一次评估后，这里展示六维指标与分布。</div>
          <template v-else>
            <div class="metric-grid">
              <div v-for="[label, key] in METRIC_CARDS" :key="key" class="metric-card">
                <div class="metric-val" :class="{ na: runDetail.metrics[key] == null }">
                  {{ fmtVal(runDetail.metrics[key]) }}{{ key === 'latency_ms_avg' && runDetail.metrics[key] != null ? ' ms' : '' }}
                </div>
                <div class="metric-label">{{ label }}</div>
              </div>
            </div>
            <p class="metric-note">
              忠实度 / 切题度由 LLM 判分，未配置可用模型或判分失败时显示 —；其余为检索层指标，无需 LLM。
            </p>
            <div ref="chartEl" class="eval-chart"></div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.eval-layout { display: grid; grid-template-columns: 400px 1fr; gap: 18px; align-items: start; }
.eval-chart { width: 100%; height: 280px; }

.form-row { display: flex; gap: 12px; margin-bottom: 12px; }
.field { margin-bottom: 12px; }
.field:last-child { margin-bottom: 14px; }

.run-list { padding: 8px; max-height: 340px; overflow-y: auto; }
.run-item { padding: 11px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 2px; transition: background .12s; }
.run-item:hover { background: #f3f6fa; }
.run-item.active { background: var(--accent-weak); }
.run-row { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.his-meta { font-size: 11.5px; color: var(--ink-3); margin-top: 3px; }

.metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; margin-bottom: 14px; }
.metric-card {
  background: #f8fafc; border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 12px; text-align: center;
}
.metric-val { font-size: 24px; font-weight: 700; color: var(--accent); font-family: var(--mono); line-height: 1.2; }
.metric-val.na { color: var(--ink-3); font-weight: 500; }
.metric-label { font-size: 11.5px; color: var(--ink-2); margin-top: 6px; }
.metric-note { font-size: 12px; color: var(--ink-3); margin: 0 0 8px; }

@media (max-width: 960px) {
  .eval-layout { grid-template-columns: 1fr; }
}
</style>
