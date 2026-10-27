# Anvil — Where Agents Are Forged

A cross-platform desktop AI agent app (Electron + React front end, Python agent runtime). Provides Claude Code and Cowork capabilities with the flexibility to choose between cloud models (Claude via API), local models (GGUF, run by a bundled llama.cpp), and any custom OpenAI-compatible endpoint.

## Features

- **Multi-Model Support**: Switch between Claude (cloud), local models via llama.cpp, or any OpenAI-compatible endpoint
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
    ├── llama.cpp llama-server (bundled, loopback, started on demand)
    └── Custom endpoints (OpenAI-compatible)
```

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

### Local (llama.cpp)
GGUF models download from Hugging Face on first use (`model.download`) into `~/.anvil/models`; the runtime then
starts `llama-server` for the model you select, on 127.0.0.1 behind a random API key, and shares it between
agents. Set `HF_TOKEN` for gated repositories.

| Model | Parameters | Min RAM |
|-------|-----------|---------|
| Gemma 4 E2B | 2.3B effective | 4GB |
| Gemma 4 E4B | 4B effective | 6GB |
| Gemma 4 26B A4B | 26B MoE (4B active) | 18GB |
| Hermes 3 8B | 8B | 6GB |
| Hermes 4.3 36B | 36B | 28GB |
| Qwen 3 8B | 8B | 6GB |
| Qwen 3 32B | 32B | 20GB |
| Mistral Small 3.2 | 24B | 16GB |
| Llama 4 Scout | 17B active (109B MoE) | 12GB |

The list lives in `AgentRuntime/anvil_agent/services/model_catalog.py`.

#### Keeping llama.cpp current
The app bundles an official llama.cpp release pinned (tag + sha256 per platform) in
`Resources/llama-cpp.lock.json`. The **Update llama.cpp** workflow runs daily: when a new release exists it pins it,
bundles it, runs the real `llama-server` against a tiny model, and opens a pull request. Merging that PR is all it
takes to ship the new engine. To bump by hand: `node Desktop/scripts/update-llama-cpp.mjs`
(`--check` only reports, `--tag bNNNN` pins a specific release). Point a dev runtime at your own build with
`ANVIL_LLAMA_SERVER=/path/to/llama-server` or the `llama_server_path` setting.

### Custom Endpoints
Any OpenAI-compatible API: LM Studio, vLLM, OpenRouter, Together AI, Groq, etc.

## License

MIT
