import Foundation
import SwiftUI

@Observable @MainActor
final class ChatViewModel {
    var messages: [Message] = []
    var inputText = ""
    var isStreaming = false
    var streamingContent = ""
    var currentSessionId: UUID?

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
        setupCallbacks()
    }

    private func setupCallbacks() {
        ipcClient.onToken = { @Sendable [weak self] token in
            Task { @MainActor [weak self] in
                self?.streamingContent += token
            }
        }

        ipcClient.onToolCall = { @Sendable [weak self] toolCall in
            Task { @MainActor [weak self] in
                guard let self else { return }
                if !self.messages.isEmpty, self.messages[self.messages.count - 1].role == .assistant {
                    self.messages[self.messages.count - 1].toolCalls.append(toolCall)
                }
            }
        }
    }

    func sendMessage() async {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

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

            let _ = try await ipcClient.sendRequest(method: "chat/send", params: [
                "content": text,
                "session_id": currentSessionId?.uuidString ?? ""
            ])

            messages[messages.count - 1].content = streamingContent
        } catch {
            messages[messages.count - 1].content = "Error: \(error.localizedDescription)"
        }

        isStreaming = false
        streamingContent = ""
    }

    func clearMessages() {
        messages = []
        currentSessionId = nil
    }

    func loadSession(_ session: Session) {
        currentSessionId = session.id
        messages = []
    }
}
