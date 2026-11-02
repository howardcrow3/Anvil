"""Fallback installer for the agent-browser / agent-desktop CLIs.

Packaged builds and checkouts that ran ``Scripts/fetch-agent-tools.mjs`` already contain the binaries. When they
are missing (a plain dev checkout, say), ``install_tools`` pulls the pinned npm tarballs into ``~/.anvil/tools``
using ``npm pack`` (no scripts run), verifies agent-desktop's published sha256, and copies the platform binary
into ``~/.anvil/tools/bin``. ``install_browser`` runs ``agent-browser install`` to fetch Chrome for Testing.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from anvil_agent.tools.external_cli import clean_env, find_binary, run_cli

# DonSeTch release assets (AGPL-3.0, https://github.com/dondai44423/donsetch). Keep in sync with
# Scripts/fetch-agent-tools.mjs (a test enforces it).
DONSETCH_VERSION = "4.10.4"
PINNED_DONSETCH = {
    "linux-x64": "793b033b5c9ff62cbe60cfbf4de14bbd3d4217d46a4956684b29263b31640bfa",
    "linux-arm64": "3c1ddfb9cb3be01942526c900c1b407a4c4f47c724190e62500e92251a4fd7c1",
    "darwin-arm64": "8889c9a65ee70a33f106634446b58a792a7349248d07b84758351ab942737791",
    "darwin-x64": "6a4e1780569cc0919c428f194ce4bb18246cf8e97fb0df9b68f2ad8663474a60",
    "win32-x64": "7e0ce0c4905d875e4be298a286023ed7f65a3ca4ba23c8b0a1b073097b786b06",
}

PINNED = {"agent-browser": "0.27.0", "agent-desktop": "1.0.2"}


def platform_key() -> str:
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    os_name = {"darwin": "darwin", "linux": "linux", "win32": "win32"}.get(sys.platform)
    if not arch or not os_name:
        raise RuntimeError(f"unsupported platform: {sys.platform}/{platform.machine()}")
    return f"{os_name}-{arch}"


def plan(tool: str, key: str) -> list[tuple[str, str]]:
    """(file inside the npm package's bin/, installed name) pairs; mirrors Scripts/fetch-agent-tools.mjs."""
    exe = ".exe" if key.startswith("win32") else ""
    if tool == "agent-browser":
        return [(f"agent-browser-{key}{exe}", f"agent-browser{exe}")]
    out = [(f"agent-desktop-{key}{exe}", f"agent-desktop{exe}")]
    if key.startswith("darwin"):
        out.append((f"agent-desktop-macos-helper-{key}", "agent-desktop-macos-helper"))
    if key.startswith("linux"):
        out.append((f"agent-desktop-linux-clipboard-owner-{key}", "agent-desktop-linux-clipboard-owner"))
    return out


def _safe_extract(tgz: Path, dest: Path) -> None:
    with tarfile.open(tgz) as tf:
        for m in tf.getmembers():
            target = (dest / m.name).resolve()
            if not str(target).startswith(str(dest.resolve())) or m.issym() or m.islnk():
                raise RuntimeError(f"unsafe path in archive: {m.name}")
        tf.extractall(dest)


async def install_tool(tool: str, dest_root: Path | None = None) -> dict[str, Any]:
    if tool not in PINNED:
        return {"ok": False, "error": f"unknown tool {tool}"}
    npm = shutil.which("npm", path=clean_env().get("PATH"))
    if not npm:
        return {"ok": False, "error": "npm not found; install Node.js or run Scripts/fetch-agent-tools.mjs"}
    try:
        key = platform_key()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    bin_dir = (dest_root or Path.home() / ".anvil" / "tools") / "bin"
    with tempfile.TemporaryDirectory(prefix="anvil-tool-") as tmp:
        work = Path(tmp)
        res = await run_cli(
            npm, ["pack", f"{tool}@{PINNED[tool]}", "--silent", "--ignore-scripts", "--pack-destination", str(work)],
            timeout=300, max_chars=4000,
        )
        if res.code != 0:
            return {"ok": False, "error": f"npm pack failed: {(res.stderr or res.stdout).strip()[:500]}"}
        tgzs = list(work.glob("*.tgz"))
        if not tgzs:
            return {"ok": False, "error": "npm pack produced no tarball"}
        _safe_extract(tgzs[0], work / "x")
        pkg_bin = work / "x" / "package" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        installed = []
        for src, dest in plan(tool, key):
            f = pkg_bin / src
            if not f.is_file():
                return {"ok": False, "error": f"{src} missing from package"}
            sha = pkg_bin / (src + ".sha256")
            if sha.is_file():
                want = sha.read_text().split()[0]
                if hashlib.sha256(f.read_bytes()).hexdigest() != want:
                    return {"ok": False, "error": f"checksum mismatch for {src}"}
            out = bin_dir / dest
            shutil.copyfile(f, out)
            out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            installed.append(str(out))
    return {"ok": True, "tool": tool, "version": PINNED[tool], "installed": installed}


async def install_browser(path_override: str | None = None) -> dict[str, Any]:
    """Download Chrome for Testing via ``agent-browser install`` (~150 MB; skipped if a system Chrome is configured)."""
    binary = find_binary("agent-browser", path_override)
    if not binary:
        return {"ok": False, "error": "agent-browser is not installed"}
    res = await run_cli(binary, ["install"], timeout=900, max_chars=8000)
    return {"ok": res.code == 0, "output": (res.stdout + res.stderr).strip()[-1500:]}


async def install_donsetch(dest_root: Path | None = None) -> dict[str, Any]:
    """Download the pinned DonSeTch release tarball, verify its pinned SHA-256, install into ``<root>/bin``."""
    import httpx

    try:
        key = platform_key()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    if key == "win32-arm64":
        key = "win32-x64"  # runs under emulation
    want = PINNED_DONSETCH.get(key)
    if not want:
        return {"ok": False, "error": f"no DonSeTch build for {key}"}
    asset = f"donsetch-{key}.tar.gz"
    url = f"https://github.com/dondai44423/donsetch/releases/download/v{DONSETCH_VERSION}/{asset}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"download failed: {e}"}
    if hashlib.sha256(resp.content).hexdigest() != want:
        return {"ok": False, "error": f"checksum mismatch for {asset}"}
    name = "donsetch.exe" if key.startswith("win32") else "donsetch"
    bin_dir = (dest_root or Path.home() / ".anvil" / "tools") / "bin"
    with tempfile.TemporaryDirectory(prefix="anvil-donsetch-") as tmp:
        tgz = Path(tmp) / asset
        tgz.write_bytes(resp.content)
        _safe_extract(tgz, Path(tmp) / "x")
        src = Path(tmp) / "x" / name
        if not src.is_file():
            return {"ok": False, "error": f"{name} missing from archive"}
        bin_dir.mkdir(parents=True, exist_ok=True)
        out = bin_dir / name
        shutil.copyfile(src, out)
        out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"ok": True, "tool": "donsetch", "version": DONSETCH_VERSION, "installed": [str(out)]}
