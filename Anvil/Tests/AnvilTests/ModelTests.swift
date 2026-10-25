import Testing
import Foundation
@testable import Anvil

@Suite("ModelInfo Tests")
struct ModelInfoTests {
    @Test func modelInfoInit() {
        let model = ModelInfo(id: "test-model", name: "Test Model", provider: .local)
        #expect(model.id == "test-model")
        #expect(model.name == "Test Model")
        #expect(model.provider == .local)
        #expect(model.size == "")
        #expect(model.status == .available)
        #expect(model.endpoint == nil)
    }

    @Test func modelInfoWithAllFields() {
        let model = ModelInfo(
            id: "custom",
            name: "Custom",
            provider: .custom,
            size: "4.2 GB",
            status: .loaded,
            endpoint: "http://localhost:8080"
        )
        #expect(model.size == "4.2 GB")
        #expect(model.status == .loaded)
        #expect(model.endpoint == "http://localhost:8080")
    }

    @Test func modelProviderCases() {
        #expect(ModelProvider.allCases.count == 3)
        #expect(ModelProvider.cloud.rawValue == "cloud")
        #expect(ModelProvider.local.rawValue == "local")
        #expect(ModelProvider.custom.rawValue == "custom")
    }

    @Test func modelStatusRawValues() {
        #expect(ModelStatus.available.rawValue == "available")
        #expect(ModelStatus.downloading.rawValue == "downloading")
        #expect(ModelStatus.loaded.rawValue == "loaded")
        #expect(ModelStatus.error.rawValue == "error")
    }

    @Test func modelInfoCodable() throws {
        let model = ModelInfo(id: "encode-test", name: "Encode", provider: .cloud, size: "1 GB")
        let data = try JSONEncoder().encode(model)
        let decoded = try JSONDecoder().decode(ModelInfo.self, from: data)
        #expect(decoded.id == model.id)
        #expect(decoded.name == model.name)
        #expect(decoded.provider == model.provider)
    }
}

@Suite("Message Tests")
struct MessageTests {
    @Test func messageInit() {
        let msg = Message(role: .user, content: "Hello")
        #expect(msg.role == .user)
        #expect(msg.content == "Hello")
        #expect(msg.toolCalls.isEmpty)
    }

    @Test func messageRoleRawValues() {
        #expect(MessageRole.user.rawValue == "user")
        #expect(MessageRole.assistant.rawValue == "assistant")
        #expect(MessageRole.system.rawValue == "system")
        #expect(MessageRole.toolUse.rawValue == "tool_use")
        #expect(MessageRole.toolResult.rawValue == "tool_result")
    }

    @Test func messageWithToolCalls() {
        let tool = ToolCall(name: "read_file", arguments: ["path": "/tmp/test.txt"])
        let msg = Message(role: .assistant, content: "Reading file...", toolCalls: [tool])
        #expect(msg.toolCalls.count == 1)
        #expect(msg.toolCalls[0].name == "read_file")
    }
}

@Suite("Session Tests")
struct SessionTests {
    @Test func sessionInit() {
        let session = Session(name: "Test Session")
        #expect(session.name == "Test Session")
        #expect(session.projectPath == "")
        #expect(session.messageCount == 0)
    }

    @Test func sessionCodable() throws {
        let session = Session(name: "Codec", projectPath: "/tmp/project", messageCount: 5)
        let data = try JSONEncoder().encode(session)
        let decoded = try JSONDecoder().decode(Session.self, from: data)
        #expect(decoded.name == session.name)
        #expect(decoded.projectPath == session.projectPath)
        #expect(decoded.messageCount == 5)
    }
}

@Suite("ToolCall Tests")
struct ToolCallTests {
    @Test func toolCallInit() {
        let tc = ToolCall(name: "bash", arguments: ["command": "ls"])
        #expect(tc.name == "bash")
        #expect(tc.arguments["command"] == "ls")
        #expect(tc.status == .running)
        #expect(tc.result == nil)
    }

