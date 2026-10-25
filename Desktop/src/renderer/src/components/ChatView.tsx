import { useEffect, useRef } from 'react'
import { useApp } from '@/store/app'
import { Composer } from './Composer'
import { MessageView } from './MessageView'
import { ModelSelector } from './ModelSelector'
import { PermissionDialog } from './PermissionDialog'

export function ChatView(): React.JSX.Element {
  const messages = useApp((s) => s.chat.messages)
  const streaming = useApp((s) => s.chat.streaming)
  const planning = useApp((s) => s.planning)
  const toggle = useApp((s) => s.togglePlanning)
  const connected = useApp((s) => s.connection === 'open')
  const scroller = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)

  // Follow the stream unless the user has scrolled up to read.
  useEffect(() => {
    const el = scroller.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [messages])

  return (
    <main className="chat">
      <header className="chat-head">
        <ModelSelector />
        <button className={`btn ghost ${planning ? 'on' : ''}`} onClick={() => void toggle()} disabled={!connected} aria-pressed={planning} title="Plan mode explores and plans without changing files">
          Plan mode
        </button>
      </header>
      <div
        className="messages"
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
      >
        {messages.length === 0 ? (
          <div className="empty">
            <h1>What should we build?</h1>
            <p>Ask Anvil to read, edit and run code in your project. Use / for commands.</p>
          </div>
        ) : (
          <div className="thread">
            {messages.map((m) => (
              <MessageView key={m.id} message={m} />
            ))}
            {streaming && <div className="typing" aria-live="polite">Working…</div>}
          </div>
        )}
      </div>
      <Composer />
      <PermissionDialog />
    </main>
  )
}
