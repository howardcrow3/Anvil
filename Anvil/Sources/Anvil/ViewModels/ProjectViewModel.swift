import Foundation

@Observable
final class ProjectViewModel: @unchecked Sendable {
    var projects: [Project] = []
    var selectedProject: Project?
    var activeTaskId: UUID?
    var errorMessage: String?

    private let ipcClient: IPCClient

    init(ipcClient: IPCClient = IPCClient()) {
        self.ipcClient = ipcClient
        setupTaskStatusCallback()
    }

    private func setupTaskStatusCallback() {
        ipcClient.onTaskStatusUpdate = { @Sendable [weak self] params in
            guard let taskId = (params["task_id"] as? String).flatMap({ UUID(uuidString: $0) }),
                  let projectId = (params["project_id"] as? String).flatMap({ UUID(uuidString: $0) }),
                  let statusStr = params["status"] as? String,
                  let status = ProjectTaskStatus(rawValue: statusStr) else { return }
            Task { @MainActor [weak self] in
                guard let self,
                      let project = self.projects.first(where: { $0.id == projectId }) else { return }
                self.updateTaskStatus(taskId, in: project, status: status, fromNotification: true)
            }
        }
    }

    func loadProjects() {
        do {
            projects = try ProjectService.loadProjects()
        } catch {
            projects = []
        }

        guard ipcClient.isConnected else { return }
        let client = ipcClient
        Task { @MainActor [weak self] in
            guard let self else { return }
            if let data = try? await client.sendRequest(method: "project.list"),
               let list = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
                var remote: [Project] = []
                let fmt = ISO8601DateFormatter()
                for item in list {
                    let id = (item["id"] as? String).flatMap { UUID(uuidString: $0) } ?? UUID()
                    let name = item["name"] as? String ?? "Untitled"
                    let folder = item["folder_path"] as? String ?? ""
                    let repo = item["github_repo"] as? String ?? ""
                    let created = (item["created_at"] as? String).flatMap { fmt.date(from: $0) } ?? Date()
                    let updated = (item["updated_at"] as? String).flatMap { fmt.date(from: $0) } ?? Date()

                    var tasks: [ProjectTask] = []
                    if let taskList = item["tasks"] as? [[String: Any]] {
                        tasks = taskList.compactMap { t in
                            guard let tid = (t["id"] as? String).flatMap({ UUID(uuidString: $0) }),
                                  let title = t["title"] as? String else { return nil }
                            let statusStr = t["status"] as? String ?? "not_started"
                            let status = ProjectTaskStatus(rawValue: statusStr) ?? .notStarted
                            let sid = (t["session_id"] as? String).flatMap { UUID(uuidString: $0) }
                            let tc = (t["created_at"] as? String).flatMap { fmt.date(from: $0) } ?? Date()
                            let tu = (t["updated_at"] as? String).flatMap { fmt.date(from: $0) } ?? Date()
                            return ProjectTask(id: tid, title: title, taskDescription: t["description"] as? String ?? "", status: status, sessionId: sid, createdAt: tc, updatedAt: tu)
                        }
                    }

                    remote.append(Project(id: id, name: name, folderPath: folder, githubRepo: repo, tasks: tasks, createdAt: created, updatedAt: updated))
                }
                if !remote.isEmpty {
                    // Merge: prefer remote data but preserve local session links
                    // if the remote has nil session_id but local has one
                    for i in remote.indices {
                        if let localProject = self.projects.first(where: { $0.id == remote[i].id }) {
                            for j in remote[i].tasks.indices {
                                if remote[i].tasks[j].sessionId == nil,
                                   let localTask = localProject.tasks.first(where: { $0.id == remote[i].tasks[j].id }),
                                   localTask.sessionId != nil {
                                    remote[i].tasks[j].sessionId = localTask.sessionId
                                }
                            }
                        }
                    }
                    self.projects = remote
                }
            }
        }
    }

    @discardableResult
    func createProject(name: String, folderPath: String, githubRepo: String = "") -> Project {
        let project = Project(name: name, folderPath: folderPath, githubRepo: githubRepo)
        projects.append(project)
        try? ProjectService.saveProject(project)

        if ipcClient.isConnected {
            let client = ipcClient
            Task { @MainActor in
                let _ = try? await client.sendRequest(method: "project.create", params: [
                    "id": project.id.uuidString,
                    "name": name,
                    "folder_path": folderPath,
                    "github_repo": githubRepo,
                ])
            }
        }
        return project
    }

    func deleteProject(_ project: Project) {
        projects.removeAll { $0.id == project.id }
        try? ProjectService.deleteProject(project)
        if selectedProject?.id == project.id {
            selectedProject = nil
        }

        if ipcClient.isConnected {
            let client = ipcClient
            let pid = project.id.uuidString
            Task { @MainActor in
                let _ = try? await client.sendRequest(method: "project.delete", params: ["id": pid])
            }
        }
    }

    func addTask(to project: Project, title: String, description: String = "") {
        guard let idx = projects.firstIndex(where: { $0.id == project.id }) else { return }
        let task = ProjectTask(title: title, taskDescription: description)
        projects[idx].tasks.append(task)
        projects[idx].updatedAt = Date()
        try? ProjectService.saveProject(projects[idx])

        if ipcClient.isConnected {
            let client = ipcClient
            let pid = project.id.uuidString
            Task { @MainActor in
                let _ = try? await client.sendRequest(method: "project.task.create", params: [
                    "project_id": pid,
                    "id": task.id.uuidString,
                    "title": title,
                    "description": description,
                ])
            }
        }

        if selectedProject?.id == project.id {
            selectedProject = projects[idx]
        }
    }

    func updateTaskStatus(_ taskId: UUID, in project: Project, status: ProjectTaskStatus, fromNotification: Bool = false) {
        guard let pIdx = projects.firstIndex(where: { $0.id == project.id }),
              let tIdx = projects[pIdx].tasks.firstIndex(where: { $0.id == taskId }) else { return }

        // Skip if already at this status
        guard projects[pIdx].tasks[tIdx].status != status else { return }

        projects[pIdx].tasks[tIdx].status = status
        projects[pIdx].tasks[tIdx].updatedAt = Date()
        projects[pIdx].updatedAt = Date()
        try? ProjectService.saveProject(projects[pIdx])

        // Only send IPC if this was a local change (not from a notification)
        if !fromNotification, ipcClient.isConnected {
            let client = ipcClient
            let pid = project.id.uuidString
            let tid = taskId.uuidString
            let statusStr = status.rawValue
            Task { @MainActor in
                let _ = try? await client.sendRequest(method: "project.task.update", params: [
                    "project_id": pid,
                    "task_id": tid,
                    "status": statusStr,
                ])
            }
        }

        if selectedProject?.id == project.id {
            selectedProject = projects[pIdx]
        }
    }

    func deleteTask(_ taskId: UUID, in project: Project) {
        guard let pIdx = projects.firstIndex(where: { $0.id == project.id }) else { return }
        projects[pIdx].tasks.removeAll { $0.id == taskId }
        projects[pIdx].updatedAt = Date()
        try? ProjectService.saveProject(projects[pIdx])

        if ipcClient.isConnected {
            let client = ipcClient
            let pid = project.id.uuidString
            let tid = taskId.uuidString
            Task { @MainActor in
                let _ = try? await client.sendRequest(method: "project.task.delete", params: [
                    "project_id": pid,
                    "task_id": tid,
                ])
            }
        }

        if selectedProject?.id == project.id {
            selectedProject = projects[pIdx]
        }
    }

    func linkSession(_ sessionId: UUID, toTask taskId: UUID, in project: Project) {
        guard let pIdx = projects.firstIndex(where: { $0.id == project.id }),
              let tIdx = projects[pIdx].tasks.firstIndex(where: { $0.id == taskId }) else { return }
        projects[pIdx].tasks[tIdx].sessionId = sessionId
        projects[pIdx].tasks[tIdx].updatedAt = Date()
        try? ProjectService.saveProject(projects[pIdx])

        if selectedProject?.id == project.id {
            selectedProject = projects[pIdx]
        }
    }

    @MainActor
    func openTask(_ task: ProjectTask, in project: Project, sessionVM: SessionViewModel, chatVM: ChatViewModel) {
        // Always use the freshest version of the task from our projects array
        let freshTask: ProjectTask
        if let pIdx = projects.firstIndex(where: { $0.id == project.id }),
           let tIdx = projects[pIdx].tasks.firstIndex(where: { $0.id == task.id }) {
            freshTask = projects[pIdx].tasks[tIdx]
        } else {
            freshTask = task
        }

        if let sessionId = freshTask.sessionId {
            // Task already has a linked session — use it directly
            let session = sessionVM.sessions.first(where: { $0.id == sessionId })
                ?? Session(id: sessionId, name: freshTask.title, projectPath: project.folderPath)
            sessionVM.resumeSession(session, chatVM: chatVM)
        } else {
            // No session yet — create one and link it
            let session = sessionVM.createSession(
                name: freshTask.title,
                projectPath: project.folderPath
            )
            linkSession(session.id, toTask: freshTask.id, in: project)
            sessionVM.resumeSession(session, chatVM: chatVM)
        }
        activeTaskId = freshTask.id

        // Auto-transition to in_progress when opening a not_started task
        if task.status == .notStarted {
            updateTaskStatus(task.id, in: project, status: .inProgress)
        }
    }

    func backToBoard() {
        activeTaskId = nil
    }
}
