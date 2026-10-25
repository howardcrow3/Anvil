import Foundation

enum MessageRole: String, Codable, Sendable {
    case user
    case assistant
    case system
    case toolUse = "tool_use"
    case toolResult = "tool_result"
}

struct Message: Identifiable, Sendable {
    let id: UUID
    var role: MessageRole
    var content: String
    var toolCalls: [ToolCall]
    var timestamp: Date

    init(
        id: UUID = UUID(),
        role: MessageRole,
        content: String,
        toolCalls: [ToolCall] = [],
        timestamp: Date = Date()
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.toolCalls = toolCalls
        self.timestamp = timestamp
    }
}
