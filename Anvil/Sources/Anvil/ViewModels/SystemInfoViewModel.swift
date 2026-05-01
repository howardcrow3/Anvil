import Foundation

@Observable
final class SystemInfoViewModel: @unchecked Sendable {
    var chip: String = "Detecting..."
    var totalRAM: Double = 0
    var availableRAM: Double = 0
    var gpuName: String = "Unknown"
    var gpuCores: String = "Unknown"
    var metalFamily: String = "Unknown"

    var memoryPressure: String = "unknown"
    var memoryFreePct: Int = -1
    var avgTokensPerSec: Double = 0
    var avgElapsedSec: Double = 0
    var inferenceCount: Int = 0

    var isLoading = false
    var errorMessage: String?

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    func refresh() async {
        isLoading = true
        defer { isLoading = false }

        guard ipcClient.isConnected else {
            errorMessage = "Not connected to agent runtime"
            return
        }

        await withTaskGroup(of: Void.self) { group in
            group.addTask { await self.fetchSystemInfo() }
            group.addTask { await self.fetchStats() }
        }
    }

    private func fetchSystemInfo() async {
        do {
            let data = try await ipcClient.sendRequest(method: "system.info")
            guard let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            await MainActor.run {
                self.chip = dict["chip"] as? String ?? "Unknown"
                self.totalRAM = dict["total_ram_gb"] as? Double ?? 0
                self.availableRAM = dict["available_ram_gb"] as? Double ?? 0
                self.gpuName = dict["gpu_name"] as? String ?? "Unknown"
                self.gpuCores = dict["gpu_cores"] as? String ?? "Unknown"
                self.metalFamily = dict["metal_family"] as? String ?? "Unknown"
            }
        } catch {
            await MainActor.run {
                self.errorMessage = error.localizedDescription
            }
        }
    }

    private func fetchStats() async {
        do {
            let data = try await ipcClient.sendRequest(method: "system.stats")
            guard let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            await MainActor.run {
                if let memory = dict["memory"] as? [String: Any] {
                    self.memoryPressure = memory["pressure"] as? String ?? "unknown"
                    self.memoryFreePct = memory["free_pct"] as? Int ?? -1
                }
                if let inference = dict["inference"] as? [String: Any] {
                    self.avgTokensPerSec = inference["avg_tokens_per_sec"] as? Double ?? 0
                    self.avgElapsedSec = inference["avg_elapsed_sec"] as? Double ?? 0
                    self.inferenceCount = inference["count"] as? Int ?? 0
                }
            }
        } catch {
            // Stats are optional, don't overwrite errorMessage
        }
    }
}
