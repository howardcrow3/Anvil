#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build"
APP_NAME="Anvil"
DMG_NAME="Anvil.dmg"

echo "=== Packaging Anvil.dmg ==="

# Create build directory
mkdir -p "$BUILD_DIR/$APP_NAME.app/Contents/MacOS"
mkdir -p "$BUILD_DIR/$APP_NAME.app/Contents/Resources"
mkdir -p "$BUILD_DIR/$APP_NAME.app/Contents/Resources/agent-runtime"
mkdir -p "$BUILD_DIR/$APP_NAME.app/Contents/Frameworks"

# Build Swift app in release mode
echo "Building SwiftUI app (release)..."
cd "$PROJECT_ROOT/Anvil"
swift build -c release
cp .build/release/Anvil "$BUILD_DIR/$APP_NAME.app/Contents/MacOS/"

# Copy Info.plist
cp "$PROJECT_ROOT/Resources/Info.plist" "$BUILD_DIR/$APP_NAME.app/Contents/"

# Bundle Python runtime (using PyInstaller or just copy)
echo "Bundling Python agent runtime..."
cp -r "$PROJECT_ROOT/AgentRuntime/anvil_agent" "$BUILD_DIR/$APP_NAME.app/Contents/Resources/agent-runtime/"
cp "$PROJECT_ROOT/AgentRuntime/requirements.txt" "$BUILD_DIR/$APP_NAME.app/Contents/Resources/agent-runtime/"

# Bundle Ollama binary if available
if command -v ollama &>/dev/null; then
    echo "Bundling Ollama binary..."
    cp "$(which ollama)" "$BUILD_DIR/$APP_NAME.app/Contents/Resources/"
fi

# Copy default configs
cp "$PROJECT_ROOT/Resources/default-models.json" "$BUILD_DIR/$APP_NAME.app/Contents/Resources/" 2>/dev/null || true

# Create DMG
echo "Creating DMG..."
if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "$APP_NAME" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "$APP_NAME.app" 175 190 \
        --app-drop-link 425 190 \
        "$BUILD_DIR/$DMG_NAME" \
        "$BUILD_DIR/$APP_NAME.app"
else
    echo "create-dmg not found. Creating simple DMG..."
    hdiutil create -volname "$APP_NAME" -srcfolder "$BUILD_DIR/$APP_NAME.app" -ov -format UDZO "$BUILD_DIR/$DMG_NAME"
fi

echo "=== DMG created at $BUILD_DIR/$DMG_NAME ==="
