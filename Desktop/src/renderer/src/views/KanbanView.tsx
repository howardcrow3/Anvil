import { useEffect, useState } from 'react'
import { Modal } from '@/components/Modal'
import { PromptDialog } from '@/components/PromptDialog'
import { KANBAN_COLUMNS, groupKanban, kanbanAction, kanbanCreate, kanbanDispatcher, kanbanList, kanbanActions, type KanbanTask } from '@/lib/work'
import { rpc } from '@/lib/api'
import { errText, useLoad } from './useLoad'

const TITLES = { todo: 'To do', ready: 'Ready', running: 'Running', blocked: 'Blocked', done: 'Done' } as const

function NewTask({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }): React.JSX.Element {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [priority, setPriority] = useState(0)
  const [assignee, setAssignee] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault()
    if (!title.trim()) return setError('Enter a title.')
    try {
      await kanbanCreate(title.trim(), body, priority, assignee.trim())
      onCreated()
      onClose()
    } catch (err) {
      setError(errText(err))
    }
  }
  return (
    <Modal title="New task" onClose={onClose}>
      <form className="form" onSubmit={(e) => void submit(e)}>
        <label className="field">
          <span>Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
        </label>
        <label className="field">
          <span>Details</span>
          <textarea rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
        </label>
        <label className="field">
          <span>Priority</span>
          <input type="number" value={priority} onChange={(e) => setPriority(Number(e.target.value) || 0)} />
        </label>
        <label className="field">
          <span>Assignee (optional)</span>
          <input value={assignee} onChange={(e) => setAssignee(e.target.value)} />
        </label>
        {error && <div className="msg-error" role="alert">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary">Create task</button>
        </div>
      </form>
    </Modal>
  )
}

export function KanbanView(): React.JSX.Element {
  const { data, error, reload } = useLoad(kanbanList)
  const [creating, setCreating] = useState(false)

  // The dispatcher moves tasks in the background; refresh (debounced) when the runtime says one changed.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const off = rpc.on('kanban.event', () => {
      clearTimeout(timer)
      timer = setTimeout(() => void reload(), 250)
    })
    return () => {
      off()
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [actionError, setActionError] = useState<string | null>(null)

  const [blocking, setBlocking] = useState<KanbanTask | null>(null)

  const act = async (t: KanbanTask, action: string, extra: Record<string, unknown> = {}): Promise<void> => {
    try {
      await kanbanAction(t.id, action, action === 'complete' ? { summary: 'Completed from the board' } : extra)
      setActionError(null)
    } catch (e) {
      setActionError(errText(e))
    }
    await reload()
  }
  const toggleDispatcher = async (): Promise<void> => {
    try {
      await kanbanDispatcher(!data?.dispatcher?.running)
    } catch (e) {
      setActionError(errText(e))
    }
    await reload()
  }

  const cols = groupKanban(data?.tasks ?? [])
  return (
    <section className="view" aria-label="Kanban">
      <header className="view-head">
        <h1>Kanban</h1>
        <span className="grow" />
        <label className="check">
          <input type="checkbox" checked={!!data?.dispatcher?.running} onChange={() => void toggleDispatcher()} />
          <span>Auto-run ready tasks</span>
        </label>
        <button className="btn primary" onClick={() => setCreating(true)}>+ New task</button>
      </header>
      {(error || actionError) && <div className="msg-error" role="alert">{error ?? actionError}</div>}
      <div className="board">
        {KANBAN_COLUMNS.map((col) => (
          <div key={col} className="column" aria-label={TITLES[col]}>
            <h3>{TITLES[col]} <span className="muted">{cols[col].length}</span></h3>
            {cols[col].length === 0 && <div className="muted small">Nothing here.</div>}
            {cols[col].map((t) => (
              <article key={t.id} className="card">
                <div className="card-title">{t.title}</div>
                {t.body && <p className="small muted clamp">{t.body}</p>}
                <div className="small muted">
                  {t.assignee ? `@${t.assignee} · ` : ''}P{t.priority}
                </div>
                <div className="card-actions">
                  {kanbanActions(t.status).map((a) => (
                    <button key={a.action} className="btn ghost small" onClick={() => (a.action === 'block' ? setBlocking(t) : void act(t, a.action))}>{a.label}</button>
                  ))}
                </div>
              </article>
            ))}
          </div>
        ))}
      </div>
      {blocking && (
        <PromptDialog title="Block task" message={blocking.title} inputLabel="Why is it blocked?" confirmLabel="Block" onClose={() => setBlocking(null)} onConfirm={(reason) => void act(blocking, 'block', { reason })} />
      )}
      {creating && <NewTask onClose={() => setCreating(false)} onCreated={() => void reload()} />}
    </section>
  )
}
