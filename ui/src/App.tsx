import { useState, useEffect, useRef } from 'react'
import { WS_CHAT } from './config'
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
  const [input, setInput]         = useState('')
  const [voiceOn, setVoiceOn]     = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const connect = () => {
      try {
        const ws = new WebSocket(WS_CHAT)
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
          }
          if (data.type === 'voice_mode_ack') {
            setVoiceOn(data.enabled)
          }
        }
        ws.onclose = () => setTimeout(connect, 3000)
        wsRef.current = ws
      } catch { setTimeout(connect, 3000) }
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  const toggleVoice = () => {
    const next = !voiceOn
    setVoiceOn(next)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'voice_mode', enabled: next }))
    }
  }

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

  const isChat = activeTab === 'chat'

  return (
    <div className={`app ${isChat ? 'mode-chat' : 'mode-panel'}`}>
      {/* ── Brain: large, centered, the living core ── */}
      <div className="brain-bg">
        <BrainOrb status={status} />
      </div>

      {/* ── Top HUD: wordmark + status + tabs ── */}
      <header className="hud-top">
        <div className="hud-brand">
          <span className="wm-c">C</span>ORTANA
          <StatusBar status={status} />
        </div>
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

      {/* ── System stats HUD (bottom-left corner) ── */}
      <div className="stats-hud">
        <SysStats />
      </div>

      {/* ── Dock: active panel floats over the brain ── */}
      <main className="dock">
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
            <button
              className={`mic-btn ${voiceOn ? 'active' : ''}`}
              onClick={toggleVoice}
              title={voiceOn ? 'Voice mode ON — click to disable' : 'Click to enable voice mode'}
            >
              {voiceOn ? '🎙' : '🎤'}
            </button>
            <button className="send-btn" onClick={send}>Send</button>
          </div>
        )}
      </main>
    </div>
  )
}
