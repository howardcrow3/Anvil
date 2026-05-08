import SwiftUI
import UniformTypeIdentifiers

struct SkillInfo: Identifiable, Hashable, Codable {
    let id: String
    let name: String
    let description: String
    let source: String
    let version: String
    var enabled: Bool
    let type: String

    enum CodingKeys: String, CodingKey {
        case id, name, description, source, version, enabled, type
    }

    init(id: String, name: String, description: String, source: String, version: String, enabled: Bool = true, type: String = "skill") {
        self.id = id
        self.name = name
        self.description = description
        self.source = source
        self.version = version
        self.enabled = enabled
        self.type = type
    }
}

struct SkillsBrowserView: View {
    @State private var skills: [SkillInfo] = []
    @State private var searchText = ""
    @State private var selectedSkill: SkillInfo?
    @State private var isLoading = false
    @State private var showCreateSheet = false
    @State private var showImportPicker = false

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    var filteredSkills: [SkillInfo] {
        let list = searchText.isEmpty ? skills : skills.filter {
            $0.name.localizedCaseInsensitiveContains(searchText) ||
            $0.description.localizedCaseInsensitiveContains(searchText)
        }
        return list
    }

    var groupedSkills: [(String, [SkillInfo])] {
        let order = ["skill", "command"]
        let grouped = Dictionary(grouping: filteredSkills, by: \.type)
        return order.compactMap { type in
            guard let items = grouped[type], !items.isEmpty else { return nil }
            let label = type == "skill" ? "Skills" : "Commands"
            return (label, items)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Toolbar
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                    .font(.system(size: 12))
                TextField("Search skills...", text: $searchText)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))

                Spacer()

                Button {
                    showImportPicker = true
                } label: {
                    Image(systemName: "square.and.arrow.down")
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .help("Import skill from file")

                Button {
                    showCreateSheet = true
                } label: {
                    Image(systemName: "plus.circle.fill")
                        .font(.system(size: 16))
                        .foregroundColor(.accentColor)
                }
                .buttonStyle(.plain)
                .help("Create new skill")
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.bar)

