from anvil_agent.guardrails import GuardConfig, ToolLoopGuard


def test_exact_failure_warns_then_hard_blocks():
    g = ToolLoopGuard(GuardConfig(hard_stop=True))
    args = {"path": "/x"}
    assert g.after_call("read_file", args, "err", True).action == "allow"
    assert g.after_call("read_file", args, "err", True).action == "warn"
    for _ in range(2):
        g.after_call("read_file", args, "err", True)
    assert g.after_call("read_file", args, "err", True).action == "halt"
    assert g.before_call("read_file", args).action == "block"


def test_interactive_never_blocks():
    g = ToolLoopGuard(GuardConfig(hard_stop=False))
    for _ in range(10):
        d = g.after_call("read_file", {"p": 1}, "err", True)
    assert d.action == "warn" and g.before_call("read_file", {"p": 1}).allows_execution


def test_bash_failures_are_tolerated():
    g = ToolLoopGuard(GuardConfig(hard_stop=True))
    for _ in range(10):
        assert g.after_call("bash", {"command": "pytest"}, "FAILED", True).action != "halt"


def test_idempotent_no_progress_warns_and_edit_resets():
    g = ToolLoopGuard()
    g.after_call("grep", {"q": "a"}, "same", False)
    assert g.after_call("grep", {"q": "a"}, "same", False).code == "no_progress_warn"
    g.after_call("edit_file", {"p": 1}, "ok", False)
    assert g.after_call("grep", {"q": "a"}, "same", False).action == "allow"


def test_changed_result_is_progress():
    g = ToolLoopGuard()
    g.after_call("read_file", {"p": 1}, "v1", False)
    assert g.after_call("read_file", {"p": 1}, "v2", False).action == "allow"


def test_web_search_cap():
    g = ToolLoopGuard(GuardConfig(max_web_searches_per_turn=2))
    for i in range(2):
        g.after_call("web_search", {"q": str(i)}, "r", False)
    assert g.before_call("web_search", {"q": "z"}).should_halt
    g.reset()
    assert g.before_call("web_search", {"q": "z"}).allows_execution
