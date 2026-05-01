import SwiftUI

struct SettingsView: View {
    @Environment(SettingsViewModel.self) private var settingsVM

    var body: some View {
        @Bindable var vm = settingsVM

        TabView {
            GeneralSettingsTab()
                .tabItem { Label("General", systemImage: "gearshape") }

            ModelsSettingsTab()
                .tabItem { Label("Models", systemImage: "cpu") }

            APIKeySettingsView()
                .tabItem { Label("API Keys", systemImage: "key") }

            PermissionsSettingsTab()
                .tabItem { Label("Permissions", systemImage: "lock.shield") }

            MCPSettingsTab()
                .tabItem { Label("MCP", systemImage: "server.rack") }

            HooksSettingsTab()
                .tabItem { Label("Hooks", systemImage: "link") }

            EndpointSettingsView()
                .tabItem { Label("Endpoints", systemImage: "network") }
        }
        .frame(width: 550, height: 400)
        .onAppear { settingsVM.loadSettings() }
    }
}

struct GeneralSettingsTab: View {
    @Environment(SettingsViewModel.self) private var settingsVM

    var body: some View {
        @Bindable var vm = settingsVM

        Form {
            TextField("Data Directory", text: $vm.settings.dataDirectory)
            Picker("Theme", selection: $vm.settings.theme) {
                Text("System").tag("system")
                Text("Light").tag("light")
                Text("Dark").tag("dark")
            }
            TextField("Default Model", text: $vm.settings.defaultModel)

            Button("Save") { settingsVM.saveSettings() }
        }
        .formStyle(.grouped)
        .padding()
    }
}

struct ModelsSettingsTab: View {
    @Environment(SettingsViewModel.self) private var settingsVM

    var body: some View {
        @Bindable var vm = settingsVM

        Form {
            TextField("Default Model", text: $vm.settings.defaultModel)
            TextField("Ollama Port", value: $vm.settings.ollamaPort, format: .number)

            Button("Save") { settingsVM.saveSettings() }
        }
        .formStyle(.grouped)
        .padding()
    }
}

struct PermissionsSettingsTab: View {
    @Environment(SettingsViewModel.self) private var settingsVM

    var body: some View {
        @Bindable var vm = settingsVM

        Form {
            Picker("Permission Mode", selection: $vm.settings.permissionMode) {
                Text("Ask").tag(PermissionMode.ask)
                Text("Auto Allow").tag(PermissionMode.autoAllow)
                Text("Auto Deny").tag(PermissionMode.autoDeny)
            }

            Button("Save") { settingsVM.saveSettings() }
        }
        .formStyle(.grouped)
        .padding()
    }
}

struct MCPSettingsTab: View {
    @Environment(SettingsViewModel.self) private var settingsVM

    var body: some View {
        Form {
            if settingsVM.settings.mcpServers.isEmpty {
                Text("No MCP servers configured.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(settingsVM.settings.mcpServers) { server in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(server.name).fontWeight(.medium)
                            Text(server.command).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Toggle("", isOn: .constant(server.enabled))
                    }
                }
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}

struct HooksSettingsTab: View {
    var body: some View {
        Form {
            Text("Hook configuration coming soon.")
                .foregroundStyle(.secondary)
        }
        .formStyle(.grouped)
        .padding()
    }
}
