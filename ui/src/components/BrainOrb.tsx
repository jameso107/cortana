import { useEffect, useRef } from 'react'
import type { Status } from '../App'
import './BrainOrb.css'

interface Props { status: Status }

interface Node {
  // base position on unit ellipsoid (3D)
  bx: number; by: number; bz: number
  // animated position
  x: number; y: number; z: number
  // projected
  sx: number; sy: number; scale: number
  r: number
  phase: number
  speed: number
  freq: number   // turbulence frequency
}

interface Pulse {
  path: number[]   // node indices to travel through
  t: number        // 0..path.length
  speed: number
}

// Status → visual parameters
function paramsFor(s: Status) {
  switch (s) {
    case 'listening': return { hue: 150, rot: 0.0016, turb: 0.06, breathe: 0.07, pulseRate: 0.04, coreP: 0.6 }
    case 'thinking':  return { hue: 28,  rot: 0.0052, turb: 0.34, breathe: 0.04, pulseRate: 0.22, coreP: 1.0 }
    case 'speaking':  return { hue: 190, rot: 0.0030, turb: 0.16, breathe: 0.13, pulseRate: 0.14, coreP: 0.9 }
    default:          return { hue: 200, rot: 0.0011, turb: 0.04, breathe: 0.05, pulseRate: 0.02, coreP: 0.45 }
  }
}

