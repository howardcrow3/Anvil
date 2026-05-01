import Foundation

@Observable
final class SettingsViewModel {
    var settings = AppSettings()
    var apiKeyInput = ""
    var isSaving = false

    func loadSettings() {
        let path = AnvilConstants.settingsFile
        guard FileManager.default.fileExists(atPath: path),
              let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
              let decoded = try? JSONDecoder().decode(AppSettings.self, from: data) else {
            return
        }
        settings = decoded
        apiKeyInput = (try? KeychainService.retrieve(key: "anthropic_api_key")) ?? ""
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
            // Save failed
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
