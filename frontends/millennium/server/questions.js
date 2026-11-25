import { ragUrl } from './config.js'
import { sessionFor, ipSession, isLoopbackIp } from './security.js'
import { jsonResponse, answerPayload, ndjsonEvents, quotaMessage } from './responses.js'

export function registerQuestions(app, { fetcher, production, clientIpForRequest }) {
  const activeAskIps = new Set()
  app.post('/api/ask', async (req, res) => {
    const question = typeof req.body?.question === 'string' ? req.body.question.trim() : ''
    if (!question || question.length > 2000) return res.status(400).json({ error: 'Enter a question of up to 2,000 characters.' })
    const ip = clientIpForRequest(req) || 'unknown'
    const limited = production && !isLoopbackIp(ip)
    if (limited && activeAskIps.has(ip)) {
      return res.status(429).json({ error: 'A question from this IP address is already in progress. Please try again when it finishes.' })
    }
    if (limited) activeAskIps.add(ip)
    try {
      const browserId = sessionFor(req, res)
      // A browser that accepts NDJSON gets the answer as it is written: status and token events, then one done event
      // carrying the same payload a plain request gets. Errors before the stream starts keep their HTTP status.
      const streaming = (req.headers.accept || '').includes('application/x-ndjson')
      const upstream = await fetcher(`${ragUrl}/ask${streaming ? '/stream' : ''}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, pipeline: 'v2.16',
          settings: { agent_provider: 'openai', agent_reasoning_effort: 'high' },
          session_id: ip === 'unknown' ? browserId : ipSession(ip), user_id: browserId,
          source: 'frontend', client_ip: ip === 'unknown' ? null : ip,
          production }),
        signal: AbortSignal.timeout(960_000),
      })
      if (!upstream.ok) {
        const result = await jsonResponse(upstream)
        const retryAfter = upstream.headers.get('retry-after')
        if (upstream.status === 429 && retryAfter) {
          res.set('Retry-After', retryAfter)
          return res.status(429).json({ error: quotaMessage(retryAfter) })
        }
        return res.status(upstream.status >= 500 ? 502 : upstream.status).json({ error: typeof result.detail === 'string' ? result.detail : 'The pipeline could not answer this question.' })
      }
      if (!streaming) return res.json(answerPayload(await jsonResponse(upstream)))
      res.set({ 'Content-Type': 'application/x-ndjson; charset=utf-8', 'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no' })
      res.flushHeaders()
      for await (const event of ndjsonEvents(upstream.body)) {
        if (event.type === 'token' || event.type === 'status') res.write(JSON.stringify(event) + '\n')
        else if (event.type === 'done') res.write(JSON.stringify({ type: 'done', ...answerPayload(event.result || {}) }) + '\n')
        else if (event.type === 'error') res.write(JSON.stringify({ type: 'error', error: 'The pipeline could not answer this question.' }) + '\n')
      }
      res.end()
    } catch (error) {
      const message = error?.name === 'TimeoutError' ? 'The answer took too long. Please try again.' : 'The answer service is unavailable.'
      if (res.headersSent) res.end(JSON.stringify({ type: 'error', error: message }) + '\n')
      else res.status(502).json({ error: message })
    } finally {
      if (limited) activeAskIps.delete(ip)
    }
  })

}
