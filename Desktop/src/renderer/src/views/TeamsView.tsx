import { useEffect, useState } from 'react'
import { Modal } from '@/components/Modal'
import { parseMembers, teamCreate, teamList, teamTaskCreate, teamTasks, type TeamTask } from '@/lib/work'
import { errText, useLoad } from './useLoad'

function NewTeam({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }): React.JSX.Element {
  const [name, setName] = useState('')
  const [members, setMembers] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault()
    if (!name.trim()) return setError('Enter a team name.')
    try {
      const { team_id } = await teamCreate(name.trim(), parseMembers(members))
      onCreated(team_id)
      onClose()
    } catch (err) {
      setError(errText(err))
    }
  }
  return (
    <Modal title="New team" onClose={onClose}>
      <form className="form" onSubmit={(e) => void submit(e)}>
        <label className="field"><span>Team name</span><input value={name} onChange={(e) => setName(e.target.value)} autoFocus /></label>
        <label className="field">
          <span>Members</span>
          <textarea rows={5} value={members} onChange={(e) => setMembers(e.target.value)} placeholder={'researcher: finds sources\nwriter: drafts the report'} />
          <small>One per line, as “name: role”.</small>
        </label>
        {error && <div className="msg-error" role="alert">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary">Create team</button>
        </div>
      </form>
    </Modal>
  )
}

export function TeamsView(): React.JSX.Element {
  const { data, error, reload } = useLoad(teamList)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [tasks, setTasks] = useState<TeamTask[]>([])
  const [title, setTitle] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  const teams = data ?? []
  const selected = teams.find((t) => t.id === selectedId) ?? teams[0] ?? null
  const selectedKey = selected?.id

  const loadTasks = async (id: string): Promise<void> => {
    try {
      setTasks(await teamTasks(id))
      setActionError(null)
    } catch (e) {
      setActionError(errText(e))
    }
  }
  useEffect(() => {
    if (selectedKey) void loadTasks(selectedKey)
    else setTasks([])
  }, [selectedKey])

  return (
    <section className="view" aria-label="Teams">
      <header className="view-head">
        <h1>Teams</h1>
        <span className="grow" />
        <button className="btn primary" onClick={() => setCreating(true)}>+ New team</button>
      </header>
      {(error || actionError) && <div className="msg-error" role="alert">{error ?? actionError}</div>}
      <div className="split">
        <nav className="list" aria-label="Team list">
          {teams.length === 0 && <div className="muted pad">No teams yet.</div>}
          {teams.map((t) => (
            <button key={t.id} className={`list-item ${selected?.id === t.id ? 'active' : ''}`} onClick={() => setSelectedId(t.id)}>
              <span>{t.name}</span>
              <span className="muted small">{(t.members ?? []).length} member(s)</span>
            </button>
          ))}
        </nav>
        <div className="detail">
          {!selected && <div className="muted pad">Create a team to share a task list between agents.</div>}
          {selected && (
            <>
              <h2>{selected.name}</h2>
              <div className="chips">
                {(selected.members ?? []).length === 0 && <span className="muted small">No members listed.</span>}
                {(selected.members ?? []).map((m, i) => (
                  <span key={i} className="pill">{m.name ?? 'agent'}{m.role ? ` · ${m.role}` : ''}</span>
                ))}
              </div>
              <form
                className="row"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!title.trim()) return
                  const t = title.trim()
                  setTitle('')
                  void teamTaskCreate(selected.id, t, '').then(() => loadTasks(selected.id)).catch((err) => setActionError(errText(err)))
                }}
              >
                <input className="grow" aria-label="New team task" placeholder="Add a shared task…" value={title} onChange={(e) => setTitle(e.target.value)} />
                <button className="btn" type="submit">Add</button>
              </form>
              <ul className="tasks">
                {tasks.length === 0 && <li className="muted">No shared tasks yet.</li>}
                {tasks.map((t) => (
                  <li key={t.id} className="task-row">
                    <span className="grow">{t.title}</span>
                    {t.assignee && <span className="muted small">@{t.assignee}</span>}
                    <span className="pill">{t.status}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
      {creating && <NewTeam onClose={() => setCreating(false)} onCreated={(id) => { setSelectedId(id); void reload() }} />}
    </section>
  )
}
