import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createApp, citedSources, clientIp, ipSession, quotaMessage } from '../server.js'

let server
let base
const calls = []
const sessionId = 'interactive-ui-12345678-1234-4123-8123-123456789abc'
const traceId = 'a'.repeat(32)

before(async () => {
  const app = createApp({ fetcher: async (url, options) => {
    calls.push({ url, options })
    if (url.endsWith('/ask')) return new Response(JSON.stringify({ answer: 'Answer [E2]', citations: ['[E2]'],
      reranked: [{ book: 'One', text: 'first' }, { book: 'Two', chapter: 'Chapter 2', paragraph: 8, text: 'second' }],
      trace_id: traceId, pipeline_id: 'pipeline-123', latency_seconds: 3.4 }), { status: 200 })
    if (url.includes('/v2/observations?')) return new Response(JSON.stringify({ data: [{ isRootObservation: true, name: 'rag ask', sessionId: 'ui-127-0-0-1', userId: sessionId, environment: 'interactive-ui' }] }), { status: 200 })
    if (url.endsWith('/scores')) return new Response(JSON.stringify({ id: 'score-1' }), { status: 200 })
    return new Response('{}', { status: 404 })
  } })
  await new Promise(resolve => { server = app.listen(0, resolve) })
  base = `http://127.0.0.1:${server.address().port}`
})
after(() => server?.close())

test('maps only cited passages, keeping citation order', () => {
  assert.deepEqual(citedSources({ citations: ['[E2]'], reranked: [{ text: 'first' }, { book: 'Two', text: 'second' }] }),
    [{ label: '[E2]', book: 'Two', chapter: null, page: null, paragraph: null, text: 'second' }])
})

test('normalizes the connection IP without trusting forwarding headers', () => {
  assert.equal(clientIp({ socket: { remoteAddress: '::ffff:192.0.2.12' }, headers: { 'x-forwarded-for': '198.51.100.9' } }), '192.0.2.12')
  assert.equal(clientIp({ socket: { remoteAddress: '2001:db8::1' } }), '2001:db8::1')
  assert.equal(clientIp({ socket: { remoteAddress: 'not-an-ip' } }), null)
})

test('trusts Cloudflare client IP only on an enabled local proxy connection', () => {
  const prior = process.env.TRUST_CLOUDFLARE_PROXY
  process.env.TRUST_CLOUDFLARE_PROXY = 'true'
  try {
    assert.equal(clientIp({ socket: { remoteAddress: '127.0.0.1' }, headers: { 'cf-connecting-ip': '198.51.100.9' } }), '198.51.100.9')
    assert.equal(clientIp({ socket: { remoteAddress: '::ffff:127.0.0.1' }, headers: { 'cf-connecting-ip': '2001:db8::1' } }), '2001:db8::1')
    assert.equal(clientIp({ socket: { remoteAddress: '192.0.2.12' }, headers: { 'cf-connecting-ip': '198.51.100.9' } }), '192.0.2.12')
    assert.equal(clientIp({ socket: { remoteAddress: '127.0.0.1' }, headers: { 'cf-connecting-ip': 'invalid' } }), '127.0.0.1')
  } finally {
    if (prior === undefined) delete process.env.TRUST_CLOUDFLARE_PROXY
    else process.env.TRUST_CLOUDFLARE_PROXY = prior
  }
})

test('explains quota wait times in plain language', () => {
  assert.equal(quotaMessage('45'), "You've reached the question limit. Please try again in about 45 seconds.")
  assert.equal(quotaMessage('60'), "You've reached the question limit. Please try again in about 1 minute.")
  assert.equal(quotaMessage('3600'), "You've reached the question limit. Please try again in about 1 hour.")
  assert.equal(quotaMessage('81000'), "You've reached the question limit. Please try again in about 23 hours.")
  assert.equal(quotaMessage('invalid'), "You've reached the question limit. Please try again later.")
})

test('names the session after the client IP', () => {
  assert.equal(ipSession('78.163.48.13'), 'ui-78-163-48-13')
  assert.equal(ipSession('2a00:1d34:cf1e:9701:9471:f827:b074:bc40'), 'ui-2a00-1d34-cf1e-9701')
  assert.equal(ipSession('2a00:1d34:cf1e:9701:9ec7:d3ff:fee3:4bf8'), 'ui-2a00-1d34-cf1e-9701')
  assert.equal(ipSession('2A00:1D34:0:0::1'), 'ui-2a00-1d34-0-0')
  assert.equal(ipSession('2001:db8::1'), 'ui-2001-db8-0-0')
  assert.equal(ipSession('::1'), 'ui-0-0-0-0')
})

