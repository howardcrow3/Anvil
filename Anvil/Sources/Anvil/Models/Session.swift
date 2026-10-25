import Foundation

struct Session: Identifiable, Codable, Sendable {
    let id: UUID
    var name: String
    var projectPath: String
    var lastActive: Date
    var messageCount: Int

    init(
        id: UUID = UUID(),
        name: String,
        projectPath: String = "",
        lastActive: Date = Date(),
        messageCount: Int = 0
    ) {
        self.id = id
        self.name = name
        self.projectPath = projectPath
        self.lastActive = lastActive
        self.messageCount = messageCount
    }
}
