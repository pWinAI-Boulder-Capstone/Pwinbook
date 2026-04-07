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
 * Assigns each spoken word a time slice proportional to its character weight
 * so longer words get slightly more time. Total spans [0, duration].
 * (No real word timestamps from TTS — this approximates alignment.)
 */
export function buildWordTimings(
  entries: TranscriptEntry[],
  durationSeconds: number
): WordTiming[] {
  type Acc = {
    globalIndex: number
    lineIndex: number
    weight: number
  }
  const weighted: Acc[] = []
  let gi = 0

  entries.forEach((entry, lineIndex) => {
    const text = (entry.dialogue ?? entry.text ?? '').trim()
    if (!text) return
    const parts = text.split(/\s+/).filter(Boolean)
    for (const w of parts) {
      const weight = Math.max(1.5, w.length * 0.35 + 1)
      weighted.push({ globalIndex: gi++, lineIndex, weight })
    }
  })

  const totalW = weighted.reduce((s, x) => s + x.weight, 0)
  if (weighted.length === 0 || totalW <= 0 || !Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    return []
  }

  let t = 0
  const out: WordTiming[] = weighted.map((x) => {
    const len = durationSeconds * (x.weight / totalW)
    const start = t
    const end = t + len
    t = end
    return {
      globalIndex: x.globalIndex,
      lineIndex: x.lineIndex,
      start,
      end,
    }
  })
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
