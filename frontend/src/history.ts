export interface Source {
  label: string
  book: string
  chapter: string | null
  page: string | number | null
  paragraph: number | null
  text: string
}

export interface AnswerRecord {
  id: string
  question: string
  answer: string
  sources: Source[]
  traceId: string | null
  traceUrl: string | null
  pipelineId: string | null
  durationSeconds: number
  askedAt: string
  feedback: boolean | null
}

const KEY = 'millennium-corpus-history-v1'
const LIMIT = 50

export function readHistory(): AnswerRecord[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is AnswerRecord =>
      !!item && typeof item.id === 'string' && typeof item.question === 'string' &&
      typeof item.answer === 'string' && Array.isArray(item.sources)).slice(0, LIMIT)
  } catch {
    return []
  }
}

export function writeHistory(records: AnswerRecord[]): void {
  try { localStorage.setItem(KEY, JSON.stringify(records.slice(0, LIMIT))) } catch { /* Browser storage may be unavailable. */ }
}

export function clearHistory(): void {
  try { localStorage.removeItem(KEY) } catch { /* Browser storage may be unavailable. */ }
}
