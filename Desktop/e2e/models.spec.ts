import { expect, test, type Page } from '@playwright/test'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

const state = (): { runtime: string } => JSON.parse(readFileSync(resolve(__dirname, '.state.json'), 'utf8'))

interface Row {
  id: string
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
