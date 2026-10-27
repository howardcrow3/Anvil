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
    await app.close()
    mark('app closed')
  }
  // Quitting the app stops the runtime it started.
  await expect.poll(running, { timeout: 15_000 }).toBe('')
})
