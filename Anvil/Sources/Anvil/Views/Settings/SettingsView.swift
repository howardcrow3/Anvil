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

            SkillsSettingsTab()
                .tabItem { Label("Skills", systemImage: "sparkles") }

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
                Text("Accept Edits").tag(PermissionMode.acceptEdits)
                Text("Trust").tag(PermissionMode.trust)
            }
            .pickerStyle(.segmented)

            switch vm.settings.permissionMode {
            case .ask:
                Text("All tool executions require your approval.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            case .acceptEdits:
                Text("Read-only tools auto-approved. Write/execute tools require approval.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            case .trust:
                Text("All tools auto-approved. Use with caution.")
                    .font(.caption)
                    .foregroundStyle(.orange)
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
            Section("About Hooks") {
                Text("Hooks run shell commands at lifecycle events (PreToolUse, PostToolUse, SessionStart, etc.).")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text("Configure hooks in ~/.anvil/hooks.json or .claude/hooks/ in your project.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Hook Events") {
                ForEach(["PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart", "SessionEnd", "Stop"], id: \.self) { event in
                    HStack {
                        Text(event)
                            .font(.system(.body, design: .monospaced))
                        Spacer()
                        Image(systemName: "circle")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}

struct SkillsSettingsTab: View {
    @State private var skills: [(name: String, description: String)] = []

    var body: some View {
        Form {
            Section("Built-in Commands") {
                ForEach([("/help", "Show help"), ("/clear", "Clear conversation"), ("/compact", "Compress history"), ("/plan", "Planning mode"), ("/resume", "Resume session"), ("/settings", "Show settings")], id: \.0) { cmd, desc in
                    HStack {
                        Text(cmd)
                            .font(.system(.body, design: .monospaced))
                        Spacer()
                        Text(desc)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section("Custom Skills") {
                if skills.isEmpty {
                    Text("No custom skills found. Add skills to .claude/skills/ in your project.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(skills, id: \.name) { skill in
                        HStack {
                            Text(skill.name)
                                .fontWeight(.medium)
                            Spacer()
                            Text(skill.description)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}
