import { useState, useEffect, useRef } from 'react'
import BrainOrb from './components/BrainOrb'
import ChatPanel from './components/ChatPanel'
import StatusBar from './components/StatusBar'
import './App.css'

export type Status = 'idle' | 'listening' | 'thinking' | 'speaking'

export interface Message {
  role: 'user' | 'cortana'
  text: string
  ts: number
}

export default function App() {
  const [status, setStatus] = useState<Status>('idle')
  const [messages, setMessages] = useState<Message[]>([
    { role: 'cortana', text: 'Cortana online. How can I help you?', ts: Date.now() },
  ])
  const [input, setInput] = useState('')
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const connect = () => {
      try {
        const ws = new WebSocket('ws://localhost:8765')
        ws.onopen = () => setStatus('idle')
        ws.onmessage = (e) => {
          const data = JSON.parse(e.data)
          if (data.type === 'status') setStatus(data.value)
          if (data.type === 'message') {
            setMessages(prev => [...prev, { role: 'cortana', text: data.text, ts: Date.now() }])
            setStatus('idle')
          }
        }
        ws.onclose = () => setTimeout(connect, 3000)
        wsRef.current = ws
      } catch {
        setTimeout(connect, 3000)
      }
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
      // Offline demo mode
      setTimeout(() => {
        setMessages(prev => [...prev, {
          role: 'cortana',
          text: '(Backend not connected — start the Cortana daemon to get live responses.)',
          ts: Date.now(),
        }])
        setStatus('idle')
      }, 800)
    }
  }

  return (
    <div className="app">
      <div className="orb-container">
        <BrainOrb status={status} />
      </div>
      <div className="interface">
        <StatusBar status={status} />
        <ChatPanel messages={messages} />
        <div className="input-row">
          <input
            className="text-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && send()}
            placeholder="Speak or type a command…"
            autoFocus
          />
          <button className="send-btn" onClick={send}>▶</button>
        </div>
      </div>
    </div>
  )
}
