#!/usr/bin/env node
// CI diagnostic for the Electron launch: times each phase and prints what the app said. Not part of the product.
import { _electron as electron } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const t0 = Date.now()
const lines = []
const log = (m) => lines.push(`[+${((Date.now() - t0) / 1000).toFixed(1)}s] ${m}`)
const home = mkdtempSync(resolve(tmpdir(), 'anvil-diag-'))
const deadline = (ms, what) => new Promise((_, rej) => setTimeout(() => rej(new Error(`TIMEOUT ${what} after ${ms / 1000}s`)), ms))
let app
try {
  log('launching')
  app = await Promise.race([
    electron.launch({
      args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--enable-logging=stderr', '.'],
      cwd: desktop,
      env: { ...process.env, HOME: home, USERPROFILE: home, ANVIL_PROJECT_DIR: home, ELECTRON_ENABLE_LOGGING: '1' }
    }),
    deadline(40_000, 'electron.launch')
  ])
  log(`launched pid=${app.process().pid}`)
  app.process().stdout?.on('data', (d) => log(`stdout: ${String(d).trim().slice(0, 300)}`))
  app.process().stderr?.on('data', (d) => log(`stderr: ${String(d).trim().slice(0, 300)}`))
  const win = await Promise.race([app.firstWindow(), deadline(40_000, 'firstWindow')])
  log(`first window: ${win.url()}`)
  win.on('console', (m) => log(`console.${m.type()}: ${m.text().slice(0, 200)}`))
  win.on('pageerror', (e) => log(`pageerror: ${String(e).slice(0, 300)}`))
  const text = await Promise.race([
    win.waitForFunction(() => document.body.innerText.includes('Connected'), null, { timeout: 60_000 }).then(() => 'Connected'),
    deadline(65_000, 'Connected text')
  ])
  log(`ui: ${text}`)
} catch (e) {
  log(`FAILED: ${String(e).slice(0, 300)}`)
  try {
    const w = app && app.windows()[0]
    if (w) log(`page text: ${JSON.stringify((await w.evaluate(() => document.body.innerText)).slice(0, 300))}`)
  } catch (x) {
    log(`no page text: ${String(x).slice(0, 100)}`)
  }
} finally {
  await Promise.race([app?.close(), new Promise((r) => setTimeout(r, 5000))]).catch(() => {})
  const body = lines.slice(-40).join('\n')
  console.log(body)
  console.log(`::error title=electron diagnostic::${body.slice(0, 3800).replace(/%/g, '%25').replace(/\n/g, '%0A')}`)
  process.exit(0)
}
