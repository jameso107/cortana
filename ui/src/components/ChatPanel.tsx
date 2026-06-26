import { useEffect, useRef } from 'react'
import type { Message } from '../App'

interface Props {
  messages: Message[]
  streaming?: string | null
  toolActivity?: string | null
}

export default function ChatPanel({ messages, streaming, toolActivity }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming, toolActivity])

  return (
    <div className="chat-panel">
      {messages.map((m, i) => (
        <div key={i} className={`message ${m.role}`}>
          <div className="message-label">{m.role === 'cortana' ? 'CORTANA' : 'YOU'}</div>
          {m.text}
        </div>
      ))}

      {toolActivity && (
        <div className="tool-activity">⚙ Using <b>{toolActivity}</b>…</div>
      )}

      {streaming != null && (
        <div className="message cortana streaming">
          <div className="message-label">CORTANA</div>
          {streaming}
          <span className="caret">▋</span>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
