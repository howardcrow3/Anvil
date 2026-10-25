import { useEffect } from 'react'
import { bridge } from '@/lib/bridge'
import { useApp } from '@/store/app'
import { ChatView } from './components/ChatView'
import { Sidebar } from './components/Sidebar'
import { KanbanView } from './views/KanbanView'
import { ProjectsView } from './views/ProjectsView'
import { SkillsView } from './views/SkillsView'
import { TeamsView } from './views/TeamsView'
import { SettingsDialog } from './settings/SettingsDialog'

function Banner(): React.JSX.Element | null {
  const runtime = useApp((s) => s.runtime)
  const connection = useApp((s) => s.connection)
  const notice = useApp((s) => s.notice)
  const setNotice = useApp((s) => s.setNotice)

  if (notice) {
    return (
      <div className="banner warn" role="alert">
        <span className="grow">{notice}</span>
        <button className="btn ghost" onClick={() => setNotice(null)}>
          Dismiss
        </button>
      </div>
    )
  }
  if (runtime.status === 'crashed' || runtime.status === 'stopped') {
    return (
      <div className="banner error" role="alert">
        <span className="grow">The agent runtime isn’t running{runtime.detail ? `: ${runtime.detail}` : '.'}</span>
        {bridge() && (
          <button className="btn" onClick={() => void bridge()?.restartRuntime()}>
            Restart
          </button>
        )}
      </div>
    )
  }
  if (runtime.status === 'starting' || connection === 'connecting') {
    return <div className="banner info">Starting the agent runtime…</div>
  }
  return null
}

export default function App(): React.JSX.Element {
  const init = useApp((s) => s.init)
  const settingsOpen = useApp((s) => s.settingsOpen)
  const view = useApp((s) => s.view)

  useEffect(() => {
    document.body.classList.add(`platform-${bridge()?.platform ?? 'web'}`)
    return init()
  }, [init])

  return (
    <div className="app">
      <Sidebar />
      <div className="main-col">
        <Banner />
        {view === 'chat' && <ChatView />}
        {view === 'projects' && <ProjectsView />}
        {view === 'kanban' && <KanbanView />}
        {view === 'teams' && <TeamsView />}
        {view === 'skills' && <SkillsView />}
      </div>
      {settingsOpen && <SettingsDialog />}
    </div>
  )
}
