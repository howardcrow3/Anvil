import { call } from './api'

/* ── Custom endpoints (stored in the `endpoints` setting) ─────────────── */

export interface Endpoint {
  name: string
  base_url: string
  api_key: string
  default_model: string
}

export const blankEndpoint = (): Endpoint => ({ name: '', base_url: '', api_key: '', default_model: '' })

export function readEndpoints(settings: Record<string, unknown>): Endpoint[] {
  const raw = settings.endpoints
  if (!Array.isArray(raw)) return []
  return raw
    .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
    .map((e) => ({
      name: String(e.name ?? ''),
      base_url: String(e.base_url ?? ''),
      api_key: String(e.api_key ?? ''),
      default_model: String(e.default_model ?? '')
    }))
}

/** Returns an error message, or null when the endpoint can be saved. `index` is the row being edited (-1 for new). */
export function validateEndpoint(ep: Endpoint, all: Endpoint[], index: number): string | null {
  const name = ep.name.trim()
  if (!name) return 'Give the endpoint a name.'
  if (all.some((o, i) => i !== index && o.name.trim().toLowerCase() === name.toLowerCase())) return `There is already an endpoint named “${name}”.`
  try {
    const u = new URL(ep.base_url.trim())
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return 'The base URL must start with http:// or https://.'
  } catch {
    return 'Enter a valid base URL, for example http://localhost:1234/v1.'
  }
  if (!ep.default_model.trim()) return 'Enter the model name this endpoint should use.'
  return null
}

export const cleanEndpoint = (ep: Endpoint): Endpoint => ({
  name: ep.name.trim(),
  base_url: ep.base_url.trim().replace(/\/+$/, ''),
  api_key: ep.api_key.trim(),
  default_model: ep.default_model.trim()
})

export const saveEndpoints = (endpoints: Endpoint[]): Promise<unknown> => call('settings.set', { key: 'endpoints', value: endpoints })

/* ── Kanban ───────────────────────────────────────────────────────────── */

export const KANBAN_COLUMNS = ['todo', 'ready', 'running', 'blocked', 'done'] as const
export type KanbanStatus = (typeof KANBAN_COLUMNS)[number] | 'archived'

export interface KanbanTask {
  id: string
  title: string
  body?: string | null
  assignee?: string | null
  status: KanbanStatus
  priority: number
  result?: string | null
}

export interface KanbanBoard {
  tasks: KanbanTask[]
  stats?: Record<string, number>
  dispatcher?: { running: boolean; active?: unknown }
}

export function groupKanban(tasks: KanbanTask[]): Record<(typeof KANBAN_COLUMNS)[number], KanbanTask[]> {
  const out = { todo: [], ready: [], running: [], blocked: [], done: [] } as Record<(typeof KANBAN_COLUMNS)[number], KanbanTask[]>
  for (const t of tasks) {
    if (t.status in out) out[t.status as keyof typeof out].push(t)
  }
  for (const col of KANBAN_COLUMNS) out[col].sort((a, b) => b.priority - a.priority || a.title.localeCompare(b.title))
  return out
}

/** Actions the board offers for a task in each column. */
export function kanbanActions(status: KanbanStatus): { action: 'complete' | 'block' | 'unblock' | 'archive' | 'stop'; label: string }[] {
  switch (status) {
    case 'todo':
    case 'ready':
      return [{ action: 'complete', label: 'Complete' }, { action: 'block', label: 'Block' }, { action: 'archive', label: 'Archive' }]
    case 'running':
      return [{ action: 'stop', label: 'Stop' }, { action: 'complete', label: 'Complete' }]
    case 'blocked':
      return [{ action: 'unblock', label: 'Unblock' }, { action: 'archive', label: 'Archive' }]
    case 'done':
      return [{ action: 'archive', label: 'Archive' }]
    default:
      return []
  }
}

export const kanbanList = (): Promise<KanbanBoard> => call<KanbanBoard>('kanban.list')
export const kanbanCreate = (title: string, body: string, priority: number, assignee?: string): Promise<unknown> =>
  call('kanban.create', { title, body, priority, assignee: assignee || undefined })
