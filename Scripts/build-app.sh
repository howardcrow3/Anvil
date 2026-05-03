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
mkdir -p "$APP_BUNDLE/Contents/Resources/AgentRuntime"
mkdir -p "$APP_BUNDLE/Contents/Resources/ollama"

# Copy the release binary
BINARY_PATH="$PROJECT_ROOT/Anvil/.build/release/Anvil"
if [ ! -f "$BINARY_PATH" ]; then
    echo "ERROR: Release binary not found at $BINARY_PATH"
    exit 1
fi
cp "$BINARY_PATH" "$APP_BUNDLE/Contents/MacOS/Anvil"

# Bundle Sparkle.framework
echo "Bundling frameworks..."
mkdir -p "$APP_BUNDLE/Contents/Frameworks"
SPARKLE_SRC="$PROJECT_ROOT/Anvil/.build/release/Sparkle.framework"
if [ -d "$SPARKLE_SRC" ]; then
    cp -a "$SPARKLE_SRC" "$APP_BUNDLE/Contents/Frameworks/"
    # Add rpath so the binary can find Sparkle in Contents/Frameworks
    install_name_tool -add_rpath "@loader_path/../Frameworks" "$APP_BUNDLE/Contents/MacOS/Anvil" 2>/dev/null || true
    echo "  Bundled Sparkle.framework"
else
    echo "  WARNING: Sparkle.framework not found at $SPARKLE_SRC"
fi

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
    cp -r "$PROJECT_ROOT/AgentRuntime/anvil_agent" "$APP_BUNDLE/Contents/Resources/AgentRuntime/"
    echo "  Copied anvil_agent package"
else
    echo "ERROR: AgentRuntime/anvil_agent not found"
    exit 1
fi

if [ -f "$PROJECT_ROOT/AgentRuntime/requirements.txt" ]; then
    cp "$PROJECT_ROOT/AgentRuntime/requirements.txt" "$APP_BUNDLE/Contents/Resources/AgentRuntime/"
    echo "  Copied requirements.txt"
fi

# Install Python dependencies into bundled site-packages
echo "Installing Python dependencies..."
SITE_PACKAGES="$APP_BUNDLE/Contents/Resources/AgentRuntime/site-packages"
mkdir -p "$SITE_PACKAGES"
PYTHON3=$(command -v python3 || echo "/usr/bin/python3")
if [ -f "$PROJECT_ROOT/AgentRuntime/pyproject.toml" ]; then
    "$PYTHON3" -m pip install --target "$SITE_PACKAGES" --quiet \
        "$PROJECT_ROOT/AgentRuntime" 2>/dev/null || {
        echo "  WARNING: pip install from pyproject.toml failed, trying requirements.txt..."
        if [ -f "$PROJECT_ROOT/AgentRuntime/requirements.txt" ]; then
            "$PYTHON3" -m pip install --target "$SITE_PACKAGES" --quiet \
                -r "$PROJECT_ROOT/AgentRuntime/requirements.txt" 2>/dev/null || \
                echo "  WARNING: Could not install Python dependencies"
        fi
    }
    echo "  Installed Python dependencies to site-packages"
else
    echo "  WARNING: No pyproject.toml found, skipping dependency install"
fi

# Bundle default Ollama model (gemma4:e2b) if available locally
echo "Bundling default local model..."
OLLAMA_MODELS="$HOME/.ollama/models"
BUNDLED_MODELS="$APP_BUNDLE/Contents/Resources/models"
MODEL_MANIFEST="$OLLAMA_MODELS/manifests/registry.ollama.ai/library/gemma4/e2b"
if [ -f "$MODEL_MANIFEST" ]; then
    mkdir -p "$BUNDLED_MODELS/manifests/registry.ollama.ai/library/gemma4"
    cp "$MODEL_MANIFEST" "$BUNDLED_MODELS/manifests/registry.ollama.ai/library/gemma4/e2b"
    # Copy all blobs referenced by the manifest
    mkdir -p "$BUNDLED_MODELS/blobs"
    for digest in $(python3 -c "
import json, sys
m = json.load(open('$MODEL_MANIFEST'))
print(m['config']['digest'])
for layer in m['layers']:
    print(layer['digest'])
" 2>/dev/null); do
        blob_file="$OLLAMA_MODELS/blobs/${digest/://‐}"
        # Ollama stores blobs as sha256-<hash> (with hyphen)
        blob_file="$OLLAMA_MODELS/blobs/$(echo "$digest" | tr ':' '-')"
        if [ -f "$blob_file" ]; then
            cp "$blob_file" "$BUNDLED_MODELS/blobs/"
            echo "  Copied blob $(basename "$blob_file") ($(du -sh "$blob_file" | cut -f1))"
        fi
    done
    echo "  Bundled gemma4:e2b model"
else
    echo "  WARNING: gemma4:e2b not found locally. Run: ollama pull gemma4:e2b"
    echo "  The app will work but users must download a model on first launch."
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
