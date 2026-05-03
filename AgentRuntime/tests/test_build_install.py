"""Tests for app bundle structure, DMG packaging, and install integrity.

These tests validate the build artifacts without actually building them — they
check the already-built app bundle at build/Anvil.app and the DMG if present.
Run Scripts/build-app.sh and Scripts/package-dmg.sh first.

To run just these tests:
    python3 -m pytest tests/test_build_install.py -v
"""

from __future__ import annotations

import importlib
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

# Locate project root (two levels up from this test file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
APP_BUNDLE = PROJECT_ROOT / "build" / "Anvil.app"
RUNTIME_DIR = APP_BUNDLE / "Contents" / "Resources" / "AgentRuntime"
SITE_PKG = RUNTIME_DIR / "site-packages"


def app_bundle_exists() -> bool:
    return APP_BUNDLE.is_dir()


def dmg_exists() -> Path | None:
    dmgs = sorted(PROJECT_ROOT.glob("build/Anvil-*.dmg"))
    return dmgs[0] if dmgs else None


needs_bundle = pytest.mark.skipif(
    not app_bundle_exists(),
    reason="App bundle not built (run Scripts/build-app.sh first)",
)

needs_dmg = pytest.mark.skipif(
    dmg_exists() is None,
    reason="DMG not built (run Scripts/package-dmg.sh first)",
)


# ── App Bundle Structure ─────────────────────────────────────────


@needs_bundle
class TestAppBundleStructure:
    """Validate the .app bundle has all required files and directories."""

    def test_info_plist_exists(self):
        assert (APP_BUNDLE / "Contents" / "Info.plist").is_file()

    def test_info_plist_valid(self):
        plist_path = APP_BUNDLE / "Contents" / "Info.plist"
        with open(plist_path, "rb") as f:
            plist = plistlib.load(f)
        assert plist["CFBundleExecutable"] == "Anvil"
        assert plist["CFBundleIdentifier"] == "com.anvil.app"
        assert "CFBundleShortVersionString" in plist

    def test_binary_exists(self):
        binary = APP_BUNDLE / "Contents" / "MacOS" / "Anvil"
        assert binary.is_file()
        assert os.access(binary, os.X_OK), "Binary is not executable"

    def test_binary_is_macho(self):
        binary = APP_BUNDLE / "Contents" / "MacOS" / "Anvil"
        result = subprocess.run(
            ["file", str(binary)], capture_output=True, text=True
        )
        assert "Mach-O" in result.stdout

    def test_binary_size_reasonable(self):
        binary = APP_BUNDLE / "Contents" / "MacOS" / "Anvil"
        size = binary.stat().st_size
        assert size > 1_000_000, f"Binary too small: {size} bytes"
        assert size < 100_000_000, f"Binary too large: {size} bytes"

    def test_ollama_dir_exists(self):
        assert (APP_BUNDLE / "Contents" / "Resources" / "ollama").is_dir()

    def test_default_models_json(self):
        assert (APP_BUNDLE / "Contents" / "Resources" / "default-models.json").is_file()

    def test_sparkle_framework_bundled(self):
        sparkle = (
            APP_BUNDLE / "Contents" / "Frameworks" / "Sparkle.framework"
            / "Versions" / "B" / "Sparkle"
        )
        assert sparkle.is_file(), "Sparkle.framework not bundled"

    def test_sparkle_rpath_set(self):
        binary = APP_BUNDLE / "Contents" / "MacOS" / "Anvil"
        result = subprocess.run(
            ["otool", "-l", str(binary)], capture_output=True, text=True
        )
        assert "@loader_path/../Frameworks" in result.stdout, (
            "Missing @loader_path/../Frameworks rpath for Sparkle"
        )


# ── Python Agent Runtime ─────────────────────────────────────────


@needs_bundle
class TestAgentRuntimeBundle:
    """Validate the bundled Python agent runtime is complete."""

    def test_anvil_agent_package_exists(self):
        assert (RUNTIME_DIR / "anvil_agent" / "__init__.py").is_file()

    def test_main_module_exists(self):
        assert (RUNTIME_DIR / "anvil_agent" / "main.py").is_file()

    def test_agent_loop_exists(self):
        assert (RUNTIME_DIR / "anvil_agent" / "agent_loop.py").is_file()

    def test_requirements_txt_bundled(self):
        assert (RUNTIME_DIR / "requirements.txt").is_file()

    @pytest.mark.parametrize(
        "subpath",
        [
            "anvil_agent/gateway/__init__.py",
            "anvil_agent/gateway/server.py",
            "anvil_agent/gateway/config.py",
            "anvil_agent/gateway/adapters/base.py",
            "anvil_agent/gateway/adapters/telegram.py",
            "anvil_agent/gateway/adapters/discord.py",
            "anvil_agent/gateway/adapters/slack.py",
            "anvil_agent/gateway/adapters/webhook.py",
        ],
    )
    def test_gateway_modules(self, subpath: str):
        assert (RUNTIME_DIR / subpath).is_file()

    @pytest.mark.parametrize(
        "subpath",
        [
            "anvil_agent/session/search.py",
            "anvil_agent/memory/nudger.py",
            "anvil_agent/memory/user_model.py",
            "anvil_agent/skills/creator.py",
            "anvil_agent/skills/improver.py",
            "anvil_agent/skills/hub.py",
        ],
    )
    def test_phase6_modules(self, subpath: str):
        assert (RUNTIME_DIR / subpath).is_file()

    @pytest.mark.parametrize(
        "subpath",
        [
            "anvil_agent/tools/__init__.py",
            "anvil_agent/tools/read_tool.py",
            "anvil_agent/tools/write_tool.py",
            "anvil_agent/tools/edit_tool.py",
            "anvil_agent/tools/bash_tool.py",
            "anvil_agent/tools/glob_tool.py",
            "anvil_agent/tools/grep_tool.py",
        ],
    )
    def test_core_tool_modules(self, subpath: str):
        assert (RUNTIME_DIR / subpath).is_file()


