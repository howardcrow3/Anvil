import Foundation

@Observable
final class TeamViewModel: @unchecked Sendable {
    var team: AgentTeam?
    var isRunning = false
    var displayMode: TeamDisplayMode = .dashboard
    var focusedTeammateId: UUID?
    var errorMessage: String?

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    // MARK: - Team Lifecycle

    func createTeam(name: String) {
        team = AgentTeam(name: name)
    }

    func createTeamViaIPC(name: String, teammates: [[String: String]] = [], tasks: [[String: String]] = []) async {
        guard ipcClient.isConnected else {
            createTeam(name: name)
            return
        }

        var params: [String: Any] = ["name": name]
        if !teammates.isEmpty { params["members"] = teammates }
        if !tasks.isEmpty { params["tasks"] = tasks }

        do {
            let data = try await ipcClient.sendRequest(method: "team.create", params: params)
            if let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let teamId = dict["team_id"] as? String,
               let uuid = UUID(uuidString: teamId) {
                team = AgentTeam(id: uuid, name: name, status: .running)
                isRunning = true
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func spawnTeammate(name: String, role: String = "general", model: String) async {
        guard ipcClient.isConnected, let teamId = team?.id else { return }

        do {
            let data = try await ipcClient.sendRequest(method: "team.spawn", params: [
                "team_id": teamId.uuidString,
                "name": name,
                "role": role,
                "model": model,
            ])
            if let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               dict["member_id"] is String {
                let teammate = Teammate(name: name, role: role, model: model, state: .idle)
                team?.teammates.append(teammate)
            }
        } catch {
            errorMessage = "Failed to spawn teammate: \(error.localizedDescription)"
        }
    }

    func stopTeammate(_ teammate: Teammate) async {
        guard ipcClient.isConnected else { return }
        let _ = try? await ipcClient.sendRequest(method: "team.stop_teammate", params: [
            "member_id": teammate.id.uuidString
        ])
        if let idx = team?.teammates.firstIndex(where: { $0.id == teammate.id }) {
            team?.teammates[idx].state = .stopped
        }
    }

    func startTeam() {
        team?.status = .running
        isRunning = true
    }

    func stopTeam() {
        guard ipcClient.isConnected else {
            team?.status = .idle
            isRunning = false
            return
        }
        let client = ipcClient
        Task { @MainActor [weak self] in
            let _ = try? await client.sendRequest(method: "team.stop_all")
            self?.team?.status = .idle
            self?.isRunning = false
            self?.team?.teammates.indices.forEach { i in
                self?.team?.teammates[i].state = .stopped
            }
        }
    }

    // MARK: - Tasks

    func createTask(title: String, description: String = "", assignee: String? = nil, dependsOn: [UUID] = []) {
        let task = AgentTask(title: title, description: description, assignee: assignee, dependsOn: dependsOn)
        team?.tasks.append(task)

        guard ipcClient.isConnected, let teamId = team?.id else { return }
        let client = ipcClient
        let taskTitle = title
        let taskDesc = description
        let deps = dependsOn.map { $0.uuidString }
        Task { @MainActor in
            let _ = try? await client.sendRequest(method: "team.task.create", params: [
                "team_id": teamId.uuidString,
                "title": taskTitle,
                "description": taskDesc,
                "depends_on": deps,
                "assigned_to": assignee ?? "",
            ])
        }
    }

    func updateTaskStatus(_ taskId: UUID, status: TaskStatus) {
        guard let index = team?.tasks.firstIndex(where: { $0.id == taskId }) else { return }
        team?.tasks[index].status = status

        guard ipcClient.isConnected else { return }
        let client = ipcClient
        let statusStr = status.rawValue
        Task { @MainActor in
            let _ = try? await client.sendRequest(method: "team.task.update", params: [
                "task_id": taskId.uuidString,
                "status": statusStr,
            ])
        }
    }

    func refreshTasks() async {
        guard ipcClient.isConnected, let teamId = team?.id else { return }
        do {
            let data = try await ipcClient.sendRequest(method: "team.task.list", params: [
                "team_id": teamId.uuidString
            ])
            if let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
                var refreshedTasks: [AgentTask] = []
                for item in list {
                    let id = (item["id"] as? String).flatMap { UUID(uuidString: $0) } ?? UUID()
                    let title = item["title"] as? String ?? ""
                    let desc = item["description"] as? String ?? ""
                    let assignee = item["assigned_to"] as? String
                    let statusStr = item["status"] as? String ?? "pending"
                    let status: TaskStatus = switch statusStr {
                    case "in_progress": .inProgress
                    case "completed": .completed
                    default: .pending
                    }
                    let deps = (item["depends_on"] as? [String])?.compactMap { UUID(uuidString: $0) } ?? []
                    refreshedTasks.append(AgentTask(id: id, title: title, description: desc, assignee: assignee, status: status, dependsOn: deps))
                }
                team?.tasks = refreshedTasks
            }
        } catch {}
    }

    // MARK: - Messages

    func sendMessage(to recipient: String, content: String) {
        guard let teamId = team?.id else { return }
        let msg = TeamMessage(from: "lead", to: recipient, content: content)
        team?.messages.append(msg)

        guard ipcClient.isConnected else { return }
        let client = ipcClient
        let tid = teamId.uuidString
        Task { @MainActor in
            let _ = try? await client.sendRequest(method: "team.message.send", params: [
                "team_id": tid,
                "from_agent": "lead",
                "to_agent": recipient,
                "content": content,
            ])
        }
    }

    func refreshMessages() async {
        guard ipcClient.isConnected, let teamId = team?.id else { return }
        do {
            let data = try await ipcClient.sendRequest(method: "team.message.read", params: [
                "team_id": teamId.uuidString,
                "agent_name": "lead",
            ])
            if let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
                for item in list {
                    let from = item["from"] as? String ?? ""
                    let to = item["to"] as? String ?? ""
                    let content = item["content"] as? String ?? ""
                    let msg = TeamMessage(from: from, to: to, content: content)
                    team?.messages.append(msg)
                }
            }
        } catch {}
    }

    // MARK: - Refresh

    func refreshStatus() async {
        guard ipcClient.isConnected, let teamId = team?.id else { return }
        do {
            let data = try await ipcClient.sendRequest(method: "team.status", params: [
                "team_id": teamId.uuidString
            ])
            if let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                let statusStr = dict["status"] as? String ?? "idle"
                team?.status = TeamStatus(rawValue: statusStr) ?? .idle
                isRunning = team?.status == .running
            }
        } catch {}
        await refreshTasks()
    }

    // MARK: - Display Mode Helpers

    func addTeammate(name: String, model: String) {
        let teammate = Teammate(name: name, model: model)
        team?.teammates.append(teammate)
    }

    func removeTeammate(_ teammate: Teammate) {
        team?.teammates.removeAll { $0.id == teammate.id }
    }

    func addTask(title: String, assignee: String? = nil) {
        let task = AgentTask(title: title, assignee: assignee)
        team?.tasks.append(task)
    }
}
