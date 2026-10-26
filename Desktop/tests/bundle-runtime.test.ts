import { describe, expect, it } from 'vitest'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const script = resolve(__dirname, '../scripts/bundle-runtime.mjs')
const run = (...args: string[]) => spawnSync(process.execPath, [script, ...args], { encoding: 'utf8', timeout: 20_000 })

describe('bundle-runtime guard rails (fail before any download)', () => {
  it('rejects unsupported targets and lists the supported ones', () => {
    const r = run('--platform', 'freebsd', '--arch', 'x64')
    expect(r.status).not.toBe(0)
    expect(r.stderr).toMatch(/Unsupported target freebsd-x64/)
    expect(r.stderr).toMatch(/linux-x64/)
  })
  it('refuses to cross-bundle native wheels', () => {
    const other = process.platform === 'win32' ? 'linux' : 'win32'
    const r = run('--platform', other, '--arch', 'x64')
    expect(r.status).not.toBe(0)
    expect(r.stderr).toMatch(/Cross-bundling is not supported/)
  })
})
