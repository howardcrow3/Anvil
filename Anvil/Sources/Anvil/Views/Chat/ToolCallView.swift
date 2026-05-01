import SwiftUI

struct ToolCallView: View {
    let toolCall: ToolCall
    @State private var isExpanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            VStack(alignment: .leading, spacing: 8) {
                if !toolCall.arguments.isEmpty {
                    Text("Arguments")
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)

                    ForEach(Array(toolCall.arguments.keys.sorted()), id: \.self) { key in
                        HStack(alignment: .top) {
                            Text(key + ":")
                                .font(.system(.caption, design: .monospaced))
                                .foregroundStyle(.secondary)
                            Text(toolCall.arguments[key] ?? "")
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                        }
                    }
                }

                if let result = toolCall.result {
                    Divider()
                    Text("Result")
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)
                    Text(result)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .lineLimit(20)
                }
            }
            .padding(8)
        } label: {
            HStack(spacing: 6) {
                statusIcon
                Text(toolCall.name)
                    .font(.system(.caption, design: .monospaced))
                    .fontWeight(.medium)
                Spacer()
                statusBadge
            }
        }
        .padding(8)
        .background(.quaternary.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch toolCall.status {
        case .running:
            ProgressView()
                .scaleEffect(0.5)
                .frame(width: 14, height: 14)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .font(.caption)
        case .error:
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(.red)
                .font(.caption)
        }
    }

    private var statusBadge: some View {
        Text(toolCall.status.rawValue)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(statusColor.opacity(0.15))
            .foregroundStyle(statusColor)
            .clipShape(Capsule())
    }

    private var statusColor: Color {
        switch toolCall.status {
        case .running: .orange
        case .done: .green
        case .error: .red
        }
    }
}
