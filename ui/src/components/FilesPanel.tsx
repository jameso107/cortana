import { useState } from 'react'

interface FileEntry { name: string; size: string; isDir: boolean }

// Calls the Cortana backend file API (ws not ready yet — uses placeholder)
async function listDir(path: string): Promise<FileEntry[]> {
  try {
    const res = await fetch(`http://localhost:8765/files?path=${encodeURIComponent(path)}`)
    return await res.json()
  } catch {
    return []
  }
}


export default function FilesPanel() {
  const [path, setPath] = useState('~')
  const [inputPath, setInputPath] = useState('~')
  const [entries, setEntries] = useState<FileEntry[]>([])
  const [loading, setLoading] = useState(false)

  const navigate = async (p: string) => {
    setPath(p); setInputPath(p); setLoading(true)
    const result = await listDir(p)
    setEntries(result)
    setLoading(false)
  }

  const go = () => navigate(inputPath)

  const click = (e: FileEntry) => {
    if (e.isDir) navigate(path.replace(/\/$/, '') + '/' + e.name)
  }

  return (
    <div className="files-panel">
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
      <div className="files-list">
        {loading && <div style={{ color: 'var(--text-dim)', padding: 12, fontSize: 12 }}>Loading…</div>}
        {!loading && entries.length === 0 && (
          <div style={{ color: 'var(--text-dim)', padding: 12, fontSize: 12 }}>
            Navigate to a directory — click Go or press Enter.
            <br /><br />
            <span style={{ fontSize: 10 }}>Requires Cortana daemon running on port 8765.</span>
          </div>
        )}
        {path !== '~' && path !== '/' && (
          <div className="file-item dir" onClick={() => navigate(path.split('/').slice(0, -1).join('/') || '/')}>
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
    </div>
  )
}
