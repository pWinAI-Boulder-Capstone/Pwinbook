import type { TranscriptEntry } from '@/lib/utils/podcast-episode'

export type WordTiming = {
  globalIndex: number
  lineIndex: number
  start: number
  end: number
}

export type LineTiming = {
  lineIndex: number
  start: number
  end: number
}

/**
 * Assigns each spoken word a time slice proportional to its character weight,
 * with pause-weight gaps between lines to model the inter-clip silence
 * that the TTS pipeline inserts (200ms same-speaker, 500ms speaker-change).
 * All weights share the same proportional pool so the total always
 * spans exactly [0, durationSeconds] — no fragile subtraction.
 */

// Average word duration at ~150 wpm ≈ 0.4s.  We convert pause durations
// into equivalent "word weights" so they compete proportionally.
const AVG_WORD_WEIGHT = 2.0           // mean of  max(1.5, len*0.35+1)  for typical words
const AVG_WORD_DURATION_S = 0.4       // ~150 wpm
const WEIGHT_PER_SECOND = AVG_WORD_WEIGHT / AVG_WORD_DURATION_S  // ≈ 5.0

const SAME_SPEAKER_PAUSE_WEIGHT = 0.2 * WEIGHT_PER_SECOND   // 1.0
const SPEAKER_CHANGE_PAUSE_WEIGHT = 0.5 * WEIGHT_PER_SECOND // 2.5

type WeightedItem = {
  kind: 'word' | 'pause'
  globalIndex: number   // -1 for pauses
  lineIndex: number     // line the word belongs to, or next line for pauses
  weight: number
}

export function buildWordTimings(
  entries: TranscriptEntry[],
  durationSeconds: number
): WordTiming[] {
  if (!entries.length || !Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    return []
  }

  // Build interleaved list of words + pause gaps
  const items: WeightedItem[] = []
  let gi = 0
  let lastLineWithWords = -1

  entries.forEach((entry, lineIndex) => {
    const text = (entry.dialogue ?? entry.text ?? '').trim()
    if (!text) return
    const words = text.split(/\s+/).filter(Boolean)
    if (words.length === 0) return

    // Insert a pause gap before this line (if not the first line with words)
    if (lastLineWithWords >= 0) {
      const prevSpeaker = entries[lastLineWithWords]?.speaker ?? ''
      const currSpeaker = entry.speaker ?? ''
      const pw = prevSpeaker === currSpeaker
        ? SAME_SPEAKER_PAUSE_WEIGHT
        : SPEAKER_CHANGE_PAUSE_WEIGHT
      items.push({ kind: 'pause', globalIndex: -1, lineIndex, weight: pw })
    }
    lastLineWithWords = lineIndex

    for (const w of words) {
      const weight = Math.max(1.5, w.length * 0.35 + 1)
      items.push({ kind: 'word', globalIndex: gi++, lineIndex, weight })
    }
  })

  const totalW = items.reduce((s, x) => s + x.weight, 0)
  if (items.length === 0 || totalW <= 0) return []

  // Distribute durationSeconds proportionally across all items
  let t = 0
  const out: WordTiming[] = []
  for (const item of items) {
    const len = durationSeconds * (item.weight / totalW)
    if (item.kind === 'word') {
      out.push({
        globalIndex: item.globalIndex,
        lineIndex: item.lineIndex,
        start: t,
        end: t + len,
      })
    }
    // For pauses, we just advance t (no WordTiming emitted)
    t += len
  }

  // Snap last word to exact duration
  if (out.length > 0) {
    out[out.length - 1] = {
      ...out[out.length - 1],
      end: durationSeconds,
    }
  }
  return out
}

/**
 * Builds line-level timing by aggregating word timings per line.
 * Each line spans from its first word's start to its last word's end.
 */
export function buildLineTimings(wordTimings: WordTiming[]): LineTiming[] {
  if (wordTimings.length === 0) return []

  const lineMap = new Map<number, { start: number; end: number }>()
  for (const wt of wordTimings) {
    const existing = lineMap.get(wt.lineIndex)
    if (!existing) {
      lineMap.set(wt.lineIndex, { start: wt.start, end: wt.end })
    } else {
      existing.end = wt.end
    }
  }

  const out: LineTiming[] = []
  for (const [lineIndex, { start, end }] of lineMap) {
    out.push({ lineIndex, start, end })
  }
  return out.sort((a, b) => a.start - b.start)
}

/** Which line (lineIndex) should be highlighted at currentTime. */
export function getActiveLineIndex(
  currentTime: number,
  lineTimings: LineTiming[]
): number {
  if (lineTimings.length === 0) return -1
  const t = Math.max(0, currentTime)
  if (t < lineTimings[0].start) return lineTimings[0].lineIndex
  const last = lineTimings[lineTimings.length - 1]
  if (t >= last.end) return last.lineIndex
  for (let i = 0; i < lineTimings.length; i++) {
    const lt = lineTimings[i]
    if (t >= lt.start && t < lt.end) return lt.lineIndex
  }
  for (let i = lineTimings.length - 1; i >= 0; i--) {
    if (t >= lineTimings[i].start) return lineTimings[i].lineIndex
  }
  return lineTimings[0].lineIndex
}

/** Which word (global index) should be highlighted at currentTime. */
export function getActiveWordGlobalIndex(
  currentTime: number,
  timings: WordTiming[]
): number {
  if (timings.length === 0) return -1
  const t = Math.max(0, currentTime)
  if (t < timings[0].start) return timings[0].globalIndex
  const last = timings[timings.length - 1]
  if (t >= last.end) return last.globalIndex
  for (let i = 0; i < timings.length; i++) {
    const w = timings[i]
    if (t >= w.start && t < w.end) return w.globalIndex
  }
  for (let i = timings.length - 1; i >= 0; i--) {
    if (t >= timings[i].start) return timings[i].globalIndex
  }
  return timings[0].globalIndex
}

export function tokenizeLine(text: string): string[] {
  return text.trim().split(/\s+/).filter(Boolean)
}
