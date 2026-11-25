import { langfuseUrl, ragUrl, environment } from './config.js'
import { sessionFromCookie, authHeader, scoreId } from './security.js'
import { jsonResponse } from './responses.js'

export function registerTraces(app, { fetcher }) {
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
        if (root?.userId === sessionId && root.environment === environment) break
        if (attempt < 5) await new Promise(resolve => setTimeout(resolve, 1000))
      }
      if (!root) return res.status(409).json({ error: 'The trace is still being recorded. Please retry in a moment.' })
      if (root.userId !== sessionId || root.environment !== environment) return res.status(403).json({ error: 'That trace does not belong to this browser session.' })
      const scoreResponse = await fetcher(`${langfuseUrl}/api/public/scores`, {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: scoreId(traceId, sessionId), traceId, name: 'user_helpfulness',
          value: req.body.helpful ? 1 : 0, dataType: 'BOOLEAN', environment }),
        signal: AbortSignal.timeout(15_000),
      })
      if (!scoreResponse.ok) throw new Error(`Score submission failed: ${scoreResponse.status}`)
      const cacheResponse = await fetcher(`${ragUrl}/cache/feedback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trace_id: traceId, owner_id: sessionId, helpful: req.body.helpful }),
        signal: AbortSignal.timeout(15_000),
      })
      if (!cacheResponse.ok) throw new Error(`Answer cache feedback update failed: ${cacheResponse.status}`)
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
      if (root.userId !== sessionId || root.environment !== environment) {
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

}
