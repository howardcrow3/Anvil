import { useCallback, useEffect, useState } from 'react'
import { blankServer as blank, listServers, reloadServers, saveServers } from '@/lib/mcp'
import type { McpServer } from '@/lib/types'
import { McpImportDialog } from './McpImportDialog'
import { McpServerEditor } from './McpServerEditor'

const COLORS = { connected: 'ok', failed: 'bad', disabled: 'off', stopped: 'warn' } as const
const LABELS = { connected: 'Connected', failed: 'Failed', disabled: 'Disabled', stopped: 'Not started' } as const

/** What to show for a server: the user's enabled switch wins over the (possibly stale) runtime status. */
function displayState(s: McpServer, busy: boolean): { state: McpServer['status']; label: string } {
  if (!s.enabled) return { state: 'disabled', label: LABELS.disabled }
  if (s.status === 'disabled' || (s.status === 'stopped' && busy)) return { state: 'stopped', label: 'Connecting…' }
  return { state: s.status, label: s.status === 'connected' ? `${s.transport} · connected` : LABELS[s.status] }
}

export function McpSettings(): React.JSX.Element {
  const [servers, setServers] = useState<McpServer[] | null>(null)
  const [editing, setEditing] = useState<{ server: McpServer; isNew: boolean } | null>(null)
  const [importing, setImporting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<McpServer | null>(null)

  const run = useCallback(async (work: () => Promise<McpServer[]>, success: string): Promise<string | null> => {
    setBusy(true)
    try {
      setServers(await work())
      setStatus(success)
      return null
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e)
      setStatus(text)
      return text
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    void run(listServers, '')
  }, [run])

  const current = servers ?? []
  const upsert = (server: McpServer): Promise<string | null> => {
    const exists = current.some((s) => s.id === server.id)
    const next = exists ? current.map((s) => (s.id === server.id ? server : s)) : [...current, server]
    // Show the edit immediately; reconnecting can take a few seconds. The runtime's answer replaces it,
    // and a failed save restores the real list.
    setServers(next)
    return run(() => saveServers(next), `Saved “${server.name}”`).then((failure) => {
      if (failure) void listServers().then(setServers, () => {})
      return failure
    })
  }
  const importAll = (imported: McpServer[]): Promise<string | null> => {
    const next = [...current]
    for (const server of imported) {
      const i = next.findIndex((s) => s.name === server.name)
      if (i >= 0) next[i] = { ...server, id: next[i].id }
      else next.push(server)
    }
    return run(() => saveServers(next), `Imported ${imported.length} server${imported.length === 1 ? '' : 's'}`)
  }

  return (
    <div className="mcp">
      <p className="muted">Tools from connected MCP servers appear to the agent as <code>mcp__server__tool</code> and ask for approval before they run.</p>

      <div className="mcp-list">
        {servers === null && <div className="muted pad">Loading…</div>}
        {servers?.length === 0 && <div className="muted pad">No MCP servers configured.</div>}
        {current.map((s) => {
          const shown = displayState(s, busy)
          return (
          <div className="mcp-row" key={s.id}>
            <div className="mcp-main">
              <span className={`dot ${COLORS[shown.state]}`} title={shown.label} />
              <div className="grow">
                <div className="mcp-name">{s.name}</div>
                <div className="muted mcp-sub">{s.transport === 'stdio' ? [s.command, ...s.args].join(' ') : s.url}</div>
              </div>
              <span className="muted">{shown.label}</span>
              <button className="btn ghost" onClick={() => setEditing({ server: s, isNew: false })} aria-label={`Edit ${s.name}`}>
                Edit
              </button>
              <button className="btn ghost" onClick={() => setConfirmDelete(s)} aria-label={`Remove ${s.name}`}>
                Remove
              </button>
              <label className="switch" title={s.enabled ? 'Disable' : 'Enable'}>
                <input type="checkbox" checked={s.enabled} disabled={busy} onChange={(e) => void upsert({ ...s, enabled: e.target.checked })} aria-label={`Enable ${s.name}`} />
                <span />
              </label>
            </div>
            {s.enabled && s.status === 'failed' && s.error && <div className="mcp-error">{s.error}</div>}
            {s.tools.length > 0 && (
              <details className="mcp-tools">
                <summary>
                  {s.tools.length} tool{s.tools.length === 1 ? '' : 's'}
                </summary>
                {s.tools.map((t) => (
                  <div key={t.name} className="mcp-tool">
                    <code>{t.name}</code>
                    {t.description && <small>{t.description}</small>}
                  </div>
                ))}
              </details>
            )}
          </div>
          )
        })}
      </div>

      <div className="row mcp-actions">
        <button className="btn" onClick={() => setEditing({ server: blank(), isNew: true })}>
          + Add server
        </button>
        <button className="btn" onClick={() => setImporting(true)}>
          Import JSON…
        </button>
        <button className="btn" disabled={busy} onClick={() => void run(reloadServers, 'Reconnected MCP servers')}>
          Reconnect all
        </button>
        {busy && <span className="spinner" role="status" aria-label="Working" />}
        <span className="muted grow right">{status}</span>
      </div>

      {editing && (
        <McpServerEditor
          initial={editing.server}
          isNew={editing.isNew}
          otherNames={current.filter((s) => s.id !== editing.server.id).map((s) => s.name)}
          onSave={upsert}
          onClose={() => setEditing(null)}
        />
      )}
      {importing && <McpImportDialog onImport={importAll} onClose={() => setImporting(false)} />}
      {confirmDelete && (
        <div className="confirm" role="alertdialog" aria-label="Remove server">
          <span>Remove “{confirmDelete.name}”? It will be disconnected and removed from your MCP configuration.</span>
          <button className="btn" onClick={() => setConfirmDelete(null)}>
            Cancel
          </button>
          <button
            className="btn danger"
            onClick={() => {
              const target = confirmDelete
              setConfirmDelete(null)
              void run(() => saveServers(current.filter((s) => s.id !== target.id)), `Removed “${target.name}”`)
            }}
          >
            Remove
          </button>
        </div>
      )}
    </div>
  )
}
