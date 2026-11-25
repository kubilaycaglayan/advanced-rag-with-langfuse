import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'
import { createApp } from './server/application.js'
import { startUiDevServer } from './server/development.js'
import { dev, port, host, uiDevPort } from './server/config.js'

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  createApp().listen(port, host, () => {
    console.log(`Millennium frontend listening on http://${host}:${port}`)
    if (dev) {
      console.log(`Open the UI at http://${host}:${uiDevPort}`)
      startUiDevServer()
    }
  })
}
