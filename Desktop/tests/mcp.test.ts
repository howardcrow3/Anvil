import { describe, expect, it } from 'vitest'
import { blankServer, fromWire, kv, parseArgs, parseImport, toWire, validate } from '@/lib/mcp'

describe('mcp wire conversion', () => {
  it('round-trips a stdio server and drops blank env keys', () => {
    const s = { ...blankServer(), name: ' files ', command: 'npx', args: ['-y', 'pkg'], env: [kv('TOKEN', 'abc'), kv('  ', 'dropped')] }
    const wire = toWire(s)
    expect(wire).toMatchObject({ name: 'files', transport: 'stdio', command: 'npx', args: ['-y', 'pkg'], env: { TOKEN: 'abc' } })
    const back = fromWire({ ...wire, status: 'failed', error: 'boom', tools: [{ name: 'mcp__files__x', description: 'X' }] })!
    expect(back).toMatchObject({ id: 'files', status: 'failed', error: 'boom' })
    expect(back.env.map((r) => r.key)).toEqual(['TOKEN'])
    expect(back.tools).toEqual([{ name: 'mcp__files__x', description: 'X' }])
  })

  it('rejects nameless servers and defaults unknown values', () => {
    expect(fromWire({ transport: 'stdio' })).toBeNull()
    expect(fromWire({ name: 'a', transport: 'carrier-pigeon', status: '??' })).toMatchObject({ transport: 'stdio', status: 'stopped' })
  })
})

describe('validate', () => {
  const base = { ...blankServer(), name: 'a', command: 'x' }
  it('checks name, uniqueness, command and url', () => {
    expect(validate(blankServer(), [])).toMatch(/name/)
    expect(validate(base, [])).toBeNull()
    expect(validate(base, ['a'])).toMatch(/already named/)
    expect(validate({ ...base, command: ' ' }, [])).toMatch(/command/)
    expect(validate({ ...base, transport: 'http', url: 'ftp://x' }, [])).toMatch(/http/)
    expect(validate({ ...base, transport: 'sse', url: 'https://x.test/sse' }, [])).toBeNull()
  })
})

describe('parseArgs', () => {
  it('splits lines and drops blanks', () => expect(parseArgs('-y\n  pkg \r\n\n/tmp\n')).toEqual(['-y', 'pkg', '/tmp']))
})

describe('parseImport', () => {
  it('reads a Claude Desktop config', () => {
    const servers = parseImport(
      JSON.stringify({
        mcpServers: {
          files: { command: 'npx', args: ['-y', 'srv'], env: { A: '1' } },
          remote: { url: 'https://x.test/mcp', headers: { Authorization: 'Bearer t' } },
          legacy: { url: 'https://x.test/sse' },
          off: { command: 'x', disabled: true },
          junk: 5
        }
      })
    )
    const by = Object.fromEntries(servers.map((s) => [s.name, s]))
    expect(Object.keys(by).sort()).toEqual(['files', 'legacy', 'off', 'remote'])
    expect(by.files).toMatchObject({ transport: 'stdio', args: ['-y', 'srv'] })
    expect(by.remote).toMatchObject({ transport: 'http' })
    expect(by.remote.headers[0]).toMatchObject({ key: 'Authorization' })
    expect(by.legacy.transport).toBe('sse')
    expect(by.off.enabled).toBe(false)
  })
  it('accepts a bare table and rejects garbage', () => {
    expect(parseImport('{"a": {"command": "x"}}')).toHaveLength(1)
    expect(() => parseImport('nope')).toThrow(/valid JSON/)
    expect(() => parseImport('{"mcpServers": {}}')).toThrow(/No MCP servers/)
  })
})
