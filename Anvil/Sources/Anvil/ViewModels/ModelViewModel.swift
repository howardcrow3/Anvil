import Foundation

@Observable
final class ModelViewModel: @unchecked Sendable {
    var models: [ModelInfo] = []
    var selectedModel: ModelInfo?
    var isLoading = false
    var downloadProgress: Double = 0
    var errorMessage: String?

    private let ipcClient: IPCClient
    private let ollamaService: OllamaService

    init(ipcClient: IPCClient = IPCClient(), ollamaService: OllamaService = OllamaService()) {
        self.ipcClient = ipcClient
        self.ollamaService = ollamaService
        loadDefaultModels()
    }

    private func loadDefaultModels() {
        models = [
            ModelInfo(id: "claude-opus-4-6", name: "Claude Opus 4", provider: .cloud, size: "Cloud"),
            ModelInfo(id: "claude-sonnet-4-6", name: "Claude Sonnet 4", provider: .cloud, size: "Cloud"),
            ModelInfo(id: "claude-haiku-4-5-20251001", name: "Claude Haiku 3.5", provider: .cloud, size: "Cloud"),
            ModelInfo(id: "gemma3:4b", name: "Gemma 3 4B", provider: .local, size: "4B"),
            ModelInfo(id: "gemma3:12b", name: "Gemma 3 12B", provider: .local, size: "12B"),
            ModelInfo(id: "llama4:scout", name: "Llama 4 Scout", provider: .local, size: "109B MoE"),
            ModelInfo(id: "mistral-small:24b", name: "Mistral Small 3.2", provider: .local, size: "24B"),
            ModelInfo(id: "phi4:14b", name: "Phi-4", provider: .local, size: "14B"),
            ModelInfo(id: "qwen3:8b", name: "Qwen 3 8B", provider: .local, size: "8B"),
            ModelInfo(id: "qwen3:32b", name: "Qwen 3 32B", provider: .local, size: "32B"),
        ]
        selectedModel = models.first
    }

    var groupedModels: [(String, [ModelInfo])] {
        let grouped = Dictionary(grouping: models) { $0.provider }
        return ModelProvider.allCases.compactMap { provider in
            guard let group = grouped[provider], !group.isEmpty else { return nil }
            let label: String = switch provider {
            case .cloud: "Cloud"
            case .local: "Local"
            case .custom: "Custom"
            }
            return (label, group)
        }
    }

    func refreshModels() async {
        isLoading = true
        defer { isLoading = false }

        guard ipcClient.isConnected else { return }

        do {
            let responseData = try await ipcClient.sendRequest(method: "model.list")
            if let modelList = try? JSONSerialization.jsonObject(with: responseData) as? [[String: Any]] {
                var refreshed: [ModelInfo] = []
                for item in modelList {
                    let id = item["id"] as? String ?? ""
                    let name = item["name"] as? String ?? id
                    let providerStr = item["provider"] as? String ?? "cloud"
                    let size = item["size"] as? String ?? ""
                    let statusStr = item["status"] as? String ?? "available"
                    let provider: ModelProvider = switch providerStr {
                    case "local": .local
                    case "custom": .custom
                    default: .cloud
                    }
                    let status: ModelStatus = switch statusStr {
                    case "downloading": .downloading
                    case "loaded": .loaded
                    case "error": .error
                    default: .available
                    }
                    refreshed.append(ModelInfo(id: id, name: name, provider: provider, size: size, status: status))
                }
                if !refreshed.isEmpty {
                    models = refreshed
                    if selectedModel == nil || !refreshed.contains(where: { $0.id == selectedModel?.id }) {
                        selectedModel = refreshed.first
                    }
                }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshLocalModels() async {
        do {
            let localModels = try await ollamaService.listModels()
            models.removeAll { $0.provider == .local }
            models.append(contentsOf: localModels)
        } catch {
            // Ollama not running or not available
        }
    }

    func pullModel(name: String) async {
        if let idx = models.firstIndex(where: { $0.id == name }) {
            models[idx].status = .downloading
        }
        do {
            try await ollamaService.pullModel(name: name)
            await refreshLocalModels()
        } catch {
            errorMessage = "Failed to download \(name)"
            if let idx = models.firstIndex(where: { $0.id == name }) {
                models[idx].status = .error
            }
        }
    }

    func deleteModel(name: String) async {
        do {
            try await ollamaService.deleteModel(name: name)
            await refreshLocalModels()
        } catch {
            errorMessage = "Failed to delete \(name)"
        }
    }

    func selectModel(_ model: ModelInfo) {
        selectedModel = model
        guard ipcClient.isConnected else { return }
        let client = ipcClient
        let modelId = model.id
        Task { @MainActor in
            let _ = try? await client.sendRequest(method: "model.select", params: [
                "name": modelId
            ])
        }
    }
}