    @Test func toolCallStatusRawValues() {
        #expect(ToolCallStatus.running.rawValue == "running")
        #expect(ToolCallStatus.done.rawValue == "done")
        #expect(ToolCallStatus.error.rawValue == "error")
    }
}

@Suite("Endpoint Tests")
struct EndpointTests {
    @Test func endpointInit() {
        let ep = Endpoint(name: "Local LLM", baseURL: "http://localhost:8080")
        #expect(ep.name == "Local LLM")
        #expect(ep.baseURL == "http://localhost:8080")
        #expect(ep.apiKey == "")
        #expect(ep.defaultModel == "")
        #expect(ep.isReachable == false)
    }

    @Test func endpointCodable() throws {
        let ep = Endpoint(name: "Test", baseURL: "http://test:1234", apiKey: "sk-test")
        let data = try JSONEncoder().encode(ep)
        let decoded = try JSONDecoder().decode(Endpoint.self, from: data)
        #expect(decoded.name == ep.name)
        #expect(decoded.apiKey == "sk-test")
    }
}

@Suite("AppSettings Tests")
struct AppSettingsTests {
    @Test func appSettingsDefaults() {
        let settings = AppSettings()
        #expect(settings.apiKey == "")
        #expect(settings.defaultModel == "claude-opus-5-5")
        #expect(settings.permissionMode == .ask)
        #expect(settings.endpoints.isEmpty)
        #expect(settings.ollamaPort == 11434)
        #expect(settings.theme == "system")
    }

    @Test func appSettingsCodable() throws {
        let settings = AppSettings(apiKey: "sk-round-trip", ollamaPort: 9999)
        let data = try JSONEncoder().encode(settings)
        let decoded = try JSONDecoder().decode(AppSettings.self, from: data)
        #expect(decoded.apiKey == "sk-round-trip")
        #expect(decoded.ollamaPort == 9999)
    }

    @Test func permissionModeRawValues() {
        #expect(PermissionMode.ask.rawValue == "ask")
        #expect(PermissionMode.acceptEdits.rawValue == "accept_edits")
        #expect(PermissionMode.trust.rawValue == "trust")
    }
}

@Suite("AgentTeam Tests")
struct AgentTeamTests {
    @Test func agentTeamProgress() {
        var team = AgentTeam(name: "Test")
        #expect(team.progress == 0)

        team.tasks = [
            AgentTask(title: "Done", status: .completed),
            AgentTask(title: "Pending"),
            AgentTask(title: "WIP", status: .inProgress),
        ]
        #expect(abs(team.progress - 1.0 / 3.0) < 0.01)
    }

    @Test func agentTeamFilters() {
        let team = AgentTeam(
            name: "Filter",
            tasks: [
                AgentTask(title: "A", status: .pending),
                AgentTask(title: "B", status: .inProgress),
                AgentTask(title: "C", status: .completed),
                AgentTask(title: "D", status: .completed),
            ]
        )
        #expect(team.pendingTasks.count == 1)
        #expect(team.inProgressTasks.count == 1)
        #expect(team.completedTasks.count == 2)
    }

    @Test func agentTaskIsBlocked() {
        let blocked = AgentTask(title: "Blocked", dependsOn: [UUID()])
        #expect(blocked.isBlocked)

        let free = AgentTask(title: "Free")
        #expect(!free.isBlocked)
    }

    @Test func teammateIsActive() {
        let working = Teammate(name: "Worker", model: "test", state: .working)
        #expect(working.isActive)

        let idle = Teammate(name: "Idle", model: "test", state: .idle)
        #expect(!idle.isActive)
    }

    @Test func teamStatusRawValues() {
        #expect(TeamStatus.idle.rawValue == "idle")
        #expect(TeamStatus.running.rawValue == "running")
        #expect(TeamStatus.paused.rawValue == "paused")
        #expect(TeamStatus.completed.rawValue == "completed")
    }

    @Test func teammateStateRawValues() {
        #expect(TeammateState.idle.rawValue == "idle")
        #expect(TeammateState.working.rawValue == "working")
        #expect(TeammateState.blocked.rawValue == "blocked")
        #expect(TeammateState.stopped.rawValue == "stopped")
    }
}

