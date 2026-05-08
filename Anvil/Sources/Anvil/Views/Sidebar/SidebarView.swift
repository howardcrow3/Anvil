import SwiftUI

enum SidebarTab: String, CaseIterable {
    case sessions = "Sessions"
    case files = "Files"
    case projects = "Projects"
    case skills = "Skills"
    case git = "Git"

    var icon: String {
        switch self {
        case .sessions: "bubble.left.and.bubble.right"
        case .files: "folder"
        case .projects: "square.grid.2x2"
        case .skills: "sparkles"
        case .git: "arrow.triangle.branch"
        }
    }
}

struct SidebarView: View {
    @Binding var selectedTab: SidebarTab

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
            case .projects:
                ProjectListSidebar()
            case .skills:
                SkillsBrowserView()
            case .git:
                GitStatusView()
            }
        }
    }
}

// MARK: - Compact Project List for Sidebar

struct ProjectListSidebar: View {
    @Environment(ProjectViewModel.self) private var projectVM
    @State private var showCreateProject = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Projects")
                    .font(.headline)
                Spacer()
                Button {
                    showCreateProject = true
                } label: {
                    Image(systemName: "plus.circle.fill")
                        .font(.system(size: 16))
                        .foregroundColor(.accentColor)
                }
                .buttonStyle(.plain)
                .help("New Project")
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.bar)

            Divider()

            if projectVM.projects.isEmpty {
                ContentUnavailableView {
                    Label("No Projects", systemImage: "folder.badge.plus")
                } description: {
                    Text("Create a project to organize tasks.")
                } actions: {
                    Button("New Project") {
                        showCreateProject = true
                    }
                    .buttonStyle(.borderedProminent)
                }
            } else {
                List(selection: Binding(
                    get: { projectVM.selectedProject },
                    set: {
                        projectVM.selectedProject = $0
                        projectVM.activeTaskId = nil
                    }
                )) {
                    ForEach(projectVM.projects) { project in
                        ProjectRow(project: project)
                            .tag(project)
                            .contextMenu {
                                Button(role: .destructive) {
                                    projectVM.deleteProject(project)
                                } label: {
                                    Label("Delete Project", systemImage: "trash")
                                }
                            }
                    }
                }
                .listStyle(.sidebar)
            }
        }
        .task { projectVM.loadProjects() }
        .sheet(isPresented: $showCreateProject) {
            CreateProjectSheet()
        }
    }
}
