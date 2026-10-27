import { _electron as electron, expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Runs the real Electron app (main process, preload bridge, bundled-runtime supervisor). Needs a display:
//   xvfb-run -a npx playwright test electron
test.skip(!!process.env.SKIP_ELECTRON, 'Electron e2e disabled')

const running = (): string => {
  try {
    return execFileSync('pgrep', ['-f', 'ws-port 0 --exit-on-stdin-eof'], { encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

test('Electron starts and supervises its own runtime, with a locked-down renderer', async () => {
  test.setTimeout(90_000) // cold CI runners take far longer than a dev machine to import the runtime
  const t0 = Date.now()
  const mark = (m: string) => console.log(`[+${((Date.now() - t0) / 1000).toFixed(1)}s] ${m}`) // shows how far a timed-out run got
  const { home } = JSON.parse(readFileSync(resolve(__dirname, '.state.json'), 'utf8')) as { home: string }
  const app = await electron.launch({
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '.'],
    cwd: resolve(__dirname, '..'),
    env: { ...process.env, HOME: home, USERPROFILE: home, ANVIL_PROJECT_DIR: home }
  })
  mark('launched')
  const proc = app.process()
  proc.once('exit', (code, sig) => mark(`electron process exit code=${code} signal=${sig}`))
  proc.once('close', () => mark('electron process close (stdio closed)'))
  app.once('close', () => mark('playwright app close event'))
  let out = ''
  app.process().stdout?.on('data', (d) => (out += String(d)))
  app.process().stderr?.on('data', (d) => (out += String(d)))
  try {
    const win = await app.firstWindow()
    mark('first window')
    try {
      await expect(win.getByText('Connected', { exact: true })).toBeVisible({ timeout: 60_000 })
    } catch (e) {
      const body = await win.evaluate(() => document.body.innerText).catch((x) => `no body: ${x}`)
      throw new Error(`never connected. page text: ${JSON.stringify(String(body).slice(0, 400))} app output: ${JSON.stringify(out.slice(-1500))} (${e})`)
    }

    mark('connected')
    // Renderer isolation: no Node, but the preload bridge is present.
    expect(await win.evaluate(() => typeof (window as unknown as { require?: unknown }).require)).toBe('undefined')
    expect(await win.evaluate(() => typeof (window as unknown as { process?: unknown }).process)).toBe('undefined')
    expect(await win.evaluate(() => typeof window.anvil?.platform)).toBe('string')
    expect(running()).not.toBe('')

    mark('renderer isolation ok')
    // A full chat turn through the supervised runtime.
    await win.getByRole('combobox').first().selectOption({ label: 'fake' })
    mark('fake model selected')
    await win.getByLabel('Message').fill('say hello')
    await win.getByRole('button', { name: 'Send' }).click()
    await expect(win.locator('.msg.assistant strong', { hasText: 'world' })).toBeVisible()
    mark('assistant replied')
    await win.screenshot({ path: resolve(__dirname, 'shots', 'electron.png') })

    mark('screenshot taken')
    // External links never navigate the app window.
    const before = win.url()
    await win.evaluate(() => window.open('https://example.com'))
    expect(win.url()).toBe(before)
  } finally {
    mark('closing app')
    // app.close() can fail to settle on some CI runners even though Electron has already exited (code 0): Playwright
    // never reports the close. The process exit is the real signal that the app quit, so wait on whichever comes first.
    const exited = new Promise<void>((res) => (proc.exitCode !== null ? res() : proc.once('exit', () => res())))
    const probe = setTimeout(() => {
      try {
        // Daemons Electron auto-starts (dbus, at-spi) inherit its stdout/stderr and keep Playwright's close from completing.
        const orphans = execFileSync('ps', ['-eo', 'pid,ppid,etimes,args', '--sort=etimes'], { encoding: 'utf8' })
          .split('\n').filter((l) => /^\s*\d+\s+1\s+\d+\s/.test(l) && Number(l.trim().split(/\s+/)[2]) < 120).map((l) => l.slice(0, 170))
        mark(`still closing; recent processes re-parented to init:\n${orphans.join('\n')}\nchild stdio: ${JSON.stringify(proc.stdio.map((s) => s && { destroyed: s.destroyed }))}`)
      } catch (e) {
        mark(`probe failed: ${e}`)
      }
    }, 15_000)
    await Promise.race([app.close().catch(() => {}), exited])
    clearTimeout(probe)
    mark('app closed')
  }
  // Quitting the app stops the runtime it started.
  await expect.poll(running, { timeout: 15_000 }).toBe('')
})
