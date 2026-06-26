import { useEffect, useRef, useState } from 'react'
import type { Message } from '../App'
import { renderMarkdown } from '../markdown'

interface Props {
  messages: Message[]
  streaming?: string | null
  toolActivity?: string | null
}

function timeOf(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function Bubble({ m }: { m: Message }) {
  const [copied, setCopied] = useState(false)
  const isCortana = m.role === 'cortana'

  const copy = () => {
    navigator.clipboard?.writeText(m.text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1200)
  }

  return (
    <div className={`message ${m.role}`}>
      <div className="message-head">
        <span className="message-label">{isCortana ? 'CORTANA' : 'YOU'}</span>
        <span className="message-time">{timeOf(m.ts)}</span>
        <button className="message-copy" onClick={copy} title="Copy">
          {copied ? '✓' : '⧉'}
        </button>
      </div>
      {isCortana
        ? <div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(m.text) }} />
        : <div className="msg-text">{m.text}</div>}
    </div>
  )
}

export default function ChatPanel({ messages, streaming, toolActivity }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming, toolActivity])

  // Delegate clicks on code "copy" buttons inside rendered markdown.
  const onClick = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement
    if (t.classList.contains('md-copy')) {
      const code = decodeURIComponent(t.getAttribute('data-code') || '')
      navigator.clipboard?.writeText(code)
      const prev = t.textContent
      t.textContent = 'copied'
      setTimeout(() => { t.textContent = prev }, 1200)
    }
  }

  const empty = messages.length <= 1 && !streaming

  return (
    <div className="chat-panel" ref={panelRef} onClick={onClick}>
      {messages.map((m, i) => <Bubble key={i} m={m} />)}

      {toolActivity && (
        <div className="tool-activity">⚙ Using <b>{toolActivity}</b>…</div>
      )}

      {streaming != null && (
        <div className="message cortana streaming">
          <div className="message-head"><span className="message-label">CORTANA</span></div>
          <div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(streaming) }} />
          <span className="caret">▋</span>
        </div>
      )}

      {empty && (
        <div className="chat-hint">
          Try: <em>"what can you do?"</em> · <em>"remember my timezone is EST"</em> · <em>"give me my daily briefing"</em>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
