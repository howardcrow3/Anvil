# Anvil Project

macOS desktop AI agent app built with SwiftUI (frontend) and Python (agent runtime).

## Project Structure
- `Anvil/` - SwiftUI macOS app (Swift Package Manager)
- `AgentRuntime/` - Python agent runtime
- `Scripts/` - Build and packaging scripts
- `Resources/` - App icons, default configs, Info.plist

## Build Commands
- Swift app: `cd Anvil && swift build`
- Python runtime: `cd AgentRuntime && pip install -e .`
- Full dev run: `./Scripts/run-dev.sh`
- Package DMG: `./Scripts/package-dmg.sh`

## Key Conventions
- Swift: Use @Observable macro, async/await, SwiftUI NavigationSplitView
- Python: Use Pydantic v2, asyncio, type hints everywhere
- IPC: Unix domain socket at /tmp/anvil-agent.sock with JSON-RPC 2.0
- All tools shared between Claude and local model paths
