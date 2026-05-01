import Foundation

@Observable
final class TeamViewModel {
    var team: AgentTeam?
    var isRunning = false

    func createTeam(name: String) {
        team = AgentTeam(name: name)
    }

    func addTeammate(name: String, model: String) {
        let teammate = Teammate(name: name, model: model)
        team?.teammates.append(teammate)
    }

    func removeTeammate(_ teammate: Teammate) {
        team?.teammates.removeAll { $0.id == teammate.id }
    }

    func addTask(title: String, assignee: String? = nil) {
        let task = AgentTask(title: title, assignee: assignee)
        team?.tasks.append(task)
    }

    func updateTaskStatus(_ taskId: UUID, status: TaskStatus) {
        guard let index = team?.tasks.firstIndex(where: { $0.id == taskId }) else { return }
        team?.tasks[index].status = status
    }

    func startTeam() {
        team?.status = .running
        isRunning = true
    }

    func stopTeam() {
        team?.status = .idle
        isRunning = false
    }
}
