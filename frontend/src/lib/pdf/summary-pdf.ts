function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}

function markdownToSimpleHtml(markdown: string): string {
  const lines = markdown.split('\n')
  const html: string[] = []
  let inList = false

  const closeList = () => {
    if (inList) {
      html.push('</ul>')
      inList = false
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) {
      closeList()
      continue
    }

    if (line.startsWith('### ')) {
      closeList()
      html.push(`<h3>${escapeHtml(line.slice(4))}</h3>`)
      continue
    }

    if (line.startsWith('## ')) {
      closeList()
      html.push(`<h2>${escapeHtml(line.slice(3))}</h2>`)
      continue
    }

    if (line.startsWith('- ')) {
      if (!inList) {
        html.push('<ul>')
        inList = true
      }
      html.push(`<li>${escapeHtml(line.slice(2))}</li>`)
      continue
    }

    closeList()
    html.push(`<p>${escapeHtml(line)}</p>`)
  }

  closeList()
  return html.join('\n')
}

export function exportSummaryPdf(title: string, markdown: string): void {
  if (typeof window === 'undefined') return

  const iframe = document.createElement('iframe')
  iframe.style.position = 'fixed'
  iframe.style.right = '0'
  iframe.style.bottom = '0'
  iframe.style.width = '0'
  iframe.style.height = '0'
  iframe.style.border = '0'
  iframe.setAttribute('aria-hidden', 'true')
  document.body.appendChild(iframe)

  const doc = iframe.contentWindow?.document
  if (!doc) {
    document.body.removeChild(iframe)
    return
  }

  const bodyHtml = markdownToSimpleHtml(markdown)
  doc.open()
  doc.write(`<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>${escapeHtml(title)}</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 32px; }
      h2 { margin-top: 24px; }
      h3 { margin-top: 18px; }
      p { line-height: 1.5; margin: 8px 0; }
      ul { margin: 8px 0 12px 20px; }
    </style>
  </head>
  <body>
    <h1>${escapeHtml(title)}</h1>
    ${bodyHtml}
  </body>
</html>`)
  doc.close()

  iframe.onload = () => {
    iframe.contentWindow?.focus()
    iframe.contentWindow?.print()
    setTimeout(() => {
      document.body.removeChild(iframe)
    }, 1000)
  }
}
