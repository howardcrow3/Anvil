import SwiftUI

struct CompletionStep: View {
    @Environment(OnboardingState.self) private var state
    let onComplete: () -> Void

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 56))
                .foregroundStyle(.green)

            VStack(spacing: 8) {
                Text("You're All Set!")
                    .font(.largeTitle)
                    .fontWeight(.bold)

                Text("Anvil is ready to use.")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 10) {
                TipRow(icon: "command", text: "Press Cmd+N to start a new session")
                TipRow(icon: "terminal", text: "Press Cmd+Shift+T to toggle the terminal")
                TipRow(icon: "slash.circle", text: "Type / in the chat for slash commands")
                TipRow(icon: "person.3", text: "Create agent teams from the sidebar")
            }
            .padding(.horizontal, 60)
            .padding(.top, 8)

            Button("Get Started") {
                onComplete()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .padding(.top, 8)

            Spacer()
        }
    }
}

private struct TipRow: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.caption)
                .foregroundColor(.accentColor)
                .frame(width: 20)
            Text(text)
                .font(.subheadline)
        }
    }
}
