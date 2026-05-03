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
    @State private var gatewayVM: GatewayViewModel?
    @State private var updateService = UpdateService()
    @AppStorage("hasCompletedOnboarding") private var hasCompletedOnboarding = false

    var body: some Scene {
        WindowGroup {
            if !hasCompletedOnboarding {
                OnboardingView {
                    hasCompletedOnboarding = true
                }
            } else if let chatVM, let sessionVM, let modelVM, let teamVM, let settingsVM, let gatewayVM {
                ContentView()
                    .environment(chatVM)
                    .environment(sessionVM)
                    .environment(modelVM)
                    .environment(teamVM)
                    .environment(settingsVM)
                    .environment(gatewayVM)
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
                Button("Check for Updates...") {
                    updateService.checkForUpdates()
                }

                Divider()

                Button("Anvil Help") {
                    // Open help
                }
            }
        }

        Settings {
            if let settingsVM, let gatewayVM {
                SettingsView()
                    .environment(settingsVM)
                    .environment(gatewayVM)
            }
        }
    }

    private func initViewModels() {
        chatVM = ChatViewModel(ipcClient: ipcClient)
        sessionVM = SessionViewModel(ipcClient: ipcClient)
        modelVM = ModelViewModel(ipcClient: ipcClient)
        teamVM = TeamViewModel(ipcClient: ipcClient)
        settingsVM = SettingsViewModel(ipcClient: ipcClient)
        gatewayVM = GatewayViewModel(ipcClient: ipcClient)
    }

    private func startRuntime() async {
        // Ensure Ollama is ready before starting the Python agent runtime
        // (start() is idempotent — it piggybacks if already running)
        try? await appDelegate.ollamaService.start()

        let runtime = appDelegate.runtimeService
        do {
            try await runtime.start()
            if let socketPath = runtime.socketPath {
                NSLog("[Anvil] Got socket path: %@", socketPath)
                ipcClient.updateSocketPath(socketPath)
                ipcClient.enableReconnect()
                do {
                    try await ipcClient.connect()
                    NSLog("[Anvil] IPC connected successfully")
                } catch {
                    NSLog("[Anvil] IPC connection failed: %@", error.localizedDescription)
                }
                await modelVM?.refreshModels()
                sessionVM?.loadSessions()
                settingsVM?.loadSettings()
            } else {
                NSLog("[Anvil] Runtime started but no socket path received")
            }
        } catch {
            NSLog("[Anvil] Failed to start agent runtime: %@", error.localizedDescription)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let ollamaService = OllamaService()
    let runtimeService = AgentRuntimeService()
    let menuBarService = MenuBarService()
    let notificationService = NotificationService()

    func applicationDidFinishLaunching(_ notification: Notification) {
        menuBarService.setup()
        notificationService.requestPermission()
        Task {
            try? await ollamaService.start()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        menuBarService.tearDown()
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
