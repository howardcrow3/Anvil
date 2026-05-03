import Foundation
import Network

@Observable
final class IPCClient: @unchecked Sendable {
    private var connection: NWConnection?
    private var socketPath: String
    private(set) var isConnected = false
    private var requestId: Int = 0
    private var pendingRequests: [Int: CheckedContinuation<Data, Error>] = [:]
    private var receiveBuffer = Data()

    var onChatEvent: (@Sendable ([String: Any]) -> Void)?
    var onConnectionStateChanged: (@Sendable (Bool) -> Void)?

    private var reconnectTask: Task<Void, Never>?
    private var shouldReconnect = false

    init(socketPath: String = AnvilConstants.socketPath) {
        self.socketPath = socketPath
    }

    func updateSocketPath(_ path: String) {
        socketPath = path
    }

    func connect() async throws {
        NSLog("[IPCClient] Connecting to %@", socketPath)
        let nwParams = NWParameters()
        let endpoint = NWEndpoint.unix(path: socketPath)
        connection = NWConnection(to: endpoint, using: nwParams)

        return try await withCheckedThrowingContinuation { continuation in
            nonisolated(unsafe) var resumed = false
            connection?.stateUpdateHandler = { [weak self] state in
                guard let self else { return }
                NSLog("[IPCClient] State: %@", "\(state)")
                switch state {
                case .ready:
                    self.isConnected = true
                    self.receiveBuffer = Data()
                    self.onConnectionStateChanged?(true)
                    self.startReceiving()
                    if !resumed {
                        resumed = true
                        continuation.resume()
                    }
                case .failed(let error):
                    self.isConnected = false
                    self.onConnectionStateChanged?(false)
                    if !resumed {
                        resumed = true
                        continuation.resume(throwing: error)
                    }
                    self.scheduleReconnect()
                case .cancelled:
                    self.isConnected = false
                    self.onConnectionStateChanged?(false)
                default:
                    break
                }
            }
            connection?.start(queue: .global(qos: .userInitiated))
        }
    }

    func disconnect() {
        shouldReconnect = false
        reconnectTask?.cancel()
        reconnectTask = nil
        connection?.cancel()
        connection = nil
        isConnected = false
        receiveBuffer = Data()
        for (_, continuation) in pendingRequests {
            continuation.resume(throwing: IPCError.notConnected)
        }
        pendingRequests.removeAll()
        onConnectionStateChanged?(false)
    }

    @discardableResult
    func sendRequest(method: String, params: [String: Any] = [:]) async throws -> Data {
        guard let connection, isConnected else {
            throw IPCError.notConnected
        }

        requestId += 1
        let currentId = requestId

        let request: [String: Any] = [
            "jsonrpc": "2.0",
            "id": currentId,
            "method": method,
            "params": params
        ]

        let data = try JSONSerialization.data(withJSONObject: request)
        let framedData = data + Data([0x0A])

        return try await withCheckedThrowingContinuation { continuation in
            pendingRequests[currentId] = continuation
            connection.send(content: framedData, completion: .contentProcessed { error in
                if let error {
                    self.pendingRequests.removeValue(forKey: currentId)
                    continuation.resume(throwing: error)
                }
            })
        }
    }

    func enableReconnect() {
        shouldReconnect = true
    }

    private func scheduleReconnect() {
        guard shouldReconnect else { return }
        reconnectTask?.cancel()
        reconnectTask = Task { [weak self] in
            var delay: UInt64 = 1_000_000_000
            let maxDelay: UInt64 = 30_000_000_000
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: delay)
                guard !Task.isCancelled, let self, self.shouldReconnect, !self.isConnected else { return }
                do {
                    try await self.connect()
                    return
                } catch {
                    delay = min(delay * 2, maxDelay)
                }
            }
        }
    }

    private func startReceiving() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] content, _, isComplete, error in
            if let data = content, !data.isEmpty {
                self?.handleReceivedData(data)
            }
            if isComplete {
                self?.isConnected = false
                self?.onConnectionStateChanged?(false)
                self?.scheduleReconnect()
            } else if error == nil {
                self?.startReceiving()
            }
        }
    }

    private func handleReceivedData(_ data: Data) {
        receiveBuffer.append(data)

        while let newlineIndex = receiveBuffer.firstIndex(of: 0x0A) {
            let lineData = receiveBuffer[receiveBuffer.startIndex..<newlineIndex]
            receiveBuffer = Data(receiveBuffer[receiveBuffer.index(after: newlineIndex)...])

            guard !lineData.isEmpty,
                  let json = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any] else {
                continue
            }

            if let id = json["id"] as? Int, let continuation = pendingRequests.removeValue(forKey: id) {
                if let error = json["error"] as? [String: Any] {
                    let message = error["message"] as? String ?? "Unknown error"
                    continuation.resume(throwing: IPCError.serverError(message))
                } else {
                    let resultObj = json["result"] ?? [String: Any]()
                    let resultData = (try? JSONSerialization.data(withJSONObject: resultObj)) ?? Data()
                    continuation.resume(returning: resultData)
                }
            } else if let method = json["method"] as? String {
                handleNotification(method: method, params: json["params"] as? [String: Any] ?? [:])
            }
        }
    }

    private func handleNotification(method: String, params: [String: Any]) {
        switch method {
        case "chat.event":
            onChatEvent?(params)
        default:
            break
        }
    }
}

enum IPCError: LocalizedError {
    case notConnected
    case timeout
    case invalidResponse
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .notConnected: "Not connected to agent runtime"
        case .timeout: "Request timed out"
        case .invalidResponse: "Invalid response from agent"
        case .serverError(let message): "Server error: \(message)"
        }
    }
}
