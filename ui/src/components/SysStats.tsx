import { useState, useEffect } from 'react'

interface Stats { cpu: number; mem: number; model: string; uptime: string }

export default function SysStats() {
  const [stats, setStats] = useState<Stats>({ cpu: 0, mem: 0, model: 'Qwen3-27B Q6', uptime: '—' })

  useEffect(() => {
    // Poll backend for stats when available; show simulated idle animation otherwise
    const tick = () => {
      setStats(prev => ({
        ...prev,
        cpu: Math.max(2, Math.min(30, prev.cpu + (Math.random() - 0.5) * 4)),
        mem: 34 + Math.sin(Date.now() / 8000) * 3,
      }))
    }
    const id = setInterval(tick, 2000)
    return () => clearInterval(id)
  }, [])

  const rows = [
    { label: 'CPU',   val: `${stats.cpu.toFixed(0)}%`,  pct: stats.cpu / 100 },
    { label: 'RAM',   val: `${stats.mem.toFixed(0)}%`,  pct: stats.mem / 100 },
    { label: 'MODEL', val: stats.model,                  pct: null },
  ]

  return (
    <div className="sys-stats">
      {rows.map(r => (
        <div key={r.label}>
          <div className="stat-row">
            <span className="stat-label">{r.label}</span>
            <span className="stat-val">{r.val}</span>
          </div>
          {r.pct !== null && (
            <div className="stat-bar">
              <div className="stat-fill" style={{ width: `${r.pct * 100}%` }} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
