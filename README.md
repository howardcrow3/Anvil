# Anvil — Where Agents Are Forged

[![CI](https://github.com/howardcrow3/Anvil/actions/workflows/ci.yml/badge.svg)](https://github.com/howardcrow3/Anvil/actions/workflows/ci.yml)

Anvil is a cross-platform desktop AI agent app (Electron + React front end, Python agent runtime) that brings
Claude Code– and Cowork-style capabilities to your own machine. Pick the model per chat: Claude through the
Anthropic API, a local model run by a bundled llama.cpp, or any OpenAI-compatible endpoint.

## Features

- **Multiple model backends**: Claude (cloud), local GGUF models via llama.cpp, or any OpenAI-compatible endpoint
- **Local models managed in the app**: download, cancel and delete from Settings → Models; only models that fit
  your computer's memory are offered
- **Full tool system**: Read, Write, Edit, Bash, Glob, Grep, WebSearch and WebFetch, with permission prompts and plan mode
- **Agent teams and subagents**: multi-agent teams with shared task lists, delegated subagents, and a kanban board
- **MCP support**: connect Model Context Protocol servers over stdio, streamable HTTP or SSE
- **Sessions and memory**: persistent, resumable sessions with auto-compression; project-level `CLAUDE.md` and memory
- **Skills and hooks**: reusable skills, and lifecycle hooks to control agent behavior

## Install

| Platform | Build |
|----------|-------|
| macOS (Apple Silicon, Intel) | `.dmg` / `.zip` |
| Windows (x64) | NSIS installer |
| Linux (x64) | AppImage |

Every commit to `main` is built for all four targets by [CI](.github/workflows/ci.yml); download the installers from
the run's **Artifacts**. Pushing a `v*` tag publishes them to GitHub Releases.

The installers are **not signed or notarized yet**, so macOS Gatekeeper and Windows SmartScreen will warn on first
launch. CI starts the Linux app and checks that it launches its bundled Python and connects; the macOS and Windows
builds are built but not launch-tested there.

**Requirements:** 8 GB+ RAM (16 GB+ recommended for local models) and free disk space for the models you download.
Building from source also needs Node.js 20+ and Python 3.11+.

## Models

### Cloud (needs an Anthropic API key)

| Model | ID |
|-------|----|
| Claude Opus 5.5 | `claude-opus-5-5` |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` |
| Claude Haiku 5.5 | `claude-haiku-5-5` |

### Local (llama.cpp)

Open **Settings → Models** to download a model. Files come from Hugging Face into `~/.anvil/models`, resume if
interrupted, and are checksum-verified. Anvil lists only models whose RAM requirement fits this computer, checks
free disk space first, and runs one download at a time. **Cancel** deletes everything that download wrote; a download
that failed keeps its partial file so **Resume** continues where it stopped.

When you pick a downloaded model, Anvil starts `llama-server` for it on `127.0.0.1` behind a random API key and
shares it between agents. Set `HF_TOKEN` for gated repositories.

| Model | Parameters | Download | Min RAM |
|-------|-----------|----------|---------|
| Gemma 4 E2B | 2.3B effective | 2.6 GB | 4 GB |
| Gemma 4 E4B | 4B effective | 4.3 GB | 6 GB |
| Gemma 4 26B A4B | 26B MoE (4B active) | 13.6 GB | 18 GB |
| Hermes 3 8B | 8B | 4.6 GB | 6 GB |
| Hermes 4.3 36B | 36B | 20.3 GB | 28 GB |
| Qwen 3 8B | 8B | 4.7 GB | 6 GB |
| Llama 4 Scout | 17B active (109B MoE) | 60.9 GB | 67 GB |
| Mistral Small 3.2 | 24B | 13.3 GB | 16 GB |
| Qwen 3 32B | 32B | 18.4 GB | 21 GB |

The list lives in [`AgentRuntime/anvil_agent/services/model_catalog.py`](AgentRuntime/anvil_agent/services/model_catalog.py);
a weekly workflow checks it against Hugging Face.

### Custom endpoints

Any OpenAI-compatible API: LM Studio, vLLM, OpenRouter, Together AI, Groq, and so on. Add them in Settings → Endpoints.

## Configuration

Settings and data live in `~/.anvil/` (`config.json`, `mcp-servers.json`, `models/`).

| Variable | Purpose |
|----------|---------|
| `ANVIL_LLAMA_SERVER` | Path to your own `llama-server` binary (also the `llama_server_path` setting) |
| `ANVIL_LLAMA_DIR` | Folder to look for `llama-server` in |
| `HF_TOKEN` | Hugging Face token for gated model repositories |

### MCP servers

Configure them in Settings → MCP or in `~/.anvil/mcp-servers.json`:

```json
{
  "mcpServers": {
    "files":  {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
    "remote": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}},
    "legacy": {"url": "https://example.com/sse", "type": "sse"}
  }
}
```

Optional per-server keys: `enabled`, `timeout`, `connect_timeout`, `env`, `cwd`. Tools appear as
`mcp__<server>__<tool>`, require approval, and are reached through tool search.

## Architecture

```
Electron + React app
    ↕ JSON-RPC 2.0 over a localhost WebSocket (token-authenticated)
Python Agent Runtime
    ↕ Model Router
    ├── Claude API (Anthropic SDK)
    ├── llama.cpp llama-server (bundled, loopback, started on demand)
    └── Custom endpoints (OpenAI-compatible)
```

The runtime listens on `127.0.0.1` only. Each launch uses a fresh random token passed through the environment, and
the runtime exits when the app that started it exits. See [`Desktop/README.md`](Desktop/README.md) for the full
security model.

## Development

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

### Tests

```bash
cd AgentRuntime && python -m pytest --ignore=tests/test_build_install.py   # Python
cd Desktop && npm run typecheck && npm test && npm run test:e2e            # TypeScript, unit, end-to-end
```

CI runs all of these on every pull request, plus the installer builds on `main`. Four Python tests need a real
`llama-server` and model and are skipped when none is available (set `ANVIL_LLAMA_SERVER` and `ANVIL_TEST_GGUF` to run them). See
[`Desktop/README.md`](Desktop/README.md) for e2e and packaging notes.

### Keeping llama.cpp current

The app bundles an official llama.cpp release pinned (tag + sha256 per platform) in
[`Resources/llama-cpp.lock.json`](Resources/llama-cpp.lock.json). The **Update llama.cpp** workflow runs daily: when a
new release exists it pins it, bundles it, checks it on all four platforms (running a real `llama-server` against a tiny model on Linux), and
proposes the bump. To bump by hand: `node Desktop/scripts/update-llama-cpp.mjs` (`--check` only reports,
`--tag bNNNN` pins a specific release).

### Project structure

```
Anvil/
├── Desktop/        # Electron + React app (electron-vite, zustand, vitest, Playwright)
├── AgentRuntime/   # Python agent runtime (agent loop, tools, IPC, MCP, models) and its tests
├── Scripts/        # Helper scripts
├── Resources/      # Icons, default configs, pinned llama.cpp
└── docs/           # Design specs and implementation plans
```

### Contributing

Conventions are in [`CLAUDE.md`](CLAUDE.md): Pydantic v2, asyncio and type hints in Python; JSON-RPC 2.0 for IPC;
tools shared by the Claude and local-model paths. Open a pull request against `main` and make sure the checks above pass.

## License

MIT
