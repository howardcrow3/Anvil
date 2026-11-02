import { useEffect, useState } from 'react'
import { describeProgress, formatGb } from '@/lib/formatDownload'
import type { ModelInfo } from '@/lib/types'
import { useApp } from '@/store/app'

type Pending = { kind: 'cancel' | 'delete' | 'discard'; model: ModelInfo }

export function ModelsSettings(): React.JSX.Element {
  const models = useApp((s) => s.models)
  const downloads = useApp((s) => s.downloads)
  const download = useApp((s) => s.downloadModel)
  const cancel = useApp((s) => s.cancelDownload)
  const remove = useApp((s) => s.deleteModel)
  const [pending, setPending] = useState<Pending | null>(null)
  const [now, setNow] = useState(() => Date.now())

  const local = models.filter((m) => m.provider === 'local')
  const running = Object.entries(downloads).filter(([, d]) => !d.error).map(([id]) => id)

  // Tick once a second so speed and ETA keep moving, but only while something is downloading.
  useEffect(() => {
    if (running.length === 0) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running.length])

  const row = (m: ModelInfo): React.JSX.Element => {
    const entry = downloads[m.id]
    const downloading = m.status === 'downloading' || (entry !== undefined && !entry.error)
    const failed = !downloading && entry?.error
    const partial = !downloading && m.status === 'downloadable' ? (m.partial_bytes ?? 0) : 0
    const resumable = Boolean(failed) || partial > 0
    const otherRunning = running.some((id) => id !== m.id)
    const shown = entry ? describeProgress(entry, now) : null
    return (
      <div className="mcp-row model-row" key={m.id}>
        <div className="mcp-main">
          <div className="grow">
            <div className="mcp-name">{m.name}</div>
            <div className="muted mcp-sub">
              {[m.size, m.download_gb ? `${m.download_gb} GB download` : null, m.min_ram_gb ? `needs ${m.min_ram_gb} GB RAM` : null].filter(Boolean).join(' · ')}
            </div>
          </div>
          {downloading && (
            <button className="btn ghost" aria-label={`Cancel download of ${m.name}`} onClick={() => setPending({ kind: 'cancel', model: m })}>
              Cancel
            </button>
          )}
          {resumable && (
            <>
              <button className="btn" aria-label={`${failed ? 'Retry' : 'Resume'} ${m.name}`} onClick={() => void download(m.id)} disabled={otherRunning}>
                {failed ? 'Retry' : 'Resume'}
              </button>
              <button className="btn ghost" aria-label={`Remove partial download of ${m.name}`} onClick={() => setPending({ kind: 'discard', model: m })}>
                Remove
              </button>
            </>
          )}
          {!downloading && !resumable && m.status === 'available' && (
            <button
              className="btn ghost"
              aria-label={`Delete ${m.name}`}
              disabled={m.active}
              title={m.active ? 'Switch to another model before deleting this one' : undefined}
              onClick={() => setPending({ kind: 'delete', model: m })}
            >
              Delete
            </button>
          )}
          {!downloading && !resumable && m.status === 'downloadable' && (
            <button
              className="btn primary"
              aria-label={`Download ${m.name}`}
              disabled={otherRunning}
              title={otherRunning ? 'Another download is running' : undefined}
              onClick={() => void download(m.id)}
            >
              Download
            </button>
          )}
        </div>
        {downloading && shown && (
          <>
            <div className="dl-bar" role="progressbar" aria-label={`Downloading ${m.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={shown.percent}>
              <div style={{ width: `${shown.percent}%` }} />
            </div>
            <div className="muted mcp-sub">{shown.label}</div>
          </>
        )}
        {failed && <div className="mcp-error">{entry.error}</div>}
        {resumable && <div className="muted mcp-sub">Partial download: {formatGb(partial || (entry?.done ?? 0))} on disk. Resuming continues where it stopped.</div>}
      </div>
    )
  }

  return (
    <div className="form">
      <p className="muted">Only models that fit this computer’s memory are listed. Downloads run on this computer and are kept in your Anvil folder.</p>
      <div className="mcp-list">
        {local.length === 0 && <div className="muted pad">No local models are available for this computer.</div>}
        {local.map(row)}
      </div>
      {pending && (
        <div className="confirm" role="alertdialog" aria-label={pending.kind === 'delete' ? 'Delete model' : pending.kind === 'cancel' ? 'Cancel download' : 'Remove partial download'}>
          <span>
            {pending.kind === 'cancel'
              ? `Cancel the download of “${pending.model.name}”? The partial download will be deleted.`
              : pending.kind === 'discard'
                ? `Remove the partial download of “${pending.model.name}”? It frees ${formatGb(pending.model.partial_bytes ?? downloads[pending.model.id]?.done ?? 0)}.`
                : `Delete “${pending.model.name}”? This frees about ${pending.model.download_gb ?? '?'} GB.`}
          </span>
          <button className="btn" onClick={() => setPending(null)}>
            {pending.kind === 'cancel' ? 'Keep downloading' : 'Keep'}
          </button>
          <button
            className="btn danger"
            onClick={() => {
              const { kind, model } = pending
              setPending(null)
              void (kind === 'delete' ? remove(model.id) : cancel(model.id))
            }}
          >
            {pending.kind === 'cancel' ? 'Cancel download' : pending.kind === 'discard' ? 'Remove' : 'Delete'}
          </button>
        </div>
      )}
    </div>
  )
}
