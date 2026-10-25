import Foundation

/// Drives the MCP settings tab. The agent runtime is the source of truth (it owns
/// `~/.anvil/mcp-servers.json` and the live connections); this talks to it over IPC.
@Observable
final class MCPViewModel: @unchecked Sendable {
    var servers: [MCPServerConfig] = []
    var isWorking = false
    var statusMessage: String?

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    var isRuntimeConnected: Bool { ipcClient.isConnected }

    // MARK: - Loading

    func load() async {
        guard ipcClient.isConnected else {
            await MainActor.run { statusMessage = "The agent runtime isn't connected." }
            return
        }
        do {
            let data = try await ipcClient.sendRequest(method: "mcp.list")
            let parsed = Self.parseServers(data)
            await MainActor.run {
                if let parsed { servers = parsed }
            }
        } catch {
            await MainActor.run { statusMessage = "Couldn't load MCP servers: \(error.localizedDescription)" }
        }
    }

    func reload() async {
        await run(method: "mcp.reload", params: [:], success: "Reconnected MCP servers")
    }

    // MARK: - Editing

    /// Adds or replaces (matched by `id`) a server, saves, and reconnects. Returns an error message, or nil on success.
    func upsert(_ server: MCPServerConfig) async -> String? {
        var updated = servers
        if let index = updated.firstIndex(where: { $0.id == server.id }) {
            updated[index] = server
        } else {
            updated.append(server)
        }
        return await save(updated, success: "Saved “\(server.name)”")
    }

    func upsert(contentsOf imported: [MCPServerConfig]) async -> String? {
        var updated = servers
        for server in imported {
            // Imported servers replace existing ones with the same name.
            if let index = updated.firstIndex(where: { $0.name == server.name }) {
                var replacement = server
                replacement.id = updated[index].id
                updated[index] = replacement
            } else {
                updated.append(server)
            }
        }
        return await save(updated, success: "Imported \(imported.count) server(s)")
    }

    func delete(_ server: MCPServerConfig) async {
        _ = await save(servers.filter { $0.id != server.id }, success: "Removed “\(server.name)”")
    }

    func setEnabled(_ server: MCPServerConfig, _ enabled: Bool) async {
        var changed = server
        changed.enabled = enabled
        _ = await upsert(changed)
    }

    /// Tries a connection without saving or registering anything.
    func test(_ server: MCPServerConfig) async -> MCPTestResult {
        guard ipcClient.isConnected else {
            return MCPTestResult(ok: false, error: "The agent runtime isn't connected.")
        }
        do {
            let data = try await ipcClient.sendRequest(method: "mcp.test", params: ["server": server.toDict()])
            guard let dict = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
                return MCPTestResult(ok: false, error: "Unexpected response from the runtime.")
            }
            if dict["ok"] as? Bool == true {
                let tools = (dict["tools"] as? [[String: Any]] ?? []).compactMap { tool -> MCPToolInfo? in
                    guard let name = tool["name"] as? String else { return nil }
                    return MCPToolInfo(name: name, description: tool["description"] as? String ?? "")
                }
                return MCPTestResult(ok: true, tools: tools)
            }
            return MCPTestResult(ok: false, error: dict["error"] as? String ?? "Connection failed.")
        } catch {
            return MCPTestResult(ok: false, error: error.localizedDescription)
        }
    }

    // MARK: - Plumbing

    private func save(_ updated: [MCPServerConfig], success: String) async -> String? {
        await run(
            method: "mcp.save",
            params: ["servers": updated.map { $0.toDict() }, "reload": true],
            success: success
        )
    }

    /// Sends a request that returns `{servers: [...]}` or `{error: ...}`. Returns an error message, or nil.
    @discardableResult
    private func run(method: String, params: [String: Any], success: String) async -> String? {
        guard ipcClient.isConnected else {
            let message = "The agent runtime isn't connected."
            await MainActor.run { statusMessage = message }
            return message
        }
        await MainActor.run { isWorking = true }
        defer { Task { @MainActor in isWorking = false } }

        do {
            let data = try await ipcClient.sendRequest(method: method, params: params)
            if let dict = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
               let error = dict["error"] as? String {
                await MainActor.run { statusMessage = error }
                return error
            }
            let parsed = Self.parseServers(data)
            await MainActor.run {
                if let parsed { servers = parsed }
                statusMessage = success
            }
            return nil
        } catch {
            let message = error.localizedDescription
            await MainActor.run { statusMessage = message }
            return message
        }
    }

    private static func parseServers(_ data: Data) -> [MCPServerConfig]? {
        guard let dict = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let list = dict["servers"] as? [[String: Any]]
        else { return nil }
        return list.compactMap(MCPServerConfig.init(dict:))
    }
}
