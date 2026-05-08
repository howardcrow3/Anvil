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
                    // Python returns "id" (from SessionMetadata model), not "session_id"
                    let idStr = item["id"] as? String ?? item["session_id"] as? String ?? ""
                    guard let id = UUID(uuidString: idStr) else { continue }
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
            let sessionId = session.id.uuidString
            Task { @MainActor in
                let _ = try? await client.sendRequest(method: "session.create", params: [
                    "session_id": sessionId,
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

        let sessionId = session.id.uuidString

        // Load from disk IMMEDIATELY so the view shows content right away
        let diskMessages = Self.loadMessagesFromDisk(sessionId: sessionId)

        if !diskMessages.isEmpty {
            chatVM.messages = diskMessages
        }

        // Then refresh from IPC (may have newer data if runtime processed more messages)
        let client = ipcClient
        guard client.isConnected else { return }

        Task { @MainActor in
            do {
                let data = try await client.sendRequest(method: "session.resume", params: [
                    "session_id": sessionId
                ])
                guard let response = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let msgList = response["messages"] as? [[String: Any]],
                      !msgList.isEmpty else { return }

                var ipcMessages: [Message] = []
                for msg in msgList {
                    let roleStr = msg["role"] as? String ?? "user"
                    let content = msg["content"] as? String ?? ""
                    let role: MessageRole = switch roleStr {
                    case "assistant": .assistant
                    case "system": .system
                    case "tool_use": .toolUse
                    case "tool_result": .toolResult
                    default: .user
                    }
                    if !content.isEmpty {
                        ipcMessages.append(Message(role: role, content: content))
                    }
                }

                // Update only if IPC returned more or different messages
                if !ipcMessages.isEmpty, ipcMessages.count >= chatVM.messages.count {
                    chatVM.messages = ipcMessages
                }
            } catch {
                // Disk messages already displayed, IPC failure is non-critical
            }
        }
    }

    private static func loadMessagesFromDisk(sessionId: String) -> [Message] {
        let path = "\(AnvilConstants.sessionsDirectory)/\(sessionId).jsonl"
        guard let content = try? String(contentsOfFile: path, encoding: .utf8) else { return [] }

        var messages: [Message] = []
        for line in content.components(separatedBy: "\n") where !line.isEmpty {
            guard let data = line.data(using: .utf8),
                  let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let roleStr = dict["role"] as? String,
                  let content = dict["content"] as? String,
                  !content.isEmpty else { continue }

            let role: MessageRole = switch roleStr {
            case "assistant": .assistant
            case "system": .system
            case "tool_use": .toolUse
            case "tool_result": .toolResult
            default: .user
            }
            messages.append(Message(role: role, content: content))
        }
        return messages
    }
}
