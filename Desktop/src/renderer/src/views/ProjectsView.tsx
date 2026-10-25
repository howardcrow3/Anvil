import { useState } from 'react'
import { Modal } from '@/components/Modal'
import { PromptDialog } from '@/components/PromptDialog'
import {
  PROJECT_STATUSES,
  PROJECT_STATUS_LABEL,
  projectCreate,
  projectDelete,
  projectList,
  projectProgress,
  projectTaskCreate,
  projectTaskDelete,
  projectTaskUpdate,
  type Project
} from '@/lib/work'
import { errText, useLoad } from './useLoad'

function NewProject({ onClose, onCreated }: { onClose: () => void; onCreated: (p: Project) => void }): React.JSX.Element {
  const [name, setName] = useState('')
  const [folder, setFolder] = useState('')
  const [repo, setRepo] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault()
    if (!name.trim()) return setError('Enter a project name.')
    try {
      onCreated(await projectCreate(name.trim(), folder.trim(), repo.trim()))
      onClose()
    } catch (err) {
      setError(errText(err))
    }
  }
  return (
    <Modal title="New project" onClose={onClose}>
      <form className="form" onSubmit={(e) => void submit(e)}>
        <label className="field"><span>Name</span><input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></label>
        <label className="field"><span>Folder path (optional)</span><input value={folder} onChange={(e) => setFolder(e.target.value)} /></label>
        <label className="field"><span>GitHub repo (optional)</span><input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="owner/name" /></label>
        {error && <div className="msg-error" role="alert">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary">Create project</button>
        </div>
      </form>
    </Modal>
  )
}

export function ProjectsView(): React.JSX.Element {
  const { data, error, reload } = useLoad(projectList)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [deleting, setDeleting] = useState<Project | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const projects = data ?? []
  const selected = projects.find((p) => p.id === selectedId) ?? projects[0] ?? null

  const run = async (work: () => Promise<unknown>): Promise<void> => {
    try {
      await work()
      setActionError(null)
    } catch (e) {
      setActionError(errText(e))
    }
    await reload()
  }

  return (
    <section className="view" aria-label="Projects">
      <header className="view-head">
        <h1>Projects</h1>
        <span className="grow" />
        <button className="btn primary" onClick={() => setCreating(true)}>+ New project</button>
      </header>
      {(error || actionError) && <div className="msg-error" role="alert">{error ?? actionError}</div>}
      <div className="split">
        <nav className="list" aria-label="Project list">
          {projects.length === 0 && <div className="muted pad">No projects yet.</div>}
          {projects.map((p) => {
            const pr = projectProgress(p)
            return (
              <button key={p.id} className={`list-item ${selected?.id === p.id ? 'active' : ''}`} onClick={() => setSelectedId(p.id)}>
                <span>{p.name}</span>
                <span className="muted small">{pr.done}/{pr.total} done</span>
              </button>
            )
          })}
        </nav>
        <div className="detail">
          {!selected && <div className="muted pad">Create a project to track tasks.</div>}
          {selected && (
            <>
              <div className="detail-head">
                <h2>{selected.name}</h2>
                <span className="grow" />
                <button
                  className="btn ghost"
                  onClick={() => setDeleting(selected)}
                >
                  Delete project
                </button>
              </div>
              <div className="muted small">{[selected.folder_path, selected.github_repo].filter(Boolean).join(' · ') || 'No folder or repo linked'}</div>
              <div className="progress" aria-label={`${projectProgress(selected).percent}% complete`}>
                <div style={{ width: `${projectProgress(selected).percent}%` }} />
              </div>
              <form
                className="row"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!title.trim()) return
                  const t = title.trim()
                  setTitle('')
                  void run(() => projectTaskCreate(selected.id, t, ''))
                }}
              >
                <input className="grow" aria-label="New task title" placeholder="Add a task…" value={title} onChange={(e) => setTitle(e.target.value)} />
                <button className="btn" type="submit">Add</button>
              </form>
              <ul className="tasks">
                {selected.tasks.length === 0 && <li className="muted">No tasks yet.</li>}
                {selected.tasks.map((t) => (
                  <li key={t.id} className="task-row">
                    <span className="grow">{t.title}</span>
                    <select aria-label={`Status of ${t.title}`} value={t.status} onChange={(e) => void run(() => projectTaskUpdate(selected.id, t.id, e.target.value))}>
                      {PROJECT_STATUSES.map((s) => (
                        <option key={s} value={s}>{PROJECT_STATUS_LABEL[s]}</option>
                      ))}
                    </select>
                    <button className="btn ghost" aria-label={`Delete ${t.title}`} onClick={() => void run(() => projectTaskDelete(selected.id, t.id))}>✕</button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
      {deleting && (
        <PromptDialog title="Delete project?" message={`“${deleting.name}” and its ${deleting.tasks.length} task(s) will be removed.`} confirmLabel="Delete" danger onClose={() => setDeleting(null)} onConfirm={() => void run(() => projectDelete(deleting.id))} />
      )}
      {creating && <NewProject onClose={() => setCreating(false)} onCreated={(p) => { setSelectedId(p.id); void reload() }} />}
    </section>
  )
}
