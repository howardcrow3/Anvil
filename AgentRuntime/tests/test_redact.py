from anvil_agent.redact import REDACTED, redact


def test_known_tokens():
    for secret in [
        "sk-ant-api03-" + "a" * 40,
        "ghp_" + "A" * 36,
        "AKIA" + "B" * 16,
        "xoxb-1234567890-abcdef",
        "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4",
    ]:
        assert secret not in redact(f"key is {secret} ok")


def test_assignments_and_bearer():
    out = redact("API_KEY=supersecret123\nAuthorization: Bearer abcdefghijklmnop1234")
    assert "supersecret123" not in out and "abcdefghijklmnop1234" not in out
    assert "API_KEY=" + REDACTED in out


def test_plain_text_untouched():
    assert redact("the tokenizer uses a token budget") == "the tokenizer uses a token budget"


def test_memory_manager_redacts_on_save(tmp_path):
    from anvil_agent.memory.manager import MemoryManager

    mm = MemoryManager.__new__(MemoryManager)
    mm._global_dir = tmp_path
    mm.save_memory("notes", "deploy with GITHUB_TOKEN=ghp_" + "A" * 36)
    assert "ghp_" not in (tmp_path / "notes.md").read_text()