# ── Bundled Site-Packages ────────────────────────────────────────


@needs_bundle
class TestBundledDependencies:
    """Validate Python dependencies are bundled in site-packages."""

    def test_site_packages_dir_exists(self):
        assert SITE_PKG.is_dir()

    @pytest.mark.parametrize(
        "package",
        [
            "aiosqlite",
            "aiohttp",
            "pydantic",
            "anthropic",
            "rich",
            "httpx",
        ],
    )
    def test_required_package_present(self, package: str):
        assert (SITE_PKG / package).is_dir(), f"{package} not in site-packages"

    def test_site_packages_not_empty(self):
        entries = list(SITE_PKG.iterdir())
        assert len(entries) > 10, f"Only {len(entries)} entries in site-packages"


# ── Python Import Smoke Tests ────────────────────────────────────


@needs_bundle
class TestBundledImports:
    """Test that modules import correctly from the bundled location.

    These tests simulate what AgentRuntimeService.swift does: set PYTHONPATH
    to include the runtime dir and site-packages, then import modules.
    """

    @pytest.fixture(autouse=True)
    def _setup_path(self):
        """Temporarily prepend bundled paths to sys.path."""
        original = sys.path[:]
        sys.path.insert(0, str(RUNTIME_DIR))
        sys.path.insert(0, str(SITE_PKG))
        yield
        sys.path[:] = original
        # Clean up any imported modules from the bundle
        to_remove = [
            k
            for k in sys.modules
            if hasattr(sys.modules[k], "__file__")
            and sys.modules[k].__file__
            and str(RUNTIME_DIR) in str(sys.modules[k].__file__)
        ]
        for k in to_remove:
            del sys.modules[k]

    def test_import_anvil_agent(self):
        mod = importlib.import_module("anvil_agent")
        assert mod is not None

    def test_import_gateway_config(self):
        mod = importlib.import_module("anvil_agent.gateway.config")
        assert hasattr(mod, "GatewayConfig")

    def test_import_session_search(self):
        mod = importlib.import_module("anvil_agent.session.search")
        assert hasattr(mod, "SessionSearchDB")

    def test_import_memory_nudger(self):
        mod = importlib.import_module("anvil_agent.memory.nudger")
        assert hasattr(mod, "MemoryNudger")

    def test_import_skill_creator(self):
        mod = importlib.import_module("anvil_agent.skills.creator")
        assert hasattr(mod, "SkillCreator")

    def test_import_tools_registry(self):
        mod = importlib.import_module("anvil_agent.tools")
        assert hasattr(mod, "create_default_registry")

    def test_tool_schemas_generate(self):
        from anvil_agent.tools import create_default_registry

        reg = create_default_registry()
        schemas = reg.get_all_schemas()
        assert len(schemas) > 0, "No tool schemas generated"

    def test_gateway_config_instantiable(self):
        from anvil_agent.gateway.config import GatewayConfig

        config = GatewayConfig()
        assert config.telegram is None
        assert config.discord is None

    def test_session_search_db_instantiable(self):
        from anvil_agent.session.search import SessionSearchDB

        db = SessionSearchDB()
        assert db is not None


# ── DMG Structure ────────────────────────────────────────────────


