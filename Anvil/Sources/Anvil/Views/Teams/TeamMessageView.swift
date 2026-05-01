import SwiftUI

struct TeamMessageView: View {
    @Environment(TeamViewModel.self) private var teamVM
    @State private var messageText = ""
    @State private var selectedRecipient = ""

    var body: some View {
        VStack(spacing: 0) {
            messageList
            Divider()
            inputBar
        }
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if let messages = teamVM.team?.messages, !messages.isEmpty {
                        ForEach(messages) { msg in
                            MessageBubble(message: msg)
                                .id(msg.id)
                        }
                    } else {
                        VStack(spacing: 8) {
                            Image(systemName: "bubble.left.and.bubble.right")
                                .font(.title2)
                                .foregroundStyle(.tertiary)
                            Text("No messages yet")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .padding(.top, 60)
                    }
                }
                .padding(12)
            }
            .onChange(of: teamVM.team?.messages.count) { _, _ in
                if let lastId = teamVM.team?.messages.last?.id {
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
        }
    }

    private var inputBar: some View {
        HStack(spacing: 8) {
            Picker("To:", selection: $selectedRecipient) {
                Text("Select...").tag("")
                if let teammates = teamVM.team?.teammates {
                    ForEach(teammates) { teammate in
                        Text(teammate.name).tag(teammate.name)
                    }
                }
            }
            .frame(width: 130)

            TextField("Message...", text: $messageText)
                .textFieldStyle(.roundedBorder)
                .onSubmit { send() }

            Button("Send") { send() }
                .buttonStyle(.borderedProminent)
                .disabled(messageText.isEmpty || selectedRecipient.isEmpty)
        }
        .padding(8)
    }

    private func send() {
        guard !messageText.isEmpty, !selectedRecipient.isEmpty else { return }
        teamVM.sendMessage(to: selectedRecipient, content: messageText)
        messageText = ""
    }
}

struct MessageBubble: View {
    let message: TeamMessage

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Circle()
                .fill(message.from == "lead" ? .blue : .green)
                .frame(width: 24, height: 24)
                .overlay {
                    Text(String(message.from.prefix(1)).uppercased())
                        .font(.caption2)
                        .fontWeight(.bold)
                        .foregroundStyle(.white)
                }

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(message.from)
                        .font(.caption)
                        .fontWeight(.medium)
                    Image(systemName: "arrow.right")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(message.to)
                        .font(.caption)
                        .fontWeight(.medium)
                    Spacer()
                    Text(message.timestamp.relativeFormatted)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }

                Text(message.content)
                    .font(.callout)
            }
        }
        .padding(8)
        .background(.background.secondary)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
