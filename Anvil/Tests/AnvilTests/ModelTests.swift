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
        #expect(settings.defaultModel == "claude-opus-4-6")
        #expect(settings.permissionMode == .ask)
        #expect(settings.endpoints.isEmpty)
        #expect(settings.mcpServers.isEmpty)
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

    @Test func mcpServerInit() {
        let server = MCPServer(name: "test", command: "/usr/bin/test")
        #expect(server.id == "test")
        #expect(server.enabled == true)
        #expect(server.args.isEmpty)
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
