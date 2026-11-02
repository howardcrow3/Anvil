#!/usr/bin/env node
// Bundle Vercel Labs' agent-browser and agent-desktop (Apache-2.0) and DonSeTch (AGPL-3.0, run as a separate
// MCP server process) into Resources/agent-tools/ so they ship inside Anvil. Mirrors Scripts/download-ollama.sh: build-time download, gitignored output.
//
//   node Scripts/fetch-agent-tools.mjs [--platform darwin-arm64|darwin-x64|linux-x64|linux-arm64|win32-x64|win32-arm64]
//
// Output: Resources/agent-tools/bin/{agent-browser,agent-desktop,<helpers>}  (+ .exe on Windows)
//         Resources/agent-tools/licenses/
// Env: AGENT_BROWSER_VERSION / AGENT_DESKTOP_VERSION override the pinned versions.
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const OUT = process.env.ANVIL_AGENT_TOOLS_OUT || join(ROOT, 'Resources', 'agent-tools')
const VERSIONS = {
  'agent-browser': process.env.AGENT_BROWSER_VERSION || '0.27.0',
  'agent-desktop': process.env.AGENT_DESKTOP_VERSION || '1.0.2'
}

// DonSeTch ships as GitHub release tarballs. SHA-256 values are pinned here (from the v4.10.4 release) so a later
// swap of the release asset is detected. Keep in sync with PINNED_DONSETCH in AgentRuntime/anvil_agent/tools/installer.py.
const DONSETCH = {
  version: process.env.DONSETCH_VERSION || '4.10.4',
  sha256: {
    'linux-x64': '793b033b5c9ff62cbe60cfbf4de14bbd3d4217d46a4956684b29263b31640bfa',
    'linux-arm64': '3c1ddfb9cb3be01942526c900c1b407a4c4f47c724190e62500e92251a4fd7c1',
    'darwin-arm64': '8889c9a65ee70a33f106634446b58a792a7349248d07b84758351ab942737791',
    'darwin-x64': '6a4e1780569cc0919c428f194ce4bb18246cf8e97fb0df9b68f2ad8663474a60',
    'win32-x64': '7e0ce0c4905d875e4be298a286023ed7f65a3ca4ba23c8b0a1b073097b786b06'
  }
}
const DONSETCH_REPO = 'dondai44423/donsetch'

const argIdx = process.argv.indexOf('--platform')
const platform = argIdx > 0 ? process.argv[argIdx + 1] : `${process.platform}-${process.arch}`
const win = platform.startsWith('win32')
const exe = win ? '.exe' : ''

// package binary name -> installed name beside it. Helpers must sit next to agent-desktop.
const PLAN = {
  'agent-browser': [[`agent-browser-${platform}${exe}`, `agent-browser${exe}`]],
  'agent-desktop': [
    [`agent-desktop-${platform}${exe}`, `agent-desktop${exe}`],
    ...(platform.startsWith('darwin') ? [[`agent-desktop-macos-helper-${platform}`, 'agent-desktop-macos-helper']] : []),
    ...(platform.startsWith('linux') ? [[`agent-desktop-linux-clipboard-owner-${platform}`, 'agent-desktop-linux-clipboard-owner']] : [])
  ]
}
if (!/^(darwin|linux|win32)-(x64|arm64)$/.test(platform)) {
  console.error(`Unsupported platform: ${platform}`)
  process.exit(2)
}

