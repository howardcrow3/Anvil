import Foundation

@Observable
final class IPCClient: @unchecked Sendable {
    private var inputStream: InputStream?
    private var outputStream: OutputStream?
    private var socketPath: String
    private(set) var isConnected = false
    private var requestId: Int = 0
    private var pendingRequests: [Int: CheckedContinuation<Data, Error>] = [:]
    private var receiveBuffer = Data()
    private let lock = NSLock()

    var onChatEvent: (@Sendable ([String: Any]) -> Void)?
    var onConnectionStateChanged: (@Sendable (Bool) -> Void)?
    var onTaskStatusUpdate: (@Sendable ([String: Any]) -> Void)?

    private var reconnectTask: Task<Void, Never>?
    private var shouldReconnect = false
    private var readTask: Task<Void, Never>?

    init(socketPath: String = AnvilConstants.socketPath) {
        self.socketPath = socketPath
    }

    func updateSocketPath(_ path: String) {
        socketPath = path
    }

    func connect() async throws {
        NSLog("[IPCClient] Connecting to %@", socketPath)

        // Create POSIX Unix domain socket
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else {
            NSLog("[IPCClient] socket() failed: %d", errno)
            throw IPCError.notConnected
        }

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = socketPath.utf8CString
        guard pathBytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else {
            close(fd)
            NSLog("[IPCClient] Socket path too long: %d chars", pathBytes.count)
            throw IPCError.notConnected
        }
        withUnsafeMutablePointer(to: &addr.sun_path) { ptr in
            ptr.withMemoryRebound(to: CChar.self, capacity: pathBytes.count) { dest in
                pathBytes.withUnsafeBufferPointer { src in
                    _ = memcpy(dest, src.baseAddress!, pathBytes.count)
                }
            }
        }

        let addrLen = socklen_t(MemoryLayout<sockaddr_un>.size)
        let result = withUnsafePointer(to: &addr) { addrPtr in
            addrPtr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPtr in
                Darwin.connect(fd, sockaddrPtr, addrLen)
            }
        }

        guard result == 0 else {
            close(fd)
            let err = String(cString: strerror(errno))
            NSLog("[IPCClient] connect() failed: %@", err)
            scheduleReconnect()
            throw IPCError.notConnected
        }

        // Wrap fd in Foundation streams
        var readStream: Unmanaged<CFReadStream>?
        var writeStream: Unmanaged<CFWriteStream>?
        CFStreamCreatePairWithSocket(nil, fd, &readStream, &writeStream)

        guard let cfInput = readStream?.takeRetainedValue(),
              let cfOutput = writeStream?.takeRetainedValue() else {
            close(fd)
            throw IPCError.notConnected
        }

        // Tell the streams to close the socket when they close
        CFReadStreamSetProperty(cfInput, CFStreamPropertyKey(rawValue: kCFStreamPropertyShouldCloseNativeSocket), kCFBooleanTrue)
        CFWriteStreamSetProperty(cfOutput, CFStreamPropertyKey(rawValue: kCFStreamPropertyShouldCloseNativeSocket), kCFBooleanTrue)

        let input = cfInput as InputStream
        let output = cfOutput as OutputStream
        input.open()
        output.open()

        self.inputStream = input
        self.outputStream = output
        self.isConnected = true
        self.receiveBuffer = Data()
        NSLog("[IPCClient] Connected successfully")
        onConnectionStateChanged?(true)

