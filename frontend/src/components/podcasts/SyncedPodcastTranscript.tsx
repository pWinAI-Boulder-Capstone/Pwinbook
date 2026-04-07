'use client'

import { useCallback, useEffect, useMemo, useRef } from 'react'

import { cn } from '@/lib/utils'
import type { TranscriptEntry } from '@/lib/utils/podcast-episode'
import {
  buildLineTimings,
  buildWordTimings,
  getActiveLineIndex,
  type LineTiming,
} from '@/lib/utils/podcast-transcript-sync'

interface SyncedPodcastTranscriptProps {
  entries: TranscriptEntry[]
  currentTime: number
  duration: number
  /** When false, highlight stays frozen. */
  hasAudio: boolean
  /** Seek to a specific time (seconds). */
  onSeek?: (timeSeconds: number) => void
}

/** Stable color per speaker so each voice gets a consistent accent. */
const SPEAKER_COLORS = [
  'hsl(221, 83%, 53%)',   // blue
  'hsl(262, 83%, 58%)',   // purple
  'hsl(142, 71%, 45%)',   // green
  'hsl(24, 95%, 53%)',    // orange
  'hsl(346, 77%, 50%)',   // rose
  'hsl(187, 85%, 43%)',   // cyan
]

function getSpeakerColor(speaker: string, speakerList: string[]): string {
  const idx = speakerList.indexOf(speaker)
  return SPEAKER_COLORS[idx >= 0 ? idx % SPEAKER_COLORS.length : 0]
}

export function SyncedPodcastTranscript({
  entries,
  currentTime,
  duration,
  hasAudio,
  onSeek,
}: SyncedPodcastTranscriptProps) {
  const wordTimings = useMemo(
    () => buildWordTimings(entries, duration),
    [entries, duration]
  )

  const lineTimings = useMemo(
    () => buildLineTimings(wordTimings),
    [wordTimings]
  )

  const activeLineIdx = useMemo(() => {
    if (!hasAudio || lineTimings.length === 0 || duration <= 0) return -1
    return getActiveLineIndex(currentTime, lineTimings)
  }, [hasAudio, currentTime, duration, lineTimings])

  const speakers = useMemo(
    () => [...new Set(entries.map((e) => e.speaker ?? 'Speaker'))],
    [entries]
  )

  const lines = useMemo(
    () =>
      entries.map((entry, lineIndex) => ({
        lineIndex,
        speaker: entry.speaker ?? 'Speaker',
        text: (entry.dialogue ?? entry.text ?? '').trim(),
        citation: entry.citation,
      })),
    [entries]
  )

  // Build a lineIndex→LineTiming map for click-to-seek
  const lineTimingMap = useMemo(() => {
    const m = new Map<number, LineTiming>()
    for (const lt of lineTimings) {
      m.set(lt.lineIndex, lt)
    }
    return m
  }, [lineTimings])

  const handleLineClick = useCallback(
    (lineIndex: number) => {
      if (!onSeek) return
      const lt = lineTimingMap.get(lineIndex)
      if (lt) onSeek(lt.start)
    },
    [onSeek, lineTimingMap]
  )

  // Auto-scroll: keep active line centered
  const containerRef = useRef<HTMLDivElement>(null)
  const lastScrolledLine = useRef(-1)

  useEffect(() => {
    lastScrolledLine.current = -1
  }, [entries, duration])

  useEffect(() => {
    if (activeLineIdx < 0) return
    if (activeLineIdx === lastScrolledLine.current) return
    lastScrolledLine.current = activeLineIdx
    const el = containerRef.current?.querySelector<HTMLElement>(
      `[data-illuminate-line="${activeLineIdx}"]`
    )
    if (!el) return
    el.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
  }, [activeLineIdx])

  return (
    <div ref={containerRef} className="flex flex-col gap-1 px-2 py-6 sm:px-4 md:px-8">
      {lines.map((line) => {
        const isActive = hasAudio && line.lineIndex === activeLineIdx
        const isPast =
          hasAudio &&
          activeLineIdx >= 0 &&
          line.lineIndex < activeLineIdx
        const isFuture =
          hasAudio &&
          activeLineIdx >= 0 &&
          line.lineIndex > activeLineIdx
        const speakerColor = getSpeakerColor(line.speaker, speakers)

        return (
          <div
            key={line.lineIndex}
            data-illuminate-line={line.lineIndex}
            onClick={() => handleLineClick(line.lineIndex)}
            className={cn(
              'group relative rounded-xl px-4 py-3 transition-all duration-300 ease-out',
              onSeek && 'cursor-pointer',
              isActive
                ? 'bg-primary/10 scale-[1.01]'
                : isPast
                  ? 'opacity-50'
                  : isFuture
                    ? 'opacity-40'
                    : '',
              !hasAudio && 'opacity-100',
            )}
            style={
              isActive
                ? { borderLeft: `3px solid ${speakerColor}` }
                : { borderLeft: '3px solid transparent' }
            }
          >
            {/* Speaker name */}
            <p
              className={cn(
                'text-xs font-semibold uppercase tracking-wider mb-1 transition-colors duration-300',
                isActive ? 'opacity-100' : 'opacity-70',
              )}
              style={{ color: speakerColor }}
            >
              {line.speaker}
            </p>

            {/* Dialogue text */}
            <p
              className={cn(
                'text-[15px] leading-relaxed transition-colors duration-300',
                isActive
                  ? 'text-foreground font-medium'
                  : 'text-foreground/70',
              )}
            >
              {line.text || <span className="text-muted-foreground">—</span>}
            </p>

            {/* Citation */}
            {line.citation ? (
              <p className="mt-1.5 text-xs text-muted-foreground/60 italic">
                {line.citation}
              </p>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
