import Foundation

@Observable
final class SessionViewModel {
    var sessions: [Session] = []
    var selectedSession: Session?
    var searchText = ""

    var filteredSessions: [Session] {
        if searchText.isEmpty {
            return sessions.sorted { $0.lastActive > $1.lastActive }
        }
        return sessions
            .filter { $0.name.localizedCaseInsensitiveContains(searchText) }
            .sorted { $0.lastActive > $1.lastActive }
    }

    func loadSessions() {
        do {
            sessions = try SessionService.loadSessions()
        } catch {
            sessions = []
        }
    }

    func createSession(name: String, projectPath: String = "") -> Session {
        let session = Session(name: name, projectPath: projectPath)
        sessions.append(session)
        try? SessionService.saveSession(session)
        return session
    }

    func deleteSession(_ session: Session) {
        sessions.removeAll { $0.id == session.id }
        try? SessionService.deleteSession(session)
        if selectedSession?.id == session.id {
            selectedSession = nil
        }
    }

    func resumeSession(_ session: Session) {
        selectedSession = session
    }
}
