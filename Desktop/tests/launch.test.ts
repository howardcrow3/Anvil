import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { resolveLaunch } from '../src/main/runtime'

const base = { resourcesPath: '/res', appPath: '/repo/Desktop', projectDir: '/proj', env: {} as NodeJS.ProcessEnv }

describe('resolveLaunch (packaged)', () => {
  it('uses the bundled interpreter and site-packages on macOS/Linux', () => {
    for (const platform of ['darwin', 'linux'] as const) {
      const l = resolveLaunch({ ...base, packaged: true, platform })
      expect(l.command).toBe(join('/res', 'runtime', 'python', 'bin', 'python3'))
      expect(l.env.PYTHONPATH).toBe(join('/res', 'runtime', 'site'))
      expect(l.cwd).toBe(join('/res', 'runtime'))
    }
  })
  it('uses python.exe on Windows', () => {
    const l = resolveLaunch({ ...base, packaged: true, platform: 'win32' })
    expect(l.command).toBe(join('/res', 'runtime', 'python', 'python.exe'))
  })
  it('never relies on a Unix socket and always exits with its parent', () => {
    const { args } = resolveLaunch({ ...base, packaged: true, platform: 'linux' })
    expect(args).toEqual(expect.arrayContaining(['-m', 'anvil_agent', '--no-socket', '--exit-on-stdin-eof']))
    expect(args[args.indexOf('--ws-port') + 1]).toBe('0')
    expect(args[args.indexOf('--project-dir') + 1]).toBe('/proj')
  })
  it('keeps the caller environment and does not leak a dev PYTHONPATH override', () => {
    const l = resolveLaunch({ ...base, env: { FOO: 'bar', PYTHONPATH: '/dev' }, packaged: true, platform: 'linux' })
    expect(l.env.FOO).toBe('bar')
    expect(l.env.PYTHONPATH).toBe(join('/res', 'runtime', 'site'))
  })
})

describe('resolveLaunch (development)', () => {
  it('runs from the repo checkout with the system python by default', () => {
    const l = resolveLaunch({ ...base, packaged: false, platform: 'linux' })
    expect(l.cwd).toBe('/repo/AgentRuntime')
    expect(l.command).toBe('python3')
    expect(resolveLaunch({ ...base, packaged: false, platform: 'win32' }).command).toBe('python')
  })
  it('honours ANVIL_PYTHON and ANVIL_RUNTIME_DIR', () => {
    const l = resolveLaunch({ ...base, env: { ANVIL_PYTHON: '/py', ANVIL_RUNTIME_DIR: '/rt' }, packaged: false, platform: 'linux' })
    expect(l.command).toBe('/py')
    expect(l.cwd).toBe('/rt')
  })
})

describe('packaged Windows launch', () => {
  it('adds the pywin32 directories that pip --target does not wire up', () => {
    const l = resolveLaunch({ ...base, packaged: true, platform: 'win32' })
    const parts = l.env.PYTHONPATH!.split(';')
    expect(parts).toHaveLength(3)
    expect(parts[1]).toMatch(/win32$/)
    expect(parts[2]).toMatch(/lib$/)
  })
})
