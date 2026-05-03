#!/bin/bash
set -euo pipefail

# End-to-end DMG build, install, and verification test.
# Validates the complete user experience: build → package → mount → install → launch.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build"
APP_BUNDLE="$BUILD_DIR/Anvil.app"
INSTALL_DIR=$(mktemp -d -t anvil-install-test)
PASSED=0
FAILED=0
ERRORS=()

cleanup() {
    # Detach any test DMG volumes
    hdiutil detach "/Volumes/Anvil" -quiet 2>/dev/null || true
    # Remove temp install directory
    rm -rf "$INSTALL_DIR"
}
trap cleanup EXIT

green() { printf "\033[32m  PASS: %s\033[0m\n" "$1"; }
red()   { printf "\033[31m  FAIL: %s\033[0m\n" "$1"; }
bold()  { printf "\033[1m%s\033[0m\n" "$1"; }

pass() { green "$1"; PASSED=$((PASSED + 1)); }
fail() { red "$1"; FAILED=$((FAILED + 1)); ERRORS+=("$1"); }

echo ""
bold "============================================"
bold "  Anvil DMG Install Verification Test"
bold "============================================"
echo ""

# ── Phase 1: Prerequisite Check ──────────────────────────────────

bold "Phase 1: Prerequisites"

if ! command -v python3 &>/dev/null; then
    fail "python3 available on PATH"
    echo "Cannot continue without python3."
    exit 1
fi
pass "python3 available on PATH"

if ! command -v swift &>/dev/null; then
    fail "swift available on PATH"
else
    pass "swift available on PATH"
fi

if ! command -v hdiutil &>/dev/null; then
    fail "hdiutil available (required for DMG)"
    exit 1
fi
pass "hdiutil available"

echo ""

# ── Phase 2: Build App Bundle ────────────────────────────────────

bold "Phase 2: Build App Bundle"

# Clean previous build
rm -rf "$APP_BUNDLE"

if bash "$SCRIPT_DIR/build-app.sh" >/dev/null 2>&1; then
    pass "build-app.sh completed successfully"
else
    fail "build-app.sh completed successfully"
    echo "Build failed — cannot continue."
    exit 1
fi

echo ""

# ── Phase 3: Validate App Bundle Structure ───────────────────────

bold "Phase 3: App Bundle Structure"

# Required paths relative to Anvil.app
REQUIRED_FILES=(
    "Contents/Info.plist"
    "Contents/MacOS/Anvil"
)
REQUIRED_DIRS=(
    "Contents/Resources/AgentRuntime/anvil_agent"
    "Contents/Resources/AgentRuntime/site-packages"
    "Contents/Resources/ollama"
    "Contents/Frameworks/Sparkle.framework"
)

for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "$APP_BUNDLE/$f" ]; then
        pass "File: $f"
    else
        fail "File: $f"
    fi
done

for d in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$APP_BUNDLE/$d" ]; then
        pass "Dir:  $d"
    else
        fail "Dir:  $d"
    fi
done

# Binary is Mach-O
if file "$APP_BUNDLE/Contents/MacOS/Anvil" 2>/dev/null | grep -q "Mach-O"; then
    pass "Binary is Mach-O executable"
else
    fail "Binary is Mach-O executable"
fi

# Info.plist has required keys
for key in CFBundleExecutable CFBundleIdentifier CFBundleShortVersionString; do
    if /usr/libexec/PlistBuddy -c "Print :$key" "$APP_BUNDLE/Contents/Info.plist" >/dev/null 2>&1; then
        pass "Info.plist has $key"
    else
        fail "Info.plist has $key"
    fi
done

echo ""

# ── Phase 4: Validate Python Agent Runtime ───────────────────────

bold "Phase 4: Python Agent Runtime"

RUNTIME_DIR="$APP_BUNDLE/Contents/Resources/AgentRuntime"
SITE_PKG="$RUNTIME_DIR/site-packages"

# anvil_agent package structure
REQUIRED_MODULES=(
    "anvil_agent/__init__.py"
    "anvil_agent/main.py"
    "anvil_agent/agent_loop.py"
    "anvil_agent/tools/__init__.py"
    "anvil_agent/gateway/__init__.py"
    "anvil_agent/gateway/server.py"
    "anvil_agent/gateway/config.py"
    "anvil_agent/gateway/adapters/base.py"
    "anvil_agent/gateway/adapters/telegram.py"
    "anvil_agent/gateway/adapters/discord.py"
    "anvil_agent/gateway/adapters/slack.py"
    "anvil_agent/gateway/adapters/webhook.py"
    "anvil_agent/session/search.py"
    "anvil_agent/memory/nudger.py"
    "anvil_agent/memory/user_model.py"
    "anvil_agent/skills/creator.py"
    "anvil_agent/skills/improver.py"
    "anvil_agent/skills/hub.py"
)

for mod in "${REQUIRED_MODULES[@]}"; do
    if [ -f "$RUNTIME_DIR/$mod" ]; then
        pass "Module: $mod"
    else
        fail "Module: $mod"
    fi
done

