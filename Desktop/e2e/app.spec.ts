import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const state = (): { runtime: string; project: string } => JSON.parse(readFileSync(resolve(__dirname, '.state.json'), 'utf8'))
const shot = (page: Page, name: string): Promise<Buffer> => page.screenshot({ path: resolve(__dirname, 'shots', `${name}.png`) })

async function open(page: Page): Promise<void> {
  await page.goto(`/?runtime=${encodeURIComponent(state().runtime)}`)
  await expect(page.getByText('Connected', { exact: true })).toBeVisible()
}

async function useFakeModel(page: Page): Promise<void> {
  await page.getByRole('combobox').first().selectOption({ label: 'fake' })
  await expect(page.getByRole('combobox').first()).toHaveValue('custom:fake')
}

test('connects, lists models, and streams a markdown reply', async ({ page }) => {
  await open(page)
  await expect(page.getByRole('heading', { name: 'What should we build?' })).toBeVisible()
  await useFakeModel(page)
  await page.getByLabel('Message').fill('say hello')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.msg.assistant strong', { hasText: 'world' })).toBeVisible()
  await expect(page.locator('.msg.assistant pre code')).toContainText("print('hi')")
  await expect(page.getByRole('button', { name: 'Send' })).toBeVisible() // turn finished
  await expect(page.locator('.session').first()).toBeVisible() // session was created and listed
  await shot(page, 'chat')
})

test('tool call asks permission; allowing runs it and shows the result', async ({ page }) => {
  await open(page)
  await useFakeModel(page)
  await page.getByLabel('Message').fill('please run it')
  await page.getByRole('button', { name: 'Send' }).click()

  const dialog = page.getByRole('dialog', { name: 'Allow this action?' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('bash')
  await expect(dialog).toContainText('echo hello-from-tool')
  await shot(page, 'permission')
  await dialog.getByRole('button', { name: 'Allow' }).click()

  await expect(page.locator('.msg.assistant')).toContainText('Tool said: hello-from-tool')
  const card = page.locator('.tool-card').first()
  await expect(card).toHaveClass(/done/)
  await card.getByRole('button').first().click()
  await expect(card).toContainText('hello-from-tool')
  await shot(page, 'tool')
})

test('denying a tool call reports it as an error', async ({ page }) => {
  await open(page)
  await useFakeModel(page)
  await page.getByLabel('Message').fill('run something')
  await page.getByRole('button', { name: 'Send' }).click()
  await page.getByRole('dialog', { name: 'Allow this action?' }).getByRole('button', { name: 'Deny' }).click()
  await expect(page.locator('.tool-card').first()).toHaveClass(/error/)
})

test('a failing model shows an error and the composer recovers', async ({ page }) => {
  await open(page)
  await useFakeModel(page)
  await page.getByLabel('Message').fill('please fail')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('alert').filter({ hasText: /./ }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Send' })).toBeVisible()
})

test('reopening a session restores its messages', async ({ page }) => {
  await open(page)
  await useFakeModel(page)
  await page.getByLabel('Message').fill('remember me')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('button', { name: 'Send' })).toBeVisible()
  await page.getByRole('button', { name: '+ New chat' }).click()
  await expect(page.getByRole('heading', { name: 'What should we build?' })).toBeVisible()
  await page.locator('.session').first().click()
  await expect(page.locator('.msg.user')).toContainText('remember me')
})

test('settings: permission mode, theme, and API key', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'Permissions' }).click()
  await page.getByLabel('Trust').check()
  await expect(page.locator('.radio.on')).toContainText('Trust')
  await page.getByRole('tab', { name: 'General' }).click()
  await page.getByLabel('Theme').selectOption('dark')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('tab', { name: 'API Key' }).click()
  await page.getByRole('dialog').getByLabel('API key').fill('sk-ant-test-1234')
  await page.getByRole('button', { name: 'Save key' }).click()
  await expect(page.getByText('API key saved.')).toBeVisible()
  await expect(page.getByText('1234')).toBeVisible()
  await page.getByRole('button', { name: 'Remove key' }).click()
  await expect(page.getByText('No key saved.')).toBeVisible()
  await page.getByRole('tab', { name: 'Permissions' }).click()
  await page.getByLabel('Ask every time').check() // restore for other tests
  await shot(page, 'settings')
})

test('MCP: add, test, enable/disable, import and remove a server', async ({ page }) => {
  const server = resolve(process.env.ANVIL_RUNTIME_DIR ?? resolve(__dirname, '../../AgentRuntime'), 'tests/fixtures/mcp_test_server.py')
  const python = process.env.ANVIL_PYTHON ?? 'python3'
  await open(page)
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('tab', { name: 'MCP' }).click()
  await expect(page.getByText('No MCP servers configured.')).toBeVisible()

  await page.getByRole('button', { name: '+ Add server' }).click()
  const editor = page.getByRole('dialog', { name: 'Add MCP server' })
  await editor.getByLabel('Name').fill('demo')
  await editor.getByLabel('Command', { exact: true }).fill(python)
  await editor.getByLabel('Arguments (one per line)').fill(server)
  await editor.getByRole('button', { name: 'Test connection' }).click()
  await expect(editor.getByText(/Connected — 3 tools available/)).toBeVisible({ timeout: 30_000 })
  await shot(page, 'mcp-editor')
  await editor.getByRole('button', { name: 'Add', exact: true }).click()

  const row = page.locator('.mcp-row', { hasText: 'demo' })
  await expect(row).toContainText('stdio · connected', { timeout: 30_000 })
  await row.getByText('3 tools').click()
  await expect(row).toContainText('mcp__demo__add')
  await shot(page, 'mcp-list')

  await row.getByLabel('Enable demo').uncheck()
  await expect(row).toContainText('Disabled', { timeout: 30_000 })
  await row.getByLabel('Enable demo').check()
  await expect(row).toContainText('connected', { timeout: 30_000 })

  await page.getByRole('button', { name: 'Import JSON…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Import MCP servers' })
  await dialog.getByLabel('MCP config JSON').fill('nope')
  await dialog.getByRole('button', { name: 'Import' }).click()
  await expect(dialog.getByText("That isn't valid JSON.")).toBeVisible()
  await dialog.getByLabel('MCP config JSON').fill(JSON.stringify({ mcpServers: { broken: { command: '/nonexistent/binary' } } }))
  await dialog.getByRole('button', { name: 'Import' }).click()
  const broken = page.locator('.mcp-row', { hasText: 'broken' })
  await expect(broken).toContainText('Failed', { timeout: 30_000 })
  await expect(broken.locator('.mcp-error')).not.toBeEmpty()

  for (const name of ['broken', 'demo']) {
    await page.getByRole('button', { name: `Remove ${name}` }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Remove' }).click()
    await expect(page.locator('.mcp-row', { hasText: name })).toHaveCount(0, { timeout: 30_000 })
  }
})
