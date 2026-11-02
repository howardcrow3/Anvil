"""Run an external agent-oriented CLI safely: no shell, minimal environment, timeout, output cap.

Used by the browser and desktop tools, which wrap Vercel Labs' ``agent-browser`` and ``agent-desktop``
(both Apache-2.0, https://github.com/vercel-labs). Anvil ships them unmodified (Scripts/fetch-agent-tools.mjs
bundles them into Resources/agent-tools/; tools/installer.py is the fallback) and simply invokes the binary.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_BASE_ENV = (
    "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "USER", "LOGNAME", "SHELL",
    "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME", "XDG_DATA_HOME", "DBUS_SESSION_BUS_ADDRESS",
    "SystemRoot", "SYSTEMROOT", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PATHEXT", "COMSPEC",
)


def extra_search_dirs() -> list[str]:
    """GUI apps on macOS start with a minimal PATH, so look in the usual npm/brew/cargo locations too."""
    home = Path.home()
    dirs = [
        home / ".anvil" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin"), home / ".npm-global" / "bin",
        home / ".local" / "bin", home / ".cargo" / "bin", home / ".bun" / "bin", home / "node_modules" / ".bin",
    ]
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            dirs.append(Path(appdata) / "npm")
    return [str(d) for d in dirs]


def bundled_dirs() -> list[Path]:
    """Where Anvil's own copy of the tools lives, in priority order.

    ANVIL_TOOLS_DIR is set by the Electron shell to <app resources>/agent-tools/bin in a packaged build; in a
    checkout the build script writes Resources/agent-tools/bin; the installer fallback uses ~/.anvil/tools/bin.
    """
    dirs: list[Path] = []
    env = os.environ.get("ANVIL_TOOLS_DIR")
    if env:
        dirs.append(Path(env))
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    dirs.append(project_root / "Resources" / "agent-tools" / "bin")
    dirs.append(Path.home() / ".anvil" / "tools" / "bin")
    return dirs


def _is_exec(p: Path) -> bool:
    return p.is_file() and os.access(p, os.X_OK)


def find_binary(name: str, override: str | None = None) -> str | None:
    if override:
        p = Path(override).expanduser()
        return str(p) if _is_exec(p) else None
    exe = name + (".exe" if sys.platform == "win32" else "")
    for d in bundled_dirs():
        if _is_exec(d / exe):
            return str(d / exe)
    search = os.pathsep.join([os.environ.get("PATH", ""), *extra_search_dirs()])
    return shutil.which(name, path=search)


@dataclass
class CLIResult:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: os.environ[k] for k in _BASE_ENV if k in os.environ}
    env["PATH"] = os.pathsep.join([env.get("PATH", ""), *extra_search_dirs()])
    env.update(extra or {})
    return env


async def run_cli(
    binary: str,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 60.0,
    max_chars: int = 60_000,
) -> CLIResult:
    proc = await asyncio.create_subprocess_exec(
        binary, *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=clean_env(env),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await asyncio.wait_for(proc.communicate(), 3)
        except Exception:  # noqa: BLE001
            pass
        return CLIResult(-1, "", f"timed out after {timeout:.0f}s", timed_out=True)
    except asyncio.CancelledError:
        proc.kill()
        raise
    text = out.decode("utf-8", "replace")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + f"\n… [truncated {len(text) - max_chars} chars]"
    return CLIResult(proc.returncode or 0, text, err.decode("utf-8", "replace")[:4000], truncated=truncated)


def safe_token(value: object, what: str, *, allow_leading_dash: bool = False) -> str:
    """Reject values a CLI could mistake for a flag or that contain control characters."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} is required")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{what} contains control characters")
    if value.startswith("-") and not allow_leading_dash:
        raise ValueError(f"{what} must not start with '-' (it could be read as a command-line flag)")
    return value
