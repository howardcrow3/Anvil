import Foundation
import SwiftUI

private struct ChatEventData: Sendable {
    let type: String?
    let text: String?
    let id: String?
    let name: String?
    let arguments: [String: String]
    let content: String?
    let isError: Bool
    let message: String?

    init(_ params: [String: Any]) {
        self.type = params["type"] as? String
        self.text = params["text"] as? String
        self.id = params["id"] as? String
        self.name = params["name"] as? String
        self.content = params["content"] as? String
        self.isError = params["is_error"] as? Bool ?? false
        self.message = params["message"] as? String

        if let argsDict = params["arguments"] as? [String: Any] {
            var result: [String: String] = [:]
            for (key, val) in argsDict {
                if let str = val as? String {
                    result[key] = str
                } else if let data = try? JSONSerialization.data(withJSONObject: val),
                          let str = String(data: data, encoding: .utf8) {
                    result[key] = str
                } else {
                    result[key] = "\(val)"
                }
            }
            self.arguments = result
        } else {
            self.arguments = [:]
        }
    }
}

struct PermissionRequest: Identifiable, Sendable {
    let id: String
    let toolName: String
    let arguments: [String: String]
}

@Observable @MainActor
final class ChatViewModel {
    var messages: [Message] = []
    var inputText = ""
    var isStreaming = false
    var streamingContent = ""
    var currentSessionId: UUID?
    var terminalOutput: [String] = []
    var isPlanningMode = false
    var pendingPermission: PermissionRequest?

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
        setupCallbacks()
    }

    private func setupCallbacks() {
        ipcClient.onChatEvent = { @Sendable [weak self] params in
            let eventData = ChatEventData(params)
            Task { @MainActor [weak self] in
                self?.handleChatEvent(eventData)
            }
        }
    }

    private func handleChatEvent(_ event: ChatEventData) {
        guard let type = event.type else { return }

        switch type {
        case "text_delta":
            if let text = event.text {
                streamingContent += text
            }

        case "tool_call":
            let toolCall = ToolCall(
                serverID: event.id,
                name: event.name ?? "",
                arguments: event.arguments,
                status: .running
            )
            ensureAssistantMessage()
            messages[messages.count - 1].toolCalls.append(toolCall)

        case "tool_result":
            guard let serverID = event.id else { return }
            let content = event.content ?? ""
            let isError = event.isError

            if let msgIdx = messages.indices.last(where: { messages[$0].role == .assistant }) {
                if let tcIdx = messages[msgIdx].toolCalls.lastIndex(where: { $0.serverID == serverID }) {
                    messages[msgIdx].toolCalls[tcIdx].result = content
                    messages[msgIdx].toolCalls[tcIdx].status = isError ? .error : .done
                }
            }

            if let name = messages.last?.toolCalls.last(where: { $0.serverID == serverID })?.name,
               name == "bash" || name == "execute_command" {
                terminalOutput.append(content)
            }

        case "permission_request":
            if let reqId = event.id, let toolName = event.name {
                pendingPermission = PermissionRequest(
                    id: reqId,
                    toolName: toolName,
                    arguments: event.arguments
                )
            }

        case "done":
            finishStreaming()

        case "error":
            let errorMsg = event.message ?? "Unknown error"
            streamingContent += "\n[Error: \(errorMsg)]"
            finishStreaming()

        default:
            break
        }
    }

    func sendMessage() async {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        if isStreaming {
            await cancelStreaming()
            return
        }

        let userMessage = Message(role: .user, content: text)
        messages.append(userMessage)
        inputText = ""
        isStreaming = true
        streamingContent = ""

        let assistantMessage = Message(role: .assistant, content: "")
        messages.append(assistantMessage)

        do {
            if !ipcClient.isConnected {
                try await ipcClient.connect()
            }

            let _ = try await ipcClient.sendRequest(method: "chat.send", params: [
                "message": text,
                "session_id": currentSessionId?.uuidString ?? ""
            ])

            // Don't call finishStreaming() here — the RPC returns before
            // streaming events arrive. Let the "done" event callback handle it.
        } catch {
            messages[messages.count - 1].content = "Error: \(error.localizedDescription)"
            isStreaming = false
            streamingContent = ""
        }
    }

    func cancelStreaming() async {
        guard isStreaming, ipcClient.isConnected else { return }
        let _ = try? await ipcClient.sendRequest(method: "chat.cancel")
        finishStreaming()
    }

    func clearMessages() {
        messages = []
        currentSessionId = nil
        terminalOutput = []
    }

    func loadSession(_ session: Session) {
        currentSessionId = session.id
        messages = []
        terminalOutput = []
    }

    func togglePlanningMode() async {
        let method = isPlanningMode ? "planning.stop" : "planning.start"
        guard ipcClient.isConnected else { return }
        let _ = try? await ipcClient.sendRequest(method: method)
        isPlanningMode.toggle()
    }

    func respondToPermission(approved: Bool) async {
        guard let request = pendingPermission else { return }
        pendingPermission = nil
        guard ipcClient.isConnected else { return }
        let _ = try? await ipcClient.sendRequest(method: "permission.respond", params: [
            "request_id": request.id,
            "approved": approved
        ])
    }

    func connectToRuntime(socketPath: String) async {
        ipcClient.updateSocketPath(socketPath)
        ipcClient.enableReconnect()
        try? await ipcClient.connect()
    }

    var connectionStatus: Bool {
        ipcClient.isConnected
    }

    private func ensureAssistantMessage() {
        if messages.isEmpty || messages.last?.role != .assistant {
            messages.append(Message(role: .assistant, content: ""))
        }
    }

    private func finishStreaming() {
        guard isStreaming else { return }
        if !streamingContent.isEmpty, let lastIdx = messages.indices.last,
           messages[lastIdx].role == .assistant {
            messages[lastIdx].content = streamingContent
        }
        isStreaming = false
        streamingContent = ""
    }

}
