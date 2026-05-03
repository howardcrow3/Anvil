import Foundation
import SwiftUI

struct CompletionStep: View {
    @Environment(OnboardingState.self) private var state
    let onComplete: () -> Void

    /// Write the API key to ~/.anvil/config.json so the Python runtime picks it up on start.
    private func saveOnboardingSettings() {
        let apiKey = state.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !apiKey.isEmpty else { return }

        let anvilDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".anvil")
        let configPath = anvilDir.appendingPathComponent("config.json")

        // Ensure ~/.anvil/ exists
        try? FileManager.default.createDirectory(at: anvilDir, withIntermediateDirectories: true)

        // Merge into existing config or create new
        var config: [String: Any] = [:]
        if let data = try? Data(contentsOf: configPath),
           let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            config = existing
        }
        config["api_key"] = apiKey

        if let data = try? JSONSerialization.data(withJSONObject: config, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: configPath)
        }
    }

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
                saveOnboardingSettings()
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
