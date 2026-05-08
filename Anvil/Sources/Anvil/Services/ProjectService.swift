import Foundation

enum ProjectService {
    private static let projectsDir = AnvilConstants.projectsDirectory

    /// ISO8601 formatter that handles fractional seconds (Python's default output)
    private static let flexibleISO8601: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSSZZZZZ"
        f.timeZone = TimeZone(secondsFromGMT: 0)
        return f
    }()

    /// Standard ISO8601 without fractional seconds
    private static let standardISO8601: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ssZZZZZ"
        f.timeZone = TimeZone(secondsFromGMT: 0)
        return f
    }()

    /// ISO8601 without timezone (Z suffix handled separately)
    private static let iso8601WithZ: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss'Z'"
        f.timeZone = TimeZone(secondsFromGMT: 0)
        return f
    }()

    static var flexibleDateDecoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let str = try container.decode(String.self)
            if let date = flexibleISO8601.date(from: str) { return date }
            if let date = standardISO8601.date(from: str) { return date }
            if let date = iso8601WithZ.date(from: str) { return date }
            if let date = ISO8601DateFormatter().date(from: str) { return date }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot parse date: \(str)")
        }
        return decoder
    }

    static func loadProjects() throws -> [Project] {
        try FileManager.default.ensureDirectoryExists(at: projectsDir)

        let files = try FileManager.default.contentsOfDirectory(atPath: projectsDir)
            .filter { $0.hasSuffix(".json") }

        let decoder = flexibleDateDecoder

        return files.compactMap { filename in
            let path = "\(projectsDir)/\(filename)"
            guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)) else { return nil }
            return try? decoder.decode(Project.self, from: data)
        }
        .sorted { $0.updatedAt > $1.updatedAt }
    }

    static func saveProject(_ project: Project) throws {
        try FileManager.default.ensureDirectoryExists(at: projectsDir)

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = .prettyPrinted
        let data = try encoder.encode(project)
        let path = "\(projectsDir)/\(project.id.uuidString).json"
        try data.write(to: URL(fileURLWithPath: path))
    }

    static func deleteProject(_ project: Project) throws {
        let path = "\(projectsDir)/\(project.id.uuidString).json"
        if FileManager.default.fileExists(atPath: path) {
            try FileManager.default.removeItem(atPath: path)
        }
    }
}
