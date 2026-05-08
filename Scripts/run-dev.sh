#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOCKET_PATH="/tmp/anvil-agent.sock"

cleanup() {
    echo "Cleaning up..."
    # Kill the agent and all its children (including Ollama it spawned)
    kill "$AGENT_PID" 2>/dev/null || true
    # Kill any Ollama processes started by the agent
    pkill -P "$AGENT_PID" 2>/dev/null || true
    # Also kill orphaned ollama processes listening on our ports
    pkill -f "ollama serve" 2>/dev/null || true
    rm -f "$SOCKET_PATH"
    echo "All processes stopped."
}
trap cleanup EXIT INT TERM

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

if [ ! -S "$SOCKET_PATH" ]; then
    echo "WARNING: Agent runtime socket not detected after 5s. Continuing anyway..."
fi

# Build the .app bundle and launch it
echo "Building Anvil.app..."
bash "$SCRIPT_DIR/build-app.sh"

echo "Launching Anvil.app..."
open "$PROJECT_ROOT/build/Anvil.app"

# Wait for agent to exit (cleanup trap handles killing everything)
echo "Anvil is running. Press Ctrl+C to stop."
wait "$AGENT_PID"