export default function BrainOrb({ status }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef   = useRef<HTMLDivElement>(null)
  const statusRef = useRef(status)
  statusRef.current = status

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap   = wrapRef.current
    if (!canvas || !wrap) return
    const ctx = canvas.getContext('2d')!

    let W = 0, H = 0, cx = 0, cy = 0, R = 0
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    const resize = () => {
      const rect = wrap.getBoundingClientRect()
      W = rect.width; H = rect.height
      canvas.width  = W * dpr
      canvas.height = H * dpr
      canvas.style.width  = W + 'px'
      canvas.style.height = H + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      cx = W / 2; cy = H / 2
      R = Math.min(W, H) * 0.34   // brain radius
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(wrap)

    // ── Build a brain-shaped 3D point cloud ──────────────────────────────────
    const N = 360
    const nodes: Node[] = []
    // Fibonacci sphere → even distribution, then squash into a brain-ish ellipsoid
    const gold = Math.PI * (3 - Math.sqrt(5))
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2          // 1 → -1
      const rad = Math.sqrt(1 - y * y)
      const theta = gold * i
      let px = Math.cos(theta) * rad
      let pz = Math.sin(theta) * rad
      let py = y
      // jitter inward for volumetric feel (some interior nodes)
      const shell = 0.72 + Math.random() * 0.28
      px *= shell; py *= shell; pz *= shell
      // brain proportions: wider on x, flatter on y, two-lobe pinch on x≈0
      px *= 1.18
      py *= 0.82
      pz *= 1.0
      // central fissure: nudge points slightly away from x=0 plane to suggest hemispheres
      px += (px >= 0 ? 1 : -1) * 0.06
      nodes.push({
        bx: px, by: py, bz: pz,
        x: px, y: py, z: pz,
        sx: 0, sy: 0, scale: 1,
        r: 0.8 + Math.random() * 1.8,
        phase: Math.random() * Math.PI * 2,
        speed: 0.6 + Math.random() * 1.4,
        freq: 0.5 + Math.random() * 1.5,
      })
    }

    // Edges: connect each node to its nearest few neighbours (in base space)
    const edges: [number, number][] = []
    const maxPerNode = 3
    for (let i = 0; i < N; i++) {
      const dists: { j: number; d: number }[] = []
      for (let j = 0; j < N; j++) {
        if (i === j) continue
        const a = nodes[i], b = nodes[j]
        const d = (a.bx - b.bx) ** 2 + (a.by - b.by) ** 2 + (a.bz - b.bz) ** 2
        dists.push({ j, d })
      }
      dists.sort((p, q) => p.d - q.d)
      for (let k = 0; k < maxPerNode; k++) {
        const j = dists[k].j
        if (i < j) edges.push([i, j])
        else if (!edges.some(([a, b]) => a === j && b === i)) edges.push([j, i])
      }
    }
    // adjacency for pulse routing
    const adj: number[][] = Array.from({ length: N }, () => [])
    edges.forEach(([i, j]) => { adj[i].push(j); adj[j].push(i) })

    const pulses: Pulse[] = []
    const spawnPulse = () => {
      let cur = Math.floor(Math.random() * N)
      const path = [cur]
      const len = 5 + Math.floor(Math.random() * 7)
      for (let s = 0; s < len; s++) {
        const next = adj[cur]
        if (!next.length) break
        cur = next[Math.floor(Math.random() * next.length)]
        path.push(cur)
      }
      pulses.push({ path, t: 0, speed: 0.06 + Math.random() * 0.08 })
    }

    // Smoothly interpolated live params
    let live = paramsFor(statusRef.current)
    let rotY = 0, rotX = -0.18
    let frame = 0
    let animId = 0

    const lerp = (a: number, b: number, f: number) => a + (b - a) * f

    const draw = () => {
      frame++
      const target = paramsFor(statusRef.current)
      // ease params toward target
      live = {
        hue:       lerp(live.hue, target.hue, 0.05),
        rot:       lerp(live.rot, target.rot, 0.05),
        turb:      lerp(live.turb, target.turb, 0.05),
        breathe:   lerp(live.breathe, target.breathe, 0.05),
        pulseRate: lerp(live.pulseRate, target.pulseRate, 0.05),
        coreP:     lerp(live.coreP, target.coreP, 0.05),
      }
      const hue = live.hue

      rotY += live.rot * 16
      rotX = -0.18 + Math.sin(frame * 0.004) * 0.12   // gentle nod

      // breathing scale
      const breath = 1 + Math.sin(frame * 0.02) * live.breathe

      ctx.clearRect(0, 0, W, H)

      // ── Ambient core glow ──────────────────────────────────────────────────
      const corePulse = 0.6 + Math.sin(frame * 0.05) * 0.4 * live.coreP + live.coreP * 0.3
      const glowR = R * (1.7 + corePulse * 0.5)
      const gg = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR)
      gg.addColorStop(0,    `hsla(${hue + 15}, 100%, 65%, ${0.22 * corePulse})`)
      gg.addColorStop(0.35, `hsla(${hue}, 100%, 50%, ${0.08 * corePulse})`)
      gg.addColorStop(1,    'transparent')
      ctx.fillStyle = gg
      ctx.fillRect(0, 0, W, H)

      // ── Rotate + project all nodes ───────────────────────────────────────────
      const cosY = Math.cos(rotY), sinY = Math.sin(rotY)
      const cosX = Math.cos(rotX), sinX = Math.sin(rotX)
      const FOV = 3.2

      for (const n of nodes) {
        // turbulence wobble around base position
        const w = live.turb
        const tx = n.bx + Math.sin(frame * 0.02 * n.freq + n.phase) * w * 0.18
        const ty = n.by + Math.cos(frame * 0.02 * n.freq + n.phase * 1.3) * w * 0.18
        const tz = n.bz + Math.sin(frame * 0.018 * n.freq + n.phase * 0.7) * w * 0.18

        // scale by breathing
        let X = tx * breath, Y = ty * breath, Z = tz * breath

        // rotate around Y
        let x1 = X * cosY - Z * sinY
        let z1 = X * sinY + Z * cosY
        // rotate around X
        let y1 = Y * cosX - z1 * sinX
        let z2 = Y * sinX + z1 * cosX

        const persp = FOV / (FOV + z2)
        n.x = x1; n.y = y1; n.z = z2
        n.scale = persp
        n.sx = cx + x1 * R * persp
        n.sy = cy + y1 * R * persp
      }

      // ── Edges (depth-sorted alpha) ────────────────────────────────────────
      for (const [i, j] of edges) {
        const a = nodes[i], b = nodes[j]
        const depth = (a.scale + b.scale) / 2
        const flick = Math.sin(frame * 0.05 + a.phase) * 0.5 + 0.5
        const alpha = Math.max(0, (depth - 0.55)) * 0.5 * (0.4 + flick * 0.6)
        if (alpha <= 0.01) continue
        ctx.strokeStyle = `hsla(${hue + flick * 30}, 100%, 62%, ${alpha})`
        ctx.lineWidth = depth * 0.8
        ctx.beginPath()
        ctx.moveTo(a.sx, a.sy)
        ctx.lineTo(b.sx, b.sy)
        ctx.stroke()
      }

      // ── Nodes (sorted back-to-front) ──────────────────────────────────────
      const order = nodes.map((_, i) => i).sort((p, q) => nodes[p].z - nodes[q].z)
      for (const i of order) {
        const n = nodes[i]
        const depth = n.scale
        const tw = Math.sin(frame * 0.04 * n.speed + n.phase) * 0.5 + 0.5
        const br = (0.35 + depth * 0.65)
        const rad = n.r * depth * 1.6
        // halo
        const hg = ctx.createRadialGradient(n.sx, n.sy, 0, n.sx, n.sy, rad * 4)
        hg.addColorStop(0, `hsla(${hue + 25}, 100%, 78%, ${(0.35 + tw * 0.5) * br})`)
        hg.addColorStop(1, 'transparent')
        ctx.fillStyle = hg
        ctx.beginPath(); ctx.arc(n.sx, n.sy, rad * 4, 0, Math.PI * 2); ctx.fill()
        // core dot
        ctx.fillStyle = `hsla(${hue + 40}, 100%, 92%, ${(0.6 + tw * 0.4) * br})`
        ctx.beginPath(); ctx.arc(n.sx, n.sy, rad, 0, Math.PI * 2); ctx.fill()
      }

      // ── Synapse pulses travelling along edges ─────────────────────────────
      if (Math.random() < live.pulseRate) spawnPulse()
      for (let p = pulses.length - 1; p >= 0; p--) {
        const pulse = pulses[p]
        pulse.t += pulse.speed
        const seg = Math.floor(pulse.t)
        if (seg >= pulse.path.length - 1) { pulses.splice(p, 1); continue }
        const a = nodes[pulse.path[seg]]
        const b = nodes[pulse.path[seg + 1]]
        const f = pulse.t - seg
        const px = a.sx + (b.sx - a.sx) * f
        const py = a.sy + (b.sy - a.sy) * f
        const depth = a.scale
        const pr = 2.2 * depth
        const pg = ctx.createRadialGradient(px, py, 0, px, py, pr * 5)
        pg.addColorStop(0, `hsla(${hue + 50}, 100%, 95%, 0.95)`)
        pg.addColorStop(0.4, `hsla(${hue + 30}, 100%, 70%, 0.5)`)
        pg.addColorStop(1, 'transparent')
        ctx.fillStyle = pg
        ctx.beginPath(); ctx.arc(px, py, pr * 5, 0, Math.PI * 2); ctx.fill()
      }

      // ── Bright central core ───────────────────────────────────────────────
      const ccR = R * (0.16 + corePulse * 0.06)
      const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, ccR * 3)
      cg.addColorStop(0,   `hsla(${hue + 30}, 100%, 96%, ${0.5 + corePulse * 0.4})`)
      cg.addColorStop(0.4, `hsla(${hue + 10}, 100%, 70%, ${0.25 + corePulse * 0.2})`)
      cg.addColorStop(1,   'transparent')
      ctx.fillStyle = cg
      ctx.beginPath(); ctx.arc(cx, cy, ccR * 3, 0, Math.PI * 2); ctx.fill()

      animId = requestAnimationFrame(draw)
    }
    draw()

    return () => { cancelAnimationFrame(animId); ro.disconnect() }
  }, [])

  return (
    <div ref={wrapRef} className={`brain-stage ${status}`}>
      <canvas ref={canvasRef} className="brain-canvas" />
    </div>
  )
}
