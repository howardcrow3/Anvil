import Foundation

struct Endpoint: Identifiable, Codable, Sendable {
    let id: UUID
    var name: String
    var baseURL: String
    var apiKey: String
    var defaultModel: String
    var isReachable: Bool

    init(
        id: UUID = UUID(),
        name: String,
        baseURL: String,
        apiKey: String = "",
        defaultModel: String = "",
        isReachable: Bool = false
    ) {
        self.id = id
        self.name = name
        self.baseURL = baseURL
        self.apiKey = apiKey
        self.defaultModel = defaultModel
        self.isReachable = isReachable
    }
}
