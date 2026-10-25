import { useState } from 'react'
import { useApp } from '@/store/app'

export function ApiKeySettings(): React.JSX.Element {
  const saved = String(useApp((s) => s.settings.api_key ?? ''))
  const setSetting = useApp((s) => s.setSetting)
  const [value, setValue] = useState('')
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  const save = async (key: string): Promise<void> => {
    try {
      await setSetting('api_key', key)
      setValue('')
      setMessage({ ok: true, text: key ? 'API key saved.' : 'API key removed.' })
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) })
    }
  }

  return (
    <div className="form">
      <p className="muted">Your Anthropic API key lets Anvil use Claude. It’s stored in your Anvil configuration folder on this computer.</p>
      <div className="status-line">{saved ? <>Saved key ending in <code>{saved.slice(-4)}</code></> : 'No key saved.'}</div>
      <label className="field">
        <span>{saved ? 'Replace key' : 'API key'}</span>
        <input type="password" value={value} placeholder="sk-ant-…" autoComplete="off" spellCheck={false} onChange={(e) => setValue(e.target.value)} />
      </label>
      <div className="row">
        <button className="btn primary" disabled={!value.trim()} onClick={() => void save(value.trim())}>
          Save key
        </button>
        {saved && (
          <button className="btn" onClick={() => void save('')}>
            Remove key
          </button>
        )}
        {message && <span className={message.ok ? 'ok' : 'bad'}>{message.text}</span>}
      </div>
    </div>
  )
}
