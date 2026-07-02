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
// In dev, route through the Vite proxy prefixes (see vite.config.ts). Callers do
// `${API_BASE}/stats` etc., so the base must carry the /api prefix or the request
// bypasses the proxy and 404s — which previously left four panels silently empty.
export const API_BASE = prod?.apiBase ?? '/api'       // dev → Vite proxy → :8767
// SearchPanel already includes the `/searxng` path segment itself, so the dev
// base stays empty (the request `/searxng/search` matches the Vite proxy rule).
export const SEARXNG  = prod?.searxng ?? ''
