import Foundation

enum SessionService {
    private static let sessionsDir = AnvilConstants.sessionsDirectory

    static func loadSessions() throws -> [Session] {
        try FileManager.default.ensureDirectoryExists(at: sessionsDir)

        let files = try FileManager.default.contentsOfDirectory(atPath: sessionsDir)
            .filter { $0.hasSuffix(".session.json") }

        return files.compactMap { filename in
            let path = "\(sessionsDir)/\(filename)"
            guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else { return nil }
            // Try default (Double) first (Swift-written), then flexible ISO8601 (Python-written)
            if let session = try? JSONDecoder().decode(Session.self, from: data) {
                return session
            }
            return try? ProjectService.flexibleDateDecoder.decode(Session.self, from: data)
        }
    }

    static func saveSession(_ session: Session) throws {
        try FileManager.default.ensureDirectoryExists(at: sessionsDir)

        // Save metadata as .session.json (separate from Python's .jsonl message log)
        let path = "\(sessionsDir)/\(session.id.uuidString).session.json"
        let data = try JSONEncoder().encode(session)
        try data.write(to: URL(fileURLWithPath: path))
    }

    static func deleteSession(_ session: Session) throws {
        let metaPath = "\(sessionsDir)/\(session.id.uuidString).session.json"
        if FileManager.default.fileExists(atPath: metaPath) {
            try FileManager.default.removeItem(atPath: metaPath)
        }
        // Also clean up legacy .jsonl if it was from old format
        let legacyPath = "\(sessionsDir)/\(session.id.uuidString).jsonl"
        if FileManager.default.fileExists(atPath: legacyPath) {
            try? FileManager.default.removeItem(atPath: legacyPath)
        }
    }
}
