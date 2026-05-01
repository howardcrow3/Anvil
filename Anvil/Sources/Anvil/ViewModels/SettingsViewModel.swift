import Foundation

@Observable
final class SettingsViewModel: @unchecked Sendable {
    var settings = AppSettings()
    var apiKeyInput = ""
    var isSaving = false
    var statusMessage: String?

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    func loadSettings() {
        // Load from local file
        let path = AnvilConstants.settingsFile
        if FileManager.default.fileExists(atPath: path),
           let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
           let decoded = try? JSONDecoder().decode(AppSettings.self, from: data) {
            settings = decoded
        }
        apiKeyInput = (try? KeychainService.retrieve(key: "anthropic_api_key")) ?? ""

        // Also try IPC
        guard ipcClient.isConnected else { return }
        let client = ipcClient
        Task { @MainActor [weak self] in
            guard let self else { return }
            if let data = try? await client.sendRequest(method: "settings.get"),
               let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if let model = dict["default_model"] as? String { self.settings.defaultModel = model }
                if let mode = dict["permission_mode"] as? String,
                   let permMode = PermissionMode(rawValue: mode) { self.settings.permissionMode = permMode }
                if let port = dict["ollama_port"] as? Int { self.settings.ollamaPort = port }
            }
        }
    }

    func saveSettings() {
        isSaving = true
        defer { isSaving = false }

        do {
            try FileManager.default.ensureDirectoryExists(at: AnvilConstants.dataDirectory)
            let data = try JSONEncoder().encode(settings)
            try data.write(to: URL(fileURLWithPath: AnvilConstants.settingsFile))

            if !apiKeyInput.isEmpty {
                try KeychainService.store(key: "anthropic_api_key", value: apiKeyInput)
            }
        } catch {
            statusMessage = "Failed to save settings locally"
        }

        // Sync to runtime via IPC
        guard ipcClient.isConnected else { return }
        let client = ipcClient
        let model = settings.defaultModel
        let mode = settings.permissionMode.rawValue
        let port = settings.ollamaPort
        let key = apiKeyInput
        Task { @MainActor [weak self] in
            var params: [String: Any] = [
                "default_model": model,
                "permission_mode": mode,
                "ollama_port": port,
            ]
            if !key.isEmpty { params["api_key"] = key }
            let _ = try? await client.sendRequest(method: "settings.set", params: params)
            self?.statusMessage = "Settings saved"
        }
    }

    func addEndpoint(_ endpoint: Endpoint) {
        settings.endpoints.append(endpoint)
        saveSettings()
    }

    func removeEndpoint(_ endpoint: Endpoint) {
        settings.endpoints.removeAll { $0.id == endpoint.id }
        saveSettings()
    }

    func updateEndpoint(_ endpoint: Endpoint) {
        guard let index = settings.endpoints.firstIndex(where: { $0.id == endpoint.id }) else { return }
        settings.endpoints[index] = endpoint
        saveSettings()
    }
}
