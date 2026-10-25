import SwiftUI

struct AgentsView: View {
    @Environment(AgentActivityViewModel.self) private var vm
    @State private var newTaskTitle = ""
    @State private var steerText: [String: String] = [:]

    var body: some View {
        List {
            subagentsSection
            kanbanSection
            learningSection
        }
        .listStyle(.sidebar)
        .task { await vm.load() }
    }

    // MARK: Subagents

    private var subagentsSection: some View {
        Section {
            if vm.subagents.isEmpty {
                Text("No subagents yet").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(vm.subagents.prefix(15)) { agent in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Circle().fill(color(for: agent.state)).frame(width: 8, height: 8)
                        Text(agent.goal).font(.callout).lineLimit(2)
                    }
                    Text("\(agent.role) · \(agent.state) · \(agent.toolCalls) tools · \(Int(agent.elapsed))s")
                        .font(.caption2).foregroundStyle(.secondary)
                    if let text = agent.error ?? agent.summary, !agent.isActive, !text.isEmpty {
                        Text(text).font(.caption).foregroundStyle(.secondary).lineLimit(3)
                    }
                    if agent.isActive {
                        HStack {
                            TextField("Steer…", text: Binding(
                                get: { steerText[agent.id] ?? "" },
                                set: { steerText[agent.id] = $0 }
                            ))
                            .textFieldStyle(.roundedBorder)
                            .onSubmit { send(agent.id) }
                            Button("Stop", role: .destructive) { Task { await vm.stop(agent.id) } }
                        }
                    }
                }
                .padding(.vertical, 2)
            }
        } header: {
            HStack {
                Text("Subagents")
                Spacer()
                if !vm.activeSubagents.isEmpty {
                    Button("Stop all") { Task { await vm.stopAll() } }.buttonStyle(.link)
                }
            }
        }
    }

    private func send(_ id: String) {
        let text = steerText[id] ?? ""
        steerText[id] = ""
        Task { await vm.steer(id, message: text) }
    }

    // MARK: Kanban

    private var kanbanSection: some View {
        Section {
            HStack {
                TextField("New task…", text: $newTaskTitle)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(addTask)
                Button(action: addTask) { Image(systemName: "plus.circle.fill") }
                    .buttonStyle(.plain)
            }
            Toggle("Run ready tasks automatically", isOn: Binding(
                get: { vm.dispatcherRunning },
                set: { on in Task { await vm.setDispatcher(on) } }
            ))
            .font(.caption)
            ForEach(["running", "ready", "todo", "blocked", "done"], id: \.self) { status in
                let items = vm.tasks(in: status)
                if !items.isEmpty {
                    Text("\(status.capitalized) (\(items.count))")
                        .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                    ForEach(items) { task in taskRow(task) }
                }
            }
        } header: {
            Text("Kanban")
        }
    }

    private func taskRow(_ task: KanbanTaskInfo) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(task.title).font(.callout).lineLimit(2)
            if let result = task.result, task.status == "done", !result.isEmpty {
                Text(result).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
        }
        .contextMenu {
            if task.status == "blocked" { Button("Unblock") { Task { await vm.taskAction(task.id, "unblock") } } }
            if task.status == "running" { Button("Stop worker") { Task { await vm.taskAction(task.id, "stop") } } }
            if task.status != "done" {
                Button("Mark done") { Task { await vm.taskAction(task.id, "complete", extra: ["summary": "Completed manually"]) } }
                Button("Block") { Task { await vm.taskAction(task.id, "block", extra: ["reason": "Blocked by user"]) } }
            }
            Button("Archive") { Task { await vm.taskAction(task.id, "archive") } }
        }
    }

    private func addTask() {
        let title = newTaskTitle
        newTaskTitle = ""
        Task { await vm.createTask(title: title) }
    }

    // MARK: Learning

    private var learningSection: some View {
        Section("Learning") {
            if let note = vm.lastReviewNote {
                Label(note, systemImage: "brain").font(.caption).lineLimit(4)
            }
            Text("Agent skills: \(vm.curator.activeCount) active · \(vm.curator.staleCount) stale · \(vm.curator.archived) archived")
                .font(.caption).foregroundStyle(.secondary)
            if let last = vm.curator.lastRunAt {
                Text("Curator last ran \(last.formatted(.relative(presentation: .named)))")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Button("Run curator now") { Task { await vm.runCurator() } }
                .disabled(!vm.curator.enabled)
        }
    }

    private func color(for state: String) -> Color {
        switch state {
        case "running": .blue
        case "succeeded": .green
        case "failed": .red
        case "cancelled": .gray
        default: .orange
        }
    }
}
