/**
 * Full PTY terminal powered by xterm.js, connected to the
 * Cortana terminal WebSocket server on ws://localhost:8766.
 */
import { useEffect, useRef } from 'react'
import { WS_TERM } from '../config'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'

export default function TerminalPanel() {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const wsRef   = useRef<WebSocket | null>(null)
  const fitRef  = useRef<FitAddon | null>(null)

  useEffect(() => {
    if (!containerRef.current || termRef.current) return

    const term = new Terminal({
      theme: {
        background:  '#000000',
        foreground:  '#b8e8ff',
        cursor:      '#00d4ff',
        selectionBackground: '#00d4ff33',
        black:       '#000408',
        blue:        '#0050ff',
        cyan:        '#00d4ff',
        green:       '#00ff88',
        yellow:      '#ffcc00',
        red:         '#ff4455',
        white:       '#c8e8ff',
        brightCyan:  '#80f0ff',
        brightBlue:  '#4488ff',
      },
      fontFamily: '"Courier New", monospace',
      fontSize: 13,
      lineHeight: 1.4,
      cursorBlink: true,
      cursorStyle: 'block',
      scrollback: 5000,
    })
    const fit   = new FitAddon()
    const links = new WebLinksAddon()
    term.loadAddon(fit)
    term.loadAddon(links)
    term.open(containerRef.current)
    fit.fit()
    termRef.current = term
    fitRef.current  = fit

    // Connect to PTY backend
    const connect = () => {
      const ws = new WebSocket(WS_TERM)
      wsRef.current = ws
      ws.onopen = () => {
        term.write('\r\n\x1b[36m  Cortana Terminal — connected.\x1b[0m\r\n\r\n')
        // Send initial resize
        const dims = fit.proposeDimensions()
        if (dims) ws.send(`\x1b[8;${dims.rows};${dims.cols}t`)
      }
      ws.onmessage = (e) => term.write(e.data)
      ws.onclose   = () => {
        term.write('\r\n\x1b[33m  [ Connection closed — retrying… ]\x1b[0m\r\n')
        setTimeout(connect, 3000)
      }
      ws.onerror   = () => ws.close()
    }
    connect()

    // Keyboard → PTY
    term.onData(data => wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.send(data))

    // Resize observer
    const ro = new ResizeObserver(() => {
      fit.fit()
      const dims = fitRef.current?.proposeDimensions()
      if (dims && wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(`\x1b[8;${dims.rows};${dims.cols}t`)
      }
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      wsRef.current?.close()
      term.dispose()
      termRef.current = null
    }
  }, [])

  return <div ref={containerRef} className="terminal-panel" />
}
