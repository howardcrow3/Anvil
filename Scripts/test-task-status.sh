#!/bin/bash
set -euo pipefail

# Test task status updates, session content persistence, and key normalization
# Tests:
#   1. Task status transitions via IPC
#   2. Session messages saved and restored on resume
#   3. Session isolation between tasks
#   4. Swift camelCase project files read correctly by Python backend
#   5. Session links preserved across project reload

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOCKET_PATH="/tmp/anvil-test-task-status.sock"
TEST_PROJECT_DIR="/tmp/anvil-test-projects-$$"

cleanup() {
    echo "Cleaning up..."
    kill "$AGENT_PID" 2>/dev/null || true
    pkill -P "$AGENT_PID" 2>/dev/null || true
    rm -f "$SOCKET_PATH"
    rm -rf "$TEST_PROJECT_DIR"
}
trap cleanup EXIT

rm -f "$SOCKET_PATH"
mkdir -p "$TEST_PROJECT_DIR"

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

python3 - "$SOCKET_PATH" "$TEST_PROJECT_DIR" <<'PYTHON'
import asyncio
import json
import os
import sys
import uuid

SOCKET_PATH = sys.argv[1]
TEST_PROJECT_DIR = sys.argv[2]

PASS_COUNT = 0
FAIL_COUNT = 0

def check(condition, msg):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS: {msg}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL: {msg}")

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

    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=30)
        if not line:
            raise RuntimeError("Connection closed")
        resp = json.loads(line.decode())
        if resp.get("id") == req_id:
            if resp.get("error"):
                return {"__error": resp["error"]}
            return resp.get("result")


