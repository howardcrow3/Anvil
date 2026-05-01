# Anvil — Where Agents Are Forged

A native macOS desktop AI agent app for Apple Silicon. Provides Claude Code and Cowork capabilities with the flexibility to choose between cloud models (Claude via API), local models (via bundled Ollama), and any custom OpenAI-compatible endpoint.

## Features

- **Multi-Model Support**: Switch between Claude (cloud), local models via Ollama, or any OpenAI-compatible endpoint
- **Full Tool System**: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch — all built in
- **Agent Teams**: Spawn multi-agent teams with shared task lists and inter-agent messaging
- **Native macOS**: SwiftUI app with full Apple Silicon optimization and Metal GPU acceleration
- **MCP Support**: Add Model Context Protocol servers for extensible tool access
- **Session Management**: Persistent sessions with resume, fork, and auto-compression
- **Memory System**: Project-level CLAUDE.md and persistent memory across sessions
- **Hooks**: Lifecycle hooks for controlling agent behavior
- **Single DMG Install**: Everything bundled — just drag to Applications

## Architecture

```
SwiftUI App (native macOS UI)
    ↕ IPC (Unix domain socket + JSON-RPC)
Python Agent Runtime
    ↕ Model Router
    ├── Claude API (Anthropic SDK)
    ├── Ollama (bundled, localhost)
    └── Custom endpoints (OpenAI-compatible)
```

## Requirements

- macOS 14.0+ (Sonoma or later)
- Apple Silicon (M1/M2/M3/M4)
- 8GB+ RAM (16GB+ recommended for local models)

## Development Setup

### Prerequisites

```bash
# Swift 6.0+ (included with Xcode 16+)
swift --version

# Python 3.11+
python3 --version

# Ollama (for local model testing)
brew install ollama
```

### Build & Run

```bash
# Build the SwiftUI app
cd Anvil
swift build

# Run the Python agent runtime (development)
cd AgentRuntime
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 -m anvil_agent --socket-path /tmp/anvil.sock

# Run the full app
swift run Anvil
```

### Project Structure

```
Anvil/
├── Anvil/                      # SwiftUI macOS app
│   ├── Package.swift
│   └── Sources/Anvil/
│       ├── App/                # App entry point
│       ├── Views/              # SwiftUI views
│       ├── ViewModels/         # Observable view models
│       ├── Models/             # Data models
│       ├── Services/           # IPC, Ollama, Keychain
│       └── Utilities/          # Constants, extensions
├── AgentRuntime/               # Python agent runtime
│   ├── pyproject.toml
│   ├── anvil_agent/
│   │   ├── main.py             # Entry point
│   │   ├── agent_loop.py       # Core agent loop
│   │   ├── ipc/                # JSON-RPC IPC server
│   │   ├── models/             # Model providers
│   │   ├── tools/              # Built-in tools
│   │   ├── session/            # Session persistence
│   │   ├── memory/             # Memory system
│   │   ├── hooks/              # Hooks engine
│   │   ├── mcp/                # MCP client
│   │   ├── teams/              # Multi-agent teams
│   │   └── services/           # Ollama, endpoints
│   └── tests/
├── Scripts/                    # Build and packaging scripts
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
