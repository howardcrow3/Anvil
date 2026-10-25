import SwiftUI

// MARK: - Tab

struct MCPSettingsTab: View {
    @Environment(MCPViewModel.self) private var mcpVM

    @State private var editing: EditorTarget?
    @State private var showImport = false
    @State private var pendingDelete: MCPServerConfig?

    private struct EditorTarget: Identifiable {
        let server: MCPServerConfig
        let isNew: Bool
        var id: String { server.id }
    }

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Section {
                    if mcpVM.servers.isEmpty {
                        Text("No MCP servers configured.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(mcpVM.servers) { server in
                        MCPServerRow(
                            server: server,
                            onEdit: { editing = EditorTarget(server: server, isNew: false) },
                            onDelete: { pendingDelete = server }
                        )
                    }
                } header: {
                    Text("MCP Servers")
                } footer: {
                    Text("Tools from connected servers appear to the agent as mcp__server__tool and ask for approval before they run.")
                        .font(.caption)
                }
            }
            .formStyle(.grouped)

            Divider()

            HStack {
                Button {
                    editing = EditorTarget(server: MCPServerConfig(), isNew: true)
                } label: {
                    Label("Add Server", systemImage: "plus")
                }
                Button {
                    showImport = true
                } label: {
                    Label("Import JSON…", systemImage: "square.and.arrow.down")
                }
                Button {
                    Task { await mcpVM.reload() }
                } label: {
                    Label("Reconnect All", systemImage: "arrow.clockwise")
                }
                .disabled(mcpVM.isWorking)

                if mcpVM.isWorking {
                    ProgressView().controlSize(.small)
                }
                Spacer()
                if let message = mcpVM.statusMessage {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            .padding(10)
        }
        .onAppear { Task { await mcpVM.load() } }
        .sheet(item: $editing) { target in
            MCPServerEditorSheet(server: target.server, isNew: target.isNew)
        }
        .sheet(isPresented: $showImport) {
            MCPImportSheet()
        }
        .alert(
            "Remove this server?",
            isPresented: Binding(
                get: { pendingDelete != nil },
                set: { if !$0 { pendingDelete = nil } }
            ),
            presenting: pendingDelete
        ) { server in
            Button("Remove", role: .destructive) {
                Task { await mcpVM.delete(server) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { server in
            Text("“\(server.name)” will be disconnected and removed from your MCP configuration.")
        }
    }
}

// MARK: - Row

private struct MCPServerRow: View {
    @Environment(MCPViewModel.self) private var mcpVM

    let server: MCPServerConfig
    let onEdit: () -> Void
    let onDelete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Circle()
                    .fill(color)
                    .frame(width: 8, height: 8)
                    .help(server.state.label)
                VStack(alignment: .leading, spacing: 2) {
                    Text(server.name).fontWeight(.medium)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Spacer()
                Text(statusText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Button(action: onEdit) { Image(systemName: "pencil") }
                    .buttonStyle(.borderless)
                    .help("Edit")
                Button(action: onDelete) { Image(systemName: "trash") }
                    .buttonStyle(.borderless)
                    .help("Remove")
                Toggle(
                    "",
                    isOn: Binding(
                        get: { server.enabled },
                        set: { value in Task { await mcpVM.setEnabled(server, value) } }
                    )
                )
                .labelsHidden()
                .disabled(mcpVM.isWorking)
            }

            if server.state == .failed, !server.error.isEmpty {
                Text(server.error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }

            if !server.tools.isEmpty {
                DisclosureGroup("\(server.tools.count) tool\(server.tools.count == 1 ? "" : "s")") {
                    ForEach(server.tools) { tool in
                        VStack(alignment: .leading, spacing: 1) {
                            Text(tool.name).font(.caption.monospaced())
                            if !tool.description.isEmpty {
                                Text(tool.description)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                        }
                        .padding(.vertical, 1)
                    }
                }
                .font(.caption)
            }
        }
        .padding(.vertical, 2)
    }

    private var color: Color {
        switch server.state {
        case .connected: .green
        case .failed: .red
        case .disabled: .gray
        case .stopped: .orange
        }
    }

    private var statusText: String {
        server.state == .connected ? "\(server.transport.rawValue) · connected" : server.state.label
    }

    private var subtitle: String {
        switch server.transport {
        case .stdio: ([server.command] + server.args).joined(separator: " ")
        case .http, .sse: server.url
        }
    }
}

// MARK: - Editor

struct MCPServerEditorSheet: View {
    @Environment(MCPViewModel.self) private var mcpVM
    @Environment(\.dismiss) private var dismiss

    private let isNew: Bool
    @State private var draft: MCPServerConfig
    @State private var argsText: String
    @State private var showSecrets = false
    @State private var isTesting = false
    @State private var testResult: MCPTestResult?
    @State private var isSaving = false
    @State private var saveError: String?

    init(server: MCPServerConfig, isNew: Bool) {
        self.isNew = isNew
        _draft = State(initialValue: server)
        _argsText = State(initialValue: server.args.joined(separator: "\n"))
    }

    private var otherNames: [String] {
        mcpVM.servers.filter { $0.id != draft.id }.map(\.name)
    }

    private var current: MCPServerConfig {
        var server = draft
        server.name = draft.name.trimmingCharacters(in: .whitespaces)
        server.args = MCPServerConfig.parseArgs(argsText)
        return server
    }

    private var problem: String? {
        current.validationError(otherNames: otherNames)
    }

    var body: some View {
        VStack(spacing: 0) {
            Text(isNew ? "Add MCP Server" : "Edit MCP Server")
                .font(.headline)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding([.top, .horizontal], 16)

            Form {
                Section {
                    TextField("Name", text: $draft.name, prompt: Text("e.g. github"))
                    Picker("Type", selection: $draft.transport) {
                        ForEach(MCPTransport.allCases) { transport in
                            Text(transport.label).tag(transport)
                        }
                    }
                    Toggle("Enabled", isOn: $draft.enabled)
                }

                if draft.transport == .stdio {
                    Section("Command") {
                        TextField("Command", text: $draft.command, prompt: Text("e.g. npx"))
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Arguments (one per line)").font(.caption).foregroundStyle(.secondary)
                            TextEditor(text: $argsText)
                                .font(.body.monospaced())
                                .frame(height: 64)
                                .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.secondary.opacity(0.3)))
                        }
                        TextField("Working directory (optional)", text: $draft.cwd)
                    }
                    MCPKeyValueEditor(
                        title: "Environment variables",
                        keyPlaceholder: "NAME",
                        rows: $draft.env,
                        showSecrets: showSecrets
                    )
                } else {
                    Section("Server") {
                        TextField("URL", text: $draft.url, prompt: Text("https://example.com/mcp"))
                    }
                    MCPKeyValueEditor(
                        title: "Headers",
                        keyPlaceholder: "Authorization",
                        rows: $draft.headers,
                        showSecrets: showSecrets
                    )
                }

                Section {
                    Toggle("Show secret values", isOn: $showSecrets)
                    TextField("Tool call timeout (seconds)", value: $draft.timeout, format: .number)
                } footer: {
                    Text("Values may reference environment variables, e.g. Bearer ${GITHUB_TOKEN}. The config file is readable only by you.")
                        .font(.caption)
                }

                Section("Connection test") {
                    HStack {
                        Button {
                            Task { await runTest() }
                        } label: {
                            Label("Test Connection", systemImage: "bolt.horizontal")
                        }
                        .disabled(problem != nil || isTesting)
                        if isTesting { ProgressView().controlSize(.small) }
                    }
                    if let result = testResult { testResultView(result) }
                }
            }
            .formStyle(.grouped)

            Divider()

            HStack {
                if let saveError {
                    Text(saveError).font(.caption).foregroundStyle(.red).lineLimit(2)
                } else if let problem, !draft.name.isEmpty || !isNew {
                    Text(problem).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if isSaving { ProgressView().controlSize(.small) }
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button(isNew ? "Add" : "Save") { Task { await save() } }
                    .keyboardShortcut(.defaultAction)
                    .disabled(problem != nil || isSaving)
            }
            .padding(12)
        }
        .frame(width: 540, height: 640)
    }

    @ViewBuilder
    private func testResultView(_ result: MCPTestResult) -> some View {
        if result.ok {
            Label("Connected — \(result.tools.count) tool\(result.tools.count == 1 ? "" : "s") available", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
            if !result.tools.isEmpty {
                Text(result.tools.map(\.name).joined(separator: ", "))
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        } else {
            Label("Couldn't connect", systemImage: "xmark.octagon.fill")
                .foregroundStyle(.red)
            Text(result.error)
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }

    private func runTest() async {
        isTesting = true
        testResult = nil
        let result = await mcpVM.test(current)
        testResult = result
        isTesting = false
    }

    private func save() async {
        isSaving = true
        saveError = nil
        let error = await mcpVM.upsert(current)
        isSaving = false
        if let error {
            saveError = error
        } else {
            dismiss()
        }
    }
}

private struct MCPKeyValueEditor: View {
    let title: String
    let keyPlaceholder: String
    @Binding var rows: [MCPKeyValue]
    let showSecrets: Bool

    var body: some View {
        Section(title) {
            ForEach($rows) { $row in
                HStack {
                    TextField("Name", text: $row.key, prompt: Text(keyPlaceholder))
                        .frame(maxWidth: 170)
                    if showSecrets {
                        TextField("Value", text: $row.value)
                    } else {
                        SecureField("Value", text: $row.value)
                    }
                    Button {
                        rows.removeAll { $0.id == row.id }
                    } label: {
                        Image(systemName: "minus.circle")
                    }
                    .buttonStyle(.borderless)
                }
            }
            Button {
                rows.append(MCPKeyValue(key: "", value: ""))
            } label: {
                Label("Add", systemImage: "plus")
            }
            .buttonStyle(.borderless)
        }
    }
}

// MARK: - Import

struct MCPImportSheet: View {
    @Environment(MCPViewModel.self) private var mcpVM
    @Environment(\.dismiss) private var dismiss

    @State private var text = ""
    @State private var errorMessage: String?
    @State private var isImporting = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Import MCP Servers").font(.headline)
            Text("Paste a config from Claude Desktop or Claude Code ({\"mcpServers\": …}). Servers with the same name as an existing one are replaced.")
                .font(.caption)
                .foregroundStyle(.secondary)

            TextEditor(text: $text)
                .font(.body.monospaced())
                .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.secondary.opacity(0.3)))

            HStack {
                if let errorMessage {
                    Text(errorMessage).font(.caption).foregroundStyle(.red).lineLimit(2)
                }
                Spacer()
                if isImporting { ProgressView().controlSize(.small) }
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Import") { Task { await importServers() } }
                    .keyboardShortcut(.defaultAction)
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isImporting)
            }
        }
        .padding(16)
        .frame(width: 520, height: 400)
    }

    private func importServers() async {
        errorMessage = nil
        let servers: [MCPServerConfig]
        do {
            servers = try MCPServerConfig.parseImport(text)
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        for server in servers {
            if let problem = server.validationError(otherNames: []) {
                errorMessage = "\(server.name): \(problem)"
                return
            }
        }
        isImporting = true
        let error = await mcpVM.upsert(contentsOf: servers)
        isImporting = false
        if let error {
            errorMessage = error
        } else {
            dismiss()
        }
    }
}
