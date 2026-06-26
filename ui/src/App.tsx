import { useState, useEffect, useRef } from 'react'
import BrainOrb from './components/BrainOrb'
import ChatPanel from './components/ChatPanel'
import StatusBar from './components/StatusBar'
import TerminalPanel from './components/TerminalPanel'
import SearchPanel from './components/SearchPanel'
import NotesPanel from './components/NotesPanel'
import FilesPanel from './components/FilesPanel'
import SysStats from './components/SysStats'
import './App.css'

export type Status = 'idle' | 'listening' | 'thinking' | 'speaking'
export type Tab = 'chat' | 'terminal' | 'search' | 'notes' | 'files'

export interface Message {
  role: 'user' | 'cortana'
  text: string
  ts: number
}

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'chat',     label: 'Chat',     icon: '◈' },
  { id: 'terminal', label: 'Terminal', icon: '>' },
  { id: 'search',   label: 'Search',   icon: '⌕' },
  { id: 'notes',    label: 'Notes',    icon: '≡' },
  { id: 'files',    label: 'Files',    icon: '◫' },
]

export default function App() {
  const [status, setStatus]   = useState<Status>('idle')
  const [activeTab, setActiveTab] = useState<Tab>('chat')
  const [messages, setMessages] = useState<Message[]>([
    { role: 'cortana', text: 'Cortana online. Systems nominal. How can I assist you?', ts: Date.now() },
  ])
  const [input, setInput] = useState('')
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const connect = () => {
      try {
        const ws = new WebSocket('ws://localhost:8765')
        ws.onopen  = () => setStatus('idle')
        ws.onmessage = (e) => {
          const data = JSON.parse(e.data)
          if (data.type === 'status') setStatus(data.value)
          if (data.type === 'message') {
            setMessages(prev => [...prev, { role: 'cortana', text: data.text, ts: Date.now() }])
          }
          // Voice input — show what Cortana heard in the chat as a user message
          if (data.type === 'voice_input') {
            setMessages(prev => [...prev, { role: 'user', text: `🎤 ${data.text}`, ts: Date.now() }])
            setStatus('listening')
          }
        }
        ws.onclose = () => setTimeout(connect, 3000)
        wsRef.current = ws
      } catch { setTimeout(connect, 3000) }
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  const send = () => {
    const text = input.trim()
    if (!text) return
    setMessages(prev => [...prev, { role: 'user', text, ts: Date.now() }])
    setInput('')
    setStatus('thinking')
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'message', text }))
    } else {
      setTimeout(() => {
        setMessages(prev => [...prev, {
          role: 'cortana',
          text: '[ Backend offline — start the Cortana daemon to process requests. ]',
          ts: Date.now(),
        }])
        setStatus('idle')
      }, 600)
    }
  }

  return (
    <div className="app">
      {/* ── Left column: orb + system stats ── */}
      <aside className="left-col">
        <div className="cortana-wordmark">
          <span className="wm-c">C</span>ORTANA
        </div>
        <BrainOrb status={status} />
        <SysStats />
      </aside>

      {/* ── Right column: tabs + panels + input ── */}
      <main className="right-col">
        <header className="top-bar">
          <StatusBar status={status} />
          <nav className="tab-bar">
            {TABS.map(t => (
              <button
                key={t.id}
                className={`tab-btn ${activeTab === t.id ? 'active' : ''}`}
                onClick={() => setActiveTab(t.id)}
              >
                <span className="tab-icon">{t.icon}</span>
                {t.label}
              </button>
            ))}
          </nav>
        </header>

        <div className="panel-area">
          {activeTab === 'chat'     && <ChatPanel messages={messages} />}
          {activeTab === 'terminal' && <TerminalPanel />}
          {activeTab === 'search'   && <SearchPanel />}
          {activeTab === 'notes'    && <NotesPanel />}
          {activeTab === 'files'    && <FilesPanel />}
        </div>

        {/* Universal input — visible on chat tab */}
        {activeTab === 'chat' && (
          <div className="input-row">
            <div className="input-icon">◈</div>
            <input
              className="text-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && send()}
              placeholder="Ask Cortana anything…"
              autoFocus
            />
            <button className="send-btn" onClick={send}>Send</button>
          </div>
        )}
      </main>
    </div>
  )
}
