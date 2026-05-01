#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOCKET_PATH="/tmp/anvil-agent.sock"

# Clean up old socket
rm -f "$SOCKET_PATH"

# Start Python agent runtime in background
echo "Starting agent runtime..."
cd "$PROJECT_ROOT/AgentRuntime"
if [ -d "venv" ]; then
    source venv/bin/activate
fi
python3 -m anvil_agent --socket-path "$SOCKET_PATH" &
AGENT_PID=$!
echo "Agent runtime PID: $AGENT_PID"

# Wait for socket to be ready
for i in $(seq 1 10); do
    if [ -S "$SOCKET_PATH" ]; then
        echo "Agent runtime ready."
        break
    fi
    sleep 0.5
done

# Start SwiftUI app
echo "Starting Anvil app..."
cd "$PROJECT_ROOT/Anvil"
swift run Anvil

# Cleanup on exit
kill "$AGENT_PID" 2>/dev/null || true
rm -f "$SOCKET_PATH"
