import SwiftUI

enum SidebarTab: String, CaseIterable {
    case sessions = "Sessions"
    case files = "Files"
    case tasks = "Tasks"
    case skills = "Skills"
    case git = "Git"

    var icon: String {
        switch self {
        case .sessions: "bubble.left.and.bubble.right"
        case .files: "folder"
        case .tasks: "checklist"
        case .skills: "sparkles"
        case .git: "arrow.triangle.branch"
        }
    }
}

struct SidebarView: View {
    @State private var selectedTab: SidebarTab = .sessions

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $selectedTab) {
                ForEach(SidebarTab.allCases, id: \.self) { tab in
                    Label(tab.rawValue, systemImage: tab.icon)
                        .tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .padding(8)

            Divider()

            switch selectedTab {
            case .sessions:
                SessionListView()
            case .files:
                FileExplorerView()
            case .tasks:
                TaskBoardView()
            case .skills:
                SkillsBrowserView()
            case .git:
                GitStatusView()
            }
        }
    }
}
