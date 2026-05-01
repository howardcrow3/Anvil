import SwiftUI

struct TeammateView: View {
    @Environment(TeamViewModel.self) private var teamVM
    let teammate: Teammate

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Circle()
                    .fill(stateColor)
                    .frame(width: 8, height: 8)

                Text(teammate.name)
                    .font(.headline)

                Spacer()

                Text(teammate.model)
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.quaternary)
                    .clipShape(Capsule())
            }

            if !teammate.role.isEmpty && teammate.role != "general" {
                Text(teammate.role)
                    .font(.caption)
                    .foregroundStyle(.blue)
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
        .contextMenu {
            if teammate.state != .stopped {
                Button("Send Message") {
                    // Focus message input on this teammate
                }

                Divider()

                Button("Stop", role: .destructive) {
                    Task { await teamVM.stopTeammate(teammate) }
                }
            }
        }
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
