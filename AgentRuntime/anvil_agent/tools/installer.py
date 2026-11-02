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
