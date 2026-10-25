# Anvil Desktop (Electron + React)

Cross-platform UI for Anvil. It talks to the same Python agent runtime as the SwiftUI app, over a
token-authenticated local WebSocket (`ws://127.0.0.1:<port>/rpc`) instead of the macOS-only Unix socket.

```
Electron main  ── spawns & supervises ──►  python -m anvil_agent --no-socket --ws-port 0
     │  preload bridge (window.anvil)               ▲
     ▼                                              │ JSON-RPC 2.0 over WebSocket
React renderer (Vite, TypeScript, zustand) ─────────┘
```

## Develop

```bash
cd Desktop
npm install
npm run dev          # Electron + hot reload; starts the runtime from ../AgentRuntime
```

The runtime needs its Python deps: `cd ../AgentRuntime && python3 -m venv venv && venv/bin/pip install -e .`
(`venv/` or `.venv/` is picked up automatically; override with `ANVIL_PYTHON` / `ANVIL_RUNTIME_DIR`).
To attach to a runtime you started yourself, set `ANVIL_RUNTIME_WS='ws://127.0.0.1:PORT/rpc?token=…'`.

## Test

```bash
npm run typecheck
npm test             # unit tests (RPC client, chat reducer, MCP helpers)
npm run test:e2e     # Playwright against the real runtime + a scripted fake model; no network or API key
```

`test:e2e` drives the built renderer in Chromium and also launches the real Electron app (needs a display;
on Linux use `xvfb-run -a npm run test:e2e`). Set `PW_CHROMIUM=/path/to/chrome` to use an existing Chromium, or
run `npx playwright install chromium` once. Screenshots land in `e2e/shots/`.

## Security model

- Renderer is sandboxed (`contextIsolation`, no Node integration) and only sees the `window.anvil` bridge.
- The runtime listens on `127.0.0.1` only; each launch uses a fresh random token passed via environment
  (not argv), and browser `Origin`s are checked on top of that.
- The runtime exits if the app that launched it dies (`--exit-on-stdin-eof`).
- External links open in the system browser; `http(s)` and `mailto:` only.

## Status

Ported from the SwiftUI app: chat (streaming markdown, tool calls, permission prompts, plan mode), sessions,
model selection, and settings (general, API key, permissions, MCP). Still to port: teams, projects/kanban,
skills browser, agents view, gateway/endpoints/hooks/system/update settings, onboarding and model download,
git and file panels. Packaging (bundled Python + Ollama, installers, auto-update) is not set up yet.