            Divider()

            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if filteredSkills.isEmpty {
                ContentUnavailableView {
                    Label("No Skills", systemImage: "sparkles")
                } description: {
                    Text("Skills are created automatically after complex tasks, or you can add them manually.")
                } actions: {
                    HStack(spacing: 12) {
                        Button("Import File") {
                            showImportPicker = true
                        }
                        .buttonStyle(.bordered)

                        Button("Create Skill") {
                            showCreateSheet = true
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
            } else {
                List(selection: $selectedSkill) {
                    ForEach(groupedSkills, id: \.0) { label, items in
                        Section {
                            ForEach(items) { skill in
                                SkillRow(skill: skill, onToggle: { enabled in
                                    toggleSkill(skill, enabled: enabled)
                                }, onDelete: skill.source == "user" && skill.type == "skill" ? {
                                    deleteSkill(skill)
                                } : nil)
                                .tag(skill)
                            }
                        } header: {
                            HStack {
                                Text(label)
                                Spacer()
                                Text("\(items.count)")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                .listStyle(.sidebar)
            }
        }
        .task { await loadSkills() }
        .fileImporter(
            isPresented: $showImportPicker,
            allowedContentTypes: [.plainText, .data],
            allowsMultipleSelection: true
        ) { result in
            switch result {
            case .success(let urls):
                Task { await importSkills(from: urls) }
            case .failure:
                break
            }
        }
        .sheet(isPresented: $showCreateSheet) {
            CreateSkillSheet(ipcClient: ipcClient) {
                Task { await loadSkills() }
            }
        }
    }

    func loadSkills() async {
        isLoading = true
        defer { isLoading = false }

        guard ipcClient.isConnected else { return }
        do {
            let data = try await ipcClient.sendRequest(method: "skills.list")
            guard let array = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return }

            skills = array.compactMap { dict in
                guard let id = dict["id"] as? String,
                      let name = dict["name"] as? String else { return nil }
                return SkillInfo(
                    id: id,
                    name: name,
                    description: dict["description"] as? String ?? "",
                    source: dict["source"] as? String ?? "user",
                    version: dict["version"] as? String ?? "",
                    enabled: dict["enabled"] as? Bool ?? true,
                    type: dict["type"] as? String ?? "skill"
                )
            }
        } catch {
            // Skills list unavailable
        }
    }

    func toggleSkill(_ skill: SkillInfo, enabled: Bool) {
        guard ipcClient.isConnected else { return }
        if let idx = skills.firstIndex(where: { $0.id == skill.id }) {
            skills[idx].enabled = enabled
        }
        Task {
            let _ = try? await ipcClient.sendRequest(method: "skills.toggle", params: [
                "id": skill.id,
                "enabled": enabled
            ])
        }
    }

    func importSkills(from urls: [URL]) async {
        guard ipcClient.isConnected else { return }
        for url in urls {
            guard url.startAccessingSecurityScopedResource() else { continue }
            defer { url.stopAccessingSecurityScopedResource() }
            guard let content = try? String(contentsOf: url, encoding: .utf8) else { continue }
            let name = url.deletingPathExtension().lastPathComponent
                .lowercased()
                .replacingOccurrences(of: " ", with: "-")
            let _ = try? await ipcClient.sendRequest(method: "skills.import", params: [
                "name": name,
                "content": content
            ])
        }
        await loadSkills()
    }

    func deleteSkill(_ skill: SkillInfo) {
        guard ipcClient.isConnected else { return }
        skills.removeAll { $0.id == skill.id }
        Task {
            let _ = try? await ipcClient.sendRequest(method: "skills.delete", params: [
                "id": skill.id
            ])
        }
    }
}

// MARK: - Skill Row

struct SkillRow: View {
    let skill: SkillInfo
    let onToggle: (Bool) -> Void
    let onDelete: (() -> Void)?

    var body: some View {
        HStack(spacing: 10) {
            // Icon
            Image(systemName: skill.type == "command" ? "terminal" : "sparkles")
                .font(.system(size: 14))
                .foregroundStyle(skill.enabled ? iconColor : .secondary)
                .frame(width: 20, alignment: .center)

            // Name + description
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(skill.name)
                        .fontWeight(.medium)
                        .font(.system(size: 13))
                        .foregroundStyle(skill.enabled ? .primary : .secondary)

                    if !skill.version.isEmpty {
                        Text("v\(skill.version)")
                            .font(.system(size: 10))
                            .foregroundStyle(.tertiary)
                    }
                }

                if !skill.description.isEmpty {
                    Text(skill.description)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 8)

            // Source badge
            Text(skill.source)
                .font(.system(size: 10, weight: .medium))
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(badgeColor.opacity(0.12))
                .foregroundStyle(badgeColor)
                .clipShape(Capsule())

            // Toggle
            Toggle("", isOn: Binding(
                get: { skill.enabled },
                set: { onToggle($0) }
            ))
            .toggleStyle(.switch)
            .controlSize(.mini)
            .labelsHidden()
        }
        .padding(.vertical, 2)
        .contextMenu {
            Toggle(skill.enabled ? "Enabled" : "Disabled", isOn: Binding(
                get: { skill.enabled },
                set: { onToggle($0) }
            ))

            if let onDelete {
                Divider()
                Button(role: .destructive) {
                    onDelete()
                } label: {
                    Label("Delete Skill", systemImage: "trash")
                }
            }
        }
    }

    var iconColor: Color {
        switch skill.source {
        case "builtin": .blue
        case "project": .purple
        case "user": .green
        default: .secondary
        }
    }

    var badgeColor: Color {
        switch skill.source {
        case "builtin": .blue
        case "project": .purple
        case "user": .green
        default: .secondary
        }
    }
}

// MARK: - Create Skill Sheet

struct CreateSkillSheet: View {
    let ipcClient: IPCClient
    let onCreated: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var summary = ""
    @State private var isCreating = false
    @State private var errorMessage: String?

    var isValid: Bool {
        !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text("New Skill")
                    .font(.headline)
                Spacer()
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                        .font(.system(size: 18))
                }
                .buttonStyle(.plain)
            }
            .padding()

            Divider()

            // Form
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Name")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    TextField("e.g. deploy-to-staging", text: $name)
                        .textFieldStyle(.roundedBorder)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("What does this skill do?")
                        .font(.subheadline)
                        .fontWeight(.medium)
                    TextEditor(text: $summary)
                        .font(.system(size: 13))
                        .frame(minHeight: 100)
                        .padding(4)
                        .background(Color(nsColor: .textBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .overlay(
                            RoundedRectangle(cornerRadius: 6)
                                .stroke(Color(nsColor: .separatorColor))
                        )
                    Text("Describe the procedure. The agent will format it into a reusable SKILL.md file.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let errorMessage {
                    Text(errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
            .padding()

            Divider()

            // Actions
            HStack {
                Spacer()
                Button("Cancel") {
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)

                Button("Create Skill") {
                    Task { await createSkill() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!isValid || isCreating)
                .keyboardShortcut(.defaultAction)
            }
            .padding()
        }
        .frame(width: 440)
    }

    func createSkill() async {
        isCreating = true
        errorMessage = nil
        defer { isCreating = false }

        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: " ", with: "-")

        do {
            let data = try await ipcClient.sendRequest(method: "skills.create", params: [
                "name": trimmedName,
                "summary": summary.trimmingCharacters(in: .whitespacesAndNewlines),
                "tool_calls": [] as [String]
            ])
            if let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               result["error"] as? String == nil {
                onCreated()
                dismiss()
            } else {
                errorMessage = "Failed to create skill. Try a different name."
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