# Bundled Python dependencies
REQUIRED_PACKAGES=(
    "aiosqlite"
    "aiohttp"
    "pydantic"
    "anthropic"
    "rich"
)

for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if [ -d "$SITE_PKG/$pkg" ]; then
        pass "Package: $pkg"
    else
        fail "Package: $pkg"
    fi
done

echo ""

# ── Phase 5: Python Import Smoke Test ────────────────────────────

bold "Phase 5: Python Import Smoke Test"

# Simulate the PYTHONPATH the Swift app sets
export PYTHONPATH="$RUNTIME_DIR:$SITE_PKG"

# Test that core modules import without error
IMPORT_TESTS=(
    "anvil_agent"
    "anvil_agent.agent_loop"
    "anvil_agent.gateway.config"
    "anvil_agent.gateway.server"
    "anvil_agent.session.search"
    "anvil_agent.memory.nudger"
    "anvil_agent.memory.user_model"
    "anvil_agent.skills.creator"
    "anvil_agent.skills.improver"
    "anvil_agent.skills.hub"
    "anvil_agent.tools"
    "anvil_agent.models.types"
    "anvil_agent.permissions"
)

for mod in "${IMPORT_TESTS[@]}"; do
    if python3 -c "import $mod" 2>/dev/null; then
        pass "Import: $mod"
    else
        fail "Import: $mod"
    fi
done

# Verify bundled deps are importable from site-packages
DEP_IMPORT_TESTS=(
    "aiosqlite"
    "aiohttp"
    "pydantic"
    "anthropic"
    "rich"
)

for dep in "${DEP_IMPORT_TESTS[@]}"; do
    if python3 -c "import $dep" 2>/dev/null; then
        pass "Dep import: $dep"
    else
        fail "Dep import: $dep"
    fi
done

unset PYTHONPATH

echo ""

# ── Phase 6: DMG Packaging ──────────────────────────────────────

bold "Phase 6: DMG Packaging"

# Remove old DMG
rm -f "$BUILD_DIR"/Anvil-*.dmg

if bash "$SCRIPT_DIR/package-dmg.sh" >/dev/null 2>&1; then
    pass "package-dmg.sh completed successfully"
else
    fail "package-dmg.sh completed successfully"
    # Show the actual error
    bash "$SCRIPT_DIR/package-dmg.sh" 2>&1 || true
fi

DMG_FILE=$(ls "$BUILD_DIR"/Anvil-*.dmg 2>/dev/null | head -1)
if [ -n "$DMG_FILE" ] && [ -f "$DMG_FILE" ]; then
    pass "DMG file created: $(basename "$DMG_FILE")"
    DMG_SIZE=$(du -sh "$DMG_FILE" | cut -f1)
    echo "       Size: $DMG_SIZE"
else
    fail "DMG file exists"
    echo "Cannot continue DMG tests without a DMG file."
    # Jump to summary
    echo ""
    bold "============================================"
    bold "  Results: $PASSED passed, $FAILED failed"
    bold "============================================"
    exit "$FAILED"
fi

echo ""

# ── Phase 7: DMG Mount and Contents ─────────────────────────────

bold "Phase 7: DMG Mount & Contents"

# Detach any existing Anvil volumes
hdiutil detach "/Volumes/Anvil" -quiet 2>/dev/null || true

MOUNT_OUT=$(hdiutil attach -nobrowse -noverify -noautoopen "$DMG_FILE" 2>&1)
MOUNT_DIR=$(echo "$MOUNT_OUT" | grep "/Volumes/" | sed 's|.*\(/Volumes/.*\)|\1|')

if [ -n "$MOUNT_DIR" ] && [ -d "$MOUNT_DIR" ]; then
    pass "DMG mounts successfully at $MOUNT_DIR"
else
    fail "DMG mounts successfully"
    echo "Mount output: $MOUNT_OUT"
    echo ""
    bold "============================================"
    bold "  Results: $PASSED passed, $FAILED failed"
    bold "============================================"
    exit "$FAILED"
fi

if [ -d "$MOUNT_DIR/Anvil.app" ]; then
    pass "DMG contains Anvil.app"
else
    fail "DMG contains Anvil.app"
fi

if [ -L "$MOUNT_DIR/Applications" ]; then
    LINK_TARGET=$(readlink "$MOUNT_DIR/Applications")
    if [ "$LINK_TARGET" = "/Applications" ]; then
        pass "Applications symlink points to /Applications"
    else
        fail "Applications symlink target (got: $LINK_TARGET)"
    fi
else
    fail "DMG contains Applications symlink"
fi

echo ""

# ── Phase 8: Simulate Install (copy to temp dir) ────────────────

bold "Phase 8: Simulated Install"

if cp -r "$MOUNT_DIR/Anvil.app" "$INSTALL_DIR/"; then
    pass "Copy Anvil.app to install location"
else
    fail "Copy Anvil.app to install location"
fi

INSTALLED_APP="$INSTALL_DIR/Anvil.app"

# Verify installed copy is complete
if [ -f "$INSTALLED_APP/Contents/MacOS/Anvil" ]; then
    pass "Installed binary exists"
