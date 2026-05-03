import SwiftUI

struct GatewaySettingsTab: View {
    @Environment(GatewayViewModel.self) private var gatewayVM

    var body: some View {
        @Bindable var vm = gatewayVM

        Form {
            Section("Gateway") {
                Toggle("Enable Gateway", isOn: $vm.isGatewayEnabled)
                if vm.isGatewayEnabled {
                    HStack {
                        Circle()
                            .fill(vm.isGatewayRunning ? Color.green : Color.red)
                            .frame(width: 8, height: 8)
                        Text(vm.isGatewayRunning ? "Running" : "Stopped")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button(vm.isGatewayRunning ? "Stop" : "Start") {
                            Task { await gatewayVM.toggleGateway() }
                        }
                    }
                }
            }

            Section("Telegram") {
                Toggle("Enabled", isOn: $vm.telegramEnabled)
                if vm.telegramEnabled {
                    SecureField("Bot Token", text: $vm.telegramBotToken)
                    TextField("Allowed User IDs (comma-separated)", text: $vm.telegramAllowedUsers)
                    statusIndicator(vm.telegramConnected)
                }
            }

            Section("Discord") {
                Toggle("Enabled", isOn: $vm.discordEnabled)
                if vm.discordEnabled {
                    SecureField("Bot Token", text: $vm.discordBotToken)
                    TextField("Allowed User IDs (comma-separated)", text: $vm.discordAllowedUsers)
                    statusIndicator(vm.discordConnected)
                }
            }

            Section("Slack") {
                Toggle("Enabled", isOn: $vm.slackEnabled)
                if vm.slackEnabled {
                    SecureField("Bot Token", text: $vm.slackBotToken)
                    SecureField("App Token", text: $vm.slackAppToken)
                    TextField("Allowed User IDs (comma-separated)", text: $vm.slackAllowedUsers)
                    statusIndicator(vm.slackConnected)
                }
            }

            Section("Webhook") {
                Toggle("Enabled", isOn: $vm.webhookEnabled)
                if vm.webhookEnabled {
                    TextField("Port", value: $vm.webhookPort, format: .number)
                    SecureField("HMAC Secret", text: $vm.webhookHmacSecret)
                    statusIndicator(vm.webhookConnected)
                }
            }

            Section {
                Button("Save Configuration") { Task { await gatewayVM.saveConfig() } }
                    .disabled(gatewayVM.isSaving)
            }
        }
        .formStyle(.grouped)
        .padding()
        .onAppear { Task { await gatewayVM.loadConfig() } }
    }

    private func statusIndicator(_ connected: Bool) -> some View {
        HStack {
            Circle()
                .fill(connected ? Color.green : Color.gray)
                .frame(width: 6, height: 6)
            Text(connected ? "Connected" : "Disconnected")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
