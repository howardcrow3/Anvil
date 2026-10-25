import Foundation

enum ModelProvider: String, Codable, Sendable, CaseIterable {
    case cloud
    case local
    case custom
}

enum ModelStatus: String, Codable, Sendable {
    case available
    case downloading
    case loaded
    case error
}

struct ModelInfo: Identifiable, Codable, Sendable {
    let id: String
    var name: String
    var provider: ModelProvider
    var size: String
    var status: ModelStatus
    var endpoint: String?

    init(
        id: String,
        name: String,
        provider: ModelProvider,
        size: String = "",
        status: ModelStatus = .available,
        endpoint: String? = nil
    ) {
        self.id = id
        self.name = name
        self.provider = provider
        self.size = size
        self.status = status
        self.endpoint = endpoint
    }
}
