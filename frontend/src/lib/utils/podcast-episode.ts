export type OutlineSegment = {
  name?: string
  description?: string
  size?: string
}

export type TranscriptEntry = {
  speaker?: string
  dialogue?: string
  text?: string
  citation?: string
  pacing_cue?: string
  pronunciation_notes?: string
}

export function extractOutlineSegments(outline: unknown): OutlineSegment[] {
  if (outline && typeof outline === 'object' && 'segments' in outline) {
    const data = outline as { segments?: OutlineSegment[] }
    if (Array.isArray(data.segments)) {
      return data.segments
    }
  }
  return []
}

export function extractTranscriptEntries(transcript: unknown): TranscriptEntry[] {
  if (transcript && typeof transcript === 'object') {
    const data = transcript as Record<string, unknown>
    const entries = data.transcript ?? data.dialogue
    if (Array.isArray(entries)) {
      return entries as TranscriptEntry[]
    }
  }
  return []
}

export function getTranscriptMeta(transcript: unknown): {
  audioError?: string
  audioSkipped?: string
  durationInfo?: {
    valid?: boolean
    duration_minutes?: number
    target_range_minutes?: [number, number]
    warning?: string
  }
} {
  if (transcript && typeof transcript === 'object') {
    const data = transcript as Record<string, unknown>
    return {
      audioError: data.audio_error as string | undefined,
      audioSkipped: data.audio_skipped as string | undefined,
      durationInfo: data.duration_info as
        | {
            valid?: boolean
            duration_minutes?: number
            target_range_minutes?: [number, number]
            warning?: string
          }
        | undefined,
    }
  }
  return {}
}
