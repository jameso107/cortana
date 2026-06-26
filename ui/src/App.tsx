import { useState, useEffect, useRef } from 'react'
import { WS_CHAT } from './config'
import BrainOrb from './components/BrainOrb'
import ChatPanel from './components/ChatPanel'
import StatusBar from './components/StatusBar'
import TerminalPanel from './components/TerminalPanel'
import SearchPanel from './components/SearchPanel'
import NotesPanel from './components/NotesPanel'
import FilesPanel from './components/FilesPanel'
import MemoryPanel from './components/MemoryPanel'
import SystemPanel from './components/SystemPanel'
import SysStats from './components/SysStats'
import './App.css'

export type Status = 'idle' | 'listening' | 'thinking' | 'speaking'
export type Tab = 'chat' | 'terminal' | 'search' | 'notes' | 'files' | 'memory' | 'system'

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
  { id: 'memory',   label: 'Memory',   icon: '✦' },
  { id: 'system',   label: 'System',   icon: '⚙' },
]

const QUICK = [
  { label: 'Daily briefing', text: 'Give me my daily briefing.' },
  { label: 'What can you do?', text: 'What can you do? List your capabilities briefly.' },
  { label: 'System status', text: 'Summarize your current system status.' },
]

export default function App() {
  const [status, setStatus]       = useState<Status>('idle')
  const [connected, setConnected] = useState(false)
  const [activeTab, setActiveTab] = useState<Tab>('chat')
  const [messages, setMessages]   = useState<Message[]>([
    { role: 'cortana', text: 'Cortana online. Systems nominal. How can I assist you?', ts: Date.now() },
  ])
  const [input, setInput]         = useState('')
  const [voiceOn, setVoiceOn]     = useState(false)
  const [streaming, setStreaming] = useState<string | null>(null)
  const [toolActivity, setToolActivity] = useState<string | null>(null)
  const [reasoning, setReasoning] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const connect = () => {
      try {
        const ws = new WebSocket(WS_CHAT)
        ws.onopen  = () => { setConnected(true); setStatus('idle') }
        ws.onmessage = (e) => {
          const data = JSON.parse(e.data)
          if (data.type === 'status') setStatus(data.value)
          if (data.type === 'message') {
            setMessages(prev => [...prev, { role: 'cortana', text: data.text, ts: Date.now() }])
          }
          if (data.type === 'stream_start') { setStreaming(''); setToolActivity(null) }
          if (data.type === 'stream_delta')  setStreaming(prev => (prev ?? '') + data.text)
          if (data.type === 'stream_cancel') { setStreaming(null); setReasoning(false) }
          if (data.type === 'stream_end') {
            const text = data.text ?? ''
            if (text) setMessages(prev => [...prev, { role: 'cortana', text, ts: Date.now() }])
            setStreaming(null); setToolActivity(null); setReasoning(false)
          }
          if (data.type === 'tool') setToolActivity(data.name)
          if (data.type === 'reasoning') setReasoning(data.value === 'start')
          if (data.type === 'voice_input') {
            setMessages(prev => [...prev, { role: 'user', text: `🎤 ${data.text}`, ts: Date.now() }])
          }
          if (data.type === 'voice_mode_ack') setVoiceOn(data.enabled)
        }
        ws.onclose = () => { setConnected(false); setStatus('idle'); setTimeout(connect, 3000) }
        wsRef.current = ws
      } catch { setTimeout(connect, 3000) }
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  const toggleVoice = () => {
    const next = !voiceOn
    setVoiceOn(next)
    wsRef.current?.readyState === WebSocket.OPEN &&
      wsRef.current.send(JSON.stringify({ type: 'voice_mode', enabled: next }))
  }

  const generating = status === 'thinking' || status === 'speaking' || streaming !== null

  const sendText = (text: string) => {
    const t = text.trim()
    if (!t) return
    setMessages(prev => [...prev, { role: 'user', text: t, ts: Date.now() }])
    setStatus('thinking')
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'message', text: t }))
    } else {
      setTimeout(() => {
        setMessages(prev => [...prev, {
          role: 'cortana',
          text: '[ Backend offline — start the Cortana daemon to process requests. ]',
          ts: Date.now(),
        }])
        setStatus('idle')
      }, 500)
    }
  }

  const send = () => { sendText(input); setInput('') }
  const stop = () => wsRef.current?.readyState === WebSocket.OPEN &&
    wsRef.current.send(JSON.stringify({ type: 'stop' }))

  const isChat = activeTab === 'chat'

  return (
    <div className={`app ${isChat ? 'mode-chat' : 'mode-panel'}`}>
      <div className="brain-bg"><BrainOrb status={status} /></div>

      {/* ── Top command bar ── */}
      <header className="hud-top">
        <div className="hud-brand">
          <span className="wm-c">C</span>ORTANA
          <span className={`conn-pill ${connected ? 'on' : 'off'}`} title={connected ? 'Connected' : 'Disconnected'}>
            {connected ? 'ONLINE' : 'OFFLINE'}
          </span>
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
              <span className="tab-label">{t.label}</span>
            </button>
          ))}
        </nav>
      </header>

      <div className="stats-hud"><SysStats /></div>

      {/* ── Dock ── */}
      <main className="dock">
        <div className="panel-area">
          {activeTab === 'chat'     && <ChatPanel messages={messages} streaming={streaming} toolActivity={toolActivity} reasoning={reasoning} />}
          {activeTab === 'terminal' && <TerminalPanel />}
          {activeTab === 'search'   && <SearchPanel />}
          {activeTab === 'notes'    && <NotesPanel />}
          {activeTab === 'files'    && <FilesPanel />}
          {activeTab === 'memory'   && <MemoryPanel />}
          {activeTab === 'system'   && <SystemPanel />}
        </div>

        {isChat && (
          <div className="composer">
            <div className="quick-row">
              {QUICK.map(q => (
                <button key={q.label} className="quick-chip" onClick={() => sendText(q.text)}>
                  {q.label}
                </button>
              ))}
            </div>
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
              {generating
                ? <button className="stop-btn" onClick={stop} title="Stop generating">■ Stop</button>
                : <button className="send-btn" onClick={send}>Send</button>}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
