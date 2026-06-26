import { useEffect, useState, useCallback } from 'react'
import { API_BASE } from '../config'

interface Manifest { name: string; description: string; capabilities: string[] }
interface Health { llama_up?: boolean; model?: string; uptime?: string }

const CAP_COLOR: Record<string, string> = {
  network: '#00d4ff', filesystem: '#ffcc00', shell: '#ff5577',
  system: '#00ff88', code: '#c084fc',
}
const REASONING = ['auto', 'always', 'never'] as const

export default function SystemPanel() {
  const [plugins, setPlugins] = useState<Manifest[]>([])
  const [health, setHealth] = useState<Health>({})
  const [reasoning, setReasoning] = useState<string>('auto')

  const load = useCallback(async () => {
    try {
      const [p, c, s] = await Promise.all([
        fetch(`${API_BASE}/plugins`).then(r => r.json()),
        fetch(`${API_BASE}/config`).then(r => r.json()),
        fetch(`${API_BASE}/stats`).then(r => r.json()),
      ])
      setPlugins(p.plugins ?? [])
      setReasoning(c.reasoning ?? 'auto')
      setHealth(s)
    } catch { /* daemon not up */ }
  }, [])

  useEffect(() => { load() }, [load])

  const setMode = async (mode: string) => {
    setReasoning(mode)
    try {
      await fetch(`${API_BASE}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reasoning: mode }),
      })
    } catch { /* ignore */ }
  }

  return (
    <div className="system-panel">
      <div className="sys-block">
        <div className="sys-head">Engine</div>
        <div className="sys-grid">
          <div className="sys-cell"><span>Inference</span>
            <b className={health.llama_up ? 'ok' : 'down'}>
              {health.llama_up ? '● online' : '○ offline'}
            </b>
          </div>
          <div className="sys-cell"><span>Model</span><b>{health.model ?? '—'}</b></div>
          <div className="sys-cell"><span>Uptime</span><b>{health.uptime ?? '—'}</b></div>
        </div>
      </div>

      <div className="sys-block">
        <div className="sys-head">Reasoning mode</div>
        <div className="seg">
          {REASONING.map(m => (
            <button key={m} className={`seg-btn ${reasoning === m ? 'on' : ''}`}
              onClick={() => setMode(m)}>{m}</button>
          ))}
        </div>
        <div className="sys-note">
          {reasoning === 'auto'   && 'Thinks for complex/multi-step asks, fast for simple ones.'}
          {reasoning === 'always' && 'Always uses chain-of-thought (slower, more thorough).'}
          {reasoning === 'never'  && 'Never thinks (fastest, best for quick replies).'}
        </div>
      </div>

      <div className="sys-block">
        <div className="sys-head">Plugins <span className="sys-count">{plugins.length}</span></div>
        <ul className="plugin-list">
          {plugins.map(p => (
            <li key={p.name} className="plugin-item">
              <div className="plugin-row">
                <span className="plugin-name">{p.name}</span>
                <span className="plugin-caps">
                  {p.capabilities.length === 0
                    ? <em className="cap none">safe</em>
                    : p.capabilities.map(c => (
                        <em key={c} className="cap" style={{ color: CAP_COLOR[c] ?? '#b8e8ff', borderColor: (CAP_COLOR[c] ?? '#b8e8ff') + '55' }}>{c}</em>
                      ))}
                </span>
              </div>
              <div className="plugin-desc">{p.description}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
