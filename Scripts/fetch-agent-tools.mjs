#!/usr/bin/env node
// Bundle Vercel Labs' agent-browser and agent-desktop (Apache-2.0) into Resources/agent-tools/
// so they ship inside Anvil. Mirrors Scripts/download-ollama.sh: build-time download, gitignored output.
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
const OUT = join(ROOT, 'Resources', 'agent-tools')
const VERSIONS = {
  'agent-browser': process.env.AGENT_BROWSER_VERSION || '0.27.0',
  'agent-desktop': process.env.AGENT_DESKTOP_VERSION || '1.0.2'
}

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
  writeFileSync(join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
  console.log(`\nBundled to ${OUT}`)
} finally {
  rmSync(work, { recursive: true, force: true })
}
