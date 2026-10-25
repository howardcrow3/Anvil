import { useState } from 'react'
import { Modal } from '@/components/Modal'
import { kv, parseArgs, testServer, validate, type TestResult } from '@/lib/mcp'
import type { KeyValue, McpServer, McpTransport } from '@/lib/types'

interface Props {
  initial: McpServer
  isNew: boolean
  otherNames: string[]
  onSave: (server: McpServer) => Promise<string | null>
  onClose: () => void
}

function KeyValueEditor({ title, placeholder, rows, onChange, reveal }: { title: string; placeholder: string; rows: KeyValue[]; onChange: (rows: KeyValue[]) => void; reveal: boolean }): React.JSX.Element {
  return (
    <fieldset className="kv">
      <legend>{title}</legend>
      {rows.map((row) => (
        <div className="kv-row" key={row.id}>
          <input aria-label={`${title} name`} placeholder={placeholder} value={row.key} onChange={(e) => onChange(rows.map((r) => (r.id === row.id ? { ...r, key: e.target.value } : r)))} />
          <input aria-label={`${title} value`} type={reveal ? 'text' : 'password'} placeholder="value" autoComplete="off" value={row.value} onChange={(e) => onChange(rows.map((r) => (r.id === row.id ? { ...r, value: e.target.value } : r)))} />
          <button className="btn ghost" aria-label="Remove row" onClick={() => onChange(rows.filter((r) => r.id !== row.id))}>
            ✕
          </button>
        </div>
      ))}
      <button className="btn ghost" onClick={() => onChange([...rows, kv()])}>
        + Add
      </button>
    </fieldset>
  )
}

export function McpServerEditor({ initial, isNew, otherNames, onSave, onClose }: Props): React.JSX.Element {
  const [draft, setDraft] = useState<McpServer>(initial)
  const [argsText, setArgsText] = useState(initial.args.join('\n'))
  const [reveal, setReveal] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<TestResult | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const current: McpServer = { ...draft, name: draft.name.trim(), args: parseArgs(argsText) }
  const problem = validate(current, otherNames)
  const patch = (p: Partial<McpServer>): void => setDraft((d) => ({ ...d, ...p }))
  const remote = draft.transport !== 'stdio'

  const test = async (): Promise<void> => {
    setTesting(true)
    setResult(null)
    try {
      setResult(await testServer(current))
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : String(e) })
    } finally {
      setTesting(false)
    }
  }

  const save = async (): Promise<void> => {
    setSaving(true)
    setError(null)
    const failure = await onSave(current)
    setSaving(false)
    if (failure) setError(failure)
    else onClose()
  }

  return (
    <Modal title={isNew ? 'Add MCP server' : 'Edit MCP server'} onClose={onClose} width={560}>
      <div className="form editor">
        <label className="field">
          <span>Name</span>
          <input value={draft.name} placeholder="e.g. github" onChange={(e) => patch({ name: e.target.value })} />
        </label>
        <label className="field">
          <span>Type</span>
          <select value={draft.transport} onChange={(e) => patch({ transport: e.target.value as McpTransport })}>
            <option value="stdio">Local command (stdio)</option>
            <option value="http">Remote (streamable HTTP)</option>
            <option value="sse">Remote (SSE, legacy)</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={draft.enabled} onChange={(e) => patch({ enabled: e.target.checked })} /> Enabled
        </label>

        {!remote ? (
          <>
            <label className="field">
              <span>Command</span>
              <input value={draft.command} placeholder="e.g. npx" onChange={(e) => patch({ command: e.target.value })} />
            </label>
            <label className="field">
              <span>Arguments (one per line)</span>
              <textarea rows={3} className="mono" value={argsText} onChange={(e) => setArgsText(e.target.value)} />
            </label>
            <label className="field">
              <span>Working directory (optional)</span>
              <input value={draft.cwd} onChange={(e) => patch({ cwd: e.target.value })} />
            </label>
            <KeyValueEditor title="Environment variables" placeholder="NAME" rows={draft.env} onChange={(env) => patch({ env })} reveal={reveal} />
          </>
        ) : (
          <>
            <label className="field">
              <span>URL</span>
              <input value={draft.url} placeholder="https://example.com/mcp" onChange={(e) => patch({ url: e.target.value })} />
            </label>
            <KeyValueEditor title="Headers" placeholder="Authorization" rows={draft.headers} onChange={(headers) => patch({ headers })} reveal={reveal} />
          </>
        )}

        <label className="check">
          <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} /> Show secret values
        </label>
        <label className="field">
          <span>Tool call timeout (seconds)</span>
          <input type="number" min={1} value={draft.timeout} onChange={(e) => patch({ timeout: Number(e.target.value) || 60 })} />
          <small>Values may reference environment variables, e.g. Bearer ${'{'}GITHUB_TOKEN{'}'}. The config file is readable only by you.</small>
        </label>

        <div className="row">
          <button className="btn" disabled={!!problem || testing} onClick={() => void test()}>
            Test connection
          </button>
          {testing && <span className="spinner" role="status" aria-label="Testing" />}
        </div>
        {result &&
          (result.ok ? (
            <div className="test ok">
              Connected — {result.tools?.length ?? 0} tool{result.tools?.length === 1 ? '' : 's'} available
              {!!result.tools?.length && <div className="mono small">{result.tools.map((t) => t.name).join(', ')}</div>}
            </div>
          ) : (
            <div className="test bad">
              Couldn’t connect
              <div className="small">{result.error}</div>
            </div>
          ))}
      </div>
      <div className="modal-actions">
        <span className="bad small grow">{error ?? (problem && (draft.name || !isNew) ? problem : '')}</span>
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn primary" disabled={!!problem || saving} onClick={() => void save()}>
          {saving ? 'Saving…' : isNew ? 'Add' : 'Save'}
        </button>
      </div>
    </Modal>
  )
}
