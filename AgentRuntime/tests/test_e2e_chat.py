"""End-to-end test: start the Anvil runtime, send a chat query, verify a response arrives.

Requires Ollama running with gemma4:e2b available.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

RUNTIME_DIR = os.path.join(os.path.dirname(__file__), "..")
PYTHON = sys.executable


def _ollama_has_model() -> bool:
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        data = json.loads(resp.read())
        return any(m["name"].startswith("gemma4:e2b") for m in data.get("models", []))
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_has_model(), reason="Ollama not running or gemma4:e2b not available")
class TestE2EChat:
    """Integration tests that boot the full runtime and talk to it via IPC."""

    @pytest.fixture(autouse=True)
    def runtime(self, tmp_path):
        """Start the Anvil agent runtime and yield when socket is ready."""
        # Use /tmp for socket (pytest tmp_path is too long for Unix sockets' 104-char limit)
        sock_path = f"/tmp/anvil_test_{uuid.uuid4().hex[:8]}.sock"

        proc = subprocess.Popen(
            [
                PYTHON, "-u", "-m", "anvil_agent",
                "--socket-path", sock_path,
                "--project-dir", str(tmp_path),
                "--model", "gemma4:e2b",
                "--provider", "ollama",
                "--log-level", "WARNING",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=RUNTIME_DIR,
        )

        # Poll for socket file existence
        deadline = time.monotonic() + 30
        socket_ready = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode(errors="replace")
                pytest.fail(f"Runtime exited (code {proc.returncode}): {stderr[:1000]}")
            if os.path.exists(sock_path):
                time.sleep(0.3)
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(2)
                    s.connect(sock_path)
                    s.close()
                    socket_ready = True
                    break
                except (ConnectionRefusedError, OSError):
                    time.sleep(0.5)
                    continue
            time.sleep(0.5)

        if not socket_ready:
            proc.kill()
            proc.wait()
            stderr = proc.stderr.read().decode(errors="replace")
            pytest.fail(f"Runtime socket not ready within 30s. stderr: {stderr[:1000]}")

        self.sock_path = sock_path
        self.proc = proc
        yield

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        # Clean up socket file
        try:
            os.unlink(sock_path)
        except OSError:
            pass

    def _send_rpc(self, method: str, params: dict | None = None, timeout: float = 30) -> list[dict]:
        """Send a JSON-RPC request and collect all responses."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(self.sock_path)

        req = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": 1,
        }) + "\n"
        s.sendall(req.encode())

        messages = []
        buf = b""
        try:
            while True:
                data = s.recv(65536)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        msg = json.loads(line)
                        messages.append(msg)
                        if "id" in msg and msg["id"] == 1:
                            s.close()
                            return messages
        except socket.timeout:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        return messages

    def test_model_list_returns_gemma(self):
        """model.list should include gemma4:e2b as active."""
        msgs = self._send_rpc("model.list", timeout=10)
        assert len(msgs) >= 1
        response = msgs[-1]
        assert response.get("id") == 1
        assert response.get("error") is None

        models = response["result"]
        active = [m for m in models if m.get("active")]
        assert len(active) == 1
        assert active[0]["id"] == "gemma4:e2b"

    def test_chat_returns_response(self):
        """A simple question should produce text_delta and done events."""
        msgs = self._send_rpc(
            "chat.send",
            {"message": "What is 1+1? Answer with just the number.", "session_id": ""},
            timeout=60,
        )

        notifications = [m for m in msgs if "method" in m]
        rpc_response = [m for m in msgs if "id" in m and m["id"] == 1]

        assert len(rpc_response) == 1
        assert rpc_response[0]["result"]["status"] == "ok"

        text_deltas = [
            n for n in notifications
            if n.get("params", {}).get("type") == "text_delta"
        ]
        assert len(text_deltas) > 0, "No text_delta events received"

        done_events = [
            n for n in notifications
            if n.get("params", {}).get("type") == "done"
        ]
        assert len(done_events) >= 1, "No done event received"

        full_text = "".join(
            n["params"]["text"] for n in text_deltas if "text" in n.get("params", {})
        )
        assert len(full_text.strip()) > 0, "Response text is empty"

    def test_chat_no_empty_response(self):
        """Response text should not be blank for a simple query."""
        msgs = self._send_rpc(
            "chat.send",
            {"message": "Say hello.", "session_id": ""},
            timeout=60,
        )

        text_deltas = [
            m for m in msgs
            if m.get("params", {}).get("type") == "text_delta"
        ]
        full_text = "".join(
            m["params"]["text"] for m in text_deltas if "text" in m.get("params", {})
        )
        assert len(full_text.strip()) >= 2, f"Response too short: '{full_text}'"
