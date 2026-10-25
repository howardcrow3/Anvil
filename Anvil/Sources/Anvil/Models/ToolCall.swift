import Foundation

enum ToolCallStatus: String, Codable, Sendable {
    case running
    case done
    case error
}

struct ToolCall: Identifiable, Sendable {
    let id: UUID
    var serverID: String?
    var name: String
    var arguments: [String: String]
    var result: String?
    var status: ToolCallStatus

    init(
        id: UUID = UUID(),
        serverID: String? = nil,
        name: String,
        arguments: [String: String] = [:],
        result: String? = nil,
        status: ToolCallStatus = .running
    ) {
        self.id = id
        self.serverID = serverID
        self.name = name
        self.arguments = arguments
        self.result = result
        self.status = status
    }
}
