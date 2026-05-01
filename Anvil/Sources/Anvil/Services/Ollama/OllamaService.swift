import Foundation

@Observable
final class OllamaService: @unchecked Sendable {
    private var process: Process?
    private(set) var isRunning = false
    private(set) var port: Int = AnvilConstants.defaultOllamaPort
    private(set) var localModels: [ModelInfo] = []

    var baseURL: String {
        "\(AnvilConstants.ollamaBaseURL):\(port)"
    }

    func start() async throws {
        if await isPortInUse(AnvilConstants.defaultOllamaPort) {
            if await healthCheck(port: AnvilConstants.defaultOllamaPort) {
                port = AnvilConstants.defaultOllamaPort
                isRunning = true
                return
            }
            port = AnvilConstants.fallbackOllamaPort
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/local/bin/ollama")
        proc.arguments = ["serve"]
        proc.environment = [
            "OLLAMA_HOST": "127.0.0.1:\(port)"
        ]
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice

        do {
            try proc.run()
            process = proc
            try await Task.sleep(for: .seconds(2))
            isRunning = await healthCheck(port: port)
        } catch {
            isRunning = false
            throw OllamaError.failedToStart(error.localizedDescription)
        }
    }

    func stop() {
        process?.terminate()
        process = nil
        isRunning = false
    }

    func listModels() async throws -> [ModelInfo] {
        let url = URL(string: "\(baseURL)/api/tags")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let response = try JSONDecoder().decode(OllamaTagsResponse.self, from: data)
        localModels = response.models.map { model in
            ModelInfo(
                id: model.name,
                name: model.name,
                provider: .local,
                size: formatBytes(model.size),
                status: .available
            )
        }
        return localModels
    }

    func pullModel(name: String) async throws {
        let url = URL(string: "\(baseURL)/api/pull")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["name": name])

        let (_, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw OllamaError.pullFailed(name)
        }
    }

    func deleteModel(name: String) async throws {
        let url = URL(string: "\(baseURL)/api/delete")!
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["name": name])

        let (_, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw OllamaError.deleteFailed(name)
        }
    }

    func healthCheck(port: Int) async -> Bool {
        let url = URL(string: "\(AnvilConstants.ollamaBaseURL):\(port)/api/tags")!
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func isPortInUse(_ port: Int) async -> Bool {
        let url = URL(string: "http://localhost:\(port)")!
        do {
            let (_, _) = try await URLSession.shared.data(from: url)
            return true
        } catch {
            return false
        }
    }

    private func formatBytes(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }
}

private struct OllamaTagsResponse: Codable {
    let models: [OllamaModel]
}

private struct OllamaModel: Codable {
    let name: String
    let size: Int64
}

enum OllamaError: LocalizedError {
    case failedToStart(String)
    case pullFailed(String)
    case deleteFailed(String)

    var errorDescription: String? {
        switch self {
        case .failedToStart(let reason): "Failed to start Ollama: \(reason)"
        case .pullFailed(let model): "Failed to pull model: \(model)"
        case .deleteFailed(let model): "Failed to delete model: \(model)"
        }
    }
}
