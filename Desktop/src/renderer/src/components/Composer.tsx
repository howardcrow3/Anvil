import { useEffect, useRef, useState } from 'react'
import { useApp } from '@/store/app'

export function Composer(): React.JSX.Element {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  const streaming = useApp((s) => s.chat.streaming)
  const connected = useApp((s) => s.connection === 'open')
  const send = useApp((s) => s.send)
  const cancel = useApp((s) => s.cancel)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  }, [text])

  const submit = (): void => {
    if (!text.trim() || streaming || !connected) return
    const value = text
    setText('')
    void send(value)
  }

  return (
    <div className="composer">
      <textarea
        ref={ref}
        value={text}
        rows={1}
        placeholder={connected ? 'Message Anvil…  (Enter to send, Shift+Enter for a new line, / for commands)' : 'Waiting for the agent runtime…'}
        disabled={!connected}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            submit()
          }
        }}
        aria-label="Message"
      />
      {streaming ? (
        <button className="btn danger" onClick={() => void cancel()}>
          Stop
        </button>
      ) : (
        <button className="btn primary" onClick={submit} disabled={!text.trim() || !connected}>
          Send
        </button>
      )}
    </div>
  )
}
