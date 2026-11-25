import { langfuseUiUrl, projectId } from './config.js'

export async function jsonResponse(response) {
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


export function answerPayload(result) {
  const traceId = typeof result.trace_id === 'string' ? result.trace_id : null
  return { answer: result.answer, sources: citedSources(result), traceId,
    traceUrl: traceId ? `${langfuseUiUrl}/project/${encodeURIComponent(projectId)}/traces/${encodeURIComponent(traceId)}` : null,
    pipelineId: result.pipeline_id || null, pipelineSeconds: result.latency_seconds ?? null }
}


export async function* ndjsonEvents(body) {
  const decoder = new TextDecoder()
  let buffered = ''
  for await (const chunk of body) {
    buffered += decoder.decode(chunk, { stream: true })
    const lines = buffered.split('\n')
    buffered = lines.pop()
    for (const line of lines) if (line.trim()) yield JSON.parse(line)
  }
  if (buffered.trim()) yield JSON.parse(buffered)
}


export function quotaMessage(retryAfter) {
  const seconds = Number(retryAfter)
  if (!Number.isFinite(seconds) || seconds <= 0) return "You've reached the question limit. Please try again later."
  const [count, unit] = seconds < 60 ? [Math.ceil(seconds), 'second']
    : seconds < 3600 ? [Math.ceil(seconds / 60), 'minute']
      : seconds < 86400 ? [Math.ceil(seconds / 3600), 'hour']
        : [Math.ceil(seconds / 86400), 'day']
  return `You've reached the question limit. Please try again in about ${count} ${unit}${count === 1 ? '' : 's'}.`
}