@Suite("Constants Tests")
struct ConstantsTests {
    @Test func anvilConstants() {
        #expect(AnvilConstants.appName == "Anvil")
        #expect(AnvilConstants.defaultOllamaPort == 11434)
        #expect(AnvilConstants.fallbackOllamaPort == 11435)
        #expect(AnvilConstants.socketPath.contains("anvil"))
        #expect(AnvilConstants.ollamaBaseURL.hasPrefix("http://"))
    }
}


@Suite("MCPServerConfig Tests")
struct MCPServerConfigTests {
    @Test func dictRoundTrip() throws {
        var server = MCPServerConfig(name: "files", command: "npx", args: ["-y", "pkg"])
        server.env = [MCPKeyValue(key: "TOKEN", value: "abc"), MCPKeyValue(key: "  ", value: "dropped")]
        let dict = server.toDict()
        #expect(dict["transport"] as? String == "stdio")
        #expect(dict["args"] as? [String] == ["-y", "pkg"])
        #expect((dict["env"] as? [String: String]) == ["TOKEN": "abc"])

        let decoded = try #require(MCPServerConfig(dict: dict))
        #expect(decoded.id == "files")
        #expect(decoded.command == "npx")
        #expect(decoded.env.map(\.key) == ["TOKEN"])
    }

    @Test func runtimeStatusParsing() throws {
        let dict: [String: Any] = [
            "name": "web", "transport": "http", "url": "https://x.test/mcp", "enabled": true,
            "status": "failed", "error": "boom",
            "tools": [["name": "mcp__web__add", "description": "Add"]],
        ]
        let server = try #require(MCPServerConfig(dict: dict))
        #expect(server.transport == .http)
        #expect(server.state == .failed)
        #expect(server.error == "boom")
        #expect(server.tools.map(\.name) == ["mcp__web__add"])
        #expect(MCPServerConfig(dict: ["transport": "stdio"]) == nil)
    }

    @Test func validation() {
        #expect(MCPServerConfig().validationError(otherNames: []) != nil)
        #expect(MCPServerConfig(name: "a", command: "x").validationError(otherNames: []) == nil)
        #expect(MCPServerConfig(name: "a", command: "x").validationError(otherNames: ["a"]) != nil)
        #expect(MCPServerConfig(name: "a", command: " ").validationError(otherNames: []) != nil)
        #expect(MCPServerConfig(name: "a", transport: .http, url: "ftp://x").validationError(otherNames: []) != nil)
        #expect(MCPServerConfig(name: "a", transport: .sse, url: "https://x.test/sse").validationError(otherNames: []) == nil)
    }

    @Test func parseArgsSplitsLinesAndDropsBlanks() {
        #expect(MCPServerConfig.parseArgs("-y\n  pkg \n\n/tmp\n") == ["-y", "pkg", "/tmp"])
    }

    @Test func importClaudeDesktopConfig() throws {
        let json = """
        {"mcpServers": {
          "files": {"command": "npx", "args": ["-y", "srv"], "env": {"A": "1"}},
          "remote": {"url": "https://x.test/mcp", "headers": {"Authorization": "Bearer t"}},
          "legacy": {"url": "https://x.test/sse"},
          "off": {"command": "x", "disabled": true},
          "junk": 5
        }}
        """
        let servers = try MCPServerConfig.parseImport(json)
        let byName = Dictionary(uniqueKeysWithValues: servers.map { ($0.name, $0) })
        #expect(byName.count == 4)
        #expect(byName["files"]?.transport == .stdio)
        #expect(byName["files"]?.args == ["-y", "srv"])
        #expect(byName["remote"]?.transport == .http)
        #expect(byName["remote"]?.headers.first?.key == "Authorization")
        #expect(byName["legacy"]?.transport == .sse)
        #expect(byName["off"]?.enabled == false)
    }

    @Test func importRejectsGarbage() {
        #expect(throws: MCPImportError.self) { try MCPServerConfig.parseImport("not json") }
        #expect(throws: MCPImportError.self) { try MCPServerConfig.parseImport("{\"mcpServers\": {}}") }
    }
}
