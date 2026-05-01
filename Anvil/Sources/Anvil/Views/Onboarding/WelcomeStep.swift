import SwiftUI

struct WelcomeStep: View {
    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: "hammer.fill")
                .font(.system(size: 64))
                .foregroundColor(.accentColor)

            VStack(spacing: 8) {
                Text("Welcome to Anvil")
                    .font(.largeTitle)
                    .fontWeight(.bold)

                Text("Where agents are forged.")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 12) {
                FeatureRow(icon: "cpu", title: "Cloud & Local Models", description: "Claude API, Ollama, or any OpenAI-compatible endpoint")
                FeatureRow(icon: "person.3", title: "Multi-Agent Teams", description: "Coordinate multiple AI agents on complex tasks")
                FeatureRow(icon: "terminal", title: "Full Dev Environment", description: "File editing, terminal access, git integration")
            }
            .padding(.horizontal, 40)
            .padding(.top, 12)

            Spacer()
        }
    }
}

private struct FeatureRow: View {
    let icon: String
    let title: String
    let description: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundColor(.accentColor)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .fontWeight(.medium)
                Text(description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
