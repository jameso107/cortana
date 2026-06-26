// Runtime config injected by the aiohttp server (production).
// Falls back to Vite proxy paths in dev mode.
declare global {
  interface Window {
    CORTANA_CONFIG?: {
      wsChat: string
      wsTerm: string
      apiBase: string
      searxng: string
    }
  }
}

const prod = window.CORTANA_CONFIG

export const WS_CHAT  = prod?.wsChat  ?? 'ws://localhost:8765'
export const WS_TERM  = prod?.wsTerm  ?? 'ws://localhost:8766'
export const API_BASE = prod?.apiBase ?? ''          // empty = use Vite proxy (/api/*)
export const SEARXNG  = prod?.searxng ?? ''          // empty = use Vite proxy (/searxng/*)
