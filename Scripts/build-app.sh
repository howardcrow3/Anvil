#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_ROOT/build"
APP_BUNDLE="$BUILD_DIR/Anvil.app"

echo "=== Building Anvil.app ==="

# Build Swift app in release mode
echo "Building SwiftUI app (release)..."
cd "$PROJECT_ROOT/Anvil"
swift build -c release

# Create .app bundle directory structure
echo "Creating app bundle structure..."
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"
mkdir -p "$APP_BUNDLE/Contents/Resources/agent-runtime"
mkdir -p "$APP_BUNDLE/Contents/Resources/ollama"

# Copy the release binary
BINARY_PATH="$PROJECT_ROOT/Anvil/.build/release/Anvil"
if [ ! -f "$BINARY_PATH" ]; then
    echo "ERROR: Release binary not found at $BINARY_PATH"
    exit 1
fi
cp "$BINARY_PATH" "$APP_BUNDLE/Contents/MacOS/Anvil"

# Copy Info.plist
if [ ! -f "$PROJECT_ROOT/Resources/Info.plist" ]; then
    echo "ERROR: Info.plist not found at $PROJECT_ROOT/Resources/Info.plist"
    exit 1
fi
cp "$PROJECT_ROOT/Resources/Info.plist" "$APP_BUNDLE/Contents/"

# Copy default-models.json
if [ -f "$PROJECT_ROOT/Resources/default-models.json" ]; then
    cp "$PROJECT_ROOT/Resources/default-models.json" "$APP_BUNDLE/Contents/Resources/"
    echo "  Bundled default-models.json"
fi

# Copy entitlements if present
if [ -f "$PROJECT_ROOT/Anvil.entitlements" ]; then
    cp "$PROJECT_ROOT/Anvil.entitlements" "$APP_BUNDLE/Contents/Resources/"
    echo "  Bundled entitlements"
fi

# Bundle Ollama binary + libraries
OLLAMA_SRC="$PROJECT_ROOT/Resources/ollama"
if [ -f "$OLLAMA_SRC/ollama" ]; then
    cp -r "$OLLAMA_SRC"/* "$APP_BUNDLE/Contents/Resources/ollama/"
    chmod +x "$APP_BUNDLE/Contents/Resources/ollama/ollama"
    echo "  Bundled Ollama binary + libraries from Resources/ollama/"
elif command -v ollama &>/dev/null; then
    cp "$(which ollama)" "$APP_BUNDLE/Contents/Resources/ollama/"
    echo "  Bundled Ollama binary from system PATH"
else
    echo "  WARNING: Ollama not found. Run Scripts/download-ollama.sh to download it."
fi

# Copy the Python AgentRuntime
echo "Bundling Python agent runtime..."
if [ -d "$PROJECT_ROOT/AgentRuntime/anvil_agent" ]; then
    cp -r "$PROJECT_ROOT/AgentRuntime/anvil_agent" "$APP_BUNDLE/Contents/Resources/agent-runtime/"
    echo "  Copied anvil_agent package"
else
    echo "ERROR: AgentRuntime/anvil_agent not found"
    exit 1
fi

if [ -f "$PROJECT_ROOT/AgentRuntime/requirements.txt" ]; then
    cp "$PROJECT_ROOT/AgentRuntime/requirements.txt" "$APP_BUNDLE/Contents/Resources/agent-runtime/"
    echo "  Copied requirements.txt"
fi

# Print summary
echo ""
echo "=== Build Summary ==="
echo "App bundle: $APP_BUNDLE"
echo "Contents:"
find "$APP_BUNDLE" -maxdepth 4 -type f | sed "s|$APP_BUNDLE|  Anvil.app|" | sort
echo ""
BUNDLE_SIZE=$(du -sh "$APP_BUNDLE" | cut -f1)
echo "Total size: $BUNDLE_SIZE"
echo "=== Build complete ==="
