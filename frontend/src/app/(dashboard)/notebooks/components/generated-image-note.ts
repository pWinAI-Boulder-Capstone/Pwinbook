import { NoteResponse } from '@/lib/types/api'

export const GENERATED_IMAGE_NOTE_MARKER = '<!-- generated-image -->'
export const GENERATED_IMAGE_TITLE_PREFIX = 'Generated Image'

export function isGeneratedImageNote(note: Pick<NoteResponse, 'note_type' | 'content' | 'title'>): boolean {
  const title = (note.title || '').trim().toLowerCase()
  if (title.startsWith(GENERATED_IMAGE_TITLE_PREFIX.toLowerCase())) {
    return true
  }

  const content = note.content || ''
  if (content.includes(GENERATED_IMAGE_NOTE_MARKER)) {
    return true
  }

  return content.includes('![Generated Summary Image](')
}

export function extractGeneratedImageDataUrl(content?: string | null): string | null {
  if (!content) return null
  const markdownMatch = content.match(/!\[[^\]]*\]\((data:image\/[^)]+)\)/)
  if (markdownMatch?.[1]) return markdownMatch[1]
  const rawMatch = content.match(/data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+/)
  return rawMatch?.[0] ?? null
}

export function extractGeneratedImagePrompt(content?: string | null): string {
  if (!content) return ''
  const promptBlock = content.match(/## Prompt\s*```text\s*([\s\S]*?)\s*```/i)
  if (promptBlock?.[1]) return promptBlock[1].trim()
  return ''
}

export function buildGeneratedImageNoteContent(
  imageDataUrl: string,
  prompt: string,
  summaryNoteId?: string
): string {
  return [
    GENERATED_IMAGE_NOTE_MARKER,
    '',
    `![Generated Summary Image](${imageDataUrl})`,
    '',
    '## Prompt',
    '',
    '```text',
    prompt,
    '```',
    '',
    summaryNoteId ? `Summary note: ${summaryNoteId}` : '',
  ].join('\n').trim()
}
