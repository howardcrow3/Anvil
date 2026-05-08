import SwiftUI

struct ContentView: View {
    @Environment(ChatViewModel.self) private var chatVM
    @Environment(ModelViewModel.self) private var modelVM
    @Environment(ProjectViewModel.self) private var projectVM
    @Environment(SessionViewModel.self) private var sessionVM
    @State private var showTerminal = false
    @State private var columnVisibility = NavigationSplitViewVisibility.all
    @State private var selectedTab: SidebarTab = .sessions

    var body: some View {
        @Bindable var vm = chatVM

        VStack(spacing: 0) {
            topBar

            if chatVM.isPlanningMode {
                planningBanner
            }

            NavigationSplitView(columnVisibility: $columnVisibility) {
                SidebarView(selectedTab: $selectedTab)
                    .navigationSplitViewColumnWidth(min: 200, ideal: 250, max: 350)
            } detail: {
                detailContent
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
        .sheet(item: $vm.pendingPermission) { request in
            PermissionRequestView(request: request)
        }
    }

    private var topBar: some View {
        HStack {
            ModelSelectorView()

            connectionIndicator

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
                Task { await chatVM.togglePlanningMode() }
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: chatVM.isPlanningMode ? "pencil.slash" : "map")
                    Text(chatVM.isPlanningMode ? "Exit Plan" : "Plan")
                        .font(.caption)
                }
            }
            .help(chatVM.isPlanningMode ? "Exit Planning Mode" : "Enter Planning Mode")

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

    private var planningBanner: some View {
        HStack {
            Image(systemName: "map.fill")
            Text("Planning Mode")
                .fontWeight(.medium)
            Text("— Read-only exploration. No files will be modified.")
                .foregroundStyle(.secondary)
            Spacer()
            Button("Exit") {
                Task { await chatVM.togglePlanningMode() }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
        .font(.caption)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(.yellow.opacity(0.15))
    }

    private var connectionIndicator: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(chatVM.connectionStatus ? .green : .red)
                .frame(width: 8, height: 8)
            Text(chatVM.connectionStatus ? "Connected" : "Disconnected")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.leading, 8)
    }

    @ViewBuilder
    private var detailContent: some View {
        if selectedTab == .projects, let project = projectVM.selectedProject {
            if projectVM.activeTaskId != nil {
                // Viewing a task's session — show chat with back-to-board bar
                VStack(spacing: 0) {
                    taskChatHeader(project)
                    Divider()
                    ChatView()
                }
            } else {
                // Viewing the project board
                ProjectBoardDetailView(project: project)
            }
        } else {
            ChatView()
        }
    }

    private func taskChatHeader(_ project: Project) -> some View {
        let task = projectVM.activeTaskId.flatMap { tid in
            project.tasks.first { $0.id == tid }
        }
        let taskName = task?.title ?? "Task"

        return HStack(spacing: 8) {
            Button {
                projectVM.backToBoard()
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 11, weight: .semibold))
                    Text(project.name)
                        .font(.caption)
                }
            }
            .buttonStyle(.plain)
            .help("Back to Board")

            Image(systemName: "chevron.right")
                .font(.system(size: 9))
                .foregroundStyle(.tertiary)

            Text(taskName)
                .font(.subheadline)
                .fontWeight(.medium)
                .lineLimit(1)

            Spacer()

            if let task {
                taskStatusMenu(task, project: project)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(.bar)
    }

    private func taskStatusMenu(_ task: ProjectTask, project: Project) -> some View {
        Menu {
            ForEach(ProjectTaskStatus.allCases, id: \.self) { status in
                Button {
                    projectVM.updateTaskStatus(task.id, in: project, status: status)
                } label: {
                    Label(status.label, systemImage: status.icon)
                }
                .disabled(task.status == status)
            }
        } label: {
            HStack(spacing: 4) {
                Circle()
                    .fill(taskStatusColor(task.status))
                    .frame(width: 7, height: 7)
                Text(task.status.label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Image(systemName: "chevron.down")
                    .font(.system(size: 8))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(.quaternary)
            .clipShape(Capsule())
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
    }

    private func taskStatusColor(_ status: ProjectTaskStatus) -> Color {
        switch status {
        case .notStarted: .secondary
        case .inProgress: .blue
        case .needsHelp: .orange
        case .completed: .green
        }
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
                    LazyVStack(alignment: .leading, spacing: 4) {
                        if chatVM.terminalOutput.isEmpty {
                            Text("Terminal output will appear here...")
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(Array(chatVM.terminalOutput.enumerated()), id: \.offset) { _, line in
                                Text(line)
                            }
                        }
                    }
                    .font(.system(.body, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                }
            }
            .frame(height: 200)
            .background(.background.secondary)
        }
    }
}

struct PermissionRequestView: View {
    let request: PermissionRequest
    @Environment(ChatViewModel.self) private var chatVM
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 16) {
            HStack {
                Image(systemName: "lock.shield")
                    .font(.title2)
                    .foregroundStyle(.orange)
                Text("Permission Required")
                    .font(.headline)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Tool:")
                        .fontWeight(.medium)
                    Text(request.toolName)
                        .font(.system(.body, design: .monospaced))
                }

                if !request.arguments.isEmpty {
                    Text("Arguments:")
                        .fontWeight(.medium)
                    ScrollView {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(Array(request.arguments.sorted(by: { $0.key < $1.key })), id: \.key) { key, value in
                                HStack(alignment: .top) {
                                    Text(key + ":")
                                        .foregroundStyle(.secondary)
                                        .frame(width: 80, alignment: .trailing)
                                    Text(value)
                                        .lineLimit(5)
                                }
                                .font(.system(.caption, design: .monospaced))
                            }
                        }
                    }
                    .frame(maxHeight: 150)
                    .padding(8)
                    .background(.quaternary)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 12) {
                Button("Deny") {
                    Task {
                        await chatVM.respondToPermission(approved: false)
                        dismiss()
                    }
                }
                .keyboardShortcut(.escape)

                Spacer()

                Button("Allow") {
                    Task {
                        await chatVM.respondToPermission(approved: true)
                        dismiss()
                    }
                }
                .keyboardShortcut(.return)
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(20)
        .frame(width: 400)
    }
}
