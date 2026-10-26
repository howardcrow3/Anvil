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

test('kanban: create a task, block it, unblock it', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Kanban' }).click()
  await page.getByRole('button', { name: '+ New task' }).click()
  await page.getByLabel('Title').fill('Write the docs')
  await page.getByRole('button', { name: 'Create task' }).click()
  const ready = page.getByLabel('Ready', { exact: true })
  await expect(ready.getByText('Write the docs')).toBeVisible()
  await ready.getByRole('button', { name: 'Block' }).click()
  await page.getByLabel('Why is it blocked?').fill('waiting on review')
  await page.getByRole('button', { name: 'Block', exact: true }).last().click()
  const blocked = page.getByLabel('Blocked', { exact: true })
  await expect(blocked.getByText('Write the docs')).toBeVisible()
  await blocked.getByRole('button', { name: 'Unblock' }).click()
  await expect(page.getByLabel('Ready', { exact: true }).getByText('Write the docs')).toBeVisible()
  await shot(page, 'kanban')
})

test('projects: create a project, add and complete a task', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Projects' }).click()
  await page.getByRole('button', { name: '+ New project' }).click()
  await page.getByLabel('Name').fill('Launch')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page.getByRole('heading', { name: 'Launch' })).toBeVisible()
  await page.getByLabel('New task title').fill('Ship it')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByLabel('Status of Ship it').selectOption('completed')
  await expect(page.getByRole('navigation', { name: 'Project list' })).toContainText('1/1 done')
  await shot(page, 'projects')
})

test('endpoints: add a custom endpoint and see it in the model picker', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Settings' }).click()
  const dialog = page.getByRole('dialog', { name: 'Settings' })
  await dialog.getByRole('tab', { name: 'Endpoints' }).click()
  await dialog.getByRole('button', { name: '+ Add endpoint' }).click()
  await dialog.getByLabel('Name').fill('local-lm')
  await dialog.getByLabel('Base URL').fill('not a url')
  await dialog.getByLabel('Model').fill('qwen')
  await dialog.getByRole('button', { name: 'Save endpoint' }).click()
  await expect(dialog.getByRole('alert')).toContainText('valid base URL')
  await dialog.getByLabel('Base URL').fill('http://127.0.0.1:9/v1')
  await dialog.getByRole('button', { name: 'Save endpoint' }).click()
  await expect(dialog.getByText('local-lm', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByRole('combobox').first().locator('option', { hasText: 'local-lm' })).toHaveCount(1)
})

test('skills: import, search, disable, delete', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Skills' }).click()
  await page.getByRole('button', { name: 'Import skill' }).click()
  await page.getByLabel('Name').fill('Release Notes')
  await page.getByLabel('SKILL.md contents').fill('---\nname: release-notes\ndescription: writes release notes\n---\nSummarize commits.')
  await page.getByRole('button', { name: 'Import', exact: true }).click()
  await page.getByLabel('Search skills').fill('release')
  const toggle = page.getByLabel('Enable release-notes')
  await expect(toggle).toBeChecked()
  await toggle.click()
  await expect(toggle).not.toBeChecked()
  await page.getByRole('button', { name: 'Delete release-notes' }).click()
  await page.getByRole('dialog', { name: 'Delete skill?' }).getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText('No skills match your search.')).toBeVisible()
})

test('teams: create a team and add a shared task', async ({ page }) => {
  await open(page)
  await page.getByRole('button', { name: 'Teams' }).click()
  await page.getByRole('button', { name: '+ New team' }).click()
  await page.getByLabel('Team name').fill('Docs crew')
  await page.getByLabel('Members').fill('writer: drafts\nreviewer: checks')
  await page.getByRole('button', { name: 'Create team' }).click()
  await expect(page.getByRole('heading', { name: 'Docs crew' })).toBeVisible()
  await expect(page.locator('.chips')).toContainText('writer · drafts')
  await page.getByLabel('New team task').fill('Outline')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.locator('.task-row', { hasText: 'Outline' })).toBeVisible()
})
