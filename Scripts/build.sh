#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Building Anvil ==="

# Build SwiftUI app
echo "Building SwiftUI app..."
cd "$PROJECT_ROOT/Anvil"
swift build -c release

# Set up Python environment
echo "Setting up Python agent runtime..."
cd "$PROJECT_ROOT/AgentRuntime"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt -q

echo "=== Build complete ==="
echo "Run with: swift run Anvil (from Anvil/ directory)"
