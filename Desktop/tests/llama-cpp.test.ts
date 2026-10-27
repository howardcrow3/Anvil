import { describe, expect, it } from 'vitest'
import { execFile, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
// @ts-expect-error plain .mjs without types
import { REQUIRED, TARGETS, assetFor, chooseRelease, pickAssets } from '../scripts/llama-cpp-lib.mjs'
// @ts-expect-error plain .mjs without types
import { findServerDir, isUnneededTool } from '../scripts/bundle-llama.mjs'

const digest = (c: string) => 'sha256:' + createHash('sha256').update(c).digest('hex')
const names = [
  'macos-arm64', 'macos-x64', 'ubuntu-x64', 'ubuntu-arm64', 'ubuntu-vulkan-x64', 'win-cpu-x64', 'win-cuda-12.4-x64', 'win-vulkan-x64'
].map((n) => `llama-b7000-bin-${n}.zip`)
type Asset = { name: string; browser_download_url?: string; digest?: string }
const release = (over: Partial<{ assets: Asset[]; tag_name: string }> = {}) => ({
  tag_name: 'b7000',
  assets: [...names, 'cudart-llama-bin-win-cuda-12.4-x64.zip'].map((name) => ({
    name, browser_download_url: `https://example.test/${name}`, digest: digest(name)
  })),
  ...over
})

describe('pickAssets', () => {
  it('chooses the plain CPU/Metal build for every platform, never a GPU variant', () => {
    const { lock, missing } = pickAssets(release())
    expect(missing).toEqual([])
    expect(lock.tag).toBe('b7000')
    expect(Object.keys(lock.assets).sort()).toEqual(Object.keys(TARGETS).sort())
    expect(lock.assets['linux-x64'].name).toBe('llama-b7000-bin-ubuntu-x64.zip')
    expect(lock.assets['win32-x64'].name).toBe('llama-b7000-bin-win-cpu-x64.zip')
    expect(lock.assets['darwin-arm64'].sha256).toBe(digest('llama-b7000-bin-macos-arm64.zip').slice(7))
  })

  it('falls back to the older avx2 Windows name and accepts .tar.gz archives', () => {
    const r = release({
      assets: [
        { name: 'llama-b7000-bin-macos-arm64.tar.gz' }, { name: 'llama-b7000-bin-macos-x64.tar.gz' },
        { name: 'llama-b7000-bin-ubuntu-x64.tar.gz' }, { name: 'llama-b7000-bin-win-avx2-x64.zip' }
      ].map((a) => ({ ...a, browser_download_url: 'https://example.test/' + a.name, digest: digest(a.name) }))
    })
    const { lock, missing } = pickAssets(r)
    expect(missing).toEqual([])
    expect(lock.assets['win32-x64'].name).toMatch(/avx2/)
    expect(lock.assets['linux-x64'].name).toMatch(/\.tar\.gz$/)
  })

  it('reports required platforms a release lacks, so it is not adopted', () => {
    const r = release()
    r.assets = r.assets.filter((a) => !/macos-x64/.test(a.name))
    expect(pickAssets(r).missing).toEqual(['darwin-x64'])
    expect(REQUIRED).toContain('darwin-x64')
  })

  it('records a missing or malformed digest as null instead of trusting it', () => {
    const r = release()
    r.assets[0] = { ...r.assets[0], digest: undefined }
    r.assets[1] = { ...r.assets[1], digest: 'md5:abc' }
    const { lock } = pickAssets(r)
    expect(lock.assets['darwin-arm64'].sha256).toBeNull()
    expect(lock.assets['darwin-x64'].sha256).toBeNull()
  })
})

describe('chooseRelease', () => {
  const binaryless = { tag_name: 'v0.7.0', assets: [{ name: 'nightly-tag.txt', browser_download_url: 'https://example.test/n', digest: digest('n') }] }

  it('skips a newest "release" that carries no binaries and takes the first complete one', () => {
    const { lock, skipped } = chooseRelease([binaryless, release({ tag_name: 'b7001' }), release({ tag_name: 'b7000' })])
    expect(lock.tag).toBe('b7001')
    expect(skipped[0]).toMatch(/v0\.7\.0/)
  })

  it('ignores drafts but accepts prereleases (llama.cpp publishes every build as one), and refuses to pick anything when nothing is complete', () => {
    const draft = { ...release({ tag_name: 'b7002' }), draft: true }
    const pre = { ...release({ tag_name: 'b7003' }), prerelease: true }
    expect(chooseRelease([draft, release({ tag_name: 'b6999' })]).lock.tag).toBe('b6999')
    expect(chooseRelease([pre, release({ tag_name: 'b6999' })]).lock.tag).toBe('b7003')
    const none = chooseRelease([binaryless])
    expect(none.lock).toBeNull()
    expect(none.missing.length).toBeGreaterThan(0)
  })
})

describe('assetFor', () => {
  const { lock } = pickAssets(release())
  it('returns the entry for a pinned platform', () => {
    expect(assetFor(lock, 'linux-x64').url).toContain('ubuntu-x64')
  })
  it('explains an unpinned lock, an unknown platform and a missing checksum', () => {
    expect(() => assetFor({ tag: null, assets: {} }, 'linux-x64')).toThrow(/Update llama.cpp/)
    expect(() => assetFor(lock, 'freebsd-x64')).toThrow(/no build for freebsd-x64/)
    expect(() => assetFor({ tag: 'b1', assets: { 'linux-x64': { name: 'x', url: 'u', sha256: null } } }, 'linux-x64')).toThrow(/no sha256/)
  })
  it('the committed lock file has the expected shape', () => {
    const committed = JSON.parse(readFileSync(resolve(__dirname, '../../Resources/llama-cpp.lock.json'), 'utf8'))
    expect(committed.repo).toBe('ggml-org/llama.cpp')
    if (committed.tag) for (const k of REQUIRED) expect(committed.assets[k].sha256).toMatch(/^[0-9a-f]{64}$/)
  })
})

describe('archive layout helpers', () => {
  it('finds llama-server however deeply the archive nests it', () => {
    const root = mkdtempSync(join(tmpdir(), 'lc-'))
    mkdirSync(join(root, 'build', 'bin'), { recursive: true })
    writeFileSync(join(root, 'build', 'bin', 'llama-server'), '')
    expect(findServerDir(root, 'llama-server')).toBe(join(root, 'build', 'bin'))
    expect(findServerDir(root, 'llama-server.exe')).toBeNull()
  })
  it('drops other tools but never the server or shared libraries', () => {
    for (const n of ['llama-cli', 'llama-bench', 'llama-cli.exe', 'test-backend-ops', 'rpc-server']) expect(isUnneededTool(n)).toBe(true)
    for (const n of ['llama-server', 'llama-server.exe', 'libllama.so', 'libggml-base.dylib', 'llama.dll', 'ggml-cpu.dll', 'libllama-common.so.0', 'LICENSE']) {
      expect(isUnneededTool(n)).toBe(false)
    }
  })
})

// End to end against a local file server: download, checksum, extraction, pruning, smoke test.
describe.skipIf(process.platform === 'win32')('bundle-llama', () => {
  const run = async (tamper: boolean) => {
    const work = mkdtempSync(join(tmpdir(), 'bl-'))
    const pkg = join(work, 'pkg', 'build', 'bin')
    mkdirSync(pkg, { recursive: true })
    writeFileSync(join(pkg, 'llama-server'), '#!/bin/sh\necho "version: 4242 (fake)"\n')
    chmodSync(join(pkg, 'llama-server'), 0o755)
    writeFileSync(join(pkg, 'llama-cli'), 'x')
    writeFileSync(join(pkg, 'libllama.so'), 'lib')
    const archive = join(work, 'llama-b1-bin-fake.tar.gz')
    expect(spawnSync('tar', ['-czf', archive, '-C', join(work, 'pkg'), 'build']).status).toBe(0)
    const bytes = readFileSync(archive)
    const server = createServer((_, res) => res.end(tamper ? Buffer.concat([bytes, Buffer.from('!')]) : bytes))
    await new Promise<void>((r) => server.listen(0, '127.0.0.1', r))
    const port = (server.address() as { port: number }).port
    const key = `${process.platform}-${process.arch}`
    const lockPath = join(work, 'lock.json')
    writeFileSync(lockPath, JSON.stringify({
      tag: 'b1', assets: { [key]: { name: 'llama-b1-bin-fake.tar.gz', url: `http://127.0.0.1:${port}/a`, sha256: createHash('sha256').update(bytes).digest('hex') } }
    }))
    const out = join(work, 'out')
    // Async: a blocking spawn would starve the in-process file server the child downloads from.
    const r = await new Promise<{ status: number; stdout: string; stderr: string }>((done) => {
      execFile(process.execPath, [resolve(__dirname, '../scripts/bundle-llama.mjs'), '--out', out, '--cache', join(work, 'cache')], {
        encoding: 'utf8', env: { ...process.env, ANVIL_LLAMA_LOCK: lockPath }, timeout: 60_000
      }, (err, stdout, stderr) => done({ status: err ? (typeof err.code === 'number' ? err.code : 1) : 0, stdout, stderr }))
    })
    server.close()
    return { r, out }
  }

  it('verifies the download, keeps the server and libraries, drops other tools, and smoke-tests it', async () => {
    const { r, out } = await run(false)
    expect(r.stderr).toBe('')
    expect(r.status).toBe(0)
    expect(r.stdout).toMatch(/version: 4242/)
    expect(readdirSync(join(out, 'llama')).sort()).toEqual(['libllama.so', 'llama-server'])
  })

  it('refuses a download whose checksum does not match the lock', async () => {
    const { r, out } = await run(true)
    expect(r.status).not.toBe(0)
    expect(r.stderr).toMatch(/Checksum mismatch/)
    expect(existsSync(join(out, 'llama'))).toBe(false)
  })
})
