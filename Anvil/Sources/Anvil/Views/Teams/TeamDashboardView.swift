import SwiftUI

struct TeamDashboardView: View {
    @Environment(TeamViewModel.self) private var teamVM

    var body: some View {
        VStack(spacing: 16) {
            if let team = teamVM.team {
                HStack {
                    VStack(alignment: .leading) {
                        Text(team.name)
                            .font(.title2)
                            .fontWeight(.bold)
                        Text(team.status.rawValue.capitalized)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()

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
                }
                .padding(.horizontal)

                ScrollView {
                    LazyVGrid(columns: [
                        GridItem(.adaptive(minimum: 250, maximum: 350))
                    ], spacing: 12) {
                        ForEach(team.teammates) { teammate in
                            TeammateView(teammate: teammate)
                        }
                    }
                    .padding(.horizontal)
                }
            } else {
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
                        teamVM.createTeam(name: "Default Team")
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .padding(.top)
    }
}
