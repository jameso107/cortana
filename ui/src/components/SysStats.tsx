import { useState, useEffect } from 'react'

interface Stats {
  cpu: number
  ram_pct: number
  ram_used_gb: number
  ram_total_gb: number
  model: string
  uptime: string
}

const DEFAULT: Stats = { cpu: 0, ram_pct: 0, ram_used_gb: 0, ram_total_gb: 0, model: '—', uptime: '—' }

export default function SysStats() {
  const [stats, setStats] = useState<Stats>(DEFAULT)

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch('/api/stats')
        if (res.ok) setStats(await res.json())
      } catch { /* daemon not up yet */ }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [])

  const rows = [
    {
      label: 'CPU',
      val: `${stats.cpu.toFixed(1)}%`,
      pct: stats.cpu / 100,
    },
    {
      label: 'RAM',
      val: `${stats.ram_used_gb.toFixed(1)} / ${stats.ram_total_gb.toFixed(0)} GB`,
      pct: stats.ram_pct / 100,
    },
    { label: 'MODEL',  val: stats.model,  pct: null },
    { label: 'UPTIME', val: stats.uptime, pct: null },
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
