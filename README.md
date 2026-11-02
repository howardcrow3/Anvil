# Anvil — Where Agents Are Forged

A cross-platform desktop AI agent app (Electron + React front end, Python agent runtime). Provides Claude Code and Cowork capabilities with the flexibility to choose between cloud models (Claude via API), local models (via bundled Ollama), and any custom OpenAI-compatible endpoint.

## Features

- **Multi-Model Support**: Switch between Claude (cloud), local models via Ollama, or any OpenAI-compatible endpoint
- **Full Tool System**: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch — all built in
- **Agent Teams**: Spawn multi-agent teams with shared task lists and inter-agent messaging
- **Cross-platform**: Electron + React desktop app
- **MCP Support**: Add Model Context Protocol servers for extensible tool access
- **Session Management**: Persistent sessions with resume, fork, and auto-compression
- **Memory System**: Project-level CLAUDE.md and persistent memory across sessions
- **Hooks**: Lifecycle hooks for controlling agent behavior

## Architecture

```
Electron + React app
    ↕ IPC (WebSocket + JSON-RPC 2.0)
Python Agent Runtime
    ↕ Model Router
    ├── Claude API (Anthropic SDK)
    ├── Ollama (bundled, localhost)
    └── Custom endpoints (OpenAI-compatible)
```

## Browser and Desktop Tools

Agents can drive a web browser and native apps through two CLIs from Vercel Labs (Apache-2.0), **bundled with Anvil**
(unmodified, in `Resources/agent-tools/`, shipped as app resources). The tools are deferred behind `tool_search`.

```bash
node Scripts/fetch-agent-tools.mjs [--platform darwin-arm64]   # build step: pins + checksum-verifies both CLIs
```

- **Web access (DonSeTch).** The same script bundles [DonSeTch](https://github.com/dondai44423/donsetch) (AGPL-3.0, run
  as a separate process), which Anvil starts automatically as a built-in MCP server named `donsetch`. It adds keyless
  `mcp__donsetch__web_fetch`, `web_search` and `web_crawl` (clean markdown, PDFs, same-domain crawling). It runs with a
  minimal environment (no API keys). Turn it off by adding `"donsetch": {"command": "x", "enabled": false}` to
  `~/.anvil/mcp-servers.json` (or disabling it in the MCP settings). Note it does not check robots.txt and imitates a
  browser TLS fingerprint, and keyless search scrapes public engines from your IP.
- Dev checkout without the build step: the `integrations.install` IPC method (`{"tool": "all", "chrome": true}`)
  installs all three (browser, desktop, donsetch) into `~/.anvil/tools/bin` (browser/desktop via `npm pack`, so Node is needed; donsetch from its GitHub release).
- `browser` needs a Chrome: `integrations.install` with `chrome: true` runs `agent-browser install` (about 150 MB,
  one time), or set `AGENT_BROWSER_EXECUTABLE_PATH` to an existing Chrome.
- `desktop` on macOS needs Accessibility permission for Anvil (`agent-desktop permissions --guide`).
- Lookup order: `agent_*_path` setting, bundled `Resources/agent-tools/bin` (`ANVIL_TOOLS_DIR` when packaged),
  `~/.anvil/tools/bin`, then `PATH`.

- Every call asks for approval like other non-read-only tools; unattended subagents and Kanban workers are denied unless
  you add `browser` / `desktop` to `tool_allow_list`.
- Each agent gets its own isolated browser session. Page and on-screen content is marked as untrusted data.
- Limit browsing with the `agent_browser_allowed_domains` setting (e.g. `["example.com", "*.example.com"]`).
- Disable either tool with `agent_browser_enabled` / `agent_desktop_enabled`; point to a custom binary with
  `agent_browser_path` / `agent_desktop_path`. The `integrations.status` IPC method reports install state.
- Not exposed to agents on purpose: JavaScript eval, file upload, credential vault, cookie/state export, the clipboard,
  headed (physical mouse/keyboard) input, closing apps, and Chrome profile attach.

## MCP Servers

Anvil connects to MCP servers with the official `mcp` SDK over stdio, streamable HTTP, or SSE. Configure them in `~/.anvil/mcp-servers.json`:

```json
{
  "mcpServers": {
    "files":  {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
    "remote": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}},
    "legacy": {"url": "https://example.com/sse", "type": "sse"}
  }
}
```

Optional per-server keys: `enabled`, `timeout`, `connect_timeout`, `env`, `cwd`. Tools appear as `mcp__<server>__<tool>`, require approval, and are reached through tool search.

## Requirements

- Node.js 20+ and Python 3.11+
- 8GB+ RAM (16GB+ recommended for local models)

## Development Setup

```bash
# Python agent runtime
cd AgentRuntime
python3 -m venv venv && source venv/bin/activate
pip install -e .

# Desktop app (starts the runtime itself)
cd ../Desktop
npm ci
npm run dev
```

See `Desktop/README.md` for tests, e2e and packaging notes.

### Project Structure

```
Anvil/
├── Desktop/                    # Electron + React app
├── AgentRuntime/               # Python agent runtime
│   ├── anvil_agent/            # agent loop, tools, ipc, mcp, models, ...
│   └── tests/
├── Scripts/                    # Helper scripts
└── Resources/                  # Icons, default configs
```

## Supported Models

### Cloud (requires API key)
| Model | Provider |
|-------|----------|
| Claude Opus 4 | Anthropic |
| Claude Sonnet 4 | Anthropic |
| Claude Haiku 3.5 | Anthropic |

### Local (via Ollama)
| Model | Parameters | Min RAM |
|-------|-----------|---------|
| Gemma 3 4B | 4B | 4GB |
| Gemma 3 12B | 12B | 10GB |
| Llama 4 Scout | 17B active | 12GB |
| Mistral Small 3.2 | 24B | 16GB |
| Phi-4 | 14B | 10GB |
| Qwen 3 8B | 8B | 6GB |
| Qwen 3 32B | 32B | 20GB |

### Custom Endpoints
Any OpenAI-compatible API: LM Studio, vLLM, OpenRouter, Together AI, Groq, etc.

## License

MIT
