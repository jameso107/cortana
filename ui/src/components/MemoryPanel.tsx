import { useEffect, useState, useCallback } from 'react'
import { API_BASE } from '../config'

interface MemoryData {
  facts: Record<string, string>
  episodic: { ts: string; text: string }[]
}

export default function MemoryPanel() {
  const [data, setData] = useState<MemoryData>({ facts: {}, episodic: [] })
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/memory`)
      setData(await res.json())
    } catch {
      setData({ facts: {}, episodic: [] })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const forget = async (key: string) => {
    await fetch(`${API_BASE}/memory/fact?key=${encodeURIComponent(key)}`, { method: 'DELETE' })
    load()
  }

  const facts = Object.entries(data.facts)

  return (
    <div className="memory-panel">
      <div className="mem-section">
        <div className="mem-head">
          <span>What Cortana knows about you</span>
          <button className="mem-refresh" onClick={load} title="Refresh">⟳</button>
        </div>
        {loading ? (
          <div className="mem-empty">Loading…</div>
        ) : facts.length === 0 ? (
          <div className="mem-empty">No stored facts yet. Tell Cortana something to remember.</div>
        ) : (
          <ul className="mem-facts">
            {facts.map(([k, v]) => (
              <li key={k}>
                <span className="mem-key">{k}</span>
                <span className="mem-val">{v}</span>
                <button className="mem-forget" onClick={() => forget(k)} title="Forget this">✕</button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mem-section">
        <div className="mem-head"><span>Recent memories</span></div>
        {data.episodic.length === 0 ? (
          <div className="mem-empty">No conversation history yet.</div>
        ) : (
          <ul className="mem-episodic">
            {data.episodic.map((e, i) => (
              <li key={i}>{e.text}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
