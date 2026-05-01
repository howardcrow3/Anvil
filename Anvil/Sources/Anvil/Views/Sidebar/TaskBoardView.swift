import SwiftUI

struct TaskBoardView: View {
    @Environment(TeamViewModel.self) private var teamVM
    @State private var showAddTask = false
    @State private var newTaskTitle = ""

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Tasks")
                    .font(.headline)
                Spacer()
                if teamVM.team != nil {
                    Button {
                        showAddTask.toggle()
                    } label: {
                        Image(systemName: "plus")
                    }
                    .help("Add Task")
                    .popover(isPresented: $showAddTask) {
                        addTaskPopover
                    }
                }
            }
            .padding(8)

            if let team = teamVM.team, !team.tasks.isEmpty {
                List {
                    if !team.inProgressTasks.isEmpty {
                        Section("In Progress") {
                            ForEach(team.inProgressTasks) { task in
                                TaskRow(task: task)
                            }
                        }
                    }

                    if !team.pendingTasks.isEmpty {
                        Section("Pending") {
                            ForEach(team.pendingTasks) { task in
                                TaskRow(task: task)
                            }
                        }
                    }

                    if !team.completedTasks.isEmpty {
                        Section("Completed") {
                            ForEach(team.completedTasks) { task in
                                TaskRow(task: task)
                            }
                        }
                    }
                }
                .listStyle(.sidebar)

                progressBar(team)
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "checklist")
                        .font(.title2)
                        .foregroundStyle(.tertiary)
                    Text("No tasks yet")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if teamVM.team != nil {
                        Text("Add tasks to track team progress")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    private var addTaskPopover: some View {
        VStack(spacing: 8) {
            TextField("Task title", text: $newTaskTitle)
                .textFieldStyle(.roundedBorder)
                .frame(width: 200)
                .onSubmit {
                    if !newTaskTitle.isEmpty {
                        teamVM.createTask(title: newTaskTitle)
                        newTaskTitle = ""
                        showAddTask = false
                    }
                }
            HStack {
                Button("Cancel") { showAddTask = false }
                Spacer()
                Button("Add") {
                    if !newTaskTitle.isEmpty {
                        teamVM.createTask(title: newTaskTitle)
                        newTaskTitle = ""
                        showAddTask = false
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(newTaskTitle.isEmpty)
            }
        }
        .padding(12)
    }

    private func progressBar(_ team: AgentTeam) -> some View {
        VStack(spacing: 4) {
            ProgressView(value: team.progress)
                .tint(.green)
            HStack {
                Text("\(team.completedTasks.count)/\(team.tasks.count) complete")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(Int(team.progress * 100))%")
                    .font(.caption2)
                    .fontWeight(.medium)
            }
        }
        .padding(8)
    }
}

struct TaskRow: View {
    let task: AgentTask

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: statusIcon)
                .foregroundStyle(statusColor)
                .font(.caption)

            VStack(alignment: .leading, spacing: 2) {
                Text(task.title)
                    .font(.caption)
                    .lineLimit(1)

                HStack(spacing: 6) {
                    if let assignee = task.assignee, !assignee.isEmpty {
                        Label(assignee, systemImage: "person")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }

                    if task.isBlocked {
                        Label("Blocked", systemImage: "exclamationmark.triangle")
                            .font(.caption2)
                            .foregroundStyle(.orange)
                    }

                    if !task.dependsOn.isEmpty {
                        Label("\(task.dependsOn.count) dep", systemImage: "arrow.branch")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
        }
        .padding(.vertical, 2)
    }

    private var statusIcon: String {
        switch task.status {
        case .pending: task.isBlocked ? "lock.circle" : "circle"
        case .inProgress: "circle.dotted.circle"
        case .completed: "checkmark.circle.fill"
        }
    }

    private var statusColor: Color {
        switch task.status {
        case .pending: task.isBlocked ? .orange : .secondary
        case .inProgress: .blue
        case .completed: .green
        }
    }
}
