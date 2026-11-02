import { expect, test, type Page } from '@playwright/test'
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const state = (): { runtime: string } => JSON.parse(readFileSync(resolve(__dirname, '.state.json'), 'utf8'))

interface Row {
  id: string
  name: string
  provider: string
  status: string
  active: boolean
  min_ram_gb?: number
  progress?: { done: number; total: number }
}

/** Calls a runtime RPC from the page (the app's own client is not exposed on window). */
async function rpc<T>(page: Page, method: string, params: Record<string, unknown> = {}): Promise<T> {
  return page.evaluate(
    ([url, m, p]) =>
      new Promise<unknown>((res, rej) => {
        const ws = new WebSocket(url as string)
        ws.onopen = () => ws.send(JSON.stringify({ jsonrpc: '2.0', id: 1, method: m, params: p }))
        ws.onmessage = (ev) => {
          const msg = JSON.parse(String(ev.data))
          if (msg.id !== 1) return
          ws.close()
          const failure = msg.error?.message ?? (typeof msg.result?.error === 'string' ? msg.result.error : null)
          failure ? rej(new Error(failure)) : res(msg.result)
        }
        ws.onerror = () => rej(new Error('websocket error'))
      }),
    [state().runtime, method, params] as const
  ) as Promise<T>
}

const locals = async (page: Page): Promise<Row[]> => (await rpc<Row[]>(page, 'model.list')).filter((m) => m.provider === 'local')

/** The smallest model that is not the active one (the runtime refuses to delete the active model). */
async function smallest(page: Page): Promise<Row> {
  return (await locals(page)).filter((m) => !m.active).sort((a, b) => (a.min_ram_gb ?? 0) - (b.min_ram_gb ?? 0))[0]
}

const status = async (page: Page, id: string): Promise<string | undefined> => (await locals(page)).find((m) => m.id === id)?.status

test.beforeEach(async ({ page }) => {
  await page.goto('/')
})

test('download completes and the model becomes selectable', async ({ page }) => {
  const { id } = await smallest(page)
  expect(await status(page, id)).toBe('downloadable')
  await rpc(page, 'model.download', { model_id: id })
  await expect.poll(() => status(page, id), { timeout: 30_000 }).toBe('available')
  await rpc(page, 'model.delete', { model_id: id })
  expect(await status(page, id)).toBe('downloadable')
})

test('cancel stops the download and leaves no files behind', async ({ page }) => {
  const { id } = await smallest(page)
  const { models_dir } = await rpc<{ models_dir: string }>(page, 'llama.info')
  await rpc(page, 'model.download', { model_id: id })
  await expect.poll(async () => (await locals(page)).find((m) => m.id === id)?.progress?.done ?? 0, { timeout: 10_000 }).toBeGreaterThan(0)
  expect(await rpc(page, 'model.cancel_download', { model_id: id })).toMatchObject({ status: 'cancelled' })
  expect(await status(page, id)).toBe('downloadable')
  expect(existsSync(models_dir) ? readdirSync(models_dir) : []).toEqual([])
})

// ── The Models tab ──────────────────────────────────────────────────────────

async function openModels(page: Page): Promise<void> {
  await page.goto(`/?runtime=${encodeURIComponent(state().runtime)}`)
  await expect(page.getByText('Connected', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Models' }).click()
}

test('models tab lists only the local models the runtime offers, with sizes', async ({ page }) => {
  await openModels(page)
  const offered = await locals(page)
  await expect(page.locator('.model-row')).toHaveCount(offered.length)
  for (const m of offered) {
    const row = page.locator('.model-row', { hasText: m.name }).first()
    await expect(row).toContainText('GB download')
    await expect(row).toContainText('GB RAM')
  }
})

test('download shows progress, blocks a second download, and cancel removes it', async ({ page }) => {
  const { id, name } = await smallest(page)
  const { models_dir } = await rpc<{ models_dir: string }>(page, 'llama.info')
  await openModels(page)
  await page.getByRole('button', { name: `Download ${name}` }).click()
  const bar = page.getByRole('progressbar', { name: `Downloading ${name}` })
  await expect(bar).toBeVisible()
  for (const other of (await locals(page)).filter((m) => m.id !== id && m.status === 'downloadable')) {
    await expect(page.getByRole('button', { name: `Download ${other.name}` })).toBeDisabled()
  }
  await page.getByRole('button', { name: `Cancel download of ${name}` }).click()
  await expect(page.getByRole('alertdialog')).toContainText('partial download will be deleted')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel download' }).click()
  await expect(bar).toBeHidden()
  await expect(page.getByRole('button', { name: `Download ${name}` })).toBeEnabled()
  expect(existsSync(models_dir) ? readdirSync(models_dir) : []).toEqual([])
})

test('delete asks for confirmation first', async ({ page }) => {
  const { id, name } = await smallest(page)
  await rpc(page, 'model.download', { model_id: id })
  await expect.poll(() => status(page, id), { timeout: 30_000 }).toBe('available')
  await openModels(page)
  await page.getByRole('button', { name: `Delete ${name}` }).click()
  await expect(page.getByRole('alertdialog')).toContainText('frees about')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Keep' }).click()
  expect(await status(page, id)).toBe('available')
  await page.getByRole('button', { name: `Delete ${name}` }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByRole('button', { name: `Download ${name}` })).toBeVisible()
  expect(await status(page, id)).toBe('downloadable')
})

test('a partial download left on disk is shown and can be removed', async ({ page }) => {
  const { id, name } = await smallest(page)
  const { models_dir } = await rpc<{ models_dir: string }>(page, 'llama.info')
  const dir = resolve(models_dir, id.replace(/[^A-Za-z0-9._-]+/g, '_'))
  mkdirSync(dir, { recursive: true })
  writeFileSync(resolve(dir, 'model-Q4_0.gguf.part'), Buffer.alloc(2 ** 20)) // as left by an interrupted download
  await openModels(page)
  const row = page.locator('.model-row', { hasText: name }).first()
  await expect(row).toContainText('Partial download')
  await expect(page.getByRole('button', { name: `Resume ${name}` })).toBeEnabled()
  await page.getByRole('button', { name: `Remove partial download of ${name}` }).click()
  await expect(page.getByRole('alertdialog')).toContainText('Remove the partial download')
  await page.getByRole('alertdialog').getByRole('button', { name: 'Remove' }).click()
  await expect(page.getByRole('button', { name: `Download ${name}` })).toBeVisible()
  expect(existsSync(dir)).toBe(false)
})