test('groups questions by IP and passes the stable browser ID as the user', async () => {
  const first = await fetch(`${base}/api/ask`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Forwarded-For': '198.51.100.9' }, body: JSON.stringify({ question: 'Who is Salander?' }) })
  assert.equal(first.status, 200)
  const cookie = first.headers.get('set-cookie')
  assert.match(cookie, /HttpOnly/i)
  assert.match(cookie, /SameSite=Lax/i)
  const body = await first.json()
  assert.equal(body.pipelineId, 'pipeline-123')
  assert.equal(body.traceId, traceId)
  assert.equal(body.sources.length, 1)
  const second = await fetch(`${base}/api/ask`, { method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie }, body: JSON.stringify({ question: 'And Mikael?' }) })
  assert.equal(second.status, 200)
  const sent = calls.filter(call => call.url.endsWith('/ask')).map(call => JSON.parse(call.options.body))
  assert.equal(sent[0].session_id, 'ui-127-0-0-1')
  assert.equal(sent[1].session_id, 'ui-127-0-0-1')
  assert.match(sent[0].user_id, /^interactive-ui-[0-9a-f-]{36}$/)
  assert.equal(sent[0].user_id, sent[1].user_id)
  assert.equal(sent[0].source, 'frontend')
  assert.equal(sent[0].client_ip, '127.0.0.1')
})

test('streams answer tokens and ends with the same payload a plain request gets', async () => {
  const events = [{ type: 'trace', trace_id: traceId }, { type: 'status', status: 'answering' }, { type: 'token', text: 'Answer ' },
    { type: 'token', text: '[E2]' }, { type: 'done', result: { answer: 'Answer [E2]', citations: ['[E2]'],
      reranked: [{ book: 'One', text: 'first' }, { book: 'Two', text: 'second' }], trace_id: traceId, pipeline_id: 'pipeline-123', latency_seconds: 3.4 } }]
  const text = events.map(event => JSON.stringify(event) + '\n').join('')
  const seen = []
  // Split mid-line, as a network chunk may be.
  const app = createApp({ fetcher: async url => {
    seen.push(url)
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode(text.slice(0, 50)))
      controller.enqueue(new TextEncoder().encode(text.slice(50)))
      controller.close()
    } }), { status: 200 })
  } })
  const streamServer = app.listen(0)
  await new Promise(resolve => streamServer.once('listening', resolve))
  try {
    const response = await fetch(`http://127.0.0.1:${streamServer.address().port}/api/ask`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' }, body: JSON.stringify({ question: 'Who?' }),
    })
    assert.equal(response.status, 200)
    assert.match(response.headers.get('content-type'), /application\/x-ndjson/)
    const received = (await response.text()).trim().split('\n').map(line => JSON.parse(line))
    assert.ok(seen[0].endsWith('/ask/stream'))
    assert.deepEqual(received.slice(0, 3), [{ type: 'status', status: 'answering' }, { type: 'token', text: 'Answer ' }, { type: 'token', text: '[E2]' }])
    const done = received[3]
    assert.equal(done.type, 'done')
    assert.equal(done.answer, 'Answer [E2]')
    assert.equal(done.traceId, traceId)
    assert.equal(done.pipelineId, 'pipeline-123')
    assert.deepEqual(done.sources.map(source => source.label), ['[E2]'])
  } finally {
    streamServer.close()
  }
})

test('production allows one active question per IP and releases the slot after completion or failure', async () => {
  let releaseFirst
  let signalStarted
  const firstStarted = new Promise(resolve => { signalStarted = resolve })
  let upstreamCalls = 0
  const app = createApp({ production: true, clientIpForRequest: () => '198.51.100.9', fetcher: async () => {
    upstreamCalls++
    if (upstreamCalls === 1) {
      signalStarted()
      return new Promise(resolve => { releaseFirst = resolve })
    }
    if (upstreamCalls === 2) throw new Error('upstream unavailable')
    return new Response(JSON.stringify({ answer: 'Ready' }), { status: 200 })
  } })
  const limitedServer = app.listen(0)
  await new Promise(resolve => limitedServer.once('listening', resolve))
  const url = `http://127.0.0.1:${limitedServer.address().port}/api/ask`
  const ask = () => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: 'Who?' }) })
  try {
    const first = ask()
    await firstStarted
    const blocked = await ask()
    assert.equal(blocked.status, 429)
    assert.match((await blocked.json()).error, /already in progress/)
    assert.equal(upstreamCalls, 1)
    releaseFirst(new Response(JSON.stringify({ answer: 'First' }), { status: 200 }))
    assert.equal((await first).status, 200)
    assert.equal((await ask()).status, 502)
    assert.equal((await ask()).status, 200)
    assert.equal(upstreamCalls, 3)
  } finally {
    releaseFirst?.(new Response('{}', { status: 200 }))
    limitedServer.close()
  }
})

