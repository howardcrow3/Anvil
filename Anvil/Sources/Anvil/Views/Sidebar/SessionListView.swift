import SwiftUI

struct SessionListView: View {
    @Environment(SessionViewModel.self) private var sessionVM
    @Environment(ChatViewModel.self) private var chatVM

    var body: some View {
        @Bindable var vm = sessionVM

        VStack(spacing: 0) {
            HStack {
                TextField("Search sessions...", text: $vm.searchText)
                    .textFieldStyle(.roundedBorder)

                Button {
                    let session = sessionVM.createSession(name: "New Session")
                    sessionVM.resumeSession(session)
                    chatVM.loadSession(session)
                } label: {
                    Image(systemName: "plus")
                }
                .help("New Session")
            }
            .padding(8)

            List(selection: Binding(
                get: { sessionVM.selectedSession?.id },
                set: { id in
                    if let session = sessionVM.sessions.first(where: { $0.id == id }) {
                        sessionVM.resumeSession(session)
                        chatVM.loadSession(session)
                    }
                }
            )) {
                ForEach(sessionVM.filteredSessions) { session in
                    SessionRow(session: session)
                        .tag(session.id)
                        .contextMenu {
                            Button("Resume") {
                                sessionVM.resumeSession(session)
                                chatVM.loadSession(session)
                            }
                            Divider()
                            Button("Delete", role: .destructive) {
                                sessionVM.deleteSession(session)
                            }
                        }
                }
            }
            .listStyle(.sidebar)
        }
        .onAppear {
            sessionVM.loadSessions()
        }
    }
}

struct SessionRow: View {
    let session: Session

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(session.name)
                .font(.body)
                .fontWeight(.medium)
                .lineLimit(1)

            HStack {
                Text(session.lastActive.relativeFormatted)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(session.messageCount) msgs")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 2)
    }
}
