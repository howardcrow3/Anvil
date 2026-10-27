#!/usr/bin/env node
// Pins the latest official llama.cpp release in Resources/llama-cpp.lock.json (run by the scheduled workflow, or by hand).
//   node scripts/update-llama-cpp.mjs            update the lock if a newer release exists
//   node scripts/update-llama-cpp.mjs --check    only report (exit 0 = current, 10 = newer release available)
//   node scripts/update-llama-cpp.mjs --tag b1234  pin a specific release
// Prints a one-line JSON summary on stdout; GITHUB_TOKEN (optional) raises the API rate limit.
import { createHash } from 'node:crypto'
import { REPO, LOCK_PATH, pickAssets, readLock, writeLock } from './llama-cpp-lib.mjs'

const arg = (name) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? process.argv[i + 1] : undefined
}
const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'anvil-llama-cpp-updater', ...(process.env.GITHUB_TOKEN ? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}) }

const tag = arg('tag')
const url = `https://api.github.com/repos/${REPO}/releases/${tag ? `tags/${tag}` : 'latest'}`
const res = await fetch(url, { headers })
if (!res.ok) throw new Error(`GET ${url} failed: ${res.status} ${await res.text()}`)
const release = await res.json()

const { lock, missing } = pickAssets(release)
if (missing.length) {
  console.error(`llama.cpp ${lock.tag} has no usable asset for: ${missing.join(', ')}. Not adopting it; adjust TARGETS in scripts/llama-cpp-lib.mjs if the asset naming changed.`)
  process.exit(2)
}

// Older releases carry no digest: hash the download ourselves so every entry is pinned to content.
for (const [key, a] of Object.entries(lock.assets)) {
  if (a.sha256) continue
  console.error(`No published digest for ${a.name}; hashing the download`)
  const r = await fetch(a.url, { redirect: 'follow' })
  if (!r.ok) throw new Error(`download of ${a.name} failed: ${r.status}`)
  lock.assets[key].sha256 = createHash('sha256').update(Buffer.from(await r.arrayBuffer())).digest('hex')
}

let current = null
try {
  current = readLock().tag ?? null
} catch {
  /* no lock yet */
}
const changed = current !== lock.tag
if (process.argv.includes('--check')) {
  console.log(JSON.stringify({ current, latest: lock.tag, changed }))
  process.exit(changed ? 10 : 0)
}
if (changed) writeLock(lock)
console.log(JSON.stringify({ previous: current, tag: lock.tag, changed, lock: LOCK_PATH }))
