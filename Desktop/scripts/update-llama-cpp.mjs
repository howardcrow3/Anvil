#!/usr/bin/env node
// Pins the latest official llama.cpp release in Resources/llama-cpp.lock.json (run by the scheduled workflow, or by hand).
//   node scripts/update-llama-cpp.mjs            update the lock if a newer release exists
//   node scripts/update-llama-cpp.mjs --check    only report (exit 0 = current, 10 = newer release available)
//   node scripts/update-llama-cpp.mjs --tag b1234  pin a specific release
// Prints a one-line JSON summary on stdout; GITHUB_TOKEN (optional) raises the API rate limit.
import { createHash } from 'node:crypto'
import { REPO, LOCK_PATH, chooseRelease, pickAssets, readLock, writeLock } from './llama-cpp-lib.mjs'

const arg = (name) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? process.argv[i + 1] : undefined
}
const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'anvil-llama-cpp-updater', ...(process.env.GITHUB_TOKEN ? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}) }

const tag = arg('tag')
const api = async (path) => {
  const res = await fetch(`https://api.github.com/repos/${REPO}/${path}`, { headers })
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${await res.text()}`)
  return res.json()
}
// "releases/latest" can point at a release with no binaries, so pick the newest one that has them all.
const chosen = tag ? { ...pickAssets(await api(`releases/tags/${tag}`)), skipped: [] } : chooseRelease(await api('releases?per_page=40'))
const { lock, missing } = chosen
if (!lock || missing.length) {
  console.error(`No usable llama.cpp release${tag ? ` ${tag}` : ''}: missing ${missing.join(', ')}. Not adopting anything; adjust TARGETS in scripts/llama-cpp-lib.mjs if the asset naming changed.`)
  if (chosen.skipped.length) console.error(`Checked: ${chosen.skipped.join('; ')}`)
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
