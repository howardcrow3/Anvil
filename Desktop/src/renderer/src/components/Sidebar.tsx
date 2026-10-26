import { useApp, type View } from '@/store/app'

const NAV: { id: View; label: string }[] = [
  { id: 'chat', label: 'Chat' },
  { id: 'projects', label: 'Projects' },
  { id: 'kanban', label: 'Kanban' },
  { id: 'teams', label: 'Teams' },
  { id: 'skills', label: 'Skills' }
]

export function Sidebar(): React.JSX.Element {
  const sessions = useApp((s) => s.sessions)
  const current = useApp((s) => s.currentSessionId)
  const newChat = useApp((s) => s.newChat)
  const open = useApp((s) => s.openSession)
  const openSettings = useApp((s) => s.openSettings)
  const connection = useApp((s) => s.connection)
  const busy = useApp((s) => s.chat.streaming)
  const view = useApp((s) => s.view)
  const setView = useApp((s) => s.setView)

  return (
    <aside className="sidebar">
      <div className="sidebar-top drag">
        <button className="btn primary block nodrag" onClick={newChat} disabled={busy}>
          + New chat
        </button>
      </div>
      <nav className="mainnav" aria-label="Sections">
        {NAV.map((n) => (
          <button key={n.id} className={`navitem ${view === n.id ? 'active' : ''}`} aria-current={view === n.id ? 'page' : undefined} onClick={() => setView(n.id)}>
            {n.label}
          </button>
        ))}
      </nav>
      <nav className="sessions" aria-label="Sessions">
        {sessions.length === 0 && <div className="muted pad">No sessions yet.</div>}
        {sessions.map((s) => (
          <button key={s.id} className={`session ${s.id === current ? 'active' : ''}`} onClick={() => void open(s.id)} disabled={busy} title={s.name || 'Untitled'}>
            {s.name || 'Untitled'}
          </button>
        ))}
      </nav>
      <div className="sidebar-foot">
        <span className={`dot ${connection}`} title={`Runtime: ${connection}`} />
        <span className="muted grow">{connection === 'open' ? 'Connected' : connection === 'connecting' ? 'Connecting…' : 'Disconnected'}</span>
        <button className="btn ghost" onClick={() => openSettings()}>
          Settings
        </button>
      </div>
    </aside>
  )
}
