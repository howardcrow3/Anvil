import SwiftUI

struct ChatView: View {
    @Environment(ChatViewModel.self) private var chatVM

    var body: some View {
        VStack(spacing: 0) {
            messageList
            Divider()
            MessageInputView()
        }
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    if chatVM.messages.isEmpty {
                        emptyState
                    } else {
                        ForEach(chatVM.messages) { message in
                            MessageView(message: message)
                                .id(message.id)
                        }

                        if chatVM.isStreaming && !chatVM.streamingContent.isEmpty {
                            StreamingTextView(text: chatVM.streamingContent)
                                .id("streaming")
                        }
                    }
                }
                .padding()
            }
            .onChange(of: chatVM.messages.count) {
                if let lastMessage = chatVM.messages.last {
                    withAnimation {
                        proxy.scrollTo(lastMessage.id, anchor: .bottom)
                    }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "hammer.fill")
                .font(.system(size: 48))
                .foregroundStyle(.tertiary)
            Text("Anvil")
                .font(.largeTitle)
                .fontWeight(.bold)
            Text("Start a conversation or resume a session")
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.top, 100)
    }
}
