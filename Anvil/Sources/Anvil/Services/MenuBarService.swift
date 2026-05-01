import AppKit
import SwiftUI

final class MenuBarService: @unchecked Sendable {
    private var statusItem: NSStatusItem?
    private var isAgentRunning = false

    func setup() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            button.image = NSImage(systemSymbolName: "hammer.fill", accessibilityDescription: "Anvil")
            button.image?.size = NSSize(width: 18, height: 18)
        }
        item.menu = buildMenu()
        statusItem = item
    }

    func updateAgentStatus(running: Bool) {
        isAgentRunning = running
        statusItem?.menu = buildMenu()
    }

    func tearDown() {
        if let item = statusItem {
            NSStatusBar.system.removeStatusItem(item)
            statusItem = nil
        }
    }

    private func buildMenu() -> NSMenu {
        let menu = NSMenu()

        let statusTitle = isAgentRunning ? "Agent: Running" : "Agent: Idle"
        let statusItem = NSMenuItem(title: statusTitle, action: nil, keyEquivalent: "")
        statusItem.isEnabled = false
        menu.addItem(statusItem)

        menu.addItem(.separator())

        let showItem = NSMenuItem(title: "Show Anvil", action: #selector(showApp), keyEquivalent: "")
        showItem.target = self
        menu.addItem(showItem)

        let newSession = NSMenuItem(title: "New Session", action: #selector(newSession), keyEquivalent: "n")
        newSession.target = self
        menu.addItem(newSession)

        menu.addItem(.separator())

        let quitItem = NSMenuItem(title: "Quit Anvil", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quitItem)

        return menu
    }

    @objc private func showApp() {
        NSApp.activate(ignoringOtherApps: true)
        NSApp.windows.first?.makeKeyAndOrderFront(nil)
    }

    @objc private func newSession() {
        NSApp.activate(ignoringOtherApps: true)
        NotificationCenter.default.post(name: .newSessionRequested, object: nil)
    }
}

extension Notification.Name {
    static let newSessionRequested = Notification.Name("newSessionRequested")
}
