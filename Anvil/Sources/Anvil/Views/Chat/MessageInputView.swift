import SwiftUI

struct MessageInputView: View {
    @Environment(ChatViewModel.self) private var chatVM
    @State private var showSlashCommands = false
    @FocusState private var isFocused: Bool

    private let slashCommands: [(command: String, description: String)] = [
        ("/help", "Show available commands"),
        ("/clear", "Clear conversation"),
        ("/compact", "Compress conversation history"),
        ("/plan", "Toggle planning mode"),
        ("/resume", "Resume last session"),
        ("/settings", "Show current settings"),
        ("/model", "Switch model"),
        ("/session", "Session management"),
        ("/team", "Team management"),
    ]

    var body: some View {
        @Bindable var vm = chatVM

        VStack(spacing: 0) {
            if showSlashCommands {
                slashCommandList
            }

            HStack(alignment: .bottom, spacing: 8) {
                Button {
                    // Attachment action
                } label: {
                    Image(systemName: "paperclip")
                        .font(.title3)
                }
                .buttonStyle(.plain)
                .help("Attach file")

                TextField("Message Anvil...", text: $vm.inputText, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(1...10)
                    .focused($isFocused)
                    .onSubmit {
                        if !NSEvent.modifierFlags.contains(.shift) {
                            Task { await chatVM.sendMessage() }
                        }
                    }
                    .onChange(of: chatVM.inputText) { _, newValue in
                        showSlashCommands = newValue.hasPrefix("/") && !newValue.contains(" ")
                    }

                Button {
                    Task { await chatVM.sendMessage() }
                } label: {
                    Image(systemName: chatVM.isStreaming ? "stop.circle.fill" : "arrow.up.circle.fill")
                        .font(.title2)
                        .foregroundStyle(chatVM.inputText.isEmpty && !chatVM.isStreaming ? AnyShapeStyle(.tertiary) : AnyShapeStyle(.tint))
                }
                .buttonStyle(.plain)
                .disabled(chatVM.inputText.isEmpty && !chatVM.isStreaming)
                .keyboardShortcut(.return, modifiers: [])
            }
            .padding(12)
        }
        .background(.bar)
        .onAppear { isFocused = true }
    }

    private var slashCommandList: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(filteredCommands, id: \.command) { item in
                Button {
                    chatVM.inputText = item.command + " "
                    showSlashCommands = false
                } label: {
                    HStack {
                        Text(item.command)
                            .font(.system(.body, design: .monospaced))
                            .fontWeight(.medium)
                        Spacer()
                        Text(item.description)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 4)
        .background(.bar)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .padding(.horizontal, 12)
        .padding(.top, 4)
    }

    private var filteredCommands: [(command: String, description: String)] {
        let input = chatVM.inputText.lowercased()
        if input == "/" { return slashCommands }
        return slashCommands.filter { $0.command.hasPrefix(input) }
    }
}