test('production allows concurrent localhost questions', async () => {
  let releaseFirst
  let signalStarted
  const firstStarted = new Promise(resolve => { signalStarted = resolve })
  let upstreamCalls = 0
  const app = createApp({ production: true, fetcher: async () => {
    upstreamCalls++
    if (upstreamCalls === 1) {
      signalStarted()
      return new Promise(resolve => { releaseFirst = resolve })
    }
    return new Response(JSON.stringify({ answer: 'Second' }), { status: 200 })
  } })
  const localServer = app.listen(0)
  await new Promise(resolve => localServer.once('listening', resolve))
  const url = `http://127.0.0.1:${localServer.address().port}/api/ask`
  const ask = () => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: 'Who?' }) })
  try {
    const first = ask()
    await firstStarted
    assert.equal((await ask()).status, 200)
    assert.equal(upstreamCalls, 2)
    releaseFirst(new Response(JSON.stringify({ answer: 'First' }), { status: 200 }))
    assert.equal((await first).status, 200)
  } finally {
    releaseFirst?.(new Response('{}', { status: 200 }))
    localServer.close()
  }
})

test('forwards the upstream quota response and Retry-After header', async () => {
  const app = createApp({ fetcher: async () => new Response(JSON.stringify({ detail: 'Question limit reached.' }), {
    status: 429, headers: { 'Retry-After': '60' },
  }) })
  const quotaServer = app.listen(0)
  await new Promise(resolve => quotaServer.once('listening', resolve))
  try {
    const response = await fetch(`http://127.0.0.1:${quotaServer.address().port}/api/ask`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: 'Who?' }),
    })
    assert.equal(response.status, 429)
    assert.equal(response.headers.get('retry-after'), '60')
    assert.equal((await response.json()).error, "You've reached the question limit. Please try again in about 1 minute.")
  } finally {
    quotaServer.close()
  }
})

test('rejects invalid feedback before contacting Langfuse', async () => {
  const beforeCount = calls.length
  const response = await fetch(`${base}/api/feedback`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ traceId, helpful: true }) })
  assert.equal(response.status, 400)
  assert.equal(calls.length, beforeCount)
})

test('links helpfulness feedback to an owned trace in the UI environment', async () => {
  process.env.LANGFUSE_PUBLIC_KEY = 'test-public'
  process.env.LANGFUSE_SECRET_KEY = 'test-secret'
  try {
    const response = await fetch(`${base}/api/feedback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: `millennium_session=${sessionId}` },
      body: JSON.stringify({ traceId, helpful: false }),
    })
    assert.equal(response.status, 200)
    const sent = JSON.parse(calls.findLast(call => call.url.endsWith('/scores')).options.body)
    assert.equal(sent.traceId, traceId)
    assert.equal(sent.value, 0)
    assert.equal(sent.dataType, 'BOOLEAN')
    assert.equal(sent.environment, 'interactive-ui')
  } finally {
    delete process.env.LANGFUSE_PUBLIC_KEY
    delete process.env.LANGFUSE_SECRET_KEY
  }
})

test('shows trace steps only to the browser session that created the trace', async () => {
  process.env.LANGFUSE_PUBLIC_KEY = 'test-public'
  process.env.LANGFUSE_SECRET_KEY = 'test-secret'
  try {
    const own = await fetch(`${base}/api/trace/${traceId}`, {
      headers: { Cookie: `millennium_session=${sessionId}` },
    })
    assert.equal(own.status, 200)
    const body = await own.json()
    assert.equal(body.traceId, traceId)
    assert.equal(body.observations[0].name, 'rag ask')
    assert.equal(body.observations[0].sessionId, undefined)

    const other = await fetch(`${base}/api/trace/${traceId}`, {
      headers: { Cookie: 'millennium_session=interactive-ui-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' },
    })
    assert.equal(other.status, 403)
  } finally {
    delete process.env.LANGFUSE_PUBLIC_KEY
    delete process.env.LANGFUSE_SECRET_KEY
  }
})

test('serves the built UI, falls back to it for app paths, and keeps API and asset misses as 404s', async () => {
  const uiDir = mkdtempSync(join(tmpdir(), 'millennium-ui-'))
  mkdirSync(join(uiDir, 'assets'))
  writeFileSync(join(uiDir, 'index.html'), '<!doctype html><title>Millennium Project</title>')
  writeFileSync(join(uiDir, 'assets', 'app-abc123.js'), 'console.log(1)')
  const uiServer = createApp({ uiDir }).listen(0)
  await new Promise(resolve => uiServer.once('listening', resolve))
  const url = path => `http://127.0.0.1:${uiServer.address().port}${path}`
  try {
    for (const path of ['/', '/some/client/route']) {
      const page = await fetch(url(path))
      assert.equal(page.status, 200)
      assert.match(await page.text(), /Millennium Project/)
      assert.equal(page.headers.get('cache-control'), 'no-cache')
    }
    const asset = await fetch(url('/assets/app-abc123.js'))
    assert.equal(asset.status, 200)
    assert.match(asset.headers.get('cache-control'), /immutable/)
    assert.equal((await fetch(url('/assets/missing.js'))).status, 404)
    const api = await fetch(url('/api/unknown'))
    assert.equal(api.status, 404)
    assert.deepEqual(await api.json(), { error: 'Not found.' })
  } finally {
    uiServer.close()
    rmSync(uiDir, { recursive: true, force: true })
  }
})
