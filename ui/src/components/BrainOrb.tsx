import { useEffect, useRef } from 'react'
import type { Status } from '../App'
import './BrainOrb.css'

interface Props { status: Status }

export default function BrainOrb({ status }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const statusRef = useRef(status)
  statusRef.current = status

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const W = canvas.width = 280
    const H = canvas.height = 280
    const cx = W / 2, cy = H / 2
    let frame = 0
    let animId: number

    // Neural network nodes — brain-hemisphere shape
    const nodes = Array.from({ length: 55 }, (_, i) => {
      const t = (i / 55) * Math.PI * 2
      const r = 50 + Math.random() * 75
      const spread = 0.55 + Math.random() * 0.75
      return {
        x: cx + Math.cos(t) * r * spread,
        y: cy + Math.sin(t) * r * (spread * 0.65),
        r: 1.2 + Math.random() * 2,
        phase: Math.random() * Math.PI * 2,
        speed: 0.018 + Math.random() * 0.03,
      }
    })

    const edges: [number, number][] = []
    nodes.forEach((a, i) => nodes.forEach((b, j) => {
      if (i >= j) return
      if (Math.hypot(a.x - b.x, a.y - b.y) < 72) edges.push([i, j])
    }))

    const draw = () => {
      const s = statusRef.current
      const speed = s === 'thinking' ? 3.5 : s === 'listening' ? 2 : s === 'speaking' ? 2.5 : 1
      const baseHue = s === 'thinking' ? 30 : s === 'listening' ? 140 : 200
      frame++
      ctx.clearRect(0, 0, W, H)

      // Core glow
      const g = ctx.createRadialGradient(cx, cy, 20, cx, cy, 130)
      g.addColorStop(0, `hsla(${baseHue + 10}, 100%, 70%, 0.12)`)
      g.addColorStop(0.6, `hsla(${baseHue}, 100%, 50%, 0.05)`)
      g.addColorStop(1, 'transparent')
      ctx.fillStyle = g
      ctx.beginPath()
      ctx.arc(cx, cy, 130, 0, Math.PI * 2)
      ctx.fill()

      // Edges
      edges.forEach(([i, j]) => {
        const a = nodes[i], b = nodes[j]
        const t = Math.sin(frame * 0.04 * speed + a.phase) * 0.5 + 0.5
        ctx.strokeStyle = `hsla(${baseHue + t * 40}, 100%, 65%, ${0.05 + t * 0.18})`
        ctx.lineWidth = 0.5 + t * 0.4
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
      })

      // Nodes
      nodes.forEach(n => {
        const t = Math.sin(frame * n.speed * speed + n.phase) * 0.5 + 0.5
        const ng = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 5)
        ng.addColorStop(0, `hsla(${baseHue + 20}, 100%, 80%, ${0.5 + t * 0.5})`)
        ng.addColorStop(1, 'transparent')
        ctx.fillStyle = ng
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r * 5, 0, Math.PI * 2); ctx.fill()

        ctx.fillStyle = `hsla(${baseHue + 30}, 100%, 90%, ${0.6 + t * 0.4})`
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r * (0.8 + t * 0.5), 0, Math.PI * 2); ctx.fill()
      })

      // Scan line
      const sy = cy + Math.sin(frame * 0.025 * speed) * 90
      const sg = ctx.createLinearGradient(cx - 110, sy, cx + 110, sy)
      sg.addColorStop(0, 'transparent')
      sg.addColorStop(0.5, `hsla(${baseHue}, 100%, 65%, 0.18)`)
      sg.addColorStop(1, 'transparent')
      ctx.fillStyle = sg
      ctx.fillRect(cx - 110, sy - 1, 220, 1.5)

      animId = requestAnimationFrame(draw)
    }
    draw()
    return () => cancelAnimationFrame(animId)
  }, [])

  return (
    <div className={`brain-orb ${status}`}>
      <div className="ring r1" />
      <div className="ring r2" />
      <canvas ref={canvasRef} className="brain-canvas" />
    </div>
  )
}
