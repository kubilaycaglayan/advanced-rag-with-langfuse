import express from 'express'
import { join } from 'node:path'
import { dev, uiDist } from './config.js'
import { clientIp } from './security.js'
import { registerQuestions } from './questions.js'
import { registerTraces } from './traces.js'

export function createApp({ fetcher = fetch, production = process.env.NODE_ENV === 'production', clientIpForRequest = clientIp, uiDir = uiDist } = {}) {
  const app = express()
  app.disable('x-powered-by')
  app.use((req, res, next) => {
    if (req.path === '/api' || req.path.startsWith('/api/')) return next()
    res.vary('Origin')
    if (req.headers.origin === 'https://kubilaycaglayan.com') {
      res.set('Access-Control-Allow-Origin', req.headers.origin)
      res.set('Access-Control-Allow-Credentials', 'true')
      res.set('Access-Control-Expose-Headers', 'Retry-After')
      if (req.method === 'OPTIONS') {
        res.set('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        res.set('Access-Control-Allow-Headers', 'Content-Type, Accept')
        return res.sendStatus(204)
      }
    }
    next()
  })
  app.use(express.json({ limit: '8kb' }))

  registerQuestions(app, { fetcher, production, clientIpForRequest })
  registerTraces(app, { fetcher })

  app.use('/api', (_req, res) => res.status(404).json({ error: 'Not found.' }))
  if (dev) return app
  // Built asset names carry a content hash, so they can be cached for good; a missing asset is a 404, not the app.
  app.use('/assets', express.static(join(uiDir, 'assets'), { immutable: true, maxAge: '1y' }), (_req, res) => res.sendStatus(404))
  app.use(express.static(uiDir, { index: false }))
  app.get('/{*path}', (_req, res) => res.set('Cache-Control', 'no-cache').sendFile(join(uiDir, 'index.html')))
  return app
}
