import { memo } from 'react'
import type { Message } from '@/lib/types'
import { Markdown } from './Markdown'
import { ToolCallCard } from './ToolCallCard'

export const MessageView = memo(function MessageView({ message }: { message: Message }): React.JSX.Element {
  if (message.role === 'system') {
    return <div className="msg-system">{message.parts.map((p) => (p.type === 'text' ? p.text : '')).join('')}</div>
  }
  return (
    <div className={`msg ${message.role}`}>
      <div className="msg-role">{message.role === 'user' ? 'You' : 'Anvil'}</div>
      <div className="msg-body">
        {message.parts.map((part, i) => {
          if (part.type === 'text') {
            return message.role === 'user' ? (
              <p key={i} className="user-text">
                {part.text}
              </p>
            ) : (
              <Markdown key={i} text={part.text} />
            )
          }
          if (part.type === 'tool') return <ToolCallCard key={part.id} part={part} />
          return (
            <div key={i} className="msg-error" role="alert">
              {part.message}
            </div>
          )
        })}
      </div>
    </div>
  )
})
