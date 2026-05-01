import Foundation
import Network

@Observable
final class IPCClient: @unchecked Sendable {
    private var connection: NWConnection?
    private let socketPath: String
    private(set) var isConnected = false
    private var requestId: Int = 0
    private var pendingRequests: [Int: CheckedContinuation<String, Error>] = [:]
    var onToken: (@Sendable (String) -> Void)?
    var onToolCall: (@Sendable (ToolCall) -> Void)?
    var onStatusUpdate: (@Sendable (String) -> Void)?

    init(socketPath: String = AnvilConstants.socketPath) {
        self.socketPath = socketPath
    }

    func connect() async throws {
        let params = NWParameters()
        let endpoint = NWEndpoint.unix(path: socketPath)
        connection = NWConnection(to: endpoint, using: params)

        return try await withCheckedThrowingContinuation { continuation in
            connection?.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready:
                    self?.isConnected = true
                    self?.startReceiving()
                    continuation.resume()
                case .failed(let error):
                    self?.isConnected = false
                    continuation.resume(throwing: error)
                case .cancelled:
                    self?.isConnected = false
                default:
                    break
                }
            }
            connection?.start(queue: .global(qos: .userInitiated))
        }
    }

    func disconnect() {
        connection?.cancel()
        connection = nil
        isConnected = false
        pendingRequests.removeAll()
    }

    func sendRequest(method: String, params: [String: Any] = [:]) async throws -> String {
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
        let framedData = data + Data([0x0A]) // newline delimiter

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

    private func startReceiving() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] content, _, isComplete, error in
            if let data = content, !data.isEmpty {
                self?.handleReceivedData(data)
            }
            if !isComplete, error == nil {
                self?.startReceiving()
            }
        }
    }

    private func handleReceivedData(_ data: Data) {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

        if let id = json["id"] as? Int, let continuation = pendingRequests.removeValue(forKey: id) {
            let result = (json["result"] as? String) ?? ""
            continuation.resume(returning: result)
        } else if let method = json["method"] as? String {
            handleNotification(method: method, params: json["params"] as? [String: Any] ?? [:])
        }
    }

    private func handleNotification(method: String, params: [String: Any]) {
        switch method {
        case "stream/token":
            if let token = params["token"] as? String {
                onToken?(token)
            }
        case "tool/call":
            let toolCall = ToolCall(
                name: params["name"] as? String ?? "",
                arguments: params["arguments"] as? [String: String] ?? [:],
                status: .running
            )
            onToolCall?(toolCall)
        case "status/update":
            if let status = params["status"] as? String {
                onStatusUpdate?(status)
            }
        default:
            break
        }
    }
}

enum IPCError: LocalizedError {
    case notConnected
    case timeout
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .notConnected: "Not connected to agent runtime"
        case .timeout: "Request timed out"
        case .invalidResponse: "Invalid response from agent"
        }
    }
}
