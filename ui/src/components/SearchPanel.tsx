import { useState, useRef } from 'react'

interface Result {
  title: string
  url: string
  content: string
}

export default function SearchPanel() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Result[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const search = async () => {
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setError('')
    setResults([])
    try {
      const res = await fetch(
        `http://localhost:8888/search?q=${encodeURIComponent(q)}&format=json`,
      )
      if (!res.ok) throw new Error(`SearXNG returned ${res.status}`)
      const data = await res.json()
      setResults(data.results?.slice(0, 12) ?? [])
    } catch (e: unknown) {
      setError(
        'Search unavailable. Start SearXNG: docker compose up -d'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="search-panel">
      <div className="search-bar">
        <input
          ref={inputRef}
          className="search-input"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && search()}
          placeholder="Search the web privately…"
          autoFocus
        />
        <button className="search-btn" onClick={search} disabled={loading}>
          {loading ? '…' : 'Search'}
        </button>
      </div>

      {error && <div className="search-empty" style={{ color: '#ff6644' }}>{error}</div>}

      {!loading && !error && results.length === 0 && query && (
        <div className="search-empty">No results found.</div>
      )}

      {results.map((r, i) => (
        <div key={i} className="search-result">
          <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a>
          <div className="search-result-url">{r.url}</div>
          {r.content && <div className="search-result-desc">{r.content}</div>}
        </div>
      ))}
    </div>
  )
}