async def main():
    print("\n=== Task Status, Session Content & Key Normalization Tests ===\n")

    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    # ─── Test 1: Task status transitions ───────────────────────────
    print("Test 1: Task status transitions")
    project_id = str(uuid.uuid4()).upper()
    task_id = str(uuid.uuid4()).upper()

    await send_rpc(reader, writer, "project.create", {
        "id": project_id,
        "name": "Status Test Project",
        "folder_path": "/tmp/test-status",
    })

    await send_rpc(reader, writer, "project.task.create", {
        "project_id": project_id,
        "id": task_id,
        "title": "Test task",
    })

    # Transition through all states
    for status in ["in_progress", "needs_help", "completed", "not_started"]:
        result = await send_rpc(reader, writer, "project.task.update", {
            "project_id": project_id,
            "task_id": task_id,
            "status": status,
        })
        check(result.get("status") == "ok", f"status -> {status}")

    # Verify final state
    result = await send_rpc(reader, writer, "project.get", {"id": project_id})
    task = next((t for t in result.get("tasks", []) if t["id"] == task_id), None)
    check(task is not None, "Task exists in project")
    check(task.get("status") == "not_started", f"Final status is not_started (got: {task.get('status')})")

    # ─── Test 2: Session content persistence ───────────────────────
    print("\nTest 2: Session content persists across resume")
    session_id = str(uuid.uuid4()).upper()

    await send_rpc(reader, writer, "session.create", {
        "session_id": session_id,
        "name": "Content persistence test",
    })

    result = await send_rpc(reader, writer, "chat.send", {
        "message": "Build a REST API with Flask",
        "session_id": session_id,
    })
    check(result.get("status") == "ok", "chat.send accepted")

    await asyncio.sleep(8)  # Wait for model response

    # Resume and check
    result = await send_rpc(reader, writer, "session.resume", {
        "session_id": session_id,
    })
    msg_count = result.get("message_count", 0)
    messages = result.get("messages", [])
    check(msg_count >= 2, f"At least 2 messages saved (got {msg_count})")

    user_msgs = [m for m in messages if m["role"] == "user"]
    check(len(user_msgs) >= 1, "User message preserved")
    check("Flask" in (user_msgs[0]["content"] if user_msgs else ""), "User message content correct")

    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    check(len(assistant_msgs) >= 1, "Assistant response saved")
    check(len(assistant_msgs[0].get("content", "")) > 10 if assistant_msgs else False, "Assistant response non-empty")

    # ─── Test 3: Session isolation ─────────────────────────────────
    print("\nTest 3: Session isolation between tasks")
    session_a = str(uuid.uuid4()).upper()
    session_b = str(uuid.uuid4()).upper()

    await send_rpc(reader, writer, "session.create", {"session_id": session_a, "name": "Task A"})
    await send_rpc(reader, writer, "session.create", {"session_id": session_b, "name": "Task B"})

    await send_rpc(reader, writer, "chat.send", {"message": "Build a calculator app", "session_id": session_a})
    await asyncio.sleep(6)

    await send_rpc(reader, writer, "chat.send", {"message": "Write a poem about space", "session_id": session_b})
    await asyncio.sleep(6)

    # Resume A
    result_a = await send_rpc(reader, writer, "session.resume", {"session_id": session_a})
    msgs_a = result_a.get("messages", [])
    a_has_calculator = any("calculator" in m.get("content", "").lower() for m in msgs_a if m["role"] == "user")
    a_has_poem = any("poem" in m.get("content", "").lower() for m in msgs_a if m["role"] == "user")
    check(a_has_calculator, "Session A has calculator message")
    check(not a_has_poem, "Session A does NOT have poem message")

    # Resume B
    result_b = await send_rpc(reader, writer, "session.resume", {"session_id": session_b})
    msgs_b = result_b.get("messages", [])
    b_has_poem = any("poem" in m.get("content", "").lower() for m in msgs_b if m["role"] == "user")
    b_has_calculator = any("calculator" in m.get("content", "").lower() for m in msgs_b if m["role"] == "user")
    check(b_has_poem, "Session B has poem message")
    check(not b_has_calculator, "Session B does NOT have calculator message")

    # ─── Test 4: Swift camelCase project file normalization ────────
    print("\nTest 4: Python reads Swift camelCase project files correctly")

    # Write a project file in Swift's camelCase format
    swift_project_id = str(uuid.uuid4()).upper()
    swift_session_id = str(uuid.uuid4()).upper()
    swift_project = {
        "id": swift_project_id,
        "name": "Swift-Written Project",
        "folderPath": "/Users/test/Documents/project",
        "githubRepo": "user/repo",
        "createdAt": "2026-05-01T00:00:00Z",
        "updatedAt": "2026-05-01T00:00:00Z",
        "tasks": [
            {
                "id": str(uuid.uuid4()).upper(),
                "title": "Camel case task",
                "taskDescription": "Has camelCase keys",
                "status": "in_progress",
                "sessionId": swift_session_id,
                "createdAt": "2026-05-01T00:00:00Z",
                "updatedAt": "2026-05-01T00:00:00Z",
            }
        ],
    }

    # Write to ~/.anvil/projects/
    projects_dir = os.path.expanduser("~/.anvil/projects")
    project_path = os.path.join(projects_dir, f"{swift_project_id}.json")
    with open(project_path, "w") as f:
        json.dump(swift_project, f, indent=2)

    # Ask Python to reload and return it
    result = await send_rpc(reader, writer, "project.get", {"id": swift_project_id})

    if result:
        check(result.get("name") == "Swift-Written Project", "Project name loaded")
        check(result.get("folder_path") == "/Users/test/Documents/project", "folderPath -> folder_path normalized")
        check(result.get("github_repo") == "user/repo", "githubRepo -> github_repo normalized")

        tasks = result.get("tasks", [])
        check(len(tasks) == 1, "Task loaded from camelCase file")
        if tasks:
            check(tasks[0].get("session_id") == swift_session_id, f"sessionId -> session_id preserved ({tasks[0].get('session_id')})")
            check(tasks[0].get("status") == "in_progress", "Status preserved")
    else:
        check(False, "project.get returned None for Swift-written project")

    # Clean up test project file
    os.remove(project_path)

    # ─── Test 5: Session link preserved when task already has one ──
    print("\nTest 5: Opening task with existing sessionId reuses it")
    linked_project_id = str(uuid.uuid4()).upper()
    linked_task_id = str(uuid.uuid4()).upper()
    linked_session_id = str(uuid.uuid4()).upper()

    # Create project, task, and session
    await send_rpc(reader, writer, "project.create", {
        "id": linked_project_id, "name": "Link Test", "folder_path": "/tmp/link-test",
    })
    await send_rpc(reader, writer, "project.task.create", {
        "project_id": linked_project_id, "id": linked_task_id, "title": "Linked task",
    })
    await send_rpc(reader, writer, "session.create", {
        "session_id": linked_session_id, "name": "Linked session",
    })

    # Send a message to this session
    await send_rpc(reader, writer, "chat.send", {
        "message": "This is the linked session content",
        "session_id": linked_session_id,
    })
    await asyncio.sleep(6)

    # Now resume the same session (simulating what Swift does when opening task)
    result = await send_rpc(reader, writer, "session.resume", {
        "session_id": linked_session_id,
    })
    check(result.get("message_count", 0) >= 2, f"Linked session has messages ({result.get('message_count', 0)})")
    user_content = [m["content"] for m in result.get("messages", []) if m["role"] == "user"]
    check(any("linked session content" in c for c in user_content), "Linked session content preserved")

    # ─── Summary ──────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print(f"{'='*50}")

    if FAIL_COUNT > 0:
        sys.exit(1)

    writer.close()
    await writer.wait_closed()

asyncio.run(main())
PYTHON

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "ALL TESTS PASSED"
else
    echo "SOME TESTS FAILED"
    exit 1
fi