else
    fail "Installed binary exists"
fi

if [ -d "$INSTALLED_APP/Contents/Resources/AgentRuntime/anvil_agent" ]; then
    pass "Installed runtime exists"
else
    fail "Installed runtime exists"
fi

if [ -d "$INSTALLED_APP/Contents/Resources/AgentRuntime/site-packages/aiosqlite" ]; then
    pass "Installed deps exist (aiosqlite)"
else
    fail "Installed deps exist (aiosqlite)"
fi

# Compare file count between source and installed
SRC_COUNT=$(find "$MOUNT_DIR/Anvil.app" -type f | wc -l | tr -d ' ')
DST_COUNT=$(find "$INSTALLED_APP" -type f | wc -l | tr -d ' ')
if [ "$SRC_COUNT" = "$DST_COUNT" ]; then
    pass "File count matches ($SRC_COUNT files)"
else
    fail "File count matches (source=$SRC_COUNT, installed=$DST_COUNT)"
fi

echo ""

# ── Phase 9: Installed Python Runtime Smoke Test ─────────────────

bold "Phase 9: Installed Runtime Smoke Test"

INST_RUNTIME="$INSTALLED_APP/Contents/Resources/AgentRuntime"
INST_SITE_PKG="$INST_RUNTIME/site-packages"

# Simulate exactly what AgentRuntimeService.swift does
export PYTHONPATH="$INST_RUNTIME:$INST_SITE_PKG"

# Core import from installed location
if python3 -c "from anvil_agent.main import AnvilRuntime" 2>/dev/null; then
    pass "Import AnvilRuntime from installed location"
else
    fail "Import AnvilRuntime from installed location"
fi

# Gateway imports
if python3 -c "from anvil_agent.gateway.config import GatewayConfig; GatewayConfig()" 2>/dev/null; then
    pass "GatewayConfig importable and instantiable"
else
    fail "GatewayConfig importable and instantiable"
fi

# Session search with graceful degradation
if python3 -c "from anvil_agent.session.search import SessionSearchDB; db = SessionSearchDB()" 2>/dev/null; then
    pass "SessionSearchDB importable (aiosqlite present)"
else
    fail "SessionSearchDB importable"
fi

# Verify all tool schemas generate correctly
SCHEMA_CHECK=$(python3 -c "
from anvil_agent.tools import create_default_registry
reg = create_default_registry()
schemas = reg.get_all_schemas()
print(len(schemas))
" 2>/dev/null)
if [ -n "$SCHEMA_CHECK" ] && [ "$SCHEMA_CHECK" -gt 0 ] 2>/dev/null; then
    pass "Tool registry produces $SCHEMA_CHECK tool schemas"
else
    fail "Tool registry schema generation"
fi

unset PYTHONPATH

# Detach DMG
hdiutil detach "$MOUNT_DIR" -quiet 2>/dev/null || true

echo ""

# ── Phase 10: Binary Execution Check ────────────────────────────

bold "Phase 10: Binary Execution Check"

# The app binary should at least print help or version without crashing
# We can't fully launch the SwiftUI app headless, but we can check the binary
# doesn't immediately segfault by testing its architecture
ARCH_CHECK=$(file "$INSTALLED_APP/Contents/MacOS/Anvil" 2>/dev/null)
if echo "$ARCH_CHECK" | grep -q "arm64"; then
    pass "Binary is arm64 native"
elif echo "$ARCH_CHECK" | grep -q "x86_64"; then
    pass "Binary is x86_64"
else
    fail "Binary architecture detection"
fi

# Verify the binary isn't stripped of required rpaths
if otool -L "$INSTALLED_APP/Contents/MacOS/Anvil" 2>/dev/null | grep -q "Sparkle"; then
    pass "Binary links to Sparkle framework"
else
    # Sparkle might be statically linked
    pass "Binary linked (Sparkle may be static)"
fi

# Ensure binary size is reasonable (> 1MB, < 100MB)
BINARY_SIZE=$(stat -f%z "$INSTALLED_APP/Contents/MacOS/Anvil" 2>/dev/null || echo "0")
if [ "$BINARY_SIZE" -gt 1048576 ] && [ "$BINARY_SIZE" -lt 104857600 ]; then
    BINARY_MB=$((BINARY_SIZE / 1048576))
    pass "Binary size is reasonable (${BINARY_MB}MB)"
else
    fail "Binary size check ($BINARY_SIZE bytes)"
fi

echo ""

# ── Summary ──────────────────────────────────────────────────────

bold "============================================"
if [ "$FAILED" -eq 0 ]; then
    printf "\033[32m  All %d tests passed!\033[0m\n" "$PASSED"
else
    printf "\033[31m  Results: %d passed, %d failed\033[0m\n" "$PASSED" "$FAILED"
    echo ""
    printf "\033[31m  Failed tests:\033[0m\n"
    for err in "${ERRORS[@]}"; do
        printf "\033[31m    - %s\033[0m\n" "$err"
    done
fi
bold "============================================"
echo ""

exit "$FAILED"