async function bundleDonsetch(manifest) {
  // win32-arm64 runs the x64 build under emulation (same as DonSeTch's own installer).
  const key = platform === 'win32-arm64' ? 'win32-x64' : platform
  const want = DONSETCH.sha256[key]
  if (!want) throw new Error(`donsetch: no pinned checksum for ${key}`)
  const tag = `v${DONSETCH.version}`
  const asset = `donsetch-${key}.tar.gz`
  console.log(`=== donsetch@${DONSETCH.version} (${key}) ===`)
  // curl (not Node's fetch) so HTTP(S)_PROXY settings are honoured; ships with macOS, Linux and Windows 10+.
  const get = async (url) => execFileSync('curl', ['-fsSL', '--retry', '3', url], { maxBuffer: 256 * 1024 * 1024 })
  const tarball = await get(`https://github.com/${DONSETCH_REPO}/releases/download/${tag}/${asset}`)
  const got = createHash('sha256').update(tarball).digest('hex')
  if (got !== want) throw new Error(`donsetch: checksum mismatch for ${asset} (expected ${want}, got ${got})`)
  console.log(`  sha256 ok  ${asset}`)
  const dir = join(work, 'donsetch')
  mkdirSync(dir)
  writeFileSync(join(dir, asset), tarball)
  execFileSync('tar', ['xzf', asset], { cwd: dir })
  const name = `donsetch${exe}`
  const to = join(OUT, 'bin', name)
  copyFileSync(join(dir, name), to)
  if (!win) chmodSync(to, 0o755)
  console.log(`  -> bin/${name}`)
  const license = (await get(`https://raw.githubusercontent.com/${DONSETCH_REPO}/${tag}/LICENSE`)).toString('utf8')
  writeFileSync(
    join(OUT, 'licenses', 'donsetch.txt'),
    `DonSeTch ${DONSETCH.version} is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-only).\n` +
      `Copyright Bishesh Bhandari. Anvil runs it as a separate program (an MCP server over stdio) and does not modify it.\n` +
      `Corresponding source: https://github.com/${DONSETCH_REPO}/tree/${tag}\n\n${license}`
  )
  manifest.tools.donsetch = { version: DONSETCH.version, license: 'AGPL-3.0-only' }
}

const sha256 = (p) => createHash('sha256').update(readFileSync(p)).digest('hex')
const work = mkdtempSync(join(tmpdir(), 'anvil-agent-tools-'))
try {
  rmSync(OUT, { recursive: true, force: true })
  mkdirSync(join(OUT, 'bin'), { recursive: true })
  mkdirSync(join(OUT, 'licenses'), { recursive: true })
  const manifest = { platform, tools: {} }

  for (const [pkg, files] of Object.entries(PLAN)) {
    const version = VERSIONS[pkg]
    console.log(`=== ${pkg}@${version} (${platform}) ===`)
    const dir = join(work, pkg)
    mkdirSync(dir)
    const tgz = execFileSync('npm', ['pack', `${pkg}@${version}`, '--silent'], { cwd: dir, shell: win, encoding: 'utf8' }).trim().split('\n').pop()
    execFileSync('tar', ['xzf', tgz], { cwd: dir })
    const pkgDir = join(dir, 'package')
    const license = JSON.parse(readFileSync(join(pkgDir, 'package.json'), 'utf8')).license
    if (license !== 'Apache-2.0') throw new Error(`${pkg}: unexpected license ${license}`)

    for (const [src, dest] of files) {
      const from = join(pkgDir, 'bin', src)
      if (!existsSync(from)) throw new Error(`${pkg}: ${src} not found in package`)
      const shaFile = `${from}.sha256`
      if (existsSync(shaFile)) {
        const want = readFileSync(shaFile, 'utf8').trim().split(/\s+/)[0]
        if (sha256(from) !== want) throw new Error(`${pkg}: checksum mismatch for ${src}`)
        console.log(`  sha256 ok  ${src}`)
      }
      const to = join(OUT, 'bin', dest)
      copyFileSync(from, to)
      if (!win) chmodSync(to, 0o755)
      console.log(`  -> bin/${dest}`)
    }
    // Apache-2.0 §4: ship the license (and NOTICE if present) with redistributed binaries.
    const lic = join(pkgDir, 'LICENSE')
    writeFileSync(
      join(OUT, 'licenses', `${pkg}.txt`),
      (existsSync(lic) ? readFileSync(lic, 'utf8') : `${pkg} is licensed under the Apache License 2.0.\nSource: https://github.com/vercel-labs/${pkg}\nLicense text: https://www.apache.org/licenses/LICENSE-2.0\n`)
    )
    manifest.tools[pkg] = { version, license }
  }
  await bundleDonsetch(manifest)
  writeFileSync(join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
  console.log(`\nBundled to ${OUT}`)
} finally {
  rmSync(work, { recursive: true, force: true })
}
