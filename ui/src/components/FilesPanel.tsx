import { useState, useEffect } from 'react'
import { API_BASE } from '../config'

interface FileEntry {
  name: string
  size: string
  isDir: boolean
  path: string
}

async function listDir(path: string): Promise<FileEntry[]> {
  try {
    const res = await fetch(`${API_BASE}/files?path=${encodeURIComponent(path)}`)
    if (!res.ok) return []
    return await res.json()
  } catch {
    return []
  }
}

async function readFile(path: string): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/file?path=${encodeURIComponent(path)}`)
    if (!res.ok) return '[ Permission denied or binary file ]'
    const data = await res.json()
    return data.content ?? '[ Empty ]'
  } catch {
    return '[ Failed to read file ]'
  }
}

export default function FilesPanel() {
  const [path, setPath]           = useState(window.location.hostname === 'localhost' ? '/Users' : '~')
  const [inputPath, setInputPath] = useState('/Users')
  const [entries, setEntries]     = useState<FileEntry[]>([])
  const [loading, setLoading]     = useState(false)
  const [preview, setPreview]     = useState<{ path: string; content: string } | null>(null)
  const [error, setError]         = useState('')

  const navigate = async (p: string) => {
    setPreview(null)
    setError('')
    setPath(p)
    setInputPath(p)
    setLoading(true)
    const result = await listDir(p)
    if (result.length === 0) setError('Empty or inaccessible directory.')
    setEntries(result)
    setLoading(false)
  }

  useEffect(() => { navigate('/Users') }, [])

  const go = () => navigate(inputPath)

  const click = async (e: FileEntry) => {
    if (e.isDir) {
      navigate(e.path)
    } else {
      setPreview({ path: e.path, content: '…' })
      const content = await readFile(e.path)
      setPreview({ path: e.path, content })
    }
  }

  const parent = () => {
    const parts = path.split('/').filter(Boolean)
    parts.pop()
    navigate('/' + parts.join('/') || '/')
  }

  return (
    <div className="files-panel">
      {/* Path bar */}
      <div className="files-path-bar">
        <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>PATH</span>
        <input
          className="files-path"
          value={inputPath}
          onChange={e => setInputPath(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && go()}
        />
        <button className="files-go-btn" onClick={go}>Go</button>
      </div>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* File list */}
        <div className="files-list" style={{ flex: preview ? '0 0 45%' : '1', overflowY: 'auto' }}>
          {loading && <div style={{ color: 'var(--text-dim)', padding: 12, fontSize: 12 }}>Loading…</div>}
          {!loading && error && <div style={{ color: 'var(--accent-warn)', padding: 12, fontSize: 12 }}>{error}</div>}

          {path !== '/' && (
            <div className="file-item dir" onClick={parent}>
              <span className="file-icon">↑</span> ..
            </div>
          )}

          {entries.map((e, i) => (
            <div key={i} className={`file-item ${e.isDir ? 'dir' : ''}`} onClick={() => click(e)}>
              <span className="file-icon">{e.isDir ? '▶' : '◻'}</span>
              {e.name}
              {!e.isDir && <span className="file-size">{e.size}</span>}
            </div>
          ))}
        </div>

        {/* File preview */}
        {preview && (
          <div className="files-preview">
            <div className="files-preview-header">
              <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{preview.path}</span>
              <button className="files-go-btn" onClick={() => setPreview(null)}>✕</button>
            </div>
            <pre className="files-preview-content">{preview.content}</pre>
          </div>
        )}
      </div>
    </div>
  )
}
