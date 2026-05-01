import SwiftUI

struct SetupModeStep: View {
    @Environment(OnboardingState.self) private var state

    var body: some View {
        @Bindable var s = state

        VStack(spacing: 20) {
            Text("Choose Your Setup")
                .font(.title2)
                .fontWeight(.bold)
                .padding(.top, 24)

            Text("You can always change this later in Settings.")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            VStack(spacing: 12) {
                SetupModeCard(
                    mode: .localOnly,
                    icon: "desktopcomputer",
                    title: "Local Only",
                    description: "Run models on your Mac with Ollama. No API key needed. Private and offline.",
                    isSelected: state.setupMode == .localOnly
                ) {
                    state.setupMode = .localOnly
                }

                SetupModeCard(
                    mode: .cloudOnly,
                    icon: "cloud",
                    title: "Cloud (Claude API)",
                    description: "Use Claude models via API. Fast, powerful, requires an API key.",
                    isSelected: state.setupMode == .cloudOnly
                ) {
                    state.setupMode = .cloudOnly
                }

                SetupModeCard(
                    mode: .both,
                    icon: "arrow.triangle.2.circlepath",
                    title: "Both",
                    description: "Best of both worlds. Use cloud for complex tasks, local for speed and privacy.",
                    isSelected: state.setupMode == .both
                ) {
                    state.setupMode = .both
                }
            }
            .padding(.horizontal, 24)

            if state.setupMode == .cloudOnly || state.setupMode == .both {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Anthropic API Key")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    SecureField("sk-ant-...", text: $s.apiKey)
                        .textFieldStyle(.roundedBorder)
                }
                .padding(.horizontal, 24)
            }

            Spacer()
        }
    }
}

private struct SetupModeCard: View {
    let mode: SetupMode
    let icon: String
    let title: String
    let description: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.title2)
                    .foregroundStyle(isSelected ? Color.white : Color.accentColor)
                    .frame(width: 36)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .fontWeight(.semibold)
                        .foregroundStyle(isSelected ? .white : .primary)
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(isSelected ? .white.opacity(0.8) : .secondary)
                        .lineLimit(2)
                }

                Spacer()

                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.white)
                }
            }
            .padding(12)
            .background(isSelected ? Color.accentColor : Color.secondary.opacity(0.1))
            .clipShape(RoundedRectangle(cornerRadius: 10))
        }
        .buttonStyle(.plain)
    }
}