        // Start background read loop
        readTask?.cancel()
        readTask = Task.detached { [weak self] in
            await self?.readLoop()
        }
    }

    func disconnect() {
        shouldReconnect = false
        reconnectTask?.cancel()
        reconnectTask = nil
        readTask?.cancel()
        readTask = nil
        inputStream?.close()
        outputStream?.close()
        inputStream = nil
        outputStream = nil
        isConnected = false

        let pending = drainPendingRequests()
        for (_, continuation) in pending {
            continuation.resume(throwing: IPCError.notConnected)
        }
        onConnectionStateChanged?(false)
    }

    @discardableResult
    func sendRequest(method: String, params: [String: Any] = [:]) async throws -> Data {
        guard outputStream != nil, isConnected else {
            throw IPCError.notConnected
        }

        let currentId = nextRequestId()

        let request: [String: Any] = [
            "jsonrpc": "2.0",
            "id": currentId,
            "method": method,
            "params": params
        ]

        let data = try JSONSerialization.data(withJSONObject: request)
        let framedData = data + Data([0x0A])

        return try await withCheckedThrowingContinuation { continuation in
            storeContinuation(continuation, forId: currentId)

            guard let output = outputStream else {
                removeContinuation(forId: currentId)
                continuation.resume(throwing: IPCError.notConnected)
                return
            }
            framedData.withUnsafeBytes { buffer in
                guard let ptr = buffer.baseAddress?.assumingMemoryBound(to: UInt8.self) else { return }
                let written = output.write(ptr, maxLength: framedData.count)
                if written < 0 {
                    self.removeContinuation(forId: currentId)
                    continuation.resume(throwing: IPCError.notConnected)
                    self.handleDisconnect()
                }
            }
        }
    }

    private func nextRequestId() -> Int {
        lock.lock()
        defer { lock.unlock() }
        requestId += 1
        return requestId
    }

    private func storeContinuation(_ continuation: CheckedContinuation<Data, Error>, forId id: Int) {
        lock.lock()
        defer { lock.unlock() }
        pendingRequests[id] = continuation
    }

    @discardableResult
    private func removeContinuation(forId id: Int) -> CheckedContinuation<Data, Error>? {
        lock.lock()
        defer { lock.unlock() }
        return pendingRequests.removeValue(forKey: id)
    }

    private func drainPendingRequests() -> [Int: CheckedContinuation<Data, Error>] {
        lock.lock()
        defer { lock.unlock() }
        let pending = pendingRequests
        pendingRequests.removeAll()
        receiveBuffer = Data()
        return pending
    }

    func enableReconnect() {
        shouldReconnect = true
    }

    // MARK: - Private

    private func readLoop() async {
        let bufferSize = 65536
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: bufferSize)
        defer { buffer.deallocate() }

        while !Task.isCancelled, let input = inputStream, input.streamStatus != .closed {
            if input.hasBytesAvailable {
                let bytesRead = input.read(buffer, maxLength: bufferSize)
                if bytesRead > 0 {
                    let data = Data(bytes: buffer, count: bytesRead)
                    handleReceivedData(data)
                } else if bytesRead < 0 {
                    // Read error — disconnected
                    handleDisconnect()
                    return
                } else {
                    // EOF
                    handleDisconnect()
                    return
                }
            } else {
                // Poll interval — yield to avoid spinning
                try? await Task.sleep(nanoseconds: 10_000_000) // 10ms
            }
        }
    }

    private func handleDisconnect() {
        isConnected = false
        inputStream?.close()
        outputStream?.close()
        inputStream = nil
        outputStream = nil
        onConnectionStateChanged?(false)
        scheduleReconnect()
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

    private func handleReceivedData(_ data: Data) {
        lock.lock()
        receiveBuffer.append(data)
        lock.unlock()

        while true {
            let lineData: Data? = extractNextLine()
            guard let lineData, !lineData.isEmpty else { break }

            guard let json = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any] else {
                continue
            }

            if let id = json["id"] as? Int {
                let continuation = removeContinuation(forId: id)

                if let continuation {
                    if let error = json["error"] as? [String: Any] {
                        let message = error["message"] as? String ?? "Unknown error"
                        continuation.resume(throwing: IPCError.serverError(message))
                    } else {
                        let resultObj = json["result"] ?? [String: Any]()
                        let resultData = (try? JSONSerialization.data(withJSONObject: resultObj)) ?? Data()
                        continuation.resume(returning: resultData)
                    }
                }
            } else if let method = json["method"] as? String {
                handleNotification(method: method, params: json["params"] as? [String: Any] ?? [:])
            }
        }
    }

    private func extractNextLine() -> Data? {
        lock.lock()
        defer { lock.unlock() }
        guard let newlineIndex = receiveBuffer.firstIndex(of: 0x0A) else {
            return nil
        }
        let lineData = Data(receiveBuffer[receiveBuffer.startIndex..<newlineIndex])
        receiveBuffer = Data(receiveBuffer[receiveBuffer.index(after: newlineIndex)...])
        return lineData.isEmpty ? Data() : lineData
    }

    private func handleNotification(method: String, params: [String: Any]) {
        switch method {
        case "chat.event":
            onChatEvent?(params)
        case "task.status":
            onTaskStatusUpdate?(params)
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
