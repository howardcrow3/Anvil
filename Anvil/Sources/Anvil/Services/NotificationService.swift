import UserNotifications
import AppKit

final class NotificationService: @unchecked Sendable {
    private var hasPermission = false

    func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, _ in
            self.hasPermission = granted
        }
    }

    func notifyAgentComplete(sessionName: String, summary: String) {
        guard hasPermission, !NSApp.isActive else { return }
        let content = UNMutableNotificationContent()
        content.title = "Agent Complete"
        content.subtitle = sessionName
        content.body = summary
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    func notifyTeamComplete(teamName: String) {
        guard hasPermission, !NSApp.isActive else { return }
        let content = UNMutableNotificationContent()
        content.title = "Team Complete"
        content.body = "\(teamName) has finished all tasks."
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    func notifyModelReady(modelName: String) {
        guard hasPermission, !NSApp.isActive else { return }
        let content = UNMutableNotificationContent()
        content.title = "Model Ready"
        content.body = "\(modelName) has finished downloading."
        content.sound = .default
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
