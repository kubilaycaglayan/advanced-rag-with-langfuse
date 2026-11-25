import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { root, host, port, uiDevPort } from './config.js'

export function startUiDevServer() {
  const ui = spawn('npm', ['run', 'dev', '--', '--host', host, '--port', String(uiDevPort), '--strictPort'], {
    cwd: join(root, 'ui'), stdio: 'inherit', env: { ...process.env, MILLENNIUM_API_PROXY: `http://${host}:${port}` },
  })
  const stop = () => ui.kill()
  process.on('exit', stop)
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { stop(); process.exit(0) })
  ui.on('exit', code => process.exit(code ?? 0))
}
