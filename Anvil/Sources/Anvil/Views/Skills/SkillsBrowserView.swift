import SwiftUI

struct SkillInfo: Identifiable, Hashable, Codable {
    let id: String
    let name: String
    let description: String
    let source: String
    let version: String
}

struct SkillsBrowserView: View {
    @State private var skills: [SkillInfo] = []
    @State private var searchText = ""
    @State private var selectedSkill: SkillInfo?
    @State private var isLoading = false

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    var filteredSkills: [SkillInfo] {
        if searchText.isEmpty { return skills }
        return skills.filter {
            $0.name.localizedCaseInsensitiveContains(searchText) ||
            $0.description.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Search skills...", text: $searchText)
                    .textFieldStyle(.plain)
            }
            .padding(8)
            .background(.bar)

            Divider()

            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if filteredSkills.isEmpty {
                ContentUnavailableView(
                    "No Skills",
                    systemImage: "sparkles",
                    description: Text("No skills found. Skills are created automatically after complex tasks.")
                )
            } else {
                List(selection: $selectedSkill) {
                    let grouped = Dictionary(grouping: filteredSkills, by: \.source)

                    ForEach(["builtin", "project", "user"], id: \.self) { source in
                        if let items = grouped[source] {
                            Section(source.capitalized) {
                                ForEach(items) { skill in
                                    SkillRow(skill: skill)
                                        .tag(skill)
                                }
                            }
                        }
                    }
                }
            }
        }
        .task { await loadSkills() }
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
                    version: dict["version"] as? String ?? "1.0"
                )
            }
        } catch {
            // Skills list unavailable
        }
    }
}

struct SkillRow: View {
    let skill: SkillInfo

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(skill.name)
                    .fontWeight(.medium)
                if !skill.description.isEmpty {
                    Text(skill.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            Spacer()
            Text(skill.source)
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(badgeColor.opacity(0.15))
                .foregroundStyle(badgeColor)
                .clipShape(Capsule())
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
