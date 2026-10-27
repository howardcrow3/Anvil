// Shared by bundle-llama.mjs (installers) and update-llama-cpp.mjs (the scheduled bump).
// The pinned llama.cpp release lives in Resources/llama-cpp.lock.json:
//   { "repo": "ggml-org/llama.cpp", "tag": "bNNNN", "assets": { "<platform>-<arch>": { "name", "url", "sha256" } } }
import { createWriteStream, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const REPO = 'ggml-org/llama.cpp'
export const LOCK_PATH = process.env.ANVIL_LLAMA_LOCK ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'Resources', 'llama-cpp.lock.json')

const ARCHIVE = '\\.(zip|tar\\.gz)$'
const asset = (middle) => new RegExp(`^llama-b\\d+-bin-${middle}${ARCHIVE}`)

/** Which release asset serves each platform: the first matching pattern wins. CPU builds (plus Metal on macOS). */
export const TARGETS = {
  'darwin-arm64': [asset('macos-arm64')],
  'darwin-x64': [asset('macos-x64')],
  'linux-x64': [asset('ubuntu-x64')],
  'linux-arm64': [asset('ubuntu-arm64')],
  'win32-x64': [asset('win-cpu-x64'), asset('win-avx2-x64')]
}

/** Platforms the installer matrix builds: a release missing one of these must not be adopted. */
export const REQUIRED = ['darwin-arm64', 'darwin-x64', 'linux-x64', 'win32-x64']

const sha256Of = (digest) => (typeof digest === 'string' && /^sha256:[0-9a-f]{64}$/.test(digest) ? digest.slice(7) : null)

/** From a GitHub release object to lock-file content. `sha256` is null when GitHub published no digest. */
export function pickAssets(release) {
  const assets = {}
  for (const [key, patterns] of Object.entries(TARGETS)) {
    for (const re of patterns) {
      const a = (release.assets ?? []).find((x) => re.test(x.name))
      if (a) {
        assets[key] = { name: a.name, url: a.browser_download_url, sha256: sha256Of(a.digest) }
        break
      }
    }
  }
  const missing = REQUIRED.filter((k) => !assets[k])
  return { lock: { repo: REPO, tag: release.tag_name, assets }, missing }
}

export function readLock(path = LOCK_PATH) {
  return JSON.parse(readFileSync(path, 'utf8'))
}

export function writeLock(lock, path = LOCK_PATH) {
  writeFileSync(path, JSON.stringify(lock, null, 2) + '\n')
}

/** The lock entry for a platform, or an error saying exactly what to do. */
export function assetFor(lock, key) {
  if (!lock?.tag) {
    throw new Error('Resources/llama-cpp.lock.json has no llama.cpp release pinned yet. Run the "Update llama.cpp" workflow, or: node Desktop/scripts/update-llama-cpp.mjs')
  }
  const a = lock.assets?.[key]
  if (!a) throw new Error(`llama.cpp ${lock.tag} has no build for ${key} in the lock file (known: ${Object.keys(lock.assets ?? {}).join(', ')})`)
  if (!a.sha256) throw new Error(`The lock entry for ${key} has no sha256; refusing to bundle an unverified download`)
  return a
}

export const llamaDir = (runtimeOut) => join(runtimeOut, 'llama')

/**
 * The newest release that actually ships every platform we need. GitHub's "latest" release is not reliable
 * here (the repo also publishes non-build releases, e.g. one that only carries nightly-tag.txt), so walk the
 * list, newest first, and take the first usable one.
 */
export function chooseRelease(releases) {
  const skipped = []
  for (const release of releases) {
    if (release.draft) continue // llama.cpp publishes every build (bNNNN) as a prerelease, so those count
    const picked = pickAssets(release)
    if (!picked.missing.length) return { ...picked, skipped }
    skipped.push(`${release.tag_name} (no ${picked.missing.join(', ')})`)
  }
  return { lock: null, missing: REQUIRED, skipped }
}

/** Download `url` to `dest`, retrying dropped connections and 5xx/429 (CI runners lose sockets now and then). */
export async function downloadFile(url, dest, { attempts = 4, delayMs = 2000 } = {}) {
  let last
  for (let i = 1; i <= attempts; i++) {
    const part = `${dest}.part`
    try {
      const res = await fetch(url, { redirect: 'follow' })
      if (!res.ok || !res.body) {
        const err = new Error(`Download failed (${res.status}) for ${url}`)
        err.retryable = res.status >= 500 || res.status === 429
        throw err
      }
      await pipeline(Readable.fromWeb(res.body), createWriteStream(part))
      renameSync(part, dest)
      return
    } catch (err) {
      last = err
      rmSync(part, { force: true })
      if (err.retryable === false || i === attempts) break
      console.warn(`Download attempt ${i}/${attempts} failed (${err.cause?.code ?? err.message}); retrying`)
      await new Promise((r) => setTimeout(r, delayMs * i))
    }
  }
  throw last
}
