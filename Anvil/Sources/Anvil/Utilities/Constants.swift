import Foundation

enum AnvilConstants {
    static let appName = "Anvil"
    static let socketPath = "/tmp/anvil.sock"
    static let dataDirectory = "\(NSHomeDirectory())/.anvil"
    static let sessionsDirectory = "\(dataDirectory)/sessions"
    static let settingsFile = "\(dataDirectory)/settings.json"
    static let defaultOllamaPort = 11434
    static let fallbackOllamaPort = 11435
    static let ollamaBaseURL = "http://localhost"
    static let defaultModel = "gemma4:e2b"
}
