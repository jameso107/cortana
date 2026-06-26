import { useState } from 'react'

interface Note { title: string; body: string }

export default function NotesPanel() {
  const [notes, setNotes] = useState<Note[]>(() => {
    try { return JSON.parse(localStorage.getItem('cortana-notes') ?? '[]') } catch { return [] }
  })
  const [active, setActive] = useState<number | null>(null)
  const [title, setTitle]   = useState('')
  const [body, setBody]     = useState('')

  const save = () => {
    const updated = active === null
      ? [...notes, { title: title || 'Untitled', body }]
      : notes.map((n, i) => i === active ? { title: title || n.title, body } : n)
    setNotes(updated)
    localStorage.setItem('cortana-notes', JSON.stringify(updated))
    if (active === null) setActive(updated.length - 1)
  }

  const open = (i: number) => {
    setActive(i)
    setTitle(notes[i].title)
    setBody(notes[i].body)
  }

  const newNote = () => { setActive(null); setTitle(''); setBody('') }

  return (
    <div className="notes-panel">
      <div className="notes-sidebar">
        <button className="notes-new-btn" onClick={newNote}>+ New Note</button>
        {notes.map((n, i) => (
          <div key={i} className={`note-item ${active === i ? 'active' : ''}`} onClick={() => open(i)}>
            {n.title}
          </div>
        ))}
      </div>
      <div className="notes-editor">
        <input
          className="notes-title-input"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="Note title…"
        />
        <textarea
          className="notes-body"
          value={body}
          onChange={e => setBody(e.target.value)}
          placeholder="Start writing…"
        />
        <button className="notes-save-btn" onClick={save}>Save</button>
      </div>
    </div>
  )
}
