import Foundation

@Observable
final class GatewayViewModel: @unchecked Sendable {
    // Master
    var isGatewayEnabled = false
    var isGatewayRunning = false

    // Telegram
    var telegramEnabled = false
    var telegramBotToken = ""
    var telegramAllowedUsers = ""
    var telegramConnected = false

    // Discord
    var discordEnabled = false
    var discordBotToken = ""
    var discordAllowedUsers = ""
    var discordConnected = false

    // Slack
    var slackEnabled = false
    var slackBotToken = ""
    var slackAppToken = ""
    var slackAllowedUsers = ""
    var slackConnected = false

    // Webhook
    var webhookEnabled = false
    var webhookPort = 8432
    var webhookHmacSecret = ""
    var webhookConnected = false

    var isSaving = false
    var statusMessage: String?

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    func loadConfig() async {
        guard ipcClient.isConnected else { return }
        do {
            let data = try await ipcClient.sendRequest(method: "gateway.config.get")
            guard let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

            await MainActor.run {
                isGatewayEnabled = dict["enabled"] as? Bool ?? false

                if let telegram = dict["telegram"] as? [String: Any] {
                    telegramEnabled = telegram["enabled"] as? Bool ?? false
                    telegramBotToken = telegram["bot_token"] as? String ?? ""
                    telegramAllowedUsers = (telegram["allowed_users"] as? [String])?.joined(separator: ", ") ?? ""
                    telegramConnected = telegram["connected"] as? Bool ?? false
                }

                if let discord = dict["discord"] as? [String: Any] {
                    discordEnabled = discord["enabled"] as? Bool ?? false
                    discordBotToken = discord["bot_token"] as? String ?? ""
                    discordAllowedUsers = (discord["allowed_users"] as? [String])?.joined(separator: ", ") ?? ""
                    discordConnected = discord["connected"] as? Bool ?? false
                }

                if let slack = dict["slack"] as? [String: Any] {
                    slackEnabled = slack["enabled"] as? Bool ?? false
                    slackBotToken = slack["bot_token"] as? String ?? ""
                    slackAppToken = slack["app_token"] as? String ?? ""
                    slackAllowedUsers = (slack["allowed_users"] as? [String])?.joined(separator: ", ") ?? ""
                    slackConnected = slack["connected"] as? Bool ?? false
                }

                if let webhook = dict["webhook"] as? [String: Any] {
                    webhookEnabled = webhook["enabled"] as? Bool ?? false
                    webhookPort = webhook["port"] as? Int ?? 8432
                    webhookHmacSecret = webhook["hmac_secret"] as? String ?? ""
                    webhookConnected = webhook["connected"] as? Bool ?? false
                }
            }
        } catch {
            await MainActor.run {
                statusMessage = "Failed to load gateway config: \(error.localizedDescription)"
            }
        }
    }

    func saveConfig() async {
        guard ipcClient.isConnected else { return }
        await MainActor.run { isSaving = true }
        defer { Task { @MainActor in isSaving = false } }

        let params: [String: Any] = [
            "enabled": isGatewayEnabled,
            "telegram": [
                "enabled": telegramEnabled,
                "bot_token": telegramBotToken,
                "allowed_users": telegramAllowedUsers.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
            ],
            "discord": [
                "enabled": discordEnabled,
                "bot_token": discordBotToken,
                "allowed_users": discordAllowedUsers.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
            ],
            "slack": [
                "enabled": slackEnabled,
                "bot_token": slackBotToken,
                "app_token": slackAppToken,
                "allowed_users": slackAllowedUsers.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
            ],
            "webhook": [
                "enabled": webhookEnabled,
                "port": webhookPort,
                "hmac_secret": webhookHmacSecret
            ]
        ]

        do {
            try await ipcClient.sendRequest(method: "gateway.config.set", params: params)
            await MainActor.run { statusMessage = "Gateway configuration saved" }
        } catch {
            await MainActor.run { statusMessage = "Failed to save: \(error.localizedDescription)" }
        }
    }

    func toggleGateway() async {
        guard ipcClient.isConnected else { return }
        let method = isGatewayRunning ? "gateway.stop" : "gateway.start"
        do {
            try await ipcClient.sendRequest(method: method)
            await refreshStatus()
        } catch {
            await MainActor.run { statusMessage = "Failed to toggle gateway: \(error.localizedDescription)" }
        }
    }

    func refreshStatus() async {
        guard ipcClient.isConnected else { return }
        do {
            let data = try await ipcClient.sendRequest(method: "gateway.status")
            guard let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }

            await MainActor.run {
                isGatewayRunning = dict["running"] as? Bool ?? false
                telegramConnected = (dict["telegram"] as? [String: Any])?["connected"] as? Bool ?? false
                discordConnected = (dict["discord"] as? [String: Any])?["connected"] as? Bool ?? false
                slackConnected = (dict["slack"] as? [String: Any])?["connected"] as? Bool ?? false
                webhookConnected = (dict["webhook"] as? [String: Any])?["connected"] as? Bool ?? false
            }
        } catch {
            // Silently fail on status refresh
        }
    }
}
