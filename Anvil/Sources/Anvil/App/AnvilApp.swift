import SwiftUI

@main
struct AnvilApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @State private var chatVM = ChatViewModel()
    @State private var sessionVM = SessionViewModel()
    @State private var modelVM = ModelViewModel()
    @State private var teamVM = TeamViewModel()
    @State private var settingsVM = SettingsViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(chatVM)
                .environment(sessionVM)
                .environment(modelVM)
                .environment(teamVM)
                .environment(settingsVM)
                .frame(minWidth: 900, minHeight: 600)
        }
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Session") {
                    let session = sessionVM.createSession(name: "New Session")
                    sessionVM.selectedSession = session
                    chatVM.clearMessages()
                }
                .keyboardShortcut("n")
            }

            CommandMenu("View") {
                Button("Toggle Terminal") {
                    NotificationCenter.default.post(name: .toggleTerminal, object: nil)
                }
                .keyboardShortcut("t", modifiers: [.command, .shift])

                Button("Toggle Sidebar") {
                    NotificationCenter.default.post(name: .toggleSidebar, object: nil)
                }
                .keyboardShortcut("s", modifiers: [.command, .shift])
            }

            CommandGroup(replacing: .help) {
                Button("Anvil Help") {
                    // Open help
                }
            }
        }

        Settings {
            SettingsView()
                .environment(settingsVM)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let ollamaService = OllamaService()

    func applicationDidFinishLaunching(_ notification: Notification) {
        Task {
            try? await ollamaService.start()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        ollamaService.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }
}

extension Notification.Name {
    static let toggleTerminal = Notification.Name("toggleTerminal")
    static let toggleSidebar = Notification.Name("toggleSidebar")
}
