<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { clearHistory, readHistory, writeHistory, type AnswerRecord } from './history'

interface TraceObservation {
  id: string
  name: string
  type: string
  level: string
  startTime: string
  latency: number | null
  statusMessage: string | null
  parentObservationId: string | null
}

const history = ref<AnswerRecord[]>(readHistory())
const selectedId = ref<string | null>(history.value[0]?.id || null)
const selected = computed(() => history.value.find(item => item.id === selectedId.value) || null)
const traceOpen = ref(false)
const tracePending = ref(false)
const traceError = ref('')
const traceObservations = ref<TraceObservation[]>([])
const traceCloseButton = ref<HTMLButtonElement | null>(null)
const contentElement = ref<HTMLElement | null>(null)
const question = ref('')
const pending = ref(false)
const feedbackPending = ref(false)
const error = ref('')
const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | undefined

watch(selectedId, async () => {
  await nextTick()
  contentElement.value?.scrollTo({ top: 0 })
})

function formatDuration(seconds: number): string {
  return `${seconds.toFixed(1)}s`
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

async function ask(): Promise<void> {
  const text = question.value.trim()
  if (!text || pending.value) return
  pending.value = true
  error.value = ''
  elapsed.value = 0
  const started = performance.now()
  timer = setInterval(() => { elapsed.value = (performance.now() - started) / 1000 }, 100)
  try {
    const response = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: text }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.error || 'The question could not be answered.')
    const record: AnswerRecord = {
      id: crypto.randomUUID(), question: text, answer: payload.answer,
      sources: payload.sources || [], traceId: payload.traceId || null,
      traceUrl: payload.traceUrl || null, pipelineId: payload.pipelineId || null,
      durationSeconds: (performance.now() - started) / 1000,
      askedAt: new Date().toISOString(), feedback: null,
    }
    history.value = [record, ...history.value].slice(0, 50)
    writeHistory(history.value)
    selectedId.value = record.id
    question.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'The question could not be answered.'
  } finally {
    if (timer) clearInterval(timer)
    timer = undefined
    pending.value = false
  }
}

