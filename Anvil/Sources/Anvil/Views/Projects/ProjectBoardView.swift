import SwiftUI

// MARK: - Project Board (Detail Pane)

struct ProjectBoardDetailView: View {
    let project: Project
    @Environment(ProjectViewModel.self) private var projectVM
    @Environment(SessionViewModel.self) private var sessionVM
    @Environment(ChatViewModel.self) private var chatVM

    @State private var showAddTask = false

    var body: some View {
        VStack(spacing: 0) {
            boardHeader
            Divider()
            boardContent
        }
    }

    private var boardHeader: some View {
        HStack(spacing: 8) {
            Button {
                projectVM.selectedProject = nil
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 12, weight: .semibold))
            }
            .buttonStyle(.plain)
            .help("Back to Projects")

            VStack(alignment: .leading, spacing: 1) {
                Text(project.name)
                    .font(.headline)
                    .lineLimit(1)

                HStack(spacing: 8) {
                    if !project.folderPath.isEmpty {
                        Label(
                            (project.folderPath as NSString).lastPathComponent,
                            systemImage: "folder"
                        )
                    }
                    if !project.githubRepo.isEmpty {
                        Label(project.githubRepo, systemImage: "arrow.triangle.branch")
                    }
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            }

            Spacer()

            Button {
                showAddTask = true
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: "plus")
                        .font(.system(size: 12))
                    Text("Add Task")
                        .font(.caption)
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .help("Add Task")
            .popover(isPresented: $showAddTask) {
                AddTaskPopover(project: project)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
    }

    @ViewBuilder
    private var boardContent: some View {
        if project.tasks.isEmpty {
            ContentUnavailableView {
                Label("No Tasks", systemImage: "checklist")
            } description: {
                Text("Add tasks to track work in this project.\nClick a task to start working on it.")
            } actions: {
                Button("Add Task") {
                    showAddTask = true
                }
                .buttonStyle(.borderedProminent)
            }
        } else {
            VStack(spacing: 0) {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 12) {
                        ForEach(ProjectTaskStatus.allCases, id: \.self) { status in
                            BoardColumn(
                                status: status,
                                tasks: project.tasks(for: status),
                                project: project
                            )
                        }
                    }
                    .padding(16)
                }

                Divider()
                progressBar
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
            }
        }
    }

    private var progressBar: some View {
        VStack(spacing: 4) {
            ProgressView(value: project.progress)
                .tint(.green)
            HStack {
                Text("\(project.tasks(for: .completed).count)/\(project.tasks.count) complete")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(Int(project.progress * 100))%")
                    .font(.caption2)
                    .fontWeight(.medium)
            }
        }
    }
}

// MARK: - Board Column

struct BoardColumn: View {
    let status: ProjectTaskStatus
    let tasks: [ProjectTask]
    let project: Project
    @Environment(ProjectViewModel.self) private var projectVM
    @Environment(SessionViewModel.self) private var sessionVM
    @Environment(ChatViewModel.self) private var chatVM

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Column header
            HStack(spacing: 6) {
                Circle()
                    .fill(colorForStatus(status))
                    .frame(width: 8, height: 8)
                Text(status.label)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(tasks.count)")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.tertiary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(.quaternary)
                    .clipShape(Capsule())
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)

            Divider()

            // Task cards
            ScrollView(.vertical, showsIndicators: false) {
                LazyVStack(spacing: 8) {
                    ForEach(tasks) { task in
                        Button {
                            projectVM.openTask(task, in: project, sessionVM: sessionVM, chatVM: chatVM)
                        } label: {
                            BoardTaskCard(task: task, project: project)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(8)
            }
        }
        .frame(width: 220)
        .background(.background.secondary)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(.separator, lineWidth: 0.5)
        )
    }

    private func colorForStatus(_ status: ProjectTaskStatus) -> Color {
        switch status {
        case .notStarted: .secondary
        case .inProgress: .blue
        case .needsHelp: .orange
        case .completed: .green
        }
    }
}

// MARK: - Board Task Card (Trello-style)

struct BoardTaskCard: View {
    let task: ProjectTask
    let project: Project
    @Environment(ProjectViewModel.self) private var projectVM

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(task.title)
                .font(.system(size: 12, weight: .medium))
                .lineLimit(2)
                .multilineTextAlignment(.leading)
                .strikethrough(task.status == .completed)
                .foregroundStyle(task.status == .completed ? .secondary : .primary)

            if !task.taskDescription.isEmpty {
                Text(task.taskDescription)
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
            }

            HStack(spacing: 6) {
                if task.sessionId != nil {
                    Label("Session", systemImage: "bubble.left.and.bubble.right")
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                }

                Spacer()

                Menu {
                    ForEach(ProjectTaskStatus.allCases, id: \.self) { status in
                        Button {
                            projectVM.updateTaskStatus(task.id, in: project, status: status)
                        } label: {
                            Label(status.label, systemImage: status.icon)
                        }
                        .disabled(task.status == status)
                    }
                    Divider()
                    Button(role: .destructive) {
                        projectVM.deleteTask(task.id, in: project)
                    } label: {
                        Label("Delete", systemImage: "trash")
                    }
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                        .frame(width: 16, height: 16)
                }
                .menuStyle(.borderlessButton)
                .frame(width: 16)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .shadow(color: .black.opacity(0.06), radius: 2, x: 0, y: 1)
        .contentShape(Rectangle())
    }
}

