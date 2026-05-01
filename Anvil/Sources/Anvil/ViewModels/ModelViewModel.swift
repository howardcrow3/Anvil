import Foundation

@Observable
final class ModelViewModel {
    var models: [ModelInfo] = []
    var selectedModel: ModelInfo?
    var isLoading = false
    var downloadProgress: Double = 0

    private let ollamaService: OllamaService

    init(ollamaService: OllamaService = OllamaService()) {
        self.ollamaService = ollamaService
        loadDefaultModels()
    }

    private func loadDefaultModels() {
        models = [
            ModelInfo(id: "claude-opus-4-6", name: "Claude Opus 4.6", provider: .cloud, size: "Cloud"),
            ModelInfo(id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6", provider: .cloud, size: "Cloud"),
            ModelInfo(id: "claude-haiku-4-5", name: "Claude Haiku 4.5", provider: .cloud, size: "Cloud"),
        ]
        selectedModel = models.first
    }

    var groupedModels: [(String, [ModelInfo])] {
        let grouped = Dictionary(grouping: models) { $0.provider }
        return ModelProvider.allCases.compactMap { provider in
            guard let group = grouped[provider], !group.isEmpty else { return nil }
            return (provider.rawValue.capitalized, group)
        }
    }

    @MainActor
    func refreshLocalModels() async {
        isLoading = true
        defer { isLoading = false }

        do {
            let localModels = try await ollamaService.listModels()
            models.removeAll { $0.provider == .local }
            models.append(contentsOf: localModels)
        } catch {
            // Local models unavailable
        }
    }

    @MainActor
    func pullModel(name: String) async {
        do {
            try await ollamaService.pullModel(name: name)
            await refreshLocalModels()
        } catch {
            // Pull failed
        }
    }

    @MainActor
    func deleteModel(name: String) async {
        do {
            try await ollamaService.deleteModel(name: name)
            await refreshLocalModels()
        } catch {
            // Delete failed
        }
    }

    func selectModel(_ model: ModelInfo) {
        selectedModel = model
    }
}