export const kanbanAction = (id: string, action: string, extra: Record<string, unknown> = {}): Promise<unknown> => call('kanban.action', { id, action, ...extra })
export const kanbanDispatcher = (running: boolean): Promise<unknown> => call('kanban.dispatcher', { enabled: running })

/* ── Projects ─────────────────────────────────────────────────────────── */

export const PROJECT_STATUSES = ['not_started', 'in_progress', 'completed'] as const
export type ProjectStatus = (typeof PROJECT_STATUSES)[number]
export const PROJECT_STATUS_LABEL: Record<string, string> = { not_started: 'Not started', in_progress: 'In progress', completed: 'Completed' }

export interface ProjectTask {
  id: string
  title: string
  description?: string
  status: string
}
export interface Project {
  id: string
  name: string
  folder_path?: string
  github_repo?: string
  tasks: ProjectTask[]
}

export const projectProgress = (p: Project): { done: number; total: number; percent: number } => {
  const total = p.tasks.length
  const done = p.tasks.filter((t) => t.status === 'completed').length
  return { done, total, percent: total ? Math.round((done / total) * 100) : 0 }
}

export const projectList = (): Promise<Project[]> => call<Project[]>('project.list')
export const projectCreate = (name: string, folder_path: string, github_repo: string): Promise<Project> => call('project.create', { name, folder_path, github_repo })
export const projectDelete = (id: string): Promise<unknown> => call('project.delete', { id })
export const projectTaskCreate = (project_id: string, title: string, description: string): Promise<ProjectTask> => call('project.task.create', { project_id, title, description })
export const projectTaskUpdate = (project_id: string, task_id: string, status: string): Promise<unknown> => call('project.task.update', { project_id, task_id, status })
export const projectTaskDelete = (project_id: string, task_id: string): Promise<unknown> => call('project.task.delete', { project_id, task_id })

/* ── Skills ───────────────────────────────────────────────────────────── */

export interface SkillItem {
  id: string
  name: string
  description: string
  source: string
  version: string
  enabled: boolean
  type: 'skill' | 'command'
}

export function filterSkills(items: SkillItem[], query: string): SkillItem[] {
  const q = query.trim().toLowerCase()
  const list = q ? items.filter((s) => `${s.name} ${s.description}`.toLowerCase().includes(q)) : items
  return [...list].sort((a, b) => Number(a.type === 'command') - Number(b.type === 'command') || a.name.localeCompare(b.name))
}

/** Normalize an imported skill name the way the runtime does, so the UI can show what will be saved. */
export const skillSlug = (name: string): string => name.trim().toLowerCase().replace(/\s+/g, '-')

export const skillsList = (): Promise<SkillItem[]> => call<SkillItem[]>('skills.list')
export const skillsToggle = (id: string, enabled: boolean): Promise<unknown> => call('skills.toggle', { id, enabled })
export const skillsDelete = (id: string): Promise<unknown> => call('skills.delete', { id })
export const skillsImport = (name: string, content: string): Promise<unknown> => call('skills.import', { name, content })

/* ── Teams ────────────────────────────────────────────────────────────── */

export interface TeamSummary {
  id: string
  name: string
  status?: string
  created_at?: string
  members?: { name?: string; role?: string }[]
}
export interface TeamTask {
  id: string
  title: string
  description?: string
  status: string
  assignee?: string | null
  depends_on?: string[]
}

export const teamList = (): Promise<TeamSummary[]> => call<TeamSummary[]>('team.list')
export const teamCreate = (name: string, members: { name: string; role: string }[]): Promise<{ team_id: string }> => call('team.create', { name, members })
export const teamTasks = (team_id: string): Promise<TeamTask[]> => call<TeamTask[]>('team.task.list', { team_id })
export const teamTaskCreate = (team_id: string, title: string, description: string): Promise<unknown> => call('team.task.create', { team_id, title, description })

/** Parse "name: role" lines into team members. Blank lines are ignored; a bare name gets the role "member". */
export function parseMembers(text: string): { name: string; role: string }[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const i = l.indexOf(':')
      return i < 0 ? { name: l, role: 'member' } : { name: l.slice(0, i).trim(), role: l.slice(i + 1).trim() || 'member' }
    })
    .filter((m) => m.name)
}
