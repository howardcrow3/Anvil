import Foundation

struct SubagentInfo: Identifiable, Sendable, Equatable {
    let id: String
    var goal: String
    var role: String
    var state: String
    var toolCalls: Int
    var elapsed: Double
    var summary: String?
    var error: String?

    var isActive: Bool { state == "pending" || state == "running" }

    init?(_ d: [String: Any]) {
        guard let id = d["id"] as? String else { return nil }
        self.id = id
        goal = d["goal"] as? String ?? ""
        role = d["role"] as? String ?? "worker"
        state = d["state"] as? String ?? "pending"
        toolCalls = d["tool_calls"] as? Int ?? 0
        elapsed = (d["elapsed"] as? NSNumber)?.doubleValue ?? 0
        summary = d["summary"] as? String
        error = d["error"] as? String
    }
}

struct KanbanTaskInfo: Identifiable, Sendable, Equatable {
    let id: String
    var title: String
    var body: String
    var status: String
    var assignee: String?
    var priority: Int
    var result: String?

    init?(_ d: [String: Any]) {
        guard let id = d["id"] as? String else { return nil }
        self.id = id
        title = d["title"] as? String ?? ""
        body = d["body"] as? String ?? ""
        status = d["status"] as? String ?? "todo"
        assignee = d["assignee"] as? String
        priority = d["priority"] as? Int ?? 0
        result = d["result"] as? String
    }
}

struct CuratorStatusInfo: Sendable, Equatable {
    var enabled = true
    var paused = false
    var archived = 0
    var lastRunAt: Date?
    var activeCount = 0
    var staleCount = 0

    init() {}

    init(_ d: [String: Any]) {
        enabled = d["enabled"] as? Bool ?? true
        paused = d["paused"] as? Bool ?? false
        archived = d["archived"] as? Int ?? 0
        if let t = (d["last_run_at"] as? NSNumber)?.doubleValue { lastRunAt = Date(timeIntervalSince1970: t) }
        let counts = d["counts"] as? [String: Any] ?? [:]
        activeCount = counts["active"] as? Int ?? 0
        staleCount = counts["stale"] as? Int ?? 0
    }
}

/// A runtime notification captured as JSON so it can cross actor boundaries safely.
struct AgentNotification: Sendable {
    let method: String
    let json: Data

    init(method: String, params: [String: Any]) {
        self.method = method
        self.json = (try? JSONSerialization.data(withJSONObject: params)) ?? Data()
    }

    var params: [String: Any] {
        (try? JSONSerialization.jsonObject(with: json)) as? [String: Any] ?? [:]
    }
}
