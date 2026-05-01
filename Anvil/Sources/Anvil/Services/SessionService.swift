import Foundation

enum SessionService {
    private static let sessionsDir = AnvilConstants.sessionsDirectory

    static func loadSessions() throws -> [Session] {
        try FileManager.default.ensureDirectoryExists(at: sessionsDir)

        let files = try FileManager.default.contentsOfDirectory(atPath: sessionsDir)
            .filter { $0.hasSuffix(".jsonl") }

        return try files.compactMap { filename in
            let path = "\(sessionsDir)/\(filename)"
            let data = try Data(contentsOf: URL(fileURLWithPath: path))
            guard let firstLine = String(data: data, encoding: .utf8)?.components(separatedBy: "\n").first,
                  let lineData = firstLine.data(using: .utf8) else { return nil }
            return try JSONDecoder().decode(Session.self, from: lineData)
        }
    }

    static func saveSession(_ session: Session) throws {
        try FileManager.default.ensureDirectoryExists(at: sessionsDir)

        let path = "\(sessionsDir)/\(session.id.uuidString).jsonl"
        let data = try JSONEncoder().encode(session)
        guard var jsonString = String(data: data, encoding: .utf8) else { return }
        jsonString += "\n"
        try jsonString.write(toFile: path, atomically: true, encoding: .utf8)
    }

    static func deleteSession(_ session: Session) throws {
        let path = "\(sessionsDir)/\(session.id.uuidString).jsonl"
        if FileManager.default.fileExists(atPath: path) {
            try FileManager.default.removeItem(atPath: path)
        }
    }

    static func appendMessage(_ message: Message, toSession sessionId: UUID) throws {
        let path = "\(sessionsDir)/\(sessionId.uuidString).jsonl"
        let entry: [String: String] = [
            "role": message.role.rawValue,
            "content": message.content,
            "timestamp": ISO8601DateFormatter().string(from: message.timestamp)
        ]
        let data = try JSONSerialization.data(withJSONObject: entry)
        guard var line = String(data: data, encoding: .utf8) else { return }
        line += "\n"

        if let handle = FileHandle(forWritingAtPath: path) {
            handle.seekToEndOfFile()
            handle.write(line.data(using: .utf8)!)
            handle.closeFile()
        }
    }
}
