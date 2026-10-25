import { spawn, type ChildProcess } from 'node:child_process'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import net from 'node:net'

const STATE = resolve(__dirname, '.state.json')
const procs: ChildProcess[] = []

const freePort = (): Promise<number> =>
  new Promise((res) => {
    const s = net.createServer().listen(0, '127.0.0.1', () => {
      const { port } = s.address() as net.AddressInfo
      s.close(() => res(port))
    })
  })

async function waitFor(check: () => Promise<boolean>, what: string, ms = 30_000): Promise<void> {
  const end = Date.now() + ms
  while (Date.now() < end) {
    if (await check().catch(() => false)) return
    await new Promise((r) => setTimeout(r, 150))
  }
  throw new Error(`timed out waiting for ${what}`)
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  const python = process.env.ANVIL_PYTHON ?? 'python3'
  const runtimeDir = process.env.ANVIL_RUNTIME_DIR ?? resolve(__dirname, '../../AgentRuntime')
  // Isolated HOME so the runtime never touches the developer's real ~/.anvil.
  const home = mkdtempSync(join(tmpdir(), 'anvil-e2e-'))
  const project = join(home, 'project')
  mkdirSync(join(home, '.anvil'), { recursive: true })
  mkdirSync(project)

  const llmPort = await freePort()
  const llm = spawn(python, [resolve(__dirname, 'fake_openai.py'), String(llmPort)], { stdio: 'inherit' })
  procs.push(llm)
  await waitFor(async () => (await fetch(`http://127.0.0.1:${llmPort}/v1/models`)).ok, 'fake LLM')

  writeFileSync(
    join(home, '.anvil', 'config.json'),
    JSON.stringify({ endpoints: [{ name: 'fake', base_url: `http://127.0.0.1:${llmPort}/v1`, default_model: 'fake-model' }], permission_mode: 'ask' })
  )

  const runtime = spawn(
    python,
    ['-u', '-m', 'anvil_agent', '--no-socket', '--ws-port', '0', '--ws-origins', 'http://127.0.0.1:4173', '--project-dir', project, '--log-level', 'WARNING'],
    { cwd: runtimeDir, env: { ...process.env, HOME: home, USERPROFILE: home, ANVIL_WS_TOKEN: 'e2e-token' } }
  )
  procs.push(runtime)
  let out = ''
  const port = await new Promise<number>((res, rej) => {
    runtime.stdout!.on('data', (d: Buffer) => {
      out += d.toString()
      const m = out.match(/WS_READY:(\{.*\})/)
      if (m) res(JSON.parse(m[1]).port)
    })
    runtime.on('exit', (code) => rej(new Error(`runtime exited early (${code}): ${out}`)))
    setTimeout(() => rej(new Error('runtime did not become ready')), 40_000)
  })

  writeFileSync(STATE, JSON.stringify({ runtime: `ws://127.0.0.1:${port}/rpc?token=e2e-token`, project, home }))
  return async () => {
    procs.forEach((p) => p.kill('SIGTERM'))
  }
}
