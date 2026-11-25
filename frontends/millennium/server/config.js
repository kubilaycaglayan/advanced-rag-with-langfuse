import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

export const root = dirname(dirname(fileURLToPath(import.meta.url)))
export const dev = process.argv.includes('--dev')
export const port = Number(process.env.FRONTEND_PORT || 43179)
export const host = process.env.FRONTEND_HOST || '127.0.0.1'
export const ragUrl = (process.env.RAG_API_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
export const langfuseUrl = (process.env.LANGFUSE_BASE_URL || 'http://127.0.0.1:28420').replace(/\/$/, '')
export const langfuseUiUrl = (process.env.LANGFUSE_UI_URL || langfuseUrl).replace(/\/$/, '')
export const projectId = process.env.LANGFUSE_PROJECT_ID || 'millenium'
// The UI is the dragon-tattoo-oracle submodule in ./ui, built as a static app (see the Dockerfile).
export const uiDist = join(root, 'ui', 'dist', 'client')
export const uiDevPort = Number(process.env.UI_DEV_PORT || 43180)
export const cookieName = 'millennium_session'
export const environment = 'interactive-ui'
