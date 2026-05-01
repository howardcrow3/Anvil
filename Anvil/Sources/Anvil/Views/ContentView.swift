import SwiftUI

struct ContentView: View {
    @Environment(ChatViewModel.self) private var chatVM
    @Environment(ModelViewModel.self) private var modelVM
    @State private var showTerminal = false
    @State private var columnVisibility = NavigationSplitViewVisibility.all

    var body: some View {
        VStack(spacing: 0) {
            topBar

            NavigationSplitView(columnVisibility: $columnVisibility) {
                SidebarView()
                    .navigationSplitViewColumnWidth(min: 200, ideal: 250, max: 350)
            } detail: {
                ChatView()
            }

            if showTerminal {
                terminalPanel
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .toggleTerminal)) { _ in
            withAnimation { showTerminal.toggle() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .toggleSidebar)) { _ in
            withAnimation {
                columnVisibility = columnVisibility == .all ? .detailOnly : .all
            }
        }
    }

    private var topBar: some View {
        HStack {
            ModelSelectorView()
            Spacer()

            if chatVM.isStreaming {
                ProgressView()
                    .scaleEffect(0.7)
                    .padding(.trailing, 4)
                Text("Streaming...")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Button {
                withAnimation { showTerminal.toggle() }
            } label: {
                Image(systemName: "terminal")
            }
            .help("Toggle Terminal")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.bar)
    }

    private var terminalPanel: some View {
        VStack(spacing: 0) {
            Divider()
            VStack(alignment: .leading) {
                HStack {
                    Image(systemName: "terminal")
                    Text("Terminal")
                        .font(.headline)
                    Spacer()
                    Button {
                        withAnimation { showTerminal = false }
                    } label: {
                        Image(systemName: "xmark")
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 12)
                .padding(.top, 8)

                ScrollView {
                    Text("Terminal output will appear here...")
                        .font(.system(.body, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                }
            }
            .frame(height: 200)
            .background(.background.secondary)
        }
    }
}
