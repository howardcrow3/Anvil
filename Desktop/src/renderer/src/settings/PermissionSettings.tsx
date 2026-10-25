import { useApp } from '@/store/app'

const MODES = [
  { id: 'ask', label: 'Ask every time', help: 'Anvil asks before running tools that change files or run commands.' },
  { id: 'accept_edits', label: 'Accept edits', help: 'File edits are allowed automatically; commands still ask.' },
  { id: 'trust', label: 'Trust', help: 'Anvil runs tools without asking. Only use this in projects you trust.' }
] as const

export function PermissionSettings(): React.JSX.Element {
  const mode = String(useApp((s) => s.settings.permission_mode ?? 'ask'))
  const setSetting = useApp((s) => s.setSetting)
  const setNotice = useApp((s) => s.setNotice)
  return (
    <div className="form">
      <p className="muted">Controls when Anvil needs your approval to use a tool. Applies immediately.</p>
      <div className="radios" role="radiogroup" aria-label="Permission mode">
        {MODES.map((m) => (
          <label key={m.id} className={`radio ${mode === m.id ? 'on' : ''}`}>
            <input type="radio" name="perm" checked={mode === m.id} onChange={() => void setSetting('permission_mode', m.id).catch((e: Error) => setNotice(e.message))} />
            <span>
              <strong>{m.label}</strong>
              <small>{m.help}</small>
            </span>
          </label>
        ))}
      </div>
    </div>
  )
}
