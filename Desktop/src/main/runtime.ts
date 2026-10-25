import { spawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { existsSync, createWriteStream, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import type { RuntimeState } from '../shared/types'

export interface RuntimeLaunch {
  command: string
  args: string[]
  cwd?: string
  env: NodeJS.ProcessEnv
}

const WS_READY = 'WS_READY:'

/** Picks how to start the Python agent runtime: bundled in a packaged app, otherwise the repo checkout. */
export function resolveLaunch(opts: {
  packaged: boolean
  resourcesPath: string
  appPath: string
  platform: NodeJS.Platform
  projectDir: string
  env: NodeJS.ProcessEnv
}): RuntimeLaunch {
  const { platform, env } = opts
  const common = ['-m', 'anvil_agent', '--no-socket', '--ws-port', '0', '--exit-on-stdin-eof', '--project-dir', opts.projectDir]

  if (opts.packaged) {
    const root = join(opts.resourcesPath, 'runtime')
    const python = platform === 'win32' ? join(root, 'python', 'python.exe') : join(root, 'python', 'bin', 'python3')
    return { command: python, args: common, cwd: root, env: { ...env, PYTHONPATH: join(root, 'site') } }
  }

  // Development: AgentRuntime lives next to Desktop/ in the repo.
  const runtimeDir = resolve(env.ANVIL_RUNTIME_DIR ?? join(opts.appPath, '..', 'AgentRuntime'))
  const venvPython = [
    platform === 'win32' ? join(runtimeDir, 'venv', 'Scripts', 'python.exe') : join(runtimeDir, 'venv', 'bin', 'python'),
    platform === 'win32' ? join(runtimeDir, '.venv', 'Scripts', 'python.exe') : join(runtimeDir, '.venv', 'bin', 'python')
  ].find(existsSync)
  const python = env.ANVIL_PYTHON ?? venvPython ?? (platform === 'win32' ? 'python' : 'python3')
  return { command: python, args: common, cwd: runtimeDir, env }
}

/** Supervises the Python runtime: starts it, parses its WS_READY line, restarts it if it dies. */
export class RuntimeSupervisor extends EventEmitter {
  state: RuntimeState = { status: 'stopped' }
  private child: ChildProcess | null = null
  private stopping = false
  private restarts = 0
  private logPath: string | null

  constructor(
    private readonly launch: () => RuntimeLaunch,
    logDir?: string
  ) {
    super()
    if (logDir) {
      mkdirSync(logDir, { recursive: true })
      this.logPath = join(logDir, 'runtime.log')
    } else {
      this.logPath = null
    }
  }

  private set(state: RuntimeState): void {
    this.state = state
    this.emit('state', state)
  }

  start(): void {
    this.stopping = false
    this.set({ status: 'starting' })
    const token = randomBytes(32).toString('base64url')
    const { command, args, cwd, env } = this.launch()
    const log = this.logPath ? createWriteStream(this.logPath, { flags: 'a' }) : null

    let child: ChildProcess
    try {
      child = spawn(command, args, { cwd, env: { ...env, ANVIL_WS_TOKEN: token, PYTHONUNBUFFERED: '1' } })
    } catch (e) {
      this.set({ status: 'crashed', detail: String(e) })
      return
    }
    this.child = child

    let buffer = ''
    child.stdout?.on('data', (chunk: Buffer) => {
      log?.write(chunk)
      buffer += chunk.toString()
      let nl: number
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trim()
        buffer = buffer.slice(nl + 1)
        if (line.startsWith(WS_READY)) {
          try {
            const { port } = JSON.parse(line.slice(WS_READY.length)) as { port: number }
            this.restarts = 0
            this.set({ status: 'ready', url: `ws://127.0.0.1:${port}/rpc?token=${encodeURIComponent(token)}` })
          } catch (e) {
            this.set({ status: 'crashed', detail: `bad WS_READY line: ${String(e)}` })
          }
        }
      }
    })
    child.stderr?.on('data', (chunk: Buffer) => log?.write(chunk))
    child.on('error', (e) => this.set({ status: 'crashed', detail: `could not start ${command}: ${e.message}` }))
    child.on('exit', (code, signal) => {
      log?.end()
      if (this.child === child) this.child = null
      if (this.stopping) return this.set({ status: 'stopped' })
      this.set({ status: 'crashed', detail: `runtime exited (${signal ?? code})` })
      if (this.restarts < 3) {
        this.restarts += 1
        setTimeout(() => !this.stopping && this.start(), 500 * this.restarts)
      }
    })
  }

  stop(): Promise<void> {
    this.stopping = true
    const child = this.child
    if (!child) {
      this.set({ status: 'stopped' })
      return Promise.resolve()
    }
    return new Promise((done) => {
      const kill = setTimeout(() => child.kill('SIGKILL'), 3000)
      child.once('exit', () => {
        clearTimeout(kill)
        done()
      })
      child.kill('SIGTERM')
    })
  }

  async restart(): Promise<void> {
    await this.stop()
    this.restarts = 0
    this.start()
  }
}
