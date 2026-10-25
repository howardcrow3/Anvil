import { useApp, type Theme } from '@/store/app'

export function GeneralSettings(): React.JSX.Element {
  const theme = useApp((s) => s.theme)
  const setTheme = useApp((s) => s.setTheme)
  const models = useApp((s) => s.models)
  const settings = useApp((s) => s.settings)
  const setSetting = useApp((s) => s.setSetting)
  const setNotice = useApp((s) => s.setNotice)
  const usable = models.filter((m) => m.status === 'available' || m.status === 'configured')

  return (
    <div className="form">
      <label className="field">
        <span>Theme</span>
        <select value={theme} onChange={(e) => setTheme(e.target.value as Theme)}>
          <option value="system">Match system</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </label>
      <label className="field">
        <span>Default model</span>
        <select
          value={String(settings.default_model ?? '')}
          onChange={(e) => void setSetting('default_model', e.target.value).catch((err: Error) => setNotice(err.message))}
        >
          {usable.length === 0 && <option value="">No models available yet</option>}
          {usable.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
        <small>Used when Anvil starts. Switch the current chat’s model from the chat header.</small>
      </label>
    </div>
  )
}
