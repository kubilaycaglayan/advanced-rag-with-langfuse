import express from 'express'
import { createHash, randomUUID } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'

const root = dirname(fileURLToPath(import.meta.url))
const dev = process.argv.includes('--dev')
const port = Number(process.env.FRONTEND_PORT || 43179)
const ragUrl = (process.env.RAG_API_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
const langfuseUrl = (process.env.LANGFUSE_BASE_URL || 'http://127.0.0.1:28420').replace(/\/$/, '')
const langfuseUiUrl = (process.env.LANGFUSE_UI_URL || langfuseUrl).replace(/\/$/, '')
const projectId = process.env.LANGFUSE_PROJECT_ID || 'millenium'
const cookieName = 'millennium_session'
const environment = 'interactive-ui'

export function sessionFromCookie(header = '') {
  const value = header.split(';').map(part => part.trim()).find(part => part.startsWith(`${cookieName}=`))?.slice(cookieName.length + 1)
  return value && /^interactive-ui-[0-9a-f-]{36}$/.test(value) ? value : null
}

function sessionFor(req, res) {
  const existing = sessionFromCookie(req.headers.cookie)
  if (existing) return existing
  const session = `interactive-ui-${randomUUID()}`
  res.cookie(cookieName, session, { httpOnly: true, sameSite: 'lax', secure: req.secure || process.env.COOKIE_SECURE === 'true', maxAge: 365 * 24 * 60 * 60 * 1000, path: '/' })
  return session
}

function authHeader() {
  const publicKey = process.env.LANGFUSE_PUBLIC_KEY
  const secretKey = process.env.LANGFUSE_SECRET_KEY
  if (!publicKey || !secretKey) throw new Error('Langfuse credentials are not configured on the frontend server.')
  return `Basic ${Buffer.from(`${publicKey}:${secretKey}`).toString('base64')}`
}

async function jsonResponse(response) {
  const raw = await response.text()
  try { return JSON.parse(raw) } catch { return {} }
}

export function citedSources(result) {
  const cited = new Set(Array.isArray(result.citations) ? result.citations : [])
  return (Array.isArray(result.reranked) ? result.reranked : []).flatMap((row, index) => {
    const label = `[E${index + 1}]`
    if (!cited.has(label)) return []
    return [{ label, book: String(row.book || 'Unknown book'), chapter: row.chapter || null,
      page: row.page || null, paragraph: row.paragraph ?? null, text: String(row.text || '') }]
  })
}

function scoreId(traceId, sessionId) {
  const hex = createHash('sha256').update(`user-helpfulness:${traceId}:${sessionId}`).digest('hex')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`
}

export function createApp({ fetcher = fetch } = {}) {
  const app = express()
  app.disable('x-powered-by')
  app.use(express.json({ limit: '8kb' }))

  app.post('/api/ask', async (req, res) => {
    const question = typeof req.body?.question === 'string' ? req.body.question.trim() : ''
    if (!question || question.length > 2000) return res.status(400).json({ error: 'Enter a question of up to 2,000 characters.' })
    const sessionId = sessionFor(req, res)
    try {
      const upstream = await fetcher(`${ragUrl}/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, session_id: sessionId, source: 'frontend' }),
        signal: AbortSignal.timeout(960_000),
      })
      const result = await jsonResponse(upstream)
      if (!upstream.ok) return res.status(upstream.status >= 500 ? 502 : upstream.status).json({ error: typeof result.detail === 'string' ? result.detail : 'The pipeline could not answer this question.' })
      const traceId = typeof result.trace_id === 'string' ? result.trace_id : null
      res.json({ answer: result.answer, sources: citedSources(result), traceId,
        traceUrl: traceId ? `${langfuseUiUrl}/project/${encodeURIComponent(projectId)}/traces/${encodeURIComponent(traceId)}` : null,
        pipelineId: result.pipeline_id || null, pipelineSeconds: result.latency_seconds ?? null })
    } catch (error) {
      res.status(502).json({ error: error?.name === 'TimeoutError' ? 'The answer took too long. Please try again.' : 'The answer service is unavailable.' })
    }
  })

  app.post('/api/feedback', async (req, res) => {
    const sessionId = sessionFromCookie(req.headers.cookie)
    const traceId = req.body?.traceId
    if (!sessionId || typeof traceId !== 'string' || !/^[0-9a-f]{32}$/i.test(traceId) || typeof req.body?.helpful !== 'boolean') {
      return res.status(400).json({ error: 'Invalid feedback request.' })
    }
    try {
      const headers = { Authorization: authHeader() }
      let root
      for (let attempt = 0; attempt < 6; attempt++) {
        const traceResponse = await fetcher(`${langfuseUrl}/api/public/v2/observations?traceId=${encodeURIComponent(traceId)}&limit=100`, { headers, signal: AbortSignal.timeout(15_000) })
        if (!traceResponse.ok) throw new Error(`Trace lookup failed: ${traceResponse.status}`)
        const observations = (await jsonResponse(traceResponse)).data || []
        root = observations.find(item => item.isRootObservation && item.name === 'rag ask')
        if (root?.sessionId === sessionId && root.environment === environment) break
        if (attempt < 5) await new Promise(resolve => setTimeout(resolve, 1000))
      }
      if (!root) return res.status(409).json({ error: 'The trace is still being recorded. Please retry in a moment.' })
      if (root.sessionId !== sessionId || root.environment !== environment) return res.status(403).json({ error: 'That trace does not belong to this browser session.' })
      const scoreResponse = await fetcher(`${langfuseUrl}/api/public/scores`, {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: scoreId(traceId, sessionId), traceId, name: 'user_helpfulness',
          value: req.body.helpful ? 1 : 0, dataType: 'BOOLEAN', environment }),
        signal: AbortSignal.timeout(15_000),
      })
      if (!scoreResponse.ok) throw new Error(`Score submission failed: ${scoreResponse.status}`)
      res.json({ saved: true })
    } catch {
      res.status(502).json({ error: 'Feedback could not be saved to Langfuse. Please try again.' })
    }
  })

  app.get('/api/trace/:traceId', async (req, res) => {
    const sessionId = sessionFromCookie(req.headers.cookie)
    const { traceId } = req.params
    if (!sessionId || !/^[0-9a-f]{32}$/i.test(traceId)) return res.status(400).json({ error: 'Invalid trace request.' })
    try {
      const observations = []
      let cursor
      for (let page = 0; page < 10; page++) {
        const url = new URL(`${langfuseUrl}/api/public/v2/observations`)
        url.searchParams.set('traceId', traceId)
        url.searchParams.set('limit', '100')
        if (cursor) url.searchParams.set('cursor', cursor)
        const response = await fetcher(url.href, {
          headers: { Authorization: authHeader() }, signal: AbortSignal.timeout(15_000),
        })
        if (!response.ok) throw new Error(`Trace lookup failed: ${response.status}`)
        const result = await jsonResponse(response)
        observations.push(...(Array.isArray(result.data) ? result.data : []))
        cursor = result.meta?.cursor
        if (!cursor) break
      }
      const root = observations.find(item => item.isRootObservation && item.name === 'rag ask')
      if (!root) return res.status(409).json({ error: 'The trace is still being recorded. Please retry in a moment.' })
      if (root.sessionId !== sessionId || root.environment !== environment) {
        return res.status(403).json({ error: 'That trace does not belong to this browser session.' })
      }
      res.json({ traceId, observations: observations.map(item => ({
        id: item.id, name: item.name, type: item.type, level: item.level,
        startTime: item.startTime, latency: item.latency, statusMessage: item.statusMessage,
        parentObservationId: item.parentObservationId,
      })).sort((a, b) => String(a.startTime).localeCompare(String(b.startTime))) })
    } catch {
      res.status(502).json({ error: 'Trace details are unavailable. Please try again.' })
    }
  })

  if (dev) {
    return import('vite').then(async ({ createServer }) => {
      const vite = await createServer({ root, server: { middlewareMode: true }, appType: 'spa' })
      app.use(vite.middlewares)
      return app
    })
  }
  app.use(express.static(join(root, 'dist')))
  app.get('/{*path}', (_req, res) => res.sendFile(join(root, 'dist', 'index.html')))
  return app
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  Promise.resolve(createApp()).then(app => app.listen(port, () => console.log(`Millennium frontend listening on http://127.0.0.1:${port}`)))
}
