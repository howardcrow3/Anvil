#!/usr/bin/env node
// Puts the pinned official llama.cpp release (llama-server and its shared libraries) in build/runtime/llama/.
// Run on the OS/arch you are packaging for; bundle-runtime.mjs calls this too.
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { chmodSync, cpSync, createWriteStream, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { fileURLToPath } from 'node:url'
import { assetFor, llamaDir, readLock } from './llama-cpp-lib.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const desktop = resolve(here, '..')

/** The directory containing llama-server(.exe) inside an extracted archive. */
export function findServerDir(root, exe) {
  const stack = [root]
  while (stack.length) {
    const dir = stack.pop()
    for (const name of readdirSync(dir)) {
      const p = join(dir, name)
      if (statSync(p).isDirectory()) stack.push(p)
      else if (name === exe) return dir
    }
  }
  return null
}

/** Other llama.cpp programs (cli, bench, tests...) ship beside the server; the app never runs them. */
export const isUnneededTool = (name) => /^(llama-(?!server)|test-|rpc-server)/.test(name) && !/\.(dll|so|dylib)(\.|$)/.test(name)

const sha256 = (file) => createHash('sha256').update(readFileSync(file)).digest('hex')

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts })
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(' ')} failed (${r.status ?? r.error})`)
}

export async function bundleLlama({ out, cache, platform = process.platform, arch = process.arch }) {
  if (platform !== process.platform || arch !== process.arch) {
    throw new Error(`Cross-bundling is not supported: run this on ${platform}-${arch} (host is ${process.platform}-${process.arch}).`)
  }
  const key = `${platform}-${arch}`
  const lock = readLock()
  const entry = assetFor(lock, key)
  mkdirSync(cache, { recursive: true })
  const archive = join(cache, entry.name)
  if (!existsSync(archive) || sha256(archive) !== entry.sha256) {
    console.log(`Downloading llama.cpp ${lock.tag}: ${entry.name}`)
    const res = await fetch(entry.url, { redirect: 'follow' })
    if (!res.ok || !res.body) throw new Error(`Download failed (${res.status}) for ${entry.url}`)
    await pipeline(Readable.fromWeb(res.body), createWriteStream(archive))
  }
  if (sha256(archive) !== entry.sha256) {
    rmSync(archive)
    throw new Error(`Checksum mismatch for ${entry.name}: expected ${entry.sha256}. The download was removed; re-run, or update the lock if the release was re-published.`)
  }

  const staging = mkdtempSync(join(tmpdir(), 'anvil-llama-'))
  try {
    // Relative paths with cwd=staging: GNU tar (Git for Windows) reads "C:\..." as host:file.
    const rel = relative(staging, archive).split(sep).join('/')
    if (entry.name.endsWith('.zip') && platform === 'linux') run('unzip', ['-q', archive, '-d', staging])
    else run('tar', [entry.name.endsWith('.zip') ? '-xf' : '-xzf', rel], { cwd: staging })

    const exe = platform === 'win32' ? 'llama-server.exe' : 'llama-server'
    const srcDir = findServerDir(staging, exe)
    if (!srcDir) throw new Error(`${entry.name} does not contain ${exe}`)
    const dest = llamaDir(out)
    rmSync(dest, { recursive: true, force: true })
    mkdirSync(dest, { recursive: true })
    for (const name of readdirSync(srcDir)) {
      if (isUnneededTool(name)) continue
      cpSync(join(srcDir, name), join(dest, name), { recursive: true, dereference: false, verbatimSymlinks: true })
    }
    if (platform !== 'win32') chmodSync(join(dest, exe), 0o755)

    // Smoke test: the binary starts and reports its build.
    const libs = { LD_LIBRARY_PATH: dest, DYLD_LIBRARY_PATH: dest }
    const r = spawnSync(join(dest, exe), ['--version'], { encoding: 'utf8', env: { ...process.env, ...libs }, timeout: 60_000 })
    if (r.status !== 0) throw new Error(`llama-server --version failed (${r.status ?? r.error}):\n${r.stdout}${r.stderr}`)
    console.log(`llama.cpp ${lock.tag} bundled at ${dest}: ${(r.stdout + r.stderr).trim().split('\n').pop()}`)
    return { dest, tag: lock.tag }
  } finally {
    rmSync(staging, { recursive: true, force: true })
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const arg = (name) => {
    const i = process.argv.indexOf(`--${name}`)
    return i > 0 ? process.argv[i + 1] : undefined
  }
  await bundleLlama({
    out: resolve(arg('out') ?? join(desktop, 'build', 'runtime')),
    cache: resolve(arg('cache') ?? join(desktop, 'build', 'cache'))
  })
}
