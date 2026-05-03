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

    /// Resolve the Ollama binary path: bundled first, then system PATH.
    private var ollamaPath: String? {
        // 1. Bundled inside Anvil.app/Contents/Resources/ollama/ollama
        if let bundled = Bundle.main.resourceURL?
            .appendingPathComponent("ollama")
            .appendingPathComponent("ollama") {
            if FileManager.default.isExecutableFile(atPath: bundled.path) {
                return bundled.path
            }
        }

        // 2. Common install locations
        let candidates = [
            "/usr/local/bin/ollama",
            "/opt/homebrew/bin/ollama",
            "\(NSHomeDirectory())/.ollama/ollama",
        ]
        for path in candidates {
            if FileManager.default.isExecutableFile(atPath: path) {
                return path
            }
        }

        return nil
    }

    /// The directory containing the Ollama binary and its dylibs.
    private var ollamaDir: String? {
        guard let path = ollamaPath else { return nil }
        return (path as NSString).deletingLastPathComponent
    }

    func start() async throws {
        // Import any bundled models before starting
        importBundledModels()

        // If an existing Ollama is already serving, piggyback on it
        if await isPortInUse(AnvilConstants.defaultOllamaPort) {
            if await healthCheck(port: AnvilConstants.defaultOllamaPort) {
                port = AnvilConstants.defaultOllamaPort
                isRunning = true
                return
            }
            port = AnvilConstants.fallbackOllamaPort
        }

        guard let execPath = ollamaPath else {
            throw OllamaError.failedToStart("Ollama binary not found. It should be bundled in the app or installed at /usr/local/bin/ollama.")
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: execPath)
        proc.arguments = ["serve"]

        // Set environment so Ollama can find its dylibs (Metal, MLX)
        var env = ProcessInfo.processInfo.environment
        env["OLLAMA_HOST"] = "127.0.0.1:\(port)"
        if let dir = ollamaDir {
            let existingPath = env["DYLD_LIBRARY_PATH"] ?? ""
            env["DYLD_LIBRARY_PATH"] = existingPath.isEmpty ? dir : "\(dir):\(existingPath)"
        }
        proc.environment = env
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice

        do {
            try proc.run()
            process = proc
            // Wait for Ollama to start accepting connections
            for _ in 0..<10 {
                try await Task.sleep(for: .milliseconds(500))
                if await healthCheck(port: port) {
                    isRunning = true
                    return
                }
            }
            isRunning = false
            throw OllamaError.failedToStart("Ollama started but health check failed after 5 seconds.")
        } catch let error as OllamaError {
            throw error
        } catch {
            isRunning = false
            throw OllamaError.failedToStart(error.localizedDescription)
        }
    }

    /// Copy bundled model blobs and manifests from the app bundle into ~/.ollama/models/
    /// so they're immediately available without downloading.
    private func importBundledModels() {
        guard let bundledModels = Bundle.main.resourceURL?
            .appendingPathComponent("models") else { return }

        let fm = FileManager.default
        guard fm.fileExists(atPath: bundledModels.path) else { return }

        let ollamaModels = fm.homeDirectoryForCurrentUser
            .appendingPathComponent(".ollama")
            .appendingPathComponent("models")

        // Copy manifests
        let srcManifests = bundledModels.appendingPathComponent("manifests")
        let dstManifests = ollamaModels.appendingPathComponent("manifests")
        if fm.fileExists(atPath: srcManifests.path) {
            copyTreeIfMissing(from: srcManifests, to: dstManifests)
        }

        // Copy blobs
        let srcBlobs = bundledModels.appendingPathComponent("blobs")
        let dstBlobs = ollamaModels.appendingPathComponent("blobs")
        if fm.fileExists(atPath: srcBlobs.path) {
            try? fm.createDirectory(at: dstBlobs, withIntermediateDirectories: true)
            if let items = try? fm.contentsOfDirectory(at: srcBlobs, includingPropertiesForKeys: nil) {
                for item in items {
                    let dest = dstBlobs.appendingPathComponent(item.lastPathComponent)
                    if !fm.fileExists(atPath: dest.path) {
                        try? fm.copyItem(at: item, to: dest)
                        NSLog("[Anvil] Imported bundled model blob: %@", item.lastPathComponent)
                    }
                }
            }
        }
    }

    /// Recursively copy directory tree, only copying files that don't already exist at destination.
    private func copyTreeIfMissing(from src: URL, to dst: URL) {
        let fm = FileManager.default
        try? fm.createDirectory(at: dst, withIntermediateDirectories: true)
        guard let items = try? fm.contentsOfDirectory(at: src, includingPropertiesForKeys: [.isDirectoryKey]) else { return }
        for item in items {
            let destItem = dst.appendingPathComponent(item.lastPathComponent)
            let isDir = (try? item.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) ?? false
            if isDir {
                copyTreeIfMissing(from: item, to: destItem)
            } else if !fm.fileExists(atPath: destItem.path) {
                try? fm.copyItem(at: item, to: destItem)
            }
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
