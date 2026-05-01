import SwiftUI

@Observable
final class GitStatusViewModel: @unchecked Sendable {
    var branch: String = ""
    var modifiedCount: Int = 0
    var addedCount: Int = 0
    var deletedCount: Int = 0
    var untrackedCount: Int = 0
    var lastCommit: String = ""
    var isGitRepo: Bool = false
    var isLoading: Bool = false

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
    }

    func refresh() async {
        guard ipcClient.isConnected else { return }
        isLoading = true
        defer { isLoading = false }

        do {
            let data = try await ipcClient.sendRequest(method: "git.status")
            if let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                isGitRepo = true
                branch = dict["branch"] as? String ?? ""
                let modified = dict["modified"] as? [String] ?? []
                let added = dict["added"] as? [String] ?? []
                let deleted = dict["deleted"] as? [String] ?? []
                let untracked = dict["untracked"] as? [String] ?? []
                modifiedCount = modified.count
                addedCount = added.count
                deletedCount = deleted.count
                untrackedCount = untracked.count
            }
        } catch {
            isGitRepo = false
        }

        do {
            let data = try await ipcClient.sendRequest(method: "git.log", params: ["count": 1])
            if let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]],
               let first = list.first {
                lastCommit = first["message"] as? String ?? ""
            }
        } catch {}
    }
}

struct GitStatusView: View {
    @State private var gitVM = GitStatusViewModel()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if gitVM.isLoading {
                ProgressView("Loading git status...")
                    .frame(maxWidth: .infinity)
            } else if !gitVM.isGitRepo {
                VStack(spacing: 8) {
                    Image(systemName: "questionmark.folder")
                        .font(.largeTitle)
                        .foregroundStyle(.secondary)
                    Text("Not a git repository")
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                branchSection
                changesSection
                lastCommitSection
                Spacer()
            }
        }
        .padding(12)
        .task { await gitVM.refresh() }
    }

    private var branchSection: some View {
        HStack {
            Image(systemName: "arrow.triangle.branch")
                .foregroundStyle(.blue)
            Text(gitVM.branch)
                .font(.headline)
            Spacer()
            Button {
                Task { await gitVM.refresh() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.plain)
            .help("Refresh")
        }
    }

    private var changesSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Changes")
                .font(.subheadline)
                .fontWeight(.medium)
                .foregroundStyle(.secondary)

            if totalChanges == 0 {
                Text("Working tree clean")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                if gitVM.modifiedCount > 0 {
                    changeRow(icon: "pencil", color: .orange, label: "Modified", count: gitVM.modifiedCount)
                }
                if gitVM.addedCount > 0 {
                    changeRow(icon: "plus", color: .green, label: "Added", count: gitVM.addedCount)
                }
                if gitVM.deletedCount > 0 {
                    changeRow(icon: "minus", color: .red, label: "Deleted", count: gitVM.deletedCount)
                }
                if gitVM.untrackedCount > 0 {
                    changeRow(icon: "questionmark", color: .secondary, label: "Untracked", count: gitVM.untrackedCount)
                }
            }
        }
    }

    private var lastCommitSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Last Commit")
                .font(.subheadline)
                .fontWeight(.medium)
                .foregroundStyle(.secondary)
            Text(gitVM.lastCommit)
                .font(.caption)
                .lineLimit(2)
        }
    }

    private func changeRow(icon: String, color: Color, label: String, count: Int) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.caption2)
                .foregroundStyle(color)
                .frame(width: 14)
            Text(label)
                .font(.caption)
            Spacer()
            Text("\(count)")
                .font(.caption)
                .fontWeight(.medium)
                .foregroundStyle(.secondary)
        }
    }

    private var totalChanges: Int {
        gitVM.modifiedCount + gitVM.addedCount + gitVM.deletedCount + gitVM.untrackedCount
    }
}
