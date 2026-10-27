# Anvil Project

Cross-platform desktop AI agent app: Electron + React front end and a Python agent runtime.
(The original SwiftUI macOS app was removed; it remains in git history before the "Remove SwiftUI app" commit.)

## Project Structure
- `Desktop/` - Electron + React app (electron-vite, zustand, vitest, Playwright)
- `AgentRuntime/` - Python agent runtime
- `Scripts/` - Helper scripts
- `Resources/` - Icons, default configs

## Build Commands
- Python runtime: `cd AgentRuntime && pip install -e .`
- Python tests: `cd AgentRuntime && python -m pytest --ignore=tests/test_build_install.py`
- Desktop dev: `cd Desktop && npm ci && npm run dev`
- Desktop checks: `npm run typecheck && npm test && npm run test:e2e`

## Key Conventions
- Python: Use Pydantic v2, asyncio, type hints everywhere
- IPC: JSON-RPC 2.0 over a localhost WebSocket (token via env ANVIL_WS_TOKEN); a Unix socket is optional
- All tools shared between Claude and local model paths

## Claude Code Skills
- `.claude/skills/` holds the [superpowers](https://github.com/obra/superpowers) skills (TDD, systematic debugging, planning, code review), vendored from upstream v6.4.2 under the MIT license. See `.claude/skills/README.md`.
