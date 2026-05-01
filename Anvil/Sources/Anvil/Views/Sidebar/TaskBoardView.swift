import SwiftUI

struct TaskBoardView: View {
    @Environment(TeamViewModel.self) private var teamVM

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Tasks")
                    .font(.headline)
                Spacer()
                Button {
                    teamVM.addTask(title: "New Task")
                } label: {
                    Image(systemName: "plus")
                }
                .help("Add Task")
            }
            .padding(8)

            if let tasks = teamVM.team?.tasks, !tasks.isEmpty {
                List(tasks) { task in
                    TaskRow(task: task)
                }
                .listStyle(.sidebar)
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "checklist")
                        .font(.title2)
                        .foregroundStyle(.tertiary)
                    Text("No tasks yet")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
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

                if let assignee = task.assignee {
                    Text(assignee)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private var statusIcon: String {
        switch task.status {
        case .pending: "circle"
        case .inProgress: "circle.dotted.circle"
        case .completed: "checkmark.circle.fill"
        }
    }

    private var statusColor: Color {
        switch task.status {
        case .pending: .secondary
        case .inProgress: .orange
        case .completed: .green
        }
    }
}
