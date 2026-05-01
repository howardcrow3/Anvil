import SwiftUI

@main
struct AnvilApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @State private var ipcClient = IPCClient()
    @State private var chatVM: ChatViewModel?
    @State private var sessionVM: SessionViewModel?
    @State private var modelVM: ModelViewModel?
    @State private var teamVM: TeamViewModel?
    @State private var settingsVM: SettingsViewModel?

    var body: some Scene {
        WindowGroup {
            if let chatVM, let sessionVM, let modelVM, let teamVM, let settingsVM {
                ContentView()
                    .environment(chatVM)
                    .environment(sessionVM)
                    .environment(modelVM)
                    .environment(teamVM)
                    .environment(settingsVM)
                    .frame(minWidth: 900, minHeight: 600)
                    .task {
                        await startRuntime()
                    }
            } else {
                ProgressView("Starting Anvil...")
                    .task { initViewModels() }
            }
        }
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Session") {
                    if let sessionVM, let chatVM {
                        let session = sessionVM.createSession(name: "New Session")
                        sessionVM.selectedSession = session
                        chatVM.clearMessages()
                    }
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
            if let settingsVM {
                SettingsView()
                    .environment(settingsVM)
            }
        }
    }

    private func initViewModels() {
        chatVM = ChatViewModel(ipcClient: ipcClient)
        sessionVM = SessionViewModel(ipcClient: ipcClient)
        modelVM = ModelViewModel(ipcClient: ipcClient)
        teamVM = TeamViewModel(ipcClient: ipcClient)
        settingsVM = SettingsViewModel(ipcClient: ipcClient)
    }

    private func startRuntime() async {
        let runtime = appDelegate.runtimeService
        do {
            try await runtime.start()
            if let socketPath = runtime.socketPath {
                ipcClient.updateSocketPath(socketPath)
                ipcClient.enableReconnect()
                try? await ipcClient.connect()
                await modelVM?.refreshModels()
                sessionVM?.loadSessions()
                settingsVM?.loadSettings()
            }
        } catch {
            print("Failed to start agent runtime: \(error.localizedDescription)")
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let ollamaService = OllamaService()
    let runtimeService = AgentRuntimeService()

    func applicationDidFinishLaunching(_ notification: Notification) {
        Task {
            try? await ollamaService.start()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        runtimeService.stop()
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
