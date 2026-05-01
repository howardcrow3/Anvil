import SwiftUI

struct APIKeySettingsView: View {
    @Environment(SettingsViewModel.self) private var settingsVM
    @State private var showKey = false

    var body: some View {
        @Bindable var vm = settingsVM

        Form {
            Section("Anthropic") {
                HStack {
                    if showKey {
                        TextField("API Key", text: $vm.apiKeyInput)
                            .textFieldStyle(.roundedBorder)
                    } else {
                        SecureField("API Key", text: $vm.apiKeyInput)
                            .textFieldStyle(.roundedBorder)
                    }

                    Button {
                        showKey.toggle()
                    } label: {
                        Image(systemName: showKey ? "eye.slash" : "eye")
                    }
                    .help(showKey ? "Hide API Key" : "Show API Key")
                }

                Text("Your API key is stored securely in the macOS Keychain.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section {
                Button("Save API Key") {
                    settingsVM.saveSettings()
                }
                .disabled(settingsVM.apiKeyInput.isEmpty)
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}
