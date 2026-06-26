// Minimal, dependency-free, XSS-safe markdown → HTML.
// All text is HTML-escaped FIRST, then a small set of markdown constructs are
// re-introduced as known-safe tags. No raw HTML from the model is ever emitted.

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function inline(s: string): string {
  // s is already HTML-escaped.
  return s
    // inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // bold
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    // italic
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    // links [text](url) — only http(s)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
}

export function renderMarkdown(src: string): string {
  const lines = src.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let i = 0
  let listType: 'ul' | 'ol' | null = null

  const closeList = () => {
    if (listType) { out.push(`</${listType}>`); listType = null }
  }

  while (i < lines.length) {
    const line = lines[i]

    // fenced code block
    const fence = line.match(/^```(\w*)\s*$/)
    if (fence) {
      closeList()
      const lang = fence[1] || ''
      const buf: string[] = []
      i++
      while (i < lines.length && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++ }
      i++ // skip closing fence
      const code = esc(buf.join('\n'))
      out.push(
        `<div class="md-code"><div class="md-code-bar">` +
        `<span class="md-code-lang">${esc(lang) || 'code'}</span>` +
        `<button class="md-copy" data-code="${encodeURIComponent(buf.join('\n'))}">copy</button>` +
        `</div><pre><code>${code}</code></pre></div>`
      )
      continue
    }

    // headings
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    if (h) {
      closeList()
      const lvl = h[1].length
      out.push(`<h${lvl + 2} class="md-h">${inline(esc(h[2]))}</h${lvl + 2}>`)
      i++; continue
    }

    // unordered list
    if (/^\s*[-*]\s+/.test(line)) {
      if (listType !== 'ul') { closeList(); out.push('<ul class="md-ul">'); listType = 'ul' }
      out.push(`<li>${inline(esc(line.replace(/^\s*[-*]\s+/, '')))}</li>`)
      i++; continue
    }
    // ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      if (listType !== 'ol') { closeList(); out.push('<ol class="md-ol">'); listType = 'ol' }
      out.push(`<li>${inline(esc(line.replace(/^\s*\d+\.\s+/, '')))}</li>`)
      i++; continue
    }

    // blank line
    if (line.trim() === '') { closeList(); i++; continue }

    // paragraph
    closeList()
    out.push(`<p class="md-p">${inline(esc(line))}</p>`)
    i++
  }
  closeList()
  return out.join('\n')
}
