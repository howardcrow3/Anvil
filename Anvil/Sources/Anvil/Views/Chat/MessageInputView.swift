import SwiftUI
import UniformTypeIdentifiers

struct MessageInputView: View {
    @Environment(ChatViewModel.self) private var chatVM
    @State private var showSlashCommands = false
    @State private var isDropTargeted = false
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
        .overlay {
            if isDropTargeted {
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.accentColor, lineWidth: 2)
                    .background(Color.accentColor.opacity(0.05))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .onDrop(of: [.fileURL], isTargeted: $isDropTargeted) { providers in
            handleDrop(providers)
        }
        .onAppear { isFocused = true }
    }

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        for provider in providers {
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                guard let data = item as? Data,
                      let url = URL(dataRepresentation: data, relativeTo: nil) else { return }
                let path = url.path
                DispatchQueue.main.async {
                    if chatVM.inputText.isEmpty {
                        chatVM.inputText = path
                    } else {
                        chatVM.inputText += " " + path
                    }
                }
            }
        }
        return true
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
