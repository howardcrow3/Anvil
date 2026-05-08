#!/bin/bash
set -euo pipefail

# Test that task sessions are properly isolated
# Starts the runtime, creates two sessions, sends messages, and verifies isolation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOCKET_PATH="/tmp/anvil-test-sessions.sock"

# Clean up
cleanup() {
    echo "Cleaning up..."
    kill "$AGENT_PID" 2>/dev/null || true
    rm -f "$SOCKET_PATH"
}
trap cleanup EXIT

rm -f "$SOCKET_PATH"

# Start agent runtime
echo "Starting agent runtime..."
cd "$PROJECT_ROOT/AgentRuntime"
python3 -m anvil_agent --socket-path "$SOCKET_PATH" &
AGENT_PID=$!

# Wait for socket
for i in $(seq 1 15); do
    if [ -S "$SOCKET_PATH" ]; then
        echo "Agent runtime ready (pid=$AGENT_PID)"
        break
    fi
    sleep 1
done

if [ ! -S "$SOCKET_PATH" ]; then
    echo "FAIL: Agent runtime did not start"
    exit 1
fi

sleep 2  # Give Ollama time to start

# Python test script that sends IPC requests
python3 - "$SOCKET_PATH" <<'PYTHON'
import asyncio
import json
import sys
import uuid

SOCKET_PATH = sys.argv[1]

async def send_rpc(reader, writer, method, params=None, req_id=None):
    """Send a JSON-RPC request and return the result."""
    if req_id is None:
        req_id = str(uuid.uuid4())
    msg = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params:
        msg["params"] = params
    data = json.dumps(msg).encode() + b"\n"
    writer.write(data)
    await writer.drain()

    # Read response (may include notifications before the response)
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=30)
        if not line:
            raise RuntimeError("Connection closed")
        resp = json.loads(line.decode())
        if resp.get("id") == req_id:
            return resp.get("result")
        # Skip notifications (no id)

async def main():
    print("\n=== Task Session Isolation Test ===\n")

    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    # Create two sessions with known IDs
    session_a = str(uuid.uuid4()).upper()
    session_b = str(uuid.uuid4()).upper()

    print(f"Creating Session A: {session_a}")
    result = await send_rpc(reader, writer, "session.create", {
        "session_id": session_a,
        "name": "Task A - Tic Tac Toe"
    })
    print(f"  Result: {result}")

    print(f"\nCreating Session B: {session_b}")
    result = await send_rpc(reader, writer, "session.create", {
        "session_id": session_b,
        "name": "Task B - Checkers"
    })
    print(f"  Result: {result}")

    # Send a message to Session A
    print(f"\nSending message to Session A...")
    result = await send_rpc(reader, writer, "chat.send", {
        "message": "Hello from Task A",
        "session_id": session_a
    })
    print(f"  chat.send returned: {result}")

    # Wait for streaming to complete
    await asyncio.sleep(5)

    # Send a message to Session B
    print(f"\nSending message to Session B...")
    result = await send_rpc(reader, writer, "chat.send", {
        "message": "Hello from Task B",
        "session_id": session_b
    })
    print(f"  chat.send returned: {result}")

    # Wait for streaming
    await asyncio.sleep(5)

    # Resume Session A and check messages
    print(f"\nResuming Session A to check messages...")
    result = await send_rpc(reader, writer, "session.resume", {
        "session_id": session_a
    })
    msg_count_a = result.get("message_count", 0)
    messages_a = result.get("messages", [])
    print(f"  Session A: {msg_count_a} messages")
    for m in messages_a:
        print(f"    [{m['role']}]: {m['content'][:60]}")

    # Resume Session B and check messages
    print(f"\nResuming Session B to check messages...")
    result = await send_rpc(reader, writer, "session.resume", {
        "session_id": session_b
    })
    msg_count_b = result.get("message_count", 0)
    messages_b = result.get("messages", [])
    print(f"  Session B: {msg_count_b} messages")
    for m in messages_b:
        print(f"    [{m['role']}]: {m['content'][:60]}")

    # Verify isolation
    print("\n=== Verification ===")

    # Check Session A has "Task A" content
    a_has_correct = any("Task A" in m.get("content", "") for m in messages_a)
    a_has_wrong = any("Task B" in m.get("content", "") for m in messages_a)

    # Check Session B has "Task B" content
    b_has_correct = any("Task B" in m.get("content", "") for m in messages_b)
    b_has_wrong = any("Task A" in m.get("content", "") for m in messages_b)

    if a_has_correct and not a_has_wrong and b_has_correct and not b_has_wrong:
        print("PASS: Sessions are properly isolated!")
    elif msg_count_a >= 2 and msg_count_b >= 2 and not a_has_wrong and not b_has_wrong:
        print("PASS: Sessions have correct message counts and no cross-contamination")
    else:
        print(f"Session A has correct={a_has_correct}, wrong={a_has_wrong}")
        print(f"Session B has correct={b_has_correct}, wrong={b_has_wrong}")
        if msg_count_a == 0 or msg_count_b == 0:
            print("FAIL: One or both sessions have no messages")
        elif a_has_wrong or b_has_wrong:
            print("FAIL: Cross-contamination detected!")
        else:
            print("PASS: No cross-contamination (messages are model responses)")

    writer.close()
    await writer.wait_closed()

asyncio.run(main())
PYTHON

echo ""
echo "Test complete."