// MARK: - Project Row (for sidebar)

struct ProjectRow: View {
    let project: Project

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: "folder.fill")
                    .foregroundStyle(.blue)
                    .font(.caption)
                Text(project.name)
                    .fontWeight(.medium)
                    .font(.system(size: 13))
                    .lineLimit(1)
            }

            HStack(spacing: 12) {
                Label("\(project.tasks.count) tasks", systemImage: "checklist")

                if !project.githubRepo.isEmpty {
                    Label(project.githubRepo, systemImage: "arrow.triangle.branch")
                        .lineLimit(1)
                }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)

            if !project.tasks.isEmpty {
                HStack(spacing: 3) {
                    ForEach(ProjectTaskStatus.allCases, id: \.self) { status in
                        let count = project.tasks(for: status).count
                        if count > 0 {
                            statusDot(status, count: count)
                        }
                    }
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func statusDot(_ status: ProjectTaskStatus, count: Int) -> some View {
        HStack(spacing: 2) {
            Circle()
                .fill(dotColor(status))
                .frame(width: 6, height: 6)
            Text("\(count)")
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
        }
    }

    private func dotColor(_ status: ProjectTaskStatus) -> Color {
        switch status {
        case .notStarted: .secondary
        case .inProgress: .blue
        case .needsHelp: .orange
        case .completed: .green
        }
    }
}

// MARK: - Create Project Sheet

struct CreateProjectSheet: View {
    @Environment(ProjectViewModel.self) private var projectVM
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var folderPath = ""
    @State private var folderPathManuallyEdited = false
    @State private var githubRepo = ""
    @State private var showFolderPicker = false

    private static let defaultBaseDir = "\(NSHomeDirectory())/Documents/Anvil"

    private var isValid: Bool {
        !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var defaultFolderPath: String {
        let safeName = name.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "-")
            .lowercased()
        guard !safeName.isEmpty else { return "" }
        return "\(Self.defaultBaseDir)/\(safeName)"
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("New Project")
                    .font(.headline)
                Spacer()
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                        .font(.system(size: 18))
                }
                .buttonStyle(.plain)
            }
            .padding()

            Divider()

            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Name")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    TextField("My Project", text: $name)
                        .textFieldStyle(.roundedBorder)
                        .onChange(of: name) {
                            if !folderPathManuallyEdited {
                                folderPath = defaultFolderPath
                            }
                        }
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("Folder")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    HStack {
                        TextField("~/Documents/Anvil/my-project", text: $folderPath)
                            .textFieldStyle(.roundedBorder)
                            .onChange(of: folderPath) {
                                if folderPath != defaultFolderPath {
                                    folderPathManuallyEdited = true
                                }
                            }
                        Button("Browse...") {
                            showFolderPicker = true
                        }
                    }
                    Text("The working directory for tasks in this project.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("GitHub Repository (optional)")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    TextField("owner/repo", text: $githubRepo)
                        .textFieldStyle(.roundedBorder)
                }
            }
            .padding()

            Divider()

            HStack {
                Spacer()
                Button("Cancel") {
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Button("Create") {
                    let trimmedFolder = folderPath.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !trimmedFolder.isEmpty {
                        try? FileManager.default.createDirectory(
                            atPath: trimmedFolder,
                            withIntermediateDirectories: true
                        )
                    }
                    projectVM.createProject(
                        name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                        folderPath: trimmedFolder,
                        githubRepo: githubRepo.trimmingCharacters(in: .whitespacesAndNewlines)
                    )
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .disabled(!isValid)
                .keyboardShortcut(.defaultAction)
            }
            .padding()
        }
        .frame(width: 420)
        .fileImporter(
            isPresented: $showFolderPicker,
            allowedContentTypes: [.folder]
        ) { result in
            if case .success(let url) = result {
                folderPath = url.path
                folderPathManuallyEdited = true
            }
        }
    }
}

// MARK: - Add Task Popover

struct AddTaskPopover: View {
    let project: Project
    @Environment(ProjectViewModel.self) private var projectVM
    @Environment(\.dismiss) private var dismiss

    @State private var title = ""
    @State private var description = ""

    var body: some View {
        VStack(spacing: 8) {
            TextField("Task title", text: $title)
                .textFieldStyle(.roundedBorder)
                .frame(width: 240)

            TextField("Description (optional)", text: $description)
                .textFieldStyle(.roundedBorder)
                .frame(width: 240)

            HStack {
                Button("Cancel") { dismiss() }
                Spacer()
                Button("Add") {
                    if !title.isEmpty {
                        projectVM.addTask(to: project, title: title, description: description)
                        title = ""
                        description = ""
                        dismiss()
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(12)
    }
}
