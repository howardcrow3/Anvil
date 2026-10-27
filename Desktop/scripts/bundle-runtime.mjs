#!/usr/bin/env node
// Builds build/runtime/ — the self-contained Python runtime that electron-builder ships as resources/runtime:
//   runtime/python/     standalone CPython (python-build-standalone)
//   runtime/site/       anvil_agent + its dependencies (PYTHONPATH)
//   runtime/Resources/  data files the runtime reads (default-models.json)
//   runtime/llama/      the pinned llama.cpp release (llama-server + libraries), see bundle-llama.mjs
//
// Must run on the OS/arch you are packaging for (native wheels are installed with the bundled interpreter).
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { bundleLlama } from './bundle-llama.mjs'
import { assetFor, downloadFile, readLock } from './llama-cpp-lib.mjs'

const PBS_TAG = '20241206'
const PY_VERSION = '3.12.8'
const TRIPLES = {
  'darwin-arm64': 'aarch64-apple-darwin',
  'darwin-x64': 'x86_64-apple-darwin',
  'linux-x64': 'x86_64-unknown-linux-gnu',
  'linux-arm64': 'aarch64-unknown-linux-gnu',
  'win32-x64': 'x86_64-pc-windows-msvc'
}

const here = dirname(fileURLToPath(import.meta.url))
const desktop = resolve(here, '..')
const repo = resolve(desktop, '..')
const out = join(desktop, 'build', 'runtime')
const cache = join(desktop, 'build', 'cache')

const arg = (name) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? process.argv[i + 1] : undefined
}
const platform = arg('platform') ?? process.platform
const arch = arg('arch') ?? process.arch
const key = `${platform}-${arch}`
const triple = TRIPLES[key]
if (!triple) throw new Error(`Unsupported target ${key}. Supported: ${Object.keys(TRIPLES).join(', ')}`)
if (platform !== process.platform || arch !== process.arch) {
  throw new Error(`Cross-bundling is not supported: run this on ${key} (host is ${process.platform}-${process.arch}). Use a CI matrix to build each OS.`)
}

assetFor(readLock(), key) // fail now, not after the slow steps, if llama.cpp is not pinned for this platform

const asset = `cpython-${PY_VERSION}+${PBS_TAG}-${triple}-install_only_stripped.tar.gz`
const base = `https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}`

const download = downloadFile

const sha256 = (file) => createHash('sha256').update(readFileSync(file)).digest('hex')

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts })
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(' ')} failed (${r.status ?? r.error})`)
}

mkdirSync(cache, { recursive: true })
const archive = join(cache, asset)
if (!existsSync(archive)) {
  console.log(`Downloading ${asset}`)
  await download(`${base}/${encodeURIComponent(asset).replace('%2B', '%2B')}`, archive)
}

// Verify against the release's published checksums.
const sums = join(cache, `SHA256SUMS-${PBS_TAG}`)
if (!existsSync(sums)) await download(`${base}/SHA256SUMS`, sums)
const expected = readFileSync(sums, 'utf8')
  .split('\n')
  .map((l) => l.trim().split(/\s+/))
  .find(([, name]) => name === asset)?.[0]
if (!expected) throw new Error(`No checksum published for ${asset}`)
if (sha256(archive) !== expected) {
  rmSync(archive)
  throw new Error(`Checksum mismatch for ${asset}; the cached download was removed. Re-run to fetch it again.`)
}

rmSync(out, { recursive: true, force: true })
mkdirSync(out, { recursive: true })
// Relative paths with cwd=desktop: GNU tar (Git for Windows) reads "C:\\..." as host:file and fails.
run('tar', ['-xzf', relative(desktop, archive).split(sep).join('/'), '-C', relative(desktop, out).split(sep).join('/')], { cwd: desktop }) // extracts to out/python
const python = platform === 'win32' ? join(out, 'python', 'python.exe') : join(out, 'python', 'bin', 'python3')

const site = join(out, 'site')
console.log('Installing the agent runtime and its dependencies')
run(python, ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-compile', '--target', site, join(repo, 'AgentRuntime')], {
  env: { ...process.env, PIP_REQUIRE_VIRTUALENV: '0' }
})

// Trim what a shipped app never needs.
const prune = (dir) => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (!statSync(p).isDirectory()) continue
    if (name === '__pycache__') rmSync(p, { recursive: true, force: true })
    else prune(p)
  }
}
rmSync(join(site, 'bin'), { recursive: true, force: true })
prune(site)

mkdirSync(join(out, 'Resources'), { recursive: true })
cpSync(join(repo, 'Resources', 'default-models.json'), join(out, 'Resources', 'default-models.json'))

// Smoke test: the bundled interpreter can import the runtime.
// (On Windows the runtime adds site/win32 and site/win32/lib too: see resolveLaunch.)
run(python, ['-I', '-c', 'import sys; sys.path[:0] = sys.argv[1:]; import anvil_agent.main, mcp; print("runtime import ok")', site, join(site, 'win32'), join(site, 'win32', 'lib')])
await bundleLlama({ out, cache, platform, arch })
console.log(`Runtime bundled at ${out}`)
