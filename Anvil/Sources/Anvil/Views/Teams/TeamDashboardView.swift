import SwiftUI

struct TeamDashboardView: View {
    @Environment(TeamViewModel.self) private var teamVM
    @State private var showCreateSheet = false

    var body: some View {
        if let team = teamVM.team {
            VStack(spacing: 0) {
                teamHeader(team)
                Divider()
                displayContent(team)
            }
        } else {
            emptyState
        }
    }

    private func teamHeader(_ team: AgentTeam) -> some View {
        @Bindable var vm = teamVM

        return HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(team.name)
                    .font(.headline)
                HStack(spacing: 8) {
                    Text(team.status.rawValue.capitalized)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if !team.tasks.isEmpty {
                        Text("\(Int(team.progress * 100))%")
                            .font(.caption)
                            .fontWeight(.medium)
                            .foregroundStyle(.blue)
                    }
                }
            }

            Spacer()

            Picker("View", selection: $vm.displayMode) {
                ForEach(TeamDisplayMode.allCases, id: \.self) { mode in
                    Label(mode.label, systemImage: mode.icon).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 280)

            Button {
                if teamVM.isRunning {
                    teamVM.stopTeam()
                } else {
                    teamVM.startTeam()
                }
            } label: {
                Label(
                    teamVM.isRunning ? "Stop" : "Start",
                    systemImage: teamVM.isRunning ? "stop.fill" : "play.fill"
                )
            }
            .controlSize(.small)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    @ViewBuilder
    private func displayContent(_ team: AgentTeam) -> some View {
        switch teamVM.displayMode {
        case .dashboard:
            dashboardView(team)
        case .tabbed:
            tabbedView(team)
        case .split:
            splitView(team)
        case .focus:
            focusView(team)
        }
    }

    // MARK: - Dashboard Mode

    private func dashboardView(_ team: AgentTeam) -> some View {
        VSplitView {
            ScrollView {
                LazyVGrid(columns: [
                    GridItem(.adaptive(minimum: 240, maximum: 320))
                ], spacing: 12) {
                    ForEach(team.teammates) { teammate in
                        TeammateCardView(teammate: teammate)
                            .onTapGesture {
                                teamVM.focusedTeammateId = teammate.id
                                teamVM.displayMode = .focus
                            }
                    }

                    addTeammateCard
                }
                .padding(16)
            }

            VStack(spacing: 0) {
                Divider()
                HStack(spacing: 0) {
                    taskSummary(team)
                    Divider()
                    TeamMessageView()
                }
            }
            .frame(minHeight: 180)
        }
    }

    // MARK: - Tabbed Mode

    private func tabbedView(_ team: AgentTeam) -> some View {
        TabView {
            ForEach(team.teammates) { teammate in
                TeammateDetailView(teammate: teammate)
                    .tabItem {
                        Label(teammate.name, systemImage: teammate.isActive ? "circle.fill" : "circle")
                    }
            }

            TeamMessageView()
                .tabItem {
                    Label("Messages", systemImage: "bubble.left.and.bubble.right")
                }
        }
    }

    // MARK: - Split Mode

    private func splitView(_ team: AgentTeam) -> some View {
        HSplitView {
            if team.teammates.count >= 1 {
                TeammateDetailView(teammate: team.teammates[0])
            }
            if team.teammates.count >= 2 {
                TeammateDetailView(teammate: team.teammates[1])
            } else {
                VStack {
                    Text("Add another teammate for split view")
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
    }

    // MARK: - Focus Mode

    private func focusView(_ team: AgentTeam) -> some View {
        let focused = team.teammates.first { $0.id == teamVM.focusedTeammateId }
            ?? team.teammates.first

        return VStack {
            if let focused {
                TeammateDetailView(teammate: focused)
            } else {
                Text("No teammates to focus on")
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Helpers

    private func taskSummary(_ team: AgentTeam) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Tasks")
                .font(.subheadline)
                .fontWeight(.medium)
                .padding(.horizontal, 12)
                .padding(.top, 8)

            if team.tasks.isEmpty {
                Text("No tasks")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 12)
            } else {
                List {
                    ForEach(team.tasks) { task in
                        TaskRow(task: task)
                    }
                }
                .listStyle(.plain)
            }
        }
        .frame(minWidth: 250)
    }

    private var addTeammateCard: some View {
        Button {
            showCreateSheet = true
        } label: {
            VStack(spacing: 8) {
                Image(systemName: "plus.circle.dashed")
                    .font(.title2)
                Text("Add Teammate")
                    .font(.caption)
            }
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, minHeight: 100)
            .background(.background.secondary)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(.quaternary, style: StrokeStyle(lineWidth: 1, dash: [6]))
            )
        }
        .buttonStyle(.plain)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "person.3")
                .font(.system(size: 48))
                .foregroundStyle(.tertiary)
            Text("No team active")
                .font(.headline)
            Text("Create a team to get started with multi-agent workflows")
                .font(.caption)
                .foregroundStyle(.secondary)
            Button("Create Team") {
                showCreateSheet = true
            }
            .buttonStyle(.borderedProminent)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .sheet(isPresented: $showCreateSheet) {
            CreateTeamSheet()
        }
    }
}

// MARK: - Teammate Card (Grid)

struct TeammateCardView: View {
    let teammate: Teammate

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Circle()
                    .fill(stateColor)
                    .frame(width: 10, height: 10)

                Text(teammate.name)
                    .font(.headline)

                Spacer()

                Text(teammate.model)
                    .font(.caption2)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(.quaternary)
                    .clipShape(Capsule())
            }

            if !teammate.role.isEmpty && teammate.role != "general" {
                Text(teammate.role)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let task = teammate.currentTask {
                HStack(spacing: 4) {
                    Image(systemName: "arrow.right.circle")
                        .font(.caption2)
                    Text(task)
                        .font(.caption)
                        .lineLimit(1)
                }
                .foregroundStyle(.secondary)
            }

            HStack {
                Label("\(teammate.messages)", systemImage: "bubble.left")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                Spacer()
                Text(teammate.state.rawValue.capitalized)
                    .font(.caption2)
                    .fontWeight(.medium)
                    .foregroundStyle(stateColor)
            }
        }
        .padding(12)
        .background(.background.secondary)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(.quaternary)
        )
    }

    private var stateColor: Color {
        switch teammate.state {
        case .idle: .secondary
        case .working: .green
        case .blocked: .orange
        case .stopped: .red
        }
    }
}

// MARK: - Teammate Detail (Expanded)

struct TeammateDetailView: View {
    let teammate: Teammate

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Circle()
                    .fill(teammate.isActive ? .green : .secondary)
                    .frame(width: 10, height: 10)
                Text(teammate.name)
                    .font(.title3)
                    .fontWeight(.semibold)
                Text("(\(teammate.role))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text(teammate.model)
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.quaternary)
                    .clipShape(Capsule())

                Text(teammate.state.rawValue.capitalized)
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(teammate.isActive ? .green : .secondary)
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)

            Divider()

            if let task = teammate.currentTask {
                HStack(spacing: 6) {
                    Image(systemName: "checklist")
                    Text("Working on: \(task)")
                        .font(.callout)
                }
                .padding(.horizontal, 16)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text("Teammate activity will appear here when connected to the runtime.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(16)
        }
    }
}