async function rate(helpful: boolean): Promise<void> {
  const record = selected.value
  if (!record?.traceId || feedbackPending.value) return
  feedbackPending.value = true
  error.value = ''
  try {
    const response = await fetch('/api/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ traceId: record.traceId, helpful }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.error || 'Feedback could not be saved.')
    record.feedback = helpful
    writeHistory(history.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Feedback could not be saved.'
  } finally {
    feedbackPending.value = false
  }
}

function removeHistory(): void {
  history.value = []
  selectedId.value = null
  clearHistory()
}

async function viewTrace(): Promise<void> {
  const traceId = selected.value?.traceId
  if (!traceId) return
  traceOpen.value = true
  tracePending.value = true
  traceError.value = ''
  traceObservations.value = []
  await nextTick()
  traceCloseButton.value?.focus()
  try {
    const response = await fetch(`/api/trace/${encodeURIComponent(traceId)}`)
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.error || 'Trace details are unavailable.')
    traceObservations.value = payload.observations || []
  } catch (cause) {
    traceError.value = cause instanceof Error ? cause.message : 'Trace details are unavailable.'
  } finally {
    tracePending.value = false
  }
}

async function closeTrace(): Promise<void> {
  traceOpen.value = false
  await nextTick()
  document.querySelector<HTMLButtonElement>('.trace-button')?.focus()
}

onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div class="shell">
    <aside class="sidebar" aria-label="Question history">
      <div class="brand"><span class="brand-mark">M</span><div><strong>MILLENNIUM</strong><small>CORPUS EXPLORER</small></div></div>
      <button class="new-question" type="button" aria-label="New question" @click="selectedId = null; question = ''; error = ''"><span aria-hidden="true">+</span><span class="new-question-label">New question</span></button>
      <div class="sidebar-scroll">
        <div class="history-heading"><span>YOUR QUESTIONS</span><button v-if="history.length" type="button" @click="removeHistory">Clear</button></div>
        <p v-if="!history.length" class="empty-history">Your answers will appear here.</p>
        <button v-for="item in history" :key="item.id" class="history-item" :class="{ active: selectedId === item.id }" type="button" :title="item.question" @click="selectedId = item.id; error = ''">
          <span>{{ item.question }}</span><small>{{ formatDate(item.askedAt) }}</small>
        </button>
      </div>
      <div class="sidebar-foot">Answers are saved in this browser.</div>
    </aside>

    <main class="main">
      <header class="topbar"><span>THE MILLENNIUM BOOKS</span><span class="status"><i></i> Corpus Q&amp;A</span></header>
      <div ref="contentElement" class="content" aria-label="Answer content">
        <div v-if="!selected" class="welcome">
          <div class="eyebrow">ASK THE CORPUS</div>
          <h1>Find the story<br><em>behind the answer.</em></h1>
          <p>Ask a question about the Millennium books. Each answer draws on passages from the corpus and shows where its evidence came from.</p>
        </div>

        <article v-else class="answer-view">
          <div class="eyebrow">QUESTION · {{ formatDate(selected.askedAt) }}</div>
          <h1>{{ selected.question }}</h1>
          <div class="answer-card">
            <div class="answer-card-label"><span class="answer-icon">✦</span> ANSWER</div>
            <p class="answer-text">{{ selected.answer }}</p>
            <div class="answer-meta"><span>Thinking duration <strong>{{ formatDuration(selected.durationSeconds) }}</strong></span><span v-if="selected.pipelineId">Setup <code>{{ selected.pipelineId }}</code></span></div>
          </div>
          <div class="answer-actions">
            <div class="feedback"><span>Was this helpful?</span><button type="button" :disabled="!selected.traceId || feedbackPending" :aria-pressed="selected.feedback === true" @click="rate(true)">👍 Yes</button><button type="button" :disabled="!selected.traceId || feedbackPending" :aria-pressed="selected.feedback === false" @click="rate(false)">👎 No</button></div>
            <button v-if="selected.traceId" type="button" class="trace-button" @click="viewTrace">View trace ↗</button>
          </div>
          <section v-if="selected.sources.length" class="sources"><div class="sources-heading"><h2>Cited passages</h2><span>{{ selected.sources.length }} source{{ selected.sources.length === 1 ? '' : 's' }}</span></div>
            <div v-for="source in selected.sources" :key="source.label" class="source-card"><div class="source-top"><strong>{{ source.label }} · {{ source.book }}</strong><span>{{ source.chapter || 'Chapter unavailable' }}</span></div><p>{{ source.text }}</p><small>Paragraph {{ source.paragraph ?? '—' }}<template v-if="source.page"> · Page {{ source.page }}</template></small></div>
          </section>
        </article>

      </div>
      <div class="ask-area"><div class="ask-inner"><form @submit.prevent="ask"><label for="question">YOUR QUESTION</label><div class="input-row"><textarea id="question" v-model="question" maxlength="2000" rows="2" :disabled="pending" placeholder="What would you like to know about the books?" @keydown.ctrl.enter.prevent="ask" @keydown.meta.enter.prevent="ask"></textarea><button type="submit" :disabled="pending || !question.trim()">{{ pending ? 'Working…' : 'Ask →' }}</button></div><div class="form-foot"><span v-if="pending" role="status">Searching the corpus · {{ formatDuration(elapsed) }}</span><span v-else>Grounded in source passages</span><span>Ctrl/⌘ + Enter to ask</span></div></form><p v-if="error" class="error" role="alert">{{ error }}</p></div></div>
    </main>
    <div v-if="traceOpen" class="trace-backdrop" @click.self="closeTrace" @keydown.esc.window="closeTrace">
      <section class="trace-panel" role="dialog" aria-modal="true" aria-labelledby="trace-title">
        <header class="trace-header"><div><div class="eyebrow">LANGFUSE TRACE</div><h2 id="trace-title">Question trace</h2><code>{{ selected?.traceId }}</code></div><button ref="traceCloseButton" type="button" aria-label="Close trace" @click="closeTrace">×</button></header>
        <div class="trace-body">
          <p v-if="tracePending" role="status">Loading trace…</p>
          <div v-else-if="traceError" class="error" role="alert">{{ traceError }} <button type="button" @click="viewTrace">Retry</button></div>
          <p v-else-if="!traceObservations.length">No trace steps were found.</p>
          <ol v-else class="trace-list"><li v-for="step in traceObservations" :key="step.id"><div><strong>{{ step.name || step.type }}</strong><span>{{ step.type }}<template v-if="step.latency != null"> · {{ formatDuration(step.latency) }}</template></span></div><small v-if="step.statusMessage">{{ step.statusMessage }}</small></li></ol>
        </div>
      </section>
    </div>
  </div>
</template>
