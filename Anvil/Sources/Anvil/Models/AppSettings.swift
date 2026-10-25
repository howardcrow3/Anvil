import Foundation

enum PermissionMode: String, Codable, Sendable {
    case ask
    case acceptEdits = "accept_edits"
    case trust
}

struct AppSettings: Codable, Sendable {
    var apiKey: String
    var defaultModel: String
    var permissionMode: PermissionMode
    var endpoints: [Endpoint]
    var ollamaPort: Int
    var dataDirectory: String
    var theme: String

    init(
        apiKey: String = "",
        defaultModel: String = "claude-opus-5-5",
        permissionMode: PermissionMode = .ask,
        endpoints: [Endpoint] = [],
        ollamaPort: Int = 11434,
        dataDirectory: String = "~/.anvil",
        theme: String = "system"
    ) {
        self.apiKey = apiKey
        self.defaultModel = defaultModel
        self.permissionMode = permissionMode
        self.endpoints = endpoints
        self.ollamaPort = ollamaPort
        self.dataDirectory = dataDirectory
        self.theme = theme
    }
}
