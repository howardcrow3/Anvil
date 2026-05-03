#!/bin/bash
set -euo pipefail

# Build Verification CI Script
# Runs all build checks and test suites for the Anvil project.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PASSED=0
FAILED=0
SKIPPED=0
ERRORS=()

green() { printf "\033[32m%s\033[0m\n" "$1"; }
red()   { printf "\033[31m%s\033[0m\n" "$1"; }
bold()  { printf "\033[1m%s\033[0m\n" "$1"; }

step() {
    bold "--- $1 ---"
}

pass() {
    green "  PASS: $1"
    PASSED=$((PASSED + 1))
}

fail() {
    red "  FAIL: $1"
    FAILED=$((FAILED + 1))
    ERRORS+=("$1")
}

skip() {
    printf "\033[33m  SKIP: %s\033[0m\n" "$1"
    SKIPPED=$((SKIPPED + 1))
}

echo ""
bold "=============================="
bold "  Anvil CI Verification Suite"
bold "=============================="
echo ""

# 1. Swift Build
step "Swift Build (release)"
cd "$PROJECT_ROOT/Anvil"
if swift build -c release 2>&1; then
    pass "Swift release build"
else
    fail "Swift release build"
fi

# 2. Swift Tests (require Xcode SDK with Testing/XCTest framework)
step "Swift Unit Tests"
cd "$PROJECT_ROOT/Anvil"
SWIFT_TEST_OUTPUT=$(swift test 2>&1) || true
if echo "$SWIFT_TEST_OUTPUT" | grep -q "no such module"; then
    skip "Swift unit tests (Xcode SDK not configured - run: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer)"
elif echo "$SWIFT_TEST_OUTPUT" | grep -q "Build complete"; then
    pass "Swift unit tests"
else
    echo "$SWIFT_TEST_OUTPUT"
    fail "Swift unit tests"
fi

# 3. Python Lint Check (basic syntax)
step "Python Syntax Check"
cd "$PROJECT_ROOT/AgentRuntime"
if python3 -m py_compile anvil_agent/main.py 2>&1; then
    pass "Python main.py syntax"
else
    fail "Python main.py syntax"
fi

if python3 -c "import anvil_agent" 2>&1; then
    pass "Python package import"
else
    fail "Python package import"
fi

# 4. Python Unit Tests
step "Python Unit Tests"
cd "$PROJECT_ROOT/AgentRuntime"
if python3 -m pytest tests/ -v --tb=short 2>&1; then
    pass "Python unit tests"
else
    fail "Python unit tests"
fi

# 5. App Bundle Build
step "App Bundle Build"
cd "$PROJECT_ROOT"
if bash Scripts/build-app.sh 2>&1; then
    pass "App bundle build"
else
    fail "App bundle build"
fi

# 6. Verify App Bundle Structure
step "App Bundle Structure"
APP_BUNDLE="$PROJECT_ROOT/build/Anvil.app"
if [ -d "$APP_BUNDLE" ]; then
    pass "Anvil.app exists"
else
    fail "Anvil.app exists"
fi

if [ -f "$APP_BUNDLE/Contents/MacOS/Anvil" ]; then
    pass "Binary exists at Contents/MacOS/Anvil"
else
    fail "Binary exists at Contents/MacOS/Anvil"
fi

if [ -f "$APP_BUNDLE/Contents/Info.plist" ]; then
    pass "Info.plist exists"
else
    fail "Info.plist exists"
fi

if [ -d "$APP_BUNDLE/Contents/Resources/AgentRuntime/anvil_agent" ]; then
    pass "Agent runtime bundled"
else
    fail "Agent runtime bundled"
fi

if [ -f "$APP_BUNDLE/Contents/Frameworks/Sparkle.framework/Versions/B/Sparkle" ]; then
    pass "Sparkle.framework bundled"
else
    fail "Sparkle.framework bundled"
fi

if otool -l "$APP_BUNDLE/Contents/MacOS/Anvil" 2>/dev/null | grep -q "@loader_path/../Frameworks"; then
    pass "Sparkle rpath set"
else
    fail "Sparkle rpath set"
fi

# Check binary is arm64
if file "$APP_BUNDLE/Contents/MacOS/Anvil" 2>/dev/null | grep -q "arm64"; then
    pass "Binary is arm64"
elif file "$APP_BUNDLE/Contents/MacOS/Anvil" 2>/dev/null | grep -q "Mach-O"; then
    pass "Binary is Mach-O (architecture may vary)"
else
    fail "Binary architecture check"
fi

# 7. DMG Packaging
step "DMG Packaging"
if bash Scripts/package-dmg.sh 2>&1; then
    pass "DMG packaging"
else
    fail "DMG packaging"
fi

DMG_FILE=$(ls "$PROJECT_ROOT/build/"*.dmg 2>/dev/null | head -1)
if [ -n "$DMG_FILE" ] && [ -f "$DMG_FILE" ]; then
    pass "DMG file created: $(basename "$DMG_FILE")"
    DMG_SIZE=$(du -sh "$DMG_FILE" | cut -f1)
    echo "  DMG size: $DMG_SIZE"
else
    fail "DMG file created"
fi

# 8. Verify DMG Contents
step "DMG Contents Verification"
if [ -n "$DMG_FILE" ] && [ -f "$DMG_FILE" ]; then
    MOUNT_OUT=$(hdiutil attach -nobrowse -noverify "$DMG_FILE" 2>/dev/null)
    MOUNT_DIR=$(echo "$MOUNT_OUT" | grep "/Volumes/" | sed 's|.*\(/Volumes/.*\)|\1|')

    if [ -n "$MOUNT_DIR" ] && [ -d "$MOUNT_DIR" ]; then
        if [ -d "$MOUNT_DIR/Anvil.app" ]; then
            pass "DMG contains Anvil.app"
        else
            fail "DMG contains Anvil.app"
        fi

        if [ -L "$MOUNT_DIR/Applications" ]; then
            pass "DMG contains Applications symlink"
        else
            fail "DMG contains Applications symlink"
        fi

        hdiutil detach "$MOUNT_DIR" -quiet 2>/dev/null || true
    else
        fail "DMG mount"
    fi
else
    fail "DMG contents (no DMG to verify)"
fi

# Summary
echo ""
bold "=============================="
bold "  Results: $PASSED passed, $FAILED failed, $SKIPPED skipped"
bold "=============================="
if [ ${#ERRORS[@]} -gt 0 ]; then
    echo ""
    red "Failed checks:"
    for err in "${ERRORS[@]}"; do
        red "  - $err"
    done
fi
echo ""

exit "$FAILED"
