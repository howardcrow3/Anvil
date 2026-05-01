import Foundation

enum TeamStatus: String, Codable, Sendable {
    case idle
    case running
    case paused
    case completed
}

enum TaskStatus: String, Codable, Sendable {
    case pending
    case inProgress = "in_progress"
    case completed
}

enum TeammateState: String, Codable, Sendable {
    case idle
    case working
    case blocked
    case stopped
}

struct AgentTask: Identifiable, Codable, Sendable {
    let id: UUID
    var title: String
    var description: String
    var assignee: String?
    var status: TaskStatus
    var dependsOn: [UUID]

    init(
        id: UUID = UUID(),
        title: String,
        description: String = "",
        assignee: String? = nil,
        status: TaskStatus = .pending,
        dependsOn: [UUID] = []
    ) {
        self.id = id
        self.title = title
        self.description = description
        self.assignee = assignee
        self.status = status
        self.dependsOn = dependsOn
    }

    var isBlocked: Bool {
        !dependsOn.isEmpty
    }
}

struct TeamMessage: Identifiable, Codable, Sendable {
    let id: UUID
    var from: String
    var to: String
    var content: String
    var timestamp: Date

    init(
        id: UUID = UUID(),
        from: String,
        to: String,
        content: String,
        timestamp: Date = Date()
    ) {
        self.id = id
        self.from = from
        self.to = to
        self.content = content
        self.timestamp = timestamp
    }
}

struct Teammate: Identifiable, Codable, Sendable {
    let id: UUID
    var name: String
    var role: String
    var model: String
    var state: TeammateState
    var currentTask: String?
    var messages: Int

    init(
        id: UUID = UUID(),
        name: String,
        role: String = "general",
        model: String,
        state: TeammateState = .idle,
        currentTask: String? = nil,
        messages: Int = 0
    ) {
        self.id = id
        self.name = name
        self.role = role
        self.model = model
        self.state = state
        self.currentTask = currentTask
        self.messages = messages
    }

    var isActive: Bool { state == .working }
}

struct AgentTeam: Identifiable, Codable, Sendable {
    let id: UUID
    var name: String
    var teammates: [Teammate]
    var tasks: [AgentTask]
    var messages: [TeamMessage]
    var status: TeamStatus

    init(
        id: UUID = UUID(),
        name: String,
        teammates: [Teammate] = [],
        tasks: [AgentTask] = [],
        messages: [TeamMessage] = [],
        status: TeamStatus = .idle
    ) {
        self.id = id
        self.name = name
        self.teammates = teammates
        self.tasks = tasks
        self.messages = messages
        self.status = status
    }

    var progress: Double {
        guard !tasks.isEmpty else { return 0 }
        return Double(tasks.filter { $0.status == .completed }.count) / Double(tasks.count)
    }

    var pendingTasks: [AgentTask] { tasks.filter { $0.status == .pending } }
    var inProgressTasks: [AgentTask] { tasks.filter { $0.status == .inProgress } }
    var completedTasks: [AgentTask] { tasks.filter { $0.status == .completed } }
}
