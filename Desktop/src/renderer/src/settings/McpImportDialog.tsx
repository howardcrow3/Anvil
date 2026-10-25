import { useState } from 'react'
import { Modal } from '@/components/Modal'
import { parseImport, validate } from '@/lib/mcp'
import type { McpServer } from '@/lib/types'

export function McpImportDialog({ onImport, onClose }: { onImport: (servers: McpServer[]) => Promise<string | null>; onClose: () => void }): React.JSX.Element {
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (): Promise<void> => {
    setError(null)
    let servers: McpServer[]
    try {
      servers = parseImport(text)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return
    }
    for (const s of servers) {
      const problem = validate(s, [])
      if (problem) return setError(`${s.name}: ${problem}`)
    }
    setBusy(true)
    const failure = await onImport(servers)
    setBusy(false)
    if (failure) setError(failure)
    else onClose()
  }

  return (
    <Modal title="Import MCP servers" onClose={onClose} width={560}>
      <p className="muted">Paste a config from Claude Desktop or Claude Code ({'{"mcpServers": …}'}). Servers with the same name as an existing one are replaced.</p>
      <textarea className="mono import-box" value={text} onChange={(e) => setText(e.target.value)} rows={12} spellCheck={false} aria-label="MCP config JSON" />
      <div className="modal-actions">
        <span className="bad small grow">{error}</span>
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn primary" disabled={!text.trim() || busy} onClick={() => void submit()}>
          {busy ? 'Importing…' : 'Import'}
        </button>
      </div>
    </Modal>
  )
}
