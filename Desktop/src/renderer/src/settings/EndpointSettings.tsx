import { useState } from 'react'
import { useApp } from '@/store/app'
import { blankEndpoint, cleanEndpoint, readEndpoints, saveEndpoints, validateEndpoint, type Endpoint } from '@/lib/work'

export function EndpointSettings(): React.JSX.Element {
  const settings = useApp((s) => s.settings)
  const refreshSettings = useApp((s) => s.refreshSettings)
  const refreshModels = useApp((s) => s.refreshModels)
  const endpoints = readEndpoints(settings)
  const [draft, setDraft] = useState<{ index: number; ep: Endpoint } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const persist = async (next: Endpoint[]): Promise<boolean> => {
    setBusy(true)
    try {
      await saveEndpoints(next)
      await Promise.all([refreshSettings(), refreshModels()])
      setError(null)
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  const save = async (): Promise<void> => {
    if (!draft) return
    const problem = validateEndpoint(draft.ep, endpoints, draft.index)
    if (problem) return setError(problem)
    const next = [...endpoints]
    const clean = cleanEndpoint(draft.ep)
    if (draft.index < 0) next.push(clean)
    else next[draft.index] = clean
    if (await persist(next)) setDraft(null)
  }

  const set = (patch: Partial<Endpoint>): void => setDraft((d) => (d ? { ...d, ep: { ...d.ep, ...patch } } : d))

  return (
    <div className="form">
      <p className="muted">Connect any OpenAI-compatible server (LM Studio, vLLM, OpenRouter, …). Its model then appears in the model picker.</p>
      {endpoints.length === 0 && !draft && <div className="muted">No custom endpoints yet.</div>}
      {endpoints.map((ep, i) => (
        <div key={ep.name} className="kv-row endpoint-row">
          <div className="grow">
            <strong>{ep.name}</strong>
            <div className="small muted">{ep.base_url} · {ep.default_model}</div>
          </div>
          <button className="btn" disabled={busy} onClick={() => { setError(null); setDraft({ index: i, ep }) }}>Edit</button>
          <button className="btn ghost" disabled={busy} aria-label={`Remove ${ep.name}`} onClick={() => void persist(endpoints.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      {draft ? (
        <div className="form endpoint-form">
          <label className="field"><span>Name</span><input value={draft.ep.name} onChange={(e) => set({ name: e.target.value })} autoFocus /></label>
          <label className="field"><span>Base URL</span><input value={draft.ep.base_url} onChange={(e) => set({ base_url: e.target.value })} placeholder="http://localhost:1234/v1" /></label>
          <label className="field"><span>Model</span><input value={draft.ep.default_model} onChange={(e) => set({ default_model: e.target.value })} /></label>
          <label className="field"><span>API key (optional)</span><input type="password" value={draft.ep.api_key} onChange={(e) => set({ api_key: e.target.value })} autoComplete="off" /></label>
          <div className="modal-actions">
            <button className="btn" onClick={() => { setDraft(null); setError(null) }}>Cancel</button>
            <button className="btn primary" disabled={busy} onClick={() => void save()}>Save endpoint</button>
          </div>
        </div>
      ) : (
        <div><button className="btn" onClick={() => { setError(null); setDraft({ index: -1, ep: blankEndpoint() }) }}>+ Add endpoint</button></div>
      )}
      {error && <div className="msg-error" role="alert">{error}</div>}
    </div>
  )
}
