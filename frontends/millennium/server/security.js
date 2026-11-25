import { createHash, randomUUID } from 'node:crypto'
import { isIP } from 'node:net'
import { cookieName } from './config.js'

export function sessionFromCookie(header = '') {
  const value = header.split(';').map(part => part.trim()).find(part => part.startsWith(`${cookieName}=`))?.slice(cookieName.length + 1)
  return value && /^interactive-ui-[0-9a-f-]{36}$/.test(value) ? value : null
}


export function sessionFor(req, res) {
  const existing = sessionFromCookie(req.headers.cookie)
  if (existing) return existing
  const session = `interactive-ui-${randomUUID()}`
  res.cookie(cookieName, session, { httpOnly: true, sameSite: 'lax', secure: req.secure || process.env.COOKIE_SECURE === 'true', maxAge: 365 * 24 * 60 * 60 * 1000, path: '/' })
  return session
}


export function ipSession(ip) {
  if (isIP(ip) !== 6) return `ui-${ip.replace(/[.:]/g, '-')}`
  const [head, tail = ''] = ip.toLowerCase().split('::')
  const left = head ? head.split(':') : []
  const right = ip.includes('::') && tail ? tail.split(':') : []
  const groups = [...left, ...Array(8 - left.length - right.length).fill('0'), ...right]
  return `ui-${groups.slice(0, 4).map(group => group.replace(/^0+(?=.)/, '')).join('-')}`
}


export function authHeader() {
  const publicKey = process.env.LANGFUSE_PUBLIC_KEY
  const secretKey = process.env.LANGFUSE_SECRET_KEY
  if (!publicKey || !secretKey) throw new Error('Langfuse credentials are not configured on the frontend server.')
  return `Basic ${Buffer.from(`${publicKey}:${secretKey}`).toString('base64')}`
}


export function clientIp(req) {
  const address = req.socket.remoteAddress || ''
  const normalized = address.startsWith('::ffff:') ? address.slice(7) : address
  if (process.env.TRUST_CLOUDFLARE_PROXY === 'true' && isLoopbackIp(normalized)) {
    const forwarded = req.headers['cf-connecting-ip']
    if (typeof forwarded === 'string' && isIP(forwarded)) return forwarded
  }
  return isIP(normalized) ? normalized : null
}


export function isLoopbackIp(ip) {
  return ip === '::1' || (isIP(ip) === 4 && ip.startsWith('127.'))
}


export function scoreId(traceId, sessionId) {
  const hex = createHash('sha256').update(`user-helpfulness:${traceId}:${sessionId}`).digest('hex')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`
}