@needs_dmg
class TestDMGStructure:
    """Validate the DMG file without mounting (basic checks)."""

    def test_dmg_file_exists(self):
        dmg = dmg_exists()
        assert dmg is not None and dmg.is_file()

    def test_dmg_size_reasonable(self):
        dmg = dmg_exists()
        assert dmg is not None
        size_mb = dmg.stat().st_size / (1024 * 1024)
        assert size_mb > 10, f"DMG too small: {size_mb:.1f}MB"
        assert size_mb < 1000, f"DMG too large: {size_mb:.1f}MB"

    def test_dmg_is_valid_image(self):
        dmg = dmg_exists()
        assert dmg is not None
        result = subprocess.run(
            ["hdiutil", "imageinfo", str(dmg)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"hdiutil imageinfo failed: {result.stderr}"
        assert "Format Description" in result.stdout

    def test_dmg_compressed_format(self):
        dmg = dmg_exists()
        assert dmg is not None
        result = subprocess.run(
            ["hdiutil", "imageinfo", str(dmg)],
            capture_output=True,
            text=True,
        )
        # Should be UDBZ (bzip2 compressed)
        assert "UDBZ" in result.stdout or "bzip2" in result.stdout.lower(), (
            "DMG should be UDBZ compressed"
        )


# ── DMG Mount & Install Simulation ──────────────────────────────


@needs_dmg
class TestDMGInstall:
    """Mount the DMG, verify contents, and simulate drag-to-install."""

    @pytest.fixture()
    def mounted_dmg(self, tmp_path):
        """Mount the DMG and yield the mount point, then clean up."""
        dmg = dmg_exists()
        assert dmg is not None

        # Detach any pre-existing Anvil volumes
        subprocess.run(
            ["hdiutil", "detach", "/Volumes/Anvil", "-quiet"],
            capture_output=True,
        )

        result = subprocess.run(
            [
                "hdiutil",
                "attach",
                "-nobrowse",
                "-noverify",
                "-noautoopen",
                str(dmg),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Failed to mount DMG: {result.stderr}"

        # Parse mount point
        mount_dir = None
        for line in result.stdout.splitlines():
            if "/Volumes/" in line:
                # Extract everything from /Volumes/ onwards
                idx = line.index("/Volumes/")
                mount_dir = line[idx:].strip()
                break

        assert mount_dir is not None, f"Could not find mount point in: {result.stdout}"
        assert Path(mount_dir).is_dir(), f"Mount dir not found: {mount_dir}"

        yield mount_dir

        # Cleanup
        subprocess.run(
            ["hdiutil", "detach", mount_dir, "-quiet"],
            capture_output=True,
        )

    def test_dmg_contains_app(self, mounted_dmg):
        assert (Path(mounted_dmg) / "Anvil.app").is_dir()

    def test_dmg_contains_applications_symlink(self, mounted_dmg):
        link = Path(mounted_dmg) / "Applications"
        assert link.is_symlink()
        assert os.readlink(str(link)) == "/Applications"

    def test_dmg_app_has_binary(self, mounted_dmg):
        binary = Path(mounted_dmg) / "Anvil.app" / "Contents" / "MacOS" / "Anvil"
        assert binary.is_file()

    def test_dmg_app_has_runtime(self, mounted_dmg):
        runtime = (
            Path(mounted_dmg)
            / "Anvil.app"
            / "Contents"
            / "Resources"
            / "AgentRuntime"
            / "anvil_agent"
        )
        assert runtime.is_dir()

    def test_dmg_app_has_site_packages(self, mounted_dmg):
        site_pkg = (
            Path(mounted_dmg)
            / "Anvil.app"
            / "Contents"
            / "Resources"
            / "AgentRuntime"
            / "site-packages"
        )
        assert site_pkg.is_dir()
        # Check key packages exist
        assert (site_pkg / "aiosqlite").is_dir()
        assert (site_pkg / "pydantic").is_dir()

    def test_simulate_drag_install(self, mounted_dmg, tmp_path):
        """Simulate the user dragging Anvil.app to Applications."""
        source = Path(mounted_dmg) / "Anvil.app"
        dest = tmp_path / "Anvil.app"

        result = subprocess.run(
            ["cp", "-r", str(source), str(dest)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Copy failed: {result.stderr}"
        assert dest.is_dir()
        assert (dest / "Contents" / "MacOS" / "Anvil").is_file()
        assert (
            dest / "Contents" / "Resources" / "AgentRuntime" / "anvil_agent"
        ).is_dir()
        assert (
            dest / "Contents" / "Resources" / "AgentRuntime" / "site-packages"
        ).is_dir()

        # Count files match
        src_count = sum(1 for _ in source.rglob("*") if _.is_file())
        dst_count = sum(1 for _ in dest.rglob("*") if _.is_file())
        assert src_count == dst_count, (
            f"File count mismatch: source={src_count}, dest={dst_count}"
        )

    def test_installed_python_imports(self, mounted_dmg, tmp_path):
        """Verify Python imports work from the simulated install location."""
        source = Path(mounted_dmg) / "Anvil.app"
        dest = tmp_path / "Anvil.app"
        subprocess.run(["cp", "-r", str(source), str(dest)], capture_output=True)

        runtime = dest / "Contents" / "Resources" / "AgentRuntime"
        site_pkg = runtime / "site-packages"

        # Run import test in a clean subprocess
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from anvil_agent.gateway.config import GatewayConfig; "
                    "from anvil_agent.session.search import SessionSearchDB; "
                    "from anvil_agent.tools import create_default_registry; "
                    "reg = create_default_registry(); "
                    "print(f'OK: {len(reg.get_all_schemas())} tools')"
                ),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": f"{runtime}:{site_pkg}",
            },
        )
        assert result.returncode == 0, (
            f"Import failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK:" in result.stdout
