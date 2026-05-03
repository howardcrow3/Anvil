import Foundation

@Observable
final class AgentRuntimeService: @unchecked Sendable {
    private var process: Process?
    private(set) var isRunning = false
    private(set) var socketPath: String?
    private(set) var lastError: String?

    private var restartTask: Task<Void, Never>?
    private var shouldAutoRestart = true

    func start(
        projectDir: String = FileManager.default.currentDirectoryPath,
        model: String = AnvilConstants.defaultModel,
        provider: String = "ollama"
    ) async throws {
        let pythonPath = findPython()
        guard let pythonPath else {
            throw RuntimeError.pythonNotFound
        }

        let runtimeDir = findRuntimeDir()
        guard let runtimeDir else {
            throw RuntimeError.runtimeNotFound
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: pythonPath)
        proc.arguments = [
            "-m", "anvil_agent",
            "--project-dir", projectDir,
            "--model", model,
            "--provider", provider
        ]
        proc.currentDirectoryURL = URL(fileURLWithPath: runtimeDir)

        // Set PYTHONPATH so bundled site-packages and anvil_agent are importable
        var env = ProcessInfo.processInfo.environment
        let sitePackagesPath = runtimeDir + "/site-packages"
        if let existing = env["PYTHONPATH"] {
            env["PYTHONPATH"] = runtimeDir + ":" + sitePackagesPath + ":" + existing
        } else {
            env["PYTHONPATH"] = runtimeDir + ":" + sitePackagesPath
        }
        proc.environment = env

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        proc.standardOutput = stdoutPipe
        proc.standardError = stderrPipe

        proc.terminationHandler = { [weak self] proc in
            guard let self else { return }
            self.isRunning = false
            self.socketPath = nil
            stderrPipe.fileHandleForReading.readabilityHandler = nil
            if proc.terminationStatus != 0 {
                self.lastError = "Python runtime exited with code \(proc.terminationStatus)"
                NSLog("[AnvilRuntime] Process exited with status %d (reason: %d)", proc.terminationStatus, proc.terminationReason.rawValue)
            }
            if self.shouldAutoRestart && proc.terminationReason == .uncaughtSignal {
                self.scheduleRestart(projectDir: projectDir, model: model, provider: provider)
            }
        }

        // Capture stderr for diagnostics
        stderrPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty, let output = String(data: data, encoding: .utf8) else { return }
            let trimmed = output.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                NSLog("[AnvilRuntime stderr] %@", trimmed)
            }
        }

        lastError = nil
        try proc.run()
        process = proc
        isRunning = true

        socketPath = try await readSocketPath(from: stdoutPipe)
    }

    func stop() {
        shouldAutoRestart = false
        restartTask?.cancel()
        restartTask = nil

        guard let process, process.isRunning else {
            process = nil
            isRunning = false
            socketPath = nil
            return
        }

        process.terminate()

        DispatchQueue.global().asyncAfter(deadline: .now() + 3) { [weak self] in
            guard let self, let proc = self.process, proc.isRunning else { return }
            proc.interrupt()
        }

        self.process = nil
        isRunning = false
        socketPath = nil
    }

    private func readSocketPath(from pipe: Pipe) async throws -> String {
        try await withCheckedThrowingContinuation { continuation in
            nonisolated(unsafe) var resumed = false
            pipe.fileHandleForReading.readabilityHandler = { handle in
                let data = handle.availableData
                guard !data.isEmpty else {
                    if !resumed {
                        resumed = true
                        continuation.resume(throwing: RuntimeError.noSocketPath)
                    }
                    return
                }
                guard let output = String(data: data, encoding: .utf8) else { return }

                for line in output.components(separatedBy: "\n") {
                    if line.hasPrefix("SOCKET:") {
                        let path = String(line.dropFirst("SOCKET:".count)).trimmingCharacters(in: .whitespacesAndNewlines)
                        if !resumed {
                            resumed = true
                            pipe.fileHandleForReading.readabilityHandler = nil
                            continuation.resume(returning: path)
                        }
                        return
                    }
                }
            }

            DispatchQueue.global().asyncAfter(deadline: .now() + 15) {
                if !resumed {
                    resumed = true
                    pipe.fileHandleForReading.readabilityHandler = nil
                    continuation.resume(throwing: RuntimeError.timeout)
                }
            }
        }
    }

    private func scheduleRestart(projectDir: String, model: String, provider: String) {
        restartTask?.cancel()
        restartTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled, let self, self.shouldAutoRestart else { return }
            try? await self.start(projectDir: projectDir, model: model, provider: provider)
        }
    }

    private func findPython() -> String? {
        let bundledPath = Bundle.main.resourcePath.map { "\($0)/python3/bin/python3" }
        if let bundledPath, FileManager.default.fileExists(atPath: bundledPath) {
            return bundledPath
        }

        // Prefer framework/Homebrew Python (3.10+) over system Python (may be 3.9)
        // The codebase uses X | None syntax which requires Python 3.10+
        let candidates = [
            "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ]
        for path in candidates {
            guard FileManager.default.fileExists(atPath: path) else { continue }
            // Verify version is 3.10+
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: path)
            proc.arguments = ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"]
            let devNull = Pipe()
            proc.standardOutput = devNull
            proc.standardError = devNull
            do {
                try proc.run()
                proc.waitUntilExit()
                if proc.terminationStatus == 0 {
                    return path
                }
            } catch {
                continue
            }
        }

        // Fallback: return first available even if version is unknown
        return candidates.first { FileManager.default.fileExists(atPath: $0) }
    }

    private func findRuntimeDir() -> String? {
        if let bundled = Bundle.main.resourcePath.map({ "\($0)/AgentRuntime" }),
           FileManager.default.fileExists(atPath: bundled) {
            return bundled
        }

        let devPath = Bundle.main.bundlePath
            .components(separatedBy: "/Anvil/")
            .first
            .map { "\($0)/AgentRuntime" }
        if let devPath, FileManager.default.fileExists(atPath: devPath) {
            return devPath
        }

        return nil
    }
}

enum RuntimeError: LocalizedError {
    case pythonNotFound
    case runtimeNotFound
    case noSocketPath
    case timeout

    var errorDescription: String? {
        switch self {
        case .pythonNotFound: "Python 3 not found"
        case .runtimeNotFound: "Agent runtime directory not found"
        case .noSocketPath: "Runtime did not provide socket path"
        case .timeout: "Runtime startup timed out"
        }
    }
}
