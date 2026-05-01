import Foundation

enum PermissionMode: String, Codable, Sendable {
    case ask
    case acceptEdits = "accept_edits"
    case trust
}

struct MCPServer: Codable, Sendable, Identifiable {
    var id: String { name }
    var name: String
    var command: String
    var args: [String]
    var enabled: Bool

    init(name: String, command: String, args: [String] = [], enabled: Bool = true) {
        self.name = name
        self.command = command
        self.args = args
        self.enabled = enabled
    }
}

struct AppSettings: Codable, Sendable {
    var apiKey: String
    var defaultModel: String
    var permissionMode: PermissionMode
    var endpoints: [Endpoint]
    var mcpServers: [MCPServer]
    var ollamaPort: Int
    var dataDirectory: String
    var theme: String

    init(
        apiKey: String = "",
        defaultModel: String = "claude-opus-4-6",
        permissionMode: PermissionMode = .ask,
        endpoints: [Endpoint] = [],
        mcpServers: [MCPServer] = [],
        ollamaPort: Int = 11434,
        dataDirectory: String = "~/.anvil",
        theme: String = "system"
    ) {
        self.apiKey = apiKey
        self.defaultModel = defaultModel
        self.permissionMode = permissionMode
        self.endpoints = endpoints
        self.mcpServers = mcpServers
        self.ollamaPort = ollamaPort
        self.dataDirectory = dataDirectory
        self.theme = theme
    }
}
