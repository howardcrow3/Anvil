import { call } from './api'
import type { KeyValue, McpServer, McpState, McpTool, McpTransport } from './types'

let seq = 0
export const kv = (key = '', value = ''): KeyValue => ({ id: `kv${seq++}`, key, value })

export function blankServer(): McpServer {
  return {
    id: `new-${Date.now().toString(36)}-${seq++}`,
    name: '',
    transport: 'stdio',
    enabled: true,
    command: '',
    args: [],
    cwd: '',
    env: [],
    url: '',
    headers: [],
    timeout: 60,
    status: 'stopped',
    error: '',
    tools: []
  }
}

const pairs = (value: unknown): KeyValue[] =>
  value && typeof value === 'object' ? Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => kv(k, String(v))) : []

const dictionary = (rows: KeyValue[]): Record<string, string> => {
  const out: Record<string, string> = {}
  for (const { key, value } of rows) if (key.trim()) out[key.trim()] = value
  return out
}

/** Runtime → UI shape (`mcp.list`). */
export function fromWire(raw: Record<string, unknown>): McpServer | null {
  const name = raw.name
  if (typeof name !== 'string' || !name) return null
  const transport = (['stdio', 'http', 'sse'] as const).includes(raw.transport as McpTransport) ? (raw.transport as McpTransport) : 'stdio'
  return {
    id: name,
    name,
    transport,
    enabled: raw.enabled !== false,
    command: String(raw.command ?? ''),
    args: Array.isArray(raw.args) ? raw.args.map(String) : [],
    cwd: String(raw.cwd ?? ''),
    env: pairs(raw.env),
    url: String(raw.url ?? ''),
    headers: pairs(raw.headers),
    timeout: typeof raw.timeout === 'number' ? raw.timeout : 60,
    status: (['connected', 'failed', 'disabled', 'stopped'] as const).includes(raw.status as McpState) ? (raw.status as McpState) : 'stopped',
    error: String(raw.error ?? ''),
    tools: Array.isArray(raw.tools)
      ? raw.tools.flatMap((t): McpTool[] => {
          const tool = t as Record<string, unknown>
          return typeof tool.name === 'string' ? [{ name: tool.name, description: String(tool.description ?? '') }] : []
        })
      : []
  }
}

/** UI → runtime shape (`mcp.save` / `mcp.test`). */
export function toWire(s: McpServer): Record<string, unknown> {
  return {
    name: s.name.trim(),
    transport: s.transport,
    enabled: s.enabled,
    command: s.command.trim(),
    args: s.args,
    cwd: s.cwd.trim(),
    env: dictionary(s.env),
    url: s.url.trim(),
    headers: dictionary(s.headers),
    timeout: s.timeout
  }
}

/** Problem that stops a server being saved, or null. */
export function validate(s: McpServer, otherNames: string[]): string | null {
  const name = s.name.trim()
  if (!name) return 'Give the server a name.'
  if (otherNames.includes(name)) return `Another server is already named “${name}”.`
  if (s.transport === 'stdio') return s.command.trim() ? null : 'Enter the command to run.'
  return /^https?:\/\/\S+$/i.test(s.url.trim()) ? null : 'Enter a full http:// or https:// URL.'
}

export const parseArgs = (text: string): string[] =>
  text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)

/** Parses a Claude Desktop / Claude Code config: `{"mcpServers": {...}}` or the bare name→entry table. */
export function parseImport(text: string): McpServer[] {
  let root: unknown
  try {
    root = JSON.parse(text)
  } catch {
    throw new Error("That isn't valid JSON.")
  }
  if (!root || typeof root !== 'object' || Array.isArray(root)) throw new Error("That isn't valid JSON.")
  const table = ((root as Record<string, unknown>).mcpServers ?? root) as Record<string, unknown>
  const servers: McpServer[] = []
  for (const [name, value] of Object.entries(table).sort(([a], [b]) => a.localeCompare(b))) {
    if (!value || typeof value !== 'object') continue
    const e = value as Record<string, unknown>
    const command = typeof e.command === 'string' ? e.command : ''
    const url = typeof e.url === 'string' ? e.url : ''
    if (!command && !url) continue
    const server: McpServer = { ...blankServer(), id: name, name }
    server.enabled = typeof e.enabled === 'boolean' ? e.enabled : e.disabled !== true
    if (typeof e.timeout === 'number') server.timeout = e.timeout
    if (command) {
      server.command = command
      server.args = Array.isArray(e.args) ? e.args.map(String) : []
      server.cwd = typeof e.cwd === 'string' ? e.cwd : ''
      server.env = pairs(e.env)
    } else {
      const type = typeof e.type === 'string' ? e.type.toLowerCase() : ''
      server.transport = type === 'sse' || (!type && url.endsWith('/sse')) ? 'sse' : 'http'
      server.url = url
      server.headers = pairs(e.headers)
    }
    servers.push(server)
  }
  if (!servers.length) throw new Error('No MCP servers found. Expected {"mcpServers": {"name": {"command": …}}}.')
  return servers
}

// ---- runtime calls --------------------------------------------------------------------------

const parseList = (r: { servers?: Record<string, unknown>[] }): McpServer[] => (r.servers ?? []).flatMap((s) => fromWire(s) ?? [])

export const listServers = async (): Promise<McpServer[]> => parseList(await call('mcp.list'))

/** Saves the full list and reconnects. Reconnecting can take a while if a server is slow to start. */
export const saveServers = async (servers: McpServer[]): Promise<McpServer[]> =>
  parseList(await call('mcp.save', { servers: servers.map(toWire), reload: true }, 120_000))

export const reloadServers = async (): Promise<McpServer[]> => parseList(await call('mcp.reload', {}, 120_000))

export interface TestResult {
  ok: boolean
  tools?: McpTool[]
  error?: string
}
export const testServer = (server: McpServer): Promise<TestResult> => call<TestResult>('mcp.test', { server: toWire(server) }, 60_000)
