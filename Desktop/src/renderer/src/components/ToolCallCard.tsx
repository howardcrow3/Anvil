import { useState } from 'react'
import type { Part } from '@/lib/types'

type ToolPart = Extract<Part, { type: 'tool' }>

const ICON = { running: '⏳', done: '✓', error: '✕' } as const

function summary(args: Record<string, unknown>): string {
  const first = args.command ?? args.path ?? args.file_path ?? args.pattern ?? args.query ?? args.url ?? Object.values(args)[0]
  const text = typeof first === 'string' ? first : first === undefined ? '' : JSON.stringify(first)
  return text.length > 90 ? `${text.slice(0, 90)}…` : text
}

export function ToolCallCard({ part }: { part: ToolPart }): React.JSX.Element {
  const [open, setOpen] = useState(false)
  return (
    <div className={`tool-card ${part.status}`}>
      <button className="tool-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className={`tool-icon ${part.status}`} aria-label={part.status}>
          {ICON[part.status]}
        </span>
        <span className="tool-name">{part.name}</span>
        <span className="tool-summary">{summary(part.arguments)}</span>
        <span className="chev">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="tool-body">
          <div className="tool-label">Arguments</div>
          <pre>{JSON.stringify(part.arguments, null, 2)}</pre>
          {part.result !== undefined && (
            <>
              <div className="tool-label">{part.status === 'error' ? 'Error' : 'Result'}</div>
              <pre className={part.status === 'error' ? 'err' : ''}>{part.result.length > 20000 ? `${part.result.slice(0, 20000)}\n… (truncated)` : part.result}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}
