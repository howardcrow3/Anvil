import SwiftUI

struct TeammateSpec: Identifiable {
    let id = UUID()
    var name: String = ""
    var role: String = "general"
    var model: String = "claude-sonnet-4-6"
}

struct TaskSpec: Identifiable {
    let id = UUID()
    var title: String = ""
    var assignee: String = ""
}

struct CreateTeamSheet: View {
    @Environment(TeamViewModel.self) private var teamVM
    @Environment(ModelViewModel.self) private var modelVM
    @Environment(\.dismiss) private var dismiss

    @State private var teamName = ""
    @State private var teammates: [TeammateSpec] = [
        TeammateSpec(name: "coder", role: "implementation", model: "claude-sonnet-4-6")
    ]
    @State private var tasks: [TaskSpec] = []

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    teamNameSection
                    teammatesSection
                    tasksSection
                }
                .padding(20)
            }
            Divider()
            footer
        }
        .frame(width: 550, height: 500)
    }

    private var header: some View {
        HStack {
            Text("Create Agent Team")
                .font(.headline)
            Spacer()
            Button("Cancel") { dismiss() }
                .keyboardShortcut(.escape)
        }
        .padding(16)
    }

    private var teamNameSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Team Name")
                .font(.subheadline)
                .fontWeight(.medium)
            TextField("e.g. Feature Team", text: $teamName)
                .textFieldStyle(.roundedBorder)
        }
    }

    private var teammatesSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Teammates")
                    .font(.subheadline)
                    .fontWeight(.medium)
                Spacer()
                Button {
                    teammates.append(TeammateSpec())
                } label: {
                    Image(systemName: "plus.circle")
                }
                .buttonStyle(.plain)
            }

            ForEach($teammates) { $spec in
                HStack(spacing: 8) {
                    TextField("Name", text: $spec.name)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 100)

                    TextField("Role", text: $spec.role)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 120)

                    Picker("", selection: $spec.model) {
                        ForEach(modelVM.models) { model in
                            Text(model.name).tag(model.id)
                        }
                    }
                    .frame(width: 160)

                    Button {
                        teammates.removeAll { $0.id == spec.id }
                    } label: {
                        Image(systemName: "minus.circle")
                            .foregroundStyle(.red)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var tasksSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Tasks")
                    .font(.subheadline)
                    .fontWeight(.medium)
                Spacer()
                Button {
                    tasks.append(TaskSpec())
                } label: {
                    Image(systemName: "plus.circle")
                }
                .buttonStyle(.plain)
            }

            ForEach($tasks) { $spec in
                HStack(spacing: 8) {
                    TextField("Task title", text: $spec.title)
                        .textFieldStyle(.roundedBorder)

                    Picker("Assignee", selection: $spec.assignee) {
                        Text("Unassigned").tag("")
                        ForEach(teammates) { teammate in
                            Text(teammate.name.isEmpty ? "Agent" : teammate.name)
                                .tag(teammate.name)
                        }
                    }
                    .frame(width: 140)

                    Button {
                        tasks.removeAll { $0.id == spec.id }
                    } label: {
                        Image(systemName: "minus.circle")
                            .foregroundStyle(.red)
                    }
                    .buttonStyle(.plain)
                }
            }

            if tasks.isEmpty {
                Text("No tasks yet. Add tasks to assign to teammates.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var footer: some View {
        HStack {
            Text("\(teammates.count) teammates, \(tasks.count) tasks")
                .font(.caption)
                .foregroundStyle(.secondary)

            Spacer()

            Button("Create & Start") {
                let membersData = teammates.map { t -> [String: String] in
                    ["name": t.name, "role": t.role, "model": t.model]
                }
                let tasksData = tasks.map { t -> [String: String] in
                    var d: [String: String] = ["title": t.title]
                    if !t.assignee.isEmpty { d["assignee"] = t.assignee }
                    return d
                }
                let name = teamName.isEmpty ? "Team" : teamName
                Task {
                    await teamVM.createTeamViaIPC(
                        name: name,
                        teammates: membersData,
                        tasks: tasksData
                    )
                    dismiss()
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(teamName.isEmpty && teammates.isEmpty)
        }
        .padding(16)
    }
}
