#!/bin/bash
set -euo pipefail

# Download the Ollama CLI binary for macOS and extract to Resources/ollama/
# This bundles Ollama into the app so users don't need a separate install.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OLLAMA_DIR="$PROJECT_ROOT/Resources/ollama"
OLLAMA_VERSION="${OLLAMA_VERSION:-v0.22.1}"

echo "=== Downloading Ollama ${OLLAMA_VERSION} for macOS ==="

# Clean previous download
rm -rf "$OLLAMA_DIR"
mkdir -p "$OLLAMA_DIR"

# Download tarball
TEMP_FILE=$(mktemp)
trap "rm -f '$TEMP_FILE'" EXIT

echo "Downloading ollama-darwin.tgz..."
curl -L --progress-bar \
    -o "$TEMP_FILE" \
    "https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-darwin.tgz"

# Extract
echo "Extracting to Resources/ollama/..."
tar xzf "$TEMP_FILE" -C "$OLLAMA_DIR"
chmod +x "$OLLAMA_DIR/ollama"

# Verify
echo ""
echo "=== Download Complete ==="
file "$OLLAMA_DIR/ollama"
echo ""
echo "Contents:"
ls -lh "$OLLAMA_DIR/ollama"
du -sh "$OLLAMA_DIR"
echo ""
echo "Ollama is ready to be bundled. Run ./Scripts/build-app.sh to build the app."
