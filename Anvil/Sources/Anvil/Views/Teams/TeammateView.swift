import SwiftUI

struct TeammateView: View {
    let teammate: Teammate

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Circle()
                    .fill(teammate.isActive ? .green : .gray)
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
                Text(teammate.isActive ? "Active" : "Idle")
                    .font(.caption2)
                    .foregroundStyle(teammate.isActive ? .green : .secondary)
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
}
