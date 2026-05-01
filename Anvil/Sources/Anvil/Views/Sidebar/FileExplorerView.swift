import SwiftUI

struct FileNode: Identifiable {
    let id = UUID()
    let name: String
    let path: String
    let isDirectory: Bool
    var children: [FileNode]?

    var icon: String {
        if isDirectory {
            return "folder.fill"
        }
        switch (name as NSString).pathExtension.lowercased() {
        case "swift": return "swift"
        case "py": return "doc.text"
        case "json": return "curlybraces"
        case "md": return "doc.richtext"
        case "yml", "yaml": return "doc.badge.gearshape"
        default: return "doc"
        }
    }
}

struct FileExplorerView: View {
    @State private var rootNodes: [FileNode] = []
    @State private var projectPath = ""

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                TextField("Project path...", text: $projectPath)
                    .textFieldStyle(.roundedBorder)
                    .font(.caption)
                Button {
                    loadDirectory(projectPath)
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("Refresh")
            }
            .padding(8)

            if rootNodes.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "folder.badge.questionmark")
                        .font(.title2)
                        .foregroundStyle(.tertiary)
                    Text("No project loaded")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(rootNodes, children: \.children) { node in
                    Label(node.name, systemImage: node.icon)
                        .font(.caption)
                }
                .listStyle(.sidebar)
            }
        }
    }

    private func loadDirectory(_ path: String) {
        guard !path.isEmpty else { return }
        let expandedPath = NSString(string: path).expandingTildeInPath

        guard let contents = try? FileManager.default.contentsOfDirectory(atPath: expandedPath) else { return }

        rootNodes = contents
            .filter { !$0.hasPrefix(".") }
            .sorted()
            .map { name in
                let fullPath = "\(expandedPath)/\(name)"
                var isDir: ObjCBool = false
                FileManager.default.fileExists(atPath: fullPath, isDirectory: &isDir)
                return FileNode(
                    name: name,
                    path: fullPath,
                    isDirectory: isDir.boolValue,
                    children: isDir.boolValue ? loadChildren(fullPath) : nil
                )
            }
    }

    private func loadChildren(_ path: String) -> [FileNode]? {
        guard let contents = try? FileManager.default.contentsOfDirectory(atPath: path) else { return nil }
        let nodes = contents
            .filter { !$0.hasPrefix(".") }
            .sorted()
            .map { name in
                let fullPath = "\(path)/\(name)"
                var isDir: ObjCBool = false
                FileManager.default.fileExists(atPath: fullPath, isDirectory: &isDir)
                return FileNode(
                    name: name,
                    path: fullPath,
                    isDirectory: isDir.boolValue,
                    children: isDir.boolValue ? [] : nil
                )
            }
        return nodes.isEmpty ? nil : nodes
    }
}
