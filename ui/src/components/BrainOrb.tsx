/**
 * BrainOrb — animated holographic brain orb inspired by Cortana / JARVIS.
 * Uses SVG + CSS animations only, no external deps.
 */
import { useEffect, useRef } from 'react'
import type { Status } from '../App'
import './BrainOrb.css'

interface Props { status: Status }

export default function BrainOrb({ status }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    let frame = 0
    let animId: number

    const W = canvas.width = 500
    const H = canvas.height = 500
    const cx = W / 2, cy = H / 2

    // Neural node positions (brain-like cluster)
    const nodes = Array.from({ length: 60 }, (_, i) => {
      const angle = (i / 60) * Math.PI * 2
      const r = 80 + Math.random() * 100
      return {
        x: cx + Math.cos(angle) * r * (0.6 + Math.random() * 0.8),
        y: cy + Math.sin(angle) * r * (0.4 + Math.random() * 0.6),
        r: 1.5 + Math.random() * 2.5,
        phase: Math.random() * Math.PI * 2,
        speed: 0.02 + Math.random() * 0.04,
      }
    })

    // Edges (nearest-neighbor connections)
    const edges: [number, number][] = []
    nodes.forEach((n, i) => {
      nodes.forEach((m, j) => {
        if (i >= j) return
        const d = Math.hypot(n.x - m.x, n.y - m.y)
        if (d < 90) edges.push([i, j])
      })
    })

    const speedMult = status === 'thinking' ? 3 : status === 'listening' ? 1.5 : 1

    const draw = () => {
      ctx.clearRect(0, 0, W, H)
      frame++

      // Outer glow sphere
      const grad = ctx.createRadialGradient(cx, cy, 60, cx, cy, 220)
      grad.addColorStop(0, '#00d4ff18')
      grad.addColorStop(0.5, '#0050ff0a')
      grad.addColorStop(1, 'transparent')
      ctx.fillStyle = grad
      ctx.beginPath()
      ctx.arc(cx, cy, 220, 0, Math.PI * 2)
      ctx.fill()

      // Edges
      edges.forEach(([i, j]) => {
        const a = nodes[i], b = nodes[j]
        const pulse = Math.sin(frame * 0.04 * speedMult + a.phase) * 0.5 + 0.5
        ctx.strokeStyle = `rgba(0, ${100 + Math.floor(pulse * 100)}, 255, ${0.06 + pulse * 0.14})`
        ctx.lineWidth = 0.6
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.stroke()
      })

      // Nodes
      nodes.forEach(n => {
        const pulse = Math.sin(frame * n.speed * speedMult + n.phase) * 0.5 + 0.5
        const alpha = 0.4 + pulse * 0.6
        const size = n.r * (0.8 + pulse * 0.6)
        const ng = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, size * 4)
        ng.addColorStop(0, `rgba(0, 212, 255, ${alpha})`)
        ng.addColorStop(1, 'transparent')
        ctx.fillStyle = ng
        ctx.beginPath()
        ctx.arc(n.x, n.y, size * 4, 0, Math.PI * 2)
        ctx.fill()

        ctx.fillStyle = `rgba(180, 240, 255, ${alpha})`
        ctx.beginPath()
        ctx.arc(n.x, n.y, size, 0, Math.PI * 2)
        ctx.fill()
      })

      // Scan line
      const scanY = cy + Math.sin(frame * 0.03 * speedMult) * 150
      const scanGrad = ctx.createLinearGradient(cx - 160, scanY, cx + 160, scanY)
      scanGrad.addColorStop(0, 'transparent')
      scanGrad.addColorStop(0.5, '#00d4ff22')
      scanGrad.addColorStop(1, 'transparent')
      ctx.fillStyle = scanGrad
      ctx.fillRect(cx - 160, scanY - 1, 320, 2)

      animId = requestAnimationFrame(draw)
    }
    draw()
    return () => cancelAnimationFrame(animId)
  }, [status])

  return (
    <div className={`brain-orb ${status}`}>
      {/* Outer ring decorations */}
      <div className="ring ring-outer" />
      <div className="ring ring-mid" />
      <canvas ref={canvasRef} className="brain-canvas" />
      <div className="orb-label">{status.toUpperCase()}</div>
    </div>
  )
}
