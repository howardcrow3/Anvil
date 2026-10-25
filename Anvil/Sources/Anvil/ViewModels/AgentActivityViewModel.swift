import Foundation

@Observable @MainActor
final class AgentActivityViewModel {
    var subagents: [SubagentInfo] = []
    var tasks: [KanbanTaskInfo] = []
    var dispatcherRunning = false
    var curator = CuratorStatusInfo()
    var lastReviewNote: String?
    var errorMessage: String?
    var pendingPermissions: [PermissionRequest] = []

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
        ipcClient.onNotification = { @Sendable [weak self] method, params in
            let note = AgentNotification(method: method, params: params)
            Task { @MainActor [weak self] in self?.handle(note) }
        }
    }

    var activeSubagents: [SubagentInfo] { subagents.filter(\.isActive) }

    func tasks(in status: String) -> [KanbanTaskInfo] { tasks.filter { $0.status == status } }

    // MARK: - Loading

    func load() async {
        await loadSubagents()
        await loadKanban()
        await loadCurator()
    }

    func loadSubagents() async {
        guard let dict = await request("subagents.list"),
              let list = dict["subagents"] as? [[String: Any]] else { return }
        subagents = list.compactMap(SubagentInfo.init)
    }

    func loadKanban() async {
        guard let dict = await request("kanban.list") else { return }
        tasks = (dict["tasks"] as? [[String: Any]] ?? []).compactMap(KanbanTaskInfo.init)
        dispatcherRunning = (dict["dispatcher"] as? [String: Any])?["running"] as? Bool ?? false
    }

    func loadCurator() async {
        guard let dict = await request("curator.status") else { return }
        curator = CuratorStatusInfo(dict)
    }

    // MARK: - Subagent controls

    func steer(_ id: String, message: String) async {
        let text = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        _ = await request("subagents.steer", ["id": id, "message": text])
    }

    func stop(_ id: String) async {
        _ = await request("subagents.stop", ["id": id])
        await loadSubagents()
    }

    func stopAll() async {
        _ = await request("subagents.stop", ["all": true])
        await loadSubagents()
    }

    // MARK: - Kanban

    func createTask(title: String, body: String = "") async {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        _ = await request("kanban.create", ["title": t, "body": body])
        await loadKanban()
    }

    func taskAction(_ id: String, _ action: String, extra: [String: Any] = [:]) async {
        var params = extra
        params["id"] = id
        params["action"] = action
        _ = await request("kanban.action", params)
        await loadKanban()
    }

    func setDispatcher(_ enabled: Bool) async {
        if let dict = await request("kanban.dispatcher", ["enabled": enabled, "stop_workers": !enabled]) {
            dispatcherRunning = dict["running"] as? Bool ?? enabled
        }
    }

    // MARK: - Permissions

    func respond(to request: PermissionRequest, approved: Bool) async {
        pendingPermissions.removeAll { $0.id == request.id }
        _ = await self.request("permission.respond", ["request_id": request.id, "approved": approved])
    }

    // MARK: - Curator

    func runCurator() async {
        _ = await request("curator.run")
        await loadCurator()
    }

    // MARK: - Notifications

    private func handle(_ note: AgentNotification) {
        let params = note.params
        switch note.method {
        case "subagent.update":
            guard let info = SubagentInfo(params) else { return }
            if let i = subagents.firstIndex(where: { $0.id == info.id }) { subagents[i] = info } else { subagents.insert(info, at: 0) }
            // A finished subagent can no longer be waiting on an answer.
            if !info.isActive { pendingPermissions.removeAll { $0.subagentId == info.id } }
        case "subagent.permission_request":
            guard let reqId = params["request_id"] as? String, let tool = params["tool_name"] as? String else { return }
            var args: [String: String] = [:]
            for (k, v) in params["arguments"] as? [String: Any] ?? [:] {
                if let s = v as? String { args[k] = s }
                else if let d = try? JSONSerialization.data(withJSONObject: v), let s = String(data: d, encoding: .utf8) { args[k] = s }
                else { args[k] = "\(v)" }
            }
            let role = params["role"] as? String ?? "subagent"
            let goal = params["goal"] as? String ?? ""
            pendingPermissions.append(PermissionRequest(
                id: reqId, toolName: tool, arguments: args,
                source: "\(role): \(goal)", subagentId: params["subagent_id"] as? String))
        case "kanban.event":
            Task { await loadKanban() }
        case "learning.review":
            if params["saved"] as? Bool == true, let summary = params["summary"] as? String, !summary.isEmpty {
                lastReviewNote = summary
            }
            Task { await loadCurator() }
        case "curator.report":
            Task { await loadCurator() }
        default:
            break
        }
    }

    // MARK: - Transport

    private func request(_ method: String, _ params: [String: Any] = [:]) async -> [String: Any]? {
        guard ipcClient.isConnected else { return nil }
        do {
            let data = try await ipcClient.sendRequest(method: method, params: params)
            let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            if let err = dict?["error"] as? String { errorMessage = err }
            return dict
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }
}
