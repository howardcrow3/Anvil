#!/bin/bash
set -euo pipefail

# Test IPC concurrency: verifies the IPCClient thread safety fix by
# sending many concurrent requests to the agent runtime.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SOCKET_PATH="/tmp/anvil-test-concurrency.sock"

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


async def single_connection_burst():
    """Send many requests on a single connection rapidly."""
    print("\nTest 1: Burst of 20 rapid requests on one connection")
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    # Create a project we can use for requests
    project_id = str(uuid.uuid4()).upper()
    await send_rpc(reader, writer, "project.create", {
        "id": project_id, "name": "Concurrency Test", "folder_path": "/tmp/conc-test",
    })

    # Send 20 task creations as fast as possible
    tasks_created = []
    for i in range(20):
        tid = str(uuid.uuid4()).upper()
        result = await send_rpc(reader, writer, "project.task.create", {
            "project_id": project_id,
            "id": tid,
            "title": f"Task {i}",
        })
        if result and "__error" not in result:
            tasks_created.append(tid)

    check(len(tasks_created) == 20, f"All 20 tasks created successfully (got {len(tasks_created)})")

    # Verify project has all tasks
    result = await send_rpc(reader, writer, "project.get", {"id": project_id})
    task_count = len(result.get("tasks", [])) if result else 0
    check(task_count == 20, f"Project reports 20 tasks (got {task_count})")

    writer.close()
    await writer.wait_closed()


async def parallel_connections():
    """Open multiple connections and send requests simultaneously."""
    print("\nTest 2: 5 parallel connections sending concurrently")

    project_id = str(uuid.uuid4()).upper()
    # Create project on a fresh connection
    r, w = await asyncio.open_unix_connection(SOCKET_PATH)
    await send_rpc(r, w, "project.create", {
        "id": project_id, "name": "Parallel Test", "folder_path": "/tmp/par-test",
    })
    w.close()
    await w.wait_closed()

    async def worker(worker_id, num_tasks):
        reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
        created = 0
        for i in range(num_tasks):
            tid = str(uuid.uuid4()).upper()
            result = await send_rpc(reader, writer, "project.task.create", {
                "project_id": project_id,
                "id": tid,
                "title": f"W{worker_id}-Task{i}",
            })
            if result and "__error" not in result:
                created += 1
        writer.close()
        await writer.wait_closed()
        return created

    # 5 workers, each creating 4 tasks = 20 total
    results = await asyncio.gather(*[worker(i, 4) for i in range(5)])
    total = sum(results)
    check(total == 20, f"All 20 tasks from parallel workers created (got {total})")

    # Verify
    r, w = await asyncio.open_unix_connection(SOCKET_PATH)
    result = await send_rpc(r, w, "project.get", {"id": project_id})
    task_count = len(result.get("tasks", [])) if result else 0
    check(task_count == 20, f"Project has all 20 parallel tasks (got {task_count})")
    w.close()
    await w.wait_closed()


async def rapid_status_updates():
    """Rapidly toggle task status to stress the update path."""
    print("\nTest 3: Rapid status transitions (50 updates)")
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    project_id = str(uuid.uuid4()).upper()
    task_id = str(uuid.uuid4()).upper()

    await send_rpc(reader, writer, "project.create", {
        "id": project_id, "name": "Status Stress", "folder_path": "/tmp/status-stress",
    })
    await send_rpc(reader, writer, "project.task.create", {
        "project_id": project_id, "id": task_id, "title": "Stress task",
    })

    statuses = ["in_progress", "needs_help", "completed", "not_started"]
    success_count = 0
    for i in range(50):
        status = statuses[i % len(statuses)]
        result = await send_rpc(reader, writer, "project.task.update", {
            "project_id": project_id, "task_id": task_id, "status": status,
        })
        if result and result.get("status") == "ok":
            success_count += 1

    check(success_count == 50, f"All 50 rapid status updates succeeded (got {success_count})")

    # Final state should match last update
    final_status = statuses[49 % len(statuses)]
    result = await send_rpc(reader, writer, "project.get", {"id": project_id})
    task = next((t for t in result.get("tasks", []) if t["id"] == task_id), None)
    check(task and task.get("status") == final_status, f"Final status correct ({final_status})")

    writer.close()
    await writer.wait_closed()


async def disconnect_recovery():
    """Connect, send requests, disconnect, reconnect, verify state."""
    print("\nTest 4: Disconnect and reconnect preserves prior state")
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    project_id = str(uuid.uuid4()).upper()
    await send_rpc(reader, writer, "project.create", {
        "id": project_id, "name": "Reconnect Test", "folder_path": "/tmp/reconn",
    })
    await send_rpc(reader, writer, "project.task.create", {
        "project_id": project_id, "id": str(uuid.uuid4()).upper(), "title": "Persistent task",
    })

    # Abruptly close
    writer.close()
    await writer.wait_closed()

    # Reconnect
    await asyncio.sleep(0.5)
    reader2, writer2 = await asyncio.open_unix_connection(SOCKET_PATH)
    result = await send_rpc(reader2, writer2, "project.get", {"id": project_id})
    tasks = result.get("tasks", []) if result else []
    check(len(tasks) == 1, f"Task persisted after reconnect (got {len(tasks)})")
    check(tasks[0]["title"] == "Persistent task" if tasks else False, "Task data intact")

    writer2.close()
    await writer2.wait_closed()


async def main():
    print("=== IPC Concurrency & Thread Safety Tests ===")

    await single_connection_burst()
    await parallel_connections()
    await rapid_status_updates()
    await disconnect_recovery()

    print(f"\n{'='*50}")
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print(f"{'='*50}")

    if FAIL_COUNT > 0:
        sys.exit(1)

asyncio.run(main())
PYTHON

EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "ALL CONCURRENCY TESTS PASSED"
else
    echo "SOME TESTS FAILED"
    exit 1
fi
