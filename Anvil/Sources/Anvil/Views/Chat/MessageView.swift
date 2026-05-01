import SwiftUI

struct MessageView: View {
    let message: Message

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            avatar
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(roleLabel)
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(roleColor)
                    Spacer()
                    Text(message.timestamp.relativeFormatted)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }

                Text(message.content)
                    .textSelection(.enabled)
                    .font(.body)

                ForEach(message.toolCalls) { toolCall in
                    ToolCallView(toolCall: toolCall)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(backgroundColor)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var avatar: some View {
        Image(systemName: avatarIcon)
            .font(.title3)
            .frame(width: 28, height: 28)
            .foregroundStyle(roleColor)
    }

    private var avatarIcon: String {
        switch message.role {
        case .user: "person.fill"
        case .assistant: "cpu"
        case .system: "gearshape.fill"
        case .toolUse: "wrench.fill"
        case .toolResult: "checkmark.circle.fill"
        }
    }

    private var roleLabel: String {
        switch message.role {
        case .user: "You"
        case .assistant: "Assistant"
        case .system: "System"
        case .toolUse: "Tool Use"
        case .toolResult: "Tool Result"
        }
    }

    private var roleColor: Color {
        switch message.role {
        case .user: .blue
        case .assistant: .purple
        case .system: .gray
        case .toolUse: .orange
        case .toolResult: .green
        }
    }

    private var backgroundColor: Color {
        switch message.role {
        case .user: .blue.opacity(0.05)
        case .assistant: .purple.opacity(0.05)
        default: .clear
        }
    }
}
