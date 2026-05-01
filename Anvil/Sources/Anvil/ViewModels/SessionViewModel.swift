import Foundation

@Observable
final class SessionViewModel: @unchecked Sendable {
    var sessions: [Session] = []
    var selectedSession: Session?
    var searchText = ""

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    var filteredSessions: [Session] {
        if searchText.isEmpty {
            return sessions.sorted { $0.lastActive > $1.lastActive }
        }
        return sessions
            .filter { $0.name.localizedCaseInsensitiveContains(searchText) }
            .sorted { $0.lastActive > $1.lastActive }
    }

    func loadSessions() {
        // Try local first, then IPC
        do {
            sessions = try SessionService.loadSessions()
        } catch {
            sessions = []
        }

        guard ipcClient.isConnected else { return }
        let client = ipcClient
        Task { @MainActor [weak self] in
            guard let self else { return }
            let data = try? await client.sendRequest(method: "session.list")
            if let data,
               let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
                var remoteSessions: [Session] = []
                for item in list {
                    let id = (item["session_id"] as? String).flatMap { UUID(uuidString: $0) } ?? UUID()
                    let name = item["name"] as? String ?? "Untitled"
                    let projectPath = item["project_path"] as? String ?? ""
                    let messageCount = item["message_count"] as? Int ?? 0
                    let lastActive = (item["last_active"] as? String).flatMap { ISO8601DateFormatter().date(from: $0) } ?? Date()
                    remoteSessions.append(Session(id: id, name: name, projectPath: projectPath, lastActive: lastActive, messageCount: messageCount))
                }
                if !remoteSessions.isEmpty {
                    self.sessions = remoteSessions
                }
            }
        }
    }

    @discardableResult
    func createSession(name: String, projectPath: String = "") -> Session {
        let session = Session(name: name, projectPath: projectPath)
        sessions.append(session)
        try? SessionService.saveSession(session)

        if ipcClient.isConnected {
            let client = ipcClient
            Task { @MainActor in
                let _ = try? await client.sendRequest(method: "session.create", params: [
                    "name": name,
                    "project_path": projectPath
                ])
            }
        }
        return session
    }

    func deleteSession(_ session: Session) {
        sessions.removeAll { $0.id == session.id }
        try? SessionService.deleteSession(session)
        if selectedSession?.id == session.id {
            selectedSession = nil
        }
    }

    @MainActor
    func resumeSession(_ session: Session, chatVM: ChatViewModel) {
        selectedSession = session
        chatVM.loadSession(session)

        if ipcClient.isConnected {
            let client = ipcClient
            let sessionId = session.id.uuidString
            Task { @MainActor in
                let _ = try? await client.sendRequest(method: "session.resume", params: [
                    "session_id": sessionId
                ])
            }
        }
    }
}
