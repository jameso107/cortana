import { useEffect, useRef } from 'react'
import type { Message } from '../App'

export default function ChatPanel({ messages }: { messages: Message[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  return (
    <div className="chat-panel">
      {messages.map((m, i) => (
        <div key={i} className={`message ${m.role}`}>
          <div className="message-label">{m.role === 'cortana' ? 'CORTANA' : 'YOU'}</div>
          {m.text}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
