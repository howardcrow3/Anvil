import Foundation

private struct FlexibleCodingKeys: CodingKey {
    var stringValue: String
    var intValue: Int?
    init(_ string: String) { self.stringValue = string; self.intValue = nil }
    init?(stringValue: String) { self.stringValue = stringValue; self.intValue = nil }
    init?(intValue: Int) { self.stringValue = "\(intValue)"; self.intValue = intValue }
}

enum ProjectTaskStatus: String, Codable, CaseIterable, Sendable {
    case notStarted = "not_started"
    case inProgress = "in_progress"
    case needsHelp = "needs_help"
    case completed

    var label: String {
        switch self {
        case .notStarted: "Not Started"
        case .inProgress: "In Progress"
        case .needsHelp: "Needs Help"
        case .completed: "Completed"
        }
    }

    var icon: String {
        switch self {
        case .notStarted: "circle"
        case .inProgress: "circle.dotted.circle"
        case .needsHelp: "exclamationmark.circle"
        case .completed: "checkmark.circle.fill"
        }
    }

    var color: String {
        switch self {
        case .notStarted: "secondary"
        case .inProgress: "blue"
        case .needsHelp: "orange"
        case .completed: "green"
        }
    }
}

struct ProjectTask: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    var title: String
    var taskDescription: String
    var status: ProjectTaskStatus
    var sessionId: UUID?
    var createdAt: Date
    var updatedAt: Date

    init(
        id: UUID = UUID(),
        title: String,
        taskDescription: String = "",
        status: ProjectTaskStatus = .notStarted,
        sessionId: UUID? = nil,
        createdAt: Date = Date(),
        updatedAt: Date = Date()
    ) {
        self.id = id
        self.title = title
        self.taskDescription = taskDescription
        self.status = status
        self.sessionId = sessionId
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: FlexibleCodingKeys.self)
        id = try container.decode(UUID.self, forKey: .init("id"))
        title = try container.decodeIfPresent(String.self, forKey: .init("title")) ?? ""
        // Python uses "description", Swift uses "taskDescription"
        taskDescription = try container.decodeIfPresent(String.self, forKey: .init("taskDescription"))
            ?? container.decodeIfPresent(String.self, forKey: .init("task_description"))
            ?? container.decodeIfPresent(String.self, forKey: .init("description"))
            ?? ""
        status = try container.decodeIfPresent(ProjectTaskStatus.self, forKey: .init("status")) ?? .notStarted
        // Handle both camelCase and snake_case
        sessionId = try container.decodeIfPresent(UUID.self, forKey: .init("sessionId"))
            ?? container.decodeIfPresent(UUID.self, forKey: .init("session_id"))
        createdAt = try container.decodeIfPresent(Date.self, forKey: .init("createdAt"))
            ?? container.decodeIfPresent(Date.self, forKey: .init("created_at"))
            ?? Date()
        updatedAt = try container.decodeIfPresent(Date.self, forKey: .init("updatedAt"))
            ?? container.decodeIfPresent(Date.self, forKey: .init("updated_at"))
            ?? Date()
    }
}

struct Project: Identifiable, Codable, Hashable, Sendable {
    let id: UUID
    var name: String
    var folderPath: String
    var githubRepo: String
    var tasks: [ProjectTask]
    var createdAt: Date
    var updatedAt: Date

    init(
        id: UUID = UUID(),
        name: String,
        folderPath: String = "",
        githubRepo: String = "",
        tasks: [ProjectTask] = [],
        createdAt: Date = Date(),
        updatedAt: Date = Date()
    ) {
        self.id = id
        self.name = name
        self.folderPath = folderPath
        self.githubRepo = githubRepo
        self.tasks = tasks
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: FlexibleCodingKeys.self)
        id = try container.decode(UUID.self, forKey: .init("id"))
        name = try container.decodeIfPresent(String.self, forKey: .init("name")) ?? "Untitled"
        folderPath = try container.decodeIfPresent(String.self, forKey: .init("folderPath"))
            ?? container.decodeIfPresent(String.self, forKey: .init("folder_path"))
            ?? ""
        githubRepo = try container.decodeIfPresent(String.self, forKey: .init("githubRepo"))
            ?? container.decodeIfPresent(String.self, forKey: .init("github_repo"))
            ?? ""
        tasks = try container.decodeIfPresent([ProjectTask].self, forKey: .init("tasks")) ?? []
        createdAt = try container.decodeIfPresent(Date.self, forKey: .init("createdAt"))
            ?? container.decodeIfPresent(Date.self, forKey: .init("created_at"))
            ?? Date()
        updatedAt = try container.decodeIfPresent(Date.self, forKey: .init("updatedAt"))
            ?? container.decodeIfPresent(Date.self, forKey: .init("updated_at"))
            ?? Date()
    }

    var progress: Double {
        guard !tasks.isEmpty else { return 0 }
        return Double(tasks.filter { $0.status == .completed }.count) / Double(tasks.count)
    }

    func tasks(for status: ProjectTaskStatus) -> [ProjectTask] {
        tasks.filter { $0.status == status }
    }
}
