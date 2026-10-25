# Third-party notices

## Hermes Agent (Nous Research) — MIT License

The following Anvil modules are adapted from ideas and code structure in
[Hermes Agent](https://github.com/NousResearch/hermes-agent):

- `AgentRuntime/anvil_agent/guardrails.py` (from `agent/tool_guardrails.py`)
- `AgentRuntime/anvil_agent/compaction.py` (from `agent/context_compressor*.py`)
- `AgentRuntime/anvil_agent/budget.py` (from `agent/iteration_budget.py`)
- `AgentRuntime/anvil_agent/redact.py` (from `agent/redact.py`)
- `AgentRuntime/anvil_agent/tools/tool_search.py`, `tools/registry.py` (tool search / progressive tool disclosure)
- `AgentRuntime/anvil_agent/subagents/`, `tools/delegate_tool.py` (subagent lifecycle and steer/stop controls)
- `AgentRuntime/anvil_agent/kanban/`, `tools/kanban_tool.py` (from `hermes_cli/kanban_db*.py` and the kanban dispatcher)
- `AgentRuntime/anvil_agent/learning/review.py` (background memory/skill review)
- `AgentRuntime/anvil_agent/learning/curator.py`, `skills/usage.py` (skill curator and usage tracking)
- `AgentRuntime/anvil_agent/tools/skill_tools.py` (skills_list / skill_view / skill_manage / memory tools)

```
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
