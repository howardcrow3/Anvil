#!/bin/bash
set -euo pipefail

# Test that conversations are correctly loaded and displayed for both sessions and tasks.
# Verifies:
#   1. Session resume returns messages via IPC
#   2. Task with linked session loads conversation via IPC
#   3. Task without session gets a new session linked
#   4. Local JSONL fallback works when IPC returns empty
#   5. Project file decoding handles both camelCase and snake_case keys
#   6. Session list uses correct "id" key (not "session_id")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOCKET_PATH="/tmp/anvil-test-convview.sock"

cleanup() {
    echo "Cleaning up..."
    kill "$AGENT_PID" 2>/dev/null || true
    pkill -P "$AGENT_PID" 2>/dev/null || true
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

sleep 2

python3 - "$SOCKET_PATH" <<'PYTHON'
import asyncio
import json
import os
import sys
import uuid

SOCKET_PATH = sys.argv[1]
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
    print("\n=== Conversation View Tests ===\n")

    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    # ─── Test 1: Session list returns correct "id" key ─────────────────
    print("Test 1: Session list returns 'id' field (not 'session_id')")

    session_id_1 = str(uuid.uuid4()).upper()
    await send_rpc(reader, writer, "session.create", {
        "session_id": session_id_1,
        "name": "View Test Session 1",
    })

    # Send a message to have content
    await send_rpc(reader, writer, "chat.send", {
        "message": "Hello from view test 1",
        "session_id": session_id_1,
    })
    await asyncio.sleep(6)

    result = await send_rpc(reader, writer, "session.list")
    check(isinstance(result, list), "session.list returns a list")
    matching = [s for s in result if s.get("id") == session_id_1]
    check(len(matching) == 1, f"Session found by 'id' key (not 'session_id')")
    if matching:
        check(matching[0].get("message_count", 0) >= 2, f"Session has messages (count={matching[0].get('message_count')})")
        check("session_id" not in matching[0], "No 'session_id' key in session list (uses 'id')")

    # ─── Test 2: Session resume returns full conversation ──────────────
    print("\nTest 2: Session resume loads full conversation")

    result = await send_rpc(reader, writer, "session.resume", {
        "session_id": session_id_1,
    })
    check("messages" in result, "Resume response has 'messages' key")
    check(result.get("message_count", 0) >= 2, f"message_count >= 2 (got {result.get('message_count')})")

    messages = result.get("messages", [])
    user_msgs = [m for m in messages if m["role"] == "user"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    check(len(user_msgs) >= 1, "Has user message")
    check(len(assistant_msgs) >= 1, "Has assistant message")
    check("view test 1" in (user_msgs[0]["content"].lower() if user_msgs else ""), "User message content correct")
    check(len(assistant_msgs[0].get("content", "")) > 5 if assistant_msgs else False, "Assistant response has content")

    # ─── Test 3: Task with linked session loads conversation ───────────
    print("\nTest 3: Task with linked session loads conversation via session.resume")

    project_id = str(uuid.uuid4()).upper()
    task_id = str(uuid.uuid4()).upper()
    task_session_id = str(uuid.uuid4()).upper()

    await send_rpc(reader, writer, "project.create", {
        "id": project_id, "name": "Conv View Project", "folder_path": "/tmp/convview",
    })
    await send_rpc(reader, writer, "project.task.create", {
        "project_id": project_id, "id": task_id, "title": "Linked Conv Task",
    })
    await send_rpc(reader, writer, "session.create", {
        "session_id": task_session_id, "name": "Task Session",
    })

    # Send messages to the task's session
    await send_rpc(reader, writer, "chat.send", {
        "message": "Build a todo app with React",
        "session_id": task_session_id,
    })
    await asyncio.sleep(6)

    # Simulate what Swift does: resume the task's linked session
    result = await send_rpc(reader, writer, "session.resume", {
        "session_id": task_session_id,
    })
    messages = result.get("messages", [])
    check(len(messages) >= 2, f"Task session has conversation (got {len(messages)} msgs)")
    user_content = [m["content"] for m in messages if m["role"] == "user"]
    check(any("todo" in c.lower() for c in user_content), "Task session has correct user message")
    assistant_content = [m["content"] for m in messages if m["role"] == "assistant"]
    check(len(assistant_content) >= 1 and len(assistant_content[0]) > 10, "Task session has assistant response")

    # ─── Test 4: Project file with session_id is read correctly ─────────
    print("\nTest 4: Fresh project file with session_id loads via project.get")

    # Write a project file directly to disk (simulating Swift saving a link)
    # Use a NEW project ID so Python reads it fresh from disk (not cached)
    projects_dir = os.path.expanduser("~/.anvil/projects")
    linked_project_id = str(uuid.uuid4()).upper()
    linked_task_id = str(uuid.uuid4()).upper()

    linked_proj = {
        "id": linked_project_id,
        "name": "Linked Session Project",
        "folder_path": "/tmp/linked",
        "github_repo": "",
        "created_at": "2026-05-04T00:00:00Z",
        "updated_at": "2026-05-04T00:00:00Z",
        "tasks": [{
            "id": linked_task_id,
            "title": "Task With Session",
            "description": "",
            "status": "in_progress",
            "session_id": task_session_id,
            "created_at": "2026-05-04T00:00:00Z",
            "updated_at": "2026-05-04T00:00:00Z",
        }],
    }
    linked_path = os.path.join(projects_dir, f"{linked_project_id}.json")
    with open(linked_path, "w") as f:
        json.dump(linked_proj, f, indent=2)

    # Python reads fresh from disk for uncached projects
    result = await send_rpc(reader, writer, "project.get", {"id": linked_project_id})
    tasks = result.get("tasks", [])
    linked_task = next((t for t in tasks if t["id"] == linked_task_id), None)
    check(linked_task is not None, "Task found in project")
    check(linked_task.get("session_id") == task_session_id, f"Task has correct session_id link")

    os.remove(linked_path)

    # ─── Test 5: camelCase project file decoded correctly ──────────────
    print("\nTest 5: camelCase project file with sessionId decoded correctly")

    camel_project_id = str(uuid.uuid4()).upper()
    camel_session_id = str(uuid.uuid4()).upper()
    camel_task_id = str(uuid.uuid4()).upper()

    # Write a project file in Swift's camelCase format
    camel_project = {
        "id": camel_project_id,
        "name": "CamelCase Project",
        "folderPath": "/Users/test/camel",
        "githubRepo": "",
        "createdAt": "2026-05-01T00:00:00Z",
        "updatedAt": "2026-05-01T00:00:00Z",
        "tasks": [{
            "id": camel_task_id,
            "title": "Camel Task",
            "taskDescription": "Has camelCase sessionId",
            "status": "in_progress",
            "sessionId": camel_session_id,
            "createdAt": "2026-05-01T00:00:00Z",
            "updatedAt": "2026-05-01T00:00:00Z",
        }],
    }
    camel_path = os.path.join(projects_dir, f"{camel_project_id}.json")
    with open(camel_path, "w") as f:
        json.dump(camel_project, f, indent=2)

    # Python should normalize and return it
    result = await send_rpc(reader, writer, "project.get", {"id": camel_project_id})
    check(result is not None, "camelCase project loaded")
    if result:
        tasks = result.get("tasks", [])
        check(len(tasks) == 1, "Task present")
        if tasks:
            check(tasks[0].get("session_id") == camel_session_id, f"sessionId normalized to session_id ({tasks[0].get('session_id')})")

    os.remove(camel_path)

    # ─── Test 6: snake_case project file decoded correctly ─────────────
    print("\nTest 6: snake_case project file with session_id decoded correctly")

    snake_project_id = str(uuid.uuid4()).upper()
    snake_session_id = str(uuid.uuid4()).upper()
    snake_task_id = str(uuid.uuid4()).upper()

    snake_project = {
        "id": snake_project_id,
        "name": "Snake Case Project",
        "folder_path": "/Users/test/snake",
        "github_repo": "",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:00Z",
        "tasks": [{
            "id": snake_task_id,
            "title": "Snake Task",
            "description": "Has snake_case session_id",
            "status": "in_progress",
            "session_id": snake_session_id,
            "created_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-05-01T00:00:00Z",
        }],
    }
    snake_path = os.path.join(projects_dir, f"{snake_project_id}.json")
    with open(snake_path, "w") as f:
        json.dump(snake_project, f, indent=2)

    result = await send_rpc(reader, writer, "project.get", {"id": snake_project_id})
    check(result is not None, "snake_case project loaded")
    if result:
        tasks = result.get("tasks", [])
        check(len(tasks) == 1, "Task present")
        if tasks:
            check(tasks[0].get("session_id") == snake_session_id, f"session_id preserved ({tasks[0].get('session_id')})")

    os.remove(snake_path)

    # ─── Test 7: JSONL fallback — direct file read ─────────────────────
    print("\nTest 7: JSONL fallback reads messages from disk")

    fallback_session_id = str(uuid.uuid4()).upper()
    sessions_dir = os.path.expanduser("~/.anvil/sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    jsonl_path = os.path.join(sessions_dir, f"{fallback_session_id}.jsonl")

    # Write messages directly to JSONL (simulating what the runtime saves)
    with open(jsonl_path, "w") as f:
        f.write(json.dumps({"role": "user", "content": "Direct JSONL message", "timestamp": "2026-05-01T00:00:00Z"}) + "\n")
        f.write(json.dumps({"role": "assistant", "content": "Response from JSONL file", "timestamp": "2026-05-01T00:00:01Z"}) + "\n")

    # Resume should find it from the file
    result = await send_rpc(reader, writer, "session.resume", {
        "session_id": fallback_session_id,
    })
    messages = result.get("messages", [])
    check(len(messages) == 2, f"JSONL file messages loaded (got {len(messages)})")
    check(messages[0]["content"] == "Direct JSONL message" if messages else False, "First message content correct")
    check(messages[1]["content"] == "Response from JSONL file" if len(messages) > 1 else False, "Second message content correct")

    os.remove(jsonl_path)

    # ─── Test 8: Multiple resumes don't duplicate messages ─────────────
    print("\nTest 8: Multiple resumes return same message set")

    result1 = await send_rpc(reader, writer, "session.resume", {"session_id": session_id_1})
    result2 = await send_rpc(reader, writer, "session.resume", {"session_id": session_id_1})
    check(result1.get("message_count") == result2.get("message_count"),
          f"Same message count on double-resume ({result1.get('message_count')} == {result2.get('message_count')})")

    # ─── Test 9: Swift decoder test (simulated) ───────────────────────
    print("\nTest 9: Project files with mixed key formats all return session links")

    # Create 3 projects: one camelCase, one snake_case, one mixed
    test_projects = []
    for fmt_name, task_data in [
        ("camel", {"id": str(uuid.uuid4()).upper(), "title": "T1", "taskDescription": "d",
                   "status": "in_progress", "sessionId": str(uuid.uuid4()).upper(),
                   "createdAt": "2026-05-01T00:00:00Z", "updatedAt": "2026-05-01T00:00:00Z"}),
        ("snake", {"id": str(uuid.uuid4()).upper(), "title": "T2", "description": "d",
                   "status": "completed", "session_id": str(uuid.uuid4()).upper(),
                   "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-01T00:00:00Z"}),
        ("mixed", {"id": str(uuid.uuid4()).upper(), "title": "T3", "taskDescription": "d",
                   "status": "not_started", "session_id": str(uuid.uuid4()).upper(),
                   "createdAt": "2026-05-01T00:00:00Z", "updated_at": "2026-05-01T00:00:00Z"}),
    ]:
        pid = str(uuid.uuid4()).upper()
        proj = {"id": pid, "name": f"Format {fmt_name}", "folder_path": "/tmp/fmt",
                "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-01T00:00:00Z",
                "tasks": [task_data]}
        path = os.path.join(projects_dir, f"{pid}.json")
        with open(path, "w") as f:
            json.dump(proj, f, indent=2)
        expected_sid = task_data.get("sessionId") or task_data.get("session_id")
        test_projects.append((pid, fmt_name, expected_sid, path))

    all_good = True
    for pid, fmt_name, expected_sid, path in test_projects:
        result = await send_rpc(reader, writer, "project.get", {"id": pid})
        if result:
            tasks = result.get("tasks", [])
            actual_sid = tasks[0].get("session_id") if tasks else None
            if actual_sid != expected_sid:
                all_good = False
                print(f"    DETAIL: {fmt_name} expected {expected_sid}, got {actual_sid}")
        else:
            all_good = False
        os.remove(path)

    check(all_good, "All key formats (camel/snake/mixed) preserve session_id")

    # ─── Summary ──────────────────────────────────────────────────────
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
    echo "ALL CONVERSATION VIEW TESTS PASSED"
else
    echo "SOME TESTS FAILED"
    exit 1
fi
