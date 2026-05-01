import Foundation

extension Date {
    var relativeFormatted: String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: self, relativeTo: Date())
    }

    var shortFormatted: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .short
        formatter.timeStyle = .short
        return formatter.string(from: self)
    }
}

extension String {
    var truncated: String {
        truncated(to: 100)
    }

    func truncated(to length: Int) -> String {
        if count <= length { return self }
        return String(prefix(length)) + "..."
    }
}

extension FileManager {
    func ensureDirectoryExists(at path: String) throws {
        if !fileExists(atPath: path) {
            try createDirectory(atPath: path, withIntermediateDirectories: true)
        }
    }
}
